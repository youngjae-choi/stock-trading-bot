# INBOX: 백테스트 모듈 — pykrx 과거 데이터 기반

**날짜:** 2026-05-22  
**우선순위:** HIGH  
**대상:** Codex (Backend)

---

## 목적

pykrx로 과거 2년 주가 데이터를 가져와 현재 매매 조건을 적용한 백테스트를 실행한다.
"현재 스크리닝 기준(price_change, volume_ratio, RSI 등)으로 과거에 매매했다면 수익이 났을까?"를 검증한다.

---

## 작업 1: 백테스트 서비스 생성

파일: `backend/services/engine/backtest.py` (신규 생성)

```python
"""백테스트 엔진 — pykrx 과거 데이터 기반."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger("Backtest")


def _pykrx_ohlcv(symbol: str, start: str, end: str):
    try:
        from pykrx import stock
        df = stock.get_market_ohlcv(start, end, symbol)
        return df if df is not None and len(df) > 0 else None
    except Exception as e:
        logger.warning("WARN: pykrx OHLCV 실패 symbol=%s error=%s", symbol, e)
        return None


def _get_universe_symbols(limit: int = 50) -> list[str]:
    """DB의 hybrid_screening_results에서 최근 등장한 종목을 유니버스로 사용.
    없으면 KOSPI 시가총액 상위 종목 사용."""
    try:
        from ..db import get_connection
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT DISTINCT symbol FROM hybrid_screening_results
                   ORDER BY created_at DESC LIMIT ?""",
                (limit,)
            ).fetchall()
        symbols = [r["symbol"] for r in rows]
        if symbols:
            return symbols
    except Exception:
        pass
    # fallback: KOSPI 시가총액 상위
    try:
        from pykrx import stock
        today = datetime.now().strftime("%Y%m%d")
        df = stock.get_market_cap(today, market="KOSPI")
        if df is not None and len(df) > 0:
            return list(df.sort_values("시가총액", ascending=False).head(limit).index)
    except Exception:
        pass
    return []


def _simulate_trade(
    closes: list[float],
    entry_idx: int,
    stop_loss_pct: float = -0.015,
    trailing_activate_pct: float = 0.02,
    trailing_stop_pct: float = 0.01,
    force_exit_bars: int = 5,  # 5봉(일봉 기준 5일) 강제 청산
) -> dict[str, Any]:
    """entry_idx 시점에 매수 후 exit 시뮬레이션.
    일봉 기반 단순 시뮬레이션."""
    entry_price = closes[entry_idx]
    peak = entry_price
    trailing_active = False

    for i in range(entry_idx + 1, min(entry_idx + force_exit_bars + 1, len(closes))):
        price = closes[i]
        pnl_pct = (price - entry_price) / entry_price

        # 손절
        if pnl_pct <= stop_loss_pct:
            return {"exit_idx": i, "exit_price": price, "pnl_pct": round(pnl_pct * 100, 3), "exit_reason": "stop_loss", "hold_bars": i - entry_idx}

        # 트레일링 활성화
        if pnl_pct >= trailing_activate_pct:
            trailing_active = True
        if price > peak:
            peak = price

        # 트레일링 청산
        if trailing_active and (peak - price) / peak >= trailing_stop_pct:
            return {"exit_idx": i, "exit_price": price, "pnl_pct": round(pnl_pct * 100, 3), "exit_reason": "trailing_stop", "hold_bars": i - entry_idx}

    # 강제 청산 (마지막 바)
    exit_idx = min(entry_idx + force_exit_bars, len(closes) - 1)
    exit_price = closes[exit_idx]
    pnl_pct = (exit_price - entry_price) / entry_price
    return {"exit_idx": exit_idx, "exit_price": exit_price, "pnl_pct": round(pnl_pct * 100, 3), "exit_reason": "force_exit", "hold_bars": exit_idx - entry_idx}


def run_backtest(
    start_date: str,
    end_date: str,
    min_price_change_pct: float = 2.0,
    max_price_change_pct: float = 15.0,
    min_volume_ratio: float = 1.5,
    min_rsi: float = 30.0,
    max_rsi: float = 65.0,
    stop_loss_pct: float = -0.015,
    trailing_activate_pct: float = 0.02,
    trailing_stop_pct: float = 0.01,
    universe_limit: int = 50,
) -> dict[str, Any]:
    """백테스트 실행.

    Args:
        start_date: YYYY-MM-DD 시작일
        end_date: YYYY-MM-DD 종료일
        min_price_change_pct: 진입 조건 — 최소 등락률 (%)
        max_price_change_pct: 진입 조건 — 최대 등락률 (%)
        min_volume_ratio: 진입 조건 — 최소 거래량 비율
        min_rsi / max_rsi: RSI 범위 조건
        stop_loss_pct: 손절 기준 (음수, 예: -0.015)
        trailing_activate_pct: 트레일링 활성 기준
        trailing_stop_pct: 트레일링 폭
        universe_limit: 검사할 종목 수
    """
    logger.info("START: Backtest start=%s end=%s universe=%d", start_date, end_date, universe_limit)
    symbols = _get_universe_symbols(universe_limit)
    if not symbols:
        return {"error": "유니버스 종목을 불러올 수 없습니다."}

    # pykrx 날짜 형식
    start_ym = start_date.replace("-", "")
    # 지표 계산용 추가 기간 (RSI 14일 + MA 20일 필요)
    dt_start = datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=45)
    fetch_start = dt_start.strftime("%Y%m%d")
    end_ym = end_date.replace("-", "")

    trades: list[dict[str, Any]] = []
    errors: list[str] = []

    for symbol in symbols:
        try:
            df = _pykrx_ohlcv(symbol, fetch_start, end_ym)
            if df is None or len(df) < 25:
                continue

            closes = list(df["종가"])
            volumes = list(df["거래량"])
            dates = [str(d)[:10].replace("-", "") for d in df.index]

            # start_date 이후 인덱스만 신호 발생 대상
            for i in range(22, len(closes)):
                bar_date = dates[i]
                if bar_date < start_ym:
                    continue

                # 조건 계산
                prev_close = closes[i - 1]
                today_close = closes[i]
                price_change = (today_close - prev_close) / prev_close * 100

                avg_vol20 = sum(volumes[i-20:i]) / 20 if i >= 20 else 0
                vol_ratio = volumes[i] / avg_vol20 if avg_vol20 > 0 else 0

                # RSI(14)
                from .technical_indicators import _calc_rsi
                rsi = _calc_rsi(closes[max(0, i-20):i+1]) or 50

                # 진입 조건 필터
                if not (min_price_change_pct <= price_change <= max_price_change_pct):
                    continue
                if vol_ratio < min_volume_ratio:
                    continue
                if not (min_rsi <= rsi <= max_rsi):
                    continue

                # 시뮬레이션
                result = _simulate_trade(
                    closes, i,
                    stop_loss_pct=stop_loss_pct,
                    trailing_activate_pct=trailing_activate_pct,
                    trailing_stop_pct=trailing_stop_pct,
                )
                trades.append({
                    "symbol": symbol,
                    "entry_date": bar_date,
                    "entry_price": today_close,
                    "price_change_pct": round(price_change, 2),
                    "volume_ratio": round(vol_ratio, 2),
                    "rsi14": rsi,
                    **result,
                })

        except Exception as e:
            errors.append(f"{symbol}: {e}")
            logger.warning("WARN: backtest symbol=%s error=%s", symbol, e)

    if not trades:
        return {"total": 0, "trades": [], "errors": errors, "message": "조건에 맞는 거래 없음"}

    pnls = [t["pnl_pct"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    avg_pnl = round(sum(pnls) / len(pnls), 3)
    win_rate = round(len(wins) / len(pnls) * 100, 1)

    # Sharpe (간이)
    import statistics
    std = statistics.stdev(pnls) if len(pnls) > 1 else 0
    sharpe = round(avg_pnl / std, 2) if std > 0 else 0

    # MDD
    cumulative = 0.0
    peak_cum = 0.0
    mdd = 0.0
    for p in pnls:
        cumulative += p
        if cumulative > peak_cum:
            peak_cum = cumulative
        dd = peak_cum - cumulative
        if dd > mdd:
            mdd = dd

    summary = {
        "total": len(trades),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate_pct": win_rate,
        "avg_pnl_pct": avg_pnl,
        "avg_win_pct": round(sum(wins) / len(wins), 3) if wins else 0,
        "avg_loss_pct": round(sum(losses) / len(losses), 3) if losses else 0,
        "sharpe_ratio": sharpe,
        "max_drawdown_pct": round(mdd, 3),
        "total_pnl_pct": round(sum(pnls), 2),
        "params": {
            "min_price_change_pct": min_price_change_pct,
            "max_price_change_pct": max_price_change_pct,
            "min_volume_ratio": min_volume_ratio,
            "rsi_range": [min_rsi, max_rsi],
            "stop_loss_pct": stop_loss_pct,
            "trailing_activate_pct": trailing_activate_pct,
            "trailing_stop_pct": trailing_stop_pct,
        },
        "period": {"start": start_date, "end": end_date},
        "errors": errors[:5],
    }

    logger.info(
        "SUCCESS: Backtest total=%d win_rate=%.1f%% avg_pnl=%.3f%%",
        len(trades), win_rate, avg_pnl,
    )
    return {**summary, "trades": trades[:200]}  # 최대 200건만 반환
```

---

## 작업 2: API 엔드포인트 생성

파일: `backend/api/routes/backtest.py` (신규 생성)

```python
"""백테스트 API."""
from __future__ import annotations
import logging
from fastapi import APIRouter, Query
router = APIRouter(prefix="/api/v1/backtest", tags=["backtest"])
logger = logging.getLogger("BacktestAPI")

@router.post("/run")
async def run_backtest(
    start_date: str = Query(..., description="YYYY-MM-DD"),
    end_date: str = Query(..., description="YYYY-MM-DD"),
    min_price_change_pct: float = Query(2.0),
    max_price_change_pct: float = Query(15.0),
    min_volume_ratio: float = Query(1.5),
    min_rsi: float = Query(30.0),
    max_rsi: float = Query(65.0),
    stop_loss_pct: float = Query(-0.015),
    trailing_activate_pct: float = Query(0.02),
    trailing_stop_pct: float = Query(0.01),
    universe_limit: int = Query(30, le=100),
) -> dict:
    """백테스트 실행 — pykrx 과거 데이터 기반."""
    logger.info("START: POST /api/v1/backtest/run start=%s end=%s", start_date, end_date)
    from ...services.engine.backtest import run_backtest as _run
    result = _run(
        start_date=start_date,
        end_date=end_date,
        min_price_change_pct=min_price_change_pct,
        max_price_change_pct=max_price_change_pct,
        min_volume_ratio=min_volume_ratio,
        min_rsi=min_rsi,
        max_rsi=max_rsi,
        stop_loss_pct=stop_loss_pct,
        trailing_activate_pct=trailing_activate_pct,
        trailing_stop_pct=trailing_stop_pct,
        universe_limit=universe_limit,
    )
    logger.info("SUCCESS: POST /api/v1/backtest/run total=%s", result.get("total", 0))
    return {"ok": True, "payload": result}

@router.get("/quick")
async def quick_backtest() -> dict:
    """최근 3개월 / 현재 설정값으로 빠른 백테스트."""
    from datetime import datetime, timedelta
    from ...services.settings_store import get_setting
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    min_pc = float(get_setting("engine.min_price_change_pct") or 2.0)
    stop_loss = float(get_setting("override_stop_loss_rate") or -0.015)
    trailing_act = float(get_setting("override_trailing_activate_rate") or 0.02)
    trailing_stop = float(get_setting("override_trailing_stop_rate") or 0.01)
    from ...services.engine.backtest import run_backtest as _run
    result = _run(
        start_date=start,
        end_date=end,
        min_price_change_pct=min_pc,
        stop_loss_pct=stop_loss,
        trailing_activate_pct=trailing_act,
        trailing_stop_pct=trailing_stop,
        universe_limit=30,
    )
    return {"ok": True, "payload": result}
```

---

## 작업 3: 라우터 등록

`backend/main.py`에서 backtest 라우터 import 및 등록:
```python
from .api.routes.backtest import router as backtest_router
app.include_router(backtest_router)
```

`backend/main.py`의 다른 router include 패턴을 참고해 동일하게 추가한다.

---

## 완료 기준

1. `py_compile` 통과 (backtest.py, routes/backtest.py, main.py)
2. 테스트:
   ```bash
   curl -X POST "http://127.0.0.1:8000/api/v1/backtest/quick"
   ```
   응답에 `win_rate_pct`, `avg_pnl_pct`, `total` 포함 확인
3. 최소 1건 이상 trade 시뮬레이션 결과 반환 확인
4. `GET /api/v1/backtest/quick` 도 동일하게 동작

결과: `docs/agent-comm/OUTBOX_CODEX_20260522_backtest.md`
