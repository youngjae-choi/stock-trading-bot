# OUTBOX_EXECUTOR - 2026-05-07 10:10 KST - 스케줄 프로세스 P2 수정 결과

## 변경 파일 목록

- `backend/services/db.py`
- `backend/services/scheduler.py`
- `backend/services/console_state.py`
- `docs/agent-comm/OUTBOX_EXECUTOR_20260507_1010_scheduler_p2_fixes.md`

참고: 작업 시작 시점에 `backend/services/kis/domestic/service.py`, `backend/static/console.html` 등 선행 변경사항이 이미 존재했으며 되돌리지 않았다.

## 구현 요약

1. Legacy custom schedule 보존
   - DB 초기화에서 process key seed 전 legacy 값을 먼저 확인한다.
   - `schedule_trade_prep_time`이 없으면 valid `schedule_s1_time`을 복사한다.
   - `schedule_postprocess_time`이 없으면 valid `schedule_s9_time`을 복사한다.
   - legacy 값이 없거나 HH:MM 형식이 invalid이면 기본값을 사용한다.
   - `_build_scheduler()`에도 DB seed 전 build 상황을 위한 `schedule_s1_time`/`schedule_s9_time` fallback을 추가했다.

2. S9 청산 실패 masking 방지
   - `job_eod_liquidation()`이 청산 실패를 re-raise하고, Decision Engine deactivate는 청산 성공/실패와 무관하게 시도한다.
   - `job_postprocess_pipeline()`은 S9 audit과 전체 `POSTPROCESS` audit을 기록한다.
   - S9 실패 후 S10을 계속 진행하면 전체 상태를 `partial_failed`로 기록하고, message에 `S9 failed, S10 review continued`를 남긴다.

3. S1 token refresh 실패 audit/중단 정책 보강
   - S1 결과를 `token_status`, `token_error`, `trading_day_status`, `trading_day`로 분리했다.
   - token refresh 실패 시 S1 audit은 `failed`로 종료한다.
   - token refresh 실패 시 S2~S6 downstream audit을 `blocked`로 남기고 trade prep pipeline을 중단한다.
   - 거래일 확인 `unknown`은 `partial_failed` audit + WARN으로 남기되 기존 정책처럼 token이 정상인 경우 진행한다.

4. active Daily Plan 없는 S6 activation 차단
   - S6 시작 전에 오늘 `status='active'` Daily Plan 존재를 직접 조회한다.
   - active Daily Plan이 없으면 `decision_engine.activate()`를 호출하지 않고 S6 `blocked` audit과 WARN 로그를 남긴다.

5. Overview timeline P3 정리
   - `get_console_overview()` timeline을 legacy 개별 단계 시간 대신 process 중심으로 정리했다.
   - 표시 축: 거래준비 프로세스, S6, 후처리 프로세스, 백업, S11 Learning Memory, 미국장 야간 관찰.

## 테스트 결과

- PASS: `.venv/bin/python -m compileall -q backend`
- PASS: `git diff --check`
- PASS: 외부 호출 없는 smoke 4종
  - legacy custom schedule migration/build fallback 보존
  - S9 failure가 postprocess success로 masking되지 않음
  - S1 token failure가 success audit로 끝나지 않고 downstream blocked 기록
  - active Daily Plan 없으면 S6 activate blocked

Smoke 조건:

- 실제 S1~S11 단계 실행 없음.
- `/api/v1/decision/activate` 호출 없음.
- 주문/매수/매도/청산 API 호출 없음.
- 외부 LLM/KIS 호출 없음.
- S1/S9/S10/S6 위험 경로는 monkeypatch로 대체했다.

## 남은 위험

- 실제 KIS/LLM/주문성 API 연동은 지시상 실행하지 않아 운영 성공 여부는 미검증이다.
- S10 Review & Audit 함수는 내부 예외를 자체 로깅 후 삼키는 기존 구조라, 이번 범위에서는 S9 masking만 제거했다.
- 기존에 이미 잘못 seed된 DB에서 `schedule_trade_prep_time`/`schedule_postprocess_time`이 존재하는 경우에는 legacy 값으로 강제 덮어쓰지 않는다. 이번 요구 범위는 "새 process key가 없으면 legacy copy" 기준으로 구현했다.
- S6 gate는 active Daily Plan 존재를 hard requirement로 두므로, 최신 plan이 실패 상태여도 과거 active plan이 존재하면 활성화를 허용한다. 이는 "active Daily Plan 존재" 기준에 맞춘 동작이다.

## Oracle 리뷰 포인트

- Legacy-only DB fresh process에서 scheduler build가 `schedule_s1_time`/`schedule_s9_time` fallback을 쓰는지 확인.
- `initialize_database()`가 process key 부재 시 legacy custom 값을 보존하는지 확인.
- S9 liquidation failure 후 S10 continuation 정책과 `POSTPROCESS=partial_failed` audit이 운영자가 보기 충분한지 확인.
- S1 token failure 시 S2까지도 차단하는 안전 정책이 PM 의도와 맞는지 확인.
- S6 active plan direct query가 Daily Plan gate의 의미를 충분히 보장하는지 확인.
