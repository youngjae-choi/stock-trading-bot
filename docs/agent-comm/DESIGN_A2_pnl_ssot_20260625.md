# A2 — P&L SSOT 단일집계 통합 설계 v0.1

## 배경
fills 기반 실현손익 / position entry_price 기반 / 계좌-자본 기반 3종이 서로 달라 화면 불일치(Daily Results 3승/4 vs Review 카드 3승/6·손실4). 근본 원인: **auto_import(KIS 보유 흡수) 포지션은 매수 fill이 없어** fills 기반 손익이 `matched_qty=min(buy,sell)=0`으로 그 거래를 통째로 누락. → 화면마다 다른 경로를 읽어 숫자가 갈림.

## 핵심 설계 결정

### 1) SSOT = 통합 trade-pair 원장 + 원가 보조 테이블
- 거래 결과(실현손익·승패·거래수)의 단일 진실원본은 **`trade_pairs.py`의 페어 원장**.
- 매수 fill 없는 포지션(auto_import·정합)을 위해 **신규 테이블 `position_cost_basis`** (원가 보조 원장) 추가.
- ⚠️ **합성 매수 주문을 `trading_orders`에 넣지 않음** — 무결성 체크(A3) 오염 방지. 별도 원장이 깔끔.

```
position_cost_basis(
  id, symbol, norm_symbol, qty, avg_price,
  source('auto_imported'|'reconciled'|'manual'),
  trade_date, created_at,
  UNIQUE(norm_symbol, trade_date))
```

### 2) 원가 기록 시점 (write)
- `position_manager.add_position`에서 `auto_imported=True`일 때 `upsert_cost_basis(symbol, qty, entry_price=KIS평단, 'auto_imported', today)`.
- `residual_reconciliation`이 실보유 확인 시 `source='reconciled'`로 기록.
- UNIQUE로 idempotent(재기동·재흡수 중복 방지).

### 3) trade_pairs 원가 주입 (read)
- `get_trade_pairs`에서 `buy_qty==0 & sell_qty>0` 그룹은 `get_cost_basis(norm_symbol, sell_date)`로 매수측 보강 → 누락됐던 거래가 손익·승패에 포함.
- 페어에 `cost_basis_source`, `cost_basis_trade_date` 필드 추가(표시·이월 판정용).

### 4) daily_summary 실현손익 writer 교체
- `run_daily_summary`의 구식 주문가 기반 인라인 계산(라인 128-150) 제거 → **trade_pairs 집계로 단일화**. `pnl_source`에 `'fills+cost_basis'` 추가.

### 5) 3종 P&L 분리 유지 (혼동 금지)
| 유형 | 의미 | 출처 | 저장 |
|------|------|------|------|
| 실현(거래별) | 청산 라운드트립 손익(원가보정) | trade_pairs+cost_basis | daily_trade_summary.realized_pnl, day_score |
| 계좌누적(종가-종가) | 시드 대비 총손익 | account_pnl(KIS잔고) | 라이브 |
| 자본변화(intraday) | 개장→마감 자본 변동 | daily_capital | equity_pnl |

### 6) 이월(carryover) 일관화
- cost_basis_trade_date를 `_pair_buy_date`에 흘려, 전일 흡수·당일 매도 포지션을 **이월로 일관 처리**(현재 경로별 상이).

## 변경 범위
- 신규: `position_cost_basis.py`, `tests/unit/test_position_cost_basis.py`
- 수정: `trade_pairs.py`, `position_manager.py`, `daily_summary.py`, `residual_reconciliation.py`, `review_audit.py(_pair_buy_date)`
- 테스트 보강: `test_today_realized_pnl.py`, `test_cross_surface_consistency.py`, `test_daily_score.py`

## 빌드 순서 (TDD, 4단계)
1. cost_basis 모듈(스키마+write) + 단위테스트
2. trade_pairs 원가 주입 + 테스트
3. daily_summary writer 교체 + 테스트
4. 화면 교차일관성 검증(day_score == summary 거래수, get_today_realized_pnl == 페어합)

## 마이그레이션·안전
- 신규 테이블 CREATE IF NOT EXISTS → WAL 하 서버 가동 중 안전. ALTER 없음.
- **forward-only**: 과거 daily_trade_summary 값은 구방식 잔존. 필요 시 S10 재실행으로 해당일 갱신(단 cost_basis는 배포일 이후만 존재).

## 미해결/확인 필요 (PM·구현 시)
- ⚠️ **화면 숫자(3승/4 vs 6·손실4)의 정확한 렌더 필드 확정**: 설계는 day_score(4) vs signal 기반 win/loss(6)로 추정하나, Review 카드가 실제 day_score를 읽는지 win_count를 읽는지 **구현 1단계에서 확정**하고 그 필드가 SSOT를 읽도록 보장해야 함. (이게 사용자 가시 증상이라 반드시 못박아야 함)
- 부분매도/부분체결 시 cost_basis qty는 상한으로만 작용(min 매칭) — 정상.

## 리스크
- daily_summary writer 교체로 과거 숨은 불일치가 드러날 수 있음(pnl_source로 가시화).
- ETN Q접두어 → cost_basis는 norm_symbol 키로 저장/조회 필수.
