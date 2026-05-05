# INBOX_EXECUTOR_phase5a_backend

## 역할
너는 Executor다. Phase 5A 운영 안정화 백엔드를 구현하라.
완료 후 `docs/agent-comm/OUTBOX_EXECUTOR_phase5a_backend.md`에 결과를 작성하라.

---

## 작업 1 — DB 테이블 3개 추가 (backend/services/db.py)

`_schema_statements()` 에 추가한다.
`human_approval_queue` 와 `approval_decision_logs` 는 이미 존재하므로 추가하지 않는다.

```sql
CREATE TABLE IF NOT EXISTS data_quality_events (
    id          TEXT PRIMARY KEY,
    trade_date  TEXT NOT NULL,
    event_type  TEXT NOT NULL,  -- tick_delay|price_diverge|volume_missing|orderbook_missing|db_write_fail|llm_parse_error|duplicate_tick|symbol_mapping_error
    severity    TEXT NOT NULL DEFAULT 'WARNING',  -- INFO|WARNING|DEGRADED|BLOCK_NEW_ENTRY|EMERGENCY
    symbol      TEXT,
    detail      TEXT NOT NULL DEFAULT '',
    resolved    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dq_events_trade_date ON data_quality_events(trade_date);
CREATE INDEX IF NOT EXISTS idx_dq_events_severity ON data_quality_events(severity);

CREATE TABLE IF NOT EXISTS data_quality_snapshots (
    id              TEXT PRIMARY KEY,
    trade_date      TEXT NOT NULL,
    overall_status  TEXT NOT NULL DEFAULT 'NORMAL',  -- NORMAL|WARNING|DEGRADED|BLOCK_NEW_ENTRY|EMERGENCY
    event_counts    TEXT NOT NULL DEFAULT '{}',      -- JSON: {event_type: count}
    worst_severity  TEXT NOT NULL DEFAULT 'INFO',
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dq_snapshots_trade_date ON data_quality_snapshots(trade_date);

CREATE TABLE IF NOT EXISTS system_alerts (
    id          TEXT PRIMARY KEY,
    trade_date  TEXT NOT NULL,
    alert_type  TEXT NOT NULL,  -- risk_guard|daily_loss_limit|ws_delay|rest_error|db_fail|fill_missing|plan_validation_fail|preflight_block|dq_degraded|emergency_halt
    severity    TEXT NOT NULL DEFAULT 'WARNING',  -- INFO|WARNING|CRITICAL
    title       TEXT NOT NULL,
    detail      TEXT NOT NULL DEFAULT '',
    acknowledged INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alerts_trade_date ON system_alerts(trade_date);
CREATE INDEX IF NOT EXISTS idx_alerts_acknowledged ON system_alerts(acknowledged);
```

---

## 작업 2 — Data Quality Guard 서비스

파일: `backend/services/engine/data_quality_guard.py`

```python
"""Data Quality Guard — 데이터 이상 감지 및 전체 품질 상태 관리."""
```

### 구현 함수

#### `def record_dq_event(event_type, severity='WARNING', symbol=None, detail='') -> str`
- `data_quality_events`에 INSERT
- event_id 반환
- severity 우선순위: INFO < WARNING < DEGRADED < BLOCK_NEW_ENTRY < EMERGENCY

#### `def get_today_dq_status(trade_date: str) -> dict`
- 오늘 `data_quality_events` 조회
- event_type별 카운트 집계
- worst_severity 결정 (우선순위 기준)
- overall_status 결정 로직:
  - EMERGENCY 이벤트 >= 1 → EMERGENCY
  - BLOCK_NEW_ENTRY 이벤트 >= 1 → BLOCK_NEW_ENTRY
  - DEGRADED 이벤트 >= 3 → DEGRADED
  - WARNING 이벤트 >= 5 → WARNING
  - 그 외 → NORMAL
- 반환: `{overall_status, worst_severity, event_counts, events}`

#### `def take_dq_snapshot(trade_date: str) -> dict`
- `get_today_dq_status()` 호출
- `data_quality_snapshots`에 저장
- 반환: snapshot dict

#### `def get_latest_dq_snapshot(trade_date: str) -> dict | None`
- `data_quality_snapshots`에서 최신 스냅샷 조회

---

## 작업 3 — Alert Center 서비스

파일: `backend/services/engine/alert_center.py`

```python
"""Alert Center — 시스템 이상 알림 저장 및 조회."""
```

### 구현 함수

#### `def create_alert(alert_type, title, severity='WARNING', detail='') -> dict`
- `system_alerts`에 INSERT
- 반환: alert dict

#### `def get_today_alerts(trade_date: str, unacknowledged_only=False) -> list[dict]`
- `system_alerts` 조회, 최신순 정렬

#### `def acknowledge_alert(alert_id: str) -> bool`
- `acknowledged=1` UPDATE

#### `def get_alert_summary(trade_date: str) -> dict`
- 오늘 알림 수, severity별 카운트, 미확인 수 반환

---

## 작업 4 — Human Approval Queue 서비스

파일: `backend/services/engine/human_approval.py`

`human_approval_queue`, `approval_decision_logs` 테이블은 Phase 4B에서 이미 생성됐다.

### 구현 함수

#### `def create_approval_request(change_type, title, description, payload_json='{}') -> dict`
- `human_approval_queue`에 INSERT (status='pending')
- change_type: `risk_profile_change|rulepack_change|risk_guard_change|knowledge_change|scoring_weight_change|confidence_threshold_change`

#### `def list_approval_requests(status=None) -> list[dict]`
- 목록 조회, 최신순

#### `def approve_request(request_id, reason='') -> dict`
- status → 'approved'
- `approval_decision_logs`에 기록

#### `def reject_request(request_id, reason='') -> dict`
- status → 'rejected'
- `approval_decision_logs`에 기록

#### `def defer_request(request_id, reason='') -> dict`
- status → 'deferred'
- `approval_decision_logs`에 기록

---

## 작업 5 — REST API 3세트

### `backend/api/routes/data_quality.py`
```python
router = APIRouter(prefix="/api/v1/data-quality", tags=["data-quality"])
```
| Method | Path | 설명 |
|--------|------|------|
| GET | `/status` | 오늘 DQ 상태 조회 |
| GET | `/snapshot` | 최신 스냅샷 조회 |
| POST | `/snapshot` | 스냅샷 생성 |
| POST | `/event` | 이벤트 수동 기록 (테스트용) |

### `backend/api/routes/alert_center.py`
```python
router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])
```
| Method | Path | 설명 |
|--------|------|------|
| GET | `/` | 오늘 알림 목록 |
| POST | `/` | 알림 생성 |
| POST | `/{alert_id}/acknowledge` | 알림 확인 처리 |
| GET | `/summary` | 알림 요약 |

### `backend/api/routes/human_approval.py`
```python
router = APIRouter(prefix="/api/v1/approval", tags=["approval"])
```
| Method | Path | 설명 |
|--------|------|------|
| POST | `/` | 승인 요청 생성 |
| GET | `/` | 목록 조회 (status 쿼리 파라미터) |
| POST | `/{request_id}/approve` | 승인 |
| POST | `/{request_id}/reject` | 거부 |
| POST | `/{request_id}/defer` | 보류 |

---

## 작업 6 — main.py 라우터 등록

```python
from .api.routes.data_quality import router as data_quality_router
from .api.routes.alert_center import router as alert_center_router
from .api.routes.human_approval import router as human_approval_router

app.include_router(data_quality_router)
app.include_router(alert_center_router)
app.include_router(human_approval_router)
```

---

## 검증

```bash
python3 -m py_compile \
  backend/services/db.py \
  backend/services/engine/data_quality_guard.py \
  backend/services/engine/alert_center.py \
  backend/services/engine/human_approval.py \
  backend/api/routes/data_quality.py \
  backend/api/routes/alert_center.py \
  backend/api/routes/human_approval.py \
  backend/main.py
```

DB 테이블 확인:
```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('data/stock_trading_bot.sqlite3')
tables = conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()
print(sorted([t[0] for t in tables]))
conn.close()
"
```
→ `data_quality_events`, `data_quality_snapshots`, `system_alerts` 포함 확인

---

## 완료 체크리스트

- [x] 작업 1 — DB 3개 테이블
- [x] 작업 2 — data_quality_guard.py
- [x] 작업 3 — alert_center.py
- [x] 작업 4 — human_approval.py
- [x] 작업 5 — REST API 3세트
- [x] 작업 6 — main.py 라우터 등록
- [x] py_compile 전부 통과
- [x] DB 테이블 확인

결과는 `docs/agent-comm/OUTBOX_EXECUTOR_phase5a_backend.md`에 작성하라.
