# 트레이딩 복기 — 2026-05-22

---

## 📊 오늘 거래 요약

| 항목 | 값 |
|------|-----|
| 거래일 | 2026-05-22 |
| 시장 톤 | mixed |
| RulePack | RP-S4-20260522-2D6EEA |
| 총 주문 | 8건 |
| 매수 / 매도 / 실패 | 4 / 4 / 0건 |
| 실현 손익 | +191,175원 (+0.49%) |
| 손익 검증 | verified (fills) |
| 놓친 기회 | 38건 |
| 손실 거래 | 2건 |

## 📈 거래 상세

### 완료된 거래

| 종목 | 매수가 | 매도가 | 수익률 | 금액 | 청산사유 |
|------|--------|--------|--------|------|---------|
| **삼성SDI** (006400) | 641,000원 | 644,000원 | +0.47% | +36,000원 | eod |
| **삼성전기** (009150) | 1,261,000원 | 1,300,062원 | +3.10% | +312,500원 | eod |
| **두산에너빌리티** (034020) | 112,300원 | 111,885원 | -0.37% | -37,325원 | eod |
| **LG에너지솔루션** (373220) | 408,500원 | 403,500원 | -1.22% | -120,000원 | eod |

## ❌ 놓친 기회

| 종목 | 단계 | 사유 |
|------|------|------|
| 046970 | S4_HYBRID_SCREENING | S4_SCREENING: change_rate +20.44%로 max 5.0% 대폭 초과, 상한가 수준으로 추격 매수 리스크 극대 |
| 028260 | S4_HYBRID_SCREENING | S4_SCREENING: change_rate +0.36%로 min_price_change_pct 1.0% 미달 |
| 066570 | S4_HYBRID_SCREENING | S4_SCREENING: change_rate -0.21%로 하락 중, min_price_change_pct 1.0% 미달 |
| 069540 | S4_HYBRID_SCREENING | S4_SCREENING: change_rate +25.93%로 max 5.0% 대폭 초과, 상한가 수준으로 추격 매수 리스크 극대 |
| 012330 | S4_HYBRID_SCREENING | S4_SCREENING: change_rate -4.93%로 급락 중, 현대차그룹 동반 약세 |
| 000270 | S4_HYBRID_SCREENING | S4_SCREENING: change_rate -1.97%로 하락 중, 자동차 섹터 관세 불확실성 |
| 005380 | S4_HYBRID_SCREENING | S4_SCREENING: change_rate -2.25%로 하락 중, 현대차 관세 리스크 환경에서 롱 진입 부적합 |
| 005935 | S4_HYBRID_SCREENING | S4_SCREENING: change_rate -0.37%로 하락 중, 우선주로 유동성 제한 |
| 402340 | S4_HYBRID_SCREENING | S4_SCREENING: change_rate +0.25%로 min_price_change_pct 1.0% 미달 |
| 000660 | S4_HYBRID_SCREENING | S4_SCREENING: change_rate 0.0%로 모멘텀 전무, min_price_change_pct 1.0% 미달 |
| 005930 | S4_HYBRID_SCREENING | S4_SCREENING: change_rate -1.34%로 하락 중, min_price_change_pct 1.0% 미달이며 음수 방향 |
| 115500 | S3_UNIVERSE_FILTER | S3_FILTER: 상한가/하한가 제외 change_rate=30.0% |
| 208710 | S3_UNIVERSE_FILTER | S3_FILTER: 상한가/하한가 제외 change_rate=30.0% |
| 185680 | S5_DAILY_PLAN | S5_NOT_ASSIGNED: 플랜 미배정 |
| 364990 | S5_DAILY_PLAN | S5_NOT_ASSIGNED: 플랜 미배정 |

## ⚠️ 손실 거래 분석 (False Positive)

| 종목 | 유형 | 매수가→매도가 | 손실률 | 손실 원인 |
|------|------|-------------|--------|---------|
| LG에너지솔루션 (373220) | entry_fail | 408,500→403,500원 | -1.2% | 매수가 408,500원 → 매도가 403,500원, 손실 -1.2% (-120,000원). 청산사유: eod |
| 두산에너빌리티 (034020) | entry_fail | 112,300→111,885원 | -0.4% | 매수가 112,300원 → 매도가 111,885원, 손실 -0.4% (-37,325원). 청산사유: eod |

## ⚡ 무결성 경고

- 청산 대상 외 전일 전략 잔여 포지션이 있습니다.

## 🔮 내일 전략 방향

- 📊 손익 +0.49% — 현재 전략 유지하며 모니터링
- ⚠️ 손실 거래 2건 — 진입 조건 confidence 임계값 상향 또는 종목 필터 강화 검토
- 📌 놓친 기회 38건 — S3/S4 필터 조건 일부 완화 또는 RulePack 조정 검토
- 🔴 무결성 경고 1건 — 체결 검증 후 오더북 정리 필요

---

*S10 자동 생성 복기 보고서*
