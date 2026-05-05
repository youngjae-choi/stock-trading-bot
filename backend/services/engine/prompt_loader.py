"""Prompt file loader used by active AI pipeline stages."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("PromptLoader")

_PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"
_COMMON_PROMPT = "_common_safety_guard.md"


def load_prompt_template(filename: str, *, include_common_guard: bool = True) -> str:
    """Load one markdown prompt template from backend/prompts.

    Args:
        filename: Prompt filename relative to backend/prompts.
        include_common_guard: Whether to prepend the shared safety guard.
    """
    logger.info("START: PromptLoader.load filename=%s", filename)
    prompt_path = (_PROMPT_DIR / filename).resolve()
    if _PROMPT_DIR not in prompt_path.parents:
        raise ValueError("prompt filename must stay inside backend/prompts")
    body = prompt_path.read_text(encoding="utf-8")
    if not include_common_guard:
        logger.info("SUCCESS: PromptLoader.load filename=%s common=false", filename)
        return body
    common = (_PROMPT_DIR / _COMMON_PROMPT).read_text(encoding="utf-8")
    logger.info("SUCCESS: PromptLoader.load filename=%s common=true", filename)
    return common + "\n\n" + body


def render_prompt(filename: str, variables: dict[str, Any], *, include_common_guard: bool = True) -> str:
    """Render a prompt by replacing explicit {name} placeholders only.

    Args:
        filename: Prompt filename relative to backend/prompts.
        variables: Placeholder values keyed by name without braces.
        include_common_guard: Whether to prepend the shared safety guard.
    """
    template = load_prompt_template(filename, include_common_guard=include_common_guard)
    rendered = template
    for key, value in variables.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered
