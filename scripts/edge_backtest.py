#!/usr/bin/env python3
"""진입 엣지 발굴·백테스트 — intraday_bars로 과거 진입의 미시구조를 복원.

우리가 실제로 한 매수→매도 라운드트립을 승자/패자로 나누고, 각 진입 시점의
피처(VWAP거리·고점거리·등락률·거래량급증·체결강도)를 intraday_bars에서 복원해
'무엇이 승패를 갈랐나'를 데이터로 발굴한다. 가설 필터의 성과도 백테스트한다.

읽기 전용(라이브 DB read-only). 매매/서버에 영향 없음.

사용:
  python scripts/edge_backtest.py                    # 발굴: 승자 vs 패자 피처 비교
  python scripts/edge_backtest.py --filter "high_dist <= -1 and change_rate <= 4"
  python scripts/edge_backtest.py --start 2026-08-01 --end 2026-08-14 --loss-only
피처:
  vwap_dist(%)  = 진입가/VWAP - 1   (>0 VWAP위 · <0 아래)
  high_dist(%)  = 진입가/일중고가 - 1 (~0 꼭지추격 · <0 되돌림/눌림)
  change_rate(%)= 진입가/당일시가 - 1 (얼마나 오른 걸 샀나)
  vol_surge     = 진입바 거래량 / 평균바 거래량
  gangdo        = 진입바 shnu_rate (보조; 스케일 주의)
"""
from __future__ import annotations

import argparse
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "stock_trading_bot.sqlite3"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def _hhmmss(created_at: str) -> str:
    return str(created_at)[11:19].replace(":", "")


def load_roundtrips(conn, start, end):
    """실체결 매수→(다음)매도 라운드트립. pnl_pct·win·exit_reason 포함."""
    rows = conn.execute(
        """
        SELECT trade_date, symbol, side, price, reason, created_at
        FROM trading_orders
        WHERE trade_date BETWEEN ? AND ? AND status IN ('filled','partial')
          AND side IN ('buy','sell') AND price > 0
        ORDER BY symbol, trade_date, created_at
        """,
        (start, end),
    ).fetchall()
    seq = defaultdict(list)
    for r in rows:
        seq[(r["trade_date"], r["symbol"])].append(dict(r))
    trades = []
    for (date, sym), orders in seq.items():
        sells = [o for o in orders if o["side"] == "sell"]
        si = 0
        for b in (o for o in orders if o["side"] == "buy"):
            while si < len(sells) and sells[si]["created_at"] <= b["created_at"]:
                si += 1
            if si >= len(sells):
                break
            s = sells[si]
            si += 1
            pnl = (s["price"] - b["price"]) / b["price"] * 100.0
            trades.append({
                "date": date, "symbol": sym, "entry_ts": _hhmmss(b["created_at"]),
                "entry_price": b["price"], "exit_price": s["price"],
                "exit_reason": s["reason"], "pnl_pct": round(pnl, 2), "win": pnl > 0,
            })
    return trades


def entry_features(conn, date, sym, entry_ts, entry_price):
    """진입 시점(bar_ts<=entry_ts) 바들로 미시구조 피처 복원."""
    bars = conn.execute(
        "SELECT open, high, low, close, volume, shnu_rate FROM intraday_bars "
        "WHERE trade_date=? AND symbol=? AND bar_ts<=? ORDER BY bar_ts",
        (date, sym, entry_ts),
    ).fetchall()
    if not bars:
        return None
    vv = sum((b["volume"] or 0) for b in bars)
    vwap = (sum((b["close"] or 0) * (b["volume"] or 0) for b in bars) / vv) if vv > 0 else None
    day_high = max((b["high"] or 0) for b in bars)
    day_open = bars[0]["open"] or 0
    avg_vol = vv / len(bars) if bars else 0
    last_vol = bars[-1]["volume"] or 0

    # ── P2 반등/지지 포착 피처 (진입 직전 10~20바 미시구조) ──
    vols = [b["volume"] or 0 for b in bars]
    closes = [b["close"] or 0 for b in bars]
    last = bars[-1]
    # 1) 저점 대비 회복(%) — 최근 10바 최저가 대비 진입가가 얼마나 올라왔나. 0≈바닥매수(아직 하락중),
    #    +↑=반등 시작 후 매수. "떨어지는 칼 vs 반등 포착"을 직접 가르는 핵심 피처.
    win10 = bars[-10:]
    recent_low = min((b["low"] or 0) for b in win10) if win10 else 0
    recovery_from_low = round((entry_price / recent_low - 1) * 100, 2) if recent_low > 0 else None
    # 2) 진입봉 캔들 위치 [0,1] — (진입가-저가)/(고가-저가). 1=고가끝(반등 마감·강), 0=저가끝(약세).
    _lh = (last["high"] or 0) - (last["low"] or 0)
    entry_bar_pos = round((entry_price - (last["low"] or 0)) / _lh, 2) if _lh > 0 else None
    # 3) 거래량 마름 — 최근5바 평균 / 그전 5~15바 평균. <1=조정 중 거래량 감소(건전한 눌림).
    _r5 = vols[-5:]
    _prior = vols[-15:-5]
    _m5 = sum(_r5) / len(_r5) if _r5 else 0
    _mp = sum(_prior) / len(_prior) if _prior else 0
    vol_dryup = round(_m5 / _mp, 2) if _mp > 0 else None
    # 4) 단기 MA(20바) 이격(%) — 진입가 vs 최근20바 종가평균. 0 근처=이평 지지 부근 매수.
    _maw = closes[-20:]
    _ma20 = sum(_maw) / len(_maw) if _maw else 0
    ma20_dist = round((entry_price / _ma20 - 1) * 100, 2) if _ma20 > 0 else None

    return {
        "vwap_dist": round((entry_price / vwap - 1) * 100, 2) if vwap else None,
        "high_dist": round((entry_price / day_high - 1) * 100, 2) if day_high else None,
        "change_rate": round((entry_price / day_open - 1) * 100, 2) if day_open else None,
        "vol_surge": round(last_vol / avg_vol, 2) if avg_vol > 0 else None,
        "gangdo": round(bars[-1]["shnu_rate"] or 0, 4),
        "recovery_from_low": recovery_from_low,
        "entry_bar_pos": entry_bar_pos,
        "vol_dryup": vol_dryup,
        "ma20_dist": ma20_dist,
        "n_bars": len(bars),
    }


_FEATURES = ["vwap_dist", "high_dist", "change_rate", "vol_surge", "gangdo",
             "recovery_from_low", "entry_bar_pos", "vol_dryup", "ma20_dist"]


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), 2) if xs else None


def _median(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 2) if xs else None


def enrich(conn, trades):
    out = []
    for t in trades:
        f = entry_features(conn, t["date"], t["symbol"], t["entry_ts"], t["entry_price"])
        if f is None:
            continue
        out.append({**t, **f})
    return out


def discovery(trades):
    W = [t for t in trades if t["win"]]
    L = [t for t in trades if not t["win"]]
    print(f"\n=== 엣지 발굴 — 라운드트립 {len(trades)}건 (승 {len(W)} · 패 {len(L)}, 승률 {len(W)/max(len(trades),1)*100:.1f}%) ===")
    print(f"평균 손익: 승 {_mean([t['pnl_pct'] for t in W])}% · 패 {_mean([t['pnl_pct'] for t in L])}%")
    print(f"\n{'피처':<12}{'승자 평균':>12}{'패자 평균':>12}{'승-패 차':>12}   해석")
    print("-" * 72)
    for f in _FEATURES:
        wm, lm = _mean([t.get(f) for t in W]), _mean([t.get(f) for t in L])
        diff = round(wm - lm, 2) if (wm is not None and lm is not None) else None
        hint = ""
        if diff is not None and abs(diff) >= 0.3:
            hint = "★ 분리력 있음" if f != "gangdo" else "★(체결강도 스케일주의)"
        print(f"{f:<12}{str(wm):>12}{str(lm):>12}{str(diff):>12}   {hint}")
    # 청산사유별
    print("\n청산사유별 승률:")
    by_reason = defaultdict(lambda: [0, 0])
    for t in trades:
        by_reason[t["exit_reason"] or "-"][0 if t["win"] else 1] += 1
    for r, (w, l) in sorted(by_reason.items(), key=lambda x: -(x[1][0] + x[1][1])):
        n = w + l
        print(f"  {r:<28} {w:>3}승 {l:>3}패  승률 {w/max(n,1)*100:>5.1f}%")


def backtest(trades, expr):
    import math  # noqa: F401 (필터에서 쓸 수 있게)
    sel = []
    for t in trades:
        try:
            if eval(expr, {"__builtins__": {}}, {k: t.get(k) for k in _FEATURES}):
                sel.append(t)
        except Exception:
            continue
    base_wr = sum(1 for t in trades if t["win"]) / max(len(trades), 1) * 100
    base_pnl = _mean([t["pnl_pct"] for t in trades])
    sw = sum(1 for t in sel if t["win"])
    print(f"\n=== 백테스트: filter=\"{expr}\" ===")
    print(f"선택 {len(sel)}/{len(trades)}건 · 승률 {sw/max(len(sel),1)*100:.1f}% (전체 {base_wr:.1f}%) · 평균손익 {_mean([t['pnl_pct'] for t in sel])}% (전체 {base_pnl}%)")
    print(f"→ 승률 {'개선' if sel and sw/max(len(sel),1) > base_wr/100 else '악화/무변'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-07-23")
    ap.add_argument("--end", default="2026-12-31")
    ap.add_argument("--filter", default="")
    args = ap.parse_args()
    with _conn() as conn:
        trades = enrich(conn, load_roundtrips(conn, args.start, args.end))
    if not trades:
        print("라운드트립 없음"); return
    discovery(trades)
    if args.filter:
        backtest(trades, args.filter)


if __name__ == "__main__":
    main()
