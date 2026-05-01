"""RulePack schema and risk-policy validator."""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Risk policy hard limits
# ---------------------------------------------------------------------------
_RISK_LIMITS = {
    "daily_loss_limit_pct_max": 5.0,
    "max_positions_max": 20,
    "position_size_pct_max": 30.0,
}

# Required keys inside machine_rules
_REQUIRED_TOP_KEYS = {"layer3_entry", "risk_limits"}
_REQUIRED_ENTRY_KEYS = {"vwap_position", "volume_ratio_min", "ma5_above_ma20", "rsi_range", "spread_max_pct"}
_REQUIRED_RISK_KEYS = {"daily_loss_limit_pct", "max_positions", "position_size_pct"}


def validate(machine_rules: dict[str, Any]) -> dict[str, Any]:
    """Validate machine_rules and return a validation result dict.

    Returns:
        {
            "schema": "pass" | "fail",
            "schema_errors": [...],
            "risk_policy": "pass" | "fail",
            "risk_errors": [...],
            "runtime": "pending",
        }
    """
    schema_errors: list[str] = []
    risk_errors: list[str] = []

    # --- Schema check ---
    missing_top = _REQUIRED_TOP_KEYS - set(machine_rules.keys())
    if missing_top:
        schema_errors.append(f"Missing top-level keys: {sorted(missing_top)}")

    entry = machine_rules.get("layer3_entry", {})
    if not isinstance(entry, dict):
        schema_errors.append("layer3_entry must be an object")
    else:
        missing_entry = _REQUIRED_ENTRY_KEYS - set(entry.keys())
        if missing_entry:
            schema_errors.append(f"layer3_entry missing keys: {sorted(missing_entry)}")

        rsi = entry.get("rsi_range")
        if rsi is not None:
            if not (isinstance(rsi, list) and len(rsi) == 2 and all(isinstance(v, (int, float)) for v in rsi)):
                schema_errors.append("layer3_entry.rsi_range must be [min, max] numbers")
            elif rsi[0] >= rsi[1]:
                schema_errors.append("layer3_entry.rsi_range[0] must be less than rsi_range[1]")

        vwap = entry.get("vwap_position")
        if vwap is not None and vwap not in ("above", "below", "any"):
            schema_errors.append("layer3_entry.vwap_position must be 'above', 'below', or 'any'")

    risk = machine_rules.get("risk_limits", {})
    if not isinstance(risk, dict):
        schema_errors.append("risk_limits must be an object")
    else:
        missing_risk = _REQUIRED_RISK_KEYS - set(risk.keys())
        if missing_risk:
            schema_errors.append(f"risk_limits missing keys: {sorted(missing_risk)}")

    # --- Risk policy check (only if schema passed) ---
    if not schema_errors and isinstance(risk, dict):
        daily_loss = risk.get("daily_loss_limit_pct", 0)
        max_pos = risk.get("max_positions", 0)
        pos_size = risk.get("position_size_pct", 0)

        if daily_loss > _RISK_LIMITS["daily_loss_limit_pct_max"]:
            risk_errors.append(
                f"daily_loss_limit_pct {daily_loss} exceeds max {_RISK_LIMITS['daily_loss_limit_pct_max']}"
            )
        if max_pos > _RISK_LIMITS["max_positions_max"]:
            risk_errors.append(
                f"max_positions {max_pos} exceeds max {_RISK_LIMITS['max_positions_max']}"
            )
        if pos_size > _RISK_LIMITS["position_size_pct_max"]:
            risk_errors.append(
                f"position_size_pct {pos_size} exceeds max {_RISK_LIMITS['position_size_pct_max']}"
            )

    return {
        "schema": "fail" if schema_errors else "pass",
        "schema_errors": schema_errors,
        "risk_policy": "fail" if risk_errors else "pass",
        "risk_errors": risk_errors,
        "runtime": "pending",
    }
