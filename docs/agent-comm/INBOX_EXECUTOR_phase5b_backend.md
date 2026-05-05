# INBOX_EXECUTOR_phase5b_backend

## 역할
너는 Executor다. Phase 5B 판단검증 백엔드를 구현하라.
완료 후 `docs/agent-comm/OUTBOX_EXECUTOR_phase5b_backend.md`에 결과를 작성하라.

---

## 작업 1 — DB 테이블 6개 추가 (backend/services/db.py)

`_schema_statements()` 에 추가한다.

```sql
CREATE TABLE IF NOT EXISTS shadow_trades (
    id              TEXT PRIMARY KEY,
    trade_date      TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    symbol_name     TEXT NOT NULL DEFAULT '',
    missed_stage    TEXT NOT NULL,  -- S4_excluded|S5_not_allowed|confidence_low|risk_guard|preflight
    entry_price     REAL NOT NULL DEFAULT 0.0,
    entry_time      TEXT NOT NULL,
    exit_price      REAL,
    exit_time       TEXT,
    shadow_pnl      REAL,           -- 가상 손익률 (%)
    max_return_10m  REAL,
    max_return_30m  REAL,
    max_return_eod  REAL,
    status          TEXT NOT NULL DEFAULT 'active',  -- active|closed
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shadow_trades_trade_date ON shadow_trades(trade_date);

CREATE TABLE IF NOT EXISTS shadow_trade_events (
    id              TEXT PRIMARY KEY,
    shadow_trade_id TEXT NOT NULL,
    event_type      TEXT NOT NULL,  -- price_update|close|max_return
    price           REAL,
    pnl             REAL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS missed_opportunities (
    id                  TEXT PRIMARY KEY,
    trade_date          TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    symbol_name         TEXT NOT NULL DEFAULT '',
    missed_stage        TEXT NOT NULL,
    missed_reason       TEXT NOT NULL,
    price_at_missed     REAL NOT NULL DEFAULT 0.0,
    max_return_after_10m REAL,
    max_return_after_30m REAL,
    max_return_until_eod REAL,
    improvement_candidate INTEGER NOT NULL DEFAULT 0,  -- 0|1
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_missed_trade_date ON missed_opportunities(trade_date);

CREATE TABLE IF NOT EXISTS false_positive_cases (
    id                  TEXT PRIMARY KEY,
    trade_date          TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    symbol_name         TEXT NOT NULL DEFAULT '',
    false_positive_type TEXT NOT NULL,  -- entry_fail|early_exit|wrong_profile
    original_score      REAL,
    original_confidence REAL,
    assigned_profile    TEXT,
    entry_reason        TEXT NOT NULL DEFAULT '',
    loss_reason         TEXT NOT NULL DEFAULT '',
    exit_reason         TEXT NOT NULL DEFAULT '',
    applied_knowledge_ids TEXT NOT NULL DEFAULT '[]',
    applied_memory_ids  TEXT NOT NULL DEFAULT '[]',
    suggested_penalty   REAL,
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fp_trade_date ON false_positive_cases(trade_date);

CREATE TABLE IF NOT EXISTS confidence_calibration_daily (
    id              TEXT PRIMARY KEY,
    trade_date      TEXT NOT NULL,
    bin_label       TEXT NOT NULL,  -- ge090|80to90|70to80|60to70|lt060
    trade_count     INTEGER NOT NULL DEFAULT 0,
    win_count       INTEGER NOT NULL DEFAULT 0,
    avg_pnl         REAL NOT NULL DEFAULT 0.0,
    expected_win_rate REAL NOT NULL DEFAULT 0.0,
    actual_win_rate REAL NOT NULL DEFAULT 0.0,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conf_cal_trade_date ON confidence_calibration_daily(trade_date);

CREATE TABLE IF NOT EXISTS confidence_calibration_bins (
    id              TEXT PRIMARY KEY,
    bin_label       TEXT NOT NULL UNIQUE,
    bin_min         REAL NOT NULL,
    bin_max         REAL NOT NULL,
    cumulative_trades INTEGER NOT NULL DEFAULT 0,
    cumulative_wins INTEGER NOT NULL DEFAULT 0,
    cumulative_avg_pnl REAL NOT NULL DEFAULT 0.0,
    last_updated    TEXT NOT NULL
);
```

`confidence_calibration_bins` 초기 데이터 INSERT (서버 시작 시 없으면 삽입):
```python
# _seed_confidence_bins(connection) 함수 추가
# ge090 / 80to90 / 70to80 / 60to70 / lt060 5개 행
```

---

## 작업 2 — Shadow Trading 서비스

파일: `backend/services/engine/shadow_trading.py`

```python
"""Shadow Trading — 미진입 종목 가상 추적."""
```

### 구현 함수

#### `def create_shadow_trade(trade_date, symbol, symbol_name, missed_stage, entry_price, entry_time) -> dict`
- `shadow_trades`에 INSERT (status='active')

#### `def update_shadow_trade(shadow_trade_id, exit_price, exit_time, shadow_pnl, max_10m=None, max_30m=None, max_eod=None) -> dict`
- status='closed' UPDATE

#### `def get_today_shadow_trades(trade_date: str) -> list[dict]`
- 조회

#### `def get_shadow_summary(trade_date: str) -> dict`
- 총 건수, 평균 가상 손익, 양성 비율 등 집계

---

## 작업 3 — Missed Opportunity Tracker 서비스

파일: `backend/services/engine/missed_opportunity.py`

```python
"""Missed Opportunity Tracker."""
```

#### `def record_missed_opportunity(trade_date, symbol, symbol_name, missed_stage, missed_reason, price_at_missed, max_10m=None, max_30m=None, max_eod=None, improvement_candidate=False) -> dict`
- `missed_opportunities`에 INSERT

#### `def get_today_missed(trade_date: str) -> list[dict]`
#### `def get_improvement_candidates(trade_date: str) -> list[dict]`
- `improvement_candidate=1` 인 것만

---

## 작업 4 — False Positive Tracker 서비스

파일: `backend/services/engine/false_positive.py`

```python
"""False Positive Tracker."""
```

#### `def record_false_positive(trade_date, symbol, symbol_name, false_positive_type, original_score=None, original_confidence=None, assigned_profile=None, entry_reason='', loss_reason='', exit_reason='', applied_knowledge_ids=None, applied_memory_ids=None, suggested_penalty=None) -> dict`
- `false_positive_cases`에 INSERT

#### `def get_today_false_positives(trade_date: str) -> list[dict]`

---

## 작업 5 — Confidence Calibration 서비스

파일: `backend/services/engine/confidence_calibration.py`

```python
"""Confidence Calibration — confidence 구간별 실제 성과 분석."""
```

#### `def get_confidence_bin(confidence: float) -> str`
- confidence ≥ 0.90 → 'ge090'
- 0.80 ≤ c < 0.90 → '80to90'
- 0.70 ≤ c < 0.80 → '70to80'
- 0.60 ≤ c < 0.70 → '60to70'
- c < 0.60 → 'lt060'

#### `def run_confidence_calibration(trade_date: str) -> dict`
- `trading_signals`에서 confidence, realized_pnl 조회
- bin별 집계 → `confidence_calibration_daily` 저장
- `confidence_calibration_bins` cumulative 업데이트
- 반환: bin별 expected vs actual win_rate

#### `def get_calibration_summary(trade_date: str) -> list[dict]`
- `confidence_calibration_daily` 조회

---

## 작업 6 — REST API 5세트

### `backend/api/routes/shadow_trading.py`
```python
router = APIRouter(prefix="/api/v1/shadow-trading", tags=["shadow-trading"])
```
| Method | Path | 설명 |
|--------|------|------|
| GET | `/today` | 오늘 shadow trades |
| GET | `/summary` | 오늘 집계 요약 |
| POST | `/` | shadow trade 수동 생성 (테스트용) |

### `backend/api/routes/missed_opportunity.py`
```python
router = APIRouter(prefix="/api/v1/missed-opportunity", tags=["missed-opportunity"])
```
| Method | Path | 설명 |
|--------|------|------|
| GET | `/today` | 오늘 기록 |
| GET | `/candidates` | improvement_candidate 목록 |

### `backend/api/routes/false_positive.py`
```python
router = APIRouter(prefix="/api/v1/false-positive", tags=["false-positive"])
```
| Method | Path | 설명 |
|--------|------|------|
| GET | `/today` | 오늘 기록 |

### `backend/api/routes/confidence_calibration.py`
```python
router = APIRouter(prefix="/api/v1/confidence-calibration", tags=["confidence-calibration"])
```
| Method | Path | 설명 |
|--------|------|------|
| GET | `/today` | 오늘 calibration |
| POST | `/run` | 수동 실행 |

### Knowledge Impact API 확장 (`backend/api/routes/expert_knowledge.py`)
기존 라우터에 추가:
```python
@router.get("/impact")
def get_knowledge_impact():
    """knowledge_impact_stats 조회."""
    ...
```

---

## 작업 7 — main.py 라우터 등록

```python
from .api.routes.shadow_trading import router as shadow_trading_router
from .api.routes.missed_opportunity import router as missed_opportunity_router
from .api.routes.false_positive import router as false_positive_router
from .api.routes.confidence_calibration import router as confidence_calibration_router

app.include_router(shadow_trading_router)
app.include_router(missed_opportunity_router)
app.include_router(false_positive_router)
app.include_router(confidence_calibration_router)
```

---

## 검증

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
  backend/main.py
```

---

## 완료 체크리스트

- [x] 작업 1 — DB 6개 테이블
- [x] 작업 2 — shadow_trading.py
- [x] 작업 3 — missed_opportunity.py
- [x] 작업 4 — false_positive.py
- [x] 작업 5 — confidence_calibration.py
- [x] 작업 6 — REST API 5세트
- [x] 작업 7 — main.py 라우터 등록
- [x] py_compile 전부 통과

결과는 `docs/agent-comm/OUTBOX_EXECUTOR_phase5b_backend.md`에 작성하라.
