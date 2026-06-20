# 읽기모델 계약 (READ MODEL CONTRACT)

> **이 문서의 목적** — PM(비개발자)이 코드를 열지 않고도 "이 화면의 이 숫자는 **어느 서버 프로그램**이
> 계산해 **DB 어디에** 저장하고, 화면은 그걸 **그냥 읽기만** 하는가?"를 한 표로 확인하기 위함.
> 데이트레이딩은 숫자 정확도가 생명이고, 같은 숫자가 화면마다 달라지면 신뢰가 무너진다.
> (작성 2026-06-20, 전 화면 점검 결과 기준)

---

## 1. 대원칙

```
   [엔진/스케줄러 = 계산하는 사람]              [웹 화면 = 보여주는 사람]
   S1~S10 파이프라인, 쓰기 경로  ──계산·DB저장──▶  DB  ──읽기만──▶  콘솔 화면
```

- **웹 화면은 그리기만 한다.** 화면을 열 때 숫자를 새로 계산하지 않는다.
- **계산과 저장은 별도 서버 프로그램**(S단계 엔진, 스케줄러, 쓰기 경로)이 1회 수행한다.
- 그래서 **같은 숫자는 어느 화면에서 봐도 같다**(단일 출처 = SSOT).

## 2. 화면 데이터를 3가지로 분류한다

| 분류 | 뜻 | 정확도 위험 |
|---|---|---|
| **A. 순수읽기** | DB 저장값을 SELECT해서 그릴 뿐 | 없음 (저장값이 곧 진실) |
| **B. 본질적 라이브** | KIS 실시간 잔고·시세 등 "지금 이 순간"이라 저장 불가 | 없음 (라이브가 정답) |
| **C. 읽기시점 계산** | 화면 로드 때 집계/파생 | **있음** — 입력이 다르면 숫자가 갈림 |

> 과거 "고쳐도 또 틀어진다"의 원인은 **C 중에서도 조회 윈도우에 의존하는 재계산**이었다
> (당일 성적을 4곳이 각자 다른 기간으로 페어링 → 6/19가 1/9 vs 3/7로 갈림).
> 2026-06-20 정비로 **C의 위험 요소를 A 또는 안전한 B로 전환**했다.

---

## 3. 핵심 숫자의 단일 출처 (SSOT)

| 숫자 | 누가 계산·저장 | 저장 위치 | 읽는 화면(모두 같은 값) |
|---|---|---|---|
| **당일 매매성적**(승/패/완료/미청산) | S10 복기엔진이 1회 산출 | `daily_review_reports.day_score` (JSON) | Daily Results · Review 매수판단 · 손실패턴 · LLM 복기텍스트 |
| **계좌 P&L**(전일 종가 대비 Δ) | 종가총평가 + 코드 앵커로 결정론적 산출 | `daily_review_reports.equity_eod_total_eval` + 코드 앵커 | Daily Results |
| **알림 요약**(severity/미확인) | 알림 생성·확인 **쓰기 경로**가 갱신 | `alert_summary_daily` | Alert Center 요약 |
| **배당 통계**(월별/계좌별/합계) | 배당 입력·수정·삭제 **쓰기 경로**가 갱신 | `dividend_stats_cache` (연도별) | Dividend Stats |

> **자가치유**: 위 저장값이 없으면(과거 데이터·최초 1회) 읽기 때 **딱 1회** 계산해 저장한 뒤 읽는다.
> 이후로는 순수읽기. 서버 내부(단일 writer)에서만 쓰므로 DB 손상 위험 없음.

---

## 4. 전 화면 분류표

### A. 순수읽기 — 엔진이 저장, 화면은 읽기만 ✅
| 화면/엔드포인트 | 숫자를 만드는 서버 프로그램 | 저장 테이블 |
|---|---|---|
| 시장톤 `/market-tone/today` | S2 시황 LLM | `market_tone_results` |
| 아침 컨텍스트 `/morning-context/today` | S2 | `morning_context` |
| 레짐 `/regime/today` | 레짐 엔진 | `regime_set_applications` |
| 유니버스 `/universe-filter/today` | S3 | `universe_filter_results` |
| 스크리닝 `/screening/today` | S4 | `hybrid_screening_results` |
| 일일계획 `/daily-plan/today`·`/intraday-events` | S5 | `daily_trading_plans` |
| 퍼널 `/funnel/summary` | S3~S5 카운트 | 각 단계 결과 테이블 |
| 복기 `/review-audit/today`·`/{date}` | S10 | `daily_review_reports` |
| 놓친기회 `/missed-opportunity/*` | EOD 학습 | `missed_opportunities` |
| 오탐(손실패턴) `/false-positive/*` | S10 + day_score | `daily_review_reports.day_score` |
| 신뢰도보정 `/confidence-calibration/today` | 보정 배치 | `confidence_calibration_daily` |
| 주문 `/orders/today` | 주문 실행기 | `trading_orders` |
| 재선별/교체 `/trading-monitor/reselection-stats`·`/replacement-signals` | 장중 재선별 엔진 | 재선별 로그 테이블 |
| 알림목록 `/alerts/` · 승인 `/approval/` | 각 쓰기 경로 | `system_alerts` · `approval_requests` |
| **알림요약 `/alerts/summary`** | **알림 쓰기 경로(2026-06-20 신설)** | **`alert_summary_daily`** |
| **배당통계 `/dividends/stats/summary`** | **배당 쓰기 경로(2026-06-20 신설)** | **`dividend_stats_cache`** |
| 배당/규칙/설정/전문지식 (CRUD) | 사용자 입력 | 각 설정 테이블 |
| **Daily Results 승/패 `/trading-monitor/daily-results`** | **S10 day_score(2026-06-20 순수읽기 전환)** | **`daily_review_reports.day_score`** |

### B. 본질적 라이브 — 저장 불가, 매번 KIS/런타임이 정답 (정상)
| 화면/엔드포인트 | 왜 저장 안 하나 |
|---|---|
| 계좌잔고 `/account/balance` | KIS 실시간 잔고·평가손익. 저장하면 낡은 값. |
| 보유종목 `/orders/positions`, `/trading-monitor/positions` | 실시간 시세·트레일링 상태가 매 순간 변함 |
| 후보 준비도 `/trading-monitor/candidates` | 실시간 틱·바엔진 신호상태 |
| 실시간 스트림 `/trading-monitor/stream` | SSE 실시간 틱 |
| 엔진/스케줄러 상태 `/decision/status`, `/scheduler/status`, `/bot/data-health` | 런타임 상태(저장 대상 아님) |

### C. 의도적 읽기시점 계산 — 단일 화면·항상 최신이 더 중요 (문서화된 예외)
| 화면/엔드포인트 | 무엇을 읽기 때 계산 | 왜 저장 안 하나 (PM 결정 2026-06-20) |
|---|---|---|
| Today Control 상단 `/bot/overview` | 퍼널 카운트·파이프라인 플래그 집계 + **KIS 실시간 평가** | 입력이 **장중 계속 변동**. 저장하면 장중 낡은 값. 단일 화면이라 다른 화면과 갈릴 일 없음. KIS 부분은 B(라이브). |
| 정책요약 `/trading-monitor/policy-summary` | 진입룰·정책문구를 시장톤/스크리닝/계획에서 파생 | 시장톤이 **장중 슬롯마다 갱신** → 항상 최신 표시가 운영에 유리. 결정론적이라 같은 입력이면 같은 값. |
| 심볼별 룰 `/rule/composition/{symbol}` | 베이스·프로파일·계획·오버라이드 병합 | 설정성 즉시 해석. 단일 조회. |

> **핵심**: C는 "여러 화면이 공유하는 숫자"가 **아니다**. 각자 단일 화면 안에서 결정론적으로
> 계산하므로 화면 간 드리프트(과거 버그)가 생기지 않는다. 오히려 저장하면 장중에 낡아진다.
> 그래서 의도적으로 읽기시점 계산을 유지한다 — KIS 라이브와 같은 정당한 예외.

---

## 5. 정합이 다시 깨지지 않게 하는 가드

- `tests/unit/test_cross_surface_consistency.py` — "Daily Results 승/패 == 저장 day_score ==
  손실패턴 건수 == LLM 복기텍스트"를 강제. 누가 어딘가에 또 따로 계산하는 코드를 넣으면 **CI에서 즉시 실패**.
- `tests/unit/test_materialized_summaries.py` — alerts/dividends가 쓰기시점 저장 + 읽기 순수 +
  lazy 백필을 지키는지 강제.
- `tests/unit/test_daily_score.py` — 당일 성적 SSOT(`compute_daily_score`)의 구조 불변식.

## 6. 새 화면/숫자를 추가할 때 규칙

1. **여러 화면이 공유하는 숫자인가?** → 반드시 엔진이 1회 계산·저장(SSOT). 화면은 읽기만.
2. **이산적 쓰기 이벤트(입력/삭제)로만 바뀌나?** → 그 쓰기 경로에서 갱신·저장(예: alerts/dividends).
3. **장중 계속 변하거나 KIS 실시간인가?** → 읽기 유지(B/C). 단, **단일 화면 전용**일 때만 허용하고
   이 문서 C 표에 "왜 읽기인지" 한 줄 남긴다.
4. 화면 로드 때 **조회 기간(윈도우)에 따라 숫자가 달라지는 계산은 절대 금지** — 과거 드리프트의 뿌리.
