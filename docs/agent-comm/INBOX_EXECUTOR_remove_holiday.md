# INBOX_EXECUTOR_remove_holiday — 공휴일 기능 전체 삭제

## 삭제 범위

공휴일 관련 기능을 완전히 제거한다. 스케줄러 시간 DB 설정, 해외 시장 데이터 등 다른 기능은 건드리지 않는다.

---

## 1. 파일 삭제

아래 파일 2개를 완전히 삭제한다:
- `backend/services/trading_calendar.py`
- `backend/api/routes/trading_calendar.py`

---

## 2. `backend/main.py` 수정

아래 두 줄을 제거한다:

```python
from .api.routes.trading_calendar import router as trading_calendar_router
```
```python
app.include_router(trading_calendar_router)
```

---

## 3. `backend/services/scheduler.py` 수정

`_is_non_trading_day()` 함수 전체 제거 (약 32~42라인):
```python
def _is_non_trading_day(job_label: str, today: str) -> bool:
    """Return True and log a skip when the given KST date is weekend or holiday."""
    try:
        from .trading_calendar import is_trading_day

        if not is_trading_day(today):
            logger.info("SKIP: [%s] 비거래일(%s) 스킵", job_label, today)
            return True
    except Exception as exc:
        logger.error("FAIL: [%s] 거래일 판정 실패 — 기존 job 흐름 계속 reason=%s", job_label, exc)
    return False
```

그리고 Job3/Job4/Job5 내부의 `_is_non_trading_day` 호출 블록 제거:
```python
    if _is_non_trading_day("Job3", today):
        return
```
```python
    if _is_non_trading_day("Job4", today):
        return
```
```python
    if _is_non_trading_day("Job5", today):
        return
```

`today = _kst_today()` 호출도 각 job에서 더 이상 필요 없으면 제거한다 (다른 용도로 쓰이는 경우는 유지).

---

## 4. `backend/static/console.html` 수정

Settings 탭에서 공휴일 관리 섹션 전체를 제거한다.

### 제거할 HTML 블록
`공휴일 관리` 카드 전체 (약 1681라인 근처):
```html
<div class="card-title">공휴일 관리 <span>trading-calendar</span></div>
```
위 줄을 포함하는 card div 전체 제거.

### 제거할 JavaScript 함수들
- `loadHolidays()` 함수 전체
- `addHoliday()` 함수 전체
- `deleteHoliday()` 함수 전체
- `holidayYearSelect` 관련 초기화 코드 (약 2722라인 근처)
- `loadHolidays()` 호출 코드

---

## 완료 기준

```bash
python -m py_compile backend/main.py && echo "main OK"
python -m py_compile backend/services/scheduler.py && echo "scheduler OK"
python3 -c "from html.parser import HTMLParser; p=HTMLParser(); p.feed(open('backend/static/console.html').read()); print('HTML OK')"
grep -n "trading_calendar\|is_trading_day\|holiday" backend/main.py backend/services/scheduler.py
# → 결과 없어야 함
```

OUTBOX(`docs/agent-comm/OUTBOX_EXECUTOR_remove_holiday.md`)에 결과 작성.
