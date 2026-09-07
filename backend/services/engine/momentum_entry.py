"""모멘텀 진입(실전) — 리더(ORB 돌파+VWAP위+상대강도)를 실제 매수한다.

momentum_backtest 발견(강세4 돌파 = 승률 83%·순 +1.36%, 전 레짐)을 실전 적용(2026-09-07, 모의계좌).
우리 눌림전략과 **독립 경로**로 유니버스를 스캔해, 돌파 리더를 `_emit_signal(momentum=True)`로 매수한다.
모멘텀은 mean-reversion 게이트(VWAP 눌림/시가대비 추격금지/conviction)를 **우회**하되, 안전 게이트
(레버리지·ETN·손실스트릭·급락방어·하락전환·exec_start·preflight 배포캡/포지션한도)는 그대로 통과해야 한다.

감지 규칙(백테스트 동일): 시가~OR_END 고가를 exec_start 이후 첫 상향돌파 & 현재가 > 누적VWAP &
시가대비 ≥ rs_min. 종목당 하루 1회. 이미 보유/당일 매수/기록된 종목은 스킵(중복 방지).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from ..db import get_connection
from ..settings_store import get_setting

logger = logging.getLogger("MomentumEntry")
KST = ZoneInfo("Asia/Seoul")


def _f(getter: Callable, key: str, default: float) -> float:
    try:
        return float(getter(key, default) or default)
    except (TypeError, ValueError):
        return default


def _detect_breakout(bars: list, or_end: str, exec_start: str, rs_min: float):
    """첫 모멘텀 돌파 → (entry_ts, breakout_price, vwap, change_from_open) 또는 None (백테스트 동일)."""
    if not bars:
        return None
    day_open = (bars[0]["open"] or bars[0]["close"] or 0)
    if day_open <= 0:
        return None
    or_highs = [b["high"] or 0 for b in bars if b["bar_ts"] < or_end]
    or_high = max(or_highs) if or_highs else 0
    if or_high <= 0:
        return None
    pv = vv = 0.0
    for b in bars:
        c = b["close"] or 0
        v = b["volume"] or 0
        pv += c * v
        vv += v
        vwap = pv / vv if vv > 0 else c
        if b["bar_ts"] >= exec_start and (b["high"] or 0) > or_high and c > vwap:
            cfo = (c / day_open - 1) * 100
            if cfo >= rs_min:
                return b["bar_ts"], round(or_high, 2), round(vwap, 2), round(cfo, 2)
    return None


def _ensure_table(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS momentum_signals ("
        " id INTEGER PRIMARY KEY, trade_date TEXT NOT NULL, symbol TEXT NOT NULL,"
        " detected_at TEXT NOT NULL, entry_ts TEXT, price REAL, last_close REAL, vwap REAL,"
        " change_from_open REAL, bought INTEGER NOT NULL DEFAULT 0, reason TEXT,"
        " UNIQUE(trade_date, symbol))"
    )


def _name_of(conn, symbol: str) -> str:
    for tbl, col in (("trading_signals", "name"), ("trading_orders", "name")):
        try:
            r = conn.execute(f"SELECT {col} FROM {tbl} WHERE symbol=? AND {col} IS NOT NULL AND {col}!='' "
                             "ORDER BY created_at DESC LIMIT 1", (symbol,)).fetchone()
            if r and r[0]:
                return str(r[0])
        except Exception:
            continue
    return ""


async def run_momentum_entries(trade_date: str | None = None, *, getter: Callable = get_setting) -> dict[str, Any]:
    """유니버스 모멘텀 리더 감지 → 실제 매수(_emit_signal momentum=True). 반환: {enabled, scanned, entered}.

    momentum.enabled=false면 no-op. 안전: 이미 보유/당일 매수/기록 종목 스킵, 매수는 preflight
    (배포캡·포지션한도·긴급정지·손실한도)와 _emit_signal 안전게이트(레버리지/ETN·손실스트릭 등)를 통과해야 함.
    """
    try:
        if str(getter("momentum.enabled", True)).lower() in ("false", "0", "no"):
            return {"enabled": False, "scanned": 0, "entered": 0}
    except Exception:
        pass
    td = trade_date or datetime.now(KST).strftime("%Y-%m-%d")
    # exec_start 이전이면 스킵(장 초반 OR 형성 전)
    now_hm = datetime.now(KST).strftime("%H%M%S")
    exec_start = str(getter("momentum.exec_start", "093000") or "093000")
    if now_hm < exec_start:
        return {"enabled": True, "scanned": 0, "entered": 0, "reason": "before_exec_start"}
    rs_min = _f(getter, "momentum.rs_min", 4.0)
    or_end = str(getter("momentum.or_end", "093000") or "093000")
    min_vol = _f(getter, "momentum.min_vol", 300000)
    min_bars = int(_f(getter, "momentum.min_bars", 50))
    premium = _f(getter, "momentum.entry_premium_pct", 0.3) / 100.0  # 체결력: 돌파가 소폭 위 지정가
    now_iso = datetime.now(KST).isoformat()

    # 중복 방지 집합: 보유 + 당일 매수 + 이미 기록
    from .position_manager import position_manager
    held = {str(p.get("symbol") or "").strip() for p in position_manager.get_positions()}
    scanned = entered = 0
    candidates: list[tuple[str, float, float, float, str]] = []  # (sym, price, vwap, cfo, entry_ts)
    try:
        with get_connection() as conn:
            _ensure_table(conn)
            already = {r["symbol"] for r in conn.execute(
                "SELECT symbol FROM momentum_signals WHERE trade_date=?", (td,))}
            bought_today = {r["symbol"] for r in conn.execute(
                "SELECT DISTINCT symbol FROM trading_orders WHERE trade_date=? AND side='buy'", (td,))}
            uni = conn.execute(
                "SELECT symbol FROM intraday_bars WHERE trade_date=? GROUP BY symbol"
                " HAVING SUM(volume)>=? AND COUNT(*)>=?", (td, min_vol, min_bars)).fetchall()
            for row in uni:
                sym = row["symbol"]
                scanned += 1
                if sym in already or sym in held or sym in bought_today:
                    continue
                bars = conn.execute(
                    "SELECT bar_ts, open, high, low, close, volume FROM intraday_bars"
                    " WHERE trade_date=? AND symbol=? ORDER BY bar_ts", (td, sym)).fetchall()
                sig = _detect_breakout([dict(b) for b in bars], or_end, exec_start, rs_min)
                if not sig:
                    continue
                entry_ts, or_high, vwap, cfo = sig
                last_close = float(bars[-1]["close"] or or_high)
                price = round(max(or_high, last_close) * (1 + premium), 2)  # 체결력 위해 소폭 프리미엄
                conn.execute(
                    "INSERT OR IGNORE INTO momentum_signals"
                    " (trade_date, symbol, detected_at, entry_ts, price, last_close, vwap, change_from_open)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (td, sym, now_iso, entry_ts, price, last_close, vwap, cfo))
                candidates.append((sym, price, vwap, cfo, entry_ts))
            conn.commit()
    except Exception as exc:
        logger.warning("WARN: [MomentumEntry] 스캔 실패(fail-open) — %s", exc)
        return {"enabled": True, "scanned": scanned, "entered": 0}

    # 매수 실행 — _emit_signal(momentum=True): 눌림게이트 우회, 안전게이트·preflight 통과
    from .decision_engine import decision_engine
    for sym, price, vwap, cfo, entry_ts in candidates:
        try:
            with get_connection() as conn:
                name = _name_of(conn, sym)
            logger.warning(
                "MOMENTUM-BUY: 리더 매수 시도 symbol=%s name=%s 지정가=%.0f 시가대비=%+.2f%% vwap=%.0f",
                sym, name, price, cfo, vwap)
            await decision_engine._emit_signal(sym, {"name": name, "confidence": 0.7}, price, {"momentum": True})
            entered += 1
            with get_connection() as conn:
                conn.execute("UPDATE momentum_signals SET bought=1 WHERE trade_date=? AND symbol=?", (td, sym))
                conn.commit()
        except Exception as exc:
            logger.warning("WARN: [MomentumEntry] 매수 실패 symbol=%s — %s", sym, exc)
            try:
                with get_connection() as conn:
                    conn.execute("UPDATE momentum_signals SET reason=? WHERE trade_date=? AND symbol=?",
                                 (str(exc)[:80], td, sym))
                    conn.commit()
            except Exception:
                pass
    if candidates:
        logger.info("SUCCESS: [MomentumEntry] td=%s scanned=%d 신규리더=%d 매수시도=%d", td, scanned, len(candidates), entered)
    return {"enabled": True, "scanned": scanned, "entered": entered}
