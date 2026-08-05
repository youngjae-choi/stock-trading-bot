"""Expert Knowledge API routes for operator-approved strategy context."""

from __future__ import annotations

import logging
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ...api.dependencies import require_console_user
from ...services.db import get_connection
from ...services.settings_store import upsert_setting
from ...services.engine.expert_knowledge import (
    MAPPABLE_SETTINGS,
    approve_knowledge,
    classify_strategy_candidate,
    create_knowledge_item,
    get_active_knowledge,
    get_knowledge_item,
    list_knowledge_items,
    reject_knowledge,
)

router = APIRouter(
    prefix="/api/v1/expert-knowledge",
    tags=["expert-knowledge"],
    dependencies=[Depends(require_console_user)],
)
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


class StrategyApplyRequest(BaseModel):
    """Request body for applying approved PDF strategy candidates to Settings."""

    approved_keys: list[str]


def _now_utc() -> str:
    """Return the current UTC timestamp for PDF analysis audit rows."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _raise_bad_request(exc: ValueError) -> None:
    """Convert validation errors from the service layer into HTTP 400 responses."""
    logger.warning("WARN: ExpertKnowledgeAPI validation failed reason=%s", exc)
    raise HTTPException(status_code=400, detail=str(exc)) from exc


def _error_response(status_code: int, message: str) -> JSONResponse:
    """Return the console's standard ok/error JSON envelope with an HTTP error status."""
    return JSONResponse(status_code=status_code, content={"ok": False, "error": message})


@router.get("/impact")
def get_knowledge_impact() -> dict[str, Any]:
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
def create_item(body: KnowledgeCreateRequest) -> dict[str, Any]:
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
        raise AssertionError("unreachable")
    except Exception as exc:
        logger.error("FAIL: POST /api/v1/expert-knowledge reason=%s", exc)
        raise HTTPException(status_code=500, detail="Expert knowledge item creation failed") from exc
    logger.info("SUCCESS: POST /api/v1/expert-knowledge item_id=%s", item["id"])
    return {"ok": True, "payload": item}


@router.get("/")
def list_items(scope: str | None = None, status: str | None = None) -> dict[str, Any]:
    """Return Expert Knowledge items, optionally filtered by scope and status."""
    logger.info("START: GET /api/v1/expert-knowledge scope=%s status=%s", scope or "all", status or "all")
    try:
        items = list_knowledge_items(scope=scope, status=status)
    except ValueError as exc:
        _raise_bad_request(exc)
        raise AssertionError("unreachable")
    except Exception as exc:
        logger.error("FAIL: GET /api/v1/expert-knowledge reason=%s", exc)
        raise HTTPException(status_code=500, detail="Expert knowledge list failed") from exc
    logger.info("SUCCESS: GET /api/v1/expert-knowledge count=%d", len(items))
    return {"ok": True, "payload": items}


@router.post("/apply-strategy/{analysis_id}", response_model=None)
async def apply_strategy(
    analysis_id: str,
    body: StrategyApplyRequest,
    user: dict[str, Any] = Depends(require_console_user),
) -> dict[str, Any] | JSONResponse:
    """승인된 전략 후보를 Settings에 적용한다.

    Args:
        analysis_id: pdf_analyses.analysis_id 값.
        body: 적용할 Settings 키 목록.
        user: 콘솔 인증 사용자 정보.
    """
    logger.info("START: POST /api/v1/expert-knowledge/apply-strategy/%s", analysis_id)
    approved_keys = set(body.approved_keys or [])
    with get_connection() as conn:
        row = conn.execute(
            "SELECT analysis_id, candidates FROM pdf_analyses WHERE analysis_id = ?",
            (analysis_id,),
        ).fetchone()
    if row is None:
        logger.warning("WARN: ExpertKnowledge apply not_found analysis_id=%s", analysis_id)
        return _error_response(404, "PDF 분석 이력을 찾을 수 없습니다")

    applied: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    approval_required: list[dict[str, str]] = []
    messages: list[str] = []
    try:
        candidates = json.loads(row["candidates"] or "[]")
    except json.JSONDecodeError as exc:
        logger.error("FAIL: ExpertKnowledge apply invalid_candidates analysis_id=%s reason=%s", analysis_id, exc)
        raise HTTPException(status_code=500, detail="저장된 분석 결과를 읽을 수 없습니다") from exc

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        setting_key = str(candidate.get("setting_key") or "").strip()
        if setting_key not in approved_keys:
            continue
        mapped = MAPPABLE_SETTINGS.get(setting_key)
        if not mapped:
            skipped.append({"setting_key": setting_key, "reason": "매핑 가능한 Settings 키가 아닙니다"})
            logger.warning(
                "WARN: ExpertKnowledge apply skipped_unmapped analysis_id=%s setting_key=%s",
                analysis_id,
                setting_key,
            )
            continue
        label, value_type = mapped
        value = str(candidate.get("value") or "")
        safety = classify_strategy_candidate(setting_key)
        if not safety["auto_applicable"]:
            reason = str(safety["safety_reason"])
            approval_required.append({"setting_key": setting_key, "value": value, "reason": reason})
            skipped.append({"setting_key": setting_key, "value": value, "reason": reason})
            messages.append(f"{setting_key}: PM 승인 필요로 Settings 자동 적용 제외")
            logger.warning(
                "WARN: ExpertKnowledge apply approval_required analysis_id=%s setting_key=%s reason=%s",
                analysis_id,
                setting_key,
                reason,
            )
            continue
        try:
            upsert_setting(setting_key, value, value_type, label, user.get("username", "expert-knowledge"))
        except Exception as exc:
            logger.error(
                "FAIL: ExpertKnowledge apply upsert_failed analysis_id=%s setting_key=%s reason=%s",
                analysis_id,
                setting_key,
                exc,
            )
            raise
        applied.append({"setting_key": setting_key, "value": value})
        messages.append(f"{setting_key}: {value} 적용 완료")

    with get_connection() as conn:
        conn.execute(
            "UPDATE pdf_analyses SET status = ?, applied_at = ? WHERE analysis_id = ?",
            ("applied" if applied else "pending", _now_utc() if applied else None, analysis_id),
        )

    logger.info(
        "SUCCESS: POST /api/v1/expert-knowledge/apply-strategy/%s applied=%d skipped=%d approval_required=%d",
        analysis_id,
        len(applied),
        len(skipped),
        len(approval_required),
    )
    return {
        "ok": True,
        "payload": {
            "applied": applied,
            "skipped": skipped,
            "approval_required": approval_required,
            "messages": messages,
        },
    }


@router.get("/analyses")
async def list_analyses(user: dict[str, Any] = Depends(require_console_user)) -> dict[str, Any]:
    """PDF 분석 이력 목록 반환 (최신 10건).

    Args:
        user: 콘솔 인증 사용자 정보.
    """
    logger.info("START: GET /api/v1/expert-knowledge/analyses user=%s", user.get("username", "unknown"))
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT analysis_id, filename, summary, status, created_at, applied_at
            FROM pdf_analyses
            ORDER BY created_at DESC
            LIMIT 10
            """
        ).fetchall()
    payload = [dict(row) for row in rows]
    logger.info("SUCCESS: GET /api/v1/expert-knowledge/analyses count=%d", len(payload))
    return {"ok": True, "payload": payload}


@router.get("/{item_id}")
def get_item(item_id: str) -> dict[str, Any]:
    """Return one Expert Knowledge item by id."""
    logger.info("START: GET /api/v1/expert-knowledge/%s", item_id)
    item = get_knowledge_item(item_id)
    if item is None:
        logger.warning("WARN: GET /api/v1/expert-knowledge/%s not_found", item_id)
        raise HTTPException(status_code=404, detail="Expert knowledge item not found")
    logger.info("SUCCESS: GET /api/v1/expert-knowledge/%s", item_id)
    return {"ok": True, "payload": item}


@router.post("/{item_id}/approve")
def approve_item(item_id: str, body: KnowledgeActionRequest | None = None) -> dict[str, Any]:
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
def reject_item(item_id: str, body: KnowledgeActionRequest | None = None) -> dict[str, Any]:
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
def get_active(scope: str) -> dict[str, Any]:
    """Return approved, non-expired Expert Knowledge items for a pipeline scope."""
    logger.info("START: GET /api/v1/expert-knowledge/active/%s", scope)
    try:
        items = get_active_knowledge(scope=scope)
    except ValueError as exc:
        _raise_bad_request(exc)
        raise AssertionError("unreachable")
    except Exception as exc:
        logger.error("FAIL: ExpertKnowledge active scope=%s reason=%s", scope, exc)
        raise HTTPException(status_code=500, detail="Expert knowledge active lookup failed") from exc
    logger.info("SUCCESS: GET /api/v1/expert-knowledge/active/%s count=%d", scope, len(items))
    return {"ok": True, "payload": items}
