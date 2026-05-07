# OUTBOX_EXECUTOR - 2026-05-07 18:00 KST - Position Integrity P1 재수정

## 담당

- Executor / Codex CLI

## 준수 사항

- git commit 실행 안 함.
- 사용자 변경사항 되돌리지 않음.
- 매수/매도/청산/주문 API 호출 안 함.
- `/api/v1/orders/*` POST, `/api/v1/kis/order/*`, `/api/v1/decision/activate` 호출 안 함.
- 실제 S1~S11 실행 안 함.
- 외부 LLM/KIS 호출 안 함.

## 변경 파일 목록

- `backend/services/engine/position_integrity.py`
- `backend/services/engine/review_audit.py`
- `backend/services/engine/daily_summary.py`
- `docs/agent-comm/OUTBOX_EXECUTOR_20260507_1800_position_integrity_p1_fixes.md`

## 구현 요약

### 1. submitted buy 자동 청산 제외

- `load_db_open_positions()`와 restart restore용 `build_restore_position_plan()`이 `submitted` buy를 포지션 수량으로 쓰지 않도록 분리했다.
- 자동 청산/restore용 DB 포지션은 `filled` 주문 수량과 fill row가 있는 `partial_fill` 체결 수량만 사용한다.
- `submitted` buy는 `pending_buy_orders`와 Review warning에 남기며, warning 문구에 “체결 미검증 상태라 자동청산 대상에서 제외”를 명시했다.
- 기존 duplicate sell guard용 `load_order_net_positions()`는 주문 이상 탐지 목적을 위해 active order request 수량 기준을 유지했다.

### 2. PnL verified 조건을 현재 거래일 order_id fill 기준으로 제한

- `summarize_order_integrity()`가 fills를 전체 테이블에서 보지 않고, 현재 `trade_date`의 `trading_orders.id` 목록으로 제한해 조회한다.
- 오늘 `filled`/`partial_fill` 주문마다 matching fill row 존재 여부와 fill quantity 합계가 주문 수량과 일치하는지 확인한다.
- 누락 또는 불일치 시 `pnl_status='unverified'`, `pnl_source='fills_incomplete'`와 `incomplete_fill_orders` 상세를 반환한다.
- 다른 날짜/다른 order_id의 fills만 있는 경우 오늘 Review가 `verified`가 되지 않도록 수정했다.

### 3. net negative / duplicate sell anomaly 노출

- `summarize_order_integrity()` 반환값에 아래 구조를 추가했다.
  - `net_negative_positions`
  - `duplicate_sell_orders`
  - `sell_qty_exceeds_buy_qty`
- Review/Daily summary의 `integrity_warnings`에 순매도 음수, 중복 매도, 매도 수량 초과 warning을 노출한다.
- `run_review_audit()`에서 위 anomaly가 있으면 `risk_guard` system alert도 생성한다.

## 테스트 결과

- PASS: `.venv/bin/python -m compileall -q backend`
- PASS: `git diff --check`
- PASS: 외부 호출 없는 temp sqlite/monkeypatch smoke
  - submitted buy only: `load_db_open_positions()` 0개, Review warning에 자동청산 제외 문구 포함.
  - filled buy only: open position 반환.
  - filled buy 10 / sell filled 4: net 6 반환.
  - 오늘 filled order에 fill이 없고 전일 fill만 있음: `pnl_status=unverified`, `pnl_source=fills_incomplete`.
  - 오늘 filled order에 matching fill 있음: `pnl_status=verified`, `pnl_source=fills`.
  - buy 18 / sell 36: `net_negative_positions`, `duplicate_sell_orders`, `sell_qty_exceeds_buy_qty` 생성.

## 남은 위험

- `filled` 상태 주문은 DB 상태를 신뢰해 DB fallback open position 계산에 포함한다. PnL 확정은 별도로 fills 기준 검증을 요구한다.
- KIS read-only 잔고/미체결 대조는 이번 작업에서 호출 금지였으므로 수행하지 않았다.
- 이미 DB에 저장된 submitted/uncertain 주문의 실제 접수 여부는 운영자가 KIS에서 별도 확인해야 한다.

## Oracle 리뷰 포인트

- `load_db_open_positions()`와 `build_restore_position_plan()`이 submitted-only buy를 자동 청산/restore 대상으로 만들지 않는지 확인 필요.
- `summarize_order_integrity()`의 fills 제한이 현재 거래일 order_id 목록으로 충분히 닫혔는지 확인 필요.
- Review/Daily summary warning이 2026-05-07의 buy 18 / sell 36, buy 122 / sell 244 같은 상태를 PM이 볼 수 있을 만큼 명확히 드러내는지 확인 필요.
