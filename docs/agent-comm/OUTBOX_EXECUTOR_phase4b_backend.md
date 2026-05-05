# OUTBOX_EXECUTOR_phase4b_backend

## 역할
Executor

## 작업 결과 요약
Phase 4B Expert Knowledge Base 백엔드 구현을 완료했다.

## 변경 파일
- `backend/services/db.py`
- `backend/services/engine/expert_knowledge.py`
- `backend/api/routes/expert_knowledge.py`
- `backend/services/engine/universe_filter.py`
- `backend/services/engine/hybrid_screening.py`
- `backend/services/engine/daily_plan.py`
- `backend/api/routes/pipeline.py`
- `backend/main.py`
- `docs/agent-comm/OUTBOX_EXECUTOR_phase4b_backend.md`

## 구현 내용

### 작업 1 — DB 테이블 5개 추가
- `external_knowledge_sources`
- `strategy_knowledge_items`
- `knowledge_prompt_contexts`
- `knowledge_impact_stats`
- `knowledge_approval_logs`
- `strategy_knowledge_items.scope/status`, `knowledge_prompt_contexts.trade_date` 인덱스 추가
- `daily_trading_plans.used_knowledge_ids` 컬럼 추가
- 기존 DB용 `_migration_statements()`에 `used_knowledge_ids` 마이그레이션 추가

### 작업 2 — Expert Knowledge 서비스
신규 파일: `backend/services/engine/expert_knowledge.py`

구현 함수:
- `create_knowledge_item(...)`
- `list_knowledge_items(scope=None, status=None)`
- `get_knowledge_item(item_id)`
- `approve_knowledge(item_id, reason='')`
- `reject_knowledge(item_id, reason='')`
- `get_active_knowledge(scope)`
- `build_knowledge_prompt_snippet(knowledge_items)`

추가 처리:
- scope/category/status 검증
- priority 1~10 범위 보정
- 승인/거부 로그 기록
- expires_at 만료 항목 제외
- 시작/성공/경고/실패 로그 추가

### 작업 3 — REST API
신규 파일: `backend/api/routes/expert_knowledge.py`

등록 엔드포인트:
- `POST /api/v1/expert-knowledge/`
- `GET /api/v1/expert-knowledge/`
- `GET /api/v1/expert-knowledge/{item_id}`
- `POST /api/v1/expert-knowledge/{item_id}/approve`
- `POST /api/v1/expert-knowledge/{item_id}/reject`
- `GET /api/v1/expert-knowledge/active/{scope}`

추가 처리:
- Pydantic request body 검증
- 잘못된 scope/status/category는 400
- 없는 item은 404
- 서버 실패는 내부 로그 후 500

### 작업 4 — S3/S4/S5 knowledge_refs 주입
- S3 `run_universe_filter()` 결과에 `knowledge_refs`, `knowledge_count` 추가
- S4 `_build_prompt()`에 `knowledge_items` 파라미터 추가
- S4 프롬프트에 Expert Knowledge snippet 삽입
- S4 결과에 `knowledge_refs`, `knowledge_count` 추가
- S5 `_build_prompt()`에 `knowledge_items` 파라미터 추가
- S5 프롬프트에 Expert Knowledge snippet 삽입
- S5 저장 시 `used_knowledge_ids` 저장
- S5 반환값에 `used_knowledge_ids`, `knowledge_count` 추가

### 작업 5 — Context Preview API 업데이트
- S3/S4/S5 context-preview payload에 `knowledge_items`, `knowledge_count` 추가

### 작업 6 — main.py 라우터 등록
- `expert_knowledge_router` import 및 `app.include_router(expert_knowledge_router)` 등록

## 검증 결과

### py_compile
명령:
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

결과:
- 통과

### DB 테이블 확인
명령:
```bash
python3 -c "from backend.services.db import initialize_database; initialize_database()"
python3 -c "import sqlite3; conn = sqlite3.connect('data/stock_trading_bot.sqlite3'); tables = conn.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%knowledge%' ORDER BY name\").fetchall(); cols = [r[1] for r in conn.execute('PRAGMA table_info(daily_trading_plans)').fetchall()]; print([t[0] for t in tables]); print('used_knowledge_ids' in cols); conn.close()"
```

결과:
```text
['external_knowledge_sources', 'knowledge_approval_logs', 'knowledge_impact_stats', 'knowledge_prompt_contexts', 'strategy_knowledge_items']
True
```

### 서비스 단위 검증
임시 DB(`/tmp/phase4b_expert_knowledge_unit.sqlite3`)에서 다음 흐름 확인:
- knowledge item 생성
- 승인
- active 조회
- prompt snippet 생성

결과:
```text
created True pending
approved approved
active_count 1
snippet_has_content True
```

### 라우터 함수 직접 호출 검증
임시 DB(`/tmp/phase4b_route_direct.sqlite3`)에서 다음 흐름 확인:
- `create_item`
- `approve_item`
- `get_active`

결과:
```text
call create
created True
approve approved
active 1
```

### HTTP/API 호출 확인 필요
현재 Codex 샌드박스에서 로컬 소켓 생성이 차단되어 `uvicorn` 바인딩 및 `urllib` 로컬 접속이 실패했다.

확인된 오류:
```text
ERROR: could not bind on any address out of [('127.0.0.1', 8765)]
PermissionError: [Errno 1] Operation not permitted
```

또한 `fastapi.testclient.TestClient` POST 호출은 이 환경에서 응답 없이 멈춰 `timeout`으로 중단했다.
서비스 함수와 라우터 함수 직접 호출은 정상 확인했으나, 실제 브라우저/HTTP 호출은 PM 또는 서버 권한이 있는 환경에서 추가 확인 필요.

## 완료 체크리스트
- [x] 작업 1 — DB 5개 테이블
- [x] 작업 2 — expert_knowledge.py 서비스
- [x] 작업 3 — REST API
- [x] 작업 4 — S3/S4/S5 knowledge_refs 주입
- [x] 작업 5 — Context Preview API 업데이트
- [x] 작업 6 — main.py 라우터 등록
- [x] py_compile 전부 통과
- [x] DB 5개 테이블 확인
- [x] 서비스 단위 검증
- [x] 라우터 함수 직접 호출 검증
- [ ] 실제 HTTP/API 호출 검증 — 샌드박스 소켓 제한으로 확인 필요

## 리스크 및 확인 필요
- 실제 HTTP API 호출은 로컬 바인딩 권한이 있는 개발 서버에서 재확인해야 한다.
- `TestClient` POST hang은 코드 오류보다는 현재 실행 환경 이슈로 보이나, 별도 환경에서 재현 여부 확인이 필요하다.
- 기존 작업 트리에 이미 다수의 미커밋 수정/신규 파일이 있어 커밋은 수행하지 않았다. Codex는 프로젝트 규칙상 git commit 권한이 없다.
