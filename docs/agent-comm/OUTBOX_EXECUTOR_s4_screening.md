# OUTBOX_EXECUTOR_s4_screening — S4 Hybrid Screening 구현 결과

## 실행 결과: ✅ 완료

---

## 생성/수정 파일 목록

| 파일 | 유형 | 상태 |
|------|------|------|
| `backend/services/engine/hybrid_screening.py` | 신규 | ✅ 생성 완료 |
| `backend/api/routes/screening.py` | 신규 | ✅ 생성 완료 |
| `backend/services/scheduler.py` | 수정 | ✅ 수정 완료 |
| `backend/main.py` | 수정 | ✅ 수정 완료 |

---

## py_compile 검증 결과

```
python -m py_compile backend/services/engine/hybrid_screening.py → OK
python -m py_compile backend/api/routes/screening.py             → OK
python -m py_compile backend/services/scheduler.py               → OK
python -m py_compile backend/main.py                             → OK
```

모두 오류 없이 통과.

---

## 변경 내용 요약

### 1. `backend/services/engine/hybrid_screening.py` (신규)
- `_ensure_table()`: `hybrid_screening_results` 테이블 및 인덱스 생성
- `_build_prompt()`: 30종목 후보 + 시장 톤 → 프롬프트 빌드. market_tone=None 시 기본값 적용. 뉴스는 고정 문자열로 대체.
- `_parse_screening_response()`: 마크다운 코드 블록 제거 → JSON 파싱 → 브레이스 추출 fallback. suitability_score 0.0~1.0 범위 강제.
- `run_hybrid_screening()`: S3 결과 없으면 빈 결과 저장 후 skipped_reason="no_universe" 반환. LLM 호출 → 파싱 → DB INSERT OR REPLACE.
- `get_today_screening()`: trade_date 기준 최신 1건 조회. candidates/skipped 필드 자동 역직렬화.

### 2. `backend/api/routes/screening.py` (신규)
- `GET /api/v1/screening/today`: 오늘 스크리닝 결과 조회
- `POST /api/v1/screening/run`: 즉시 실행 (validate_config 체크 포함)
- `require_console_user` 의존성 적용

### 3. `backend/services/scheduler.py` (수정)
- `job_hybrid_screening` 함수 추가 (Job 4, 08:30 KST)
- 기존 Job 번호 재정렬:
  - job_intraday_liquidation: Job 4 → **Job 5**
  - job_data_backup: Job 5 → **Job 6**
  - job_us_market_watch: Job 6 → **Job 7**
- `_build_scheduler()`에 `job_hybrid_screening` 등록 (universe_filter 바로 다음, 08:30 KST)

### 4. `backend/main.py` (수정)
- `from .api.routes.screening import router as screening_router` import 추가
- `app.include_router(screening_router)` 추가 (universe_filter_router 바로 다음)

---

## 특이사항

- 뉴스 데이터는 INBOX 명세대로 이번 버전에서 제외. 프롬프트에 고정 문자열 `"뉴스 데이터 미제공 — 이번 버전 제외"` 삽입.
- LLM 호출 실패 시 candidates=[], skipped=[], overall_confidence=0.0 으로 저장하고 서버는 계속 실행됨.
- S3 결과(universe_filter_results)가 없을 경우 provider="none"으로 빈 결과 저장 후 skipped_reason="no_universe" 반환.
