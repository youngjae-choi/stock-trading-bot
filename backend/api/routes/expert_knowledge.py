"""Expert Knowledge API routes for operator-approved strategy context."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...services.db import get_connection
from ...services.engine.expert_knowledge import (
    approve_knowledge,
    create_knowledge_item,
    get_active_knowledge,
    get_knowledge_item,
    list_knowledge_items,
    reject_knowledge,
)

router = APIRouter(prefix="/api/v1/expert-knowledge", tags=["expert-knowledge"])
logger = logging.getLogger("ExpertKnowledgeAPI")


class KnowledgeCreateRequest(BaseModel):
    """Request body for creating a pending Expert Knowledge item."""

    title: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    scope: str
    category: str = "general"
    priority: int = Field(default=5, ge=1, le=10)
    auto_inject: bool = False
    expires_at: str | None = None


class KnowledgeActionRequest(BaseModel):
    """Request body for approval or rejection reason metadata."""

    reason: str = ""


def _raise_bad_request(exc: ValueError) -> None:
    """Convert validation errors from the service layer into HTTP 400 responses."""
    logger.warning("WARN: ExpertKnowledgeAPI validation failed reason=%s", exc)
    raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/impact")
def get_knowledge_impact() -> dict:
    """Return Knowledge Impact statistics rows for judgment validation."""
    logger.info("START: GET /api/v1/expert-knowledge/impact")
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM knowledge_impact_stats
                ORDER BY trade_date DESC, created_at DESC
                """
            ).fetchall()
    except Exception as exc:
        logger.error("FAIL: GET /api/v1/expert-knowledge/impact reason=%s", exc)
        raise HTTPException(status_code=500, detail="Knowledge impact lookup failed") from exc
    payload = [dict(row) for row in rows]
    logger.info("SUCCESS: GET /api/v1/expert-knowledge/impact count=%d", len(payload))
    return {"ok": True, "payload": payload}


@router.post("/")
def create_item(body: KnowledgeCreateRequest) -> dict:
    """Create a pending Expert Knowledge item for later approval."""
    logger.info("START: POST /api/v1/expert-knowledge scope=%s", body.scope)
    try:
        item = create_knowledge_item(
            title=body.title,
            content=body.content,
            scope=body.scope,
            category=body.category,
            priority=body.priority,
            auto_inject=body.auto_inject,
            expires_at=body.expires_at,
        )
    except ValueError as exc:
        _raise_bad_request(exc)
    except Exception as exc:
        logger.error("FAIL: POST /api/v1/expert-knowledge reason=%s", exc)
        raise HTTPException(status_code=500, detail="Expert knowledge item creation failed") from exc
    logger.info("SUCCESS: POST /api/v1/expert-knowledge item_id=%s", item["id"])
    return {"ok": True, "payload": item}


@router.get("/")
def list_items(scope: str | None = None, status: str | None = None) -> dict:
    """Return Expert Knowledge items, optionally filtered by scope and status."""
    logger.info("START: GET /api/v1/expert-knowledge scope=%s status=%s", scope or "all", status or "all")
    try:
        items = list_knowledge_items(scope=scope, status=status)
    except ValueError as exc:
        _raise_bad_request(exc)
    except Exception as exc:
        logger.error("FAIL: GET /api/v1/expert-knowledge reason=%s", exc)
        raise HTTPException(status_code=500, detail="Expert knowledge list failed") from exc
    logger.info("SUCCESS: GET /api/v1/expert-knowledge count=%d", len(items))
    return {"ok": True, "payload": items}


@router.get("/{item_id}")
def get_item(item_id: str) -> dict:
    """Return one Expert Knowledge item by id."""
    logger.info("START: GET /api/v1/expert-knowledge/%s", item_id)
    item = get_knowledge_item(item_id)
    if item is None:
        logger.warning("WARN: GET /api/v1/expert-knowledge/%s not_found", item_id)
        raise HTTPException(status_code=404, detail="Expert knowledge item not found")
    logger.info("SUCCESS: GET /api/v1/expert-knowledge/%s", item_id)
    return {"ok": True, "payload": item}


@router.post("/{item_id}/approve")
def approve_item(item_id: str, body: KnowledgeActionRequest | None = None) -> dict:
    """Approve one Expert Knowledge item and record the approval reason."""
    logger.info("START: POST /api/v1/expert-knowledge/%s/approve", item_id)
    try:
        result = approve_knowledge(item_id, reason=body.reason if body else "")
    except KeyError as exc:
        logger.warning("WARN: ExpertKnowledge approve not_found item_id=%s", item_id)
        raise HTTPException(status_code=404, detail="Expert knowledge item not found") from exc
    except Exception as exc:
        logger.error("FAIL: ExpertKnowledge approve item_id=%s reason=%s", item_id, exc)
        raise HTTPException(status_code=500, detail="Expert knowledge approval failed") from exc
    logger.info("SUCCESS: POST /api/v1/expert-knowledge/%s/approve", item_id)
    return {"ok": True, "payload": result}


@router.post("/{item_id}/reject")
def reject_item(item_id: str, body: KnowledgeActionRequest | None = None) -> dict:
    """Reject one Expert Knowledge item and record the rejection reason."""
    logger.info("START: POST /api/v1/expert-knowledge/%s/reject", item_id)
    try:
        result = reject_knowledge(item_id, reason=body.reason if body else "")
    except KeyError as exc:
        logger.warning("WARN: ExpertKnowledge reject not_found item_id=%s", item_id)
        raise HTTPException(status_code=404, detail="Expert knowledge item not found") from exc
    except Exception as exc:
        logger.error("FAIL: ExpertKnowledge reject item_id=%s reason=%s", item_id, exc)
        raise HTTPException(status_code=500, detail="Expert knowledge rejection failed") from exc
    logger.info("SUCCESS: POST /api/v1/expert-knowledge/%s/reject", item_id)
    return {"ok": True, "payload": result}


@router.get("/active/{scope}")
def get_active(scope: str) -> dict:
    """Return approved, non-expired Expert Knowledge items for a pipeline scope."""
    logger.info("START: GET /api/v1/expert-knowledge/active/%s", scope)
    try:
        items = get_active_knowledge(scope=scope)
    except ValueError as exc:
        _raise_bad_request(exc)
    except Exception as exc:
        logger.error("FAIL: ExpertKnowledge active scope=%s reason=%s", scope, exc)
        raise HTTPException(status_code=500, detail="Expert knowledge active lookup failed") from exc
    logger.info("SUCCESS: GET /api/v1/expert-knowledge/active/%s count=%d", scope, len(items))
    return {"ok": True, "payload": items}
