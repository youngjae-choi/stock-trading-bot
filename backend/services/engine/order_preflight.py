"""S6-P Order Pre-Flight Check — KIS 주문 직전 안전 검증."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection

logger = logging.getLogger("OrderPreflight")

PREFLIGHT_OK = "ok"
PREFLIGHT_BLOCK = "block"


def _now_kst() -> datetime:
    """Return the current Asia/Seoul datetime for market-hour checks."""
    return datetime.now(ZoneInfo("Asia/Seoul"))


def _now_utc_iso() -> str:
    """Return a UTC ISO timestamp for persisted preflight records."""
    return datetime.now(timezone.utc).isoformat()


def _to_float(value: Any, default: float = 0.0) -> float:
    """Convert rule and signal numeric values to float with a safe fallback."""
    try:
        return float(str(value).replace(",", "").strip() or default)
    except (TypeError, ValueError):
        return default


def _position_size_pct(final_rule: dict[str, Any]) -> float:
    """Return position size percent from flat final_rule keys."""
    if "position_size_pct" in final_rule:
        return _to_float(final_rule.get("position_size_pct"), 100.0)
    max_position_rate = _to_float(final_rule.get("max_position_rate"), 0.0)
    if 0 < max_position_rate <= 1:
        return max_position_rate * 100
    if max_position_rate > 1:
        return max_position_rate
    return 100.0


def _time_from_rule(value: Any, fallback: tuple[int, int]) -> tuple[int, int]:
    """Return hour and minute parsed from an HH:MM or HH:MM:SS rule value."""
    text = str(value or "").strip()
    parts = text.split(":")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return int(parts[0]), int(parts[1])
    return fallback


def run_preflight(
    signal: dict[str, Any],
    final_rule: dict[str, Any],
    current_positions_count: int = 0,
) -> dict[str, Any]:
    """주문 직전 안전 검증. 반환값: {ok, preflight_id, checks, block_reason}."""
    logger.info("START: [S6-P] preflight signal_id=%s symbol=%s", signal.get("id"), signal.get("symbol"))
    checks: dict[str, str] = {}
    block_reasons: list[str] = []

    now = _now_kst()

    # 1. 장 운영 시간 및 설정된 신규매수 금지 시간 확인
    market_open = now.replace(hour=9, minute=0, second=0, microsecond=0)
    cutoff_hour, cutoff_minute = _time_from_rule(final_rule.get("new_entry_cutoff_time"), (15, 20))
    entry_cutoff = now.replace(hour=cutoff_hour, minute=cutoff_minute, second=0, microsecond=0)
    if not (market_open <= now < entry_cutoff):
        checks["market_hours"] = PREFLIGHT_BLOCK
        block_reasons.append(f"신규매수 시간 외 (09:00~{cutoff_hour:02d}:{cutoff_minute:02d})")
    else:
        checks["market_hours"] = PREFLIGHT_OK

    # 2. 종목당 최대 비중 (final_rule에서 position_size_pct 한도 확인)
    position_size_pct = _position_size_pct(final_rule)
    if position_size_pct > 30.0:
        checks["position_size"] = PREFLIGHT_BLOCK
        block_reasons.append(f"position_size_pct={position_size_pct} 초과 (최대 30%)")
    else:
        checks["position_size"] = PREFLIGHT_OK

    # 3. 최대 보유 종목 수 초과
    max_positions = int(_to_float(final_rule.get("max_positions"), 10.0) or 10)
    if current_positions_count >= max_positions:
        checks["max_positions"] = PREFLIGHT_BLOCK
        block_reasons.append(f"최대 보유 종목 도달 ({current_positions_count}/{max_positions})")
    else:
        checks["max_positions"] = PREFLIGHT_OK

    # 4. 트리거 가격 유효성
    trigger_price = _to_float(signal.get("trigger_price"))
    if trigger_price <= 0:
        checks["price_valid"] = PREFLIGHT_BLOCK
        block_reasons.append("trigger_price 유효하지 않음")
    else:
        checks["price_valid"] = PREFLIGHT_OK

    # 5. 신뢰도 최소값 (final_rule)
    ai_conf_min = _to_float(final_rule.get("ai_confidence_min"), 0.0)
    confidence = _to_float(signal.get("confidence"), 0.0)
    if confidence < ai_conf_min:
        checks["ai_confidence"] = PREFLIGHT_BLOCK
        block_reasons.append(f"confidence={confidence:.2f} < 최소 {ai_conf_min:.2f}")
    else:
        checks["ai_confidence"] = PREFLIGHT_OK

    passed = len(block_reasons) == 0
    preflight_id = str(uuid.uuid4())
    created_at = _now_utc_iso()

    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO order_preflight_checks
                    (id, signal_id, symbol, checks, block_reasons, result, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    preflight_id,
                    str(signal.get("id") or ""),
                    str(signal.get("symbol") or ""),
                    json.dumps(checks, ensure_ascii=False),
                    "|".join(block_reasons),
                    PREFLIGHT_OK if passed else PREFLIGHT_BLOCK,
                    created_at,
                ),
            )
    except Exception as exc:
        logger.warning("WARN: [S6-P] preflight DB save failed reason=%s", exc)

    if passed:
        logger.info("SUCCESS: [S6-P] preflight ok signal_id=%s symbol=%s", signal.get("id"), signal.get("symbol"))
    else:
        logger.warning(
            "BLOCK: [S6-P] preflight signal_id=%s symbol=%s reasons=%s",
            signal.get("id"),
            signal.get("symbol"),
            block_reasons,
        )

    return {
        "ok": passed,
        "preflight_id": preflight_id,
        "checks": checks,
        "block_reason": block_reasons[0] if block_reasons else None,
        "block_reasons": block_reasons,
    }
