"""Failure classification helpers for API smoke tests."""

from __future__ import annotations

from typing import Any, Dict


def payload_to_text(payload: Any) -> str:
    """Flatten payload into lowercase text for rough error pattern matching."""
    if isinstance(payload, dict):
        parts = []
        for key, value in payload.items():
            parts.append(str(key))
            parts.append(payload_to_text(value))
        return " ".join(parts).lower()
    if isinstance(payload, list):
        return " ".join(payload_to_text(item) for item in payload).lower()
    return str(payload).lower()


def classify_failure(status_code: int, payload: Any) -> str:
    """Classify common smoke-test failure reasons for reporting."""
    text = payload_to_text(payload)

    if status_code == 0:
        return "network"
    if status_code == 429 or any(token in text for token in ["rate", "too many", "초당", "호출 제한"]):
        return "rate_limit"
    if status_code in {401, 403} or any(token in text for token in ["unauthorized", "forbidden", "권한", "인증", "access denied"]):
        return "permission"
    if any(token in text for token in ["장종료", "장 마감", "시간외", "휴장", "market closed", "outside trading hours"]):
        return "market_hours"
    if status_code in {400, 422}:
        return "validation"
    if status_code >= 500:
        return "upstream_or_server"
    return "other"


def summarize_by_type(rows: list[Dict[str, Any]]) -> Dict[str, int]:
    """Build count map by failure type."""
    out: Dict[str, int] = {}
    for row in rows:
        key = str(row.get("failure_type") or "none")
        out[key] = out.get(key, 0) + 1
    return out
