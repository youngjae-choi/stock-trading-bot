# INBOX_EXECUTOR_phase4a_backend

## 역할
너는 Executor다. Phase 4A 백엔드를 구현하라.
완료 후 `docs/agent-comm/OUTBOX_EXECUTOR_phase4a_backend.md`에 결과를 작성하라.

## 목표
S3/S4/S5 파이프라인에 Learning Memory를 주입하고,
Context Preview API 3개를 추가한다.

---

## 사전 확인

### DB 컬럼 추가 (backend/services/db.py)
`daily_trading_plans` 테이블에 `used_learning_memory_ids` 컬럼이 없다.
`_migration_statements()` 함수에 추가:

```python
("used_learning_memory_ids", "ALTER TABLE daily_trading_plans ADD COLUMN used_learning_memory_ids TEXT NOT NULL DEFAULT '[]'"),
```

---

## 작업 1 — S3 메모리 주입 (backend/services/engine/universe_filter.py)

### 변경 위치
`run_universe_filter()` 함수 내부.

### 변경 내용

1. 함수 상단에서 `S3_UNIVERSE_FILTER` 메모리 조회:
```python
from .learning_memory import get_active_memories

memories = get_active_memories(scope="S3_UNIVERSE_FILTER")
memory_refs = [m["memory_id"] for m in memories]
```

2. 메모리 기반 가중치 보정:
```python
def _apply_memory_adjustments(weights: dict, memories: list[dict]) -> dict:
    """S3 메모리 기반 가중치 미세 조정."""
    for mem in memories:
        rec = mem.get("recommendation", {})
        if rec.get("type") == "weight_adjust":
            field = rec.get("field", "")
            delta = float(rec.get("delta", 0.0))
            if field in weights:
                weights[field] = max(0.0, min(1.0, weights[field] + delta))
    # 합계를 1.0으로 정규화
    total = sum(weights.values())
    if total > 0:
        weights = {k: v / total for k, v in weights.items()}
    return weights
```

`_get_tone_weights()` 호출 직후에 `_apply_memory_adjustments(weights, memories)` 적용.

3. DB 저장 시 `memory_refs` 포함:
기존 INSERT 쿼리에 `memory_refs` 컬럼이 없으면 추가하거나,
결과 dict에 `memory_refs` 키를 추가해서 반환한다.

**단, `universe_filter_results` 테이블에 memory_refs 컬럼이 없으면
테이블에 추가하지 말고 반환 dict에만 포함한다.**
(테이블 구조 변경은 최소화)

4. `run_universe_filter()` 반환값에 추가:
```python
result["memory_refs"] = memory_refs
result["memory_count"] = len(memories)
```

---

## 작업 2 — S4 메모리 주입 (backend/services/engine/hybrid_screening.py)

### 변경 위치
`_build_prompt()` 함수와 `run_hybrid_screening()` 함수.

### 변경 내용

1. `_build_prompt()` 시그니처 변경:
```python
def _build_prompt(candidates_30: list[dict], market_tone: dict | None, memories: list[dict] | None = None) -> str:
```

2. 프롬프트에 메모리 섹션 추가:
```python
if memories:
    memory_lines = []
    for m in memories:
        memory_lines.append(f"- [{m.get('category','?')}] {m.get('summary','')}")
    memory_section = "## 📌 Learning Memory (어제 복기 결과 — 반드시 반영)\n" + "\n".join(memory_lines) + "\n"
else:
    memory_section = ""
```

프롬프트 템플릿에서 `{market_tone_json}` 섹션 바로 뒤에 `{memory_section}` 삽입.

3. `run_hybrid_screening()` 내부에서 메모리 조회 후 `_build_prompt()`에 전달:
```python
from .learning_memory import get_active_memories

memories = get_active_memories(scope="S4_HYBRID_SCREENING")
memory_refs = [m["memory_id"] for m in memories]

prompt = _build_prompt(items, market_tone, memories=memories)
```

4. DB 저장 dict에 `memory_refs`, `memory_count` 추가:
기존 `hybrid_screening_results` 테이블 INSERT 시 memory_refs를 **컬럼이 없으면 반환 dict에만** 포함.
반환 결과에 추가:
```python
result["memory_refs"] = memory_refs
result["memory_count"] = len(memories)
```

---

## 작업 3 — S5 메모리 주입 (backend/services/engine/daily_plan.py)

### 변경 위치
`_build_prompt()` 함수와 `run_daily_plan_generation()` 함수.

### 변경 내용

1. `_build_prompt()` 시그니처 변경:
```python
def _build_prompt(candidates: list[dict], market_tone_data: dict | None, memories: list[dict] | None = None) -> str:
```

2. 프롬프트에 메모리 섹션 추가 (## 후보 종목 섹션 바로 위):
```python
if memories:
    memory_lines = []
    for m in memories:
        rec = m.get("recommendation", {})
        memory_lines.append(
            f"- [{m.get('scope','?')} / {m.get('category','?')}] {m.get('summary','')} "
            f"(권고: {rec.get('field','?')} = {rec.get('value','?')})"
        )
    memory_section = "\n## 📌 Learning Memory (어제 복기 결과 — daily_overrides 결정 시 반드시 반영)\n" + "\n".join(memory_lines) + "\n"
else:
    memory_section = ""
```

프롬프트 f-string에서 `## 후보 종목` 섹션 바로 앞에 `{memory_section}` 삽입.

3. `run_daily_plan_generation()` 내부에서 메모리 조회:
```python
from .learning_memory import get_active_memories

memories = get_active_memories(scope="S5_DAILY_PLAN")
used_memory_ids = [m["memory_id"] for m in memories]

prompt = _build_prompt(candidates, market_tone, memories=memories)
```

4. DB INSERT에 `used_learning_memory_ids` 포함:
```python
# INSERT 쿼리에 컬럼 추가
"used_learning_memory_ids": json.dumps(used_memory_ids)
```

INSERT 쿼리와 VALUES에 `used_learning_memory_ids` 추가.

---

## 작업 4 — Context Preview API 신규 작성

파일: `backend/api/routes/pipeline.py`

```python
"""Pipeline Context Preview API — S3/S4/S5에 주입될 메모리 미리보기."""
from fastapi import APIRouter
from ...services.engine.learning_memory import get_active_memories

router = APIRouter(prefix="/api/v1/pipeline", tags=["pipeline"])
```

### 엔드포인트 3개

```python
@router.get("/S3/context-preview")
def s3_context_preview():
    memories = get_active_memories(scope="S3_UNIVERSE_FILTER")
    return {"ok": True, "payload": {"scope": "S3_UNIVERSE_FILTER", "memories": memories, "count": len(memories)}}

@router.get("/S4/context-preview")
def s4_context_preview():
    memories = get_active_memories(scope="S4_HYBRID_SCREENING")
    return {"ok": True, "payload": {"scope": "S4_HYBRID_SCREENING", "memories": memories, "count": len(memories)}}

@router.get("/S5/context-preview")
def s5_context_preview():
    memories = get_active_memories(scope="S5_DAILY_PLAN")
    # S5는 daily_overrides 권고도 미리 계산
    overrides_preview = {}
    for m in memories:
        rec = m.get("recommendation", {})
        if rec.get("field"):
            overrides_preview[rec["field"]] = rec.get("value")
    return {"ok": True, "payload": {
        "scope": "S5_DAILY_PLAN",
        "memories": memories,
        "count": len(memories),
        "overrides_preview": overrides_preview,
    }}
```

---

## 작업 5 — main.py 라우터 등록

```python
from .api.routes.pipeline import router as pipeline_router
app.include_router(pipeline_router)
```

---

## 검증

```bash
python3 -m py_compile \
  backend/services/db.py \
  backend/services/engine/universe_filter.py \
  backend/services/engine/hybrid_screening.py \
  backend/services/engine/daily_plan.py \
  backend/api/routes/pipeline.py \
  backend/main.py
```

Context Preview API 응답 확인:
```bash
curl -s http://127.0.0.1:8000/api/v1/pipeline/S3/context-preview | python3 -m json.tool | head -10
curl -s http://127.0.0.1:8000/api/v1/pipeline/S4/context-preview | python3 -m json.tool | head -10
curl -s http://127.0.0.1:8000/api/v1/pipeline/S5/context-preview | python3 -m json.tool | head -10
```

---

## 완료 체크리스트

- [x] DB 마이그레이션 — used_learning_memory_ids 컬럼
- [x] S3 메모리 주입 — universe_filter.py
- [x] S4 메모리 주입 — hybrid_screening.py
- [x] S5 메모리 주입 — daily_plan.py
- [x] pipeline.py 신규 — Context Preview 3개 API
- [x] main.py 라우터 등록
- [x] py_compile 전부 통과
- [x] Context Preview API 200 응답 확인

결과는 `docs/agent-comm/OUTBOX_EXECUTOR_phase4a_backend.md`에 작성하라.
