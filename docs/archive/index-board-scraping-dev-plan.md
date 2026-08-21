# index-board.space 시황 스크래핑 통합 — 개발계획서 v0.1

## 원본 요구사항 (PM 발화 그대로 인용)

> 여기 화면들 스크리핑한다면 지금 API로 데이터를 수집하는것보다 더 빠르고 자세하게 수집도 가능하고 더 정확한 시황분석도 가능하지 않을까? 또 장 마감 시황도 제공해서 전일 장마감분석과 아침 시황분석을 비교하면서 전략을 짠다면 의미가 있을까?
>
> 비용도 줄이고 더 자세한 내용도 제공하는데 안할이유가 있나??
>
> 스크래핑 수집기 (morning 8:30 / evening 00:00 두 잡) => 이렇게 하자
>
> (장후 브리핑 regime 반영 여부) => 어떻게 하는게 좋겠어?
> (Playwright) => 이미 설치되어있어
>
> 구현 범위 => Phase 1+2 한번에

## 의사결정 요약 (PM 확정)

| 결정 항목 | 결정 내용 |
|-----------|-----------|
| 데이터 소스 | index-board.space 스크래핑(Playwright) + KIS 폴백 병행 |
| 아침 수집 | 08:30 (기존 `job_premarket_market_tone`에 통합) |
| 장후 수집 | 00:00 (신규 잡) |
| 장후 브리핑 역할 | regime 1차 결정 입력 아님 → **신뢰도 보정 + 복기 baseline** |
| 범위 | Phase 1(수집·저장·화면) + Phase 2(신뢰도 보정) 동시 |

## 왜 필요한가 (WHY)

- **비용 절감**: 현재 `run_market_tone_analysis()`는 원천 시장 데이터를 LLM에 넣어 분석시킨다. index-board는 이미 "뉴스 200개→40개 선별+AI 요약"을 끝낸 브리핑을 제공하므로, LLM에는 정제된 브리핑+스냅샷만 넣어 regime을 분류시키면 된다 → 프롬프트 토큰 대폭 감소.
- **데이터 풍부화**: VIX, 공포탐욕지수, 나스닥/S&P500/WTI 등 현재 KIS로 수집 어려운 글로벌 선행지표를 한 번에 확보.
- **전략 신뢰도**: 전날 밤 장후 브리핑 vs 당일 아침 regime을 비교해, 밤사이 심리가 일치하면 확신↑, 뒤집혔으면 불확실↑로 판단. 현재 시스템에 없는 새 차원.

## ⚠️ 정찰 결과 — Playwright 불필요 (2026-06-13 확인)

실제 사이트 분석 결과 **Chromium/Playwright가 필요 없음**:
- index-board.space는 Next.js SSR → 브리핑 텍스트가 초기 HTML에 박혀 있음 (`curl`로 전부 수집됨, ~49KB)
- 브리핑은 escaped JSON 객체로 임베드:
  `{"text":"간밤 미국 증시...","type":"pre","market":"kospi","generatedAt":"2026-06-12T17:23..."}`
  `{"text":"...","type":"post","market":"nasdaq","generatedAt":"2026-06-12T21:47:52..."}`
- **수집 방식 = `httpx` GET + RSC JSON 정규식 파싱** (브라우저·150MB Chromium 불필요)
- 아침 = `type=pre, market=kospi` / 장후 = `type=post, market=nasdaq`, 각 `generatedAt` 최신 1건 선택
- MARKET SNAPSHOT 수치 테이블은 클라이언트 렌더(실시간 API) → curl에 안 옴. **단 브리핑 텍스트 자체에 핵심 수치가 산문으로 포함**("나스닥100 선물 +0.70%", "VIX 급락 -5.20%", "코스피200 +3.07%", "원/달러 1,517원대") → LLM이 텍스트에서 regime+수치 추출, 별도 스냅샷 불필요.

→ **이득**: 서버에 Chromium 미설치, httpx만으로 빠르고 견고. `briefing.scrape_timeout_sec`는 httpx 타임아웃으로 유지.

## 아키텍처 / 데이터 흐름

```
[08:30] job_premarket_market_tone
   └─ run_market_tone_analysis(is_intraday=False)
        ├─ (신규) index_board_scraper.scrape_morning() → snapshot + 장전 브리핑(최신 1건)
        ├─ 성공 → 정제 데이터를 LLM 프롬프트로 → regime 분류 → morning_context 저장
        └─ 실패 → (기존) fetch_overnight_market_summary + KIS 스냅샷 경로로 폴백

[00:00] job_evening_briefing (신규)
   └─ index_board_scraper.scrape_evening() → snapshot + 장후 브리핑(최신 1건)
        ├─ 성공 → LLM 감성 분류(sentiment) → evening_briefing 테이블 저장
        └─ 실패 → 로그 경고 + 알림(WARN), 저장 스킵 (복기용이라 치명적 아님)

[09:01] job_trade_preparation_pipeline → S1 regime
   └─ _save_daily_context_snapshot()
        ├─ (기존) morning_context로 match_regime_set() → match_score
        └─ (신규 Phase2) 전날 evening_briefing 로드 → 아침 regime과 정렬 비교
             → confidence_adjustment 산출 → match_score 보정(±, 제한폭)
             → regime_set_applications에 evening_alignment 기록
```

## 구현 범위 (체크리스트)

### Phase 1 — 수집·저장·화면
- [ ] (1) `index_board_scraper.py` 신규 — Playwright로 snapshot + 브리핑 텍스트 파싱
- [ ] (2) `evening_briefing` 테이블 신규 (db.py)
- [ ] (3) settings 신규: 스케줄 시각, feature flag, 스크래핑 URL, 타임아웃
- [ ] (4) `run_market_tone_analysis()` 아침 경로에 스크래퍼 1차 + KIS 폴백 통합
- [ ] (5) `job_evening_briefing` 신규 스케줄 잡(00:00)
- [ ] (6) API: `GET /api/v1/evening-briefing/today` + 최근 N일
- [ ] (7) UI: 장후 브리핑 카드 + 아침/장후 비교 표시

### Phase 2 — 신뢰도 보정
- [ ] (8) evening 브리핑 LLM 감성 분류(risk_on/neutral/risk_off/volatile)
- [ ] (9) 아침 regime vs 전날 evening 정렬 비교 → `confidence_adjustment` 산출
- [ ] (10) `regime_set_applications`에 `evening_alignment`, `confidence_adjustment` 컬럼 추가
- [ ] (11) match_score 보정(정렬 시 +, 충돌 시 −, 제한폭 ±0.15)
- [ ] (12) UI에 신뢰도 보정 결과 텍스트 표시 (PM 눈으로 확인)

### 공통
- [ ] (13) 폴백·예외처리·로깅
- [ ] (14) 단위 테스트 (스크래퍼 파싱은 고정 HTML fixture로, 네트워크 의존 제거)

## 신뢰도 보정 공식 (Phase 2 초기안 — 보수적)

전날 장후 sentiment `E` ∈ {risk_on, neutral, risk_off, volatile},
당일 아침 regime `M` ∈ 동일 집합.

```
정렬도(alignment):
  - E == M                          → +0.10  (확신 강화)
  - 한쪽 neutral, 다른쪽 비neutral   →  0.00  (중립, 영향 없음)
  - risk_on ↔ risk_off (정반대 뒤집힘) → −0.15  (밤사이 급변, 불확실)
  - volatile 관여                    → −0.05  (변동성 경계)

confidence_adjustment = clamp(위 값, −0.15, +0.10)
보정 match_score = clamp(match_score + confidence_adjustment, 0.0, 1.0)
```

- 실데이터 부재로 초기값은 보수적. 며칠 데이터 축적 후 재조정(후속).
- 보정은 **표시·기록 우선**, sizing 직접 연동은 후속 과제로 분리(과결합 방지).

## 변경 파일 목록

| 파일 경로 | 변경 유형 | 변경 이유 |
|-----------|-----------|-----------|
| `backend/services/engine/index_board_scraper.py` | 신규 | Playwright 스크래핑 수집기 |
| `backend/services/db.py` | 수정 | `evening_briefing` 테이블 + settings 기본값 + regime_set_applications 컬럼 |
| `backend/services/engine/market_tone.py` | 수정 | 아침 경로 스크래퍼 1차 + 폴백 통합 |
| `backend/services/scheduler.py` | 수정 | `job_evening_briefing`(00:00) 등록 + `_parse_time` 폴백 추가 |
| `backend/services/engine/evening_briefing.py` | 신규 | 장후 브리핑 저장/조회/감성분류 로직 |
| `backend/services/engine/decision_engine.py` | 수정 | S1에서 evening 정렬 비교 + match_score 보정 |
| `backend/services/regime_set_service.py` | 수정 | confidence_adjustment 기록 (record_application 확장) |
| `backend/api/routes/evening_briefing.py` | 신규 | 장후 브리핑 조회 API |
| `backend/api/__init__.py` 또는 라우터 등록부 | 수정 | 신규 라우터 등록 |
| `backend/static/console.html` | 수정 | 장후 브리핑 카드 + 비교 표시 |
| `backend/static/js/screens/console-*.js` | 수정 | 장후 브리핑 로드/렌더 |
| `tests/unit/test_index_board_scraper.py` | 신규 | HTML fixture 파싱 테스트 |
| `tests/unit/test_evening_briefing.py` | 신규 | 저장/조회/감성분류 + 보정공식 테스트 |

## evening_briefing 테이블 스키마(안)

```sql
CREATE TABLE IF NOT EXISTS evening_briefing (
    id              TEXT PRIMARY KEY,
    trade_date      TEXT NOT NULL UNIQUE,   -- 해당 거래일(장 마감일)
    market_data     TEXT NOT NULL DEFAULT '{}',  -- snapshot JSON
    briefing_text   TEXT NOT NULL DEFAULT '',     -- 장후 브리핑 원문
    sentiment       TEXT NOT NULL DEFAULT 'neutral', -- LLM 분류 결과
    source_ts       TEXT,                    -- 사이트 브리핑 timestamp
    provider        TEXT NOT NULL DEFAULT 'index-board',
    created_at      TEXT NOT NULL
);
```

## settings 신규(안)

| key | 기본값 | type | 설명 |
|-----|--------|------|------|
| `schedule_evening_briefing_time` | "00:00" | string | 장후 브리핑 수집 시각 |
| `briefing.scrape_enabled` | true | boolean | 스크래핑 1차 소스 사용 (false면 기존 KIS+LLM만) |
| `briefing.scrape_url` | "https://index-board.space/briefing" | string | 스크래핑 대상 URL |
| `briefing.scrape_timeout_sec` | 20 | number | Playwright 페이지 로드 타임아웃 |
| `regime.evening_confidence_enabled` | true | boolean | Phase2 신뢰도 보정 on/off |

## 요구사항 대조표

| 요구사항 항목 | 계획서 반영 여부 | 비고 |
|---------------|-----------------|------|
| 스크래핑으로 더 빠르고 자세한 수집 | ✓ 반영 | (1)(4) 스크래퍼+아침 통합 |
| API보다 정확한 시황분석 | ✓ 반영 | 정제 브리핑→LLM regime 분류, 토큰↓ |
| 비용 절감 | ✓ 반영 | 원천 뉴스 분석 제거, 프롬프트 축소 |
| 장마감 시황 제공 | ✓ 반영 | (5)(6) evening 잡+API |
| 전일 장마감 vs 아침 비교 전략 | ✓ 반영 | Phase2 (8)~(12) 신뢰도 보정 |
| morning 8:30 / evening 00:00 두 잡 | ✓ 반영 | 8:30=기존잡 통합, 00:00=신규잡 |
| 장후=신뢰도보정+복기 (결정입력 아님) | ✓ 반영 | 공식 보수적, sizing 연동은 후속 |
| Playwright 사용 | ✓ 반영 | 이미 설치 확인, 런타임 최초 사용 |

## 추가 제안 항목 (PM 요청 외 — 승인 필요)

- **D1. 브리핑 중복 갱신 처리**: 사이트가 장전 브리핑을 02:52/08:56 등 여러 번 갱신 → 8:30 수집 시 가장 최신 timestamp 1건만 채택. (제안: 승인 시 기본 적용)
- **D2. 스크래핑 실패 알림**: 연속 2회 실패 시 Alert Center에 WARN 기록 (사이트 구조 변경 조기 감지). (제안)
- **D3. 사용량 매너**: 하루 2회 호출로 제한(서버 부하·매너), 재시도는 최대 1회. (제안)

## 엣지케이스 & 예외처리

- 사이트 구조 변경 → 파싱 실패 → 아침은 KIS 폴백, 장후는 저장 스킵+WARN
- Playwright 타임아웃 → 재시도 1회 후 폴백
- 브리핑이 아직 안 올라온 시각(예: 8:30인데 장전 브리핑 미갱신) → 직전 거래일 데이터로 폴백 표시
- 비거래일 → 기존 trading_calendar 가드 적용(잡 자체는 돌되 거래일 아니면 스킵)

## 완료 기준

- [ ] 스크래퍼 단위 테스트(고정 HTML fixture) 통과
- [ ] evening_briefing 저장/조회 + 보정공식 테스트 통과
- [ ] 전체 pytest 통과 (현재 473개 유지+신규)
- [ ] 아침 경로 폴백 동작 확인 (스크래핑 강제 실패 시 KIS 경로)
- [ ] 화면에 장후 브리핑 + 아침/장후 비교 + 신뢰도 보정 텍스트 표시
- [ ] node --check 통과, 빌드 에러 0
- [ ] docs/manual 업데이트

## PM 검토 요청 (결정 필요 항목)

1. **추가 제안 D1·D2·D3 승인 여부** (기본 적용 권장)
2. **신뢰도 보정 sizing 연동**: 이번엔 표시·기록까지만(후속에 sizing 연동) — 동의하는지
3. **장후 감성 분류에 LLM 사용** vs **스냅샷 수치 휴리스틱**: LLM 권장(브리핑 텍스트 뉘앙스 반영), 비용은 하루 1회로 미미 — 동의하는지
