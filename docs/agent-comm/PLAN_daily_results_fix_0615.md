# Daily Results · 복기 손익 정합 버그 — 개발계획서 v0.1

## 원본 요구사항 (PM 발화 그대로 인용)

> 3. Daily Results& Trade Review화면
> - Daily Results화면에서는 6월 15일 결과가 2/4인데 하나도 안맞아.
> - 손실 패턴 분석 카드의 종목들으 보면 손실율이 어마어마해 무조건 잘못 계산한거야.
> - 걸러낸 종목카드 아무런 데이터가 없네 missed화면에 개선후보는 오늘 6개인데..

> PM 결정(2026-06-15): 매도체결 사슬 P2~P4 근본수정 **포함**해서 진행.

## 근본 원인 (실데이터로 확정)

### 버그 A — 손실율 비현실적(-50%대) : `_wavg`가 0원 주문을 평균에 합산
- [trade_pairs.py:49 `_wavg`](../../backend/services/engine/trade_pairs.py)는 그룹 내 모든 매수/매도 주문의 가중평균을 낸다.
- **price=0(미체결·submitted) 주문도 `total_amount += 0×qty`, `total_qty += qty`로 합산** → 분모만 커져 단가가 절반으로 붕괴.
- 증거(395750): 6/12 매도 체결 (24,827×530) + 6/15 매도주문 price=0 qty=529(생성시점 미취소) → `(24827×530+0×529)/1059 ≈ 12,428` = 저장된 sell_price 12,425. pnl_pct -50.09%.
- false_positive_cases는 **생성 시점 스냅샷을 영속**하므로, 그 시점 미체결 0원 주문이 평균을 오염시키면 손실율이 영구 박제됨. (현재 재계산값은 -0.27%로 정상 — 그 주문이 cancelled된 후라서)

### 버그 B — Daily Results 승/패 2/4 : trade_pairs(SSOT) 미사용, 동일날짜·비가중·심볼당 1승패
- [trading_monitor.py:900~933](../../backend/api/routes/trading_monitor.py)는 **같은 trade_date 안의** 매수·매도만 묶어 `단순평균 매도가 > 단순평균 매수가`면 1승, 아니면 1패 (심볼당 1건).
- 결과: 99 trades가 동일날짜 매수·매도 동시존재 6심볼로 붕괴 → 2/4. 전일 매수→당일 매도(이월) 건은 `if not buys: continue`로 전량 누락.
- review-audit은 날짜초월 trade_pairs(9건)를 쓰므로 **두 화면 숫자가 불일치** → "하나도 안맞아".

### 버그 C — 걸러낸 종목 카드 빈값 : 복기와 Missed 화면의 소스 불일치
- 복기 BLOCK3 [_nlMissed](../../backend/static/js/screens/console-review.js)는 `review-audit.missed_entries` + `daily_plan.excluded_symbols`만 읽음 → 6/15 둘 다 0.
- Missed Entries 화면은 `shadow-trading`(125행) + `missed-opportunity` 병합 → 개선후보 6건.
- review-audit이 missed_opportunities/shadow_trades 소스를 보지 않음.

## 구현 범위

- [ ] **A1** `_wavg`에서 effective price ≤ 0 주문 제외 (가중평균 오염 차단) — 핵심 근본수정
- [ ] **A2** 6/15(및 영향 구간) false_positive_cases 재생성 — 오염된 영속 손실율 정정
- [ ] **B1** daily-results 승/패를 trade_pairs(SSOT) 기반 완료쌍으로 산출 — review-audit과 일치
- [ ] **C1** review-audit '걸러낸 종목'에 missed_opportunities/shadow 소스 합류 (Missed 화면과 동일 기준)
- [ ] **검증** scripts/verify_0615.py + 표본 대조(승패·손익률·걸러낸 건수 3화면 일치)

## 변경 파일 목록

| 파일 경로 | 변경 유형 | 변경 이유 |
|-----------|-----------|-----------|
| `backend/services/engine/trade_pairs.py` | 수정 | A1: `_wavg` 0원 주문 제외 |
| `backend/api/routes/trading_monitor.py` | 수정 | B1: 승/패를 trade_pairs 기반으로 |
| `backend/services/engine/review_audit.py` | 수정 | C1: 걸러낸 종목 소스 합류 |
| (스크립트/일회성) false_positive 재생성 | 실행 | A2: 오염 데이터 정정 |
| `backend/static/js/screens/console-review.js` | 수정(소) | C1 표시 보정 시 |

## 요구사항 대조표

| 요구사항 | 계획 반영 | 비고 |
|----------|-----------|------|
| 6/15 2/4 안맞음 | ✓ B1 | trade_pairs SSOT로 통일 |
| 손실율 비현실적 | ✓ A1+A2 | 코드(재발방지)+데이터(과거정정) |
| 걸러낸 종목 빈값 vs missed 6건 | ✓ C1 | 소스 합류 |
| 매도체결 사슬 근본수정 포함 | ✓ A1 | 0원/미체결 오염이 사슬 잔재의 핵심 증상 |

## 리스크 / 검증

- A1은 trade_pairs를 쓰는 **전 화면(복기·통계·당일손익·학습)**에 영향 → 회귀 위험 큼. verify_0615 + 표본 대조 필수.
- A2 재생성은 idempotent해야 함(중복 INSERT 금지) — 기존 6/15 행 삭제 후 재생성 또는 UPSERT 확인 필요.
- 적용 전 Codex 디스패치 시 [[feedback-codex-dispatch-db-safety]] 따라 **서버 중지 후** DB 쓰기.

## 완료 기준

- [ ] 3개 화면(daily-results / review-audit / missed)의 승패·손익률·걸러낸 건수 정합
- [ ] 6/15 손실율이 현실값(-0.2~-1.5%대)으로 표시
- [ ] 미체결 0원 주문 존재 시에도 단가 오염 없음 (단위 테스트)
- [ ] Playwright E2E 통과 / 빌드 에러 0
