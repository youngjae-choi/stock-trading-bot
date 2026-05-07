# INBOX_EXECUTOR - 2026-05-07 09:45 KST - 스케줄 설정을 프로세스 트리거 구조로 변경

## 요청자

Sisyphus

## 담당 페르소나

Executor

## 배경

PM이 운영해보니 각 단계별 시작 시간을 모두 설정할 필요가 없다는 결론을 냈다. 현재 설정은 `schedule_s1_time`, `schedule_s2_time`, ..., `schedule_s5a_time`처럼 개별 단계 시간이 많아서 오히려 운영 혼선을 만든다.

새 운영 모델:

1. 특정 시간이 되면 **거래준비 프로세스**를 순차 실행
   - S1 KIS token refresh
   - S2 Market Tone
   - S3 Universe Filter
   - S4 Hybrid Screening
   - S5 Daily Plan 생성
   - S5-V Daily Plan 검증
   - S5-A Daily Plan 활성화 확인

2. S6, S7, S8, S11은 현행 유지
   - S6: 중요한 단계, 기존 시간 설정 유지
   - S7: 실시간/트리거 주문 실행 구조 유지
   - S8: 실시간/트리거 Position Manager 구조 유지
   - S11: Learning Memory Builder 기존 시간 설정 유지

3. 특정 시간이 되면 **후처리 프로세스**를 순차 실행
   - S9 당일 청산
   - S10 Review & Audit

또한 현재 `schedule_skip_today=true`가 오늘 거래일에도 표시되는 원인은 S1의 거래일 확인이 KIS `chk-holiday` 실패/모의투자 미지원/빈 응답을 `False=비거래일`로 반환하기 때문이다. 실패/미지원/unknown과 실제 휴장일을 분리해야 한다.

## 금지 사항

- git commit 금지.
- 사용자 변경사항 되돌리지 말 것.
- 구현 중 실제 S1~S11 단계 실행 금지.
- `/api/v1/decision/activate` 호출 금지.
- 주문/매수/매도/청산 API 호출 금지.
- 실계좌/KIS 주문성 API 호출 금지.
- 외부 LLM/KIS 호출을 유발하는 테스트 금지.

## 구현 목표

### 1. 스케줄러 job 구조 변경

대상: `backend/services/scheduler.py`

새 job:

- `job_trade_preparation_pipeline`
  - 설정 키: `schedule_trade_prep_time`
  - 기본값: `07:45`
  - 순서: S1 → S2 → S3 → S4 → S5 → S5-V → S5-A
  - 각 하위 단계 시작/완료/실패를 로그와 audit에 남긴다.
  - S1에서 오늘이 명확한 휴장일로 확인된 경우 S2~S6 skip.
  - 거래일 확인이 unknown이면 자동 프로세스 차단하지 말고 WARN 후 진행한다.

- `job_postprocess_pipeline`
  - 설정 키: `schedule_postprocess_time`
  - 기본값: `15:20`
  - 순서: S9 → S10
  - S9 청산 후 S10 Review & Audit 순차 실행.
  - 기존 `schedule_s9_time`, `schedule_s10_time`은 legacy로 남기되 scheduler 등록에는 새 postprocess key를 우선 사용한다.

현행 유지:

- `schedule_s6_time`
- `schedule_s11_time`
- backup/us_watch는 기존 의도에 맞게 유지하되, S9/S10 후처리와 충돌하지 않게 한다.

제거/비활성:

- scheduler에서 S1/S2/S3/S4/S5 개별 cron job 등록 제거 또는 legacy disabled.
- S5-V/S5-A는 새 거래준비 프로세스에 포함한다.

### 2. 거래일 판정 3상태화

대상 후보:

- `backend/services/kis/domestic/service.py`
- `backend/services/scheduler.py`

요구:

- 기존 `check_trading_day(date_str) -> bool`은 하위 호환을 위해 유지해도 된다.
- 새 함수 또는 새 내부 로직은 다음 3상태를 구분한다.
  - `trading`
  - `closed`
  - `unknown`
- KIS API 실패, 모의투자 미지원, 빈 응답, 알 수 없는 schema는 `unknown`으로 처리한다.
- `unknown`은 `schedule_skip_today=true`로 저장하면 안 된다.
- 명확히 `closed`일 때만 `schedule_skip_today=true`로 저장한다.
- 명확히 `trading`이거나 `unknown`이면 `schedule_skip_today=false`로 저장하고, unknown은 WARN 로그와 reason을 남긴다.

### 3. DB 기본 설정 변경

대상: `backend/services/db.py`

추가:

- `schedule_trade_prep_time`: `"07:45"`, 거래준비 프로세스 시작 시간
- `schedule_postprocess_time`: `"15:20"`, 후처리 프로세스 시작 시간

Legacy:

- 기존 `schedule_s1_time`~`schedule_s5a_time`, `schedule_s9_time`, `schedule_s10_time`은 즉시 삭제하지 말고 하위 호환을 위해 유지해도 된다.
- UI Settings에서는 새 키를 우선 표시하고 legacy key는 숨기거나 설명을 legacy로 바꾼다.

### 4. UI Settings / Diagnostics 표시 변경

대상: `backend/static/console.html`

요구:

- 운영 설정에서 다음 구조가 보이게 한다.
  - 거래준비 프로세스 시작 시간: S1~S5-A 순차 실행
  - S6 Decision Engine 시간
  - S7 실시간 주문 실행
  - S8 실시간 Position Manager
  - 후처리 프로세스 시작 시간: S9~S10 순차 실행
  - S11 Learning Memory 시간
- Diagnostics 카드의 개별 단계는 유지하되, 설명에 “거래준비 프로세스 하위 단계” 또는 “후처리 프로세스 하위 단계”를 표시한다.
- 스케줄 표시가 개별 S2/S3/S4 시간으로 오해되지 않게 한다.

### 5. 테스트

외부 호출 없는 테스트만 수행한다.

필수:

- `.venv/bin/python -m compileall -q backend`
- `git diff --check`
- 가능하면 unit/smoke:
  - trading day unknown이면 `schedule_skip_today=false`
  - closed면 `schedule_skip_today=true`
  - scheduler job list에 trade prep/postprocess/S6/S11이 등록되고 S1~S5 개별 cron은 등록되지 않음
  - Settings 기본값에 새 키 존재

## 완료 기준

- 운영자는 Settings에서 모든 단계 시간을 하나하나 정하지 않는다.
- 거래준비는 하나의 시작 시간으로 S1~S5-A 순차 실행된다.
- 후처리는 하나의 시작 시간으로 S9~S10 순차 실행된다.
- S6/S7/S8/S11은 현행 유지된다.
- KIS 휴장일 조회 실패/unknown이 오늘 같은 거래일을 `비거래일 스킵`으로 만들지 않는다.
- 모든 변경은 agent-comm OUTBOX로 보고된다.

## 결과 보고 파일

작업 완료 후 아래 파일을 작성하라.

`docs/agent-comm/OUTBOX_EXECUTOR_20260507_0945_scheduler_process_refactor.md`

포함 항목:

- 변경 파일 목록
- 구현 요약
- 새 설정 키
- legacy 설정 처리 방식
- 테스트 결과
- 남은 위험
- Oracle 리뷰 포인트
