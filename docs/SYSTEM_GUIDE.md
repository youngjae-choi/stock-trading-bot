# 자동매매 시스템 운영 가이드

> 최종 수정: 2026-05-04  
> 대상: 운영자(PM) — 기술 배경 없이도 시스템 상태를 파악하고 결과를 해석하기 위한 문서

---

## 목차
1. [하루 사이클 개요](#1-하루-사이클-개요)
2. [시장 톤 (S2)](#2-시장-톤-s2)
3. [유니버스 필터 (S3)](#3-유니버스-필터-s3)
4. [종목 스크리닝 (S4)](#4-종목-스크리닝-s4)
5. [Risk Profile — 매도 조건](#5-risk-profile--매도-조건)
6. [RulePack — 매수 조건](#6-rulepack--매수-조건)
7. [어디서 확인하나](#7-어디서-확인하나)
8. [서버 운영 명령어](#8-서버-운영-명령어)

---

## 1. 하루 사이클 개요

시스템은 매 영업일 아래 순서로 자동 실행된다.

```
07:45  S1  KIS 토큰 갱신          ← 장 시작 전 인증 준비
08:00  S2  AI 시장 톤 분석        ← Claude가 해외 시장 분위기 판단
09:05  S3  유니버스 필터          ← 거래대금·거래량 상위 종목 추려내기
09:20  S4  Hybrid Screening       ← Claude Opus가 후보 종목 정성 평가
09:35  S5  Daily Plan 생성        ← 오늘 매매할 종목 + 프로파일 배정
09:45  S6  Decision Engine 활성화 ← 실시간 WebSocket 매매 시작
15:20  S9  당일 청산              ← 남은 포지션 전부 정리
16:00  S10 Review & Audit         ← 오늘 거래 복기 분석
16:30  S11 Learning Memory        ← 내일에 반영할 교훈 저장
```

**S3~S5는 09:00 이후에 실행** — 장 시작 전엔 거래량 데이터가 없어서 의미가 없기 때문.

---

## 2. 시장 톤 (S2)

### "Positive"가 좋은 건가요?

**좋은 것이다.** 시장 톤은 5단계가 아닌 4단계 분류다:

| 톤 | 의미 | 시스템 반응 |
|----|------|-------------|
| `positive` | 해외 시장 강세, 한국 시장 상승 기대 | 거래량 가중치 ↑, 공격적 필터 |
| `neutral` | 뚜렷한 방향성 없음 | 기본 가중치 |
| `mixed` | 강세/약세 신호 혼재 | neutral과 동일하게 처리 |
| `negative` | 해외 시장 약세, 하락 우려 | 거래대금 가중치 ↑, 보수적 필터 |

### 오늘(2026-05-04) 시장 톤

```
톤:         positive (confidence: 82%)
판단 근거:  S&P500·NASDAQ 동반 +1.3~1.8%, 미국 10년 금리 하락, 원/달러 소폭 하락
리스크:     WTI 원유 소폭 하락으로 에너지 업종 약세 가능, 환율 1,471원대 높은 수준
```

### 톤이 가중치에 미치는 영향

| 톤 | 거래대금 가중치 | 거래량 가중치 | 등락률 가중치 |
|----|---------------|--------------|--------------|
| positive | 40% | **40%** | 20% |
| neutral | 50% | 30% | 20% |
| negative | **60%** | 30% | 10% |

→ 오늘은 `positive`이므로 거래대금과 거래량을 동등하게 봐서 **모멘텀이 붙는 종목**을 선호한다.

---

## 3. 유니버스 필터 (S3)

### 무엇을 하나

KIS에서 **거래대금 상위 30종목**과 **거래량 상위 30종목**을 가져와 합산·점수화한 뒤, 1차 필터를 통과한 종목을 Claude Opus에게 넘긴다.

### 필터 조건 (이것에 걸리면 즉시 탈락)

| 조건 | 기준 | 이유 |
|------|------|------|
| 상한가/하한가 근접 | 등락률 ±29% 이상 | 급등락 종목은 예측 불가 |
| 가격 0원 | 가격 ≤ 0 | 데이터 오류 |
| 거래량 + 거래대금 모두 0 | 동시에 0 | 실제 거래 없는 종목 |

### 점수 계산 방식

```
점수 = 거래대금 점수 × (시장톤 가중치)
     + 거래량 점수 × (시장톤 가중치)
     + 등락률 점수 × (시장톤 가중치)

등락률 점수 = (등락률% + 30) / 60  ← -30%~+30% 범위 정규화, 양수 선호
```

### 결과 확인 위치

**콘솔 UI** → `Today Control` 화면 → **Funnel Monitor** 카드  
또는 API: `GET /api/v1/universe-filter/today`

---

## 4. 종목 스크리닝 (S4)

### 무엇을 하나

S3에서 선별된 상위 30종목을 **Claude Opus**가 정성 평가해 오늘 매매에 적합한 종목을 선별한다. AI가 점수를 매기는 것이지 매수 지시가 아니다.

### Claude가 평가하는 항목

1. **시장 톤과의 부합도** — 오늘이 positive면 모멘텀 섹터 선호
2. **테마 적합성** — 오늘의 이슈(반도체, AI, 외국인 수급 등)와 연관성
3. **재료 유무** — 공시, 뉴스, 업황 이슈
4. **리스크 요인** — 환율, 섹터 약세, 수급 이탈 징후

### suitability_score 기준

| 점수 | 의미 |
|------|------|
| 0.8 ~ 1.0 | 오늘 테마와 강하게 부합, 명확한 재료 있음 → 최우선 후보 |
| 0.5 ~ 0.8 | 부분적으로 부합, 일반적 매력 → 후보 포함 |
| 0.3 ~ 0.5 | 약한 근거, 큰 매력 없음 → 하위 후보 |
| 0.0 ~ 0.3 | 부합하지 않거나 정보 부족 → 제외 |

### 최종 후보 선정

```
최종 점수 = 정량 점수(S3) × 50% + 정성 점수(Claude S4) × 50%
```

상위 10~15종목이 S5 Daily Plan으로 넘어간다.

### Risk Profile 배정

S5(Daily Plan)에서 Claude가 각 종목에 프로파일을 배정한다. 배정 기준:

| 프로파일 | 특성 | 배정 기준 |
|----------|------|-----------|
| `LOW_VOL` | 저변동성, 안정적 | 대형주, 저변동성 섹터 |
| `MID_VOL` | 중간 변동성 | 일반 중형주 |
| `HIGH_VOL` | 고변동성, 공격적 | 테마주, 급등 후보 |
| `THEME_SPIKE` | 극고변동성, 단기 | 테마 급등 종목, 재진입 불가 |

### 결과 확인 위치

**콘솔 UI** → `Today Control` → **Funnel Monitor** 카드 (S4 건수 확인)  
상세 종목 목록 → `Today Control` → **Today Daily Plan** 카드  
또는 API: `GET /api/v1/screening/today`

---

## 5. Risk Profile — 매도 조건

### 매도 조건은 Settings에서 관리된다 (고정값)

매도는 종목마다 배정된 프로파일에 따라 자동으로 결정된다.

#### LOW_VOL (저변동성)
```
초기 손절:    -2.0%  (매수가 대비 2% 손실 시 바로 매도)
트레일링 발동: +1.5%  (이 수익을 넘으면 트레일링 스탑 작동)
트레일링 간격: 1.8%   (고점 대비 1.8% 하락 시 익절)
최대 보유 시간: 240분 (4시간)
포지션 한도:  계좌의 15%
```

#### MID_VOL (중간 변동성)
```
초기 손절:    -3.0%
트레일링 발동: +2.5%
트레일링 간격: 3.0%
최대 보유 시간: 180분 (3시간)
포지션 한도:  계좌의 12%
```

#### HIGH_VOL (고변동성)
```
초기 손절:    -4.5%
트레일링 발동: +4.0%
트레일링 간격: 5.0%
최대 보유 시간: 120분 (2시간)
포지션 한도:  계좌의 8%
```

#### THEME_SPIKE (테마 급등)
```
초기 손절:    -6.0%
트레일링 발동: +5.0%
트레일링 간격: 6.0%
최대 보유 시간: 60분 (1시간)
포지션 한도:  계좌의 5%
재진입 금지
```

### 트레일링 스탑 작동 방식

```
매수 → 수익이 트레일링 발동 기준 초과
→ 트레일링 스탑 ON
→ 고점 갱신할 때마다 스탑 라인도 따라 올라감
→ 고점 대비 트레일링 간격 이상 하락 시 자동 매도 (익절)
→ 단, 초기 손절은 항상 유지 (손실 보호)
```

### 15:20 강제 청산

프로파일에 관계없이 **15:20에 남은 포지션 전부 시장가 청산**.

### 확인 위치

**콘솔 UI** → `Settings` → **Risk Profiles** 카드

---

## 6. RulePack — 매수 조건

### 매수 조건은 그날그날 달라지나요?

**원칙적으로 달라질 수 있다.** RulePack은 매일 AI가 생성하거나 운영자가 수동으로 설정할 수 있다.  
현재는 **수동 생성된 RulePack이 활성화**돼 있으며, 오늘 자동 생성은 아직 미구현이다.

### 현재 활성 매수 조건

```
[ Layer 3 — 실시간 진입 조건 ] (09:45 Decision Engine 활성화 후 적용)

VWAP 위에서만 매수       ← 당일 평균 가격 위에서만 진입 (약세 흐름 배제)
거래량 배율 ≥ 2.0배      ← 평소 대비 2배 이상 거래량 (모멘텀 확인)
20일 이평선 위            ← 중기 상승 추세 확인
RSI 40~70               ← 과매도/과매수 구간 배제
호가 스프레드 ≤ 0.3%     ← 유동성 불량 종목 배제
코스피 방향 일치          ← 지수 역행 종목 배제
AI 신뢰도 ≥ 65%          ← S4 정성 점수 65% 미만 종목 배제

[ 리스크 한도 ]
일일 손실 한도: -2.0%    ← 계좌 대비 2% 손실 시 당일 신규 매수 중단
최대 동시 보유: 5종목
종목당 최대 비중: 10%
```

### 매수 실행 흐름

```
09:45  Decision Engine ON
  ↓
실시간 WebSocket으로 체결 tick 수신
  ↓
Layer 3 조건 실시간 체크
  ↓
모든 조건 통과 → KIS 모의투자 매수 주문 (limit order)
  ↓
체결 확인 → Position Manager 등록 → 트레일링 스탑 감시 시작
```

### 확인 위치

**콘솔 UI** → `Today Control` → **Active RulePack** 카드  
또는 API: `GET /api/v1/bot/rulepack/today`

---

## 7. 어디서 확인하나

| 궁금한 것 | 콘솔 화면 | 경로 |
|-----------|-----------|------|
| 오늘 시장 톤 | Today Control | Market Tone 카드 |
| 유니버스 필터 결과 (몇 종목?) | Today Control | Funnel Monitor → S3 건수 |
| 스크리닝 결과 (어느 종목?) | Today Control | Funnel Monitor → S4 건수, Daily Plan 카드 |
| 종목별 Risk Profile | Today Control | Daily Plan 카드 → 종목별 profile 컬럼 |
| 오늘 매수 조건 | Today Control | Active RulePack 카드 |
| 현재 보유 포지션 | Today Control | Positions 카드 |
| 오늘 체결 내역 | Today Control | Signals / Orders 카드 |
| 매도 프로파일 설정값 | Settings | Risk Profiles 카드 |
| 알림/이상 | Alert Center | 사이드바 → Alert Center |
| 데이터 품질 이상 | Data & API | Data Quality Guard 카드 |
| 어제 복기 결과 | Review & Audit | 사이드바 → Review & Audit |
| 학습된 교훈 | Learning Memory | 사이드바 → Learning Memory |

**콘솔 URL**: `http://서버IP:8000/console`

---

## 8. 서버 운영 명령어

### 서버 상태 확인
```bash
sudo systemctl status stock-trading-bot
```

### 로그 실시간 모니터링
```bash
sudo journalctl -u stock-trading-bot -f
```

### 서버 재시작
```bash
sudo systemctl restart stock-trading-bot
```

### 서버 중지 / 시작
```bash
sudo systemctl stop stock-trading-bot
sudo systemctl start stock-trading-bot
```

### 부팅 시 자동 시작 여부 확인
```bash
sudo systemctl is-enabled stock-trading-bot
# → enabled 이면 정상
```

### 오늘 특정 단계 수동 실행 (콘솔 로그인 후)
| 단계 | API |
|------|-----|
| S1 토큰 갱신 | `POST /api/v1/engine/token-refresh` |
| S2 시장 톤 | `POST /api/v1/market-tone/analyze` |
| S3 유니버스 | `POST /api/v1/universe-filter/run` |
| S4 스크리닝 | `POST /api/v1/screening/run` |
| S5 Daily Plan | `POST /api/v1/daily-plan/generate` |
| Decision Engine ON | `POST /api/v1/decision/activate` |
| Decision Engine OFF | `POST /api/v1/decision/deactivate` |

---

## 부록: 전체 데이터 흐름 요약

```
[해외 시장 데이터] ──→ S2(Claude) ──→ 시장 톤(positive/neutral/negative/mixed)
                                            │
[KIS 거래대금·거래량] ──→ S3 ──→ 상위 30종목 (시장 톤 가중치 반영)
                                            │
[KIS 현재가·투자자 동향] ──→ S4(Claude Opus) ──→ 정성 점수 + 적합 종목 선별
                                            │
[S3+S4 후보 합산] ──→ S5(Claude) ──→ Daily Plan (종목별 Risk Profile 배정)
                                            │
[09:45 장 시작 후] ──→ Decision Engine ──→ Layer3 조건 실시간 체크
                                            │
               [통과] ──→ KIS 매수 주문 ──→ Position Manager(트레일링 스탑)
                                            │
                          [손절/익절/강제청산] ──→ KIS 매도 주문
                                            │
[16:00] ──→ S10 Review & Audit ──→ S11 Learning Memory ──→ 내일 S3~S5에 반영
```
