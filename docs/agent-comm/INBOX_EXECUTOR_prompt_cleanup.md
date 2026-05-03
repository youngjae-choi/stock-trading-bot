# INBOX_EXECUTOR_prompt_cleanup — 프롬프트 시간정의 제거 + S11→S2 연동

## 작업 목적

1. `backend/prompts/` 안 각 프롬프트 파일의 H1 헤더에서 시간 접두어를 제거한다.
   (파일명에 숫자 접두어는 순서 표시용이므로 그대로 유지한다.)
2. `market_tone.py` 프롬프트 본문에서 하드코딩된 시각("08:00 KST") 제거.
3. `market_tone.py`에 S11 overnight snapshot fallback 추가.

---

## Task 1 — 프롬프트 파일 H1 헤더에서 시각 제거

각 파일을 읽어 H1 (# ...) 에서 "HH:MM" 패턴과 모델명 앞의 시각 부분만 제거한다.
**파일 이름은 변경하지 않는다.**

| 파일 | 현재 H1 | 변경 후 H1 |
|------|---------|-----------|
| `backend/prompts/0800_gemini_news_summary.md` | `# 08:00 Gemini — 장 시작 전 뉴스/공시 요약` | `# Gemini — 장 시작 전 뉴스/공시 요약` |
| `backend/prompts/1600_opus_review.md` | `# 16:00 Opus — 장마감 후 복기 리포트` | `# Opus — 장마감 후 복기 리포트` |
| `backend/prompts/1630_gpt_daily_report.md` | `# 16:30 GPT — 일일 리포트 작성 (PM이 콘솔에서 확인)` | `# GPT — 일일 리포트 작성 (PM이 콘솔에서 확인)` |
| `backend/prompts/2200_gemini_us_market_brief.md` | `# 22:00 Gemini — 야간 미국장 관찰 브리핑` | `# Gemini — 야간 미국장 관찰 브리핑` |

`0805_opus_market_tone.md`, `0830_opus_screening.md`, `0845_gpt_rulepack_generation.md` 도 읽어서
H1에 시각 접두어가 있으면 동일하게 제거한다.

### 추가: `2200_gemini_us_market_brief.md` 호출 정책 섹션 수정

이 섹션:
```
## 호출 정책
- 하루 1회만 호출 (22:00)
- 실패 시 재시도 금지 (다음날 08:00 단계가 폴백 처리)
- 무료 quota 체크 후 호출 (시스템이 자동 관리)
```

아래로 변경:
```
## 호출 정책
- 하루 1회만 호출
- 실패 시 LLM 라우터가 Groq/OpenAI 순서로 자동 폴백
- 재시도 횟수는 시스템이 관리 (이 프롬프트에서 정의하지 않음)
```

---

## Task 2 — `market_tone.py` 프롬프트 본문 시각 제거

파일: `backend/services/engine/market_tone.py`

`_TONE_PROMPT` 안에 다음 줄이 있다:
```
분석 시각: 장 시작 전 (08:00 KST)
```
이것을 다음으로 변경:
```
분석 시각: 장 시작 전
```

---

## Task 3 — `market_tone.py` S11 overnight snapshot fallback 추가

파일: `backend/services/engine/market_tone.py`

현재 코드 (`run_market_tone_analysis` 함수 내):
```python
    try:
        from .market_data_fetcher import fetch_overnight_market_summary, format_for_prompt

        market_data = await fetch_overnight_market_summary()
        market_data_text = format_for_prompt(market_data)
    except Exception as exc:
        logger.warning("WARN: MarketToneService 해외 시장 데이터 수집 실패 — %s", exc)
        market_data_text = "[전날 밤 해외 시장 현황]\n  데이터 수집 실패 — 가용한 정보만 기준으로 판단"
```

변경 후:
```python
    try:
        from .market_data_fetcher import fetch_overnight_market_summary, format_for_prompt

        market_data = await fetch_overnight_market_summary()
        market_data_text = format_for_prompt(market_data)
    except Exception as exc:
        logger.warning("WARN: MarketToneService 해외 시장 데이터 실시간 수집 실패 — %s", exc)
        # S11 overnight snapshot fallback
        try:
            from .us_market_watch import get_latest_snapshot
            from .market_data_fetcher import format_for_prompt as _fmt
            snapshot = get_latest_snapshot()
            if snapshot and snapshot.get("raw_data") and isinstance(snapshot["raw_data"], dict):
                market_data_text = _fmt(snapshot["raw_data"])
                market_data_text += (
                    f"\n[참고: S11 스냅샷 기준 {snapshot['snapshot_date']} {snapshot['snapshot_time']} KST]"
                )
                logger.info(
                    "INFO: MarketToneService S11 스냅샷 폴백 적용 date=%s time=%s",
                    snapshot["snapshot_date"], snapshot["snapshot_time"],
                )
            else:
                market_data_text = "[전날 밤 해외 시장 현황]\n  데이터 수집 실패 — 가용한 정보만 기준으로 판단"
        except Exception as snap_exc:
            logger.warning("WARN: MarketToneService S11 스냅샷 폴백도 실패 — %s", snap_exc)
            market_data_text = "[전날 밤 해외 시장 현황]\n  데이터 수집 실패 — 가용한 정보만 기준으로 판단"
```

---

## 완료 기준

```bash
python -m py_compile backend/services/engine/market_tone.py && echo "market_tone OK"
python3 -c "
import re, os
for f in os.listdir('backend/prompts'):
    if not f.endswith('.md') or f.startswith('_') or f in ('README.md', 'DECISION_LOG.md'):
        continue
    content = open(f'backend/prompts/{f}').read()
    h1 = [l for l in content.split('\n') if l.startswith('# ')][0] if content else ''
    has_time = bool(re.match(r'# \d{2}:\d{2} ', h1))
    print(f'{f}: H1=\"{h1}\" time_removed={not has_time}')
"
```

기대 출력: 각 파일 H1에 `\d{2}:\d{2}` 패턴 없음 (`time_removed=True`).

---

OUTBOX 결과는 `docs/agent-comm/OUTBOX_EXECUTOR_prompt_cleanup.md` 에 작성하라.
