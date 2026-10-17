#!/usr/bin/env python3
"""H4 급등·급락 Top20 매수·매도 시점 데이터 학습 — docs/PREREG_20261017_mover_timing_ml.md 그대로(읽기 전용).

  python scripts/mover_timing_ml.py            # 전체
  python scripts/mover_timing_ml.py --days 10  # 시험

특징 13개(과거만) → 10분위 원-핫 → 릿지(numpy) 로 미래 h분(5/10/30) 수익률 예측, 월 단위 확장창 전진 검증.
예측 > 0.23%면 매수, h분 뒤 시가 매도. 데이터·유니버스·랭킹·VWAP는 scalp_movers_backtest.py 재사용.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scalp_movers_backtest as sb  # noqa: E402

HS = (5, 10, 30)
COST, STRESS, T_PASS = 0.23, 0.33, 2.39
BURN_END = "20251219"            # 분위 경계·첫 학습 전용(평가 제외)
IS_END, OOS_START = "20260430", "20260501"
NB, NF = 10, 13
I_T0 = sb.MIDX["0919"]
I_T1 = sb.I_LAST_SIGNAL      # v1.1: 랭킹이 14:29 봉까지라 판단 봉 = 09:19~14:29
FEATS = ["r1", "r5", "r15", "chg", "dhod", "dlod", "dvw", "v1", "v5", "rng5", "upruns", "tod", "grp"]


def day_samples(day, prev, closes):
    """하루 → 후보 표본: 특징(NF), 진입봉, 그룹, 종목, 판단봉, h별 미래수익(%), 같은 분 Top20 평균(대조)."""
    arr = sb.day_arrays(day, prev, closes)
    if arr is None:
        return None
    syms, O, H, L, C, V, VW, real, pc = arr
    up, dn = sb.membership(C, pc)
    n, T = C.shape
    with np.errstate(invalid="ignore", divide="ignore"):
        def lag(x, k):
            return np.concatenate([np.full((n, k), np.nan), x[:, :-k]], axis=1)
        r1, r5, r15 = C / lag(C, 1) - 1, C / lag(C, 5) - 1, C / lag(C, 15) - 1
        chg = C / pc[:, None] - 1
        hod = np.maximum.accumulate(np.where(real, H, -np.inf), axis=1)
        lod = np.minimum.accumulate(np.where(real, L, np.inf), axis=1)
        dhod, dlod, dvw = C / hod - 1, C / lod - 1, C / VW - 1
        vm = pd.DataFrame(V).T.rolling(20, min_periods=20).mean().shift(1).T.to_numpy()
        v1 = V / vm
        v5 = pd.DataFrame(V).T.rolling(5).sum().T.to_numpy() / (vm * 5)
        hh = pd.DataFrame(H).T.rolling(5).max().T.to_numpy(); ll = pd.DataFrame(L).T.rolling(5).min().T.to_numpy()
        rng5 = (hh - ll) / C
        upb = (C > lag(C, 1)).astype(float)
        runs = np.zeros_like(upb)
        for t in range(1, T):
            runs[:, t] = np.where(upb[:, t] > 0, runs[:, t - 1] + 1, 0)
    out = []
    for t in range(I_T0, I_T1 + 1):
        grp = up[:, t] | dn[:, t]
        ent = sb.entry_bar(real, t)
        rows = np.where(grp & (ent > 0) & (ent < sb.I_FORCE))[0]
        if not len(rows):
            continue
        k = ent[rows]
        ok = O[rows, k] < pc[rows] * sb.LIMIT_UP
        rows, k = rows[ok], k[ok]
        if not len(rows):
            continue
        e = O[rows, k]
        fw = []
        for h in HS:
            xk = np.minimum(k + h, sb.I_FORCE)
            fw.append((O[rows, xk] / e - 1) * 100)
        fw = np.stack(fw, 1)
        tod = np.full(len(rows), float(t))
        g = np.where(up[rows, t], 1.0, -1.0)
        X = np.stack([r1[rows, t], r5[rows, t], r15[rows, t], chg[rows, t], dhod[rows, t], dlod[rows, t],
                      dvw[rows, t], v1[rows, t], v5[rows, t], rng5[rows, t], runs[rows, t], tod, g], 1)
        ctrl = np.nanmean(fw, axis=0)
        for j, s in enumerate(rows):
            out.append((day, syms[s], t, int(k[j]), *X[j], *fw[j], *ctrl))
    cols = ["day", "sym", "t", "k"] + FEATS + [f"f{h}" for h in HS] + [f"c{h}" for h in HS]
    return pd.DataFrame(out, columns=cols)


def bin_edges(df):
    return [np.nanquantile(df[f].to_numpy(dtype=float), np.linspace(0.1, 0.9, 9)) for f in FEATS]


def design(df, edges):
    """10분위 원-핫(+절편). NaN은 별도 칸 없이 0(=평균 기여)."""
    n = len(df)
    X = np.zeros((n, NF * NB + 1), dtype=np.float32)
    X[:, -1] = 1.0
    for i, f in enumerate(FEATS):
        x = df[f].to_numpy(dtype=float)
        b = np.searchsorted(edges[i], x)
        ok = ~np.isnan(x)
        X[np.where(ok)[0], i * NB + b[ok]] = 1.0
    return X


def walk_forward(S, edges):
    """월별 XᵀX·Xᵀy를 한 번씩 누적(구간 경계 고정이라 가능) → 평가 월 M은 M 이전 월 합으로만 풀이(확장창)."""
    S = S.copy()
    # v1.1: 학습전용 기간이 끝나는 달(12월)의 이후 날짜(12-22~)는 별도 묶음으로 → 그 앞 데이터로 예측(독립 검토 지적)
    S["month"] = np.where((S.day.str[:6] == BURN_END[:6]) & (S.day > BURN_END), BURN_END[:6] + "b", S.day.str[:6])
    months = sorted(S.month.unique())
    acc = {}
    for m in months:
        idx = np.where((S.month == m).to_numpy())[0]
        XtX = np.zeros((NF * NB + 1, NF * NB + 1)); Xty = {h: np.zeros(NF * NB + 1) for h in HS}
        XtXh = {h: np.zeros_like(XtX) for h in HS}; nh = {h: 0 for h in HS}
        for c0 in range(0, len(idx), 200_000):
            part = S.iloc[idx[c0:c0 + 200_000]]
            X = design(part, edges).astype(np.float64)
            for h in HS:
                y = part[f"f{h}"].to_numpy(dtype=float); ok = ~np.isnan(y)
                Xo = X[ok]
                XtXh[h] += Xo.T @ Xo; Xty[h] += Xo.T @ y[ok]; nh[h] += int(ok.sum())
        acc[m] = (XtXh, Xty, nh)
    preds = {h: np.full(len(S), np.nan) for h in HS}
    for j, m in enumerate(months):
        if S[S.month == m].day.min() <= BURN_END:
            continue
        prior = months[:j]
        te = np.where((S.month == m).to_numpy())[0]
        Xte = design(S.iloc[te], edges).astype(np.float64)
        for h in HS:
            A = sum(acc[p][0][h] for p in prior).copy(); b = sum(acc[p][1][h] for p in prior)
            n = sum(acc[p][2][h] for p in prior)
            lam = n * 1e-3
            A[np.diag_indices_from(A)] += lam
            A[-1, -1] -= lam  # 절편은 벌점 제외
            preds[h][te] = Xte @ np.linalg.solve(A, b)
        print(f"... 전진 예측 {m} (학습 {len(prior)}개월)", file=sys.stderr)
    for h in HS:
        S[f"p{h}"] = preds[h]
    return S


def trades(S, h):
    """예측 > 비용인 후보를 시간순으로 매수(종목 동시 1개·종목-일 3회)."""
    q = S[S[f"p{h}"] > COST].sort_values(["day", "t"])
    taken = []
    for (d, sym), g in q.groupby(["day", "sym"]):
        busy, cnt = -1, 0
        for r in g.itertuples(index=False):
            if r.k <= busy or cnt >= 3:
                continue
            busy, cnt = min(r.k + h, sb.I_FORCE), cnt + 1
            taken.append((d, sym, getattr(r, f"f{h}"), getattr(r, f"c{h}")))
    return pd.DataFrame(taken, columns=["day", "sym", "ret", "ctrl"])


def ct(df, col):
    if len(df) < 3:
        return float("nan")
    m = df[col].mean(); r = (df[col] - m).groupby(df.day).sum()
    se = np.sqrt((r ** 2).sum()) / len(df)
    return float(m / se) if se else float("nan")


def report(S):
    rows, raw = [], {}
    ev = S[S.day > BURN_END].dropna(subset=[f"p{h}" for h in HS])
    for h in HS:
        tr_ = trades(ev, h)
        for seg, q, cand in (("IS-WF", tr_[tr_.day <= IS_END], ev[ev.day <= IS_END]),
                             ("OOS-WF", tr_[tr_.day >= OOS_START], ev[ev.day >= OOS_START])):
            ic = cand[[f"p{h}", f"f{h}"]].rank().corr().iloc[0, 1] if len(cand) else np.nan
            top = cand[cand[f"p{h}"] >= cand[f"p{h}"].quantile(0.9)][f"f{h}"].mean() if len(cand) else np.nan
            share = (cand[f"p{h}"] > COST).mean() if len(cand) else np.nan
            if q.empty:
                rows.append(dict(h=h, 구간=seg, 거래=0, IC=round(ic, 3), 상위10pct총=round(top, 3), 임계초과비율=f"{share:.1%}"))
                raw[(h, seg)] = None
                continue
            q = q.assign(net=q.ret - COST, st=q.ret - STRESS, ex=q.ret - q.ctrl)
            raw[(h, seg)] = dict(n=len(q), days=q.day.nunique(), net=q.net.mean(), t=ct(q, "net"), st=q.st.mean())
            rows.append(dict(h=h, 구간=seg, 거래=len(q), 거래일=q.day.nunique(), 총수익=round(q.ret.mean(), 3),
                             순수익=round(q.net.mean(), 3), t=round(ct(q, "net"), 2), 스트레스=round(q.st.mean(), 3),
                             승률=f"{(q.net > 0).mean():.0%}", 대조군대비=round(q.ex.mean(), 3),
                             IC=round(ic, 3), 상위10pct총=round(top, 3), 임계초과비율=f"{share:.1%}"))
    print(pd.DataFrame(rows).to_string(index=False))
    for h in HS:
        o, i = raw.get((h, "OOS-WF")), raw.get((h, "IS-WF"))
        if not o:
            print(f"h={h} 판정: 거래 없음(예측이 비용을 넘는 후보 없음) → 불통과"); continue
        i_net = i["net"] if i else -1
        ok = o["net"] > 0 and o["t"] >= T_PASS and o["n"] >= 300 and o["days"] >= 60 and i_net > 0 and o["st"] > 0
        pend = o["net"] > 0 and i_net > 0 and 1.0 <= o["t"] < T_PASS
        print(f"h={h} 판정(OOS-WF):", "통과" if ok else ("미결" if pend else "불통과"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--cache", default=None, help="표본 parquet 캐시 경로")
    a = ap.parse_args()
    if a.cache and Path(a.cache).exists():
        S = pd.read_parquet(a.cache)
    else:
        closes = sb.load_prev_close()
        tdays = list(closes["005930"].index)
        files = sorted(p.stem for p in sb.MINUTE.glob("*/*.parquet"))
        if a.days:
            files = files[: a.days]
        parts = []
        for j, d in enumerate(files):
            if d not in tdays or tdays.index(d) == 0:
                continue
            x = day_samples(d, tdays[tdays.index(d) - 1], closes)
            if x is not None and len(x):
                for c in FEATS + [f"f{h}" for h in HS] + [f"c{h}" for h in HS]:
                    x[c] = x[c].astype(np.float32)
                parts.append(x)
            if (j + 1) % 25 == 0:
                print(f"... 표본 {j + 1}/{len(files)}일", file=sys.stderr)
        S = pd.concat(parts, ignore_index=True)
        if a.cache:
            S.to_parquet(a.cache, index=False)
    edges = bin_edges(S[S.day <= BURN_END])
    S = walk_forward(S, edges)
    report(S)
    return 0


if __name__ == "__main__":
    sys.exit(main())
