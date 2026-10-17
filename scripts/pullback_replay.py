#!/usr/bin/env python3
"""리더 pullback(E6) 배포 로직 재생 — 배포된 _detect_leader_pullback을 실제 분봉에 돌려
"laggard 대신 강세 리더를 사서 돈을 냈을지"를 실증한다(장 마감 상태 최대 증명·read-only).

각 상승일에 대해: 09:30부터 종목별로 배포 검출함수를 전진 적용 → 첫 발동 바에 매수(1종목 1일 1회,
max_positions까지) → 하이브리드 트레일(Xc: +2%발동·고점-1.5%·손절-3%·13:30정지)로 청산. 결과를
그날 우리가 실제 산 laggard와 대조한다. 사용: python scripts/pullback_replay.py 2026-09-18 ...
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services.engine.momentum_entry import _detect_leader_pullback  # 배포된 실제 검출

DB = Path(__file__).resolve().parent.parent / "data" / "stock_trading_bot.sqlite3"
FLOOR, CEIL = -3.0, 1.0          # 배포 밴드(engine.entry_vwap_floor/ceiling_riskon)
TP_ACT, TRAIL, STOP = 2.0, 1.5, -3.0   # Xc 하이브리드 트레일(상승장)
COST, MAXPOS = 0.25, 8


def _conn():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True); c.row_factory = sqlite3.Row
    return c


def _mins(conn, d, sym):
    rows = conn.execute("SELECT bar_ts,open,high,low,close,volume FROM intraday_bars"
                        " WHERE trade_date=? AND symbol=? ORDER BY bar_ts,id", (d, sym)).fetchall()
    by = {}
    for r in rows:
        c = float(r["close"] or 0)
        if c <= 0:
            continue
        m = str(r["bar_ts"])[:4]
        b = by.get(m)
        v = float(r["volume"] or 0)
        if b is None:
            by[m] = {"bar_ts": m + "00", "open": float(r["open"] or c), "high": float(r["high"] or c),
                     "low": float(r["low"] or c), "close": c, "volume": v}
        else:
            b["high"] = max(b["high"], float(r["high"] or c)); b["low"] = min(b["low"], float(r["low"] or c))
            b["close"] = c; b["volume"] += v
    return [by[m] for m in sorted(by)]


def _exit(bars, ei):
    entry = bars[ei]["close"]; peak = entry
    for j in range(ei + 1, len(bars)):
        b = bars[j]; peak = max(peak, b["high"])
        lo = (b["low"] / entry - 1) * 100
        if lo <= STOP:
            return STOP, b["bar_ts"]
        if (peak / entry - 1) * 100 >= TP_ACT:
            trail = peak * (1 - TRAIL / 100)
            if b["low"] <= trail:
                return (trail / entry - 1) * 100, b["bar_ts"]
        if b["bar_ts"] >= "133000":
            return (b["close"] / entry - 1) * 100, b["bar_ts"]
    return (bars[-1]["close"] / entry - 1) * 100, bars[-1]["bar_ts"]


def replay(d):
    conn = _conn()
    syms = [r["symbol"] for r in conn.execute(
        "SELECT symbol FROM intraday_bars WHERE trade_date=? GROUP BY symbol"
        " HAVING SUM(volume)>=300000 AND COUNT(*)>=50", (d,))]
    trades = []
    for sym in syms:
        bars = _mins(conn, d, sym)
        if len(bars) < 5 or bars[0]["bar_ts"] > "093500":
            continue
        for i in range(len(bars)):
            if bars[i]["bar_ts"] < "093000":
                continue
            sig = _detect_leader_pullback(bars[: i + 1], FLOOR, CEIL, 0.0)  # 배포 로직 그대로
            if sig:
                ret, xt = _exit(bars, i)
                trades.append({"sym": sym, "t": bars[i]["bar_ts"][:4], "cfo": sig[3],
                               "ret": ret - COST, "xt": xt[:4]})
                break
    trades.sort(key=lambda x: x["t"])
    trades = trades[:MAXPOS]

    # 실제 우리가 산 것(laggard 대조)
    actual = conn.execute(
        "WITH b AS (SELECT symbol,AVG(price) bp FROM fills WHERE side='buy' AND substr(filled_at,1,10)=? GROUP BY symbol),"
        " o AS (SELECT symbol,open FROM intraday_bars WHERE trade_date=? AND (symbol,bar_ts) IN"
        " (SELECT symbol,MIN(bar_ts) FROM intraday_bars WHERE trade_date=? GROUP BY symbol))"
        " SELECT b.symbol,(b.bp/o.open-1)*100 cfo FROM b JOIN o ON o.symbol=b.symbol", (d, d, d)).fetchall()

    print(f"\n{'='*66}\n{d} — 배포 pullback 로직 재생 (강세 리더 매수)\n{'='*66}")
    if trades:
        print(f"  {'종목':<8}{'매수시각':>7}{'cfo':>7}{'청산':>7}{'손익%':>8}")
        for t in trades:
            print(f"  {t['sym']:<8}{t['t']:>7}{t['cfo']:>+6.1f}%{t['xt']:>7}{t['ret']:>+7.2f}%")
        avg = sum(t["ret"] for t in trades) / len(trades)
        wr = 100 * sum(1 for t in trades if t["ret"] > 0) / len(trades)
        print(f"  → pullback {len(trades)}건 · 승률 {wr:.0f}% · 평균 {avg:+.2f}%/거래 (균등배분 일수익≈{avg:+.2f}%)")
    else:
        print("  pullback 발동 0건 (그날 강세리더가 VWAP밴드에 안 들어옴)")
    lag = [a for a in actual if a["cfo"] <= 0]
    print(f"  vs 실제 매수: {len(actual)}건 중 laggard(cfo≤0) {len(lag)}건"
          + (f" (평균 cfo {sum(a['cfo'] for a in lag)/len(lag):+.1f}%)" if lag else ""))


if __name__ == "__main__":
    for d in (sys.argv[1:] or ["2026-09-18", "2026-09-21", "2026-09-22"]):
        replay(d)
    print()
