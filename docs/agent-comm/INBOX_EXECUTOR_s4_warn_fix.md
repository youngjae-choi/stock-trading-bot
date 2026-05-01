# INBOX_EXECUTOR_s4_warn_fix — S4 WARN 2건 수정

## 대상 파일
`backend/services/engine/hybrid_screening.py` 만 수정한다.

---

## 수정 1: `_build_prompt()` — str.format() → str.replace() 교체

### 문제
`_build_prompt()` 함수에서 프롬프트 템플릿에 `str.format()`을 사용하면
candidates JSON 내 중괄호(`{`, `}`)가 있을 때 KeyError 또는 의도치 않은 치환이 발생할 수 있다.

### 수정 방법
`_build_prompt()` 함수에서 프롬프트 템플릿 변수 치환 방식을
`str.format(candidates_json=..., market_tone_json=..., news_summary=...)` 대신
아래처럼 `str.replace()` 체인으로 교체한다:

```python
prompt = (
    _SCREENING_PROMPT_TEMPLATE
    .replace("{candidates_json}", candidates_json)
    .replace("{market_tone_json}", market_tone_json)
    .replace("{news_summary}", news_summary)
)
```

프롬프트 템플릿 상수(`_SCREENING_PROMPT_TEMPLATE`)의 플레이스홀더는
`{candidates_json}`, `{market_tone_json}`, `{news_summary}` 세 개만 있으면 된다.
LLM 출력 예시 JSON의 중괄호는 이스케이프 불필요 (replace()는 중괄호를 특별 처리하지 않음).

---

## 수정 2: `_parse_screening_response()` — 파싱 실패 로그에 raw 텍스트 포함

### 문제
`_parse_screening_response()` 내부에서 두 번째 JSON 파싱도 실패하면
`JSONDecodeError`가 상위 `run_hybrid_screening()`의 except 블록으로 전파되는데,
이때 로그에 raw 텍스트가 없어 운영 중 디버깅이 어렵다.

### 수정 방법
`run_hybrid_screening()`의 파싱 실패 except 블록에서 로그 호출을 아래처럼 수정:

현재:
```python
except Exception as parse_exc:
    logger.warning("WARN: HybridScreening JSON 파싱 실패 — %s", parse_exc)
```

수정 후:
```python
except Exception as parse_exc:
    logger.warning(
        "WARN: HybridScreening JSON 파싱 실패 — %s | raw_preview=%s",
        parse_exc,
        llm_result.get("raw", "")[:200],
    )
```

---

## 완료 기준

```bash
python -m py_compile backend/services/engine/hybrid_screening.py && echo "OK"
```

OUTBOX(`docs/agent-comm/OUTBOX_EXECUTOR_s4_warn_fix.md`)에 수정 내용 요약 작성.
