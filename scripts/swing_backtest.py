#!/usr/bin/env python3
"""스윙 가설 3건 백테스트 — docs/PREREG_20261007_swing.md 와 동일 규칙 (읽기 전용).

  .venv/bin/python scripts/swing_backtest.py [--out data/market/bt]

규칙·파라미터의 SSOT는 사전등록 문서다. 여기서 바꾸면 새 가설이다.
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
TEST_START, IS_END = "20250417", "20251231"  # 시작 = 유니버스(이력 130일) 첫 유효일
COST, COST_STRESS = 0.0023, 0.0043
TOP_N, MIN_PRICE, MIN_HIST, LIMIT = 500, 5000.0, 130, 0.31  # 0.31 = 가격제한폭(30%) 초과만 이상치(부동소수 오차 여유)
HOLD = 5
NW_LAG = 4          # H1/H2: 5일 겹침 → Hansen-Hodrick(균등 가중) lag 4
H3_LAG = 20         # H3 달력시간 일별 포트폴리오: Newey-West lag 20(최대 보유)
H3_MAX = 22         # H3 형성일 상한: 20일 보유 + 다음날 시가 + 여유


def load_panels(root: Path = ROOT) -> dict[str, pd.DataFrame]:
    cols = {k: {} for k in ("open", "high", "low", "close", "volume", "amount")}
    for f in sorted(glob.glob(str(root / "daily" / "*.parquet"))):
        d = pd.read_parquet(f)
        d = d[d.close > 0].set_index("date")
        d.loc[d.volume <= 0, ["open", "high", "low", "close"]] = np.nan  # 거래정지일(가격 고정 행) → 거래 불가
        s = Path(f).stem
        for k in cols:
            cols[k][s] = d[k]
    return {k: pd.DataFrame(v).sort_index() for k, v in cols.items()}


def universe(P: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = P["close"]
    amt20 = P["amount"].rolling(20, min_periods=20).mean()
    rank = amt20.rank(axis=1, ascending=False, method="first")
    nozero = (P["volume"].fillna(0) <= 0).astype(int).rolling(20, min_periods=20).max() == 0
    hist = c.notna().cumsum() >= MIN_HIST
    return (c >= MIN_PRICE) & (rank <= TOP_N) & nozero & hist


def newey_west_t(x: np.ndarray, lag: int = NW_LAG, uniform: bool = False) -> float:
    """uniform=True → Hansen-Hodrick(겹침 MA 구조에 맞는 균등 가중). 분산이 음수면 Bartlett로 대체."""
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < lag + 2:
        return float("nan")
    e = x - x.mean()
    g = [(e[k:] @ e[:-k]) / n for k in range(1, lag + 1)]
    v = (e @ e) / n + 2 * sum(gk * (1.0 if uniform else 1 - k / (lag + 1)) for k, gk in enumerate(g, 1))
    if v <= 0 and uniform:
        v = (e @ e) / n + 2 * sum(gk * (1 - k / (lag + 1)) for k, gk in enumerate(g, 1))
    return float(x.mean() / np.sqrt(v / n)) if v > 0 else float("nan")


def cluster_t(x: np.ndarray, groups: np.ndarray) -> float:
    n = len(x)
    if n < 3:
        return float("nan")
    mu = x.mean()
    s = pd.Series(x - mu).groupby(groups).sum()
    se = np.sqrt((s ** 2).sum()) / n
    return float(mu / se) if se > 0 else float("nan")


def _ret(c: pd.DataFrame) -> pd.DataFrame:
    """직전 유효 종가 대비 변화(거래정지 후 재개 갭 포함)."""
    return c / c.ffill().shift(1) - 1


def _locked_up_open(P) -> pd.DataFrame:
    prev = P["close"].ffill().shift(1)
    return (P["open"] >= prev * 1.295) & (P["high"] == P["low"])


def cohorts(P: dict[str, pd.DataFrame], U: pd.DataFrame, kind: str) -> pd.DataFrame:
    """H1(mom)/H2(rev): 형성일별 묶음 수익률. 점수·유니버스는 t 종가까지만 사용."""
    c, o = P["close"], P["open"]
    ob = o.bfill(limit=10)  # 청산일 시가 없음 → 10거래일 안 다음 시가
    bad = _ret(c).abs() > LIMIT
    ev = bad.astype(int).rolling(127, min_periods=1).max().astype(bool)  # 점수 구간(t-126~t)에 미수정 권리 이벤트 → 제외
    lock = _locked_up_open(P)
    score = c.shift(5) / c.shift(126) - 1 if kind == "mom" else c / c.shift(5) - 1
    dates = list(c.index)
    rows = []
    for i, t in enumerate(dates):
        if t < TEST_START or i + 1 + HOLD >= len(dates):
            continue
        ent, ext = dates[i + 1], dates[i + 1 + HOLD]
        u = U.loc[t] & score.loc[t].notna() & ~ev.loc[t] & ~lock.loc[ent]
        win_bad = bad.iloc[i + 1:i + 2 + HOLD].any(axis=0)  # 진입일~청산일 종가 변화
        r = ob.loc[ext] / o.loc[ent] - 1
        valid = u & ~win_bad & r.notna() & o.loc[ent].notna()
        if valid.sum() < 50:
            continue
        sc = score.loc[t][valid]
        k = max(1, int(round(len(sc) * 0.10)))
        pick = sc.nlargest(k).index if kind == "mom" else sc.nsmallest(k).index
        rows.append({"t": t, "exit": ext, "n": k, "R": float(r[pick].mean()), "B": float(r[valid].mean())})
    return pd.DataFrame(rows)


def breakout_trades(P: dict[str, pd.DataFrame], U: pd.DataFrame) -> pd.DataFrame:
    c, o, h, lo, v = P["close"], P["open"], P["high"], P["low"], P["volume"]
    ob = o.bfill(limit=10)
    ma20, ma60 = c.rolling(20).mean(), c.rolling(60).mean()
    hi60 = h.shift(1).rolling(60, min_periods=60).max()
    vavg = v.shift(1).rolling(20, min_periods=20).mean()
    ret = _ret(c)
    bad = ret.abs() > LIMIT
    ev = bad.astype(int).rolling(61, min_periods=1).max().astype(bool)
    lock = _locked_up_open(P)
    prevc = c.ffill().shift(1)
    lockdn = (P["high"] == P["low"]) & (lo <= prevc * 0.705)
    sig = U & (c > hi60) & (ma20 > ma60) & (ret <= 0.15) & (v >= 1.5 * vavg) & ~ev
    dates = list(c.index)
    pos = {d: i for i, d in enumerate(dates)}
    C, O, Lo, M20, OB, BAD, LK, LD = (x.values for x in (c, o, lo, ma20, ob, bad, lock, lockdn))
    syms = list(c.columns)
    rows = []
    for j, s in enumerate(syms):
        busy = -1
        for t in sig.index[sig[s].values]:
            i = pos[t]
            if t < TEST_START or i <= busy or i + H3_MAX >= len(dates):
                continue
            e = i + 1
            entry = O[e, j]
            if not entry > 0 or LK[e, j]:
                continue
            stop = entry * 0.92
            exit_i, px, why = None, None, None
            held = 0
            for d in range(e, len(dates)):
                if np.isnan(C[d, j]):
                    continue  # 거래정지일
                held += 1
                if Lo[d, j] <= stop:
                    if LD[d, j]:
                        continue  # 하한가 잠김 → 못 팖, 다음 거래일로
                    exit_i, px, why = d, min(stop, O[d, j]), "stop"
                    break
                if not np.isnan(M20[d, j]) and C[d, j] < M20[d, j]:
                    exit_i, why = d + 1, "ma20"
                    break
                if held >= 20:
                    exit_i, why = d + 1, "time"
                    break
            if exit_i is None or exit_i >= len(dates):
                continue  # 형성일 상한으로 사실상 발생 안 함(장기 거래정지만)
            busy = exit_i  # 제외 판정 전에 보유기간 확정(보유 중 재신호 무시)
            if px is None:
                px = OB[exit_i, j]
                if not px > 0:
                    continue
            if BAD[e:exit_i + 1, j].any():
                continue
            # 기준선: 형성일 U_t 동일가중, 같은 기간 시가→시가 (같은 이상치 제외)
            ui = np.where(U.loc[t].values)[0]
            wb = BAD[e:exit_i + 1][:, ui].any(axis=0)
            br = OB[exit_i, ui] / O[e, ui] - 1
            ok = ~wb & ~np.isnan(br)
            rows.append({"t": t, "sym": s, "e": e, "x": exit_i, "entry": entry, "px": px, "gross": px / entry - 1, "why": why, "hold": exit_i - e,
                         "exit_date": dates[exit_i],
                         "B": float(np.nanmean(br[ok])) if ok.any() else np.nan})
    return pd.DataFrame(rows)


def calendar_excess(P: dict[str, pd.DataFrame], U: pd.DataFrame, tr: pd.DataFrame) -> pd.Series:
    """H3 달력시간 포트폴리오: 매일 보유 중 거래들의 (일별 순수익 − 그날 유니버스 동일가중 일별수익) 평균.
    일별 수익은 진입일 시가→종가, 중간 종가→종가, 청산일 전일종가→청산가. 비용은 진입일에 0.23% 차감."""
    c, o = P["close"], P["open"]
    dates = list(c.index)
    cr = (c / c.ffill().shift(1) - 1).where(U.shift(1, fill_value=False))
    mkt = cr.mean(axis=1).fillna(0.0).values  # 전일 유니버스 종목의 오늘 종가 수익 평균
    oc = (c / o - 1).where(U.shift(1, fill_value=False)).mean(axis=1).fillna(0.0).values
    co = (o / c.ffill().shift(1) - 1).where(U.shift(1, fill_value=False)).mean(axis=1).fillna(0.0).values
    C = c.ffill().values
    cols = {s: k for k, s in enumerate(c.columns)}
    acc = np.zeros(len(dates)); cnt = np.zeros(len(dates))
    for r in tr.itertuples():
        j, e, x = cols[r.sym], int(r.e), int(r.x)
        last = x if r.why == "stop" else x - 1  # 마지막 보유일
        prev = r.entry
        for d in range(e, last + 1):
            if d == last and r.why == "stop":
                px = r.px
            else:
                px = C[d, j]
            day_r = px / prev - 1
            bench = oc[d] if d == e else mkt[d]
            if d == e:
                day_r -= COST
            acc[d] += day_r - bench; cnt[d] += 1
            prev = px
        if r.why != "stop":  # 청산일: 전일 종가 → 청산일 시가
            day_r = r.px / prev - 1
            acc[x] += day_r - co[x]; cnt[x] += 1
    s = pd.Series(np.where(cnt > 0, acc / np.maximum(cnt, 1), np.nan), index=dates)
    return s.dropna()


def summarize_cohorts(df: pd.DataFrame) -> dict:
    out = {}
    for part, sub in (("IS", df[df.exit <= IS_END]), ("OOS", df[df.t > IS_END]), ("ALL", df)):  # IS = 청산까지 2025 안(엠바고)
        if len(sub) < 5:
            out[part] = {"n": len(sub)}
            continue
        ex = sub.R - COST - sub.B
        out[part] = {"cohorts": len(sub), "avg_pick": float(sub.n.mean()),
                     "gross": float(sub.R.mean()), "B": float(sub.B.mean()),
                     "net_abs": float((sub.R - COST).mean()), "net_abs_t": newey_west_t((sub.R - COST).values, uniform=True),
                     "net_excess": float(ex.mean()), "t": newey_west_t(ex.values, uniform=True),
                     "stress_excess": float((sub.R - COST_STRESS - sub.B).mean()),
                     "ann_sharpe_excess": float(ex.mean() / ex.std() * np.sqrt(252 / HOLD)) if ex.std() > 0 else float("nan")}
    return out


def summarize_trades(df: pd.DataFrame, cal: pd.Series) -> dict:
    out = {}
    for part, sub, cs in (("IS", df[df.exit_date <= IS_END], cal[cal.index <= IS_END]),
                          ("OOS", df[df.t > IS_END], cal[cal.index > IS_END]), ("ALL", df, cal)):
        sub = sub.dropna(subset=["B"])
        if len(sub) < 5:
            out[part] = {"n": len(sub)}
            continue
        wk = pd.to_datetime(sub.t).dt.strftime("%G-%V").values
        ex = (sub.gross - COST - sub.B).values
        out[part] = {"n": len(sub), "weeks": int(len(set(wk))), "gross": float(sub.gross.mean()), "B": float(sub.B.mean()),
                     "net_abs": float((sub.gross - COST).mean()), "net_abs_t": cluster_t((sub.gross - COST).values, wk),
                     "net_excess": float(ex.mean()), "t": newey_west_t(cs.values, H3_LAG),
                     "t_week_cluster_ref": cluster_t(ex, wk), "cal_days": len(cs), "cal_excess_daily": float(cs.mean()),
                     "stress_excess": float((sub.gross - COST_STRESS - sub.B).mean()),
                     "win": float((sub.gross - COST > 0).mean()), "hold_median": float(sub.hold.median()),
                     "exit": sub.why.value_counts().to_dict()}
    return out


def verdict(o: dict) -> str:
    s, i = o.get("OOS", {}), o.get("IS", {})
    if "t" not in s or "net_excess" not in i:
        return "판정불가"
    if s["net_excess"] > 0 and i["net_excess"] > 0 and s["net_abs"] > 0 and s["t"] >= 2.39:
        return "통과"
    if s["net_excess"] > 0 and i["net_excess"] > 0 and 1.0 <= s["t"] < 2.39:
        return "미결(유망)"
    return "불통과"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "bt"))
    args = ap.parse_args()
    P = load_panels()
    U = universe(P)
    res = {}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, kind in (("H1_momentum", "mom"), ("H2_reversal", "rev")):
        df = cohorts(P, U, kind)
        df.to_parquet(out / f"{name}.parquet", index=False)
        res[name] = summarize_cohorts(df)
        res[name]["verdict"] = verdict(res[name])
    tr = breakout_trades(P, U)
    tr.to_parquet(out / "H3_breakout.parquet", index=False)
    cal = calendar_excess(P, U, tr)
    res["H3_breakout"] = summarize_trades(tr, cal)
    res["H3_breakout"]["verdict"] = verdict(res["H3_breakout"])
    (out / "swing_summary.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
