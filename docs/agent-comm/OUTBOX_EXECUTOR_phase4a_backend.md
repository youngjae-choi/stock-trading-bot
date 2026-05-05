# OUTBOX_EXECUTOR_phase4a_backend

## 작업 결과

Phase 4A 백엔드 작업을 수행했다.

### 변경 파일

- `backend/services/db.py`
- `backend/services/engine/universe_filter.py`
- `backend/services/engine/hybrid_screening.py`
- `backend/services/engine/daily_plan.py`
- `backend/api/routes/pipeline.py`
- `backend/main.py`

### 구현 내용

1. DB 마이그레이션
   - `daily_trading_plans.used_learning_memory_ids` 컬럼을 신규 스키마에 추가했다.
   - 기존 DB용 `_migration_statements()`에도 동일 컬럼 추가를 반영했다.
   - 서버 startup 중 실제 마이그레이션 로그 확인:
     - `DB migration: added column used_learning_memory_ids to daily_trading_plans`

2. S3 Universe Filter Learning Memory 주입
   - `S3_UNIVERSE_FILTER` 활성 메모리를 조회한다.
   - `weight_adjust` 타입 recommendation을 기반으로 `trade` / `volume` / `change` 가중치를 보정한다.
   - 보정 후 가중치 합계를 1.0으로 정규화한다.
   - 반환값에 `memory_refs`, `memory_count`를 추가했다.
   - DB 테이블 구조는 지시대로 변경하지 않았다.

3. S4 Hybrid Screening Learning Memory 주입
   - `_build_prompt()`에 `memories` 인자를 추가했다.
   - 시장 톤 섹션 뒤에 Learning Memory 섹션이 들어가도록 프롬프트를 확장했다.
   - `S4_HYBRID_SCREENING` 활성 메모리를 조회해 프롬프트에 전달한다.
   - 반환값에 `memory_refs`, `memory_count`를 추가했다.
   - DB 테이블 구조는 지시대로 변경하지 않았다.

4. S5 Daily Plan Learning Memory 주입
   - `_build_prompt()`에 `memories` 인자를 추가했다.
   - `## 후보 종목` 섹션 바로 앞에 Learning Memory 섹션이 들어가도록 프롬프트를 확장했다.
   - `S5_DAILY_PLAN` 활성 메모리를 조회해 프롬프트에 전달한다.
   - `daily_trading_plans.used_learning_memory_ids`에 사용된 메모리 ID 목록을 JSON으로 저장한다.
   - 반환값에 `used_learning_memory_ids`, `memory_count`를 추가했다.
   - `get_today_daily_plan()` 조회 결과에서도 `used_learning_memory_ids`를 JSON 배열로 파싱하도록 반영했다.

5. Context Preview API
   - 신규 파일 `backend/api/routes/pipeline.py`를 작성했다.
   - 신규 엔드포인트:
     - `GET /api/v1/pipeline/S3/context-preview`
     - `GET /api/v1/pipeline/S4/context-preview`
     - `GET /api/v1/pipeline/S5/context-preview`
   - S5 응답에는 `overrides_preview`를 포함한다.
   - 각 엔드포인트에 시작/완료 서버 로그를 추가했다.

6. 라우터 등록
   - `backend/main.py`에 `pipeline_router` import 및 `app.include_router(pipeline_router)`를 추가했다.

## 검증 결과

### py_compile

통과.

```bash
python3 -m py_compile \
  backend/services/db.py \
  backend/services/engine/universe_filter.py \
  backend/services/engine/hybrid_screening.py \
  backend/services/engine/daily_plan.py \
  backend/api/routes/pipeline.py \
  backend/main.py
```

### Context Preview API 검증

샌드박스 환경에서 로컬 소켓 바인딩이 제한되어 `uvicorn`의 8000/8001 포트 서버 실행은 실패했다.

- startup, DB 초기화, scheduler 등록까지는 정상 진행
- 이후 bind 단계에서 실패:
  - `could not bind on any address out of [('127.0.0.1', 8000)]`
  - `could not bind on any address out of [('127.0.0.1', 8001)]`

대신 동일 라우터 함수를 in-process로 호출해 응답 payload를 확인했다.

```text
S3 True S3_UNIVERSE_FILTER 0 False
S4 True S4_HYBRID_SCREENING 0 False
S5 True S5_DAILY_PLAN 0 True
```

확인 내용:

- S3 payload: `ok=True`, scope 정상, count 정상
- S4 payload: `ok=True`, scope 정상, count 정상
- S5 payload: `ok=True`, scope 정상, count 정상, `overrides_preview` 포함

## 완료 체크리스트

- [x] DB 마이그레이션 — `used_learning_memory_ids` 컬럼
- [x] S3 메모리 주입 — `universe_filter.py`
- [x] S4 메모리 주입 — `hybrid_screening.py`
- [x] S5 메모리 주입 — `daily_plan.py`
- [x] `pipeline.py` 신규 — Context Preview 3개 API
- [x] `main.py` 라우터 등록
- [x] `py_compile` 전부 통과
- [x] Context Preview 응답 구조 확인

## 확인 필요

- 실제 `curl http://127.0.0.1:8000/...` 검증은 현재 Codex 샌드박스의 로컬 바인딩 제한 때문에 수행하지 못했다.
- PM 또는 Claude 실행 환경에서 서버를 띄운 뒤 8000 포트 curl 검증을 한 번 더 수행해야 한다.
