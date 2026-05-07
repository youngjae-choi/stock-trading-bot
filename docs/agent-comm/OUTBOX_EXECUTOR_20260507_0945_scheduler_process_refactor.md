# OUTBOX_EXECUTOR - 2026-05-07 09:45 KST - 스케줄 설정 프로세스 트리거 구조 변경

## 변경 파일 목록

- `backend/services/scheduler.py`
- `backend/services/db.py`
- `backend/services/kis/domestic/service.py`
- `backend/static/console.html`
- `docs/agent-comm/OUTBOX_EXECUTOR_20260507_0945_scheduler_process_refactor.md`

## 구현 요약

- scheduler 등록 구조를 개별 S1~S5 cron에서 `job_trade_preparation_pipeline` 단일 cron으로 변경했다.
  - `schedule_trade_prep_time` 기준으로 S1 -> S2 -> S3 -> S4 -> S5 -> S5-V -> S5-A를 순차 실행한다.
  - S1에서 명확한 휴장일(`closed`)이면 S2~S6 audit을 `skipped`로 남기고 후속 자동 단계를 막는다.
  - S1 거래일 판정이 `unknown`이면 `schedule_skip_today=false`로 저장하고 WARN 로그 후 S2~S5-A를 계속 진행한다.
- scheduler 등록 구조를 개별 S9/S10 cron에서 `job_postprocess_pipeline` 단일 cron으로 변경했다.
  - `schedule_postprocess_time` 기준으로 S9 당일 청산 -> S10 Review & Audit을 순차 실행한다.
- S6, S11, backup, us_watch 등록은 유지했다.
  - S7/S8은 기존처럼 별도 cron 없이 실시간/트리거 표시 구조를 유지했다.
- S5-V/S5-A는 외부 HTTP API를 호출하지 않고 내부 DB 상태 확인과 audit 기록으로 처리했다.
  - `/api/v1/daily-plan/activate` 호출 없음.
  - `/api/v1/decision/activate` 호출 없음.
- KIS 휴장일 조회를 `trading`, `closed`, `unknown` 3상태로 분리했다.
  - KIS 오류, 모의투자 미지원성 오류, 빈 응답, 알 수 없는 schema는 `unknown`이다.
  - `unknown`은 비거래일로 오판하지 않는다.
- Console Settings는 운영자가 프로세스 시작 시간 중심으로 보도록 변경했다.
  - 거래준비 프로세스 시작 시간
  - S6 Decision Engine 시간
  - S7 실시간 주문 실행
  - S8 실시간 Position Manager
  - 후처리 프로세스 시작 시간
  - S11 Learning Memory 시간
- Console Diagnostics의 S1~S5-A/S9~S10 설명에 각각 거래준비/후처리 프로세스 하위 단계임을 표시했다.

## 새 설정 키

- `schedule_trade_prep_time`
  - 기본값: `"07:45"`
  - 용도: S1~S5-A 거래준비 프로세스 시작 시간
- `schedule_postprocess_time`
  - 기본값: `"15:20"`
  - 용도: S9~S10 후처리 프로세스 시작 시간

## Legacy 설정 처리 방식

- 기존 `schedule_s1_time`~`schedule_s5a_time`, `schedule_s9_time`, `schedule_s10_time`은 삭제하지 않았다.
- DB 기본 설명과 기존 DB migration 설명을 `[legacy]`로 변경했다.
- scheduler 등록에는 S1~S5-A 개별 legacy 키를 사용하지 않는다.
- `schedule_postprocess_time`이 없고 legacy `schedule_s9_time`만 있는 기존 DB에서는 후처리 시간 fallback으로 `schedule_s9_time`을 사용한다.
- Console Settings에서는 legacy 개별 시간 키를 숨기고 새 프로세스 키를 우선 표시한다.

## 테스트 결과

- PASS: `.venv/bin/python -m compileall -q backend`
- PASS: `git diff --check`
- PASS: 외부 호출 없는 scheduler/settings/trading-day smoke
  - `trading/closed/unknown` 응답 파싱 확인
  - `unknown`이면 `schedule_skip_today=false`
  - `closed`이면 `schedule_skip_today=true`
  - scheduler job list에 `job_trade_preparation_pipeline`, `job_postprocess_pipeline`, `job_decision_engine_start`, `job_learning_memory`, `job_data_backup`, `job_us_market_watch` 등록 확인
  - S1~S5/S9/S10 개별 cron job 미등록 확인
  - 임시 DB에서 `schedule_trade_prep_time`, `schedule_postprocess_time` 기본값 및 legacy 설명 확인

## 남은 위험

- 실제 S1~S11 단계는 지시상 실행하지 않았다. 따라서 실제 장 운영 중 외부 KIS/LLM 호출 성공 여부는 미검증이다.
- S5 생성 함수가 현재 내부에서 자동 검증/활성화까지 수행한다. 새 S5-V/S5-A scheduler substep은 별도 활성화 API 호출이 아니라 생성 후 상태 확인/audit 역할이다.
- S9 job 내부 함수가 예외를 자체 catch하므로 `job_postprocess_pipeline`은 S9 내부 실패를 반환값으로 엄격히 구분하지 못한다. 로그에는 실패가 남는다.
- S1 토큰 갱신 실패 시에도 기존 동작처럼 서버는 계속 진행한다. 거래일 unknown 오판 방지는 적용됐지만, KIS 장애 상황에서 S3 등 후속 KIS 단계가 실패할 수 있다.

## Oracle 리뷰 포인트

- `job_trade_preparation_pipeline`이 S1 token refresh 실패를 계속 진행하는 정책이 운영 의도와 맞는지 확인 필요.
- S5-V/S5-A를 내부 상태 확인 audit으로 구현한 것이 PM의 “검증/활성화 확인” 의도에 맞는지 확인 필요.
- S9 내부 실패를 `job_postprocess_pipeline`에서 구조적으로 감지하도록 `job_eod_liquidation` 반환값을 확장할지 검토 필요.
- Console Diagnostics의 수동 실행 버튼은 기존 기능을 유지했다. 운영 UI에서 위험 버튼을 별도 권한/확인 모달로 제한할지 검토 필요.
