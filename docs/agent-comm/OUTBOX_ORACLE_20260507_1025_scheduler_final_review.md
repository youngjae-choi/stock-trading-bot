# OUTBOX_ORACLE - 2026-05-07 10:25 KST - 스케줄 프로세스 최종 리뷰

## Findings

### P1/P2

- 발견 없음.

### P3 - S10 Review & Audit 내부 실패는 아직 postprocess 성공으로 보일 수 있음

- 위치:
  - `backend/services/scheduler.py:651`~`665`
  - `backend/services/scheduler.py:702`~`721`
- 영향:
  - `job_review_audit()`은 `run_review_audit()` 예외를 내부에서 로깅한 뒤 re-raise 또는 status 반환 없이 종료한다.
  - 따라서 S9가 성공하고 S10 내부에서만 실패하면 `job_postprocess_pipeline()`은 `SUCCESS: [PostProcess] S10 Review & Audit 호출 완료`와 `POSTPROCESS=success`를 남길 수 있다.
  - S9 청산 실패 masking은 이번 P2 수정으로 해결됐으므로 주문/청산 안전성 blocking 이슈는 아니다. 다만 운영자가 S10 보고서 생성 실패를 후처리 성공으로 오해할 수 있다.
- 권장:
  - 다음 정리 작업에서 `job_review_audit()`도 `job_eod_liquidation()`처럼 status를 반환하거나 실패를 re-raise하게 맞춘다.
  - S10 개별 audit row를 `success/failed`로 남기고, S10 실패 시 `POSTPROCESS=partial_failed` 또는 `failed`로 기록한다.

## 확인 결과

- `schedule_trade_prep_time` 하나로 S1~S5-A 순차 실행:
  - PASS. `job_trade_preparation_pipeline`이 S1 -> S2 -> S3 -> S4 -> S5 -> S5-V -> S5-A 순서로 실행된다.
  - S1 token 실패 시 S1 audit은 `failed`, S2~S6은 `blocked`로 남고 downstream은 실행되지 않는다.
  - 명확한 휴장일(`closed`)이면 S2~S6 skip audit을 남기고 중단한다.
  - 거래일 `unknown`은 `schedule_skip_today=false`로 저장하고 WARN 후 진행한다.

- `schedule_postprocess_time` 하나로 S9~S10 순차 실행:
  - PASS. scheduler 등록은 `job_postprocess_pipeline` 단일 cron이다.
  - S9 청산 실패는 S9 `failed`, POSTPROCESS `partial_failed`로 남고 success masking되지 않는다.
  - S9 실패 후 S10 continuation 정책은 로그와 audit message에 명시된다.

- S6/S7/S8/S11 현행 유지:
  - PASS. S6와 S11은 개별 cron 유지, S7/S8은 cron 없이 실시간/트리거 표시 구조 유지.
  - S6는 오늘 active Daily Plan이 없으면 `decision_engine.activate()`를 호출하지 않고 `blocked` audit을 남긴다.

- KIS 거래일 3상태:
  - PASS. `trading`, `closed`, `unknown` 파싱을 확인했다.
  - KIS error, empty output, unknown schema는 `unknown`이다.
  - `closed`만 `schedule_skip_today=true`, `trading/unknown`은 false다.

- Legacy custom schedule 보존:
  - PASS. legacy-only DB에서 `_build_scheduler()`가 `schedule_s1_time`/`schedule_s9_time` fallback을 사용한다.
  - `initialize_database()`는 새 process key가 없을 때 `schedule_trade_prep_time <- schedule_s1_time`, `schedule_postprocess_time <- schedule_s9_time`으로 복사한다.

- Overview/Settings/Diagnostics:
  - PASS. Settings와 Overview timeline은 process 중심 표시로 정리됐다.
  - Diagnostics의 S1~S5-A/S9~S10 설명도 process 하위 단계로 표시된다.

## 테스트 결과

- PASS: `.venv/bin/python -m compileall -q backend`
- PASS: `git diff --check`
- PASS: 외부 호출 없는 scheduler/settings/trading-day smoke
  - scheduler build only, scheduler start 없음.
  - S1~S5/S9/S10 개별 cron 미등록 확인.
  - trade prep/postprocess/S6/S11/backup/us_watch job 등록 확인.
  - legacy custom schedule migration/build fallback 확인.
  - trading/closed/unknown 및 `schedule_skip_today` 저장 정책 확인.
- PASS: 외부 호출 없는 P2 fix smoke
  - S9 failure가 postprocess success로 masking되지 않음.
  - S1 token failure가 success audit로 끝나지 않고 downstream blocked 기록.
  - active Daily Plan 없으면 S6 activate blocked.
  - trade prep 순서 S1 -> S2 -> S3 -> S4 -> S5 -> S5-V -> S5-A 확인.

Smoke 조건:

- 실제 S1~S11 단계 실행 없음.
- `/api/v1/decision/activate` 호출 없음.
- 주문/매수/매도/청산 API 호출 없음.
- 외부 LLM/KIS 호출 없음.
- 위험 경로는 monkeypatch로 대체했다.

## 최종 판단

배포 가능.

- 운영 배포를 막을 P1/P2는 발견하지 못했다.
- Scheduler process refactor와 선행 P2 4건은 현재 코드 기준으로 해소됐다.
- 단, S10 실패 masking은 P3 잔여 위험으로 남겨 후속 개선을 권장한다.

## 남은 위험

- 실제 KIS/LLM/주문성 API 연동은 지시상 실행하지 않아 실운영 외부 호출 성공 여부는 미검증이다.
- `check_trading_day()` legacy bool API는 `unknown`도 `False`를 반환한다. 현재 repo 내 직접 호출자는 없지만, 향후 재사용 시 비거래일 오판 방지를 위해 deprecated 표시 또는 사용 금지 주석을 권장한다.
- 기존에 이미 잘못 seed된 DB에서 `schedule_trade_prep_time`/`schedule_postprocess_time`이 존재하는 경우에는 migration이 legacy 값으로 강제 덮어쓰지 않는다. 이번 요구 범위는 "새 process key가 없을 때 legacy copy" 기준이다.
