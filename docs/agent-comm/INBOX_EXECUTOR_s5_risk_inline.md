# INBOX_EXECUTOR_s5_risk_inline — risk_constants 인라인 통합

## 배경
`backend/config/risk_constants.py`는 외부 에이전트가 만든 파일로,
현재 `backend/services/engine/rulepack_generation.py`에서만 참조한다.

`backend/config.py`(파일)와 `backend/config/`(디렉토리)가 동시 존재해
Python이 `backend.config`를 패키지로 인식하지 못하고 직접 import가 불가능하다.
현재 `rulepack_generation.py`는 `importlib` 우회 코드를 사용 중이다.

## 작업 목표

1. `backend/config/risk_constants.py` 파일 삭제
2. `backend/config/` 디렉토리 삭제 (비어 있으면)
3. `backend/services/engine/rulepack_generation.py` 수정:
   - `importlib` import 및 `_risk_constants_module()` 함수 제거
   - L1 상수 + 캡 로직을 파일 상단에 인라인으로 추가
   - `_load_pm_settings()`, `_apply_caps_and_build_validation()` 에서 인라인 상수/함수 사용

---

## 인라인할 내용 (rulepack_generation.py 상단에 추가)

`from __future__ import annotations` 바로 아래, 다른 import 전에 추가:

```python
# ---------------------------------------------------------------------------
# L1 절대 한도 (코드 변경 + 재배포 없이는 변경 불가)
# ---------------------------------------------------------------------------
_DAILY_LOSS_LIMIT_L1 = -0.10   # -10%
_MAX_POSITIONS_L1    = 30
_STOP_LOSS_L1        = -0.05   # -5%
_MAX_POS_SIZE_L1     = 0.30    # 30%
_TAKE_PROFIT_L1      = 0.30    # 30%
_MAX_HOLDING_MIN_L1  = 390     # 390분
```

그리고 내부 캡 함수 추가:

```python
def _cap(value, limit, direction: str):
    """단일 값에 L1 한도를 적용한다.
    direction='neg': value < limit 이면 limit으로 올림 (음수 한도)
    direction='pos': value > limit 이면 limit으로 내림 (양수 한도)
    """
    if direction == "neg":
        return limit if value < limit else value
    else:
        return limit if value > limit else value


def _apply_l1_caps(rulepack: dict, pm: dict) -> tuple[dict, list[dict]]:
    """rulepack의 risk_limits에 PM설정 → L1 순서로 캐스케이딩 캡을 적용한다.

    Returns:
        (capped_rulepack, cap_log)  -- cap_log: [{field, original, capped, capped_by}]
    """
    import copy
    result = copy.deepcopy(rulepack)
    rl = result["risk_limits"]
    cap_log = []

    def _apply_one(field, ai_val, pm_val, l1_val, direction):
        # PM 값 자체가 L1 위반이면 먼저 L1로 보정
        eff_pm = _cap(pm_val, l1_val, direction)
        # AI 값을 유효 PM으로 캡
        final = _cap(ai_val, eff_pm, direction)
        capped_by = "none"
        if final != ai_val:
            capped_by = "l1_absolute" if eff_pm != pm_val else "pm_settings"
        cap_log.append({"field": field, "original": ai_val, "capped": final, "capped_by": capped_by})
        return final

    rl["daily_loss_limit_rate"] = _apply_one(
        "daily_loss_limit_rate",
        rl.get("daily_loss_limit_rate", _DAILY_LOSS_LIMIT_L1),
        pm.get("daily_loss_limit_rate", _DAILY_LOSS_LIMIT_L1),
        _DAILY_LOSS_LIMIT_L1, "neg",
    )
    rl["max_positions"] = int(_apply_one(
        "max_positions",
        rl.get("max_positions", _MAX_POSITIONS_L1),
        pm.get("max_positions", _MAX_POSITIONS_L1),
        _MAX_POSITIONS_L1, "pos",
    ))
    rl["stop_loss_rate"] = _apply_one(
        "stop_loss_rate",
        rl.get("stop_loss_rate", _STOP_LOSS_L1),
        pm.get("stop_loss_rate", _STOP_LOSS_L1),
        _STOP_LOSS_L1, "neg",
    )
    rl["max_position_size_rate"] = _apply_one(
        "max_position_size_rate",
        rl.get("max_position_size_rate", _MAX_POS_SIZE_L1),
        pm.get("max_position_size_rate", _MAX_POS_SIZE_L1),
        _MAX_POS_SIZE_L1, "pos",
    )
    rl["take_profit_rate"] = _apply_one(
        "take_profit_rate",
        rl.get("take_profit_rate", _TAKE_PROFIT_L1),
        pm.get("take_profit_rate", _TAKE_PROFIT_L1),
        _TAKE_PROFIT_L1, "pos",
    )
    rl["max_holding_minutes"] = int(_apply_one(
        "max_holding_minutes",
        rl.get("max_holding_minutes", _MAX_HOLDING_MIN_L1),
        pm.get("max_holding_minutes", _MAX_HOLDING_MIN_L1),
        _MAX_HOLDING_MIN_L1, "pos",
    ))

    return result, cap_log
```

---

## `_load_pm_settings()` 수정

기존 코드에서 `risk_constants` 모듈 참조를 인라인 상수로 교체:

```python
def _load_pm_settings() -> dict:
    defaults = {
        "daily_loss_limit_rate": _DAILY_LOSS_LIMIT_L1,
        "max_positions": _MAX_POSITIONS_L1,
        "stop_loss_rate": _STOP_LOSS_L1,
        "max_position_size_rate": _MAX_POS_SIZE_L1,
        "take_profit_rate": _TAKE_PROFIT_L1,
        "max_holding_minutes": _MAX_HOLDING_MIN_L1,
    }
    try:
        settings = list_settings()
        loaded = {s["key"]: s["value"] for s in settings}
        for k in defaults:
            if k in loaded:
                defaults[k] = loaded[k]
    except Exception as exc:
        logger.warning("WARN: RulePackGen PM settings 로드 실패 — L1 기본값 사용 %s", exc)
    return defaults
```

---

## `_apply_caps_and_build_validation()` 수정

`_risk_constants_module().apply_all_caps()` 호출을 `_apply_l1_caps()` 로 교체:

```python
def _apply_caps_and_build_validation(rulepack_data: dict, pm_settings: dict) -> tuple[dict, dict]:
    capped, cap_log = _apply_l1_caps(rulepack_data, pm_settings)
    capped_fields = [r for r in cap_log if r["capped_by"] != "none"]
    validation = {
        "schema": "pass",
        "risk_policy": "pass",
        "runtime": "pending",
        "cap_applied": capped_fields,
    }
    return capped, validation
```

---

## 제거 대상

`rulepack_generation.py` 에서 아래를 완전히 제거:
- `from importlib import util as importlib_util` import
- `from pathlib import Path` import (다른 곳에서 안 쓰면)
- `_risk_constants_module()` 함수 전체
- `from ...config.risk_constants import apply_all_caps` import (있다면)

---

## 완료 기준

```bash
rm -f backend/config/risk_constants.py
rmdir backend/config/ 2>/dev/null || true  # 비어있으면 삭제, 아니면 무시
python -m py_compile backend/services/engine/rulepack_generation.py && echo "OK"
python -c "from backend.services.engine.rulepack_generation import run_rulepack_generation; print('import OK')"
```

OUTBOX(`docs/agent-comm/OUTBOX_EXECUTOR_s5_risk_inline.md`)에 결과 작성.
