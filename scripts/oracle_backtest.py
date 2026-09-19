#!/usr/bin/env python3
"""오라클(이상매매) 복원 — "무엇을·언제 사서·언제 팔았어야 했나 + 그게 감지 가능한 패턴인가".

우리가 그날 지켜본(intraday_bars 종일 커버) 종목들에 대해:
  1) 이론상 최대이익 라운드트립(best buy-low/sell-high) = 오라클 진입/청산 복원
  2) 오라클 진입 시점의 관찰가능 피처(시가대비·VWAP거리·고점거리·거래량·시각) 분포
     → 이상적 진입이 '이른 시각·VWAP 근처·저(低)등락'에 몰리는가, 아니면 무작위인가
  3) 조기신호 예측력: 결정시각 T(기본 09:30)의 초반 강도로 그날 승자를 미리 고를 수 있었나
  4) 단순 규칙 vs 오라클 vs 우리 실제 — 상승장 참여 상한/실현 갭

읽기 전용(mode=ro). 매매/서버 무영향.
사용: python scripts/oracle_backtest.py [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--decide HHMM]
"""
from __future__ import annotations

import argparse
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "stock_trading_bot.sqlite3"

MIN_BARS = 200          # 종일 커버 판정(초단위 바라 200↑이면 대부분 하루)
OPEN_BY = "0920"        # 첫 바가 이 시각 이전이어야 '개장부터 관측'
CLOSE_AFTER = "1400"    # 마지막 바가 이 시각 이후여야 '장 후반까지 관측'


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def trading_dates(conn, start, end):
    rows = conn.execute(
        "SELECT DISTINCT trade_date FROM intraday_bars WHERE trade_date BETWEEN ? AND ? ORDER BY trade_date",
        (start, end),
    ).fetchall()
    return [r["trade_date"] for r in rows]


def load_minute_bars(conn, date, sym):
    """(date, sym) 바를 1분봉으로 리샘플. (symbol,bar_ts) 중복은 마지막 id 채택."""
    rows = conn.execute(
        "SELECT bar_ts, open, high, low, close, volume, shnu_rate, id FROM intraday_bars "
        "WHERE trade_date=? AND symbol=? ORDER BY bar_ts, id",
        (date, sym),
    ).fetchall()
    if not rows:
        return []
    by_ts = {}
    for r in rows:
        by_ts[r["bar_ts"]] = r  # 같은 bar_ts 중복이면 나중 것
    mins = {}
    for ts in sorted(by_ts):
        r = by_ts[ts]
        m = str(ts)[:4]  # HHMM
        c = float(r["close"] or 0)
        if c <= 0:
            continue
        b = mins.get(m)
        vol = float(r["volume"] or 0)
        if b is None:
            mins[m] = {"m": m, "o": float(r["open"] or c), "h": float(r["high"] or c),
                       "l": float(r["low"] or c), "c": c, "v": vol, "shnu": float(r["shnu_rate"] or 0)}
        else:
            b["h"] = max(b["h"], float(r["high"] or c))
            b["l"] = min(b["l"], float(r["low"] or c))
            b["c"] = c
            b["v"] += vol
            b["shnu"] = float(r["shnu_rate"] or 0)
    return [mins[m] for m in sorted(mins)]


def covered(bars):
    if len(bars) < 3:
        return False
    return bars[0]["m"] <= OPEN_BY[:4] and bars[-1]["m"] >= CLOSE_AFTER[:4]


def oracle_trade(bars):
    """이론상 최대이익 롱 1회(진입 close < 청산 close). O(n). 반환 idx/return."""
    if len(bars) < 2:
        return None
    min_i = 0
    best = None
    for j in range(1, len(bars)):
        if bars[j]["c"] > bars[min_i]["c"]:
            ret = bars[j]["c"] / bars[min_i]["c"] - 1
            if best is None or ret > best["ret"]:
                best = {"ei": min_i, "xi": j, "ret": ret}
        if bars[min_i]["c"] > bars[j]["c"]:
            min_i = j
    return best


def features_at(bars, i):
    """i번째 바 진입 시점의 관찰가능 피처(look-ahead 없음: i까지 정보만)."""
    day_open = bars[0]["o"]
    upto = bars[: i + 1]
    vv = sum(b["v"] for b in upto)
    vwap = (sum(b["c"] * b["v"] for b in upto) / vv) if vv > 0 else bars[i]["c"]
    run_high = max(b["h"] for b in upto)
    avg_v = (vv / len(upto)) if upto else 0
    px = bars[i]["c"]
    return {
        "t": bars[i]["m"],
        "cfo": (px / day_open - 1) * 100 if day_open else 0,        # 시가대비 등락%
        "vwap_dist": (px / vwap - 1) * 100 if vwap else 0,          # VWAP 거리%
        "high_dist": (px / run_high - 1) * 100 if run_high else 0,  # 당일고점 거리%
        "vol_surge": (bars[i]["v"] / avg_v) if avg_v else 0,
        "min_from_open": len([b for b in upto]) ,                    # 근사(분 인덱스)
    }


def fwd_return_from(bars, decide_hhmm):
    """결정시각 이후 최대상승(고점기준)과 종가수익. 초반강도 예측력 검증용."""
    idx = next((k for k, b in enumerate(bars) if b["m"] >= decide_hhmm), None)
    if idx is None or idx >= len(bars) - 1:
        return None
    base = bars[idx]["c"]
    fwd_high = max(b["h"] for b in bars[idx:])
    return {
        "decide_px": base,
        "fwd_max_pct": (fwd_high / base - 1) * 100,
        "close_pct": (bars[-1]["c"] / base - 1) * 100,
    }


def early_strength(bars, decide_hhmm):
    """결정시각까지의 초반 관찰 피처(그날 승자 랭킹 가능한지)."""
    idx = next((k for k, b in enumerate(bars) if b["m"] >= decide_hhmm), None)
    if idx is None:
        return None
    return features_at(bars, idx)


def pct(xs, p):
    if not xs:
        return 0.0
    s = sorted(xs)
    k = int(round((len(s) - 1) * p))
    return s[k]


def band(v, edges, labels):
    for e, l in zip(edges, labels):
        if v < e:
            return l
    return labels[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-08-25")
    ap.add_argument("--end", default="2026-12-31")
    ap.add_argument("--decide", default="0930", help="조기신호 결정시각 HHMM")
    ap.add_argument("--min-run", type=float, default=3.0, help="'좋은 종목' 판정 오라클 수익 하한%")
    args = ap.parse_args()

    conn = _conn()
    dates = trading_dates(conn, args.start, args.end)
    per_symbol = []   # 종목-일 단위 오라클 결과
    for date in dates:
        syms = [r["symbol"] for r in conn.execute(
            "SELECT DISTINCT symbol FROM intraday_bars WHERE trade_date=?", (date,))]
        for sym in syms:
            bars = load_minute_bars(conn, date, sym)
            if not covered(bars):
                continue
            orc = oracle_trade(bars)
            if not orc:
                continue
            ef = features_at(bars, orc["ei"])
            xf = features_at(bars, orc["xi"])
            day_open = bars[0]["o"]
            close_ret = (bars[-1]["c"] / day_open - 1) * 100
            es = early_strength(bars, args.decide)
            fr = fwd_return_from(bars, args.decide)
            per_symbol.append({
                "date": date, "sym": sym,
                "orc_ret": orc["ret"] * 100,
                "entry_t": ef["t"], "entry_cfo": ef["cfo"], "entry_vwap": ef["vwap_dist"],
                "entry_high": ef["high_dist"], "exit_t": xf["t"], "exit_cfo": xf["cfo"],
                "close_ret": close_ret,
                "early_cfo": es["cfo"] if es else None,
                "early_vwap": es["vwap_dist"] if es else None,
                "early_vol": es["vol_surge"] if es else None,
                "fwd_max": fr["fwd_max_pct"] if fr else None,
                "fwd_close": fr["close_pct"] if fr else None,
            })

    n = len(per_symbol)
    print(f"\n{'='*78}\n오라클 복원 — {args.start}~{args.end} · 종일커버 종목-일 {n}건 · 결정시각 {args.decide}\n{'='*78}")

    # ── 1) 일자별 최고 오라클 종목: 언제 사서 언제 팔았어야 (상위 2개/일)
    print("\n[1] 일자별 '샀어야 할 종목' — 이상적 진입/청산 시각·수익 (상위 2)")
    print(f"{'날짜':<11}{'종목':<8}{'오라클%':>8}{'진입시각':>7}{'진입시가대비':>10}{'진입VWAP':>9}{'청산시각':>7}{'종가보유%':>9}")
    bydate = defaultdict(list)
    for r in per_symbol:
        bydate[r["date"]].append(r)
    for date in sorted(bydate):
        top = sorted(bydate[date], key=lambda x: -x["orc_ret"])[:2]
        for r in top:
            print(f"{date:<11}{r['sym']:<8}{r['orc_ret']:>7.1f}%{r['entry_t']:>7}"
                  f"{r['entry_cfo']:>9.1f}%{r['entry_vwap']:>8.1f}%{r['exit_t']:>7}{r['close_ret']:>8.1f}%")

    # ── 2) 오라클 진입 피처 분포: 이상적 매수는 '어디서' 일어났나
    print("\n[2] 이상적 진입 시점의 관찰가능 피처 분포 (n={})".format(n))
    cfos = [r["entry_cfo"] for r in per_symbol]
    vwaps = [r["entry_vwap"] for r in per_symbol]
    times = [r["entry_t"] for r in per_symbol]
    print(f"  시가대비(cfo)  : 중앙값 {statistics.median(cfos):+.1f}%  25p {pct(cfos,.25):+.1f}%  75p {pct(cfos,.75):+.1f}%")
    print(f"  VWAP거리       : 중앙값 {statistics.median(vwaps):+.1f}%  25p {pct(vwaps,.25):+.1f}%  75p {pct(vwaps,.75):+.1f}%")
    tb = defaultdict(int)
    for t in times:
        hh = t[:2]
        tb[hh] += 1
    print("  진입 시각대 분포: " + "  ".join(f"{h}시:{tb[h]}" for h in sorted(tb)))
    le0 = sum(1 for c in cfos if c <= 0)
    le2 = sum(1 for c in cfos if c <= 2)
    print(f"  → 이상적 진입 중 시가대비 ≤0%: {le0}/{n} ({100*le0/n:.0f}%) · ≤+2%: {le2}/{n} ({100*le2/n:.0f}%)")
    print(f"     (우리 momentum 실제진입은 전부 cfo≥+4%, 6건 avg+16.6% — 정반대 구간)")

    # ── 3) 조기신호 예측력: 09:30 초반강도로 그날 승자를 미리 고를 수 있었나
    print(f"\n[3] 조기신호({args.decide}) 예측력 — 초반 강한 종목이 그날 더 오르나")
    rows = [r for r in per_symbol if r["early_cfo"] is not None and r["fwd_max"] is not None]
    # 결정시각 등락 상위 vs 하위로 그날 이후 최대상승 비교
    rows.sort(key=lambda x: -x["early_cfo"])
    half = max(1, len(rows) // 2)
    strong, weak = rows[:half], rows[half:]
    def avg(xs, k): return statistics.mean([x[k] for x in xs]) if xs else 0
    print(f"  초반강세(cfo상위50%) 이후 최대상승 평균: {avg(strong,'fwd_max'):+.1f}% · 종가 {avg(strong,'fwd_close'):+.1f}%")
    print(f"  초반약세(cfo하위50%) 이후 최대상승 평균: {avg(weak,'fwd_max'):+.1f}% · 종가 {avg(weak,'fwd_close'):+.1f}%")
    # VWAP 위/아래로도
    rows.sort(key=lambda x: -(x["early_vwap"] or -99))
    above = [r for r in rows if (r["early_vwap"] or 0) > 0]
    below = [r for r in rows if (r["early_vwap"] or 0) <= 0]
    print(f"  {args.decide} VWAP위 종목({len(above)}) 이후 최대상승: {avg(above,'fwd_max'):+.1f}% · 종가 {avg(above,'fwd_close'):+.1f}%")
    print(f"  {args.decide} VWAP아래 종목({len(below)}) 이후 최대상승: {avg(below,'fwd_max'):+.1f}% · 종가 {avg(below,'fwd_close'):+.1f}%")

    # ── 4) 단순 규칙들의 상승장 참여도 (오라클 상한 대비)
    print("\n[4] 참여 상한·실현 갭 — 종목-일 평균 수익%")
    orc_avg = statistics.mean([r["orc_ret"] for r in per_symbol])
    close_avg = statistics.mean([r["close_ret"] for r in per_symbol])
    # '오라클 진입시각에 사서 종가보유' = 완벽진입+무청산
    print(f"  오라클(완벽 진입+청산)         : {orc_avg:+.1f}%   ← 이론 상한")
    print(f"  시가매수→종가보유(그냥 보유)   : {close_avg:+.1f}%")
    pos_close = sum(1 for r in per_symbol if r["close_ret"] > 0)
    print(f"  종가>시가 종목 비율             : {pos_close}/{n} ({100*pos_close/n:.0f}%)")
    print()


if __name__ == "__main__":
    main()
