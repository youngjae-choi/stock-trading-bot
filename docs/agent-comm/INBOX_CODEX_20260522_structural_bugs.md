# INBOX: 구조적 버그 2개 수정

**날짜:** 2026-05-22  
**우선순위:** HIGH  
**대상:** Codex (Backend)

---

## 버그 1: trading_signals.realized_pnl 미업데이트

### 현상
`review_audit.py`의 `create_daily_report()` 함수가 `total_pnl`, `win_count`, `loss_count`를 계산할 때
`trading_signals.realized_pnl` 필드를 읽는다. 그러나 이 필드는 매도 체결 이후 어디서도 업데이트되지 않아 항상 `None` → `pnl=0.0`으로 처리됨.

결과: `total_pnl=0.0`, `win_count=0`, `loss_count=N` (모든 거래를 손실로 분류)

### 수정 파일
`backend/services/engine/review_audit.py`

### 구현
`create_daily_report(trade_date)` 함수 내부 상단에서 signals 로드 직전에 trade_pairs 기반으로 realized_pnl을 업데이트한다.

```python
# signals 루프 시작 전에 삽입:
# trading_signals.realized_pnl을 trade_pairs 체결 데이터로 업데이트
try:
    from .trade_pairs import get_trade_pairs as _get_pairs
    _pairs = _get_pairs(trade_date, trade_date)
    with get_connection() as _conn:
        for _p in _pairs:
            if _p.get("status") == "매도완료" and _p.get("pnl_amount") is not None:
                _conn.execute(
                    "UPDATE trading_signals SET realized_pnl=? WHERE symbol=? AND trade_date=? AND signal_type='BUY'",
                    (_p["pnl_amount"], _p["symbol"], trade_date),
                )
    logger.info("INFO: [S10] trading_signals.realized_pnl 업데이트 완료 pairs=%d", len(_pairs))
except Exception as _pnl_exc:
    logger.warning("WARN: [S10] trading_signals.realized_pnl 업데이트 실패 reason=%s", _pnl_exc)
```

삽입 위치: `signals = [...]` 로드 코드 바로 직전 (약 line 265~280 근처, `_table_columns("trading_signals")` 호출 전후).

---

## 버그 2: fill_poller output2_fallback 수량 2배 오류

### 현상
`fill_poller.py`의 `_fetch_symbol_output2()` 함수가 `output2` fallback을 사용할 때
매도 주문의 fill quantity가 실제의 2배로 기록됨.

예: 매수 90주, 매도 90주 → fills 테이블에 quantity=180으로 저장.

### 원인 추정
`_fetch_symbol_output2(symbol, date_str)`가 당일 해당 종목의 모든 체결(매수+매도)을 합산하거나,
tot_ccld_qty를 잘못 읽어 누적 수량이 2배가 됨.

### 수정 파일
`backend/services/engine/fill_poller.py`

### 구현

1. `_fetch_symbol_output2()` 함수 내에서 주문번호(`odno`) 기반으로 매칭하는지 확인한다.
   - 주문번호가 일치하는 행만 사용 (`order.kis_order_no == item.odno`)
   - 전체 종목 누적 수량이 아닌, 해당 주문 건의 체결 수량만 사용

2. `poll_once()` 내부에서 order별 fill 기록 시 `quantity`가 `order.qty`를 초과하지 않도록 cap 처리:
   ```python
   fill_qty = min(fill_qty, order_qty)  # 주문 수량 초과 방지
   ```

3. 이미 기록된 오류 데이터 수정 (2026-05-22):
   ```sql
   UPDATE fills SET quantity = (
       SELECT quantity FROM trading_orders WHERE id = fills.order_id
   )
   WHERE side = 'sell' AND date(filled_at) = '2026-05-22'
     AND quantity > (SELECT quantity FROM trading_orders WHERE id = fills.order_id);
   ```
   위 쿼리를 직접 실행하거나, 수정된 `poll_once()`를 2026-05-22에 재실행.

---

## 완료 기준

1. `review_audit.py` — create_daily_report 내 realized_pnl 업데이트 로직 추가
2. `fill_poller.py` — output2 fallback 수량 2배 버그 수정
3. `fills` 테이블 2026-05-22 sell quantity 수정 (12, 8, 90, 24로 정정)
4. 서버 재시작 후 `job_review_audit()` 재실행 확인:
   - `daily_review_reports.win_count`, `loss_count`, `total_pnl` 정상 여부
5. py_compile 통과

결과를 `docs/agent-comm/OUTBOX_CODEX_20260522_structural_bugs.md` 에 기록하라.
