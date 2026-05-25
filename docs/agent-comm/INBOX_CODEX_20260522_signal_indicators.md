# INBOX: S6 진입 시점 기술지표 스냅샷 저장

**날짜:** 2026-05-22  
**우선순위:** HIGH  
**대상:** Codex (Backend)

---

## 목적

S6에서 BUY 신호 생성 시점의 기술지표 값을 DB에 저장한다.
나중에 "어떤 지표 조합이 수익과 연관됐는가"를 분석하기 위한 데이터 수집이다.

---

## 작업 1: 테이블 생성 (`backend/services/db.py`)

`init_database()` 함수 내 테이블 생성 목록에 아래 추가:

```sql
CREATE TABLE IF NOT EXISTS signal_technical_indicators (
    id          TEXT PRIMARY KEY,
    signal_id   TEXT NOT NULL,          -- trading_signals.id
    symbol      TEXT NOT NULL,
    trade_date  TEXT NOT NULL,          -- YYYY-MM-DD
    -- 가격 지표
    price_change_pct    REAL,           -- 당일 등락률 (%)
    price_vs_ma5_pct    REAL,           -- 5일 이평 대비 (%)
    price_vs_ma20_pct   REAL,           -- 20일 이평 대비 (%)
    -- 모멘텀
    rsi14               REAL,           -- RSI(14)
    momentum5d_pct      REAL,           -- 5일 모멘텀 (%)
    -- 거래량
    volume_ratio        REAL,           -- 당일거래량 / 20일평균거래량
    -- 시장 환경
    kospi_change_pct    REAL,           -- KOSPI 당일 등락률 (%)
    -- 결과 (나중에 채움)
    outcome_pnl_pct     REAL,           -- 실제 손익률 (fill 후 업데이트)
    outcome_hold_min    REAL,           -- 보유 시간(분)
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sti_symbol_date ON signal_technical_indicators(symbol, trade_date);
CREATE INDEX IF NOT EXISTS idx_sti_signal_id ON signal_technical_indicators(signal_id);
```

---

## 작업 2: 기술지표 계산 서비스 생성

파일: `backend/services/engine/technical_indicators.py` (신규 생성)

```python
"""기술지표 계산 — pykrx 기반 진입 시점 스냅샷."""
from __future__ import annotations
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger("TechnicalIndicators")

_CACHE: dict[str, Any] = {}  # (symbol, date) → indicators


def _pykrx_ohlcv(symbol: str, start: str, end: str):
    """pykrx로 OHLCV 조회. 실패 시 None 반환."""
    try:
        from pykrx import stock
        df = stock.get_market_ohlcv(start, end, symbol)
        return df if df is not None and len(df) > 0 else None
    except Exception as e:
        logger.warning("WARN: pykrx OHLCV 조회 실패 symbol=%s error=%s", symbol, e)
        return None


def _calc_rsi(closes, period=14) -> float | None:
    """RSI(period) 계산."""
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def calculate_indicators(symbol: str, trade_date: str) -> dict[str, Any]:
    """trade_date 기준 기술지표 계산. pykrx 사용.
    
    Args:
        symbol: 종목코드 (예: 005930)
        trade_date: YYYY-MM-DD
    Returns:
        dict with price_change_pct, rsi14, volume_ratio 등
    """
    cache_key = f"{symbol}:{trade_date}"
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    result: dict[str, Any] = {}
    try:
        dt = datetime.strptime(trade_date, "%Y-%m-%d")
        start = (dt - timedelta(days=40)).strftime("%Y%m%d")
        end = dt.strftime("%Y%m%d")

        df = _pykrx_ohlcv(symbol, start, end)
        if df is None or len(df) < 5:
            return result

        closes = list(df["종가"])
        volumes = list(df["거래량"])
        today_close = closes[-1]
        today_open = list(df["시가"])[-1]
        prev_close = closes[-2] if len(closes) >= 2 else today_close

        # 당일 등락률
        result["price_change_pct"] = round((today_close - prev_close) / prev_close * 100, 2) if prev_close else None

        # MA 비교
        if len(closes) >= 5:
            ma5 = sum(closes[-5:]) / 5
            result["price_vs_ma5_pct"] = round((today_close - ma5) / ma5 * 100, 2)
        if len(closes) >= 20:
            ma20 = sum(closes[-20:]) / 20
            result["price_vs_ma20_pct"] = round((today_close - ma20) / ma20 * 100, 2)

        # RSI(14)
        result["rsi14"] = _calc_rsi(closes)

        # 5일 모멘텀
        if len(closes) >= 6:
            result["momentum5d_pct"] = round((closes[-1] - closes[-6]) / closes[-6] * 100, 2)

        # 거래량 비율 (오늘 / 20일 평균)
        if len(volumes) >= 21:
            avg_vol20 = sum(volumes[-21:-1]) / 20
            result["volume_ratio"] = round(volumes[-1] / avg_vol20, 2) if avg_vol20 > 0 else None

    except Exception as e:
        logger.warning("WARN: calculate_indicators failed symbol=%s date=%s error=%s", symbol, trade_date, e)

    # KOSPI 등락률
    try:
        from pykrx import stock as _stock
        dt2 = datetime.strptime(trade_date, "%Y-%m-%d")
        kstart = (dt2 - timedelta(days=5)).strftime("%Y%m%d")
        kend = dt2.strftime("%Y%m%d")
        kdf = _stock.get_market_ohlcv(kstart, kend, "1001")  # KOSPI 지수
        if kdf is not None and len(kdf) >= 2:
            kcloses = list(kdf["종가"])
            result["kospi_change_pct"] = round((kcloses[-1] - kcloses[-2]) / kcloses[-2] * 100, 2)
    except Exception:
        pass

    _CACHE[cache_key] = result
    return result


def save_signal_indicators(signal_id: str, symbol: str, trade_date: str) -> bool:
    """signal_technical_indicators 테이블에 저장."""
    from ..db import get_connection
    indicators = calculate_indicators(symbol, trade_date)
    if not indicators:
        logger.warning("WARN: save_signal_indicators empty symbol=%s", symbol)
        return False
    now = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
    row_id = str(uuid.uuid4())
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO signal_technical_indicators
                    (id, signal_id, symbol, trade_date,
                     price_change_pct, price_vs_ma5_pct, price_vs_ma20_pct,
                     rsi14, momentum5d_pct, volume_ratio, kospi_change_pct,
                     created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row_id, signal_id, symbol, trade_date,
                    indicators.get("price_change_pct"),
                    indicators.get("price_vs_ma5_pct"),
                    indicators.get("price_vs_ma20_pct"),
                    indicators.get("rsi14"),
                    indicators.get("momentum5d_pct"),
                    indicators.get("volume_ratio"),
                    indicators.get("kospi_change_pct"),
                    now,
                ),
            )
        logger.info("SUCCESS: signal_indicators saved signal_id=%s symbol=%s", signal_id, symbol)
        return True
    except Exception as e:
        logger.warning("WARN: save_signal_indicators DB error=%s", e)
        return False


def update_signal_outcome(signal_id: str, pnl_pct: float, hold_minutes: float) -> bool:
    """체결 후 실제 결과를 업데이트한다."""
    from ..db import get_connection
    try:
        with get_connection() as conn:
            conn.execute(
                "UPDATE signal_technical_indicators SET outcome_pnl_pct=?, outcome_hold_min=? WHERE signal_id=?",
                (pnl_pct, hold_minutes, signal_id),
            )
        return True
    except Exception as e:
        logger.warning("WARN: update_signal_outcome failed signal_id=%s error=%s", signal_id, e)
        return False
```

---

## 작업 3: Decision Engine에 통합

파일: `backend/services/engine/decision_engine.py`

BUY 신호를 `trading_signals`에 INSERT한 직후, 비동기로 지표 저장:

```python
# trading_signals INSERT 완료 후 (signal_id 확보된 시점):
try:
    import asyncio
    from .technical_indicators import save_signal_indicators as _save_sti
    # 비동기 컨텍스트이므로 executor 사용
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _save_sti, signal_id, symbol, trade_date)
except Exception as _sti_exc:
    logger.warning("WARN: signal_indicators save skipped reason=%s", _sti_exc)
```

`decision_engine.py`에서 BUY signal INSERT 위치를 찾아 (grep "INSERT INTO trading_signals") 그 바로 아래에 삽입한다.

---

## 작업 4: trade_pairs 결과와 연결

파일: `backend/services/engine/review_audit.py` 또는 `false_positive.py`

매도 완료 pair가 있을 때 `update_signal_outcome()` 호출:

S10 `create_daily_report()` 내부, trade_pairs 루프에서 매도완료 pair 처리 시:
```python
from .technical_indicators import update_signal_outcome as _update_sti
# signal_id는 trading_signals 조회로 획득
with get_connection() as conn:
    sig = conn.execute(
        "SELECT id FROM trading_signals WHERE symbol=? AND trade_date=? AND signal_type='BUY' LIMIT 1",
        (pair["symbol"], pair.get("buy_date") or trade_date)
    ).fetchone()
if sig and pair.get("pnl_pct") is not None:
    hold_min = 0.0  # 보유시간 계산 가능하면 추가
    _update_sti(sig["id"], float(pair["pnl_pct"]), hold_min)
```

---

## 완료 기준

1. `py_compile` 통과 (db.py, technical_indicators.py, decision_engine.py)
2. `signal_technical_indicators` 테이블 DB에 생성됨
3. 테스트:
   ```python
   from backend.services.engine.technical_indicators import calculate_indicators
   r = calculate_indicators("005930", "2026-05-22")
   print(r)  # rsi14, volume_ratio 등 값 있어야 함
   ```
4. decision_engine.py grep으로 `save_signal_indicators` 호출 위치 확인

결과: `docs/agent-comm/OUTBOX_CODEX_20260522_signal_indicators.md`
