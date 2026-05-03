# OUTBOX_EXECUTOR_prompt_cleanup

## 작업 결과

완료.

### 변경 파일

- `backend/prompts/0800_gemini_news_summary.md`
- `backend/prompts/0805_opus_market_tone.md`
- `backend/prompts/0830_opus_screening.md`
- `backend/prompts/0845_gpt_rulepack_generation.md`
- `backend/prompts/1600_opus_review.md`
- `backend/prompts/1630_gpt_daily_report.md`
- `backend/prompts/2200_gemini_us_market_brief.md`
- `backend/services/engine/market_tone.py`
- `docs/agent-comm/OUTBOX_EXECUTOR_prompt_cleanup.md`

### 구현 내용

1. `backend/prompts/` 대상 프롬프트 7개 파일의 H1에서 `HH:MM` 시각 접두어를 제거했다.
   - 파일명 숫자 접두어는 변경하지 않았다.

2. `backend/prompts/2200_gemini_us_market_brief.md` 호출 정책을 수정했다.
   - 하루 1회 호출
   - 실패 시 LLM 라우터가 Groq/OpenAI 순서로 자동 폴백
   - 재시도 횟수는 시스템이 관리

3. `backend/services/engine/market_tone.py`의 `_TONE_PROMPT`에서 하드코딩 시각을 제거했다.
   - `분석 시각: 장 시작 전 (08:00 KST)`
   - `분석 시각: 장 시작 전`

4. `run_market_tone_analysis()`에 S11 overnight snapshot fallback을 추가했다.
   - 실시간 해외 시장 데이터 수집 실패 시 `us_market_watch.get_latest_snapshot()` 조회
   - snapshot `raw_data`가 dict이면 `market_data_fetcher.format_for_prompt()`로 프롬프트 입력 생성
   - 적용 시 S11 snapshot 기준 날짜/시각을 프롬프트에 추가
   - fallback 적용/실패 로그 추가
   - snapshot도 없으면 기존 기본 실패 문구 사용

## 검증 결과

### 1. Python 컴파일

명령:

```bash
python -m py_compile backend/services/engine/market_tone.py && echo "market_tone OK"
```

결과:

```text
market_tone OK
```

### 2. 프롬프트 H1 시각 제거 확인

명령:

```bash
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

결과:

```text
1630_gpt_daily_report.md: H1="# GPT — 일일 리포트 작성 (PM이 콘솔에서 확인)" time_removed=True
0830_opus_screening.md: H1="# Opus — 하이브리드 스크리닝 (정성 점수 부여)" time_removed=True
2200_gemini_us_market_brief.md: H1="# Gemini — 야간 미국장 관찰 브리핑" time_removed=True
0800_gemini_news_summary.md: H1="# Gemini — 장 시작 전 뉴스/공시 요약" time_removed=True
0805_opus_market_tone.md: H1="# Opus — 시장 톤 최종 판단" time_removed=True
1600_opus_review.md: H1="# Opus — 장마감 후 복기 리포트" time_removed=True
0845_gpt_rulepack_generation.md: H1="# GPT — RulePack JSON 생성 (가장 중요한 단계)" time_removed=True
```

## 주의 사항

- 작업 시작 시점에 이미 작업 트리에 다수의 변경 파일이 있었다.
- `backend/services/engine/market_tone.py`도 이미 수정 상태였으므로, 기존 변경을 되돌리지 않고 요청 범위의 라인만 부분 수정했다.
- Codex 역할 규칙에 따라 git commit은 수행하지 않았다.
