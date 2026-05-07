# OUTBOX_ORACLE - 2026-05-07 10:00 KST - 스케줄 프로세스 구조 변경 리뷰

## Findings

### P2 - Legacy scheduler custom time migration can silently reset operator schedules

- 위치:
  - `backend/main.py:57`~`58`, `backend/main.py:101`~`106`
  - `backend/services/scheduler.py:674`~`684`
  - `backend/services/db.py:124`, `backend/services/db.py:135`
- 영향:
  - `scheduler_instance`가 `initialize_database()`보다 먼저 import/build된다.
  - 기존 DB에 `schedule_s1_time` 또는 `schedule_s9_time`만 있고 새 process key가 없는 배포 첫 기동에서 `postprocess`는 legacy `schedule_s9_time` fallback을 한 번 사용하지만, `trade_prep`은 legacy `schedule_s1_time` fallback이 없어 기본 `07:45`로 돌아간다.
  - 이후 `initialize_database()`가 새 `schedule_trade_prep_time=07:45`, `schedule_postprocess_time=15:20`을 seed하므로, 다음 재시작부터는 기존 custom S9 시간도 `15:20` 기본값으로 덮인 것처럼 동작한다.
- 재현 smoke:
  - legacy-only DB에 `schedule_s1_time=06:11`, `schedule_s9_time=15:44`를 넣고 fresh process에서 scheduler build 확인.
  - 결과: `job_trade_preparation_pipeline cron[hour='7', minute='45']`, `job_postprocess_pipeline cron[hour='15', minute='44']`.
  - `initialize_database()` 이후 새 키 값: `schedule_trade_prep_time=07:45`, `schedule_postprocess_time=15:20`.
- 수정 제안:
  - 마이그레이션에서 새 key가 없을 때 `schedule_trade_prep_time <- schedule_s1_time`, `schedule_postprocess_time <- schedule_s9_time`으로 값까지 복사한다.
  - 또는 `scheduler_instance`를 lifespan 내부에서 `initialize_database()` 이후 lazy build하도록 변경한다.
  - 최소한 `_build_scheduler()`에 `trade_prep`도 `schedule_s1_time` fallback을 추가하고, seed가 legacy custom 값을 보존하게 한다.

### P2 - S9 liquidation failure is swallowed, but postprocess pipeline logs S9/S10 success

- 위치:
  - `backend/services/scheduler.py:546`~`563`
  - `backend/services/scheduler.py:599`~`609`
- 영향:
  - `job_eod_liquidation()`이 `run_eod_liquidation()` 예외를 catch 후 re-raise/return status 없이 계속 진행한다.
  - `job_postprocess_pipeline()`은 S9 내부 실패를 알 수 없어 `SUCCESS: [PostProcess] S9 당일 청산 호출 완료`, 이어서 S10 실행 및 전체 성공 로그를 남긴다.
  - 실제 포지션 청산 실패가 후처리 성공처럼 보일 수 있어 운영자가 미청산 상태를 늦게 발견할 위험이 있다.
- 수정 제안:
  - `job_eod_liquidation()`이 `{"ok": bool, "liquidation_ok": bool, ...}` 형태를 반환하거나 liquidation 실패를 re-raise한다.
  - Decision Engine deactivate는 `finally`에서 시도하되, liquidation 실패 시 postprocess 전체 상태는 `failed` 또는 `partial_failed`로 기록한다.
  - S10 진행 정책을 PM이 정해야 한다. 진행하더라도 S9 실패를 Review/Audit metadata와 로그에 명확히 남겨야 한다.

### P2 - S1 token refresh failure is audited as success and downstream prep continues

- 위치:
  - `backend/services/scheduler.py:214`~`232`
  - `backend/services/scheduler.py:457`~`468`
- 영향:
  - `job_refresh_kis_token()`은 token refresh 실패를 catch만 하고, 거래일 확인 결과를 반환한다.
  - `job_trade_preparation_pipeline()`은 S1 audit을 항상 `success`로 finish한다.
  - 인증/토큰 장애가 있는 날에도 S1 성공처럼 표시되고, `unknown` 정책에 따라 S2~S5-A가 계속 진행될 수 있다. S3 등 KIS 의존 단계에서 뒤늦게 실패할 가능성이 높다.
- 수정 제안:
  - S1 결과를 `token_status`와 `trading_day_status`로 분리한다.
  - token refresh 실패 시 S1 audit은 `failed` 또는 `partial_failed`로 남기고, 후속 진행 여부를 PM 정책으로 결정한다.
  - 계속 진행하더라도 S3/S6 전에는 KIS credential/token readiness를 다시 확인하고 operator-visible WARN을 남긴다.

### P2 - S5-V/S5-A failure does not block later S6 activation

- 위치:
  - `backend/services/scheduler.py:510`~`514`
  - `backend/services/scheduler.py:517`~`532`
  - `backend/services/engine/rule_cache.py:61`~`83`
- 영향:
  - trade prep pipeline은 S5-V/S5-A 실패 시 자기 pipeline만 중단한다.
  - 별도 cron인 S6는 `schedule_skip_today`만 확인하고, active Daily Plan이 없어도 S4 후보와 기본/MID_VOL 룰로 rule cache를 만들 수 있다.
  - "S5-A 활성화 확인"이 실패했는데도 장중 Decision Engine이 켜질 수 있어 Daily Plan gate의 의미가 약해진다.
- 수정 제안:
  - S6 시작 시 오늘 active Daily Plan 존재를 hard requirement로 확인한다.
  - 또는 S5-V/S5-A 실패 시 `schedule_skip_today`와 별도의 `trade_prep_ready=false` 같은 당일 gate를 저장하고 S6가 이를 확인한다.
  - active plan 없이 S6를 유지해야 한다면 PM 승인 정책과 UI 경고가 필요하다.

### P3 - Dashboard/overview timeline still shows legacy individual times

- 위치:
  - `backend/services/console_state.py:461`~`481`
- 영향:
  - Console Settings와 Diagnostics는 process 중심으로 바뀌었지만 overview payload는 여전히 `08:00`, `08:15`, `08:30`, `08:45`, `16:00` 등 개별 단계 timeline을 반환한다.
  - 운영자가 화면별로 다른 스케줄 구조를 보게 되어 혼선이 남는다.
- 수정 제안:
  - overview timeline도 `schedule_trade_prep_time`, `schedule_s6_time`, `schedule_postprocess_time`, `schedule_s11_time`, backup/us_watch 중심으로 정리한다.
  - 하위 단계 진행률은 pipeline audit 기반으로 별도 표시한다.

## 확인 결과

- Scheduler job 등록:
  - PASS: build-only smoke에서 job id는 `job_trade_preparation_pipeline`, `job_decision_engine_start`, `job_postprocess_pipeline`, `job_data_backup`, `job_learning_memory`, `job_us_market_watch`.
  - PASS: S1~S5/S9/S10 legacy individual cron job id는 build 결과에 없음.
  - PASS: S7/S8 cron job은 추가되지 않음.
- Trade prep 순서:
  - PASS: 코드상 S1 -> S2 -> S3 -> S4 -> S5 -> S5-V -> S5-A 순서.
  - 주의: S1 token 실패와 S5-V/S5-A 실패의 후속 S6 정책은 P2로 남김.
- Postprocess 순서:
  - PASS: 코드상 S9 -> S10 순서.
  - FAIL/RISK: S9 내부 실패가 pipeline에 전파되지 않음.
- Trading day 3상태:
  - PASS: `trading`, `closed`, `unknown` 파싱 smoke 확인.
  - PASS: KIS error, empty output, unknown schema는 `unknown`.
  - PASS: `closed`만 `schedule_skip_today=true`, `unknown/trading`은 false.
- Settings/UI:
  - PASS: Settings table은 process key 중심으로 축소됨.
  - PASS: S7/S8은 read-only 실시간 표시.
  - 주의: overview timeline은 legacy 표시가 남아 P3.

## 테스트 결과

- PASS: `.venv/bin/python -m compileall -q backend`
- PASS: `git diff --check`
- PASS: 외부 호출 없는 scheduler/settings/trading-day smoke
  - scheduler build only, scheduler start 없음.
  - S1~S11 실제 단계 실행 없음.
  - `/api/v1/decision/activate`, 주문/청산 API, KIS/LLM 호출 없음.
- PASS: legacy migration smoke
  - 외부 호출 없음.
  - legacy custom schedule 보존 실패를 재현해 P2로 기록.

## 최종 판단

조건부 가능.

- read-only/demo smoke 수준에서는 빌드와 핵심 job 등록 구조가 의도대로 동작한다.
- 실제 자동매매 운영 배포는 P2 수정 전 보류를 권장한다.
- 특히 S9 청산 실패 masking, S5-A 실패 후 S6 activation 가능성, legacy custom schedule 유실은 운영 리스크가 크다.

## 남은 위험

- 실제 S1~S11 단계는 지시상 실행하지 않았으므로 KIS/LLM/주문성 API의 실운영 성공 여부는 미검증이다.
- 수동 Diagnostics 버튼에는 여전히 S5-A activate, S6 activate, S9 liquidate-all 같은 위험 동작이 남아 있다. 이번 변경 범위 유지 사항이지만 운영 권한/확인 모달 정책은 별도 검토가 필요하다.
- `check_trading_day()` legacy bool API는 unknown도 `False`를 반환한다. 현재 repo 내 호출자는 없지만, 향후 재사용 시 비거래일 오판이 재발할 수 있어 deprecated 표시나 호출 금지를 권장한다.
