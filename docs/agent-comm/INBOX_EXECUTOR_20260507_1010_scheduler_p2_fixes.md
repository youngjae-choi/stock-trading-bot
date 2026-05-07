# INBOX_EXECUTOR - 2026-05-07 10:10 KST - 스케줄 프로세스 P2 수정

## 요청자

Sisyphus

## 담당 페르소나

Executor

## 선행 리뷰

반드시 먼저 읽을 것:

- `docs/agent-comm/OUTBOX_ORACLE_20260507_1000_scheduler_process_refactor_review.md`

## 배경

Scheduler 프로세스 구조 변경은 큰 방향은 맞지만 Oracle이 운영 배포 전 P2 4건을 지적했다.

이번 작업은 해당 P2만 좁혀서 수정한다.

## 금지 사항

- git commit 금지.
- 사용자 변경사항 되돌리지 말 것.
- 실제 S1~S11 단계 실행 금지.
- `/api/v1/decision/activate` 호출 금지.
- 주문/매수/매도/청산 API 호출 금지.
- 실계좌/KIS 주문성 API 호출 금지.
- 외부 LLM/KIS 호출 금지.

## 수정 대상

### 1. Legacy custom schedule 보존

문제:

- 새 키 `schedule_trade_prep_time`, `schedule_postprocess_time`가 없을 때 기존 `schedule_s1_time`, `schedule_s9_time` 커스텀 값을 보존하지 못할 수 있다.

요구:

- DB 초기화/마이그레이션에서 새 process key가 없으면:
  - `schedule_trade_prep_time <- schedule_s1_time`
  - `schedule_postprocess_time <- schedule_s9_time`
- 해당 legacy 값이 없거나 invalid이면 기본값 사용.
- `_build_scheduler()`도 DB seed 전 build 상황을 고려해 legacy fallback을 지원한다.

### 2. S9 청산 실패 masking 방지

문제:

- `job_eod_liquidation()` 내부 실패가 postprocess pipeline에 전달되지 않아 S9 실패 후에도 S9/S10/전체 성공처럼 보일 수 있다.

요구:

- `job_eod_liquidation()`은 성공/실패 status를 반환하거나 실패를 re-raise한다.
- Decision Engine deactivate는 가능한 한 `finally`에서 시도하되, liquidation 실패는 postprocess pipeline에 전달되어야 한다.
- `job_postprocess_pipeline()`은 S9 실패 시:
  - 전체 pipeline status를 `failed` 또는 `partial_failed`로 기록
  - 로그에 S9 실패를 명확히 표시
  - S10 진행 여부는 안전 정책상 진행해도 되지만, 진행했다면 `S9 failed, S10 review continued`를 명확히 기록

### 3. S1 토큰 갱신 실패 audit 수정

문제:

- S1 token refresh 실패가 S1 success로 audit되고 후속 prep이 계속될 수 있다.

요구:

- S1 결과를 `token_status`와 `trading_day_status`로 분리한다.
- token refresh 실패 시 S1 audit은 `failed` 또는 `partial_failed`여야 한다.
- 후속 진행 정책:
  - token refresh 실패면 S2는 LLM이라 가능할 수 있지만 S3 이후 KIS 의존 단계가 위험하다.
  - 최소한 operator-visible WARN과 pipeline audit message에 남긴다.
  - 가능하면 S3 전에 token readiness를 확인하거나, token failed면 trade prep pipeline을 중단한다. PM 안전 관점에서는 중단 권장.

### 4. S5-V/S5-A 실패 후 S6 activation 차단

문제:

- S5-V/S5-A 실패 후에도 별도 cron인 S6가 active Daily Plan 없이 켜질 수 있다.

요구:

- S6 시작 전 오늘 active Daily Plan 존재를 hard requirement로 확인한다.
- 없으면 S6는 activate하지 않고 skip/blocked audit 또는 명확한 WARN 로그를 남긴다.
- 가능하면 `trade_prep_ready` 당일 gate를 system_settings 또는 audit에서 확인한다.
- 최소 구현은 `decision_engine.activate()` 또는 `job_decision_engine_start()`에서 active plan check.

### 5. P3 overview timeline 정리 가능하면 반영

가능하면 `backend/services/console_state.py`의 overview timeline도 process 중심으로 정리한다.

## 필수 검증

- `.venv/bin/python -m compileall -q backend`
- `git diff --check`
- 외부 호출 없는 smoke:
  - legacy custom schedule migration 보존
  - S9 failure가 postprocess success로 masking되지 않음
  - S1 token failure가 success audit로 끝나지 않음
  - active Daily Plan 없으면 S6 activate blocked

## 결과 보고 파일

작업 완료 후 아래 파일을 작성하라.

`docs/agent-comm/OUTBOX_EXECUTOR_20260507_1010_scheduler_p2_fixes.md`

포함 항목:

- 변경 파일 목록
- 구현 요약
- 테스트 결과
- 남은 위험
- Oracle 리뷰 포인트
