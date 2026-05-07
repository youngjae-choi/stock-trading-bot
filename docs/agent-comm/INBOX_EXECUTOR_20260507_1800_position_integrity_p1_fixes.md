# INBOX_EXECUTOR - 2026-05-07 18:00 KST - Position Integrity P1 재수정

## 요청자

Sisyphus

## 담당 페르소나

Executor

## 선행 리뷰

반드시 먼저 읽을 것:

- `docs/agent-comm/OUTBOX_ORACLE_20260507_1745_position_liquidation_integrity_review.md`

## 배경

Oracle 최종 판단은 배포 불가다. P1 2건:

1. `submitted` buy를 실보유 포지션처럼 계산해 fills/KIS 잔고 확인 없이 S9 DB fallback 청산 대상이 될 수 있음.
2. S10/Review PnL 검증이 현재 거래일 주문 id와 무관한 fills만 있어도 `verified`가 될 수 있음.

P2 1건:

- 동일일 net 음수/중복 매도 이상이 Review warning에 구조적으로 드러나지 않음.

## 금지 사항

- git commit 금지.
- 사용자 변경사항 되돌리지 말 것.
- 매수/매도/청산/주문 API 호출 금지.
- `/api/v1/orders/*` POST, `/api/v1/kis/order/*`, `/api/v1/decision/activate` 호출 금지.
- 실제 S1~S11 실행 금지.
- 외부 LLM/KIS 호출 금지.

## 수정 요구

### 1. `submitted` buy는 자동 청산 대상에서 제외

대상: `backend/services/engine/position_integrity.py`, 필요 시 `eod_liquidation.py`, `decision_engine.py`

요구:

- EOD DB fallback/restore용 open position 계산은 `filled`/검증된 `partial_fill`/fills 기준 수량만 사용한다.
- `submitted` buy는 `unverified_buy_orders` 또는 `pending_buy_orders`로만 warning 처리한다.
- fills 또는 잔고 대조가 없는 submitted buy는 자동 sell 대상이 아니다.
- `load_db_open_positions()`는 submitted-only buy를 open position으로 반환하지 않는다.
- Review에는 submitted-only buy가 “체결 미검증, 자동청산 제외”로 남아야 한다.

### 2. PnL verified 조건을 현재 거래일 order_id 기준으로 제한

대상: `backend/services/engine/position_integrity.py`, `review_audit.py`, `daily_summary.py`

요구:

- fills는 현재 trade_date의 `trading_orders.id` 목록으로 제한해서 조회한다.
- 현재 거래일 filled/partial_fill 주문마다 대응 fill row가 있는지 확인한다.
- fill quantity 합계가 주문 수량과 맞는지 확인한다.
- 하나라도 누락/불일치하면:
  - `pnl_status='unverified'`
  - `pnl_source='fills_incomplete'` 또는 `incomplete_orders`
  - warning 상세 포함
- 다른 날짜/다른 주문의 fills가 있어도 오늘 Review가 verified가 되면 안 된다.

### 3. net negative / duplicate sell anomaly 노출

대상: `position_integrity.py`, `review_audit.py`, `daily_summary.py`

요구:

- `summarize_order_integrity()`에 다음 이상을 포함한다.
  - `net_negative_positions`
  - `duplicate_sell_orders`
  - `sell_qty_exceeds_buy_qty`
- Review/Daily summary integrity warnings에 위 정보를 포함한다.
- 현재 2026-05-07 같은 buy 18 / sell 36, buy 122 / sell 244는 명확히 duplicate/net-negative 경고가 나와야 한다.

## 필수 검증

- `.venv/bin/python -m compileall -q backend`
- `git diff --check`
- 외부 호출 없는 temp sqlite/monkeypatch smoke:
  - submitted buy only는 `load_db_open_positions()`에서 0개, warning에는 포함
  - filled buy only는 open position 반환
  - filled buy 10 / sell filled 4는 net 6 반환
  - 오늘 filled order에 fill이 없고 전일 fill만 있으면 `pnl_status=unverified`
  - 오늘 filled order에 matching fill이 있으면 verified
  - buy 18 / sell 36은 net_negative/duplicate warning 생성

## 결과 보고 파일

작업 완료 후 아래 파일을 작성하라.

`docs/agent-comm/OUTBOX_EXECUTOR_20260507_1800_position_integrity_p1_fixes.md`

포함 항목:

- 변경 파일 목록
- 구현 요약
- 테스트 결과
- 남은 위험
- Oracle 리뷰 포인트
