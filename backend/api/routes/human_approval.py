"""Human Approval API routes for operator-governed changes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...services.engine.human_approval import (
    approve_request,
    create_approval_request,
    defer_request,
    list_approval_requests,
    reject_request,
)

router = APIRouter(prefix="/api/v1/approval", tags=["approval"])
logger = logging.getLogger("HumanApprovalAPI")


class ApprovalCreateRequest(BaseModel):
    """Request body for creating a pending human approval request."""

    change_type: str
    title: str = Field(..., min_length=1)
    description: str = ""
    payload_json: str = "{}"


class ApprovalDecisionRequest(BaseModel):
    """Request body for an approval decision reason."""

    reason: str = ""


def _raise_bad_request(exc: ValueError) -> None:
    """Convert service validation errors into HTTP 400 responses."""
    logger.warning("WARN: HumanApprovalAPI validation failed reason=%s", exc)
    raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/")
def create_request(body: ApprovalCreateRequest) -> dict:
    """Create a pending human approval request."""
    logger.info("START: POST /api/v1/approval change_type=%s", body.change_type)
    try:
        request = create_approval_request(
            change_type=body.change_type,
            title=body.title,
            description=body.description,
            payload_json=body.payload_json,
        )
    except ValueError as exc:
        _raise_bad_request(exc)
    except Exception as exc:
        logger.error("FAIL: POST /api/v1/approval reason=%s", exc)
        raise HTTPException(status_code=500, detail="Approval request creation failed") from exc
    logger.info("SUCCESS: POST /api/v1/approval request_id=%s", request["id"])
    return {"ok": True, "payload": request}


@router.get("/")
def list_requests(status: str | None = None) -> dict:
    """Return human approval requests, optionally filtered by status."""
    logger.info("START: GET /api/v1/approval status=%s", status or "all")
    try:
        requests = list_approval_requests(status=status)
    except ValueError as exc:
        _raise_bad_request(exc)
    except Exception as exc:
        logger.error("FAIL: GET /api/v1/approval reason=%s", exc)
        raise HTTPException(status_code=500, detail="Approval request list failed") from exc
    logger.info("SUCCESS: GET /api/v1/approval count=%d", len(requests))
    return {"ok": True, "payload": requests}


@router.post("/{request_id}/approve")
def approve(request_id: str, body: ApprovalDecisionRequest | None = None) -> dict:
    """Approve one human approval request."""
    logger.info("START: POST /api/v1/approval/%s/approve", request_id)
    try:
        result = approve_request(request_id, reason=body.reason if body else "")
    except KeyError as exc:
        logger.warning("WARN: POST /api/v1/approval/%s/approve not_found", request_id)
        raise HTTPException(status_code=404, detail="Approval request not found") from exc
    except ValueError as exc:
        _raise_bad_request(exc)
    except Exception as exc:
        logger.error("FAIL: POST /api/v1/approval/%s/approve reason=%s", request_id, exc)
        raise HTTPException(status_code=500, detail="Approval request approval failed") from exc
    logger.info("SUCCESS: POST /api/v1/approval/%s/approve", request_id)
    return {"ok": True, "payload": result}


@router.post("/{request_id}/reject")
def reject(request_id: str, body: ApprovalDecisionRequest | None = None) -> dict:
    """Reject one human approval request."""
    logger.info("START: POST /api/v1/approval/%s/reject", request_id)
    try:
        result = reject_request(request_id, reason=body.reason if body else "")
    except KeyError as exc:
        logger.warning("WARN: POST /api/v1/approval/%s/reject not_found", request_id)
        raise HTTPException(status_code=404, detail="Approval request not found") from exc
    except ValueError as exc:
        _raise_bad_request(exc)
    except Exception as exc:
        logger.error("FAIL: POST /api/v1/approval/%s/reject reason=%s", request_id, exc)
        raise HTTPException(status_code=500, detail="Approval request rejection failed") from exc
    logger.info("SUCCESS: POST /api/v1/approval/%s/reject", request_id)
    return {"ok": True, "payload": result}


@router.post("/{request_id}/defer")
def defer(request_id: str, body: ApprovalDecisionRequest | None = None) -> dict:
    """Defer one human approval request."""
    logger.info("START: POST /api/v1/approval/%s/defer", request_id)
    try:
        result = defer_request(request_id, reason=body.reason if body else "")
    except KeyError as exc:
        logger.warning("WARN: POST /api/v1/approval/%s/defer not_found", request_id)
        raise HTTPException(status_code=404, detail="Approval request not found") from exc
    except ValueError as exc:
        _raise_bad_request(exc)
    except Exception as exc:
        logger.error("FAIL: POST /api/v1/approval/%s/defer reason=%s", request_id, exc)
        raise HTTPException(status_code=500, detail="Approval request deferral failed") from exc
    logger.info("SUCCESS: POST /api/v1/approval/%s/defer", request_id)
    return {"ok": True, "payload": result}
