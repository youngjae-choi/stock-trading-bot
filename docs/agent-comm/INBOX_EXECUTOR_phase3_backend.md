# INBOX_EXECUTOR_phase3_backend

## 역할
너는 Executor다. 아래 지시대로 Phase 3 백엔드를 구현하고
`docs/agent-comm/OUTBOX_EXECUTOR_phase3_backend.md`에 결과를 작성하라.

## 구현 목표
S10 Review & Audit + S11 Learning Memory Builder 백엔드 전체 구현.

---

## 작업 1 — DB 마이그레이션 (backend/services/db.py)

`_schema_statements()` 함수에 아래 7개 테이블을 추가한다.
기존 테이블은 건드리지 않는다.

```sql
CREATE TABLE IF NOT EXISTS daily_review_reports (
    id              TEXT PRIMARY KEY,
    trade_date      TEXT NOT NULL,
    total_trades    INTEGER NOT NULL DEFAULT 0,
    win_count       INTEGER NOT NULL DEFAULT 0,
    loss_count      INTEGER NOT NULL DEFAULT 0,
    total_pnl       REAL NOT NULL DEFAULT 0.0,
    profile_summary TEXT NOT NULL DEFAULT '{}',   -- JSON: {profile: {count, win, pnl}}
    exit_summary    TEXT NOT NULL DEFAULT '{}',   -- JSON: {exit_reason: {count, avg_pnl}}
    trailing_quality TEXT NOT NULL DEFAULT '{}',  -- JSON: {avg_recovery_rate, early_exit_rate}
    no_trade_count  INTEGER NOT NULL DEFAULT 0,
    memory_count    INTEGER NOT NULL DEFAULT 0,   -- S11이 생성한 메모리 수
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_daily_review_trade_date ON daily_review_reports(trade_date);

CREATE TABLE IF NOT EXISTS learning_memories (
    memory_id           TEXT PRIMARY KEY,
    trade_date          TEXT NOT NULL,
    scope               TEXT NOT NULL,  -- S3_UNIVERSE_FILTER|S4_HYBRID_SCREENING|S5_DAILY_PLAN
    category            TEXT NOT NULL,  -- profile_allocation|exit_rule|universe_filter|screening_weight
    summary             TEXT NOT NULL,
    evidence            TEXT NOT NULL DEFAULT '{}',   -- JSON
    recommendation      TEXT NOT NULL DEFAULT '{}',   -- JSON
    auto_apply_allowed  INTEGER NOT NULL DEFAULT 0,   -- 0|1
    requires_approval   INTEGER NOT NULL DEFAULT 0,   -- 0|1
    status              TEXT NOT NULL DEFAULT 'active', -- active|applied|expired|rejected
    expires_at          TEXT,
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_learning_memories_trade_date ON learning_memories(trade_date);
CREATE INDEX IF NOT EXISTS idx_learning_memories_scope ON learning_memories(scope);
CREATE INDEX IF NOT EXISTS idx_learning_memories_status ON learning_memories(status);

CREATE TABLE IF NOT EXISTS profile_performance_daily (
    id          TEXT PRIMARY KEY,
    trade_date  TEXT NOT NULL,
    profile     TEXT NOT NULL,  -- LOW_VOL|MID_VOL|HIGH_VOL|THEME_SPIKE
    trade_count INTEGER NOT NULL DEFAULT 0,
    win_count   INTEGER NOT NULL DEFAULT 0,
    total_pnl   REAL NOT NULL DEFAULT 0.0,
    avg_pnl     REAL NOT NULL DEFAULT 0.0,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_profile_perf_trade_date ON profile_performance_daily(trade_date);

CREATE TABLE IF NOT EXISTS exit_reason_performance_daily (
    id          TEXT PRIMARY KEY,
    trade_date  TEXT NOT NULL,
    exit_reason TEXT NOT NULL,  -- trailing_stop|manual|time_exit|stop_loss|target_hit
    trade_count INTEGER NOT NULL DEFAULT 0,
    avg_pnl     REAL NOT NULL DEFAULT 0.0,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_exit_reason_trade_date ON exit_reason_performance_daily(trade_date);

CREATE TABLE IF NOT EXISTS trailing_quality_daily (
    id                  TEXT PRIMARY KEY,
    trade_date          TEXT NOT NULL,
    avg_recovery_rate   REAL NOT NULL DEFAULT 0.0,  -- 평균 고점 대비 실제 청산 수익 비율
    early_exit_rate     REAL NOT NULL DEFAULT 0.0,  -- 조기 청산 비율 (수익이 목표 미달)
    total_trailing_exits INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trailing_quality_trade_date ON trailing_quality_daily(trade_date);

CREATE TABLE IF NOT EXISTS no_trade_daily_reasons (
    id          TEXT PRIMARY KEY,
    trade_date  TEXT NOT NULL,
    reason      TEXT NOT NULL,  -- market_halt|no_candidates|risk_guard|data_quality|other
    detail      TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_no_trade_trade_date ON no_trade_daily_reasons(trade_date);

CREATE TABLE IF NOT EXISTS candidate_no_entry_reasons (
    id          TEXT PRIMARY KEY,
    trade_date  TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    reason      TEXT NOT NULL,  -- confidence_low|vwap_miss|volume_miss|risk_guard|preflight|data_quality|time_expired|overheating|knowledge_excluded
    detail      TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_candidate_no_entry_trade_date ON candidate_no_entry_reasons(trade_date);
```

---

## 작업 2 — S10 Review & Audit 서비스 신규 작성

파일: `backend/services/engine/review_audit.py`

```python
"""S10 Review & Audit — 당일 매매 결과 분석 서비스."""
```

### 구현할 함수

#### `async def run_review_audit(trade_date: str) -> dict`
1. `trading_signals` 테이블에서 `trade_date` 당일 체결 완료 신호 조회
   - `status IN ('filled', 'partial_fill', 'preflight_blocked', 'cancelled')`
2. **총계 계산**: total_trades, win_count, loss_count, total_pnl
   - win: `realized_pnl > 0`, loss: `realized_pnl <= 0`
   - `realized_pnl` 컬럼이 없으면 0으로 처리
3. **Risk Profile별 성과** → `profile_performance_daily` 저장
   - 신호의 `risk_profile` 컬럼 기준으로 집계
   - profile별: trade_count, win_count, total_pnl, avg_pnl
4. **Exit Reason별 성과** → `exit_reason_performance_daily` 저장
   - 신호의 `exit_reason` 컬럼 기준으로 집계
   - 없으면 'unknown'으로 처리
5. **Trailing Stop 품질** → `trailing_quality_daily` 저장
   - `exit_reason = 'trailing_stop'`인 건만 집계
   - avg_recovery_rate: 평균 `realized_pnl / entry_price * 100` (없으면 0.0)
   - early_exit_rate: trailing_stop 청산 중 pnl < 0.5% 비율
6. **무매매 처리**: total_trades == 0이면 `no_trade_daily_reasons`에 `reason='no_candidates'` 저장
7. `daily_review_reports`에 전체 요약 저장
8. 결과 dict 반환

#### `def get_review_report(trade_date: str) -> dict | None`
- `daily_review_reports`에서 trade_date 조회, profile_summary/exit_summary도 JOIN해서 반환

---

## 작업 3 — S11 Learning Memory Builder 서비스 신규 작성

파일: `backend/services/engine/learning_memory.py`

```python
"""S11 Learning Memory Builder — Review & Audit 결과를 구조화된 메모리로 변환."""
```

### auto_apply_allowed 판단 기준
| 조건 | auto_apply_allowed | requires_approval |
|------|-------------------|-------------------|
| trade_count >= 3 AND abs(avg_pnl) < 0.02 | True | False |
| trade_count >= 3 AND abs(avg_pnl) >= 0.02 | False | True |
| trade_count < 3 | False | False |

### 구현할 함수

#### `async def run_learning_memory_builder(trade_date: str) -> dict`
1. `daily_review_reports`에서 오늘 리뷰 결과 조회
   - 없으면 `{"ok": False, "reason": "no_review_report"}` 반환
2. `profile_performance_daily`에서 프로필별 성과 조회
3. **S5_DAILY_PLAN 메모리 생성** — 성과가 나쁜 프로필에 대해:
   - `win_rate < 0.4 AND trade_count >= 3` → 다음날 해당 프로필 포지션 수 제한 권고
   - auto_apply_allowed / requires_approval 판단 로직 적용
4. **S3_UNIVERSE_FILTER 메모리 생성** — trailing stop 품질 기반:
   - `early_exit_rate > 0.5` → 스크리닝 기준 강화 권고
5. **S4_HYBRID_SCREENING 메모리 생성** — exit reason 기반:
   - `exit_reason = 'stop_loss'` 비율이 30% 초과 → AI confidence 기준 상향 권고
6. 생성된 메모리들을 `learning_memories` 테이블에 저장
   - `expires_at` = trade_date 기준 +7일
7. 결과 dict 반환 (생성된 메모리 수, auto/approval 건수 포함)

#### `def get_today_memories(trade_date: str) -> list[dict]`
- `learning_memories`에서 trade_date 기준 조회, 전체 반환

#### `def get_active_memories(scope: str | None = None) -> list[dict]`
- `status = 'active'` 메모리 조회 (scope 필터 옵션)

---

## 작업 4 — REST API 작성

### `backend/api/routes/review_audit.py`
```python
router = APIRouter(prefix="/api/v1/review-audit", tags=["review-audit"])
```

| Method | Path | 함수 | 설명 |
|--------|------|------|------|
| POST | `/run` | `run()` | S10 수동 실행, 장중 금지 없음 |
| GET | `/today` | `get_today()` | 오늘 리뷰 결과 |
| GET | `/{date}` | `get_by_date(date)` | 날짜별 조회 |

### `backend/api/routes/learning_memory.py`
```python
router = APIRouter(prefix="/api/v1/learning-memory", tags=["learning-memory"])
```

| Method | Path | 함수 | 설명 |
|--------|------|------|------|
| POST | `/build` | `build()` | S11 수동 실행 |
| GET | `/today` | `get_today()` | 오늘 생성 메모리 목록 |
| GET | `/active` | `get_active()` | active 메모리 목록 (scope 쿼리 파라미터) |

---

## 작업 5 — 스케줄러 등록 (backend/services/scheduler.py)

기존 job 목록에 추가:

```python
# S10 Review & Audit (16:00 KST)
scheduler_instance.add_job(
    job_review_audit,
    CronTrigger(hour=16, minute=0, timezone="Asia/Seoul"),
    id="job_review_audit",
    name="S10 Review & Audit",
    replace_existing=True,
)

# S11 Learning Memory Builder (16:30 KST)
scheduler_instance.add_job(
    job_learning_memory,
    CronTrigger(hour=16, minute=30, timezone="Asia/Seoul"),
    id="job_learning_memory",
    name="S11 Learning Memory Builder",
    replace_existing=True,
)
```

job 함수 정의:
```python
async def job_review_audit():
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    await run_review_audit(today)

async def job_learning_memory():
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    await run_learning_memory_builder(today)
```

---

## 작업 6 — main.py 라우터 등록

`backend/main.py`에 추가:
```python
from .api.routes.review_audit import router as review_audit_router
from .api.routes.learning_memory import router as learning_memory_router

app.include_router(review_audit_router)
app.include_router(learning_memory_router)
```

---

## 검증 요구사항

1. `python3 -m py_compile` 모든 신규/수정 파일 통과
2. 임시 SQLite DB로 7개 테이블 생성 확인:
   ```bash
   python3 -c "
   import sys; sys.path.insert(0, '.')
   import os; os.environ.setdefault('APP_DB_PATH', '/tmp/phase3_test.sqlite3')
   from backend.services.db import initialize_database
   initialize_database()
   import sqlite3
   conn = sqlite3.connect('/tmp/phase3_test.sqlite3')
   tables = conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()
   print([t[0] for t in tables])
   "
   ```
3. 신규 테이블 7개 모두 출력 확인

---

## 완료 기준

- [x] 작업 1 — DB 7개 테이블
- [x] 작업 2 — review_audit.py
- [x] 작업 3 — learning_memory.py
- [x] 작업 4 — REST API 2개
- [x] 작업 5 — scheduler.py S10/S11 등록
- [x] 작업 6 — main.py 라우터 등록
- [x] py_compile 전부 통과
- [x] DB 테이블 생성 확인

결과는 `docs/agent-comm/OUTBOX_EXECUTOR_phase3_backend.md`에 작성하라.
