# KIS↔DB 수량 드리프트 정합 — 개발계획서 v0.1

> 유령 매도(매일 ~30%)·이월손익 표시 아티팩트(-4.5M)의 공통 뿌리 =
> **DB 보유수량이 KIS 실보유보다 상향 드리프트**. [[kis-db-drift-fix]](6/25)의 미완 후속.

## 원본 요구사항 (PM 발화 그대로 인용)

> "어떤 종목은 손절라인을 넘어서도 청산을 안하던데.. 무슨이유지?"
> "이거 8월 10일 거래 내역이 왜 안쌓이지?"
> "둘다 병렬로 조사해줘" (→ (A) 유령 주문 생성 지점, (B) S10 이월 손익 계산)
> "계발계획서 작성해."

**조사로 확정된 근본원인**(원본 요구의 근거):
- `order_executor.execute_sell`(order_executor.py:651-680): KIS가 HTTP 200 + ODNO 누락 = 대부분 **업무거부(매도가능수량부족)**. 봇이 **KIS에 없는 수량을 매도 시도**. 증거: 8/10 0039P0 DB net **2,446주** vs KIS 실보유 **0주**.
- 8/10 매도주문 71건 중 **cancelled 21건(~30%)** = `intraday_reconcile_no_kis_order`로 사후 취소.
- `position_cost_basis` 로트가 전부 `source=auto_imported`(KIS 스냅샷 재구성) + **KIS 매도 시 차감 경로 없음** → FIFO가 오늘 매도를 스테일 로트에 매칭 → 이월 **-4.5M 종이손익**(실현 -486K·자본변화 **+1.25%**와 불일치).
- `execute_sell:702`: uncertain 매도 시 `remove_position` → 실제 일부 거부면 **진짜 보유분이 손절 감시에서 이탈**.

## 구현 범위

- [ ] **(A) 매도 KIS-실보유 상한 게이트** — 매도 제출 전 KIS 실보유를 sellable qty의 단일 진실로. 부풀린 수량 매도 시도 자체를 차단(거부·유령 매도 소멸). 게이트: `engine.sell_kis_qty_clamp_enabled`.
- [ ] **(B) cost_basis 원장 KIS 정합** — KIS 실보유 0/축소 시 스테일 로트 close/decrement. FIFO가 유효 로트만 매칭 → 이월손익 아티팩트 소멸. 게이트: `engine.costbasis_kis_reconcile_enabled`.
- [ ] **(A-2) uncertain 매도 remove_position 재검토** — 거부 가능성이 있으면 감시 유지(손절 이탈 방지). rt_cd 기반으로 "실제 접수"만 remove.
- [ ] **(관측) drift율 알림** — Ops Watchdog에 일일 `취소매도/전체매도` 비율 노출(재발 조기감지).

## 변경 파일 목록

| 파일 경로 | 변경 유형 | 변경 이유 |
|-----------|-----------|-----------|
| `backend/services/engine/order_executor.py` | 수정 | (A) execute_sell 단일 길목에 KIS 실보유 clamp/skip. (A-2) uncertain 시 remove_position 조건화 |
| `backend/services/engine/order_reconciliation.py` | 수정 | `_kis_held_qty_map()`를 공용 모듈로 승격(중복 정의 residual_reconciliation.py와 통합) |
| `backend/services/engine/position_cost_basis.py` | 수정 | `reconcile_to_kis(held_map, trade_date)` 추가 — KIS 실보유 기준 로트 close/decrement |
| `backend/services/engine/residual_reconciliation.py` | 수정 | 정합 시 cost_basis 로트를 KIS 실보유로 동기화 호출 |
| `backend/services/engine/review_audit.py` | 수정 | (B) 이월 짝을 KIS 검증 잔고와 대조 — 미검증 로트는 이월표에서 제외/라벨 |
| `system_settings` (DB, 서버 중지 상태 삽입) | 신규 | `engine.sell_kis_qty_clamp_enabled`·`engine.costbasis_kis_reconcile_enabled` (기본 게이트) |
| `tests/unit/test_sell_kis_clamp.py` 등 | 신규 | clamp·cost_basis 정합·carried 대조 TDD |

## 요구사항 대조표  ← 핵심

| 요구사항 항목 | 계획서 반영 여부 | 비고 |
|---------------|-----------------|------|
| "손절선 넘어도 청산 안 함" 근본 해결 | ✓ 반영됨 | (A) clamp로 부풀린 매도 차단 + (A-2) 감시 이탈 방지 |
| 유령 매도 ~30% 제거 | ✓ 반영됨 | (A) KIS 실보유 진실화 = 매도가능수량부족 거부 소멸 |
| 화면 손익 왜곡(이월 -4.5M) 제거 | ✓ 반영됨 | (B) cost_basis 로트 KIS 정합 → FIFO 아티팩트 소멸 |
| 8/10 거래 표시 문제 | ✓ 별건 완료 | dbea4ba(날짜필터) 이미 수정·배포 |
| 재발 방지 | ✓ 반영됨 | drift율 관측 알림 + 게이트/롤백 스위치 |

## 추가 제안 항목 (PM 요청 외 — 승인 필요)

- **KIS 실보유 조회 캐시(TTL 10~30s)** : 매 매도마다 KIS 호출 시 API 폭주·손절 지연 위험 → 짧은 TTL 캐시로 clamp. *(권장)*
- **drift율 Ops 알림** : 일일 취소매도율이 임계 초과 시 Alert Center 경고. *(권장)*

## 검토 요청 (PM 결정 필요)

1. **(A) clamp 위치** — 두 안 중 택1:
   - **1a. execute_sell 길목 + TTL 캐시**(권장) : 단일 지점, 즉효, 핫패스에 캐시로 지연 최소화.
   - **1b. 주기적 position sync에서 manager qty를 KIS로 하향 정합** : 근본적이나 sync 주기 의존, 핫패스 무변경.
   - → **1a+1b 병행**(길목 방어 + 근본 정합)을 권장하나 범위 확대. **1a만 먼저** 갈지 결정 요청.
2. **게이트 기본값** — 신규 설정 2개를 기본 **ON**(즉시 정합)으로 배포할지, **OFF**(관측 후 수동 ON)로 안전하게 갈지.
3. **(B) 우선순위** — (A)만 먼저 배포하고 (B)는 다음 웨이브로 분리할지(표시 문제라 후순위 가능).

## 완료 기준

- [ ] 신규 TDD 통과 (clamp: KIS<요청 시 clamp/skip / cost_basis: KIS=0 시 로트 close / carried: 미검증 제외)
- [ ] 회귀 테스트 통과 (`tests/unit/test_review_equity_line.py` 등 손익 집계 무변)
- [ ] `python -m py_compile` / pyright 에러 0
- [ ] 서버 재기동 **forward-only**(장 마감 후, PM 승인) — [[kis-db-drift-fix]] 원칙
- [ ] 배포 후 **다음 거래일 cancelled sell율 하락** 확인(관측 지표)
- [ ] `docs/manual/` 정합 로직 문서 반영

## 구현 노트 (v0.1 착수 시 발견 — 계획 조정)

- **1b(manager↔KIS 하향 동기화)는 이미 존재함** — `decision_engine.py:369-402`의 S6 동기화 루프가
  KIS 잔고 미존재/수량 0 → `remove_position`, 있으면 `update_position_quantity(KIS qty)`로 이미 하향 정합.
  → **중복 구현하지 않음.** 남은 진짜 갭은 **1a(제출 시점 clamp)** — 주기적 sync 사이에 stale qty로
  나가는 매도를 최후 방어선에서 막는 것.
- **Wave 1 실구현 = (A) 1a + (A-2)만**:
  - **1a**: `order_executor.py` — `execute_sell` 제출 직전 KIS 실보유 clamp/skip.
    모듈 헬퍼 `_cached_kis_held_qty`(TTL 15s 캐시, `order_reconciliation._kis_held_qty_map` 재사용),
    게이트 `_sell_clamp_enabled`(기본 ON), 조회 실패 시 fail-open.
  - **A-2**: uncertain 매도 시 `remove_position`을 rt_cd 기반 조건화 — 업무거부(미접수)면 포지션 보존.
  - 테스트: `tests/unit/test_sell_kis_clamp.py` 6종 + 기존 `test_sell_resilience.py` 회귀.
- **배포 게이트 설정**: `engine.sell_kis_qty_clamp_enabled` 기본값을 코드에서 True로 두어 설정이 없어도 ON.
  (원복은 설정을 false로.)

## 리스크 / 아웃오브스코프

- **리스크**: 금융 핵심경로(매도) 수정 — 게이트+롤백 스위치로 즉시 원복. clamp 과도 시 정당 매도 차단 위험 → KIS 실보유 조회 실패 시 **fail-open**(기존 동작 유지, 절대 차단 안 함).
- **아웃오브스코프**: 유령 **매수** 근본(auto_import가 KIS 미체결 매수를 흡수하는 경로), P2-a 반등 진입 트리거, R:R 튜닝 — 별건.

---

# Wave 2 (B) — 이월손익 정확화 (A-full) 개발노트

## 재검증으로 뒤집힌 전제
계획서 v0.1의 "cost_basis 스테일 로트" 가설은 **틀림**(검증). 실제 원인:
- `get_trade_pairs`가 **trade_date−7일 범위를 종목별 가중평균 한 짝으로 뭉침** → `_pair_buy_date`=최소매수일≠오늘 → **이월 오분류**. 매드업 8/03~8/10 매수 17,846주@wavg 8,717 → 복기 "8,375" 재현.
- **모든 DB net 소스가 드리프트 오염**: trading_orders·fills(0039P0 fills net +7,877인데 KIS 0)·cost_basis 전부 KIS 실보유와 불일치.
- 신뢰 소스는 **daily_capital_baseline 총액**(KIS 검증)뿐 — **종목별 스냅샷은 애초에 캡처된 적 없음**(positions·account_snapshots 0행, 캡처 잡 미구축).

## A-full 결정 (PM): EOD/장전 KIS 보유 스냅샷 잡 신설 → 종목별 정확
### Part 1 — 토대 (구현·TDD 5통과)
- 신규 `backend/services/engine/holdings_snapshot.py` + 테이블 `daily_holdings_snapshot(trade_date, norm_symbol PK, qty, avg_price, market_price)`.
- `scheduler.job_capture_capital_baseline`(08:50)에 **동일 balance 재사용** 캡처 연결 → **추가 KIS 호출 0**(토큰 경합 없음). 이 open 스냅샷 = 밤사이 carried-in.
### Part 2 — 이월 섹션 정확화 (구현·TDD 5통과)
- `review_audit._compute_carried_from_snapshot`: 이월 P&L = min(carried_qty, 금일매도량) × (금일 매도가 − KIS 평단).
- 스냅샷 없는 과거일(8/10 등) → `_carried_total_fallback_line`: KIS 검증 **시작 보유주식 총액**만 표기(가짜 종목별 숫자 금지).
- DB 접근은 async `run_review_audit`에서 선계산 → 순수 빌더 `_build_review_markdown`은 `result["carried_snapshot"]`만 렌더(순수성 유지).
- **day_score·realized SSOT 무손상**(day_score는 시그널 기반, _split_carried_pairs는 표시 전용).

## 검증 (Wave 2)
- 신규 TDD `test_holdings_snapshot.py`(5) + `test_carried_snapshot.py`(5) + 회귀 `test_review_equity_line`(갱신).
- **정확도는 스냅샷 첫 캡처(배포 후 첫 거래일 08:50)부터**. 그 전 과거일은 총액 표기.
