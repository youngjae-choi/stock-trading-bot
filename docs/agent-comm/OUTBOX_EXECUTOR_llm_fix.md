# OUTBOX_EXECUTOR_llm_fix — LLM Router 수정 결과

## 작업 요약

- `requirements.txt`
  - `httpx==0.27.0` 아래에 `anthropic>=0.40.0` 추가.
- `backend/config.py`
  - `ANTHROPIC_API_KEY` 설정 추가.
  - LLM fallback 주석을 `Anthropic → Gemini → Groq → OpenAI` 순서로 갱신.
- `.env.example`
  - LLM API Key 예시 섹션 추가.
  - `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENAI_API_KEY` 예시 추가.
- `backend/services/engine/llm_router.py`
  - Gemini endpoint 모델을 `gemini-2.0-flash`로 변경.
  - Anthropic Claude 호출 함수 `_call_anthropic()` 추가.
  - provider 우선순위를 `anthropic → gemini → groq → openai`로 변경.
  - `_CALLERS`와 `provider_status()`에 Anthropic 추가.

## 검증 결과

```bash
python -m py_compile backend/services/engine/llm_router.py && echo OK_LLM_ROUTER
# OK_LLM_ROUTER
```

```bash
python -m py_compile backend/config.py && echo OK_CONFIG
# OK_CONFIG
```

```bash
python -c "from backend.services.engine.llm_router import provider_status; print(provider_status())"
# [{'name': 'anthropic', 'role': 'primary_claude', 'enabled': False, 'model': 'claude-opus-4-6'}, {'name': 'gemini', 'role': 'long_summary', 'enabled': True, 'model': 'gemini-2.0-flash'}, {'name': 'groq', 'role': 'fast_classify', 'enabled': True, 'model': 'llama-3.1-8b-instant'}, {'name': 'openai', 'role': 'fallback_gpt', 'enabled': True, 'model': 'gpt-4o-mini'}]
```

```bash
python - <<'PY'
import asyncio
from backend.config import settings
from backend.services.engine.llm_router import _providers_in_order, call_llm

settings.ANTHROPIC_API_KEY = "test_anthropic"
settings.GEMINI_API_KEY = "test_gemini"
settings.GROQ_API_KEY = "test_groq"
settings.OPENAI_API_KEY = "test_openai"
print([p["name"] for p in _providers_in_order()])

settings.ANTHROPIC_API_KEY = ""
settings.GEMINI_API_KEY = ""
settings.GROQ_API_KEY = ""
settings.OPENAI_API_KEY = ""
print(asyncio.run(call_llm("ping", task_name="no-provider-smoke")))
PY
# ['anthropic', 'gemini', 'groq', 'openai']
# {'ok': False, 'provider': 'none', 'raw': '', 'tried': [], 'error': 'no_provider_configured'}
```

## 설치 확인

```bash
pip install anthropic --quiet
```

결과: 실패.

원인:
- 현재 실행 환경에서 PyPI DNS 조회가 실패했다.
- 오류: `Failed to establish a new connection: [Errno -2] Name or service not known`

조치:
- `requirements.txt`에는 의존성을 반영했다.
- 네트워크 가능한 환경에서 `pip install -r requirements.txt` 또는 `pip install anthropic` 재실행 필요.

## 확인 필요 / 리스크

- Anthropic Messages API 호출 형태는 공식 문서의 Python SDK 사용 방식과 일치한다.
- `claude-opus-4-6` 모델명은 INBOX 지시값대로 반영했다. 다만 공식 Anthropic 문서 검색 결과에서는 해당 모델명을 확인하지 못했다. 실제 API 호출 전 모델명 유효성 확인이 필요하다.
- 실제 Anthropic API 호출은 `ANTHROPIC_API_KEY`와 설치된 `anthropic` 패키지가 없어 수행하지 못했다.

