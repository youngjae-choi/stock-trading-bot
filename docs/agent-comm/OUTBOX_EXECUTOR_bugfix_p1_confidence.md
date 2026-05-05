# OUTBOX_EXECUTOR_bugfix_p1_confidence

## 처리 결과

P1 버그 `Decision Engine confidence 필터 미동작` 수정 완료.

## 변경 파일

- `backend/services/db.py`
- `backend/services/engine/rule_resolver.py`
- `backend/services/engine/rule_cache.py`
- `backend/services/engine/decision_engine.py`
- `backend/api/routes/rule.py`

## 구현 내용

### 1. system_settings 기본값 추가

- `_seed_system_settings()`에 `engine.min_ai_confidence` 기본값 `"0.60"` 추가.
- `initialize_database()`에서 `_seed_system_settings(conn)` 호출 경로가 이미 존재함을 확인.
- 로컬 DB 초기화 후 실제 row 확인:
  - `key`: `engine.min_ai_confidence`
  - `value_json`: `"0.60"`
  - `value_type`: `number`

### 2. RulePack entry_rules 병합 추가

- `rule_resolver.py`에 `_get_active_rulepack_entry_rules(trade_date)` 추가.
- `resolve_symbol_rule()`에 `trade_date: str = ""` 파라미터 추가.
- 병합 순서 변경:
  - `base_rulepack`
  - `rulepacks.machine_rules.entry_rules`
  - `profile_rule`
  - `symbol_override`
  - `Global Risk Guard`
- `rule_cache.py`의 `load_daily_rules()`에서 `trade_date=trade_date` 전달.
- `/api/v1/rule/composition/{symbol_code}` 미리보기 경로도 같은 날짜의 entry_rules를 반영하도록 `trade_date=today` 전달.

### 3. Decision Engine 평가 로직 수정

- `_get_setting_float(key, default)` 추가.
- `_evaluate_rules()` confidence 임계값 조회 순서 변경:
  - `final_rule["min_ai_confidence"]`
  - `final_rule["ai_confidence_min"]`
  - `system_settings["engine.min_ai_confidence"]`
  - fallback `0.60`
- 가격 등락률 조건 추가:
  - `min_price_change_pct`
  - `max_price_change_pct`
  - tick의 `change_rate` 또는 `prdy_ctrt`
- 반환 결과에 `price_change` 추가.

## 검증 결과

### py_compile

```bash
python3 -m py_compile \
  backend/services/db.py \
  backend/services/engine/rule_resolver.py \
  backend/services/engine/rule_cache.py \
  backend/services/engine/decision_engine.py \
  backend/api/routes/rule.py
```

결과: `py_compile OK`

### 인박스 지정 검증 스크립트

출력:

```text
min_ai_confidence from DB: 0.6
entry_rules: {}
PASS
```

주의: 현재 로컬 DB에는 `2026-05-04` 기준 `status='active'` rulepack이 없어 `entry_rules`는 `{}`로 조회됨. 조회 실패가 아니라 활성 데이터 부재 상태임.

### 추가 로직 검증

`DecisionEngine._evaluate_rules()` 직접 검증:

```text
low_confidence: {'volume_ratio': True, 'ai_confidence': False, 'price_change': True}
high_confidence_price_ok: {'volume_ratio': True, 'ai_confidence': True, 'price_change': True}
price_out_of_range: {'volume_ratio': True, 'ai_confidence': True, 'price_change': False}
PASS
```

확인 내용:

- confidence `0.45`는 기본 임계값 `0.60`에서 차단됨.
- confidence `0.61`은 통과됨.
- 가격 등락률 범위 밖 tick은 `price_change=False`로 차단됨.

## 완료 체크리스트

- [x] db.py `_seed_system_settings`에 `engine.min_ai_confidence` = `"0.60"` 추가
- [x] rule_resolver.py `_get_active_rulepack_entry_rules()` 추가
- [x] rule_resolver.py `resolve_symbol_rule()` `trade_date` 파라미터 추가 + rulepack_entry 레이어 병합
- [x] rule_cache.py `load_daily_rules()`에서 `trade_date` 전달
- [x] decision_engine.py `_get_setting_float()` 추가
- [x] decision_engine.py `_evaluate_rules()` confidence 조회 방식 수정 + price_change 조건 추가
- [x] py_compile 전체 통과
- [x] 검증 스크립트 통과

## 남은 확인 필요 사항

- 실제 운영 날짜의 active rulepack에 `machine_rules.entry_rules`가 포함되어 있는지 데이터 생성 경로에서 확인 필요.
- 현재 검증 DB 기준 `2026-05-04` active rulepack은 없음.
