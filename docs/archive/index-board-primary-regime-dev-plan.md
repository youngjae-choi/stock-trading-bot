# index-board 주력 regime 소싱 (하이브리드) — 개발계획서 v0.1

## 원본 요구사항 (PM 발화 인용)
> 대체하려고 난 저 SITE를 사용하자고 한건데 즉, 기존 KIS 수집하던 정보는 풀백상황에만 반영하고 저 SITE에서 정보를 수집해서 레짐을 할당하는거지.
> (분류 방식·하이브리드 확인 후) 진행해

## 확정 설계 (하이브리드)
- **index-board 브리핑이 주력 regime 소스**. 우리 Opus 시황분석 호출을 **대체(제거)**.
- **KIS 숫자(VIX·KOSPI 등)는 유지** — match_regime_set 점수 계산에 필수, 개인 사이트 단일 의존 회피.
- 분류: **키워드 휴리스틱 우선**, 애매하면 **neutral**(보수적). 며칠 정확도 로그 평가 후 부정확하면 소형 LLM 보강.
- 스크랩 실패/비활성 → **폴백: 기존 KIS+Opus 풀분석**(현행 그대로).

## 데이터 흐름 (run_market_tone_analysis, is_intraday=False)
```
1. KIS 숫자 수집 (fetch_overnight_market_summary, 야간선물, 장개시 스냅샷) — 유지
2. index-board 장전 브리핑 스크랩
   ├─ 성공(briefing_scraped):
   │    parsed = classify_regime_heuristic(브리핑텍스트) → regime/tone/risk_level...
   │    llm_result = {ok:True, raw:브리핑텍스트, provider:"index-board"}
   │    ⛔ call_llm SKIP
   │    risk_level = KIS VIX 기반 파생
   └─ 실패: 기존 call_llm(Opus 풀분석) 경로
3. 이후 저장/결과 코드는 공통 재사용 (provider/raw가 분기에 따라 다름)
```

## 휴리스틱 분류 규칙 (classify_regime_heuristic)
반환: `{regime, tone, risk_level, confidence, summary, stock_character, rulepack_hint, key_factors, risk_factors}`
- 키워드 가중 카운트:
  - risk_on(↑): 위험선호, 강세, 회복, 반등, 상승 출발, 급등, 우호적, 갭상승
  - risk_off(↓): 위험회피, 약세, 하락, 급락, 부진, 경계, 위축, 불안
  - volatile: 변동성, 혼조, 불확실, 출렁, 급변, 엇갈
- 판정: net = on점수 − off점수. |net|이 임계 미만이거나 신호 빈약 → **neutral**(보수적). volatile 신호 강하면 volatile.
- regime→tone: risk_on→positive, risk_off→negative, volatile/neutral→neutral.
- risk_level: KIS VIX 기준 — VIX<20 low, 20~30 normal, >30 high(없으면 normal).
- summary = 브리핑 텍스트(원문), stock_character/rulepack_hint = "" (카드가 브리핑 원문 표시), key_factors=[].
- confidence = min(|net|/임계, 1.0) 정도.

## 변경 파일
| 파일 | 변경 | 이유 |
|------|------|------|
| `backend/services/engine/market_tone.py` | 수정 | 브리핑 성공 시 휴리스틱 parsed + call_llm SKIP 분기, 폴백 유지 |
| `backend/services/engine/index_board_scraper.py` 또는 market_tone | `classify_regime_heuristic()` 신규 | 텍스트→regime 휴리스틱 |
| `tests/unit/test_regime_heuristic.py` | 신규 | 분류 케이스 |
| `tests/unit/test_market_tone_index_board_primary.py` | 신규 | 브리핑 성공→LLM 미호출, 실패→LLM 폴백 |

## 요구사항 대조표
| 요구사항 | 반영 | 비고 |
|----------|------|------|
| index-board에서 정보 수집해 regime 할당 | ✓ | 휴리스틱 분류 |
| 기존 KIS 정보는 폴백에만 | △ 부분 | KIS **숫자**는 유지(점수계산 필수), KIS 기반 **Opus 분석**만 폴백으로 격하 — 안전상 권장(PM 합의) |
| Opus 분석 대체(비용절감) | ✓ | 정상일엔 Opus 호출 0 |
| 단일 장애점 회피 | ✓ | 스크랩 실패→KIS+Opus 폴백 |

## 완료 기준
- [ ] 휴리스틱 분류 단위테스트 통과(risk_on/off/volatile/neutral/애매→neutral)
- [ ] 브리핑 성공 시 call_llm 미호출(mock 검증), 실패 시 기존 LLM 폴백
- [ ] 전체 pytest 통과(현재 502 + 신규)
- [ ] morning_context.provider="index-board"로 저장, 화면 정상
- [ ] regime 판정 로그(휴리스틱 결과+브리핑) 남겨 정확도 평가 가능
