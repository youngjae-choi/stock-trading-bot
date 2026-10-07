#!/usr/bin/env python3
"""유튜브 채널 전략 2건 백테스트 — docs/PREREG_20261007_youtube_strategies.md 와 동일 규칙 (읽기 전용).

  .venv/bin/python scripts/youtube_strategy_backtest.py [--out data/market/bt]

P1 주도주 눌림목 / P2 신고가 돌파 후 지지. 진단용 V1·V2는 판정에서 제외한다.
규칙·파라미터는 사전등록 문서가 SSOT다. 여기서 바꾸면 새 가설이다.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent / "data" / "market"
IS_END = "20260430"
COST_BASE, COST_STRESS = 0.0023, 0.0043
OPEN_MIN, FORCE_MIN, CUTOFF_MIN = 9 * 60, 15 * 60 + 10, 15 * 60 + 20  # 15:20 이후(단일가) 봉 제외
MIN_PRICE, JUMP_LIMIT = 5000.0, 0.15
STOP_PCT = 0.03

_daily: dict[str, pd.DataFrame | None] = {}


def daily_feats(sym: str) -> pd.DataFrame | None:
    """일봉 파생(모두 해당 행 날짜 종가 시점까지의 정보). 수정주가."""
    if sym in _daily:
        return _daily[sym]
    p = ROOT / "daily" / f"{sym}.parquet"
    if not p.exists():
        _daily[sym] = None
        return None
    d = pd.read_parquet(p).sort_values("date").reset_index(drop=True)
    d = d[d.close > 0].reset_index(drop=True)
    if len(d) < 70:
        _daily[sym] = None
        return None
    c = d.close
    f = pd.DataFrame({"date": d.date, "close": c, "high": d.high, "vol": d.volume})
    f["ma20"], f["ma60"] = c.rolling(20).mean(), c.rolling(60).mean()
    f["ma20_l5"] = f.ma20.shift(5)
    f["ret20"] = c / c.shift(20) - 1
    f["dev"] = c / f.ma20 - 1
    # 돌파: 종가 > 직전 60일(당일 제외) 최고 고가. L = 그 최고 고가
    prior_hi = d.high.shift(1).rolling(60).max()
    f["L"] = prior_hi
    f["brk"] = (c > prior_hi) & ((c / c.shift(1) - 1) <= 0.15) & (d.volume >= 1.5 * d.volume.shift(1).rolling(20).mean())
    _daily[sym] = f
    return f


def prev_row(f: pd.DataFrame, day: str):
    i = int(np.searchsorted(f.date.values, day, side="left")) - 1
    return (i, f.iloc[i]) if i >= 59 else (None, None)


class SymDay:
    """종목-일 분봉 배열 + 5분봉(완성 시각 기준) 파생."""

    def __init__(self, g: pd.DataFrame):
        g = g.sort_values("time")
        t = g.time.astype(str).values
        tm = np.array([int(x[:2]) * 60 + int(x[2:]) for x in t])
        keep = tm < CUTOFF_MIN
        self.tm, self.o, self.h, self.l, self.c = (g[k].values[keep] if k != "tm" else tm[keep] for k in ("tm", "open", "high", "low", "close"))
        self.n = len(self.tm)
        self.ok = self.n >= 60
        if self.ok and self.n > 1:
            r = np.abs(self.c[1:] / np.where(self.c[:-1] > 0, self.c[:-1], np.nan) - 1)
            if np.nanmax(r) > JUMP_LIMIT:
                self.ok = False
        self._b = None

    def five(self):
        if self._b is not None:
            return self._b
        nb = (CUTOFF_MIN - OPEN_MIN) // 5
        c5, h5, l5 = np.full(nb, np.nan), np.full(nb, np.nan), np.full(nb, np.nan)
        bk = (self.tm - OPEN_MIN) // 5
        for b in range(nb):
            m = bk == b
            if m.any():
                c5[b], h5[b], l5[b] = self.c[m][-1], self.h[m].max(), self.l[m].min()
        last = np.nan
        for b in range(nb):  # 빈 구간 = 직전 종가로 채움
            if np.isnan(c5[b]):
                c5[b] = h5[b] = l5[b] = last
            else:
                last = c5[b]
        first = np.where(~np.isnan(c5))[0]
        ma = np.full(nb, np.nan)
        for b in range(19, nb):
            w = c5[b - 19:b + 1]
            if not np.isnan(w).any():
                ma[b] = w.mean()
        self._b = (c5, h5, l5, ma)
        return self._b

    def bar_at(self, minute: int, tol: int = 3):
        """minute 이후 첫 1분봉 인덱스(공백이 tol분 넘으면 None)."""
        i = int(np.searchsorted(self.tm, minute, side="left"))
        if i >= self.n or self.tm[i] - minute > tol:
            return None
        return i


def simulate(sd: SymDay, e: int, stop: float, trend: bool):
    """진입(봉 e 시가) 후 청산. 반환 (총수익률, 사유, 보유분)."""
    entry = sd.o[e]
    if entry <= 0:
        return None
    n = sd.n
    sl = np.where(sd.l[e:] <= stop)[0]
    i_stop = e + int(sl[0]) if len(sl) else n
    fo = np.where(sd.tm[e:] >= FORCE_MIN)[0]
    i_force = e + int(fo[0]) if len(fo) else n
    i_trend = n
    if trend:
        c5, _, _, ma = sd.five()
        b0 = (sd.tm[e] - OPEN_MIN) // 5 - 1
        bl = (sd.tm[e:] - OPEN_MIN) // 5 - 1
        valid = (bl > b0) & (bl >= 19)
        flag = np.zeros(len(bl), bool)
        idx = np.where(valid)[0]
        if len(idx):
            flag[idx] = c5[bl[idx]] < ma[bl[idx]]
        tr = np.where(flag)[0]
        i_trend = e + int(tr[0]) if len(tr) else n
    i = min(i_stop, i_trend, i_force)
    if i >= n:  # 15:10 이전에 데이터 종료(비유동) → 마지막 봉 종가
        return sd.c[-1] / entry - 1, "end", int(sd.tm[-1] - sd.tm[e])
    if i == i_stop:
        px, why = min(stop, sd.o[i]), "stop"
    elif i == i_trend:
        px, why = sd.o[i], "trend"
    else:
        px, why = sd.o[i], "force"
    return px / entry - 1, why, int(sd.tm[i] - sd.tm[e])


def trig_p1(sd: SymDay, prior_ext: float | None):
    c5, h5, l5, ma = sd.five()
    for b in range(19, 48):  # 완성 10:40~13:00
        m = ma[b]
        if np.isnan(m) or np.isnan(l5[b]) or b < 3 or np.isnan(ma[b - 3]):
            continue
        if not (l5[b] <= m * 1.003 and c5[b] > m and m >= ma[b - 3]):
            continue
        if prior_ext is not None and not (np.nanmax(h5[:b]) >= m * (1 + prior_ext)):
            continue
        return OPEN_MIN + 5 * (b + 1)
    return None


def trig_p2(sd: SymDay, L_raw: float):
    c5, h5, l5, ma = sd.five()
    if sd.o[0] < L_raw:
        return None
    for b in range(6, 48):  # 완성 09:30~13:00
        if np.isnan(l5[b]):
            continue
        if l5[b] <= L_raw * 1.005 and c5[b] >= L_raw:
            return OPEN_MIN + 5 * (b + 1)
    return None


def cstat(r: np.ndarray, days: np.ndarray) -> dict:
    n = len(r)
    if n < 2:
        return {"n": n, "days": int(len(set(days))), "mean": float("nan"), "t": float("nan"), "win": float("nan")}
    mu = r.mean()
    s = pd.Series(r - mu).groupby(days).sum()
    se = np.sqrt((s ** 2).sum()) / n
    return {"n": n, "days": int(len(set(days))), "mean": float(mu), "t": float(mu / se) if se > 0 else float("nan"),
            "win": float((r > 0).mean())}


def summarize(tr: pd.DataFrame) -> dict:
    out = {}
    for part, sub in (("IS", tr[tr.day <= IS_END]), ("OOS", tr[tr.day > IS_END]), ("ALL", tr)):
        if len(sub) == 0:
            out[part] = {"n": 0}
            continue
        d = sub.day.values
        row = {"base": cstat(sub.gross.values - COST_BASE, d), "stress": cstat(sub.gross.values - COST_STRESS, d)}
        w = sub.dropna(subset=["ctrl"])
        row["vs_ctrl"] = cstat((w.gross - w.ctrl).values, w.day.values) if len(w) > 1 else {"n": len(w)}
        row["ctrl_gross_mean"] = float(w.ctrl.mean()) if len(w) else float("nan")
        row["exit"] = sub.why.value_counts().to_dict()
        row["hold_min_median"] = float(sub.hold.median())
        out[part] = row
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "bt"))
    args = ap.parse_args()
    files = sorted(glob.glob(str(ROOT / "minute" / "*" / "*.parquet")))
    days = [f[-16:-8] for f in files]
    specs = {"P1": dict(prior_ext=0.02, top=0.20), "P1_V1": dict(prior_ext=None, top=0.20), "P1_V2": dict(prior_ext=0.02, top=0.10), "P2": {}}
    trades: dict[str, list] = {k: [] for k in specs}
    funnel = {k: {"qual": 0, "sig": 0} for k in specs}
    prev_last: dict[str, float] = {}
    for fi, (f, day) in enumerate(zip(files, days)):
        m = pd.read_parquet(f)
        cache: dict[str, SymDay] = {}

        def sd_of(sym):
            if sym not in cache:
                cache[sym] = SymDay(g.get_group(sym)) if sym in g.groups else None
            return cache[sym]

        g = m.groupby("symbol")
        syms = list(g.groups.keys())
        # 유니버스 20일 수익률(D-1) → 상위 N% 컷
        r20 = {}
        for s in syms:
            df = daily_feats(s)
            if df is None:
                continue
            i, row = prev_row(df, day)
            if row is not None and not np.isnan(row.ret20):
                r20[s] = float(row.ret20)
        cut = {t: (np.quantile(list(r20.values()), 1 - t) if r20 else np.inf) for t in (0.20, 0.10)}
        # ---- P1 계열 ----
        for name in ("P1", "P1_V1", "P1_V2"):
            sp = specs[name]
            Q = []
            for s in syms:
                df = daily_feats(s)
                if df is None or s not in r20:
                    continue
                i, row = prev_row(df, day)
                if row is None or row.close < MIN_PRICE or np.isnan(row.ma60):
                    continue
                if not (row.close > row.ma20 > 0 and row.ma20 > row.ma60 and row.ma20 > row.ma20_l5 and row.dev <= 0.10):
                    continue
                if r20[s] < cut[sp["top"]]:
                    continue
                sd = sd_of(s)
                if sd is None or not sd.ok:
                    continue
                Q.append(s)
            funnel[name]["qual"] += len(Q)
            sigs = {}
            for s in Q:
                T = trig_p1(sd_of(s), sp["prior_ext"])
                if T is not None:
                    sigs[s] = T
            funnel[name]["sig"] += len(sigs)
            ctrl_pool = [s for s in Q if s not in sigs]
            ccache: dict = {}
            for s, T in sigs.items():
                sd = sd_of(s)
                e = sd.bar_at(T)
                if e is None:
                    continue
                res = simulate(sd, e, sd.o[e] * (1 - STOP_PCT), True)
                if res is None:
                    continue
                cr = []
                for q in ctrl_pool:
                    key = (q, T)
                    if key not in ccache:
                        sq = sd_of(q)
                        eq = sq.bar_at(T)
                        rr = simulate(sq, eq, sq.o[eq] * (1 - STOP_PCT), True) if eq is not None else None
                        ccache[key] = rr[0] if rr else None
                    if ccache[key] is not None:
                        cr.append(ccache[key])
                trades[name].append((day, s, T, res[0], res[1], res[2], float(np.mean(cr)) if cr else np.nan, len(cr)))
        # ---- P2 ----
        Q = {}
        if prev_last:
            for s in syms:
                df = daily_feats(s)
                if df is None or s not in prev_last:
                    continue
                i, row = prev_row(df, day)
                if row is None or row.close < MIN_PRICE:
                    continue
                xs = [x for x in range(i, i - 5, -1) if x >= 60 and bool(df.brk.iat[x])]
                if not xs:
                    continue
                L = float(df.L.iat[xs[0]])
                if not (L <= row.close <= L * 1.08):
                    continue
                k = prev_last[s] / row.close
                if abs(k - 1) > 0.02:
                    continue  # 권리락 의심 → 제외
                sd = sd_of(s)
                if sd is None or not sd.ok:
                    continue
                Q[s] = L
        funnel["P2"]["qual"] += len(Q)
        sigs = {s: trig_p2(sd_of(s), L) for s, L in Q.items()}
        sigs = {s: T for s, T in sigs.items() if T is not None}
        funnel["P2"]["sig"] += len(sigs)
        ctrl_pool = [s for s in Q if s not in sigs]
        ccache = {}
        for s, T in sigs.items():
            sd = sd_of(s)
            e = sd.bar_at(T)
            if e is None:
                continue
            entry = sd.o[e]
            res = simulate(sd, e, max(Q[s] * 0.99, entry * (1 - STOP_PCT)), False)
            if res is None:
                continue
            cr = []
            for q in ctrl_pool:
                key = (q, T)
                if key not in ccache:
                    sq = sd_of(q)
                    eq = sq.bar_at(T)
                    rr = simulate(sq, eq, max(Q[q] * 0.99, sq.o[eq] * (1 - STOP_PCT)), False) if eq is not None else None
                    ccache[key] = rr[0] if rr else None
                if ccache[key] is not None:
                    cr.append(ccache[key])
            trades["P2"].append((day, s, T, res[0], res[1], res[2], float(np.mean(cr)) if cr else np.nan, len(cr)))
        # 다음 날 k 계산용: 오늘 분봉 마지막 종가(15:20 이전)
        prev_last = {}
        for s in syms:
            sd = sd_of(s)
            if sd is not None and sd.n:
                prev_last[s] = float(g.get_group(s).sort_values("time").close.iloc[-1])
        if fi % 40 == 0:
            print(f"  ... {fi}/{len(files)} {day} 신호 " + " ".join(f"{k}:{len(v)}" for k, v in trades.items()), file=sys.stderr)
    cols = ["day", "sym", "T", "gross", "why", "hold", "ctrl", "nctrl"]
    res = {}
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    for k, rows in trades.items():
        tr = pd.DataFrame(rows, columns=cols)
        tr.to_parquet(outdir / f"{k}_trades.parquet", index=False)
        res[k] = {"funnel": funnel[k], **(summarize(tr) if len(tr) else {})}
    (outdir / "summary.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
