"""Pipeline Context Preview API — S3/S4/S5에 주입될 메모리 미리보기."""

from __future__ import annotations

import logging

from fastapi import APIRouter

from ...services.engine.expert_knowledge import get_active_knowledge
from ...services.engine.learning_memory import get_active_memories

logger = logging.getLogger("PipelineContextPreviewAPI")
router = APIRouter(prefix="/api/v1/pipeline", tags=["pipeline"])


@router.get("/S3/context-preview")
def s3_context_preview() -> dict:
    """Return active Learning Memory rows that S3 Universe Filter will consume."""
    logger.info("START: pipeline.s3_context_preview")
    memories = get_active_memories(scope="S3_UNIVERSE_FILTER")
    knowledge_items = get_active_knowledge(scope="S3_UNIVERSE_FILTER")
    logger.info(
        "SUCCESS: pipeline.s3_context_preview memories=%d knowledge=%d",
        len(memories),
        len(knowledge_items),
    )
    return {
        "ok": True,
        "payload": {
            "scope": "S3_UNIVERSE_FILTER",
            "memories": memories,
            "count": len(memories),
            "knowledge_items": knowledge_items,
            "knowledge_count": len(knowledge_items),
        },
    }


@router.get("/S4/context-preview")
def s4_context_preview() -> dict:
    """Return active Learning Memory rows that S4 Hybrid Screening will consume."""
    logger.info("START: pipeline.s4_context_preview")
    memories = get_active_memories(scope="S4_HYBRID_SCREENING")
    knowledge_items = get_active_knowledge(scope="S4_HYBRID_SCREENING")
    logger.info(
        "SUCCESS: pipeline.s4_context_preview memories=%d knowledge=%d",
        len(memories),
        len(knowledge_items),
    )
    return {
        "ok": True,
        "payload": {
            "scope": "S4_HYBRID_SCREENING",
            "memories": memories,
            "count": len(memories),
            "knowledge_items": knowledge_items,
            "knowledge_count": len(knowledge_items),
        },
    }


@router.get("/S5/context-preview")
def s5_context_preview() -> dict:
    """Return S5 Learning Memory rows plus a daily_overrides preview map."""
    logger.info("START: pipeline.s5_context_preview")
    memories = get_active_memories(scope="S5_DAILY_PLAN")
    knowledge_items = get_active_knowledge(scope="S5_DAILY_PLAN")
    overrides_preview = {}
    for memory in memories:
        rec = memory.get("recommendation", {})
        if rec.get("field"):
            overrides_preview[rec["field"]] = rec.get("value")
    logger.info(
        "SUCCESS: pipeline.s5_context_preview memories=%d knowledge=%d override_fields=%d",
        len(memories),
        len(knowledge_items),
        len(overrides_preview),
    )
    return {
        "ok": True,
        "payload": {
            "scope": "S5_DAILY_PLAN",
            "memories": memories,
            "count": len(memories),
            "knowledge_items": knowledge_items,
            "knowledge_count": len(knowledge_items),
            "overrides_preview": overrides_preview,
        },
    }
