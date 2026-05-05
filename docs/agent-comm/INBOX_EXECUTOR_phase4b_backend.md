# INBOX_EXECUTOR_phase4b_backend

## 역할
너는 Executor다. Phase 4B Expert Knowledge Base 백엔드를 구현하라.
완료 후 `docs/agent-comm/OUTBOX_EXECUTOR_phase4b_backend.md`에 결과를 작성하라.

---

## 작업 1 — DB 테이블 5개 추가 (backend/services/db.py)

`_schema_statements()` 에 아래 5개 테이블을 추가한다.

```sql
CREATE TABLE IF NOT EXISTS external_knowledge_sources (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'manual',  -- manual|rss|api
    description TEXT NOT NULL DEFAULT '',
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS strategy_knowledge_items (
    id              TEXT PRIMARY KEY,
    source_id       TEXT,                           -- external_knowledge_sources.id (nullable)
    title           TEXT NOT NULL,
    content         TEXT NOT NULL,
    scope           TEXT NOT NULL,                  -- S3_UNIVERSE_FILTER|S4_HYBRID_SCREENING|S5_DAILY_PLAN|ALL
    category        TEXT NOT NULL DEFAULT 'general', -- timing|sector|profile|risk|general
    status          TEXT NOT NULL DEFAULT 'pending', -- pending|approved|rejected
    auto_inject     INTEGER NOT NULL DEFAULT 0,      -- 승인 후 자동 주입 여부
    priority        INTEGER NOT NULL DEFAULT 5,      -- 1(높음)~10(낮음)
    created_at      TEXT NOT NULL,
    approved_at     TEXT,
    expires_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_knowledge_items_scope ON strategy_knowledge_items(scope);
CREATE INDEX IF NOT EXISTS idx_knowledge_items_status ON strategy_knowledge_items(status);

CREATE TABLE IF NOT EXISTS knowledge_prompt_contexts (
    id              TEXT PRIMARY KEY,
    trade_date      TEXT NOT NULL,
    scope           TEXT NOT NULL,
    knowledge_ids   TEXT NOT NULL DEFAULT '[]',  -- JSON array
    prompt_snippet  TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_knowledge_ctx_trade_date ON knowledge_prompt_contexts(trade_date);

CREATE TABLE IF NOT EXISTS knowledge_impact_stats (
    id              TEXT PRIMARY KEY,
    knowledge_id    TEXT NOT NULL,
    trade_date      TEXT NOT NULL,
    scope           TEXT NOT NULL,
    applied         INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_approval_logs (
    id              TEXT PRIMARY KEY,
    knowledge_id    TEXT NOT NULL,
    action          TEXT NOT NULL,  -- approve|reject
    reason          TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL
);
```

---

## 작업 2 — Expert Knowledge 서비스 신규 작성

파일: `backend/services/engine/expert_knowledge.py`

```python
"""Expert Knowledge Base — 운영자 정성 지식 관리 및 S3/S4/S5 주입."""
```

### 구현할 함수

#### `def create_knowledge_item(title, content, scope, category='general', priority=5, auto_inject=False, expires_at=None) -> dict`
- `strategy_knowledge_items`에 INSERT (status='pending')
- 생성된 item dict 반환

#### `def list_knowledge_items(scope=None, status=None) -> list[dict]`
- `strategy_knowledge_items` 조회
- scope, status 필터 옵션

#### `def get_knowledge_item(item_id) -> dict | None`
- 단건 조회

#### `def approve_knowledge(item_id, reason='') -> dict`
- status → 'approved', approved_at 설정
- `knowledge_approval_logs`에 action='approve' 기록
- 반환: {"ok": True, "item_id": ..., "status": "approved"}

#### `def reject_knowledge(item_id, reason='') -> dict`
- status → 'rejected'
- `knowledge_approval_logs`에 action='reject' 기록
- 반환: {"ok": True, "item_id": ..., "status": "rejected"}

#### `def get_active_knowledge(scope: str) -> list[dict]`
- `status='approved'` AND (`scope=scope` OR `scope='ALL'`)
- `expires_at`이 있고 이미 지난 것은 제외
- `priority ASC` 정렬 (낮을수록 우선)
- S3/S4/S5에서 호출할 핵심 함수

#### `def build_knowledge_prompt_snippet(knowledge_items: list[dict]) -> str`
- 지식 목록을 프롬프트에 삽입할 텍스트로 변환
- 예:
  ```
  ## 📚 Expert Knowledge (운영자 승인 전략 지식)
  - [timing/S4] THEME_SPIKE는 오전 9:00~9:30에 집중된다.
  - [sector/S5] ETF 리밸런싱 주간 대형주 수급 증가 효과가 있다.
  ```

---

## 작업 3 — REST API 신규 작성

파일: `backend/api/routes/expert_knowledge.py`

```python
router = APIRouter(prefix="/api/v1/expert-knowledge", tags=["expert-knowledge"])
```

| Method | Path | 설명 |
|--------|------|------|
| POST | `/` | knowledge item 생성 |
| GET | `/` | 목록 조회 (scope, status 쿼리 파라미터) |
| GET | `/{item_id}` | 단건 조회 |
| POST | `/{item_id}/approve` | 승인 (body: `{"reason": "..."}` 옵션) |
| POST | `/{item_id}/reject` | 거부 (body: `{"reason": "..."}` 옵션) |
| GET | `/active/{scope}` | scope별 approved 항목 조회 |

**POST `/` request body:**
```json
{
  "title": "string",
  "content": "string",
  "scope": "S3_UNIVERSE_FILTER|S4_HYBRID_SCREENING|S5_DAILY_PLAN|ALL",
  "category": "timing|sector|profile|risk|general",
  "priority": 5,
  "auto_inject": false,
  "expires_at": null
}
```

---

## 작업 4 — S3/S4/S5에 knowledge_refs 주입

### 4-1. universe_filter.py 수정
`run_universe_filter()` 에서 memory 주입 코드 바로 뒤에:
```python
from .expert_knowledge import get_active_knowledge, build_knowledge_prompt_snippet

knowledge_items = get_active_knowledge(scope="S3_UNIVERSE_FILTER")
knowledge_refs = [k["id"] for k in knowledge_items]
```
결과 반환에 `knowledge_refs`, `knowledge_count` 추가.

### 4-2. hybrid_screening.py 수정
`_build_prompt()` 에 `knowledge_items` 파라미터 추가:
```python
def _build_prompt(candidates_30, market_tone, memories=None, knowledge_items=None):
```

프롬프트에 knowledge snippet 삽입 (memory_section 뒤에):
```python
if knowledge_items:
    knowledge_section = build_knowledge_prompt_snippet(knowledge_items)
else:
    knowledge_section = ""
```

`run_hybrid_screening()` 에서:
```python
from .expert_knowledge import get_active_knowledge

knowledge_items = get_active_knowledge(scope="S4_HYBRID_SCREENING")
knowledge_refs = [k["id"] for k in knowledge_items]
prompt = _build_prompt(items, market_tone, memories=memories, knowledge_items=knowledge_items)
```
결과에 `knowledge_refs`, `knowledge_count` 추가.

### 4-3. daily_plan.py 수정
`_build_prompt()` 에 `knowledge_items` 파라미터 추가.
프롬프트에 knowledge snippet 삽입 (memory_section 뒤에).

`run_daily_plan_generation()` 에서:
```python
from .expert_knowledge import get_active_knowledge

knowledge_items = get_active_knowledge(scope="S5_DAILY_PLAN")
used_knowledge_ids = [k["id"] for k in knowledge_items]
```
DB INSERT에 `used_knowledge_ids` 컬럼 추가 (먼저 마이그레이션 필요):
```python
("used_knowledge_ids", "ALTER TABLE daily_trading_plans ADD COLUMN used_knowledge_ids TEXT NOT NULL DEFAULT '[]'"),
```
`_migration_statements()`에 추가.

---

## 작업 5 — Context Preview API 업데이트 (backend/api/routes/pipeline.py)

기존 S3/S4/S5 context-preview에 knowledge 정보도 포함:
```python
from ...services.engine.expert_knowledge import get_active_knowledge

# 각 엔드포인트에 추가:
knowledge_items = get_active_knowledge(scope="S3_UNIVERSE_FILTER")
# payload에 knowledge_items, knowledge_count 추가
```

---

## 작업 6 — main.py 라우터 등록

```python
from .api.routes.expert_knowledge import router as expert_knowledge_router
app.include_router(expert_knowledge_router)
```

---

## 검증

```bash
python3 -m py_compile \
  backend/services/db.py \
  backend/services/engine/expert_knowledge.py \
  backend/services/engine/universe_filter.py \
  backend/services/engine/hybrid_screening.py \
  backend/services/engine/daily_plan.py \
  backend/api/routes/expert_knowledge.py \
  backend/api/routes/pipeline.py \
  backend/main.py
```

DB 테이블 확인:
```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('data/stock_trading_bot.sqlite3')
tables = conn.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%knowledge%'\").fetchall()
print([t[0] for t in tables])
conn.close()
"
```
→ `external_knowledge_sources`, `strategy_knowledge_items`, `knowledge_prompt_contexts`, `knowledge_impact_stats`, `knowledge_approval_logs` 5개 출력 확인

---

## 완료 체크리스트

- [x] 작업 1 — DB 5개 테이블
- [x] 작업 2 — expert_knowledge.py 서비스
- [x] 작업 3 — REST API
- [x] 작업 4 — S3/S4/S5 knowledge_refs 주입
- [x] 작업 5 — Context Preview API 업데이트
- [x] 작업 6 — main.py 라우터 등록
- [x] py_compile 전부 통과
- [x] DB 5개 테이블 확인

결과는 `docs/agent-comm/OUTBOX_EXECUTOR_phase4b_backend.md`에 작성하라.
