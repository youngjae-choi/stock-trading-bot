# INBOX — Codex | 배당금 수정 시 stock_id 미반영 버그 수정

## 배경
배당 이력을 수정할 때 종목 선택을 변경해도 DB에 반영되지 않는 버그가 있다.

## 근본 원인
`backend/api/routes/dividends.py` 의 `update_dividend_entry` (PUT /entries/{entry_id}) 라우트에서
UPDATE SQL에 `stock_id` 컬럼이 누락되어 있다.

현재 코드 (line ~273):
```python
res = conn.execute(
    """
    UPDATE dividends
    SET account_id = ?, dividend_date = ?, amount = ?, tax = ?, net_amount = ?, dividend_rate = ?, memo = ?, updated_at = ?
    WHERE id = ?
    """,
    (payload.account_id, payload.dividend_date, payload.amount, payload.tax, payload.net_amount,
     payload.dividend_rate, payload.memo, now, entry_id),
)
```

`stock_id`가 SET 절에 없고, `payload.stock_id`가 파라미터에 없다.

## 수정 작업

### 1. `backend/api/routes/dividends.py` — `update_dividend_entry` 수정

UPDATE SQL에 `stock_id = ?` 추가:

```python
res = conn.execute(
    """
    UPDATE dividends
    SET account_id = ?, stock_id = ?, dividend_date = ?, amount = ?, tax = ?, net_amount = ?, dividend_rate = ?, memo = ?, updated_at = ?
    WHERE id = ?
    """,
    (payload.account_id, payload.stock_id or None,
     payload.dividend_date, payload.amount, payload.tax, payload.net_amount,
     payload.dividend_rate, payload.memo, now, entry_id),
)
```

수정 완료 후 아래 확인:
- `backend/api/routes/dividends.py` 문법 오류 없을 것
- 서버를 재시작하지 않아도 됨 (--reload 모드로 실행 중)

## 완료 기준
- [ ] `update_dividend_entry` SQL에 `stock_id` 포함됨
- [ ] `payload.stock_id or None` 을 파라미터에 추가
- [ ] 파이썬 문법 오류 없음

결과를 `docs/agent-comm/OUTBOX_CODEX_20260516_dividend_stockid_bugfix.md` 에 작성하라.
