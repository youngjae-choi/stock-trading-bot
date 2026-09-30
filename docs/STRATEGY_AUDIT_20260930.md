# 매매기법 전수점검 보고서 (2026-09-30)

> 질문: ① 개발된 데이트레이딩 기법이 `STRATEGY_SPEC.md`에 100% 반영돼 있나? ② 폭락·하락·보합·상승·폭등 모두 수익을 낼 수 있는 구조인가(전문가·논문 대비)?
> 방법: 코드 전 경로 추적 + 라이브 DB 설정·성과 조회(읽기 전용) + 논문·실무서 조사 + 실거래 재시뮬 통계.

## 한 줄 결론
1. **SPEC은 100% 일치하지 않았다** → 불일치 20+건을 찾아 이번에 SPEC·INTENT를 실제 동작 그대로 교정했다(드리프트 0 확인).
2. **5장세 모두 수익 구조가 아니다.** 실측과 논문이 같은 답: **보합만 수익, 하락·폭락은 방어(현금), 상승·폭등은 현 구조로 손실/미참여.** 롱온리 단일 단타기법이 모든 장세에서 번다는 신뢰할 근거는 없다.
3. 어제 켠 "거래량 마름" 승리조건은 **손실군을 걸러내는 효과는 근거가 있지만, 흑자 자체는 아직 통계적으로 증명되지 않았다**(41건).

---

## 1. SPEC ↔ 실제 동작 대조

### 매매 결과를 바꾸는 불일치 (교정 완료, 일부는 PM 결정 필요)
| # | 항목 | SPEC에 적혀 있던 것 | 실제 동작 |
|---|---|---|---|
| 1 | 하락전환 매수중단·트레일조임 | 켜짐 | **꺼짐**(09-29 하락장 테스트). `entry_suspended=true` 잔재 |
| 2 | ABCD 진입엔진 | 상승장 한정 | **전 장세**에서 켜짐, VWAP 천장·바닥·거래량마름 **모두 건너뜀** |
| 3 | 모멘텀 진입 | 실전 가동, ORB 돌파 | **꺼짐**(09-18/09-23 손실로) |
| 4 | confidence 게이트 | 방어장세 강화 | **꺼짐**(09-02, 죽은 신호) |
| 5 | 장세별 VWAP 기준 | 장중 장세 바뀌면 따라감 | **아침 판정으로 하루 종일 고정**. 09-30: 11시 보합 전환됐는데 종일 상승장 기준(VWAP까지 허용)으로 매수 |
| 6 | 수익 확정(수확) | 모든 장세 +2%에서 50% | 하락장 **+1.5%에서 80%**, 변동성장 **+1.2%에서 전량**(코드에 고정) |
| 7 | 상승/폭등 트레일 | +4%에서 3% 폭 | 상승 **+2%/1.5%**, 폭등 **+3%/2%**로 덮어씀 |
| 8 | 손절 | 장세 SET(-4~-5%) | 일부 종목은 **기본값 -2.5%**로 돎(9월 10일치 실제 발생) |
| 9 | 상승장 밴드(E6) | 기재 없음 | 꺼져 있으나 **DB 값이 지워지면 자동으로 켜짐**(코드 기본값이 ON) |
| 10 | 수급 점수 | 최종 순위 반영 | 후보 명단 진입에만 영향, 2차 순위(S4)엔 미반영 |
| 11 | 드리프트 감시 기준(INTENT) | — | 라이브와 8건 불일치 상태로 경보만 울리던 중 |
| 12 | 폭락장 인버스 예산 30% 상한 | — | **버그로 무력화**(상한 적용 뒤 다른 계산이 수량을 덮어씀) |

그 외 표기 오류: 등락률 기준은 "시가 대비"가 아니라 **전일종가 대비**, 강제청산은 15:20이 아니라 **시장톤에 따라 15:05~15:12**, 2분 폴링은 장세를 다시 판정하지 않음(30분 크론이 함), 프로필별 금액상한·TSI 하드제외·반등트랙 전 장세 동작 등 누락 항목 추가.

**조치:** `STRATEGY_SPEC.md` A절 교정, 상단에 "지금 켜진 실험 설정" 표 신설, 관리주의(A-7)에 #7~#12 추가, `strategy_spec.py` INTENT를 라이브에 맞춤(실험 설정은 ⚠실험 표시 + 롤백값), 코드기본과 다른 키는 DB에서 사라지면 경보가 뜨도록 감시 대상으로 이동. `--check` 드리프트 0, conformance 일치.

---

## 2. 5장세 수익 구조 — 실측

9월(09-01~09-29, 19거래일) 계좌 총평가 기준 **-650만원(-7.4%)**. 장 마감 시점 장세로 나누면:

| 장세 | 일수 | 수익 난 날 | 손익 |
|---|---|---|---|
| 상승(risk_on) | 6 | **0일** | **-602만** |
| 보합(neutral) | 9 | 5일 | **+53만** |
| 하락(risk_off) | 4 | 1일 | -101만 |
| 폭락·폭등·변동성 | **0** | — | **한 번도 겪어보지 않음(검증 불가)** |

→ **손실의 대부분이 상승장에서 났다.** 보합장만 흑자.

## 3. 5장세 수익 구조 — 논문·전문가 비교

| 장세 | 논문이 말하는 것 | 우리 기법 |
|---|---|---|
| **폭락** | 하루 안에서 떨어지는 흐름은 장 마감까지 이어지는 경향(장중 모멘텀). 싸 보여서 사면 더 떨어짐 | 신규매수 차단·배포 30%는 **올바른 설계**. 인버스 상한 버그는 고쳐야 함 |
| **하락** | 같은 이유로 눌림 매수 = 흐름 역행 | 소손실. 하락전환 매수중단을 꺼둔 지금은 **위험 노출 중** |
| **보합** | 옆으로 기는 장에서만 "많이 빠진 걸 사면 되돌아온다(평균회귀)"가 성립 | **유일한 수익 구간** — 실측과 일치 |
| **상승** | 오르는 장에선 VWAP **위**에 있는 강한 종목을 따라가야 이김(VWAP 추세추종 논문). VWAP 아래 종목은 뒤처진 약체 | 우리는 VWAP 아래를 삼 → **구조적으로 약체 매수**. 실측 6일 전패와 일치 |
| **폭등** | 수익은 거래량 폭발한 주도주("stocks in play")에서 남 | 등락률 +4% 넘으면 안 사므로 **주도주를 전부 놓침** |

**모든 장세에서 버는 한 가지 기법?** 믿을 만한 문헌 중 그렇다고 주장하는 곳은 없다. 극단적인 장에서 돈을 버는 전략들은 **공매도**를 쓴다. 한국 개인은 공매도가 사실상 제한되므로, 현실적 방어수단은 **현금 보유와 인버스 1배 ETF**뿐이다. 참고로 대만 데이트레이더 전체를 15년 추적한 연구에서 개인 단타는 15년 중 14년 손실이었다(기저율이 나쁘다).

**거래량 마름 필터에 대해:** 학술 연구는 오히려 "거래량이 터지며 떨어진 주식이 반등한다"고 본다. 그런데 우리 데이터에선 반대(조용한 눌림이 이김)가 나왔다. 이는 우리 필터가 "많이 빠진 걸 사는 것"이 아니라 **"오르던 종목이 조용히 쉬는 순간을 사는 것(추세 지속)"** 으로 작동한다는 뜻으로 해석된다. Linda Raschke·Brian Shannon 같은 실무 전문가의 "추세 속 눌림" 개념과 맞는다.

## 4. 통계로 본 "승리조건"의 신뢰도 (실측 재시뮬)

| 진입 그룹 | 건수 | 거래당 순손익 | t값 | 승률(95% 범위) |
|---|---|---|---|---|
| 지금까지 전체 | 111 | **-0.745%** | **-3.04** | 45% (36~54%) |
| 승리조건(VWAP -1% 이하 + 거래량 마름) | 41 | **+0.165%** | 0.38 | 63% (49~78%) |
| 거래량 터질 때 눌림 매수 | 38 | **-0.953%** | **-2.56** | 42% (26~58%) |

쉽게 말하면:
- **확실한 것:** 지금까지 방식 전체, 그리고 "거래량 터질 때 사기"는 **우연이 아니라 진짜로 지는 방식**이다(t값이 -2.5보다 작음 = 통계적으로 유의).
- **아직 모르는 것:** 승리조건의 +0.165%는 **동전 던지기와 구분이 안 된다**(t=0.38). 흑자를 통계적으로 증명하려면 약 1,160건(보통 기준)~2,600건(엄격 기준)이 필요하다. 하루 2건이면 2~5년.
- 손익 구조: 평균 이익 +1.96% vs 평균 손실 -2.95% → **본전 승률 60%**. 지금 63%로 겨우 넘는 수준이라 여유가 얇다.

그래도 켜둔 게 맞는 이유: **손실이 확실한 그룹을 걸러내는 효과**는 근거가 있기 때문이다(-0.95% 그룹 차단). "돈을 버는 필터"라기보다 "확실히 잃는 거래를 막는 필터"로 이해하는 게 정확하다.

## 5. PM 결정이 필요한 것

| # | 결정 | 권고 | 이유 |
|---|---|---|---|
| 1 | 인버스 예산상한 버그 수정 | **즉시 수정** | 다음 폭락장에서 인버스를 과대 매수할 수 있음. 소규모 수정 |
| 2 | 하락전환 매수중단 | **다시 켜기 권고** | 논문·실측 모두 하락 흐름 중 매수 = 손실 방향. 테스트는 9-29~ 데이터로 평가 후 종료 |
| 3 | ABCD 전 장세 | **상승장 한정(up) 또는 관찰(shadow)로 복귀 권고** | 모든 안전 필터를 건너뛰고, 백테스트도 손실 |
| 4 | 장세별 VWAP 기준 | **장중 장세 따라가게 수정 권고** | 09-30처럼 장세가 바뀌어도 아침 기준으로 매수하는 불일치 |
| 5 | -2.5% 기본손절 | 장세 SET 손절로 통일 검토 | 같은 전략인데 종목에 따라 손절폭이 다름 |
| 6 | 상승장 전략 | 관찰 계속(표본 부족) | 논문 방향(VWAP 위 강세주)은 E6와 같으나 실현손익이 반증됨 |
| 7 | 목표 재정의 | "5장세 수익" → **"보합 수익 + 나머지 손실 최소화"** | 현 구조의 정직한 목표. 상승장 수익은 별도 엔진 과제 |

### 적용 결과 (2026-10-01 07:30 장전, PM 지시)
- ✅ #1 인버스 예산상한 버그 수정 — 상한을 최종 수량 확정 후 적용(`order_executor.py`)
- ✅ #2 하락전환 매수중단 복원(`transition_response_active=true`) + 래치 잔재 리셋
- ✅ #3 ABCD 전 장세 → 상승장 한정(`abcd_enforce_regimes=up`)
- ✅ #4 VWAP 기준 장세 = 장중 현재 SET 추종(`engine.gate_regime_source=intraday`, 롤백 `snapshot`)
- 🔍 부수 발견·수정: 전체 테스트 실행이 **라이브 DB에 가짜 하락전환·KOSPI 값을 기록**하던 누수(07:18 기록) → conftest에서 차단, 오염값 정리
- 미적용(후속): #5 -2.5% 기본손절 통일, #6 상승장 전략

---

## 출처
- Gao, Han, Li, Zhou (2018) Market intraday momentum, JFE — https://www.semanticscholar.org/paper/Market-intraday-momentum-Gao-Han/eb5931b46eb39831d053babe7bfed0f4687f0cea
- Baltussen, Da, Lammers, Martens (2021) Hedging demand and market intraday momentum, JFE — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3760365
- Lai, Lin, Eom, Tsai (2022) KOSPI 장중 모멘텀 — https://pdfs.semanticscholar.org/f318/9fbb43163889c153dd0735c3140d8a5ac940.pdf
- Heston, Korajczyk, Sadka (2010) Intraday patterns in the cross-section, JF — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1509466
- Zarattini, Aziz — VWAP 추세추종 — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4631351
- Zarattini, Barbon, Aziz — ORB "stocks in play" — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284
- Nagel (2012) Evaporating liquidity, RFS — https://econpapers.repec.org/RePEc:oup:rfinst:v:25:y:2012:i:7:p:2005-2039
- Campbell, Grossman, Wang (1993) Trading volume and serial correlation, QJE — https://ideas.repec.org/a/oup/qjecon/v108y1993i4p905-939..html
- Llorente, Michaely, Saar, Wang (2002) RFS — https://academic.oup.com/rfs/article-abstract/15/4/1005/1567663
- Raschke — Holy Grail 셋업 — https://lindaraschke.net/faq-terminology-setups/
- Shannon — Anchored VWAP — https://cmtassociation.org/wp-content/uploads/2024/01/Shannon-Specific-Anchored-VWAP-Strategies-1.pdf
- Kaminski, Lo (2014) When do stop-loss rules stop losses? — https://dspace.mit.edu/bitstream/handle/1721.1/114876/Lo_When%20Do%20Stop-Loss.pdf
- Frazzini (2006) Disposition effect, JF — https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.2006.00896.x
- Moskowitz, Ooi, Pedersen (2012) Time series momentum, JFE — https://www.researchgate.net/publication/239806792_Time_series_momentum
- Daniel, Moskowitz (2016) Momentum crashes, JFE — https://www.kentdaniel.net/papers/published/jfe_16.pdf
- Barber, Lee, Liu, Odean — 대만 데이트레이더 — https://faculty.haas.berkeley.edu/odean/papers/Day%20Traders/Day%20Trading%20and%20Learning%20110217.pdf
- White (2000) Reality check for data snooping — https://onlinelibrary.wiley.com/doi/abs/10.1111/1468-0262.00152
- Bailey, López de Prado — Deflated Sharpe — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- Harvey, Liu, Zhu (2016) …and the cross-section of expected returns, RFS — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2249314
- 한국 2026 거래세 0.20% — https://taxnews.ey.com/news/2026-0126-korea-enacts-2026-tax-reform-bill
- 한국 공매도 재개(2025-03-31) — https://www.fsc.go.kr/eng/pr010101/84220

*한계: 우리 기법(한국 개별주 장중 VWAP 눌림 + 거래량마름 + 수급)을 장세별로 직접 검증한 논문은 없다. 장세별 판정은 일반 원리 + 우리 실측(장세당 4~9일)에 기반한다.*
