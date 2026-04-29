"""Automatic smoke-test runner for domestic/overseas KIS API surface."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx

from .classifier import classify_failure, summarize_by_type
from .inventory import build_coverage_matrix, get_api_inventory
from .report_writer import write_report


def _render_endpoint(template: str, path_params: Dict[str, Any]) -> str:
    endpoint = template
    for key, value in path_params.items():
        endpoint = endpoint.replace("{" + key + "}", str(value))
    return endpoint


def _is_ok_payload(payload: Any) -> bool:
    if isinstance(payload, dict) and payload.get("ok") is False:
        return False
    return True


def _requires_kis(item: Dict[str, Any]) -> bool:
    if "requires_kis" in item:
        return bool(item.get("requires_kis"))
    endpoint = str(item.get("endpoint", ""))
    if endpoint.startswith("/api/v1/kis/meta/stocks/search"):
        return False
    if endpoint.startswith("/api/v1/kis/meta/stock-filters"):
        return False
    return True


async def run_smoke_tests(
    *,
    base_url: str,
    include_schema_only: bool = True,
    timeout_seconds: float = 25.0,
) -> Dict[str, Any]:
    """Run smoke tests and persist JSON/markdown reports."""
    inventory = get_api_inventory()
    items = [item for item in inventory if include_schema_only or item.get("risk_level") != "schema_only"]

    health_payload: Dict[str, Any] = {}
    kis_configured = True
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        try:
            health_resp = await client.get(f"{base_url.rstrip('/')}/health")
            health_payload = health_resp.json() if health_resp.headers.get("content-type", "").startswith("application/json") else {}
            kis_configured = bool(health_payload.get("kis_configured", True))
        except Exception:
            kis_configured = False

    results: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        for item in items:
            method = str(item.get("method", "GET")).upper()
            endpoint = _render_endpoint(str(item.get("endpoint", "")), dict(item.get("path_params") or {}))
            params = dict(item.get("query_params") or {})
            body = dict(item.get("body") or {})
            expected_status = [int(code) for code in list(item.get("expected_status") or [])]

            started = time.time()
            if (not kis_configured) and _requires_kis(item):
                results.append(
                    {
                        "id": item.get("id"),
                        "market": item.get("market"),
                        "domain": item.get("domain"),
                        "status": "skip",
                        "http_status": 0,
                        "elapsed_ms": int((time.time() - started) * 1000),
                        "failure_type": "config_missing",
                        "reason": "KIS credentials missing",
                        "endpoint": endpoint,
                    }
                )
                continue

            try:
                if method == "GET":
                    response = await client.get(f"{base_url.rstrip('/')}{endpoint}", params=params)
                else:
                    response = await client.request(method, f"{base_url.rstrip('/')}{endpoint}", params=params, json=body)
                elapsed_ms = int((time.time() - started) * 1000)
                try:
                    payload: Any = response.json()
                except ValueError:
                    payload = {"raw_text": response.text}

                http_status = int(response.status_code)
                expected_match = bool(expected_status) and http_status in expected_status
                success = expected_match or (response.is_success and _is_ok_payload(payload))

                if success:
                    results.append(
                        {
                            "id": item.get("id"),
                            "market": item.get("market"),
                            "domain": item.get("domain"),
                            "status": "success",
                            "http_status": http_status,
                            "elapsed_ms": elapsed_ms,
                            "failure_type": "none",
                            "reason": "ok",
                            "endpoint": endpoint,
                        }
                    )
                    continue

                failure_type = classify_failure(http_status, payload)
                status = "skip" if failure_type == "market_hours" else "fail"
                reason = payload.get("error") if isinstance(payload, dict) and payload.get("error") else str(payload)
                results.append(
                    {
                        "id": item.get("id"),
                        "market": item.get("market"),
                        "domain": item.get("domain"),
                        "status": status,
                        "http_status": http_status,
                        "elapsed_ms": elapsed_ms,
                        "failure_type": failure_type,
                        "reason": str(reason)[:240],
                        "endpoint": endpoint,
                    }
                )
            except Exception as exc:
                elapsed_ms = int((time.time() - started) * 1000)
                results.append(
                    {
                        "id": item.get("id"),
                        "market": item.get("market"),
                        "domain": item.get("domain"),
                        "status": "fail",
                        "http_status": 0,
                        "elapsed_ms": elapsed_ms,
                        "failure_type": "network",
                        "reason": str(exc)[:240],
                        "endpoint": endpoint,
                    }
                )

    summary = {
        "total": len(results),
        "success": len([row for row in results if row.get("status") == "success"]),
        "fail": len([row for row in results if row.get("status") == "fail"]),
        "skip": len([row for row in results if row.get("status") == "skip"]),
        "failure_type_counts": summarize_by_type(results),
    }

    report = {
        "ok": summary["fail"] == 0,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "kis_configured": kis_configured,
        "summary": summary,
        "coverage": build_coverage_matrix(items),
        "results": results,
        "reference_document": "docs/reference/한국투자증권_오픈API_전체문서_20260412_030007.xlsx",
    }
    report["artifacts"] = write_report(report)
    return report
