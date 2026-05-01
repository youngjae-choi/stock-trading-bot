"""RulePack CRUD and activation REST API."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ...api.dependencies import require_console_user
from ...services.engine import rulepack_store, rulepack_validator

logger = logging.getLogger("BackendRulePackAPI")
router = APIRouter(prefix="/api/v1/rulepack", tags=["rulepack"], dependencies=[Depends(require_console_user)])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class MachineRulesLayer3Entry(BaseModel):
    vwap_position: str = Field("any", description="above | below | any")
    volume_ratio_min: float = Field(1.0, ge=0)
    ma5_above_ma20: bool = True
    rsi_range: list[float] = Field(default_factory=lambda: [30.0, 75.0])
    spread_max_pct: float = Field(0.5, ge=0)
    index_sync: bool = True
    ai_confidence_min: float = Field(0.0, ge=0, le=1)


class MachineRulesRiskLimits(BaseModel):
    daily_loss_limit_pct: float = Field(..., gt=0, le=5.0)
    max_positions: int = Field(..., gt=0, le=20)
    position_size_pct: float = Field(..., gt=0, le=30.0)


class MachineRules(BaseModel):
    layer3_entry: MachineRulesLayer3Entry = Field(default_factory=MachineRulesLayer3Entry)
    risk_limits: MachineRulesRiskLimits


class CreateRulePackRequest(BaseModel):
    trade_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    machine_rules: MachineRules
    summary: str = ""
    changes: str = ""
    mode: str = "auto"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", summary="RulePack 생성")
async def create_rulepack(body: CreateRulePackRequest):
    """Create a new RulePack. Runs schema and risk-policy validation immediately."""
    logger.info("START: POST /api/v1/rulepack trade_date=%s", body.trade_date)
    try:
        rules_dict: dict[str, Any] = body.machine_rules.model_dump()
        validation = rulepack_validator.validate(rules_dict)

        record = rulepack_store.create_rulepack(
            trade_date=body.trade_date,
            machine_rules=rules_dict,
            summary=body.summary,
            changes=body.changes,
            mode=body.mode,
            validation=validation,
        )
        rulepack_store.update_rulepack_validation(record["rulepack_id"], validation)
        record["validation"] = validation

        logger.info("SUCCESS: POST /api/v1/rulepack rulepack_id=%s", record["rulepack_id"])
        return {"ok": True, "source": "backend", "live": True, "payload": record}
    except Exception as exc:
        logger.error("FAIL: POST /api/v1/rulepack - %s", exc)
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc), "source": "backend", "live": True})


@router.get("", summary="RulePack 목록 조회")
async def list_rulepacks(trade_date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
    """List RulePacks, optionally filtered by trade_date."""
    logger.info("START: GET /api/v1/rulepack trade_date=%s", trade_date)
    try:
        items = rulepack_store.list_rulepacks(trade_date=trade_date)
        logger.info("SUCCESS: GET /api/v1/rulepack count=%s", len(items))
        return {"ok": True, "source": "backend", "live": True, "payload": {"items": items, "total": len(items)}}
    except Exception as exc:
        logger.error("FAIL: GET /api/v1/rulepack - %s", exc)
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc), "source": "backend", "live": True})


@router.get("/{rulepack_id}", summary="RulePack 단건 조회")
async def get_rulepack(rulepack_id: str):
    """Return a single RulePack by ID."""
    logger.info("START: GET /api/v1/rulepack/%s", rulepack_id)
    record = rulepack_store.get_rulepack(rulepack_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"RulePack not found: {rulepack_id}")
    logger.info("SUCCESS: GET /api/v1/rulepack/%s", rulepack_id)
    return {"ok": True, "source": "backend", "live": True, "payload": record}


@router.put("/{rulepack_id}/activate", summary="RulePack 활성화")
async def activate_rulepack(rulepack_id: str):
    """Activate a RulePack for its trade_date. Fails if risk_policy validation failed."""
    logger.info("START: PUT /api/v1/rulepack/%s/activate", rulepack_id)
    try:
        record = rulepack_store.activate_rulepack(rulepack_id)
        logger.info("SUCCESS: PUT /api/v1/rulepack/%s/activate", rulepack_id)
        return {"ok": True, "source": "backend", "live": True, "payload": record}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("FAIL: PUT /api/v1/rulepack/%s/activate - %s", rulepack_id, exc)
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc), "source": "backend", "live": True})
