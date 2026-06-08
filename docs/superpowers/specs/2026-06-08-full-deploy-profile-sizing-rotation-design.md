# 풀예수금·Profile 비중 사이징·적극 교체매매 — 설계서 v0.1

> 탐색 엔진(모의 전용)이 예수금을 하루 종일 풀로 굴리며 활발히 거래해 전략 수립용 데이터를 모으도록,
> 사이징·배포·재활용·교체 모델을 재배선한다. (PM 요청 2026-06-08)

## 왜 필요한가 (WHY)
현재 탐색 사이징은 **예수금/40 균등분할 + 보유 5종목 게이트**라, profile 비중·풀배포·재활용·교체가
전부 무력화돼 **실제 예수금의 ~12%만 투입**되고 있다. PM은 하락장·상승장 무관하게 예수금을 최대 95%까지
풀로 굴리고, 매도로 생긴 룸을 즉시 재매수로 채우며, 치고 오르는 종목으로 적극 교체해 **활발한 거래 데이터**를
모아 전략을 세우려 한다. 적용 범위는 **exploration_mode=true (모의계좌 전용)**.

## 요구사항 (PM 발화 기반)
1. 예수금 **최대 95% 풀 배포** (시장 방향 무관).
2. 종목당 **Risk Profile 비중대로** 매수 (균등분할 금지).
3. 매도로 룸이 생기면 **재매수 → 하루 종일 풀가동·활발한 거래**.
4. **적극적 교체매매**: 치고 오르는 대기종목 ↔ 힘 빠지는 보유종목 자동 스왑 (손절 허용).

## 확정된 정책 (PM 승인 2026-06-08)
- 종목당 비중 = **현행 Risk Profile Pack(profile-v1.0) 유지**: LOW_VOL 15% · MID_VOL 12% · HIGH_VOL 8% · THEME_SPIKE 5%.
- 교체 = **자동 스왑 + 손절 허용** (대기 후보 점수가 보유 종목보다 임계 이상 높으면, 손실 중이어도 매도→스왑).
- **배포 목표율 95%, 버퍼 5%** (수수료·미체결·슬리피지 여유).
- **교체 적극성 시작값**: 점수차 임계 **+0.15**, 일일 교체 상한 **20회**, 같은 종목 재교체 쿨다운 **30분**. (데이터 보고 튜닝)
- 적용 범위 = **exploration_mode=true (모의 전용)**. 실계좌 전환 시 자동 비활성, 기존 보수 사이징 사용.

## 현재 구현 자산 (재사용)
- Profile별 비중(`max_position_rate`) 이미 정의됨 (risk_profile_packs profile-v1.0).
- `order_executor._calc_qty(deposit, pct, price)` — profile %-기반 사이징 헬퍼(현재 폴백만).
- `replacement_signal.evaluate_replacement_signals` — 후보 vs 보유 점수비교 + 신호생성/알림(실행은 안 함).
- `decision_engine.on_position_slot_opened` — 매도 후 빈 슬롯 훅.
- 실시간 가용현금 = KIS balance `ord_psbl_cash`, 총자산 `tot_evlu_amt`.

## 제안 모델

### A. Profile 비중 사이징 (균등분할 대체)
- 후보의 `profile_assigned`(S5 Daily Plan 배정) → profile `max_position_rate`(15/12/8/5%).
- 목표 매수금액 `target = tot_evlu_amt × profile_rate`.
- 실제 매수금액 `spend = min(target, deployable_now)`, `qty = floor(spend / price)`.
- exploration_mode일 때 `order_executor`의 균등분할(`_calc_budget_qty`) 대신 이 경로 사용.

### B. 총 95% 배포 게이트 (보유수 게이트 대체)
- `deployable_now = ord_psbl_cash − (tot_evlu_amt × 0.05 버퍼)`.
- order_preflight: 기존 `보유수 ≥ max_positions` 차단을 **`배포액 ≥ 총자산×0.95` 차단**으로 전환.
- 보유 종목 수는 비중 합이 95%에 도달할 때까지 자연 증가(고정 상한 없음, 안전 ceiling만 높게 유지).

### C. 자본 재활용 (하루 종일 풀가동)
- 사이징을 **실시간 ord_psbl_cash** 기준으로 → 매도 시 현금↑ → 다음 매수조건 충족 종목 즉시 재매수.
- 기존 `on_position_slot_opened` 훅 + 틱/장중 재선별 신호평가로 빈 룸을 계속 채움.

### D. 적극 교체매매 (신호 → 자동 실행)
- `evaluate_replacement_signals`를 **자동 실행**으로 승격.
- 조건: 가용현금이 부족(거의 풀배포)한 상태에서, **대기 후보 점수 − 보유 종목 현재 점수 ≥ 교체임계**이면 스왑.
- 스왑 = 약한 보유 매도(손절 허용) → 후보 매수(Profile 비중 사이징).
- churn 방지: 종목별 쿨다운, 일일 교체 상한, 최소 점수차 임계 (기본값 제안, PM 튜닝).

## 상태별 UI & 로그
- 매수 사이징 로그: `[S7] Profile비중 사이징 symbol=.. profile=HIGH_VOL rate=0.08 spend=.. qty=..`.
- 배포율 표시: Trading Monitor에 **배포율(투입/총자산 %)** 카드 추가 → 풀가동 가시화.
- 교체 실행 로그/Alert: `교체 실행: SELL 약한보유(점수x) → BUY 강한후보(점수y)`.

## 엣지케이스 & 예외처리
- 예수금 부족: `qty=0`이면 스킵(에러 아님).
- 95% 초과 방지: 주문마다 실시간 ord_psbl_cash 재확인(순차 처리), 동시 초과 배포 차단.
- 5% 버퍼: 수수료·미체결·슬리피지 여유.
- 교체 손절 확정: 적극 모드 허용하되 EV 태깅(selection_source/교체여부)으로 성과 추적 → EV 가지치기로 수렴.
- THEME_SPIKE `reentry_allowed=false`: 당일 재진입 금지 정책 존중(교체 매도 종목 당일 재매수 제한).
- 15:10/15:20 신규매수 금지·청산 시간 게이트 기존 유지.
- **exploration_mode=false(실계좌 전환)**: 이 모델 비활성, 기존 보수 사이징 사용.

## 기술 구현 힌트 (변경 예상 파일)
- `exploration_gate.py` / `order_executor.py`: Profile 비중 사이징 경로(A), 실시간 cash 기준(C).
- `order_preflight.py`: 95% 배포 게이트(B), 보유수 게이트 완화.
- `replacement_signal.py` + `decision_engine.py`: 교체 신호→자동 실행(D), 슬롯훅 재활용.
- settings: `exploration.deploy_target_rate`(0.95), `replacement.score_gap_threshold`, `replacement.max_swaps_per_day`, `replacement.cooldown_min`.
- `account/trading_monitor`: 배포율 카드.

## 검토 결과 (PM 승인 2026-06-08)
- 배포 95%+버퍼 5%, 교체 임계 +0.15/20회/30분, 모의 전용 — **3가지 모두 승인됨**. (위 "확정된 정책" 참조)

## 완료 기준
- exploration_mode에서 예수금 ~95%까지 Profile 비중대로 배포, 매도 시 재배포 확인.
- 교체 조건 충족 시 자동 스왑 실행(손절 포함) + EV 태깅.
- TDD(사이징·배포게이트·교체판정), 회귀, E2E. docs/manual 갱신.
- 배포율·교체 내역 UI 가시화.
