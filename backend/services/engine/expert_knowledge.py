"""Expert Knowledge Base — 운영자 정성 지식 관리 및 S3/S4/S5 주입."""

from __future__ import annotations

import logging
import json
import uuid
from datetime import date, datetime, timezone
from typing import Any

from ..db import get_connection
from . import llm_router

logger = logging.getLogger("ExpertKnowledge")

_VALID_SCOPES = {"S3_UNIVERSE_FILTER", "S4_HYBRID_SCREENING", "S5_DAILY_PLAN", "ALL"}
_VALID_CATEGORIES = {"timing", "sector", "profile", "risk", "general"}
_VALID_STATUSES = {"pending", "approved", "rejected", "dev_required"}

_PM_APPROVAL_SETTING_KEYS = {
    "risk.daily_loss_limit_percent",
    "risk.max_positions",
    "risk.max_position_rate_per_stock",
    "risk.force_exit_time",
    "risk.new_entry_cutoff_time",
}

_PM_APPROVAL_REASON = "매수/청산/손실한도/포지션에 영향을 주는 값은 PM 승인 후 별도 반영해야 합니다"

MAPPABLE_SETTINGS = {
    "engine.min_confidence_floor": ("AI 신뢰도 하한선", "number"),
    "engine.min_ai_confidence": ("AI 신뢰도 기본값", "number"),
    "engine.min_price_change_pct": ("최소 등락률 %", "number"),
    "engine.max_price_change_pct": ("최대 등락률 %", "number"),
    "risk.daily_loss_limit_percent": ("일일 손실한도 %", "number"),
    "risk.max_positions": ("최대 동시 보유 종목 수", "number"),
    "risk.max_position_rate_per_stock": ("종목당 최대 비중", "number"),
    "risk.force_exit_time": ("강제청산 시간 (HH:MM)", "string"),
    "risk.new_entry_cutoff_time": ("신규 매수 금지 시간 (HH:MM)", "string"),
}

_STRATEGY_ANALYSIS_PROMPT = """
당신은 주식 자동매매 시스템의 매매전략 파싱 전문가입니다.
아래 매핑 가능한 Settings 키 목록을 참고해서 PDF 문서에서 전략 항목을 추출해주세요.

매핑 가능한 키 목록:
{mappable_settings_json}

규칙:
1. PDF 내용에서 수치 기반 매매 조건을 찾는다
2. 매핑 가능한 키와 대응되면 setting_key에 해당 키를 넣는다
3. 매핑 불가능한 내용은 unmappable 배열에 넣는다
4. value는 항상 문자열로 반환한다
5. 반드시 JSON만 반환하고 다른 텍스트는 절대 포함하지 않는다

출력 형식:
{{
  "strategy_candidates": [
    {{
      "label": "AI 신뢰도 최소값",
      "value": "0.65",
      "setting_key": "engine.min_confidence_floor",
      "value_type": "number",
      "reason": "문서 3페이지: '60% 이상의 신뢰도' 언급"
    }}
  ],
  "unmappable": [
    {{
      "label": "뉴스 기반 감성 필터",
      "description": "현재 Settings에 해당 키 없음",
      "raw_text": "..."
    }}
  ],
  "summary": "전략 핵심 요약"
}}

PDF 텍스트:
{text}
"""


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


def _parse_llm_json(raw: str) -> dict[str, Any]:
    """Parse a JSON-only LLM response while tolerating accidental code fences."""
    text = str(raw or "").strip()
    if "```" in text:
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start == -1 or end <= start:
            raise
        return json.loads(text[start:end])


def classify_strategy_candidate(setting_key: str) -> dict[str, str | bool]:
    """Classify whether a mapped strategy candidate is safe to auto-apply to Settings.

    Args:
        setting_key: Settings key extracted from the PDF strategy analysis.
    """
    clean_key = str(setting_key or "").strip()
    if clean_key not in MAPPABLE_SETTINGS:
        return {
            "setting_key": clean_key,
            "safety_status": "dev_required",
            "auto_applicable": False,
            "approval_required": False,
            "safety_reason": "현재 Settings에 매핑 가능한 키가 없어 개발필요로 저장합니다",
        }
    if clean_key in _PM_APPROVAL_SETTING_KEYS:
        return {
            "setting_key": clean_key,
            "safety_status": "pm_approval_required",
            "auto_applicable": False,
            "approval_required": True,
            "safety_reason": _PM_APPROVAL_REASON,
        }
    return {
        "setting_key": clean_key,
        "safety_status": "safe_auto_apply",
        "auto_applicable": True,
        "approval_required": False,
        "safety_reason": "낮은 위험의 Settings 값으로 자동 적용 가능합니다",
    }


def _normalize_strategy_analysis(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize LLM strategy analysis into the API contract and enforce setting allowlist."""
    candidates: list[dict[str, Any]] = []
    unmappable: list[dict[str, str]] = []
    for raw_candidate in data.get("strategy_candidates", []) or []:
        if not isinstance(raw_candidate, dict):
            continue
        setting_key = str(raw_candidate.get("setting_key") or "").strip()
        value = str(raw_candidate.get("value") or "").strip()
        mapped = MAPPABLE_SETTINGS.get(setting_key)
        safety = classify_strategy_candidate(setting_key)
        label = str(raw_candidate.get("label") or (mapped[0] if mapped else ""))
        reason = str(raw_candidate.get("reason") or "")
        candidates.append(
            {
                "label": label,
                "value": value,
                "setting_key": setting_key if mapped else "",
                "value_type": mapped[1] if mapped else str(raw_candidate.get("value_type") or "string"),
                "reason": reason,
                "safety_status": safety["safety_status"],
                "auto_applicable": safety["auto_applicable"],
                "approval_required": safety["approval_required"],
                "safety_reason": safety["safety_reason"],
            }
        )
        if not mapped:
            unmappable.append(
                {
                    "label": label or "미매핑 전략 항목",
                    "description": reason or "현재 Settings에 해당 키 없음",
                    "raw_text": value,
                    "status": "dev_required",
                    "operator_status_label": "개발필요",
                }
            )

    for raw_item in data.get("unmappable", []) or []:
        if not isinstance(raw_item, dict):
            continue
        unmappable.append(
            {
                "label": str(raw_item.get("label") or ""),
                "description": str(raw_item.get("description") or "현재 Settings에 해당 키 없음"),
                "raw_text": str(raw_item.get("raw_text") or ""),
                "status": "dev_required",
                "operator_status_label": "개발필요",
            }
        )

    return {
        "strategy_candidates": candidates,
        "unmappable": unmappable,
        "summary": str(data.get("summary") or "")[:1000],
    }


def extract_pdf_text(file_bytes: bytes) -> str:
    """PDF bytes에서 전체 텍스트를 추출한다.

    Args:
        file_bytes: 업로드된 PDF 파일의 원본 bytes.
    """
    import io

    logger.info("START: ExpertKnowledge.extract_pdf_text size=%d", len(file_bytes or b""))
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        logger.error("FAIL: ExpertKnowledge.extract_pdf_text missing_pypdf")
        raise RuntimeError("pypdf 라이브러리가 없습니다. pip install pypdf") from exc

    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        pages = []
        for page in reader.pages:
            text = page.extract_text() or ""
            pages.append(text)
    except Exception as exc:
        logger.error("FAIL: ExpertKnowledge.extract_pdf_text reason=%s", exc)
        raise ValueError("PDF 텍스트 추출에 실패했습니다") from exc

    extracted = "\n".join(pages).strip()
    logger.info("SUCCESS: ExpertKnowledge.extract_pdf_text chars=%d pages=%d", len(extracted), len(pages))
    return extracted


async def analyze_strategy_with_llm(text: str) -> dict[str, Any]:
    """PDF 텍스트를 LLM에 보내 전략 후보 목록을 JSON으로 반환한다.

    Args:
        text: PDF에서 추출한 전체 텍스트.
    """
    logger.info("START: ExpertKnowledge.analyze_strategy_with_llm chars=%d", len(text or ""))
    clean_text = str(text or "").strip()
    if not clean_text:
        logger.warning("WARN: ExpertKnowledge.analyze_strategy_with_llm empty_text")
        return {
            "strategy_candidates": [],
            "unmappable": [],
            "summary": "",
            "error": "empty_pdf_text",
        }

    prompt = _STRATEGY_ANALYSIS_PROMPT.format(
        mappable_settings_json=json.dumps(MAPPABLE_SETTINGS, ensure_ascii=False),
        text=clean_text[:60000],
    )
    llm_result = await llm_router.call_llm(prompt, task_name="Expert Knowledge PDF strategy analysis")
    if not llm_result.get("ok"):
        logger.warning(
            "WARN: ExpertKnowledge.analyze_strategy_with_llm provider=none error=%s",
            llm_result.get("error", "unknown"),
        )
        return {
            "strategy_candidates": [],
            "unmappable": [],
            "summary": "",
            "error": llm_result.get("error", "no_provider_configured"),
            "provider": "none",
        }

    try:
        parsed = _parse_llm_json(llm_result.get("raw", ""))
        normalized = _normalize_strategy_analysis(parsed)
    except Exception as exc:
        logger.error("FAIL: ExpertKnowledge.analyze_strategy_with_llm parse reason=%s", exc)
        return {
            "strategy_candidates": [],
            "unmappable": [],
            "summary": "",
            "error": "llm_json_parse_failed",
            "provider": llm_result.get("provider", "none"),
        }

    normalized["provider"] = llm_result.get("provider", "none")
    logger.info(
        "SUCCESS: ExpertKnowledge.analyze_strategy_with_llm provider=%s candidates=%d unmappable=%d",
        normalized["provider"],
        len(normalized["strategy_candidates"]),
        len(normalized["unmappable"]),
    )
    return normalized


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
    status: str = "pending",
) -> dict[str, Any]:
    """Create an Expert Knowledge item with a validated operator workflow status.

    Args:
        title: Short operator-facing title.
        content: Strategy knowledge text that may be injected into prompts after approval.
        scope: Target pipeline scope or ALL.
        category: Knowledge category such as timing, sector, profile, risk, or general.
        priority: Injection order where 1 is highest priority and 10 is lowest.
        auto_inject: Whether this item should be marked for automatic injection after approval.
        expires_at: Optional ISO date or datetime after which the item is inactive.
        status: Operator workflow status, including dev_required for unmappable strategy gaps.
    """
    logger.info("START: ExpertKnowledge.create scope=%s category=%s status=%s", scope, category, status)
    clean_title = str(title or "").strip()
    clean_content = str(content or "").strip()
    if not clean_title or not clean_content:
        raise ValueError("title and content are required")
    clean_scope = _validate_scope(scope)
    clean_category = _validate_category(category)
    clean_status = str(status or "pending").strip()
    if clean_status not in _VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")
    clean_priority = max(1, min(10, int(priority)))
    item = {
        "id": str(uuid.uuid4()),
        "source_id": None,
        "title": clean_title,
        "content": clean_content,
        "scope": clean_scope,
        "category": clean_category,
        "status": clean_status,
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
    logger.info("SUCCESS: ExpertKnowledge.create item_id=%s status=%s", item["id"], clean_status)
    return item


def persist_unmappable_strategy_items(
    unmappable: list[dict[str, Any]],
    filename: str,
    analysis_id: str,
) -> list[dict[str, Any]]:
    """Persist unmappable PDF strategy items as operator-visible dev_required Knowledge rows.

    Args:
        unmappable: Normalized strategy items without current Settings mappings.
        filename: Uploaded PDF filename used for operator traceability.
        analysis_id: pdf_analyses.analysis_id that produced the items.
    """
    logger.info(
        "START: ExpertKnowledge.persist_unmappable analysis_id=%s count=%d",
        analysis_id,
        len(unmappable or []),
    )
    created: list[dict[str, Any]] = []
    for item in unmappable or []:
        if not isinstance(item, dict):
            logger.warning("WARN: ExpertKnowledge.persist_unmappable skipped_non_dict analysis_id=%s", analysis_id)
            continue
        label = str(item.get("label") or "미매핑 전략 항목").strip()
        description = str(item.get("description") or "현재 Settings에 해당 키 없음").strip()
        raw_text = str(item.get("raw_text") or "").strip()
        content = (
            f"PDF 전략 문서 '{filename}'에서 Settings 개발이 필요한 항목입니다.\n"
            f"분석 ID: {analysis_id}\n"
            f"설명: {description}\n"
            f"원문: {raw_text or '-'}"
        )
        created.append(
            create_knowledge_item(
                title=f"[개발필요] {label}",
                content=content,
                scope="ALL",
                category="general",
                priority=5,
                auto_inject=False,
                status="dev_required",
            )
        )
    logger.info(
        "SUCCESS: ExpertKnowledge.persist_unmappable analysis_id=%s created=%d",
        analysis_id,
        len(created),
    )
    return created


def list_knowledge_items(scope: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    """List Expert Knowledge items with optional scope and status filters.

    Args:
        scope: Optional target scope filter.
        status: Optional pending, approved, rejected, or dev_required filter.
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


def get_knowledge_item(item_id: str) -> dict[str, Any] | None:
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


def approve_knowledge(item_id: str, reason: str = "") -> dict[str, Any]:
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


def reject_knowledge(item_id: str, reason: str = "") -> dict[str, Any]:
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


def get_active_knowledge(scope: str) -> list[dict[str, Any]]:
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


def build_knowledge_prompt_snippet(knowledge_items: list[dict[str, Any]]) -> str:
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
