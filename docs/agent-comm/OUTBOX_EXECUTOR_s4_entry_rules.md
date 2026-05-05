# OUTBOX_EXECUTOR_s4_entry_rules

## 상태
완료

## 작업 요약
- `backend/services/engine/hybrid_screening.py`
  - S4 Hybrid Screening 프롬프트 출력 JSON에 `entry_rules` 블록을 추가했다.
  - 시장 톤별 `entry_rules` 설정 기준을 프롬프트에 추가했다.
  - LLM 응답 파서가 `entry_rules`를 보존하도록 확장했다.
  - `_save_daily_rulepack_from_screening()` 헬퍼를 추가해 S4가 생성한 `entry_rules`를 오늘 날짜 active RulePack에 저장하도록 했다.
  - 기존 active RulePack이 있으면 `machine_rules.entry_rules`만 갱신하고, 없으면 `RP-S4-YYYYMMDD-XXXXXX` 형식의 active RulePack을 신규 생성한다.
  - `run_hybrid_screening()` 결과 payload에 `entry_rules`를 포함했다.

- `backend/services/db.py`
  - `_seed_system_settings()`에 매수조건 가드레일 seed 3개를 추가했다.
  - 추가 key:
    - `engine.min_confidence_floor`
    - `engine.min_price_change_pct`
    - `engine.max_price_change_pct`

- `backend/services/engine/decision_engine.py`
  - `_evaluate_rules()`에서 RulePack `entry_rules` 적용 시 settings 가드레일을 반영하도록 했다.
  - `min_ai_confidence`는 `engine.min_confidence_floor` 아래로 내려가지 않게 했다.
  - `min_price_change_pct`는 `engine.min_price_change_pct` 아래로 내려가지 않게 했다.
  - `max_price_change_pct`는 `engine.max_price_change_pct` 위로 올라가지 않게 했다.

## 검증 결과
```bash
python3 -m py_compile \
  backend/services/engine/hybrid_screening.py \
  backend/services/db.py \
  backend/services/engine/decision_engine.py
```

결과:
```text
py_compile OK
```

```bash
python3 - <<'EOF'
import sys, os
sys.path.insert(0, '.')
os.environ.setdefault("APP_ENV", "development")

from backend.services.engine.hybrid_screening import _save_daily_rulepack_from_screening
print("_save_daily_rulepack_from_screening import OK")

from backend.services.engine.decision_engine import _get_setting_float
floor = _get_setting_float("engine.min_confidence_floor", 0.40)
print(f"min_confidence_floor: {floor}")

print("PASS")
EOF
```

결과:
```text
_save_daily_rulepack_from_screening import OK
min_confidence_floor: 0.4
PASS
```

## 참고 사항
- 작업 시작 시 대상 파일을 포함해 작업트리에 기존 변경이 다수 있었다. 기존 변경을 되돌리지 않고 요청 범위만 추가 패치했다.
- Codex 역할 제한에 따라 git commit은 수행하지 않았다.
