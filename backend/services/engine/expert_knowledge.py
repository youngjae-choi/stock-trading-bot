"""Expert Knowledge Base — 운영자 정성 지식 관리 및 S3/S4/S5 주입."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any

from ..db import get_connection

logger = logging.getLogger("ExpertKnowledge")

_VALID_SCOPES = {"S3_UNIVERSE_FILTER", "S4_HYBRID_SCREENING", "S5_DAILY_PLAN", "ALL"}
_VALID_CATEGORIES = {"timing", "sector", "profile", "risk", "general"}
_VALID_STATUSES = {"pending", "approved", "rejected"}


def _now_utc() -> str:
    """Return the current UTC timestamp for Expert Knowledge DB rows."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _validate_scope(scope: str) -> str:
    """Validate and normalize a knowledge scope parameter."""
    normalized = str(scope or "").strip()
    if normalized not in _VALID_SCOPES:
        raise ValueError(f"invalid scope: {scope}")
    return normalized


def _validate_category(category: str) -> str:
    """Validate and normalize a knowledge category parameter."""
    normalized = str(category or "general").strip()
    if normalized not in _VALID_CATEGORIES:
        raise ValueError(f"invalid category: {category}")
    return normalized


def _hydrate_item(row: Any) -> dict[str, Any]:
    """Convert a strategy_knowledge_items row into an API-friendly dictionary."""
    item = dict(row)
    item["auto_inject"] = bool(item.get("auto_inject"))
    return item


def _is_not_expired(expires_at: str | None) -> bool:
    """Return whether an optional expiry date/time should still be considered active."""
    if not expires_at:
        return True
    text = str(expires_at).strip()
    try:
        if "T" in text:
            parsed_dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            now = datetime.now(parsed_dt.tzinfo or timezone.utc)
            return parsed_dt >= now
        return date.fromisoformat(text) >= datetime.now(timezone.utc).date()
    except ValueError:
        logger.warning("WARN: ExpertKnowledge invalid expires_at ignored expires_at=%s", expires_at)
        return True


def create_knowledge_item(
    title: str,
    content: str,
    scope: str,
    category: str = "general",
    priority: int = 5,
    auto_inject: bool = False,
    expires_at: str | None = None,
) -> dict:
    """Create a pending Expert Knowledge item.

    Args:
        title: Short operator-facing title.
        content: Strategy knowledge text that may be injected into prompts after approval.
        scope: Target pipeline scope or ALL.
        category: Knowledge category such as timing, sector, profile, risk, or general.
        priority: Injection order where 1 is highest priority and 10 is lowest.
        auto_inject: Whether this item should be marked for automatic injection after approval.
        expires_at: Optional ISO date or datetime after which the item is inactive.
    """
    logger.info("START: ExpertKnowledge.create scope=%s category=%s", scope, category)
    clean_title = str(title or "").strip()
    clean_content = str(content or "").strip()
    if not clean_title or not clean_content:
        raise ValueError("title and content are required")
    clean_scope = _validate_scope(scope)
    clean_category = _validate_category(category)
    clean_priority = max(1, min(10, int(priority)))
    item = {
        "id": str(uuid.uuid4()),
        "source_id": None,
        "title": clean_title,
        "content": clean_content,
        "scope": clean_scope,
        "category": clean_category,
        "status": "pending",
        "auto_inject": bool(auto_inject),
        "priority": clean_priority,
        "created_at": _now_utc(),
        "approved_at": None,
        "expires_at": expires_at,
    }
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO strategy_knowledge_items
                (id, source_id, title, content, scope, category, status,
                 auto_inject, priority, created_at, approved_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["id"],
                item["source_id"],
                item["title"],
                item["content"],
                item["scope"],
                item["category"],
                item["status"],
                1 if item["auto_inject"] else 0,
                item["priority"],
                item["created_at"],
                item["approved_at"],
                item["expires_at"],
            ),
        )
    logger.info("SUCCESS: ExpertKnowledge.create item_id=%s", item["id"])
    return item


def list_knowledge_items(scope: str | None = None, status: str | None = None) -> list[dict]:
    """List Expert Knowledge items with optional scope and status filters.

    Args:
        scope: Optional target scope filter.
        status: Optional pending, approved, or rejected filter.
    """
    logger.info("START: ExpertKnowledge.list scope=%s status=%s", scope or "all", status or "all")
    clauses: list[str] = []
    params: list[Any] = []
    if scope:
        clauses.append("scope = ?")
        params.append(_validate_scope(scope))
    if status:
        normalized_status = str(status).strip()
        if normalized_status not in _VALID_STATUSES:
            raise ValueError(f"invalid status: {status}")
        clauses.append("status = ?")
        params.append(normalized_status)
    where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM strategy_knowledge_items{where_sql} ORDER BY created_at DESC",
            params,
        ).fetchall()
    items = [_hydrate_item(row) for row in rows]
    logger.info("SUCCESS: ExpertKnowledge.list count=%d", len(items))
    return items


def get_knowledge_item(item_id: str) -> dict | None:
    """Return one Expert Knowledge item by id.

    Args:
        item_id: strategy_knowledge_items.id value.
    """
    logger.info("START: ExpertKnowledge.get item_id=%s", item_id)
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM strategy_knowledge_items WHERE id = ?", (item_id,)).fetchone()
    item = _hydrate_item(row) if row else None
    logger.info("SUCCESS: ExpertKnowledge.get item_id=%s found=%s", item_id, bool(item))
    return item


def approve_knowledge(item_id: str, reason: str = "") -> dict:
    """Approve a pending Expert Knowledge item and write an approval audit log.

    Args:
        item_id: strategy_knowledge_items.id value.
        reason: Optional operator approval reason.
    """
    logger.info("START: ExpertKnowledge.approve item_id=%s", item_id)
    now = _now_utc()
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM strategy_knowledge_items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise KeyError(item_id)
        conn.execute(
            "UPDATE strategy_knowledge_items SET status = 'approved', approved_at = ? WHERE id = ?",
            (now, item_id),
        )
        conn.execute(
            """
            INSERT INTO knowledge_approval_logs (id, knowledge_id, action, reason, created_at)
            VALUES (?, ?, 'approve', ?, ?)
            """,
            (str(uuid.uuid4()), item_id, reason or "", now),
        )
    logger.info("SUCCESS: ExpertKnowledge.approve item_id=%s", item_id)
    return {"ok": True, "item_id": item_id, "status": "approved"}


def reject_knowledge(item_id: str, reason: str = "") -> dict:
    """Reject an Expert Knowledge item and write an approval audit log.

    Args:
        item_id: strategy_knowledge_items.id value.
        reason: Optional operator rejection reason.
    """
    logger.info("START: ExpertKnowledge.reject item_id=%s", item_id)
    now = _now_utc()
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM strategy_knowledge_items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise KeyError(item_id)
        conn.execute(
            "UPDATE strategy_knowledge_items SET status = 'rejected' WHERE id = ?",
            (item_id,),
        )
        conn.execute(
            """
            INSERT INTO knowledge_approval_logs (id, knowledge_id, action, reason, created_at)
            VALUES (?, ?, 'reject', ?, ?)
            """,
            (str(uuid.uuid4()), item_id, reason or "", now),
        )
    logger.info("SUCCESS: ExpertKnowledge.reject item_id=%s", item_id)
    return {"ok": True, "item_id": item_id, "status": "rejected"}


def get_active_knowledge(scope: str) -> list[dict]:
    """Return approved, non-expired knowledge for one pipeline scope plus ALL.

    Args:
        scope: Target S3/S4/S5 scope requesting prompt context.
    """
    clean_scope = _validate_scope(scope)
    logger.info("START: ExpertKnowledge.active scope=%s", clean_scope)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM strategy_knowledge_items
            WHERE status = 'approved' AND (scope = ? OR scope = 'ALL')
            ORDER BY priority ASC, created_at DESC
            """,
            (clean_scope,),
        ).fetchall()
    items = [_hydrate_item(row) for row in rows]
    active_items = [item for item in items if _is_not_expired(item.get("expires_at"))]
    logger.info("SUCCESS: ExpertKnowledge.active scope=%s count=%d", clean_scope, len(active_items))
    return active_items


def build_knowledge_prompt_snippet(knowledge_items: list[dict]) -> str:
    """Build the prompt section used to inject approved operator knowledge.

    Args:
        knowledge_items: Approved Expert Knowledge items returned by get_active_knowledge.
    """
    if not knowledge_items:
        return ""
    lines = ["## Expert Knowledge (운영자 승인 전략 지식)"]
    for item in knowledge_items:
        lines.append(
            f"- [{item.get('category', 'general')}/{item.get('scope', '?')}] {item.get('content', '')}"
        )
    return "\n".join(lines) + "\n"
