# INBOX_EXECUTOR_bugfix_p1_confidence

## 역할
너는 Executor다. 아래 P1 버그를 수정하라.
완료 후 `docs/agent-comm/OUTBOX_EXECUTOR_bugfix_p1_confidence.md`에 결과를 작성하라.

---

## 버그 — Decision Engine confidence 필터 미동작

### 증상
S4 스크리닝에서 confidence 0.28~0.45인 종목에 BUY 신호가 발생.
본래 confidence 0.60 이상만 통과해야 함.

### 근본 원인 (조사 완료)

1. `decision_engine.py _evaluate_rules()` (line 204):
   ```python
   ai_conf_min = float(final_rule.get("ai_confidence_min", 0.0) or 0.0)
   ```
   `final_rule`에 `ai_confidence_min` 키가 없으므로 기본값 0.0 사용 → 모든 신호 통과.

2. `final_rule`은 `rule_resolver.resolve_symbol_rule()`이 빌드:
   - `base_rulepacks` 테이블 (machine_rules 컬럼 없음)
   - `risk_profile_packs` 테이블 (stop_loss, trailing 파라미터만 있음)
   
   두 테이블 모두 `ai_confidence_min` / `min_ai_confidence` 키 없음.

3. `rulepacks` 테이블 (`machine_rules` JSON 있음)은 rule_resolver가 전혀 읽지 않음.
   활성 rulepack의 `entry_rules` 내용:
   ```json
   {
     "min_volume_multiple_5d": 1.5,
     "min_price_change_pct": 1.0,
     "max_price_change_pct": 5.0,
     "exclude_market_open_minutes": 5,
     "exclude_market_close_minutes": 30
   }
   ```
   `min_ai_confidence`도 없음.

4. `system_settings` 테이블에도 confidence 관련 키 없음.

### 수정 방법

아래 3단계를 모두 구현하라.

---

#### 수정 1 — system_settings에 `engine.min_ai_confidence` 추가

`backend/services/db.py`의 `_seed_system_settings()` 함수 내에
아래 항목을 추가한다 (기존 항목이 없을 때만 INSERT하는 패턴 준수):

```python
(
    "engine.min_ai_confidence",
    "0.60",
    "number",
    "S6 매수 신호 최소 AI confidence 임계값 (0.0~1.0)"
),
```

기존 `_seed_system_settings()`의 패턴:
```python
conn.execute(
    "INSERT OR IGNORE INTO system_settings (key, value_json, value_type, description, updated_at, updated_by)"
    " VALUES (?, ?, ?, ?, ?, ?)",
    (key, value_json, value_type, description, now, "system"),
)
```

단, 기존 DB에 이미 이 키가 없으므로 서버 시작 시 자동 삽입되려면
`initialize_database()` 호출 시 `_seed_system_settings(conn)` 호출 경로를 확인하라.
이미 경로가 있으면 seed 추가만으로 충분하다.

---

#### 수정 2 — rule_resolver에 활성 rulepack entry_rules 병합 추가

`backend/services/engine/rule_resolver.py`의 `resolve_symbol_rule()` 함수에서
**레이어 병합** 직전, Base RulePack 바로 뒤에 아래 로직을 추가한다:

```python
# 2a. 활성 rulepacks의 entry_rules 읽기 (레이어 5.5 — base보다 높음, profile보다 낮음)
rulepack_entry = _get_active_rulepack_entry_rules(trade_date)
```

그리고 아래 새 함수를 추가한다:

```python
def _get_active_rulepack_entry_rules(trade_date: str) -> dict[str, Any]:
    """활성 RulePack의 machine_rules.entry_rules 반환. 없으면 빈 dict."""
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT machine_rules FROM rulepacks"
                " WHERE trade_date = ? AND status = 'active'"
                " ORDER BY created_at DESC LIMIT 1",
                (trade_date,),
            ).fetchone()
        if not row or not row["machine_rules"]:
            return {}
        mr = json.loads(row["machine_rules"])
        return mr.get("entry_rules", {}) or {}
    except Exception as e:
        logger.warning("WARN: [RuleResolver] rulepack entry_rules 조회 실패 — %s", e)
        return {}
```

`resolve_symbol_rule` 시그니처에 `trade_date: str` 파라미터를 추가한다:

```python
def resolve_symbol_rule(
    symbol_code: str,
    base_rulepack: dict[str, Any],
    profile_pack: dict[str, Any],
    daily_plan: dict[str, Any] | None,
    symbol_overrides: dict[str, dict[str, Any]],
    global_risk: dict[str, Any],
    trade_date: str = "",          # ← 추가
) -> dict[str, Any]:
```

레이어 병합 순서 (높을수록 우선):
```
base_rulepack (base_rulepacks 테이블)
→ rulepack_entry (rulepacks.machine_rules.entry_rules)   ← 새로 추가
→ profile_rule (risk_profile_packs 테이블)
→ symbol_override
→ Global Risk Guard
```

즉 기존 코드:
```python
final.update({k: v for k, v in base_rulepack.items() ...})
final.update(profile_rule)
final.update(symbol_overrides.get(symbol_code, {}))
```

를 아래로 변경:
```python
final.update({k: v for k, v in base_rulepack.items() ...})
final.update(rulepack_entry)          # ← 추가
final.update(profile_rule)
final.update(symbol_overrides.get(symbol_code, {}))
```

`rulepack_entry`에는 `min_volume_multiple_5d`, `min_price_change_pct`, `max_price_change_pct` 등의 키가 들어있다. 이 키들은 profile_rule이 덮을 수 있다.

**호출부 `rule_cache.py` 수정:**
`load_daily_rules()`에서 `resolve_symbol_rule()` 호출 시 `trade_date=trade_date`를 추가로 전달한다.

---

#### 수정 3 — decision_engine `_evaluate_rules` 수정

`backend/services/engine/decision_engine.py`의 `_evaluate_rules()` 함수를 아래와 같이 수정한다.

현재:
```python
ai_conf_min = float(final_rule.get("ai_confidence_min", 0.0) or 0.0)
ai_conf = _candidate_confidence(candidate)

volume_value = tick.get("volume")
volume_seen = volume_value not in (None, "")
return {
    "volume_ratio": bool(volume_seen or final_rule.get("volume_ratio_min", 1.0) <= 1.0),
    "ai_confidence": ai_conf >= ai_conf_min,
}
```

수정 후:
```python
# confidence 임계값: final_rule → system_settings 순으로 조회
ai_conf_min = float(
    final_rule.get("min_ai_confidence")
    or final_rule.get("ai_confidence_min")
    or _get_setting_float("engine.min_ai_confidence", 0.60)
)
ai_conf = _candidate_confidence(candidate)

# 가격 등락률 조건 (rulepack entry_rules 기준)
price_min_pct = float(final_rule.get("min_price_change_pct", 0.0) or 0.0)
price_max_pct = float(final_rule.get("max_price_change_pct", 999.0) or 999.0)
try:
    change_rate = float(tick.get("change_rate") or tick.get("prdy_ctrt") or 0.0)
except (TypeError, ValueError):
    change_rate = 0.0
price_ok = price_min_pct <= change_rate <= price_max_pct if price_min_pct > 0 else True

volume_value = tick.get("volume")
volume_seen = volume_value not in (None, "")
return {
    "volume_ratio": bool(volume_seen or final_rule.get("volume_ratio_min", 1.0) <= 1.0),
    "ai_confidence": ai_conf >= ai_conf_min,
    "price_change": price_ok,
}
```

그리고 `_get_setting_float()` 헬퍼를 `decision_engine.py` 모듈 레벨에 추가:

```python
def _get_setting_float(key: str, default: float) -> float:
    """system_settings에서 숫자 값을 읽는다. 실패 시 default 반환."""
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT value_json FROM system_settings WHERE key = ?", (key,)
            ).fetchone()
        if row:
            return float(json.loads(row["value_json"]))
    except Exception:
        pass
    return default
```

`decision_engine.py` 상단에 `import json`이 없으면 추가한다.

---

### 검증

```bash
python3 -m py_compile \
  backend/services/db.py \
  backend/services/engine/rule_resolver.py \
  backend/services/engine/rule_cache.py \
  backend/services/engine/decision_engine.py
echo "py_compile OK"
```

그리고 아래 로직 검증 스크립트를 실행해 결과를 OUTBOX에 포함하라:

```bash
python3 - <<'EOF'
import sys, os
sys.path.insert(0, '.')
os.environ.setdefault("APP_ENV", "development")

from backend.services.engine.decision_engine import _get_setting_float
v = _get_setting_float("engine.min_ai_confidence", 0.60)
print(f"min_ai_confidence from DB: {v}")
assert v > 0, "FAIL: confidence threshold is 0"

from backend.services.engine.rule_resolver import _get_active_rulepack_entry_rules
today = "2026-05-04"
entry = _get_active_rulepack_entry_rules(today)
print(f"entry_rules: {entry}")

print("PASS")
EOF
```

---

## 완료 체크리스트

- [ ] db.py `_seed_system_settings`에 `engine.min_ai_confidence` = "0.60" 추가
- [ ] rule_resolver.py `_get_active_rulepack_entry_rules()` 추가
- [ ] rule_resolver.py `resolve_symbol_rule()` `trade_date` 파라미터 추가 + rulepack_entry 레이어 병합
- [ ] rule_cache.py `load_daily_rules()`에서 `trade_date` 전달
- [ ] decision_engine.py `_get_setting_float()` 추가
- [ ] decision_engine.py `_evaluate_rules()` confidence 조회 방식 수정 + price_change 조건 추가
- [ ] py_compile 전체 통과
- [ ] 검증 스크립트 통과

결과는 `docs/agent-comm/OUTBOX_EXECUTOR_bugfix_p1_confidence.md`에 작성하라.
