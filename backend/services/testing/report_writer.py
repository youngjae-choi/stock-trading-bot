"""Write smoke-test execution artifacts as JSON and readable markdown report."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

REPORT_DIR = Path("logs/api_smoke")


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _build_markdown(report: Dict[str, Any]) -> str:
    summary = report.get("summary", {})
    rows = report.get("results", [])
    lines = [
        "# KIS API Smoke Test Report",
        "",
        f"- generated_at_utc: {report.get('generated_at_utc')}",
        f"- total: {summary.get('total', 0)}",
        f"- success: {summary.get('success', 0)}",
        f"- fail: {summary.get('fail', 0)}",
        f"- skip: {summary.get('skip', 0)}",
        "",
        "## Failure Type Counts",
        "",
    ]
    for key, value in sorted((summary.get("failure_type_counts") or {}).items()):
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Cases", "", "|id|market|domain|status|http|failure_type|reason|", "|---|---|---|---|---:|---|---|"])
    for row in rows:
        lines.append(
            "|{id}|{market}|{domain}|{status}|{http_status}|{failure_type}|{reason}|".format(
                id=row.get("id", ""),
                market=row.get("market", ""),
                domain=row.get("domain", ""),
                status=row.get("status", ""),
                http_status=row.get("http_status", ""),
                failure_type=row.get("failure_type", ""),
                reason=str(row.get("reason", "")).replace("|", "/"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def write_report(report: Dict[str, Any]) -> Dict[str, str]:
    """Persist smoke-test report to JSON and markdown files."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _now_stamp()
    json_path = REPORT_DIR / f"smoke_{stamp}.json"
    md_path = REPORT_DIR / f"smoke_{stamp}.md"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    md_path.write_text(_build_markdown(report), encoding="utf-8")

    return {"json_path": str(json_path), "report_path": str(md_path)}


def read_latest_report() -> Dict[str, Any]:
    """Return latest smoke report payload if exists."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(REPORT_DIR.glob("smoke_*.json"))
    if not files:
        return {"ok": False, "error": "no smoke report found"}
    latest = files[-1]
    payload = json.loads(latest.read_text(encoding="utf-8"))
    return {"ok": True, "path": str(latest), "payload": payload}
