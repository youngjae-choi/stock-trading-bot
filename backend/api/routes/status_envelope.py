"""Shared helpers for read-only pipeline status API envelopes."""

from __future__ import annotations

import logging
from typing import Any

from ...services.scheduler import get_schedule_skip_today_status

logger = logging.getLogger("PipelineStatusEnvelope")


def build_pipeline_read_envelope(
    *,
    payload: dict[str, Any] | None,
    result: dict[str, Any] | None,
    trade_date: str,
    source: str = "backend",
    live: bool = True,
) -> dict[str, Any]:
    """Return a backward-compatible GET envelope with explicit result state.

    Args:
        payload: Existing response payload shape that older callers already use.
        result: The actual persisted pipeline result, or None when not created.
        trade_date: KST trade date used for the read.
        source: Existing envelope source value.
        live: Existing envelope live value.
    """
    has_result = result is not None
    status = "success" if has_result else "pending"
    if not has_result:
        try:
            skip_status = get_schedule_skip_today_status()
            if skip_status.get("skip"):
                status = "skipped"
        except Exception as exc:
            logger.warning("WARN: schedule skip status read failed for envelope reason=%s", exc)

    return {
        "ok": True,
        "source": source,
        "live": live,
        "status": status,
        "has_result": has_result,
        "result": result,
        "trade_date": trade_date,
        "payload": payload,
    }
