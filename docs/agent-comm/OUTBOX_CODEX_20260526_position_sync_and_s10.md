# Codex 작업 결과 — position sync + S10 EOD guard

**작성일:** 2026-05-26  
**수신:** Sisyphus  
**역할:** Backend Executor  
**주의:** PM 지시대로 백엔드 서버는 기동하지 않았음.

---

## 1. 항목 1 fix 완료 — funnel.py import

- 변경 파일: `backend/api/routes/funnel.py`
- 변경 라인: `backend/api/routes/funnel.py:139`
- 변경 내용:
  - `from ..services.engine.position_manager import position_manager`
  - → `from ...services.engine.position_manager import position_manager`

검증:
- `python3 -m py_compile backend/api/routes/funnel.py ...` 통과
- `python3 -c "from backend.services.engine.position_manager import position_manager; from backend.api.routes.funnel import get_funnel_summary; print('import-ok')"` 통과
- 서버 기동 금지 지시 때문에 `/api/v1/funnel/summary` API smoke는 실행하지 않음.

---

## 2. 항목 2 설계안 + 구현 — KIS 실계좌 SSOT 통일

구현 요약:
- `backend/services/engine/position_manager.py`
  - `PositionManager.sync_account_position()` 추가.
  - KIS 잔고에만 있는 종목을 S8 PositionManager에 자동 등록.
  - KIS 평균매입가(`avg_price`)를 `entry_price`로 사용.
  - 자동 등록 종목은 기본 `LOW_VOL` profile fallback을 사용.
- `backend/services/engine/decision_engine.py`
  - `_sync_managed_positions_with_account()` 정책 변경.
  - 기존 S8 포지션은 KIS 수량 기준으로 동기화.
  - KIS에 없는 S8 포지션은 제거하되, 최근 매수 주문 5분 이내 종목은 기존 race-condition 보호 유지.
  - KIS-only 보유 종목은 자동 등록.
  - S6 활성화 시 1회 동기화 후, S6 활성 상태에서 60초마다 KIS 잔고를 재동기화.
  - 동기화로 종목 집합이 바뀌면 WS 구독 목록을 갱신.
  - S7 신규 매수 후보 평가 전, 이미 `position_manager`에 있는 종목은 tick 평가에서 제외.

트레이드오프:
- 60초 sync는 KIS balance API rate limit을 고려한 보수적 주기다. 콘솔의 1초 polling과 달리 직접 잔고 조회 빈도를 낮춰 EGW00201 위험을 줄였다.
- KIS-only 종목을 즉시 S8 보호 대상으로 넣기 때문에 중복 매수/손절 감시 누락 위험은 줄어든다.
- 다만 HTS 수동 매수 종목은 원래 전략 진입 근거가 없으므로 `LOW_VOL` fallback이 보수적이지만, 종목별 의도된 profile과 다를 수 있다.
- 평균매입가가 없거나 0인 KIS payload는 자동 등록하지 않고 WARN 로그만 남긴다. 잘못된 stop line 생성을 막기 위한 선택이다.

PM 승인 필요 사항:
- 구현은 완료했다. 운영 정책 관점에서 `LOW_VOL` 대신 별도 `IMPORTED` profile을 만들지는 PM 결정이 필요하다. 현재 profile enum/UI와의 호환성을 위해 이번 변경에서는 `LOW_VOL`로 처리했다.
- KIS API 부하가 실제 운영에서 여전히 크면 sync 주기를 120초로 늘리는 선택지가 있다.

---

## 3. 항목 3 원인 확정 — S10 EOD 배치

결론:
- 후보 a/b/c 중 하나가 아니라, 실제 원인은 **`job_postprocess_pipeline()` 내부의 `asyncio` import 누락**이었다.
- APScheduler cron 자체는 실행됐다. 즉 a) misfire/서버 재시작 누락은 아님.
- `_apply_market_open_schedule_guards()`는 `trade_prep`, `s6` 시간만 보정하므로 postprocess skip 원인이 아님. 즉 b) 아님.
- 무거래일 자동 skip 설계로 S10이 의도적으로 skip된 것도 아님. 즉 c) 아님.

로그 근거:
- `logs/server.log:779709` — APScheduler가 2026-05-25 15:20 KST job 실행.
- `logs/server.log:779710` — `START: [PostProcess] S9~S10 후처리 프로세스`.
- `logs/server.log:779748` — `START: [PostProcess] S9 후 fill 폴링 (30초 대기 후)`.
- `logs/server.log:779750` — `FAIL: [PostProcess] 후처리 프로세스 중단 reason=name 'asyncio' is not defined`.
- `logs/server.log:779751` — APScheduler 입장에서는 job이 executed successfully로 종료되어 재시도되지 않음.

조치:
- `backend/services/scheduler.py`에 `import asyncio` 추가.
- `job_missed_returns_update()` 독립 job 추가.
- 매일 15:35 KST `job_missed_returns_update` 실행 등록.
- `job_postprocess_pipeline`에 `misfire_grace_time=1800`, `coalesce=True` 추가.
- 독립 missed returns job에는 `misfire_grace_time=3600`, `coalesce=True` 추가.

---

## 4. 변경 파일 diff 요약

- `backend/api/routes/funnel.py`: 잘못된 relative import 경로 수정.
- `backend/services/engine/position_manager.py`: KIS 계좌 보유 종목을 S8 포지션으로 upsert하는 `sync_account_position()` 추가.
- `backend/services/engine/decision_engine.py`: KIS-only 보유 종목 자동 등록, 60초 주기 sync, WS 구독 갱신, 보유 종목 신규 매수 평가 제외 추가.
- `backend/services/scheduler.py`: `asyncio` import 누락 수정, missed returns 독립 job 추가, postprocess/missed returns misfire guard 추가.
- `tests/unit/test_position_monitoring.py`: KIS SSOT 동작에 맞게 sync 테스트 갱신.

---

## 5. 회귀 테스트 결과

실행:
- `python3 -m py_compile backend/api/routes/funnel.py backend/services/engine/position_manager.py backend/services/engine/decision_engine.py backend/services/scheduler.py tests/unit/test_position_monitoring.py` → 통과
- `python3 -c "from backend.services.engine.position_manager import position_manager; from backend.api.routes.funnel import get_funnel_summary; print('import-ok')"` → 통과
- `PYTHONPATH=. pytest -q tests/unit/test_position_monitoring.py` → `8 passed`
- `PYTHONPATH=. python3 - <<'PY' ... scheduler_instance.get_jobs() ... PY`
  - job_count=24
  - `job_postprocess_pipeline` 등록 확인, `misfire_grace_time=1800`, `coalesce=True`
  - `job_missed_returns_update` 등록 확인, `misfire_grace_time=3600`, `coalesce=True`
- KIS-only holding sync 단독 검증:
  - 입력: `{'symbol': '005930', 'qty': '3', 'avg_price': '70000'}`
  - 결과: `sync_account_position(symbol='005930', qty=3, entry_price=70000.0, final_rule={'profile_assigned': 'LOW_VOL'})` 호출 확인

미실행:
- 백엔드 서버 기동 금지 지시로 API smoke, Playwright E2E, 브라우저 확인은 실행하지 않음.

---

## 6. 위험 요소

- S6 주기 sync가 KIS balance API를 60초마다 1회 호출한다. 현재는 보수적이나, 콘솔 polling과 겹치는 운영 시간대에는 KIS rate limit 추이를 관찰해야 한다.
- KIS-only 수동 매수 종목은 `LOW_VOL` fallback stop rule을 적용한다. 종목 성격과 다를 수 있으나 미감시보다 안전한 쪽을 선택했다.
- WS 구독 목록 변경 시 `realtime_ws_manager.start()`가 기존 연결을 재시작한다. sync 결과로 실제 종목 집합이 바뀔 때만 재시작되도록 방어했다.
- 독립 missed returns job 추가로 scheduler job 수가 23 → 24로 증가한다. UI나 테스트가 job count를 고정값으로 가정하면 갱신 필요하다.

