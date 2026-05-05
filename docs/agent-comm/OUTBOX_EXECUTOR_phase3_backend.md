# OUTBOX_EXECUTOR_phase3_backend

## 작업 결과

Phase 3 백엔드 S10 Review & Audit + S11 Learning Memory Builder 구현을 완료했다.

## 변경 파일

- `backend/services/db.py`
  - S10/S11 신규 테이블 7개 추가
  - `daily_review_reports`
  - `learning_memories`
  - `profile_performance_daily`
  - `exit_reason_performance_daily`
  - `trailing_quality_daily`
  - `no_trade_daily_reasons`
  - `candidate_no_entry_reasons`
- `backend/services/engine/review_audit.py`
  - `run_review_audit(trade_date)`
  - `get_review_report(trade_date)`
- `backend/services/engine/learning_memory.py`
  - `run_learning_memory_builder(trade_date)`
  - `get_today_memories(trade_date)`
  - `get_active_memories(scope)`
- `backend/api/routes/review_audit.py`
  - `POST /api/v1/review-audit/run`
  - `GET /api/v1/review-audit/today`
  - `GET /api/v1/review-audit/{date}`
- `backend/api/routes/learning_memory.py`
  - `POST /api/v1/learning-memory/build`
  - `GET /api/v1/learning-memory/today`
  - `GET /api/v1/learning-memory/active`
- `backend/services/scheduler.py`
  - 16:00 KST `job_review_audit` 등록
  - 16:30 KST `job_learning_memory` 등록
- `backend/main.py`
  - S10/S11 라우터 등록

## 구현 메모

- 현재 `trading_signals` 활성 스키마에는 `risk_profile`, `realized_pnl`, `exit_reason`, `entry_price` 컬럼이 없다.
- S10은 실제 스키마를 `PRAGMA table_info(trading_signals)`로 확인한 뒤 컬럼이 있으면 사용하고, 없으면 다음 fallback을 적용한다.
  - `realized_pnl` 없음: `0.0`
  - `risk_profile` 없음: `profile_assigned`
  - `exit_reason` 없음: `unknown`
  - `entry_price` 없음: `trigger_price`
- S11은 S10 집계 테이블을 기준으로 메모리를 생성하며, 재실행 시 해당 날짜의 기존 `learning_memories`를 교체한다.

## 검증 결과

### 1. py_compile

통과.

```bash
python3 -m py_compile backend/services/db.py backend/services/engine/review_audit.py backend/services/engine/learning_memory.py backend/api/routes/review_audit.py backend/api/routes/learning_memory.py backend/services/scheduler.py backend/main.py
```

### 2. 임시 SQLite DB 테이블 생성

통과. 신규 7개 테이블 생성 확인.

확인된 신규 테이블:

- `daily_review_reports`
- `learning_memories`
- `profile_performance_daily`
- `exit_reason_performance_daily`
- `trailing_quality_daily`
- `no_trade_daily_reasons`
- `candidate_no_entry_reasons`

### 3. 서비스 흐름 테스트

통과.

- `run_review_audit("2026-05-03")` → `ok=True`, `total_trades=0`, `no_trade_count=1`
- `get_review_report("2026-05-03")` → report 존재
- `run_learning_memory_builder("2026-05-03")` → `ok=True`, `memory_count=0`
- `get_today_memories("2026-05-03")` → 0건
- `get_active_memories()` → 0건

### 4. 라우트 핸들러 테스트

통과.

- `review_audit.run()` → `ok=True`
- `review_audit.get_today()` → `ok=True`
- `learning_memory.build()` → `ok=True`
- `learning_memory.get_today()` → `ok=True`
- `learning_memory.get_active()` → `ok=True`

### 5. 스케줄러 등록 확인

통과.

- `job_review_audit` 등록 확인
- `job_learning_memory` 등록 확인
- 전체 job 수: 11

## 확인 필요 / 제한 사항

- `fastapi.testclient.TestClient` 기반 HTTP 레벨 테스트는 이 실행 환경에서 응답 출력 없이 멈춰서 완료하지 못했다.
- 대신 서비스 함수와 FastAPI 라우트 핸들러를 직접 호출해 빈 데이터 기준 정상 흐름을 검증했다.
- 현재 `trading_signals`에 손익/청산 컬럼이 없으므로 실제 손익 기반 메모리 생성은 해당 컬럼 또는 별도 체결 결과 저장 로직이 붙은 뒤 의미 있는 값을 만든다.

## 완료 체크

- [x] 작업 1 — DB 7개 테이블
- [x] 작업 2 — review_audit.py
- [x] 작업 3 — learning_memory.py
- [x] 작업 4 — REST API 2개
- [x] 작업 5 — scheduler.py S10/S11 등록
- [x] 작업 6 — main.py 라우터 등록
- [x] py_compile 전부 통과
- [x] DB 테이블 생성 확인
