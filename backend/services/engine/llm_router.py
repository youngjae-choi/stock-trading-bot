"""LLM 라우터 — Anthropic → Gemini → Groq → OpenAI GPT 순서로 fallback 호출.

S2 시장 톤 분석, S8 중간 리포트, S10 복기 리포트, S13 야간 관찰 등에서 공통으로 사용한다.
각 provider는 API 키가 설정된 경우에만 활성화된다.
모든 provider가 실패하면 {ok: False} 결과를 반환하며 예외는 발생시키지 않는다.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ...config import settings

logger = logging.getLogger("LLMRouter")

# ---------------------------------------------------------------------------
# Provider 정의
# ---------------------------------------------------------------------------

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_ANTHROPIC_MODEL = "claude-opus-4-6"
_GROQ_MODEL = "llama-3.1-8b-instant"
_OPENAI_MODEL = "gpt-4o-mini"
_TIMEOUT = 30.0


def _providers_in_order() -> list[dict[str, Any]]:
    """활성화된 provider를 우선순위 순서대로 반환한다."""
    candidates = [
        {"name": "anthropic", "key": settings.ANTHROPIC_API_KEY},
        {"name": "gemini",    "key": settings.GEMINI_API_KEY},
        {"name": "groq",      "key": settings.GROQ_API_KEY},
        {"name": "openai",    "key": settings.OPENAI_API_KEY},
    ]
    return [p for p in candidates if p["key"]]


# ---------------------------------------------------------------------------
# Provider별 호출 함수
# ---------------------------------------------------------------------------

async def _call_anthropic(prompt: str, api_key: str) -> str:
    """Anthropic Claude API를 호출하고 응답 텍스트를 반환한다."""
    import anthropic as _anthropic

    client = _anthropic.AsyncAnthropic(api_key=api_key)
    message = await client.messages.create(
        model=_ANTHROPIC_MODEL,
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


async def _call_gemini(prompt: str, api_key: str) -> str:
    """Gemini REST API를 호출하고 응답 텍스트를 반환한다."""
    url = f"{_GEMINI_URL}?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024},
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(url, json=payload)
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


async def _call_groq(prompt: str, api_key: str) -> str:
    """Groq REST API(OpenAI 호환)를 호출하고 응답 텍스트를 반환한다."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": _GROQ_MODEL,
        "messages": [
            {"role": "system", "content": "너는 자동매매 시스템의 금융 분석 보조 AI다. 결과는 반드시 JSON으로 작성한다."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(_GROQ_URL, headers=headers, json=payload)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


async def _call_openai(prompt: str, api_key: str) -> str:
    """OpenAI REST API를 호출하고 응답 텍스트를 반환한다."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": _OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": "너는 자동매매 시스템의 금융 분석 보조 AI다. 결과는 반드시 JSON으로 작성한다."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(_OPENAI_URL, headers=headers, json=payload)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


_CALLERS = {
    "anthropic": _call_anthropic,
    "gemini": _call_gemini,
    "groq": _call_groq,
    "openai": _call_openai,
}


# ---------------------------------------------------------------------------
# 공개 인터페이스
# ---------------------------------------------------------------------------

async def call_llm(prompt: str, task_name: str = "") -> dict[str, Any]:
    """LLM을 Anthropic → Gemini → Groq → OpenAI 순서로 fallback 호출한다.

    Args:
        prompt: LLM에 전달할 전체 프롬프트 문자열.
        task_name: 로그 식별용 태스크 이름 (예: "시장 톤 분석").

    Returns:
        {
            "ok": bool,
            "provider": str,          # 성공한 provider 이름 또는 "none"
            "raw": str,               # LLM 원문 응답
            "tried": list[str],       # 시도한 provider 목록
        }
    """
    logger.info("START: LLMRouter.call_llm task=%s", task_name or "unnamed")
    providers = _providers_in_order()

    if not providers:
        logger.warning("WARN: LLMRouter — API 키가 설정된 provider 없음 (.env 확인)")
        return {"ok": False, "provider": "none", "raw": "", "tried": [], "error": "no_provider_configured"}

    tried: list[str] = []
    for p in providers:
        name = p["name"]
        tried.append(name)
        try:
            logger.info("TRY: LLMRouter provider=%s task=%s", name, task_name or "unnamed")
            caller = _CALLERS[name]
            raw = await caller(prompt, p["key"])
            logger.info("SUCCESS: LLMRouter provider=%s task=%s", name, task_name or "unnamed")
            return {"ok": True, "provider": name, "raw": raw, "tried": tried}
        except Exception as exc:
            logger.warning("WARN: LLMRouter provider=%s failed — %s", name, exc)

    logger.error("FAIL: LLMRouter 모든 provider 실패 tried=%s task=%s", tried, task_name or "unnamed")
    return {"ok": False, "provider": "none", "raw": "", "tried": tried, "error": "all_providers_failed"}


def provider_status() -> list[dict[str, Any]]:
    """현재 설정된 provider 목록과 활성화 여부를 반환한다 (API 키 노출 없음)."""
    all_providers = [
        {"name": "anthropic", "key": settings.ANTHROPIC_API_KEY, "role": "primary_claude"},
        {"name": "gemini",    "key": settings.GEMINI_API_KEY,    "role": "long_summary"},
        {"name": "groq",      "key": settings.GROQ_API_KEY,      "role": "fast_classify"},
        {"name": "openai",    "key": settings.OPENAI_API_KEY,    "role": "fallback_gpt"},
    ]
    return [
        {
            "name": p["name"],
            "role": p["role"],
            "enabled": bool(p["key"]),
            "model": {
                "anthropic": _ANTHROPIC_MODEL,
                "gemini": "gemini-2.0-flash",
                "groq": _GROQ_MODEL,
                "openai": _OPENAI_MODEL,
            }[p["name"]],
        }
        for p in all_providers
    ]
