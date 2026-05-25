# OUTBOX: Codex — S10 복기 LLM화 + 레짐 피드백 학습 + S11 us_market_watch 제거

**작성:** Codex 2026-05-23  
**상태:** 구현 및 로컬 검증 완료

## 작업 결과

1. `backend/prompts/1600_opus_review.md`
   - S10 복기 프롬프트를 레짐 평가, 설정 변경 제안, 패턴 분석을 포함한 JSON 전용 포맷으로 완전 교체했다.

2. `backend/services/engine/review_audit.py`
   - S10 deterministic 집계 결과를 LLM 입력용 Markdown 컨텍스트로 조립하는 `_build_review_context_md()`를 추가했다.
   - 기존 하드코딩 추천 기반 `_send_action_plan_for_approval()` 흐름을 LLM 호출 기반으로 교체했다.
   - `llm_router.call_llm()` 실제 반환 키가 `raw`인 점에 맞춰 JSON 파싱을 구현했다.
   - LLM 결과 기반으로 `regime_set_feedback` 저장, `system_settings` 자동 반영, `human_approval_queue` 감사 로그 저장, 텔레그램 통보를 수행한다.
   - `run_review_audit()` 반환값과 `get_review_report()` 응답에 `llm_review`를 포함했다.

3. `backend/services/db.py`
   - `regime_set_feedback` 테이블과 `set_id`, `trade_date` 인덱스를 `CREATE TABLE IF NOT EXISTS` 방식으로 추가했다.

4. `backend/services/regime_set_service.py`
   - `_apply_feedback_scores()`를 추가해 과거 `bad` 평가 누적 시 감점, `good` 평가 누적 시 가점이 후보 SET 점수에 반영되도록 했다.
   - 피드백 테이블이 없거나 조회 실패 시 기존 매칭 흐름을 유지하도록 방어 처리했다.

5. `backend/services/scheduler.py`
   - `job_us_market_watch()` 함수 정의를 제거했다.
   - `us_watch` 스케줄 키와 `job_us_market_watch` 등록을 제거했다.
   - `S11 Learning Memory` job은 별도 기능이므로 유지했다.

6. 추가 정리
   - `backend/services/console_state.py`에서 더 이상 실행되지 않는 “미국장 야간 관찰” 타임라인 표시를 제거했다.
   - `tests/unit/test_universe_filter_diagnostics.py`의 스케줄 가드 테스트 입력에서 `us_watch` 키를 제거했다.

## 검증 결과

```bash
python -m py_compile backend/services/db.py backend/services/engine/review_audit.py backend/services/regime_set_service.py backend/services/scheduler.py backend/services/console_state.py tests/unit/test_universe_filter_diagnostics.py
```

결과: 통과

```bash
python3 -c "import sys; sys.path.insert(0,'.'); from backend.services.db import initialize_database, get_connection; initialize_database(); ..."
```

결과: `regime_set_feedback` 컬럼과 인덱스 생성 확인, `OK`

```bash
python -m unittest tests.unit.test_universe_filter_diagnostics
```

결과: 5개 테스트 통과

## 확인 필요

- 실제 LLM 호출은 `.env`의 provider API 키가 있어야 동작한다. provider가 없으면 `llm_review`는 빈 분석에 가까운 fallback 결과가 저장될 수 있다.
- LLM이 제안한 `settings_overrides`는 즉시 `system_settings`에 반영된다. 운영 전 허용 가능한 setting key 범위를 제한할지 PM 결정이 필요하다.
