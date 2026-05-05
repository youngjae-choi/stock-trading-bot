# OUTBOX_EXECUTOR_phase5b_backend

## 역할
Executor

## 작업 요약
Phase 5B 판단검증 백엔드 구현을 완료했다.

## 구현 결과
- `backend/services/db.py`
  - `shadow_trades`
  - `shadow_trade_events`
  - `missed_opportunities`
  - `false_positive_cases`
  - `confidence_calibration_daily`
  - `confidence_calibration_bins`
  - `confidence_calibration_bins` 5개 기본 bin seed 추가
  - `trading_signals.realized_pnl` 컬럼 추가 및 기존 DB용 마이그레이션 추가
- `backend/services/engine/shadow_trading.py`
  - `create_shadow_trade`
  - `update_shadow_trade`
  - `get_today_shadow_trades`
  - `get_shadow_summary`
- `backend/services/engine/missed_opportunity.py`
  - `record_missed_opportunity`
  - `get_today_missed`
  - `get_improvement_candidates`
- `backend/services/engine/false_positive.py`
  - `record_false_positive`
  - `get_today_false_positives`
- `backend/services/engine/confidence_calibration.py`
  - `get_confidence_bin`
  - `run_confidence_calibration`
  - `get_calibration_summary`
- REST API 추가
  - `backend/api/routes/shadow_trading.py`
  - `backend/api/routes/missed_opportunity.py`
  - `backend/api/routes/false_positive.py`
  - `backend/api/routes/confidence_calibration.py`
- `backend/api/routes/expert_knowledge.py`
  - `GET /api/v1/expert-knowledge/impact` 추가
- `backend/main.py`
  - Phase 5B 신규 라우터 4개 등록

## 검증 결과

### 1. py_compile
통과.

```bash
python3 -m py_compile \
  backend/services/db.py \
  backend/services/engine/shadow_trading.py \
  backend/services/engine/missed_opportunity.py \
  backend/services/engine/false_positive.py \
  backend/services/engine/confidence_calibration.py \
  backend/api/routes/shadow_trading.py \
  backend/api/routes/missed_opportunity.py \
  backend/api/routes/false_positive.py \
  backend/api/routes/confidence_calibration.py \
  backend/api/routes/expert_knowledge.py \
  backend/main.py
```

### 2. DB 초기화
임시 DB(`/tmp/phase5b_backend_test.sqlite3`) 기준 통과.

확인 결과:
- 신규 6개 테이블 누락 없음
- `confidence_calibration_bins` seed 5개 생성 확인
- `trading_signals.realized_pnl` 컬럼 생성 확인

### 3. 라우터 함수 호출 검증
임시 DB(`/tmp/phase5b_route_test.sqlite3`) 기준 통과.

확인한 응답:
- `post_shadow True dict`
- `shadow_today True list`
- `shadow_summary True dict`
- `missed_today True list`
- `missed_candidates True list`
- `false_positive_today True list`
- `calibration_run True dict`
- `calibration_today True list`
- `knowledge_impact True list`

### 4. 실제 HTTP 호출 확인
통과.

2026-05-04 개발 서버(`http://127.0.0.1:8000`) 기준으로 Phase 5B Playwright e2e를 실행해 실제 HTTP 호출과 UI 진입을 확인했다.

```bash
npx playwright test --config=playwright.config.cjs tests/e2e/phase5b.spec.cjs --workers=1
```

결과:
- 12 passed
- `POST /api/v1/shadow-trading/` 200 OK
- `GET /api/v1/shadow-trading/today` 200 OK
- `GET /api/v1/shadow-trading/summary` 200 OK
- `GET /api/v1/missed-opportunity/today` 200 OK
- `GET /api/v1/missed-opportunity/candidates` 200 OK
- `GET /api/v1/false-positive/today` 200 OK
- `POST /api/v1/confidence-calibration/run` 200 OK
- `GET /api/v1/confidence-calibration/today` 200 OK
- Phase 5B UI 4개 화면 진입 확인

## 영향 범위
- DB schema 초기화 및 기존 DB 마이그레이션에 영향 있음
- FastAPI 라우터 등록에 영향 있음
- 기존 API 라우터 인터페이스 변경 없음
- `trading_signals`에는 `realized_pnl` nullable 컬럼이 추가됨

## 남은 확인 필요
- UI Phase 5B에서 표시 필드와 날짜 기준(KST)이 기대와 일치하는지 확인

## 완료 체크리스트
- [x] 작업 1 — DB 6개 테이블
- [x] 작업 2 — shadow_trading.py
- [x] 작업 3 — missed_opportunity.py
- [x] 작업 4 — false_positive.py
- [x] 작업 5 — confidence_calibration.py
- [x] 작업 6 — REST API 5세트
- [x] 작업 7 — main.py 라우터 등록
- [x] py_compile 전부 통과
- [x] DB 초기화 검증
- [x] 라우터 함수 호출 검증
- [x] 실제 HTTP 호출 검증
