#!/usr/bin/env python3
"""청산(exit) 백테스트 — 진입 후 가격경로를 재생해 청산전략별 순기대값을 비교한다.

진입 엣지(edge_backtest.py)가 '무엇을 살까'를 본다면, 이 도구는 '어떻게 팔까'를 본다.
과거 실매수(진입)마다 진입 이후 intraday_bars(10초봉) 가격경로를 재생하고, 주어진 청산설정
(초기손절·scaleout 목표/비율·트레일 활성/폭)을 적용해 라운드트립 손익%를 재계산한다.
여러 설정을 스윕해 '승자를 더 태우면 순수익이 오르나'를 수치로 검증한다.

읽기 전용(라이브 DB read-only). 매매/서버에 영향 없음.

핵심 질문: +2% scaleout이 승리를 캡한다 → 늦게 수확(+3%)하거나 덜 확정(35%)하면 순기대값이?

사용:
  python scripts/exit_backtest.py                       # 기본 스윕(현행 vs 대안들)
  python scripts/exit_backtest.py --start 2026-08-01 --end 2026-08-31
  python scripts/exit_backtest.py --entry-filter "vwap_dist<=-1"   # 눌림 진입만 대상

가정(단순화, 보수적):
  · 한 바 안에서 손절(저가)이 scaleout(고가)보다 먼저 일어난 것으로 본다(보수적).
  · 트레일 활성 후 잔량은 peak×(1-트레일폭)에서 청산, 그 아래로는 초기손절가가 바닥.
  · 왕복비용 0.23%(수수료 0.015%×2 + 거래세 0.20%)를 순기대값에서 차감.
"""
from __future__ import annotations

import argparse
import sqlite3
import statistics
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "stock_trading_bot.sqlite3"
ROUNDTRIP_COST_PCT = 0.23  # 수수료 0.015%×2 + 거래세 0.20%


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def _hhmmss(created_at: str) -> str:
    return str(created_at)[11:19].replace(":", "")


def load_entries(conn, start, end):
    """실체결 매수(진입). 같은 종목·날짜의 첫 매수만(스케일인은 대표 1건). 진입 후 바가 있어야 함."""
    rows = conn.execute(
        """
        SELECT trade_date, symbol, price, created_at
        FROM trading_orders
        WHERE trade_date BETWEEN ? AND ? AND status IN ('filled','partial')
          AND side='buy' AND price > 0
        ORDER BY symbol, trade_date, created_at
        """,
        (start, end),
    ).fetchall()
    seen: set = set()
    entries = []
    for r in rows:
        key = (r["trade_date"], r["symbol"])
        if key in seen:
            continue
        seen.add(key)
        entries.append({
            "date": r["trade_date"], "symbol": r["symbol"],
            "entry_ts": _hhmmss(r["created_at"]), "entry_price": float(r["price"]),
        })
    return entries


def load_path(conn, date, sym, entry_ts):
    """진입 이후(bar_ts > entry_ts) 가격경로."""
    return conn.execute(
        "SELECT high, low, close FROM intraday_bars "
        "WHERE trade_date=? AND symbol=? AND bar_ts > ? ORDER BY bar_ts",
        (date, sym, entry_ts),
    ).fetchall()


def entry_vwap_dist(conn, date, sym, entry_ts, entry_price):
    """진입 시점 vwap_dist(%) — entry-filter용."""
    bars = conn.execute(
        "SELECT close, volume FROM intraday_bars WHERE trade_date=? AND symbol=? AND bar_ts<=? ORDER BY bar_ts",
        (date, sym, entry_ts),
    ).fetchall()
    vv = sum((b["volume"] or 0) for b in bars)
    if vv <= 0:
        return None
    vwap = sum((b["close"] or 0) * (b["volume"] or 0) for b in bars) / vv
    return (entry_price / vwap - 1) * 100 if vwap else None


def simulate_exit(path, entry_price, cfg):
    """진입 후 경로에 청산설정 적용 → 라운드트립 손익%(가중). 값은 소수%(예 +2.0)."""
    P = entry_price
    stop_price = P * (1 + cfg["stop_loss"])           # 초기손절가
    so_price = P * (1 + cfg["scaleout_target"])       # scaleout 목표가
    so_ratio = cfg["scaleout_ratio"]
    tr_act = cfg["trailing_activate"]
    tr_stop = cfg["trailing_stop"]

    remaining = 1.0
    realized = 0.0     # 가중 수익률(소수, 1.0=100%)
    scaled = False
    trailing_on = False
    peak = P

    for b in path:
        hi = b["high"] or 0.0
        lo = b["low"] or 0.0
        if hi <= 0 or lo <= 0:
            continue
        # 1) 초기손절 (보수적: 저가 먼저) — 잔량 전량 청산
        exit_floor = stop_price
        if trailing_on:
            exit_floor = max(stop_price, peak * (1 - tr_stop))
        if lo <= exit_floor and remaining > 0:
            realized += remaining * (exit_floor / P - 1)
            return (realized - 0.0) * 100
        # 2) scaleout
        if not scaled and hi >= so_price:
            realized += so_ratio * (so_price / P - 1)
            remaining -= so_ratio
            scaled = True
        # 3) 트레일 활성
        peak = max(peak, hi)
        if not trailing_on and hi >= P * (1 + tr_act):
            trailing_on = True
    # EOD: 잔량 종가 청산
    if remaining > 0 and path:
        last_close = path[-1]["close"] or P
        realized += remaining * (last_close / P - 1)
    return realized * 100


_CONFIGS = {
    "현행(+2%/50%·trail3.5/2.5)": dict(stop_loss=-0.04, scaleout_target=0.02, scaleout_ratio=0.50, trailing_activate=0.035, trailing_stop=0.025),
    "늦수확(+3%/50%)":            dict(stop_loss=-0.04, scaleout_target=0.03, scaleout_ratio=0.50, trailing_activate=0.045, trailing_stop=0.025),
    "덜확정(+2%/35%)":           dict(stop_loss=-0.04, scaleout_target=0.02, scaleout_ratio=0.35, trailing_activate=0.035, trailing_stop=0.025),
    "러너극대(+3%/30%)":         dict(stop_loss=-0.04, scaleout_target=0.03, scaleout_ratio=0.30, trailing_activate=0.045, trailing_stop=0.03),
    "넓은트레일(+2%/50%·2.5/3.5)": dict(stop_loss=-0.04, scaleout_target=0.02, scaleout_ratio=0.50, trailing_activate=0.035, trailing_stop=0.035),
    "타이트손절(-3%)":            dict(stop_loss=-0.03, scaleout_target=0.02, scaleout_ratio=0.50, trailing_activate=0.035, trailing_stop=0.025),
    "넓은손절(-5%)":              dict(stop_loss=-0.05, scaleout_target=0.02, scaleout_ratio=0.50, trailing_activate=0.035, trailing_stop=0.025),
}


def run(entries, cfg):
    pnls = [simulate_exit(e["path"], e["entry_price"], cfg) for e in entries]
    n = len(pnls)
    wins = [p for p in pnls if p > 0]
    avg = statistics.mean(pnls) if pnls else 0.0
    net = avg - ROUNDTRIP_COST_PCT
    return {
        "n": n, "win_rate": len(wins) / n * 100 if n else 0,
        "avg_gross": avg, "avg_net": net,
        "avg_win": statistics.mean(wins) if wins else 0,
        "avg_loss": statistics.mean([p for p in pnls if p <= 0]) if (n - len(wins)) else 0,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-07-23")
    ap.add_argument("--end", default="2026-12-31")
    ap.add_argument("--entry-filter", default="", help="진입 대상 필터, 예: 'vwap_dist<=-1'")
    args = ap.parse_args()

    conn = _conn()
    entries = load_entries(conn, args.start, args.end)
    # 경로 부착 + (옵션) 진입필터
    prepared = []
    for e in entries:
        path = load_path(conn, e["date"], e["symbol"], e["entry_ts"])
        if not path:
            continue
        if args.entry_filter:
            vd = entry_vwap_dist(conn, e["date"], e["symbol"], e["entry_ts"], e["entry_price"])
            scope = {"vwap_dist": vd}
            try:
                if vd is None or not eval(args.entry_filter, {"__builtins__": {}}, scope):
                    continue
            except Exception:
                continue
        e["path"] = path
        prepared.append(e)

    print(f"\n=== 청산 백테스트 — 진입 {len(prepared)}건 (경로재생) · 왕복비용 {ROUNDTRIP_COST_PCT}% 차감 ===")
    if args.entry_filter:
        print(f"    진입필터: {args.entry_filter}")
    print(f"{'청산설정':<30} {'건수':>5} {'승률':>7} {'평균총':>8} {'평균순':>8} {'평균승':>7} {'평균패':>7}")
    print("-" * 78)
    base = None
    for label, cfg in _CONFIGS.items():
        r = run(prepared, cfg)
        if base is None:
            base = r["avg_net"]
        delta = r["avg_net"] - base
        mark = "" if label.startswith("현행") else (f"  ({'+' if delta >= 0 else ''}{delta:.3f}%p)")
        print(f"{label:<30} {r['n']:>5} {r['win_rate']:>6.1f}% {r['avg_gross']:>+7.3f}% {r['avg_net']:>+7.3f}% {r['avg_win']:>+6.2f}% {r['avg_loss']:>+6.2f}%{mark}")
    print("\n※ 평균순 = 평균총 - 왕복비용 0.23%. 현행 대비 개선폭(%p) 표시. 순기대값이 높을수록 좋음.")


if __name__ == "__main__":
    main()
