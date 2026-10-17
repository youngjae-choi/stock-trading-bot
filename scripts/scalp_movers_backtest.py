#!/usr/bin/env python3
"""급등·급락 Top20 분봉 초단타 3가설 — docs/PREREG_20261017_scalp_movers.md 규칙 그대로(읽기 전용).

  python scripts/scalp_movers_backtest.py            # 전체 258일
  python scripts/scalp_movers_backtest.py --days 5   # 시험(앞 5일)

H1 급등 Top20 눌림목 · H2 급등 Top20 신고가 돌파(거래량 2배) · H3 급락 Top20 반등(VWAP −3%↓·반등봉·거래량 2배).
청산 공통: +1.0% 익절 · −0.7% 손절(같은 봉 동시면 손절) · 진입 후 10봉 시간청산 · 15:15 강제. 비용 0.23%(스트레스 0.33%).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
MINUTE = ROOT / "data" / "market" / "minute"
DAILY = ROOT / "data" / "market" / "daily"
INDEX = ROOT / "data" / "market" / "index" / "0001.parquet"

COST, STRESS = 0.23, 0.33
IS_END, OOS_START = "20260430", "20260501"
TOP = 20
TP, SL, HOLD = 0.010, -0.007, 10
MIN_PX, MAX_GAP, MIN_BARS, MAX_ENTRIES = 2000.0, 0.30, 300, 3
LIMIT_UP = 1.29
T_PASS = 2.39


def _minutes() -> list[str]:
    out = []
    for h in range(9, 16):
        for m in range(60):
            hm = f"{h:02d}{m:02d}"
            if "0900" <= hm <= "1519":
                out.append(hm)
    return out


MIN_LIST = _minutes()                       # 0900..1519 (380개)
MIDX = {hm: i for i, hm in enumerate(MIN_LIST)}
I_FIRST_RANK = MIDX["0904"]                 # 09:05 시점 = 0904 봉 완성
I_LAST_SIGNAL = MIDX["1429"]                # 14:30까지 신호(진입은 다음 봉)
I_FORCE = MIDX["1515"]


def load_prev_close() -> dict[str, pd.Series]:
    out = {}
    for p in DAILY.glob("*.parquet"):
        d = pd.read_parquet(p, columns=["date", "close"])
        out[p.stem] = d.set_index("date")["close"].astype(float).sort_index()
    return out


def day_arrays(day: str, prev_day: str, closes: dict[str, pd.Series]):
    """하루 분봉 → (symbols, O,H,L,C,V,VWAP, real(실제 봉 여부), prev_close). 제외 규칙 적용."""
    f = MINUTE / day[:4] / f"{day}.parquet"
    m = pd.read_parquet(f)
    m = m[m.time.isin(MIDX.keys())]
    cnt = m.groupby("symbol").size()
    syms = []
    pcs = []
    for s in cnt.index:
        if cnt[s] < MIN_BARS or s not in closes:
            continue
        ser = closes[s]
        if prev_day not in ser.index:
            continue
        pc = float(ser.loc[prev_day])
        if pc < MIN_PX:
            continue
        syms.append(s)
        pcs.append(pc)
    if not syms:
        return None
    m = m[m.symbol.isin(syms)]
    sidx = {s: i for i, s in enumerate(syms)}
    n, T = len(syms), len(MIN_LIST)
    O = np.full((n, T), np.nan); H = O.copy(); L = O.copy(); C = O.copy(); V = np.zeros((n, T)); A = O.copy()
    r = m.symbol.map(sidx).to_numpy(); c = m.time.map(MIDX).to_numpy()
    O[r, c] = m.open.to_numpy(); H[r, c] = m.high.to_numpy(); L[r, c] = m.low.to_numpy()
    C[r, c] = m.close.to_numpy(); V[r, c] = m.volume.to_numpy(); A[r, c] = m.cum_amount.to_numpy()
    real = ~np.isnan(C)
    # 빈 봉(무체결) = 직전 종가로 채움(고·저·시 = 종가 → 손익 판정 없음)
    C = pd.DataFrame(C).ffill(axis=1).to_numpy()
    A = pd.DataFrame(A).ffill(axis=1).to_numpy()
    O = np.where(real, O, C); H = np.where(real, H, C); L = np.where(real, L, C)
    pc = np.array(pcs)
    first_open = np.array([O[i, np.argmax(real[i])] if real[i].any() else np.nan for i in range(n)])
    keep = np.abs(first_open / pc - 1) <= MAX_GAP
    keep &= ~np.isnan(C[:, I_FIRST_RANK])
    if not keep.any():
        return None
    sel = np.where(keep)[0]
    cumv = np.cumsum(V, axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        VW = np.where(cumv > 0, A / cumv, np.nan)
    return ([syms[i] for i in sel], O[sel], H[sel], L[sel], C[sel], V[sel], VW[sel], real[sel], pc[sel])


def membership(C: np.ndarray, pc: np.ndarray):
    """5분 랭킹 → 각 봉 t의 급등/급락 Top20 멤버십(가장 최근 랭킹 봉 기준)."""
    n, T = C.shape
    up = np.zeros((n, T), bool); dn = np.zeros((n, T), bool)
    chg = C / pc[:, None] - 1
    cur_up = cur_dn = None
    for t in range(I_FIRST_RANK, I_LAST_SIGNAL + 1):
        if (t - I_FIRST_RANK) % 5 == 0:
            x = chg[:, t]
            ok = ~np.isnan(x)
            order = np.argsort(np.where(ok, x, -np.inf))
            cur_up = order[::-1][:TOP]
            order2 = np.argsort(np.where(ok, x, np.inf))
            cur_dn = order2[:TOP]
        up[cur_up, t] = True
        dn[cur_dn, t] = True
    return up, dn


def signals(O, H, L, C, V, VW, real):
    """가설별 신호 행렬 (n,T) bool — 봉 t 완성 시 판단."""
    n, T = C.shape
    hod_prev = np.maximum.accumulate(np.where(real, H, -np.inf), axis=1)
    hod_prev = np.concatenate([np.full((n, 1), -np.inf), hod_prev[:, :-1]], axis=1)  # t 이전까지
    hod_now = np.maximum(hod_prev, H)
    prev_high = np.concatenate([np.full((n, 1), np.inf), H[:, :-1]], axis=1)
    vs = pd.DataFrame(V).T.rolling(20, min_periods=20).mean().shift(1).T.to_numpy()  # 직전 20봉 평균
    vol_spike = real & (V >= 2 * vs) & (vs > 0)
    with np.errstate(invalid="ignore"):
        pull = C / hod_now - 1
        h1 = real & (pull <= -0.02) & (pull >= -0.05) & (C > VW) & (C > prev_high)
        h2 = real & (C > hod_prev) & np.isfinite(hod_prev) & vol_spike
        h3 = real & (C <= VW * 0.97) & (C > prev_high) & vol_spike
    return h1, h2, h3


def simulate(O, H, L, rows: np.ndarray, t: int):
    """rows 종목들을 t+1 봉 시가에 진입 → (수익%, 청산사유, 청산 봉). 벡터화."""
    e = O[rows, t + 1]
    tp, sl = e * (1 + TP), e * (1 + SL)
    ret = np.full(len(rows), np.nan); why = np.full(len(rows), "", dtype=object)
    xbar = np.full(len(rows), -1)
    open_ = np.ones(len(rows), bool)
    last = min(t + 1 + HOLD, I_FORCE)
    for i in range(t + 1, last + 1):
        if i == last:  # 시간청산 또는 15:15 강제청산 = 그 봉 시가
            px = O[rows, i]
            ret[open_] = (px[open_] / e[open_] - 1) * 100
            why[open_] = "time" if last == t + 1 + HOLD else "force"
            xbar[open_] = i
            break
        o, h, l_ = O[rows, i], H[rows, i], L[rows, i]
        stop = open_ & (l_ <= sl)
        stop_px = np.where(i == t + 1, sl, np.minimum(sl, o))
        ret[stop] = (stop_px[stop] / e[stop] - 1) * 100; why[stop] = "stop"; xbar[stop] = i
        open_ &= ~stop
        take = open_ & (h >= tp)
        take_px = np.where(i == t + 1, tp, np.maximum(tp, o))
        ret[take] = (take_px[take] / e[take] - 1) * 100; why[take] = "target"; xbar[take] = i
        open_ &= ~take
        if not open_.any():
            break
    return ret, why, xbar


def run_day(day, prev_day, closes):
    arr = day_arrays(day, prev_day, closes)
    if arr is None:
        return []
    syms, O, H, L, C, V, VW, real, pc = arr
    up, dn = membership(C, pc)
    h1, h2, h3 = signals(O, H, L, C, V, VW, real)
    out = []
    for name, sig, grp in (("H1", h1, up), ("H2", h2, up), ("H3", h3, dn)):
        busy_until = np.full(len(syms), -1); entries = np.zeros(len(syms), int)
        for t in range(I_FIRST_RANK, I_LAST_SIGNAL + 1):
            cand = np.where(sig[:, t] & grp[:, t] & (busy_until < t + 1) & (entries < MAX_ENTRIES)
                            & real[:, t + 1] & (O[:, t + 1] < pc * LIMIT_UP))[0]
            if not len(cand):
                continue
            ret, why, xbar = simulate(O, H, L, cand, t)
            ctrl_rows = np.where(grp[:, t] & ~sig[:, t] & real[:, t + 1] & (O[:, t + 1] < pc * LIMIT_UP))[0]
            ctrl = np.nanmean(simulate(O, H, L, ctrl_rows, t)[0]) if len(ctrl_rows) else np.nan
            for k, s in enumerate(cand):
                if np.isnan(ret[k]):
                    continue
                busy_until[s] = xbar[k]; entries[s] += 1
                out.append((day, name, syms[s], MIN_LIST[t], ret[k], why[k], ctrl))
    return out


def cluster_t(df: pd.DataFrame, col: str) -> float:
    if len(df) < 3:
        return float("nan")
    m = df[col].mean()
    resid = (df[col] - m).groupby(df.day).sum()
    se = np.sqrt((resid ** 2).sum()) / len(df)
    return float(m / se) if se else float("nan")


def report(res: pd.DataFrame) -> None:
    res = res.assign(net=res.ret - COST, stress=res.ret - STRESS, ex=res.ret - res.ctrl)
    rows = []
    for h in ("H1", "H2", "H3"):
        for seg, q in (("IS", res[(res.h == h) & (res.day <= IS_END)]), ("OOS", res[(res.h == h) & (res.day >= OOS_START)])):
            if q.empty:
                rows.append(dict(가설=h, 구간=seg, 거래=0)); continue
            mix = q.why.value_counts(normalize=True)
            rows.append(dict(가설=h, 구간=seg, 거래=len(q), 거래일=q.day.nunique(),
                             총수익=round(q.ret.mean(), 3), 순수익=round(q.net.mean(), 3), t=round(cluster_t(q, "net"), 2),
                             스트레스=round(q.stress.mean(), 3), 승률=f"{(q.net > 0).mean():.0%}",
                             대조군대비=round(q.ex.mean(), 3), t_대조=round(cluster_t(q.dropna(subset=["ex"]), "ex"), 2),
                             익절=f"{mix.get('target', 0):.0%}", 손절=f"{mix.get('stop', 0):.0%}",
                             시간=f"{mix.get('time', 0) + mix.get('force', 0):.0%}"))
    tab = pd.DataFrame(rows)
    print(tab.to_string(index=False))
    print()
    for h in ("H1", "H2", "H3"):
        o = tab[(tab.가설 == h) & (tab.구간 == "OOS")].iloc[0]
        i = tab[(tab.가설 == h) & (tab.구간 == "IS")].iloc[0]
        if o.get("거래", 0) == 0:
            print(h, "판정: 거래 없음"); continue
        ok = (o.순수익 > 0 and o.t >= T_PASS and o.거래 >= 300 and o.거래일 >= 60 and i.get("순수익", -1) > 0 and o.스트레스 > 0)
        pend = (o.순수익 > 0 and i.get("순수익", -1) > 0 and 1.0 <= o.t < T_PASS)
        print(h, "판정(OOS):", "통과" if ok else ("미결" if pend else "불통과"))
    if INDEX.exists():
        ix = pd.read_parquet(INDEX).set_index("date").sort_index()
        chg = (ix.close / ix.close.shift(1) - 1) * 100
        res["mkt"] = res.day.map(chg)
        res["장세"] = pd.cut(res.mkt, [-99, -1.5, -0.5, 0.5, 1.5, 99], labels=["하락≤-1.5", "약세", "보합", "강세", "상승≥1.5"])
        print("\n장세별 순수익/거래(전 구간):")
        print(res.pivot_table(index="장세", columns="h", values="net", aggfunc="mean", observed=False).round(3))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--csv", default=None)
    a = ap.parse_args()
    closes = load_prev_close()
    trade_days = list(closes["005930"].index)
    files = sorted(p.stem for p in MINUTE.glob("*/*.parquet"))
    if a.days:
        files = files[: a.days]
    out = []
    for k, day in enumerate(files):
        if day not in trade_days or trade_days.index(day) == 0:
            continue
        prev = trade_days[trade_days.index(day) - 1]
        out += run_day(day, prev, closes)
        if (k + 1) % 25 == 0:
            print(f"... {k + 1}/{len(files)}일 거래 {len(out)}", file=sys.stderr)
    res = pd.DataFrame(out, columns=["day", "h", "symbol", "t", "ret", "why", "ctrl"])
    if a.csv:
        res.to_csv(a.csv, index=False)
    if res.empty:
        print("거래 없음"); return 0
    report(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
