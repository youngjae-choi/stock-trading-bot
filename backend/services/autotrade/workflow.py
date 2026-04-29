"""Safe auto-trading workflow (dry-run/live split + standardized responses)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Literal

from ..kis.common.market_interface import order_cash as market_order_cash
from ..sim_store import create_order

LIVE_CONFIRM_TEXT = "AUTO_TRADE_LIVE_CONFIRM"


def _classify_error(message: str) -> str:
    text = message.lower()
    if any(token in text for token in ["rate", "too many", "초당", "호출 제한"]):
        return "rate_limit"
    if any(token in text for token in ["권한", "인증", "forbidden", "unauthorized"]):
        return "permission"
    if any(token in text for token in ["장종료", "시간외", "market closed"]):
        return "market_hours"
    return "api_error"


def _normalize_error(exc: Exception) -> Dict[str, Any]:
    message = str(exc)
    return {
        "code": _classify_error(message),
        "message": message,
        "retryable": _classify_error(message) in {"rate_limit", "api_error"},
    }


def _side_for_sim(side: str) -> Literal["BUY", "SELL"]:
    return "BUY" if side.lower() == "buy" else "SELL"


async def execute_auto_trade(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Execute auto-trade workflow with hard safety checks."""
    workflow_id = f"AT-{uuid.uuid4().hex[:10].upper()}"
    mode = str(payload.get("mode", "dry_run"))
    side = str(payload.get("side", "buy")).lower()
    market = str(payload.get("market", "domestic"))
    symbol = str(payload.get("symbol", "")).strip().upper()
    exchange = str(payload.get("exchange", "NASD")).strip().upper()
    qty = int(payload.get("qty", 0))
    price = str(payload.get("price", "0"))

    if side not in {"buy", "sell"}:
        return {"ok": False, "workflow_id": workflow_id, "error": {"code": "validation", "message": "side must be buy/sell", "retryable": False}}
    if qty <= 0:
        return {"ok": False, "workflow_id": workflow_id, "error": {"code": "validation", "message": "qty must be > 0", "retryable": False}}
    if not symbol:
        return {"ok": False, "workflow_id": workflow_id, "error": {"code": "validation", "message": "symbol required", "retryable": False}}

    base_response = {
        "workflow_id": workflow_id,
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "request": {
            "market": market,
            "exchange": exchange,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": price,
        },
    }

    if mode == "dry_run":
        sim_price = float(str(price).replace(",", ""))
        created = create_order(symbol=symbol, side=_side_for_sim(side), qty=qty, price=sim_price)
        return {
            "ok": True,
            **base_response,
            "order": {
                "status": "accepted",
                "execution_path": "local_simulation",
                "order_id": created["order"]["order_id"],
                "message": "dry_run 모드로 로컬 시뮬레이션 주문만 기록되었습니다.",
            },
            "raw": created,
        }

    confirm = str(payload.get("confirm_text", "")).strip()
    if confirm != LIVE_CONFIRM_TEXT:
        return {
            "ok": False,
            **base_response,
            "error": {
                "code": "confirm_required",
                "message": f"live mode requires confirm_text={LIVE_CONFIRM_TEXT}",
                "retryable": False,
            },
        }

    try:
        raw = await market_order_cash(
            market="overseas" if market == "overseas" else "domestic",
            side=side,
            symbol=symbol,
            qty=qty,
            price=price,
            exchange=exchange,
            ord_dvsn="00",
        )
        return {
            "ok": True,
            **base_response,
            "order": {
                "status": "accepted",
                "execution_path": "kis_rest",
                "message": "live mode 주문 요청이 KIS REST로 전달되었습니다.",
            },
            "raw": raw,
        }
    except Exception as exc:
        return {"ok": False, **base_response, "error": _normalize_error(exc)}


async def run_autotrade_scenarios() -> Dict[str, Any]:
    """Run mock-first auto-trading scenario tests."""
    scenarios = [
        {
            "id": "dryrun.domestic.buy",
            "payload": {"mode": "dry_run", "market": "domestic", "symbol": "005930", "side": "buy", "qty": 1, "price": "70000"},
        },
        {
            "id": "dryrun.overseas.buy",
            "payload": {"mode": "dry_run", "market": "overseas", "exchange": "NASD", "symbol": "AAPL", "side": "buy", "qty": 1, "price": "150"},
        },
        {
            "id": "live.guard",
            "payload": {"mode": "live", "market": "domestic", "symbol": "005930", "side": "buy", "qty": 1, "price": "70000", "confirm_text": ""},
            "expected_error_code": "confirm_required",
        },
    ]

    results = []
    for scenario in scenarios:
        result = await execute_auto_trade(scenario["payload"])
        expected_error = scenario.get("expected_error_code")
        passed = bool(result.get("ok")) if not expected_error else (not result.get("ok") and result.get("error", {}).get("code") == expected_error)
        results.append({"id": scenario["id"], "passed": passed, "result": result})

    return {
        "ok": all(row["passed"] for row in results),
        "count": len(results),
        "passed": len([row for row in results if row["passed"]]),
        "failed": len([row for row in results if not row["passed"]]),
        "results": results,
    }
