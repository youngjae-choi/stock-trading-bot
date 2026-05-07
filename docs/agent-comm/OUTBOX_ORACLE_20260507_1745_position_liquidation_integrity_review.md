# OUTBOX_ORACLE - 2026-05-07 17:45 KST - 포지션/청산/체결 정합성 리뷰

## 담당

- Oracle / Codex CLI

## 준수 사항

- 코드/설정 파일 수정 안 함.
- git commit 실행 안 함.
- 매수/매도/청산/주문 API 호출 안 함.
- `/api/v1/orders/*` POST, `/api/v1/kis/order/*`, `/api/v1/decision/activate` 호출 안 함.
- 실제 S1~S11 실행 안 함.
- 외부 LLM/KIS 호출 안 함.
- 단, 요청된 결과 보고 파일만 작성함.

## Findings

### P1 - `submitted` buy를 실보유 포지션으로 간주해 DB fallback 청산 주문을 낼 수 있음

- 위치: `backend/services/engine/position_integrity.py:17`, `backend/services/engine/position_integrity.py:124`, `backend/services/engine/position_integrity.py:246`
- 영향:
  - `_ACTIVE_BUY_STATUSES`에 `submitted`가 포함되어 있고, `load_db_open_positions()`가 이 수량을 그대로 EOD 청산 대상 포지션으로 반환한다.
  - fills/KIS 잔고 확인 없이 buy submitted만 있는 종목도 서버 재시작 후 DB fallback에서 보유 포지션으로 취급된다.
  - 현재 DB 기준 2026-05-04는 buy `submitted` 11건, fills 0건인데도 새 helper는 open position 11개, 총 9441주를 청산 대상처럼 판단한다.
  - 이는 "체결 미검증 상태를 숨기지 않는다"는 목적과 달리, 미체결 가능성이 있는 주문을 실제 보유로 간주해 S9 주문성 API 호출 위험으로 이어질 수 있다.
- 수정 제안:
  - 청산 주문 대상 net position은 `filled`/검증된 `partial_fill` 및 fills 수량 기준으로만 계산한다.
  - `submitted` buy는 `pending_buy_orders` 또는 `unverified_buy_orders`로 별도 경고하고, 자동 EOD sell 대상에서는 제외한다.
  - fills 테이블이 비어 있거나 KIS 잔고 대조가 없으면 `requires_manual_balance_check` 같은 상태를 반환해 S9가 주문 호출 전에 멈추도록 한다.

### P1 - S10/Review PnL 검증이 현재 거래일 주문과 무관한 fills만 있어도 `verified`가 될 수 있음

- 위치: `backend/services/engine/position_integrity.py:395`, `backend/services/engine/position_integrity.py:399`, `backend/services/engine/position_integrity.py:425`
- 영향:
  - `fills_by_order`를 전체 fills 테이블에서 읽고, 현재 `trade_date` 주문 id와 조인하지 않는다.
  - 현재 거래일 주문이 `filled` 상태지만 해당 order_id의 fill row가 없어도, 다른 날짜/다른 주문의 fills가 하나라도 있으면 `pnl_status='verified'`, `pnl_source='fills'`가 된다.
  - temp sqlite 재현에서 2026-05-07 `filled` 주문 1건의 fills가 없고, 2026-05-06의 다른 fill 1건만 넣었을 때 `summarize_order_integrity('2026-05-07')`가 `verified`를 반환했다.
- 수정 제안:
  - fills는 현재 거래일 `trading_orders.id` 목록으로 제한해 조회한다.
  - `filled`/`partial_fill` 주문마다 대응 fill row가 있는지, fill quantity 합계가 주문 수량과 맞는지 검증한다.
  - 하나라도 불일치하면 `pnl_status='unverified'`, `pnl_source='fills_incomplete'`와 상세 warning을 반환한다.

### P2 - 동일일 net 음수/중복 매도 이상이 Review warning에 구조적으로 드러나지 않음

- 위치: `backend/services/engine/position_integrity.py:137`, `backend/services/engine/position_integrity.py:246`, `backend/services/engine/position_integrity.py:417`
- 영향:
  - 현재 DB 2026-05-07은 `036930` buy 18 / sell 36, `050890` buy 122 / sell 244로 sell_qty가 buy_qty의 2배다.
  - 새 중복 매도 guard는 앞으로의 추가 주문은 막지만, 이미 발생한 `net_qty < 0` 또는 `sell_count > 1` 이상을 별도 integrity warning으로 노출하지 않는다.
  - `load_db_open_positions()`는 `net_qty <= 0`이면 바로 continue하여 `skipped`에도 남기지 않는다.
  - Review는 generic "체결/손익 검증 미완료"와 "주문번호 없음"만 보여주므로, PM/운영자가 "이미 중복 청산 주문이 2개 나갔다"는 위험을 명확히 보기 어렵다.
- 수정 제안:
  - `summarize_order_integrity()`에 `net_negative_positions`, `duplicate_sell_orders`, `sell_qty_exceeds_buy_qty`를 추가한다.
  - S9/Review system_alert에도 `risk_guard` 또는 `duplicate_liquidation` 경고를 남긴다.
  - `load_db_open_positions()`는 `net_qty <= 0`이어도 active submitted sell 또는 net negative면 skipped/anomaly 목록으로 반환한다.

## 통과 확인

- PASS: `.venv/bin/python -m compileall -q backend`
  - repo 내 pycache 생성을 피하기 위해 `PYTHONPYCACHEPREFIX=/tmp/codex_pycache_position_review`로 실행.
- PASS: `git diff --check`
- PASS: 외부 호출 없는 temp sqlite/monkeypatch smoke
  - buy 10 + sell submitted 10: restart restore skip.
  - buy 10 + sell filled 4: net 6 restore.
  - 인메모리 포지션 + 기존 submitted sell: EOD 중복 청산 skip, `order_cash` 미호출.
  - sell 응답 주문번호 없음: `submitted_without_order_no`, `uncertain=True` 저장.
  - DB net closed: 주문 호출 전 `net_position_closed` skip.
  - Review submitted-only 주문 및 전일 residual 탐지.
- PASS: temp sqlite legacy migration smoke
  - 기존 `daily_review_reports`에 `pnl_status`, `pnl_source`, `integrity_warnings`, `legacy_residual_positions` 추가 확인.
  - 기존 `daily_trade_summary`에 `pnl_status`, `pnl_source`, `integrity_warnings` 추가 확인.
- FAIL 재현: S10 PnL false verified smoke
  - 현재 거래일 `filled` 주문에 fill이 없고 다른 날짜 fill만 있는 경우 `verified`가 반환됨.

## 현재 DB 기준 예상 판단

읽기 전용 `mode=ro`로 `/home/young/repos/stock-trading-bot/data/stock_trading_bot.sqlite3`를 확인했다.

### 2026-05-04

- `trading_orders`: buy failed 9건 qty 0, buy submitted 11건 qty 9441, sell 0건.
- fills: 해당 trading order 기준 0건.
- 새 helper `load_order_net_positions('2026-05-04')`: 11개 종목 모두 `buy_qty > 0`, `sell_qty=0`, `net_qty > 0`.
- 새 helper `load_db_open_positions('2026-05-04')`: 11개 open position 반환.
- `summarize_order_integrity('2026-05-04')`: `pnl_status=unverified`, `pnl_source=incomplete_orders`, submitted-only 11건.
- Oracle 판단: 현재 helper는 5/4 잔여를 탐지하지만, fills 없는 submitted buy를 자동 청산 대상처럼 반환하는 점이 P1 위험이다.

### 2026-05-07

- `trading_orders`: buy submitted 2건 qty 140, sell submitted 4건 qty 280.
- fills: 해당 trading order 기준 0건.
- 종목별 net:
  - `036930`: buy 18, sell 36, net -18, submitted sell 2건.
  - `050890`: buy 122, sell 244, net -122, submitted sell 2건.
- 새 helper `load_db_open_positions('2026-05-07')`: open position 0개, skipped 0개.
- `summarize_order_integrity('2026-05-07')`: `pnl_status=unverified`, `pnl_source=incomplete_orders`, submitted-only 6건, 주문번호 없는 주문 2건, legacy residual warning 포함.
- `detect_legacy_residual_positions('2026-05-07')`: 2026-05-04 잔여 11개 종목 탐지.
- Oracle 판단: 신규 guard가 배포되어 있었다면 같은 종목의 두 번째 EOD sell은 주문 호출 전에 차단됐을 가능성이 높다. 그러나 현재 DB에 이미 존재하는 net negative/중복 sell 상태는 별도 위험 항목으로 충분히 드러나지 않는다.

## 최종 판단

- 배포 가능 여부: **불가**
- 이유:
  - P1: `submitted` buy를 실보유 포지션으로 간주해 S9 DB fallback 청산 주문 대상이 될 수 있다.
  - P1: S10/Review가 fills 검증을 현재 거래일 주문 id 기준으로 하지 않아 `verified`를 허위로 반환할 수 있다.
  - P2: 현재 DB의 2026-05-07 중복 sell/net negative 상태를 명확한 integrity anomaly로 노출하지 못한다.

## 남은 위험

- KIS 잔고 read-only 대조를 하지 않았으므로 실제 계좌 보유/미체결/접수 상태는 확인 필요.
- `submitted_without_order_no`는 실제 접수와 실패를 구분할 수 없어, 운영자가 KIS 주문 상태를 별도로 확인해야 한다.
- 현재 DB의 2026-05-07 중복 sell 4건 중 2건은 주문번호가 있고 2건은 주문번호가 없다. 실제 주문 상태 확정 전에는 자동 청산/재시작 복원/손익 확정 모두 보수적으로 막아야 한다.
