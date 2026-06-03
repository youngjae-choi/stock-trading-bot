# 레짐별 일일예산 균등배분 포지션 사이징 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 매 주문이 "남은 현금의 N%"(기하 감소)가 아니라 "장 개시 예수금 × 레짐 예산률 ÷ 슬롯 수"(균등 배분)로 매수해, 시장톤에 맞춰 과감하되 100%를 넘지 않게 한다.

**Architecture:** ① 09:00 스케줄러 잡이 `ord_psbl_cash`를 일자별 DB에 1회 캡처(idempotent, 재기동 유지). ② 레짐 SET에 `daily_budget_rate` 추가, 활성 SET의 `applied_settings`에서 런타임 조회. ③ `order_executor` 사이징을 `baseline×budget_rate/max_positions`로 교체(실제 현금으로 clamp, baseline 결손 시 기존 로직 폴백). ④ `order_preflight`에 당일 누적 매수액이 `baseline×budget_rate` 도달 시 신규매수 차단 가드.

**Tech Stack:** Python 3, SQLite (`backend/services/db.py` `get_connection`), APScheduler, pytest. 실행: `PYTHONPATH=. .venv/bin/python -m pytest`.

**설계서:** `docs/superpowers/specs/2026-06-03-regime-budget-sizing-design.md`

**관련 기존 코드 (참고):**
- `backend/services/settings_store.py`: `get_setting(key, default)`, `upsert_setting(key, value, value_type, description, actor)`.
- `backend/services/regime_set_service.py`: `get_today_application(trade_date)` → `{..., "applied_settings": {...}}`; 4개 기본 SET은 `backend/services/db.py` `_seed_regime_sets()` 인근 리스트(`SET-RISK_ON` 등)에 `settings` 딕셔너리로 정의됨(`max_positions`, `stop_loss_rate` …).
- `backend/services/engine/order_executor.py`: `_execute_signal_inner` 내부 ~250행 `deposit=_extract_deposit(balance)` / `position_size_pct=_position_size_pct(final_rule)` / `qty=_calc_qty(deposit, position_size_pct, price)`. `_get_cached_balance()`(30s 캐시), `_extract_deposit()`(`ord_psbl_cash` 우선).
- `backend/services/engine/order_preflight.py`: `run_preflight(signal, final_rule, current_positions_count)` → `{ok, preflight_id, checks, block_reason}`; 내부 `checks[...]=PREFLIGHT_BLOCK` + `block_reasons.append(...)` 패턴.
- `trading_orders` 테이블 컬럼: `trade_date, symbol, side, qty REAL, price REAL, status`(side='buy', 매수액=`qty*price`).

---

## File Structure

| 파일 | 책임 |
|---|---|
| `backend/services/engine/daily_capital.py` (신규) | 장 개시 예수금 baseline 캡처·조회 (일자별, idempotent) + 레짐 예산률 해석 + 당일 누적 매수액 집계 |
| `backend/services/db.py` (수정) | 4개 레짐 SET `settings`에 `daily_budget_rate` 추가 |
| `backend/services/scheduler.py` (수정) | 09:00 baseline 캡처 잡 등록 + 잡 함수 |
| `backend/services/engine/order_executor.py` (수정) | 사이징을 예산 균등배분으로 교체 + clamp + 폴백 |
| `backend/services/engine/order_preflight.py` (수정) | 누적 예산 상한 차단 가드 |
| `tests/unit/test_daily_capital.py` (신규) | baseline idempotent·예산률·누적집계 |
| `tests/unit/test_budget_sizing.py` (신규) | 사이징 균등배분·clamp·폴백 |
| `tests/unit/test_preflight_budget_cap.py` (신규) | 누적 예산 상한 차단 |

---

### Task 1: daily_capital 모듈 — baseline 캡처/조회 + 예산률 + 누적집계

**Files:**
- Create: `backend/services/engine/daily_capital.py`
- Test: `tests/unit/test_daily_capital.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/test_daily_capital.py`:
```python
import backend.services.engine.daily_capital as dc


def test_capture_is_idempotent_and_readable():
    d = "2099-01-02"
    dc._delete_baseline(d)  # 테스트 클린업 헬퍼
    assert dc.get_baseline(d) is None
    assert dc.capture_baseline(1_000_000.0, trade_date=d) == 1_000_000.0
    # 두 번째 캡처는 기존값 유지(idempotent)
    assert dc.capture_baseline(7_777.0, trade_date=d) == 1_000_000.0
    assert dc.get_baseline(d) == 1_000_000.0
    dc._delete_baseline(d)


def test_capture_rejects_nonpositive():
    d = "2099-01-03"
    dc._delete_baseline(d)
    assert dc.capture_baseline(0.0, trade_date=d) is None
    assert dc.capture_baseline(-5.0, trade_date=d) is None
    assert dc.get_baseline(d) is None


def test_active_budget_rate_defaults_to_neutral_when_no_application(monkeypatch):
    monkeypatch.setattr(dc, "get_today_application", lambda _d: None)
    assert dc.get_active_budget_rate("2099-01-04") == 0.8


def test_active_budget_rate_from_applied_settings(monkeypatch):
    monkeypatch.setattr(
        dc, "get_today_application",
        lambda _d: {"applied_settings": {"daily_budget_rate": 0.9, "max_positions": 12}},
    )
    assert dc.get_active_budget_rate("2099-01-05") == 0.9
    assert dc.get_active_max_positions("2099-01-05") == 12


def test_cumulative_buy_amount(tmp_path, monkeypatch):
    # trading_orders에 buy 2건 submitted → 합계 qty*price
    d = "2099-01-06"
    dc._delete_orders_for_test(d)
    dc._insert_order_for_test(d, "005930", "buy", 10, 1000.0, "submitted")
    dc._insert_order_for_test(d, "000660", "buy", 5, 2000.0, "filled")
    dc._insert_order_for_test(d, "005930", "sell", 10, 1000.0, "filled")  # sell 제외
    assert dc.get_cumulative_buy_amount(d) == 10 * 1000.0 + 5 * 2000.0
    dc._delete_orders_for_test(d)
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_daily_capital.py -q`
Expected: FAIL (`ModuleNotFoundError` 또는 `AttributeError: _delete_baseline`).

- [ ] **Step 3: 구현**

`backend/services/engine/daily_capital.py`:
```python
"""장 개시 예수금 baseline 캡처/조회 + 레짐 예산률 + 당일 누적 매수액 집계.

포지션 사이징(order_executor)과 누적 예산 상한 가드(order_preflight)가 공유한다.
baseline은 일자별 1회 캡처(idempotent)되어 서버 재기동에도 유지된다.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection
from ..regime_set_service import get_today_application

logger = logging.getLogger("DailyCapital")

_DEFAULT_BUDGET_RATE = 0.8   # 레짐 미적용 시 중립 표준형 기준
_DEFAULT_MAX_POSITIONS = 7


def _today_kst() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


def _ensure_table() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_capital_baseline (
                trade_date   TEXT PRIMARY KEY,
                deposit_krw  REAL NOT NULL,
                captured_at  TEXT NOT NULL
            )
            """
        )


def capture_baseline(deposit: float, trade_date: str | None = None) -> float | None:
    """장 개시 예수금을 일자별 1회 저장. 이미 있으면 기존값 유지(idempotent).

    Returns: 저장(또는 기존) baseline, 비정상 입력이면 None.
    """
    d = trade_date or _today_kst()
    try:
        value = float(deposit)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        logger.warning("WARN: baseline 캡처 거부 — deposit<=0 trade_date=%s value=%s", d, deposit)
        return None
    _ensure_table()
    existing = get_baseline(d)
    if existing is not None:
        logger.info("INFO: baseline 이미 존재 — 재캡처 생략 trade_date=%s value=%.0f", d, existing)
        return existing
    now = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO daily_capital_baseline (trade_date, deposit_krw, captured_at) VALUES (?, ?, ?)",
            (d, value, now),
        )
    logger.info("SUCCESS: baseline 캡처 trade_date=%s deposit=%.0f", d, value)
    return value


def get_baseline(trade_date: str | None = None) -> float | None:
    d = trade_date or _today_kst()
    _ensure_table()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT deposit_krw FROM daily_capital_baseline WHERE trade_date = ?", (d,)
        ).fetchone()
    if row is None:
        return None
    try:
        return float(row["deposit_krw"])
    except (TypeError, ValueError, KeyError):
        return None


def get_active_budget_rate(trade_date: str | None = None) -> float:
    """오늘 적용된 레짐 SET의 daily_budget_rate. 없으면 중립 기본값."""
    d = trade_date or _today_kst()
    try:
        app = get_today_application(d)
        if app:
            rate = app.get("applied_settings", {}).get("daily_budget_rate")
            if rate is not None:
                r = float(rate)
                if 0 < r <= 1:
                    return r
    except Exception as exc:
        logger.warning("WARN: budget_rate 조회 실패 trade_date=%s reason=%s", d, exc)
    return _DEFAULT_BUDGET_RATE


def get_active_max_positions(trade_date: str | None = None) -> int:
    d = trade_date or _today_kst()
    try:
        app = get_today_application(d)
        if app:
            mp = app.get("applied_settings", {}).get("max_positions")
            if mp:
                return int(mp)
    except Exception as exc:
        logger.warning("WARN: max_positions 조회 실패 trade_date=%s reason=%s", d, exc)
    return _DEFAULT_MAX_POSITIONS


def get_cumulative_buy_amount(trade_date: str | None = None) -> float:
    """당일 신규 매수 누적액(qty*price). status가 cancelled/failed 인 건 제외."""
    d = trade_date or _today_kst()
    with get_connection() as conn:
        if not _table_exists(conn, "trading_orders"):
            return 0.0
        row = conn.execute(
            """
            SELECT COALESCE(SUM(qty * price), 0.0) AS total
            FROM trading_orders
            WHERE trade_date = ? AND side = 'buy'
              AND status NOT IN ('cancelled', 'failed')
            """,
            (d,),
        ).fetchone()
    try:
        return float(row["total"]) if row else 0.0
    except (TypeError, ValueError, KeyError):
        return 0.0


def _table_exists(conn: Any, name: str) -> bool:
    return conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (name,)
    ).fetchone() is not None


# --- 테스트 전용 헬퍼 ---
def _delete_baseline(trade_date: str) -> None:
    _ensure_table()
    with get_connection() as conn:
        conn.execute("DELETE FROM daily_capital_baseline WHERE trade_date = ?", (trade_date,))


def _insert_order_for_test(trade_date: str, symbol: str, side: str, qty: int, price: float, status: str) -> None:
    import uuid
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO trading_orders (id, trade_date, signal_id, symbol, name, side, order_type, qty, price, kis_order_no, status, reason, created_at)
               VALUES (?, ?, '', ?, '', ?, 'limit', ?, ?, '', ?, '', ?)""",
            (str(uuid.uuid4()), trade_date, symbol, side, qty, price, status, datetime.now().isoformat()),
        )


def _delete_orders_for_test(trade_date: str) -> None:
    with get_connection() as conn:
        if _table_exists(conn, "trading_orders"):
            conn.execute("DELETE FROM trading_orders WHERE trade_date = ?", (trade_date,))
```

참고: `trading_orders` 테이블은 `order_executor._ensure_orders_table()`가 생성한다. 테스트는 import 시 해당 모듈이 로드되며 테이블이 보장되지 않을 수 있으므로, `_insert_order_for_test` 전에 테이블이 없으면 `test_cumulative_buy_amount`가 실패한다 → Step 3 구현 후 테스트에서 `from backend.services.engine.order_executor import _ensure_orders_table; _ensure_orders_table()`를 테스트 상단에 추가하거나, 구현의 `_insert_order_for_test`에 `from .order_executor import _ensure_orders_table; _ensure_orders_table()` 호출을 넣어 보장한다. **구현 시 `_insert_order_for_test` 첫 줄에 `from .order_executor import _ensure_orders_table; _ensure_orders_table()`를 추가하라.**

- [ ] **Step 4: 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_daily_capital.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/daily_capital.py tests/unit/test_daily_capital.py
git commit -m "feat: daily_capital — 예수금 baseline 캡처·레짐 예산률·누적매수액 집계"
```

---

### Task 2: 레짐 SET에 daily_budget_rate 필드 추가

**Files:**
- Modify: `backend/services/db.py` (SET-RISK_ON / SET-NEUTRAL / SET-RISK_OFF / SET-VOLATILE 의 `settings` 딕셔너리)

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/test_daily_capital.py` 에 추가:
```python
def test_seed_sets_carry_budget_rate():
    from backend.services.db import _default_regime_sets  # SET 리스트 반환 함수
    sets = {s["id"]: s for s in _default_regime_sets()}
    assert sets["SET-RISK_ON"]["settings"]["daily_budget_rate"] == 0.90
    assert sets["SET-NEUTRAL"]["settings"]["daily_budget_rate"] == 0.80
    assert sets["SET-RISK_OFF"]["settings"]["daily_budget_rate"] == 0.50
    assert sets["SET-VOLATILE"]["settings"]["daily_budget_rate"] == 0.30
```

> **참고:** `db.py`에서 4개 SET을 반환하는 함수명을 먼저 확인하라(`grep -n "SET-RISK_ON" backend/services/db.py` → 해당 리스트를 감싼 `def` 이름). 위 테스트의 `_default_regime_sets` 를 실제 함수명으로 교체하라. 함수가 없고 인라인 리스트면, 그 리스트를 반환하는 작은 헬퍼로 추출하지 말고 테스트는 DB 시드 후 `get_all_sets(active_only=False)`로 조회하도록 바꿔라.

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_daily_capital.py::test_seed_sets_carry_budget_rate -q`
Expected: FAIL (`KeyError: 'daily_budget_rate'`).

- [ ] **Step 3: 구현**

`backend/services/db.py`의 각 SET `settings`에 한 줄씩 추가(값 매핑):
```python
# SET-RISK_ON settings 안:
                "daily_budget_rate": 0.90,   # 장개시 예수금 대비 일일 투입 상한
# SET-NEUTRAL settings 안:
                "daily_budget_rate": 0.80,
# SET-RISK_OFF settings 안:
                "daily_budget_rate": 0.50,
# SET-VOLATILE settings 안:
                "daily_budget_rate": 0.30,
```
`SET-PRE-0526-RECOVERY` 등 추가 SET이 있으면 Risk On 계열은 0.90, 방어 계열은 0.50으로 동일 정책 적용.

- [ ] **Step 4: 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_daily_capital.py::test_seed_sets_carry_budget_rate -q`
Expected: PASS.

- [ ] **Step 5: 커밋**

```bash
git add backend/services/db.py tests/unit/test_daily_capital.py
git commit -m "feat: 레짐 SET에 daily_budget_rate(90/80/50/30) 추가"
```

---

### Task 3: 09:00 장개시 baseline 캡처 스케줄러 잡

**Files:**
- Modify: `backend/services/scheduler.py` (잡 함수 추가 + `scheduler.add_job` 등록)

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/test_daily_capital.py` 에 추가:
```python
import asyncio


def test_capture_job_uses_balance_deposit(monkeypatch):
    import backend.services.scheduler as sched
    d = "2099-01-09"
    dc._delete_baseline(d)

    async def fake_balance():
        return {"output2": [{"ord_psbl_cash": "1234567"}]}

    monkeypatch.setattr(sched, "get_balance", fake_balance, raising=False)
    monkeypatch.setattr(sched, "_today_kst_date", lambda: d, raising=False)
    asyncio.run(sched.job_capture_capital_baseline())
    assert dc.get_baseline(d) == 1234567.0
    dc._delete_baseline(d)
```

> **참고:** `scheduler.py`의 잔고 조회 함수/오늘날짜 헬퍼 실제 이름을 확인하라(`grep -nE "get_balance|_today_kst|def job_" backend/services/scheduler.py`). 위 monkeypatch 대상명을 실제 심볼에 맞춰라. `_extract_deposit` 로직은 `order_executor._extract_deposit`를 재사용하거나 잡 함수 내에서 `output2[0]["ord_psbl_cash"]`를 직접 파싱하라.

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_daily_capital.py::test_capture_job_uses_balance_deposit -q`
Expected: FAIL (`AttributeError: job_capture_capital_baseline`).

- [ ] **Step 3: 구현**

`backend/services/scheduler.py` 에 잡 함수 추가(파일 상단 import 패턴을 따라 `get_balance` import 위치 확인):
```python
async def job_capture_capital_baseline() -> None:
    """Job (08:50 KST): 장 개시 전 예수금 baseline을 일자별 1회 캡처."""
    from .engine.daily_capital import capture_baseline
    trade_date = _today_kst_date()
    logger.info("START: [JobCapital] baseline 캡처 trade_date=%s", trade_date)
    try:
        balance = await get_balance()
        summary = (balance.get("output2") or [{}])[0]
        deposit = 0.0
        for key in ("ord_psbl_cash", "dnca_tot_amt", "nass_amt"):
            try:
                deposit = float(str(summary.get(key) or "0").replace(",", ""))
            except (TypeError, ValueError):
                deposit = 0.0
            if deposit > 0:
                break
        result = capture_baseline(deposit, trade_date=trade_date)
        logger.info("SUCCESS: [JobCapital] baseline=%s trade_date=%s", result, trade_date)
    except Exception as exc:
        logger.warning("WARN: [JobCapital] baseline 캡처 실패 trade_date=%s reason=%s", trade_date, exc)
```
`_today_kst_date()` 헬퍼가 없으면 `datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")`로 인라인 처리.

`register_jobs`(혹은 `scheduler.add_job`들이 모인 함수) 안에 등록 — 08:50 KST(09:00 S6 활성화 전):
```python
    scheduler.add_job(
        job_capture_capital_baseline,
        CronTrigger(hour=8, minute=50, timezone="Asia/Seoul"),
        id="job_capture_capital_baseline",
        replace_existing=True,
    )
```

- [ ] **Step 4: 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_daily_capital.py::test_capture_job_uses_balance_deposit -q`
Expected: PASS.
또한 `PYTHONPATH=. .venv/bin/python -c "import backend.main; print('import ok')"` → import ok.

- [ ] **Step 5: 커밋**

```bash
git add backend/services/scheduler.py tests/unit/test_daily_capital.py
git commit -m "feat: 08:50 장개시 예수금 baseline 캡처 잡"
```

---

### Task 4: order_executor 사이징을 예산 균등배분으로 교체

**Files:**
- Modify: `backend/services/engine/order_executor.py` (`_execute_signal_inner` 사이징 구간 + 신규 헬퍼 `_calc_budget_qty`)
- Test: `tests/unit/test_budget_sizing.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/test_budget_sizing.py`:
```python
from backend.services.engine.order_executor import OrderExecutor


def test_budget_qty_equal_weight():
    ex = OrderExecutor()
    # baseline 1,000,000 × budget 0.9 / 12슬롯 = 75,000 → price 1,000 → 75주
    qty = ex._calc_budget_qty(baseline=1_000_000.0, budget_rate=0.9, max_positions=12,
                              price=1_000.0, available_cash=1_000_000.0)
    assert qty == 75


def test_budget_qty_clamps_to_available_cash():
    ex = OrderExecutor()
    # 산출 75,000원어치지만 가용현금 30,000뿐 → 30주로 clamp
    qty = ex._calc_budget_qty(baseline=1_000_000.0, budget_rate=0.9, max_positions=12,
                              price=1_000.0, available_cash=30_000.0)
    assert qty == 30


def test_budget_qty_zero_when_no_baseline():
    ex = OrderExecutor()
    qty = ex._calc_budget_qty(baseline=None, budget_rate=0.9, max_positions=12,
                              price=1_000.0, available_cash=1_000_000.0)
    assert qty == 0  # 폴백은 호출부에서 처리 — 헬퍼는 0 반환


def test_budget_qty_guards_bad_inputs():
    ex = OrderExecutor()
    assert ex._calc_budget_qty(1_000_000.0, 0.0, 12, 1_000.0, 1_000_000.0) == 0
    assert ex._calc_budget_qty(1_000_000.0, 0.9, 0, 1_000.0, 1_000_000.0) == 0
    assert ex._calc_budget_qty(1_000_000.0, 0.9, 12, 0.0, 1_000_000.0) == 0
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_budget_sizing.py -q`
Expected: FAIL (`AttributeError: _calc_budget_qty`).

- [ ] **Step 3: 구현**

`order_executor.py`에 헬퍼 추가:
```python
    def _calc_budget_qty(
        self,
        baseline: float | None,
        budget_rate: float,
        max_positions: int,
        price: float,
        available_cash: float,
    ) -> int:
        """예산 균등배분 수량 = floor(min(baseline*budget_rate/max_positions, available_cash) / price).

        baseline 결손/비정상 입력이면 0 반환(호출부가 기존 로직으로 폴백).
        """
        if not baseline or baseline <= 0 or budget_rate <= 0 or max_positions <= 0 or price <= 0:
            return 0
        per_slot = baseline * budget_rate / max_positions
        spend = min(per_slot, available_cash if available_cash > 0 else per_slot)
        return int(spend // price)
```

`_execute_signal_inner` 사이징 구간(현재):
```python
            deposit = self._extract_deposit(balance)
            position_size_pct = self._position_size_pct(final_rule)
            qty = self._calc_qty(deposit, position_size_pct, price)
            if qty <= 0:
                raise ValueError("calculated quantity is zero")
```
를 다음으로 교체:
```python
            deposit = self._extract_deposit(balance)
            from .daily_capital import get_baseline, get_active_budget_rate
            baseline = get_baseline(today)
            budget_rate = get_active_budget_rate(today)
            max_positions = int(_to_float(final_rule.get("max_positions"), 7.0) or 7)
            qty = self._calc_budget_qty(baseline, budget_rate, max_positions, price, deposit)
            if qty <= 0:
                # baseline 결손 등 → 기존 '남은현금 × position_size_pct' 방식으로 폴백
                position_size_pct = self._position_size_pct(final_rule)
                qty = self._calc_qty(deposit, position_size_pct, price)
                logger.info(
                    "INFO: [S7] 사이징 폴백(baseline 결손) symbol=%s qty=%d", symbol, qty,
                )
            else:
                logger.info(
                    "INFO: [S7] 예산 균등배분 사이징 symbol=%s baseline=%s rate=%.2f maxpos=%d qty=%d",
                    symbol, baseline, budget_rate, max_positions, qty,
                )
            if qty <= 0:
                raise ValueError("calculated quantity is zero")
```
(`today` 변수는 해당 메서드 상단에 이미 존재하는지 확인 — 없으면 `today = self._today_kst()` 사용. `_to_float`는 모듈 상단에 이미 정의됨.)

- [ ] **Step 4: 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_budget_sizing.py -q`
Expected: PASS (4 passed).
또한 `PYTHONPATH=. .venv/bin/python -c "import backend.main; print('import ok')"` → import ok.

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/order_executor.py tests/unit/test_budget_sizing.py
git commit -m "feat: S7 사이징을 예산 균등배분(baseline×rate/슬롯)으로 교체 + 폴백"
```

---

### Task 5: order_preflight 누적 예산 상한 차단 가드

**Files:**
- Modify: `backend/services/engine/order_preflight.py` (`run_preflight` 내부 체크 추가)
- Test: `tests/unit/test_preflight_budget_cap.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/test_preflight_budget_cap.py`:
```python
import backend.services.engine.order_preflight as pf


def test_budget_cap_blocks_when_cumulative_reaches_budget(monkeypatch):
    # baseline 1,000,000 × 0.5 = 500,000 예산. 이미 500,000 매수 → 차단.
    monkeypatch.setattr(pf, "get_baseline", lambda _d=None: 1_000_000.0)
    monkeypatch.setattr(pf, "get_active_budget_rate", lambda _d=None: 0.5)
    monkeypatch.setattr(pf, "get_cumulative_buy_amount", lambda _d=None: 500_000.0)
    blocked, reason = pf._budget_cap_check(trade_date="2099-01-10")
    assert blocked is True
    assert "예산" in reason


def test_budget_cap_allows_when_under_budget(monkeypatch):
    monkeypatch.setattr(pf, "get_baseline", lambda _d=None: 1_000_000.0)
    monkeypatch.setattr(pf, "get_active_budget_rate", lambda _d=None: 0.5)
    monkeypatch.setattr(pf, "get_cumulative_buy_amount", lambda _d=None: 200_000.0)
    blocked, _ = pf._budget_cap_check(trade_date="2099-01-10")
    assert blocked is False


def test_budget_cap_allows_when_no_baseline(monkeypatch):
    # baseline 없으면 가드 비활성(매수 막지 않음)
    monkeypatch.setattr(pf, "get_baseline", lambda _d=None: None)
    monkeypatch.setattr(pf, "get_active_budget_rate", lambda _d=None: 0.5)
    monkeypatch.setattr(pf, "get_cumulative_buy_amount", lambda _d=None: 999_999.0)
    blocked, _ = pf._budget_cap_check(trade_date="2099-01-10")
    assert blocked is False
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_preflight_budget_cap.py -q`
Expected: FAIL (`AttributeError: _budget_cap_check` 또는 import 실패).

- [ ] **Step 3: 구현**

`order_preflight.py` 상단 import 추가:
```python
from .daily_capital import get_baseline, get_active_budget_rate, get_cumulative_buy_amount
```
헬퍼 함수 추가:
```python
def _budget_cap_check(trade_date: str | None = None) -> tuple[bool, str]:
    """당일 누적 매수액이 baseline×budget_rate 도달 시 (True, 사유). baseline 없으면 (False, '')."""
    baseline = get_baseline(trade_date)
    if not baseline or baseline <= 0:
        return False, ""
    budget = baseline * get_active_budget_rate(trade_date)
    used = get_cumulative_buy_amount(trade_date)
    if used >= budget > 0:
        return True, f"일일 투입예산 소진 ({used:,.0f}/{budget:,.0f}원)"
    return False, ""
```
`run_preflight` 내부, 기존 체크들 사이(예: "4. 최대 보유 종목 수" 뒤)에 추가:
```python
    # 6. 일일 투입예산 상한 (baseline×budget_rate 도달 시 신규매수 차단)
    budget_blocked, budget_reason = _budget_cap_check(_today_kst().strftime("%Y-%m-%d"))
    if budget_blocked:
        checks["budget_cap"] = PREFLIGHT_BLOCK
        block_reasons.append(budget_reason)
    else:
        checks["budget_cap"] = PREFLIGHT_OK
```
(`_today_kst()`는 파일에 이미 존재. `run_preflight`가 `trade_date` 인자를 받으면 그걸 우선 사용.)

- [ ] **Step 4: 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_preflight_budget_cap.py -q`
Expected: PASS (3 passed).
회귀: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/ -q` → 전체 PASS.

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/order_preflight.py tests/unit/test_preflight_budget_cap.py
git commit -m "feat: 프리플라이트 일일 투입예산 상한 차단 가드"
```

---

## 완료 기준
- [ ] 신규 유닛 테스트 3파일 전체 PASS + 기존 `tests/unit/` 회귀 PASS.
- [ ] `import backend.main` 정상.
- [ ] 사이징이 baseline 균등배분으로 동작, baseline 결손 시 기존 로직 폴백.
- [ ] 누적 예산 상한 도달 시 신규매수 차단, baseline 없으면 가드 비활성.
- [ ] 최종 코드리뷰 후 finishing-a-development-branch로 main 병합.

## 수동 검증 (선택, 장중)
- 08:50 잡 로그 `SUCCESS: [JobCapital] baseline=...` 확인.
- 매수 발생 시 `INFO: [S7] 예산 균등배분 사이징 ... qty=` 로그로 균등성 확인.
- 누적 예산 도달 시 `BLOCK: ... 일일 투입예산 소진` 확인.
