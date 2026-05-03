# OUTBOX_EXECUTOR_design_v2_backend_core

## 결과 요약

모든 작업 완료. `py_compile` 전부 통과.

---

## 완료 체크리스트

- [x] **db.py**: 6개 신규 테이블 + trading_signals 이관 + `_seed_rule_system()` 함수
  - `base_rulepacks`, `risk_profile_packs`, `daily_trading_plans`, `symbol_overrides`, `rule_compositions`, `position_stop_states`
  - `trading_signals` 테이블 및 인덱스 추가
  - `_seed_rule_system()` 함수 추가 및 `initialize_database()` 내 호출
  - base-v1.0, profile-v1.0 초기값 seeding (LOW_VOL/MID_VOL/HIGH_VOL/THEME_SPIKE)

- [x] **rule_resolver.py** (`backend/services/engine/rule_resolver.py`): 신규 생성
  - `get_active_base_rulepack()`, `get_active_profile_pack()`, `get_active_daily_plan()`, `get_symbol_overrides()` 구현
  - `resolve_symbol_rule()` 구현 — 레이어 병합 (base → profile → symbol_override) + Global Risk Guard 강제 적용

- [x] **rule_cache.py** (`backend/services/engine/rule_cache.py`): 신규 생성
  - `load_daily_rules(trade_date, symbol_codes)` — S6 시작 시 호출
  - `get_rule(symbol_code)` — O(1) 캐시 조회
  - `clear_cache()` — 장마감 후 초기화
  - `get_meta()`, `get_all_cached()` 보조 함수

- [x] **daily_plan.py** (`backend/services/engine/daily_plan.py`): 신규 생성
  - `run_daily_plan_generation()` async 함수 구현
  - `llm_router.call_llm(prompt, task_name)` 실제 시그니처에 맞게 어댑터 적용 (INBOX 원본은 `system`, `max_tokens` 파라미터 있었으나 실제 함수 시그니처와 상이하여 수정)
  - 8가지 `_validate_plan()` 검증 로직
  - LLM 실패 시 MID_VOL 기본 배정 fallback

- [x] **position_manager.py** (`backend/services/engine/position_manager.py`): 전면 교체
  - `take_profit` 로직 완전 제거
  - 트레일링 스탑 중심으로 재구현 (`_update_trailing()`)
  - `position_stop_states` DB sync (`_upsert_stop_state()`)
  - `add_position()` 시그니처 변경: `rulepack` → `final_rule` (rule_cache 결과 수신)
  - 청산 우선순위: DAILY_FORCE_EXIT → INITIAL_STOP_LOSS / TRAILING_STOP → TIME_EXIT
  - `stop_price_can_only_increase = True` 강제 (active_stop_price 절대 하향 불가)

- [x] **decision_engine.py** (`backend/services/engine/decision_engine.py`): 수정
  - `from .rulepack_store import get_active_rulepack_for_date` 제거
  - `from .rule_cache import load_daily_rules, get_rule, clear_cache, get_meta` 추가
  - `self._rulepack` 제거
  - `activate()`: rulepack early-return 블록 제거, candidates 로드 후 `load_daily_rules()` 호출, 반환값에 `cache_meta` 추가
  - `_on_tick()`: `get_rule(symbol)` 로 final_rule 조회
  - `_evaluate_rules()`: `rules` → `final_rule` 파라미터
  - `_emit_signal()`: `profile_assigned` 컬럼 추가 INSERT
  - `deactivate()`: `clear_cache()` 호출 추가

- [x] **py_compile 전부 통과**
  - `python3 -m py_compile backend/services/db.py` → OK
  - `python3 -m py_compile backend/services/engine/rule_resolver.py` → OK
  - `python3 -m py_compile backend/services/engine/rule_cache.py` → OK
  - `python3 -m py_compile backend/services/engine/daily_plan.py` → OK
  - `python3 -m py_compile backend/services/engine/position_manager.py` → OK
  - `python3 -m py_compile backend/services/engine/decision_engine.py` → OK

---

## 주요 변경 메모

### llm_router.call_llm 시그니처 불일치 처리
INBOX 원본의 daily_plan.py는 `call_llm(prompt, system, max_tokens)` 시그니처를 사용했으나, 실제 `llm_router.py`의 시그니처는 `call_llm(prompt, task_name="")` 이며 반환값이 `{ok, provider, raw, tried}`임. 이를 반영하여 daily_plan.py 어댑터 수정:
- `llm_router.call_llm(prompt=prompt, task_name="S5 Daily Trading Plan")` 호출
- 반환값의 `ok`, `raw`, `provider` 필드 활용

### db.py 사전 완료 상태
작업 시작 시 db.py는 이미 6개 테이블, trading_signals, `_seed_rule_system()` 함수가 모두 추가된 상태였음 (변경 불필요, 검증만 수행).

### rule_resolver.py, rule_cache.py 사전 완료 상태
두 파일 모두 이미 생성된 상태였음 (변경 불필요, 검증만 수행).
