"""Human Approval Queue — 운영자 승인 요청 저장 및 결정 로그 관리."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from ..db import get_connection

logger = logging.getLogger("HumanApproval")

_VALID_CHANGE_TYPES = {
    "risk_profile_change",
    "rulepack_change",
    "risk_guard_change",
    "knowledge_change",
    "scoring_weight_change",
    "confidence_threshold_change",
}
_VALID_STATUSES = {"pending", "approved", "rejected", "deferred"}


def _now_utc() -> str:
    """Return a compact UTC timestamp for approval queue rows."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _validate_change_type(change_type: str) -> str:
    """Validate an approval change_type against the allowed operator approval taxonomy."""
    clean_change_type = str(change_type or "").strip()
    if clean_change_type not in _VALID_CHANGE_TYPES:
        raise ValueError(f"invalid change_type: {change_type}")
    return clean_change_type


def _validate_status(status: str) -> str:
    """Validate a request status used by the approval list filter."""
    clean_status = str(status or "").strip()
    if clean_status not in _VALID_STATUSES:
        raise ValueError(f"invalid approval status: {status}")
    return clean_status


def _normalize_payload_json(payload_json: str) -> str:
    """Validate JSON text and store it in compact form so downstream readers get stable data."""
    try:
        parsed = json.loads(payload_json or "{}")
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("payload_json must be valid JSON") from exc
    return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))


def _request_row_to_dict(row: Any) -> dict[str, Any]:
    """Convert a human_approval_queue row into an API-friendly dictionary."""
    request = dict(row)
    try:
        request["payload"] = json.loads(request.get("payload_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        logger.warning("WARN: HumanApproval malformed payload_json request_id=%s", request.get("id"))
        request["payload"] = {}
    return request


def create_approval_request(change_type, title, description, payload_json: str = "{}") -> dict:
    """Create a pending human approval request.

    Args:
        change_type: Type of operational change requiring approval.
        title: Short operator-facing title.
        description: Explanation of the proposed change.
        payload_json: JSON text with machine-readable change details.
    """
    clean_change_type = _validate_change_type(str(change_type))
    clean_title = str(title or "").strip()
    if not clean_title:
        raise ValueError("approval title is required")
    clean_payload_json = _normalize_payload_json(payload_json)
    now = _now_utc()
    request = {
        "id": str(uuid.uuid4()),
        "change_type": clean_change_type,
        "title": clean_title,
        "description": description or "",
        "payload_json": clean_payload_json,
        "payload": json.loads(clean_payload_json),
        "status": "pending",
        "created_at": now,
        "decided_at": None,
    }
    logger.info("START: HumanApproval.create change_type=%s", clean_change_type)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO human_approval_queue
                (id, change_type, title, description, payload_json, status, created_at, decided_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?, NULL)
            """,
            (
                request["id"],
                request["change_type"],
                request["title"],
                request["description"],
                request["payload_json"],
                request["created_at"],
            ),
        )
    logger.info("SUCCESS: HumanApproval.create request_id=%s", request["id"])
    return request


def list_approval_requests(status: str | None = None) -> list[dict]:
    """List human approval requests, optionally filtered by status.

    Args:
        status: Optional pending, approved, rejected, or deferred filter.
    """
    logger.info("START: HumanApproval.list status=%s", status or "all")
    params: list[Any] = []
    where_sql = ""
    if status:
        where_sql = "WHERE status = ?"
        params.append(_validate_status(status))
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM human_approval_queue
            {where_sql}
            ORDER BY created_at DESC
            """,
            params,
        ).fetchall()
    requests = [_request_row_to_dict(row) for row in rows]
    logger.info("SUCCESS: HumanApproval.list count=%d", len(requests))
    return requests


def _decide_request(request_id: str, action: str, reason: str = "") -> dict:
    """Apply one approval decision and write its immutable decision log."""
    clean_action = _validate_status(action)
    if clean_action == "pending":
        raise ValueError("pending is not a decision action")
    now = _now_utc()
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM human_approval_queue WHERE id = ?", (request_id,)).fetchone()
        if row is None:
            raise KeyError(request_id)
        conn.execute(
            "UPDATE human_approval_queue SET status = ?, decided_at = ? WHERE id = ?",
            (clean_action, now, request_id),
        )
        conn.execute(
            """
            INSERT INTO approval_decision_logs (id, request_id, action, reason, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), request_id, clean_action, reason or "", now),
        )
    return {"ok": True, "request_id": request_id, "status": clean_action}


def approve_request(request_id, reason: str = "") -> dict:
    """Approve a pending human approval request and record the decision reason.

    Args:
        request_id: human_approval_queue.id value.
        reason: Optional operator decision reason.
    """
    logger.info("START: HumanApproval.approve request_id=%s", request_id)
    result = _decide_request(str(request_id), "approved", reason)
    logger.info("SUCCESS: HumanApproval.approve request_id=%s", request_id)
    return result


def reject_request(request_id, reason: str = "") -> dict:
    """Reject a pending human approval request and record the decision reason.

    Args:
        request_id: human_approval_queue.id value.
        reason: Optional operator decision reason.
    """
    logger.info("START: HumanApproval.reject request_id=%s", request_id)
    result = _decide_request(str(request_id), "rejected", reason)
    logger.info("SUCCESS: HumanApproval.reject request_id=%s", request_id)
    return result


def defer_request(request_id, reason: str = "") -> dict:
    """Defer a pending human approval request and record the decision reason.

    Args:
        request_id: human_approval_queue.id value.
        reason: Optional operator decision reason.
    """
    logger.info("START: HumanApproval.defer request_id=%s", request_id)
    result = _decide_request(str(request_id), "deferred", reason)
    logger.info("SUCCESS: HumanApproval.defer request_id=%s", request_id)
    return result
