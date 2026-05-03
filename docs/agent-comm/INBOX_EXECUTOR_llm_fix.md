# INBOX_EXECUTOR_llm_fix — LLM Router 수정 (Gemini 모델 + Anthropic 추가)

## 수정 대상 파일
- `backend/services/engine/llm_router.py`
- `backend/config.py`
- `.env.example`
- `requirements.txt`

---

## 1. `requirements.txt` — anthropic 패키지 추가

기존 `httpx==0.27.0` 줄 아래에 추가:
```
anthropic>=0.40.0
```

---

## 2. `backend/config.py` — ANTHROPIC_API_KEY 추가

기존:
```python
    # LLM API Keys (S2: 시장 톤 분석 — fallback 순서: Gemini → Groq → OpenAI)
    GEMINI_API_KEY: str = ""   # Google Gemini API key
    GROQ_API_KEY: str = ""     # Groq API key
    OPENAI_API_KEY: str = ""   # OpenAI GPT fallback key
```

수정 후:
```python
    # LLM API Keys (fallback 순서: Anthropic → Gemini → Groq → OpenAI)
    ANTHROPIC_API_KEY: str = ""  # Anthropic Claude API key (1순위)
    GEMINI_API_KEY: str = ""     # Google Gemini API key (2순위)
    GROQ_API_KEY: str = ""       # Groq API key (3순위)
    OPENAI_API_KEY: str = ""     # OpenAI GPT fallback key (4순위)
```

---

## 3. `.env.example` — ANTHROPIC_API_KEY 섹션 추가

파일 끝에 아래 내용 추가:
```
# LLM API Keys (자동매매 AI 분석용)
# fallback 순서: Anthropic → Gemini → Groq → OpenAI
# Anthropic Claude (S2 시장분석, S4 스크리닝, S5 RulePack 생성)
ANTHROPIC_API_KEY=

# Google Gemini
GEMINI_API_KEY=

# Groq (빠른 추론, 무료 티어)
GROQ_API_KEY=

# OpenAI (최후 fallback)
OPENAI_API_KEY=
```

---

## 4. `backend/services/engine/llm_router.py` — 전체 수정

### 변경 내용

#### A. 상수 변경
기존:
```python
_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
```
수정:
```python
_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
```

#### B. Anthropic 호출 함수 추가 (기존 `_call_gemini` 앞에 삽입)

```python
async def _call_anthropic(prompt: str, api_key: str) -> str:
    """Anthropic Claude API를 호출하고 응답 텍스트를 반환한다."""
    import anthropic as _anthropic
    client = _anthropic.AsyncAnthropic(api_key=api_key)
    message = await client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text
```

#### C. `_providers_in_order()` 함수 수정

기존:
```python
def _providers_in_order() -> list[dict[str, Any]]:
    candidates = [
        {"name": "gemini",  "key": settings.GEMINI_API_KEY},
        {"name": "groq",    "key": settings.GROQ_API_KEY},
        {"name": "openai",  "key": settings.OPENAI_API_KEY},
    ]
    return [p for p in candidates if p["key"]]
```

수정:
```python
def _providers_in_order() -> list[dict[str, Any]]:
    candidates = [
        {"name": "anthropic", "key": settings.ANTHROPIC_API_KEY},
        {"name": "gemini",    "key": settings.GEMINI_API_KEY},
        {"name": "groq",      "key": settings.GROQ_API_KEY},
        {"name": "openai",    "key": settings.OPENAI_API_KEY},
    ]
    return [p for p in candidates if p["key"]]
```

#### D. `_CALLERS` dict에 anthropic 추가

기존:
```python
_CALLERS = {
    "gemini": _call_gemini,
    "groq": _call_groq,
    "openai": _call_openai,
}
```

수정:
```python
_CALLERS = {
    "anthropic": _call_anthropic,
    "gemini": _call_gemini,
    "groq": _call_groq,
    "openai": _call_openai,
}
```

#### E. `provider_status()` 함수 수정

기존 `all_providers` 리스트에 anthropic 추가 (첫 번째):
```python
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
            "anthropic": "claude-opus-4-6",
            "gemini": "gemini-2.0-flash",
            "groq": _GROQ_MODEL,
            "openai": _OPENAI_MODEL,
        }[p["name"]],
    }
    for p in all_providers
]
```

---

## 완료 기준

```bash
pip install anthropic --quiet
python -m py_compile backend/services/engine/llm_router.py && echo "OK"
python -m py_compile backend/config.py && echo "OK"
python -c "from backend.services.engine.llm_router import provider_status; print(provider_status())"
```

OUTBOX(`docs/agent-comm/OUTBOX_EXECUTOR_llm_fix.md`)에 결과 작성.
