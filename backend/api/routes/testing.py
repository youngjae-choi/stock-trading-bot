"""API inventory and smoke-test routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ...config import validate_config
from ...services.testing.domestic_filter_console import (
    get_domestic_filter_console_catalog,
    run_domestic_filter_console,
)
from ...services.testing.inventory import build_coverage_matrix, get_api_inventory
from ...services.testing.report_writer import read_latest_report
from ...services.testing.smoke_runner import run_smoke_tests
from ..dependencies import kis_config_error_response
from ..models import DomesticFilterConsoleRequest, SmokeRunRequest

logger = logging.getLogger("BackendTestingAPI")
router = APIRouter(prefix="/api/v1/kis/testing", tags=["kis-testing"])


@router.get("/inventory")
async def get_inventory():
    items = get_api_inventory()
    return {
        "ok": True,
        "count": len(items),
        "items": items,
        "coverage": build_coverage_matrix(items),
        "reference_document": "docs/reference/한국투자증권_오픈API_전체문서_20260412_030007.xlsx",
    }


@router.post("/smoke/run")
async def run_smoke(payload: SmokeRunRequest):
    try:
        logger.info("START: /api/v1/kis/testing/smoke/run")
        report = await run_smoke_tests(
            base_url=payload.base_url,
            include_schema_only=payload.include_schema_only,
            timeout_seconds=payload.timeout_seconds,
        )
        logger.info(
            "SUCCESS: /api/v1/kis/testing/smoke/run total=%s success=%s fail=%s skip=%s",
            report["summary"]["total"],
            report["summary"]["success"],
            report["summary"]["fail"],
            report["summary"]["skip"],
        )
        return report
    except Exception as exc:
        logger.error("FAIL: /api/v1/kis/testing/smoke/run - %s", str(exc))
        return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})


@router.get("/smoke/latest")
async def get_latest_smoke_report():
    report = read_latest_report()
    if not report.get("ok"):
        return JSONResponse(status_code=404, content=report)
    return report


@router.get("/domestic-filter/catalog")
async def get_domestic_filter_catalog():
    return get_domestic_filter_console_catalog()


@router.post("/domestic-filter/run")
async def run_domestic_filter(payload: DomesticFilterConsoleRequest):
    if not validate_config():
        return kis_config_error_response("/api/v1/kis/testing/domestic-filter/run")
    try:
        logger.info("START: /api/v1/kis/testing/domestic-filter/run")
        result = await run_domestic_filter_console(payload.model_dump())
        logger.info(
            "SUCCESS: /api/v1/kis/testing/domestic-filter/run candidate=%s filtered=%s result=%s",
            result.get("candidate_count", 0),
            result.get("filtered_count", 0),
            result.get("count", 0),
        )
        return result
    except Exception as exc:
        logger.error("FAIL: /api/v1/kis/testing/domestic-filter/run - %s", str(exc))
        return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})
