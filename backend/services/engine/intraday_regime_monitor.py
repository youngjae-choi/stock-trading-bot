"""Intraday regime SET monitoring and transition execution."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection
from ..regime_set_service import (
    auto_create_set,
    get_match_preview,
    get_today_application,
    get_today_transitions,
    record_application,
)

logger = logging.getLogger("IntradayRegimeMonitor")
KST = ZoneInfo("Asia/Seoul")
MIN_TRANSITION_INTERVAL_MINUTES = 25


def _today() -> str:
    """Return today's KST trading date as YYYY-MM-DD."""
    return datetime.now(KST).strftime("%Y-%m-%d")


def _to_float(value: Any) -> float | None:
    """Convert a value to float when possible, otherwise return None."""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _json_loads(value: str | None) -> dict[str, Any]:
    """Parse a JSON object text column defensively."""
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _get_morning_vix(trade_date: str) -> float | None:
    """Return the VIX value stored by the morning briefing for a trade date."""
    logger.info("START: IntradayRegimeMonitor._get_morning_vix trade_date=%s", trade_date)
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT market_data FROM morning_context WHERE trade_date = ?",
                (trade_date,),
            ).fetchone()
        if row is None:
            logger.info("SKIP: IntradayRegimeMonitor morning_context missing trade_date=%s", trade_date)
            return None
        market_data = _json_loads(dict(row).get("market_data"))
        vix_data = market_data.get("vix") if isinstance(market_data.get("vix"), dict) else {}
        vix = _to_float(vix_data.get("price") or vix_data.get("value") or market_data.get("vix_value"))
        logger.info("SUCCESS: IntradayRegimeMonitor._get_morning_vix vix=%s", vix)
        return vix
    except Exception as exc:
        logger.warning("WARN: IntradayRegimeMonitor morning VIX lookup failed error=%s", exc)
        return None


def _extract_kospi_change_from_payload(payload: dict[str, Any]) -> float | None:
    """Extract KOSPI change percentage from known snapshot JSON shapes."""
    for key in ("kospi", "KOSPI", "^KS11", "KS11"):
        value = payload.get(key)
        if isinstance(value, dict):
            change = _to_float(
                value.get("change_pct")
                or value.get("change_rate")
                or value.get("chg_rate")
                or value.get("prdy_ctrt")
            )
            if change is not None:
                return change
    return _to_float(
        payload.get("kospi_change_pct")
        or payload.get("kospi_change")
        or payload.get("change_pct")
        or payload.get("change_rate")
        or payload.get("chg_rate")
        or payload.get("prdy_ctrt")
    )


def _get_current_kospi_change() -> float | None:
    """Return the latest KOSPI change percentage from market_snapshots."""
    logger.info("START: IntradayRegimeMonitor._get_current_kospi_change")
    try:
        with get_connection() as conn:
            targeted = conn.execute(
                """
                SELECT symbol, change_rate, raw_json
                FROM market_snapshots
                WHERE UPPER(symbol) IN ('KOSPI', 'KS11', '^KS11')
                ORDER BY captured_at DESC
                LIMIT 1
                """
            ).fetchone()
            row = targeted or conn.execute(
                """
                SELECT symbol, change_rate, raw_json
                FROM market_snapshots
                ORDER BY captured_at DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            logger.info("SKIP: IntradayRegimeMonitor market_snapshots empty")
            return None

        item = dict(row)
        payload_change = _extract_kospi_change_from_payload(_json_loads(item.get("raw_json")))
        change = payload_change if payload_change is not None else _to_float(item.get("change_rate"))
        logger.info(
            "SUCCESS: IntradayRegimeMonitor._get_current_kospi_change symbol=%s change=%s",
            item.get("symbol"),
            change,
        )
        return change
    except Exception as exc:
        logger.warning("WARN: IntradayRegimeMonitor KOSPI change lookup failed error=%s", exc)
        return None


def _judge_regime(vix: float | None, kospi_change: float | None) -> str:
    """Judge the intraday regime from fixed morning VIX and current KOSPI change."""
    vix_value = vix if vix is not None else 20.0
    kospi_value = kospi_change if kospi_change is not None else 0.0
    if vix_value > 28:
        return "volatile"
    if vix_value > 22 and kospi_value < -1.0:
        return "risk_off"
    if kospi_value < -1.5:
        return "risk_off"
    if kospi_value > 0.5 and vix_value < 22:
        return "risk_on"
    return "neutral"


def _should_skip_transition(trade_date: str) -> bool:
    """Return true when the most recent transition is inside the debounce window."""
    transitions = get_today_transitions(trade_date)
    if not transitions:
        return False
    last_at_str = str(transitions[-1].get("applied_at") or transitions[-1].get("created_at") or "")
    if not last_at_str:
        return False
    try:
        last_at = datetime.fromisoformat(last_at_str)
        if last_at.tzinfo is None:
            last_at = last_at.replace(tzinfo=KST)
        elapsed = (datetime.now(KST) - last_at.astimezone(KST)).total_seconds() / 60
        return elapsed < MIN_TRANSITION_INTERVAL_MINUTES
    except Exception as exc:
        logger.warning("WARN: IntradayRegimeMonitor transition interval parse failed error=%s", exc)
        return False


def _insert_transition_alert(
    trade_date: str,
    old_set_name: str,
    new_set_name: str,
    old_regime: str,
    new_regime: str,
    vix: float | None,
    kospi_change: float | None,
) -> None:
    """Insert a system alert for the operator-facing Today Control feed."""
    now = datetime.now(KST)
    detail = {
        "old_regime": old_regime,
        "new_regime": new_regime,
        "old_set_name": old_set_name,
        "new_set_name": new_set_name,
        "vix": vix,
        "kospi_change_pct": kospi_change,
    }
    title = f"[장중 레짐 전환] {now.strftime('%H:%M')} {old_regime} → {new_regime}"
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO system_alerts
                    (id, trade_date, alert_type, severity, title, detail, acknowledged, created_at)
                VALUES (?, ?, 'regime_transition', 'WARNING', ?, ?, 0, ?)
                """,
                (str(uuid.uuid4()), trade_date, title, json.dumps(detail, ensure_ascii=False), now.isoformat()),
            )
        logger.info("SUCCESS: IntradayRegimeMonitor transition alert inserted title=%s", title)
    except Exception as exc:
        logger.warning("WARN: IntradayRegimeMonitor transition alert insert failed error=%s", exc)


async def check_intraday_regime(slot: str = "") -> dict[str, Any]:
    """Check current market conditions and switch the active regime SET when needed.

    Args:
        slot: Scheduler slot label such as 09:30. Empty means manual invocation.
    """
    trade_date = _today()
    now_str = datetime.now(KST).strftime("%H:%M")
    logger.info("START: IntradayRegimeMonitor.check slot=%s trade_date=%s", slot or now_str, trade_date)

    current_app = get_today_application(trade_date)
    if not current_app:
        logger.info("SKIP: IntradayRegimeMonitor no active morning SET trade_date=%s", trade_date)
        return {"ok": True, "action": "skipped", "reason": "no_morning_set"}

    if _should_skip_transition(trade_date):
        logger.info("SKIP: IntradayRegimeMonitor min transition interval trade_date=%s", trade_date)
        return {"ok": True, "action": "skipped", "reason": "min_interval"}

    vix = _get_morning_vix(trade_date)
    kospi_change = _get_current_kospi_change()
    if kospi_change is None:
        logger.info("SKIP: IntradayRegimeMonitor KOSPI change missing trade_date=%s", trade_date)
        return {"ok": True, "action": "skipped", "reason": "no_kospi_data"}

    current_set_id = current_app.get("set_id")
    current_regime = current_app.get("regime_label") or "neutral"
    new_regime = _judge_regime(vix, kospi_change)
    new_match = get_match_preview(new_regime, vix, kospi_change, trade_date)
    if not new_match.get("set_id"):
        logger.warning("WARN: IntradayRegimeMonitor preview has no SET; creating auto SET regime=%s", new_regime)
        new_match = auto_create_set(new_regime, vix, kospi_change)
    new_set_id = new_match.get("set_id")

    if new_set_id == current_set_id:
        logger.info(
            "NO_CHANGE: IntradayRegimeMonitor set_id=%s regime=%s",
            current_set_id,
            current_regime,
        )
        return {"ok": True, "action": "no_change", "set_id": current_set_id, "regime": current_regime}

    logger.info(
        "SWITCH: IntradayRegimeMonitor %s -> %s (%s -> %s)",
        current_set_id,
        new_set_id,
        current_regime,
        new_regime,
    )
    record_application(
        trade_date=trade_date,
        matched_set=new_match,
        regime_label=new_regime,
        vix=vix,
        kospi_change_pct=kospi_change,
        trigger="intraday",
    )
    _insert_transition_alert(
        trade_date=trade_date,
        old_set_name=current_app.get("set_name") or str(current_set_id or ""),
        new_set_name=new_match.get("set_name") or str(new_set_id or ""),
        old_regime=current_regime,
        new_regime=new_regime,
        vix=vix,
        kospi_change=kospi_change,
    )

    logger.info("SUCCESS: IntradayRegimeMonitor switched to set_id=%s", new_set_id)
    return {
        "ok": True,
        "action": "switched",
        "from_set": current_set_id,
        "to_set": new_set_id,
        "from_regime": current_regime,
        "to_regime": new_regime,
        "vix": vix,
        "kospi_change": kospi_change,
    }
