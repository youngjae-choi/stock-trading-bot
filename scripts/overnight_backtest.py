#!/usr/bin/env python3
"""H-ON 오버나잇 보유 백테스트 — docs/PREREG_20261016_overnight.md 규칙 그대로(읽기 전용).

  python scripts/overnight_backtest.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DAILY = ROOT / "data" / "market" / "daily"
INDEX = ROOT / "data" / "market" / "index" / "0001.parquet"
COST, STRESS = 0.23, 0.43
IS_END, OOS_START = "20251231", "20260101"
TOP_N, MIN_PX, MAX_GAP = 500, 5000.0, 0.30


def load() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    o, c, a, v = {}, {}, {}, {}
    for p in DAILY.glob("*.parquet"):
        d = pd.read_parquet(p).set_index("date")
        o[p.stem], c[p.stem], a[p.stem], v[p.stem] = d.open, d.close, d.amount, d.volume
    f = lambda x: pd.DataFrame(x).sort_index()  # noqa: E731
    return f(o), f(c), f(a), f(v)


def nw_t(x: np.ndarray, lag: int = 5) -> float:
    x = np.asarray(x, float)
    n = len(x)
    if n < 10:
        return float("nan")
    e = x - x.mean()
    s = (e @ e) / n
    for k in range(1, lag + 1):
        s += 2 * (1 - k / (lag + 1)) * (e[k:] @ e[:-k]) / n
    return float(x.mean() / np.sqrt(s / n))


def daily_returns(op, cl, am, vol) -> pd.Series:
    """t → 그날 매수(종가)·다음날 매도(시가) 포트폴리오 총수익(%, 비용 전)."""
    dates = list(cl.index)
    out = {}
    for i in range(1, len(dates) - 1):
        prev, t, nxt = dates[i - 1], dates[i], dates[i + 1]
        amt, pc = am.loc[prev], cl.loc[prev]
        elig = amt[(pc >= MIN_PX) & amt.notna()]
        uni = elig.sort_values(ascending=False).index[:TOP_N]
        uni = [s for s in uni if vol.at[t, s] > 0]
        r = op.loc[nxt, uni] / cl.loc[t, uni] - 1
        r = r[(r.abs() <= MAX_GAP) & r.notna() & (op.loc[nxt, uni] > 0)]
        if len(r) >= 50:
            out[t] = r.mean() * 100
    return pd.Series(out).sort_index()


def summarize(name: str, g: pd.Series) -> dict:
    net = g - COST
    return {"구간": name, "일수": len(g), "총수익": round(g.mean(), 3), "순수익": round(net.mean(), 3),
            "NW t": round(nw_t(net.values), 2), "스트레스 순수익": round((g - STRESS).mean(), 3),
            "승률": f"{(net > 0).mean():.0%}"}


def main() -> int:
    op, cl, am, vol = load()
    g = daily_returns(op, cl, am, vol)
    ins, oos = g[g.index <= IS_END], g[g.index >= OOS_START]
    rows = [summarize("IS", ins), summarize("OOS", oos)]
    print(pd.DataFrame(rows).to_string(index=False))
    o, i_ = rows[1], rows[0]
    if o["순수익"] > 0 and o["NW t"] >= 2.5 and i_["순수익"] > 0 and o["스트레스 순수익"] > 0:
        verdict = "통과"
    elif o["순수익"] > 0 and i_["순수익"] > 0 and o["NW t"] >= 1.0:
        verdict = "미결"
    else:
        verdict = "불통과"
    print("판정(OOS):", verdict)
    net = oos - COST
    eq = (1 + net / 100).cumprod()
    print(f"OOS 누적 {(eq.iloc[-1] - 1) * 100:+.1f}% · 최대낙폭 {((eq / eq.cummax()) - 1).min() * 100:.1f}% · 최악 1일 {net.min():+.2f}% ({net.idxmin()})")
    crash = g[(g.index >= "20261006") & (g.index <= "20261015")] - COST
    print("폭락 구간(10-06~10-15 매수일) 순수익/일:", crash.round(2).to_dict())
    if INDEX.exists():
        ix = pd.read_parquet(INDEX).set_index("date").sort_index()
        ion = (ix.open.shift(-1) / ix.close - 1) * 100
        both = pd.concat([g, ion.rename("ix")], axis=1, join="inner").dropna()
        bo = both[both.index >= OOS_START]
        print(f"참고: KOSPI 지수 오버나잇 OOS {bo.ix.mean():+.3f}%/일 · 전략 총수익 − 지수 = {(bo[0] - bo.ix).mean():+.3f}%/일 (n={len(bo)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
