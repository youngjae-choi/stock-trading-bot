# OUTBOX — Codex : 장중 재선별 시스템 보강 v2

작성일: 2026-05-25
담당: Codex / Executor

## 변경 파일 전체 목록

- `backend/services/scheduler.py`
- `backend/services/engine/intraday_refresh.py`
- `backend/services/engine/sector_rotation.py`
- `backend/services/engine/replacement_signal.py`
- `backend/services/engine/decision_engine.py`
- `backend/services/engine/position_manager.py`
- `backend/services/db.py`
- `backend/services/migrations/20260525_intraday_reselection_replacement_signals.sql`
- `backend/services/migrations/20260525_intraday_reselection_sector_rotation_log.sql`
- `backend/api/routes/trading_monitor.py`
- `tests/unit/test_intraday_reselection_v2.py`
- `docs/manual/intraday_reselection_v2.md`

## 신규 system_settings 키

| Key | 기본값 |
| --- | ---: |
| `intraday_refresh.master_enabled` | `true` |
| `intraday_refresh.lunch_slots_enabled` | `true` |
| `intraday_refresh.sector_rotation_enabled` | `true` |
| `intraday_refresh.sector_rotation_threshold` | `3.0` |
| `intraday_refresh.replacement_signal_enabled` | `true` |
| `intraday_refresh.replacement_score_gap` | `0.15` |
| `intraday_refresh.max_replacement_per_symbol` | `1` |
| `intraday_refresh.max_replacement_per_day` | `5` |

## 신규 API endpoint

- `GET /api/v1/trading-monitor/reselection-stats?trade_date=YYYY-MM-DD`
- `GET /api/v1/trading-monitor/replacement-signals?trade_date=YYYY-MM-DD`

## 신규 DB 테이블

- `replacement_signals`
- `sector_rotation_log`

## 구현 요약

- 13:00, 14:00 장중 재선별 APScheduler 슬롯을 추가했다.
- 기존 시장 평균 트리거 임계치와 같은 방향 중복 방지 로직은 변경하지 않았다.
- 섹터 회전 감지 모듈을 추가하고, 시장 평균 트리거와 OR 조건으로 통합했다.
- 섹터 분석 결과는 슬롯 실행 시 `sector_rotation_log`에 저장한다.
- 재선별 후 신규 후보와 보유 포지션을 비교해 교체 신호만 저장/알림한다.
- 강제 매도/매수 로직은 추가하지 않았다.
- 트레일링 스탑 매도 주문 성공 후 S6 후보 감시를 재정렬하고, 최근 매수 주문이 없는 후보만 자연 진입 평가를 다시 받을 수 있게 했다.
- 신규 설정 8개는 DB 초기화 시 없으면 자동 등록된다.

## INBOX와 다르게 구현한 부분 / 추가 확인 필요

- `intraday_refresh.py` 기존 구현이 `system_settings.value` 컬럼을 읽고 있었으나 실제 스키마는 `value_json`이다. 신규 기능 통합 중 기존 재선별 로그 저장/조회가 정상 동작하도록 `value_json` 기준으로 보정했다.
- 교체 신호의 기존 보유 종목 점수는 PositionManager 메모리 값에 없을 수 있어, 없으면 최신 `trading_signals.confidence`를 fallback으로 사용한다. 둘 다 없으면 신호를 만들지 않는다.
- `GET` API 스모크는 FastAPI 라우터 단위 ASGI 테스트로 확인했다. 전체 `backend.main` lifespan 기반 TestClient는 스케줄러 thread가 붙어 테스트 프로세스가 종료되지 않아 사용하지 않았다.
- 전체 unit suite에서 기존 `EODLiquidationPolicyTest` 1건이 실패한다. 실패 원인은 `execute_sell(..., name='')` 인자 추가와 테스트 기대값 불일치이며, 이번 변경 범위 파일은 아니다.

## 단위 동작 검증 결과

- `python -m pytest tests/unit/test_intraday_reselection_v2.py -q` → 3 passed
- `python -m py_compile backend/services/engine/sector_rotation.py backend/services/engine/replacement_signal.py backend/services/engine/intraday_refresh.py backend/services/engine/decision_engine.py backend/services/engine/position_manager.py backend/api/routes/trading_monitor.py backend/services/scheduler.py backend/services/db.py` → 통과
- `python -m compileall -q backend` → 통과
- DB 초기화 스모크 → 신규 8개 `system_settings` 키와 2개 신규 테이블 생성 확인
- Scheduler 스모크 → `job_intraday_refresh_1300`, `job_intraday_refresh_1400` 등록 확인
- API 빈 데이터 스모크:
  - `GET /api/v1/trading-monitor/reselection-stats?trade_date=2099-01-01` → 200, 빈 배열 응답
  - `GET /api/v1/trading-monitor/replacement-signals?trade_date=2099-01-01` → 200, 빈 배열 응답

## 남은 리스크

- 운영 DB의 `symbols.sector` 채움 상태가 섹터 회전 감지 품질을 좌우한다.
- 실제 KIS 거래량 상위 30종목 API 응답 필드명은 기존 `_fetch_market_snapshot()` 결과를 그대로 사용하므로, 해당 함수의 `symbol/change_rate` 정규화 품질에 의존한다.
- Playwright E2E는 INBOX에 “별도 INBOX로 추가 지시 예정”이라고 명시되어 있어 이번 작업에서는 추가하지 않았다.
