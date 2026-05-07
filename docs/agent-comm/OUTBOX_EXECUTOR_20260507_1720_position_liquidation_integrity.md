# OUTBOX_EXECUTOR - 2026-05-07 17:20 KST - 포지션/청산/체결 정합성 P1 수정

## 담당

- Executor / Codex CLI

## 준수한 금지 사항

- git commit 실행 안 함.
- 매수/매도/청산/주문 API 호출 안 함.
- 실제 S1~S11 실행 안 함.
- decision activate 실행 안 함.
- 외부 LLM 호출 안 함.
- KIS 주문성 API 호출 안 함.
- 검증은 compile/diff check/temp sqlite/monkeypatch smoke만 수행함.

## 변경 파일 목록

- `backend/services/engine/position_integrity.py` 신규
- `backend/services/engine/decision_engine.py`
- `backend/services/engine/eod_liquidation.py`
- `backend/services/engine/order_executor.py`
- `backend/services/engine/daily_summary.py`
- `backend/services/engine/review_audit.py`
- `backend/services/db.py`
- `docs/agent-comm/OUTBOX_EXECUTOR_20260507_1720_position_liquidation_integrity.md` 신규

## 구현 요약

### 1. 재시작 포지션 복원 net position화

- `position_integrity.load_order_net_positions()`를 추가해 `trading_orders`의 active buy/sell 수량을 symbol별로 집계한다.
- `_restore_positions_from_db()`가 더 이상 오늘 buy 주문만 보고 복원하지 않는다.
- buy qty에서 sell submitted/filled/partial/uncertain qty를 차감해 `net_qty`를 계산한다.
- `net_qty <= 0` 또는 sell submitted/uncertain 존재 시 복원하지 않는다.
- 복원/스킵 로그에 `buy_qty`, `sell_qty`, `net_qty`, `skipped_reason`을 남긴다.
- sell cancelled/failed/blocked는 차감하지 않는 정책으로 분리했다.

### 2. S9 중복 매도 및 잔여 포지션 경고

- S9가 인메모리 포지션을 쓰더라도 같은 trade date에 unverified sell submitted/uncertain 주문이 있으면 EOD 매도를 스킵한다.
- 인메모리 포지션이 없을 때 DB fallback은 기존 buy-only가 아니라 DB net position 기준으로 대상화한다.
- 전일 전략 주문 이력의 net residual position을 `legacy_residual_positions`/`orphan_positions`로 반환하고 `system_alerts`에 `risk_guard` 경고를 남긴다.
- S9 반환 summary에 `submitted`, `uncertain`, `skipped_duplicate`, `failed` count를 추가했다.

### 3. EOD 매도 성공 조건 강화

- `OrderExecutor.execute_sell()`에서 주문 호출 전 중복 submitted/uncertain sell 주문을 DB로 차단한다.
- sell filled로 이미 DB net qty가 0 이하인 stale 포지션도 주문 호출 전 `net_position_closed`로 스킵한다.
- KIS 응답에 `kis_order_no`가 없으면 `submitted_without_order_no`로 저장하고 `ok=False`, `uncertain=True`로 반환한다.
- 주문번호 없는 sell은 인메모리 포지션을 제거하지 않아 “완전 청산 완료”로 보이지 않게 했다. 이후 중복 주문은 DB guard가 막는다.

### 4. S10/Review 체결 미검증 표시

- `summarize_order_integrity()`를 추가해 submitted-only 주문, 주문번호 없는 주문, fills 부재, 전일 잔여를 집계한다.
- `daily_trade_summary`에 `pnl_status`, `pnl_source`, `integrity_warnings` 컬럼을 추가/마이그레이션한다.
- `daily_review_reports`에 `pnl_status`, `pnl_source`, `integrity_warnings`, `legacy_residual_positions` 컬럼을 추가/마이그레이션한다.
- S10 Review 결과와 조회 payload가 submitted-only 주문을 `pnl_status=unverified`, `pnl_source=incomplete_orders`로 노출한다.
- 체결/손익 검증 미완료 상태는 `system_alerts`에 `fill_missing` 경고로 남긴다.

## 테스트 결과

- PASS: `.venv/bin/python -m compileall -q backend`
- PASS: `git diff --check`
- PASS: 외부 호출 없는 temp sqlite/monkeypatch smoke
  - buy 10 + sell submitted 10: restart restore 안 됨.
  - buy 10 + sell filled 4: net 6만 restore 됨.
  - 인메모리 포지션이 있어도 sell submitted 있으면 S9 EOD 중복 매도 스킵.
  - sell 결과에 order number 없음: `submitted_without_order_no` 저장 및 uncertain 집계.
  - DB net qty closed 상태의 stale sell 요청: 주문 호출 전 `net_position_closed` 스킵.
  - Review submitted-only 주문: `pnl_status=unverified`, warning 생성.
  - 전일 buy 잔여: `legacy_residual_positions` 탐지.

## 남은 위험

- 실제 KIS 잔고 read-only 대조 및 잔고 기반 자동 청산은 이번 범위에서 구현하지 않았다. 전일 잔여는 DB 전략 주문 이력 기반으로 탐지/경고한다.
- `submitted` 주문을 실제 filled/cancelled/rejected로 확정하는 fill poller 고도화는 별도 P1 후속이 필요하다.
- 주문번호 없는 sell은 실제 KIS에 접수됐을 가능성과 실패했을 가능성을 구분할 수 없다. 현재는 중복 방지를 위해 uncertain 상태로 보수 처리한다.
- DailySummary의 realized PnL 산식 자체는 fills 기반으로 완전 재작성하지 않았고, 이번 수정은 미검증 상태를 숨기지 않는 최소 보강이다.

## Oracle 리뷰 포인트

- `position_integrity.py`의 active status 정책이 운영 정책과 맞는지 확인 필요.
- sell `submitted_without_order_no`를 차감/중복 방지 대상으로 보는 보수 정책이 적절한지 확인 필요.
- S9 `legacy_residual_positions`가 DB 주문 이력 기반이라 KIS 실제 잔고와 차이가 날 수 있음을 Review/운영 화면에서 충분히 드러내는지 확인 필요.
- `daily_review_reports`/`daily_trade_summary` 신규 컬럼 migration이 기존 운영 DB에서 정상 적용되는지 재확인 필요.
