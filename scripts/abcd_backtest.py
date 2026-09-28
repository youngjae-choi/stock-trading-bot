#!/usr/bin/env python3
"""ABCD 눌림목 패턴 백테스트 (Andrew Aziz 『How to Day Trade for a Living』).

PM 요청: "제대로 된 눌림목"을 시스템이 실행 가능하게 결정론 규칙으로 구현하고, 우리 데이터로
이기는지 숫자로 검증. ABCD = A(강한 1차상승 신고가) → B(눌림 저점) → C(higher-low 지지 후
반등) 지점 매수 → D(전고점 A 돌파 목표). 손절=지지선(B저점) 아래, 청산=트레일링(추세 태우기).

look-ahead 없음(진입 시점까지의 봉만 사용). 1분봉(10초봉 6개 집계)으로 스윙 구조 판정.
read-only(mode=ro) — 매매·서버 영향 없음. edge_backtest/uptrend_pattern과 동일 소스·비용.

사용: python scripts/abcd_backtest.py [--start ..] [--end ..] [--exit trail|rr2]
       [--impulse 2.0] [--pull-min 1.0] [--pull-max 5.0] [--lookback 30]
"""
from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "stock_trading_bot.sqlite3"
OPEN_BY, CLOSE_AFTER = "0935", "1445"
COST = 0.25          # 왕복 거래비용(%)
ENTRY_START, ENTRY_END = "0935", "1330"   # 진입 허용 시간창


def _conn():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def regimes(conn, start, end):
    rows = conn.execute(
        """WITH k AS (SELECT substr(captured_at,1,10) d, change_rate,
             ROW_NUMBER() OVER (PARTITION BY substr(captured_at,1,10) ORDER BY captured_at DESC) rn
             FROM market_snapshots WHERE symbol='KOSPI')
           SELECT d, change_rate FROM k WHERE rn=1 AND d BETWEEN ? AND ?""",
        (start, end),
    ).fetchall()
    return {r["d"]: ("상승" if (r["change_rate"] or 0) >= 1.0
                     else "하락" if (r["change_rate"] or 0) <= -1.0 else "보합") for r in rows}


def load_minute_bars(conn, date, sym):
    rows = conn.execute(
        "SELECT bar_ts, open, high, low, close, volume FROM intraday_bars "
        "WHERE trade_date=? AND symbol=? ORDER BY bar_ts, id", (date, sym)).fetchall()
    mins = {}
    for r in rows:
        c = float(r["close"] or 0)
        if c <= 0:
            continue
        m = str(r["bar_ts"])[:4]
        v = float(r["volume"] or 0)
        b = mins.get(m)
        if b is None:
            mins[m] = {"m": m, "o": float(r["open"] or c), "h": float(r["high"] or c),
                       "l": float(r["low"] or c), "c": c, "v": v}
        else:
            b["h"] = max(b["h"], float(r["high"] or c)); b["l"] = min(b["l"], float(r["low"] or c))
            b["c"] = c; b["v"] += v
    return [mins[m] for m in sorted(mins)]


def covered(bars):
    return len(bars) >= 100 and bars[0]["m"] <= OPEN_BY and bars[-1]["m"] >= CLOSE_AFTER


def detect_abcd_entry(bars, i, cfg):
    """바 i에서 ABCD 진입 신호인지 판정(순수·look-ahead 없음). 성립 시 (stop, target) 반환 else None.

    A = 최근 lookback봉 내 스윙 고점 · B = A 이후 눌림 저점 · C = 현재 higher-low 지지 후 반등.
    조건: ①A 임펄스(A가 그 이전 저점 대비 impulse%↑) ②눌림 깊이 B가 [pull_min,pull_max]%
          ③현재 지지 유지(저가≥B저점) + 반등(양봉·직전종가 상향) ④현재가 A 아래(D까지 여력).
    """
    if i < 1:
        return None
    cur = bars[i]
    if not (ENTRY_START <= cur["m"] <= ENTRY_END):
        return None
    lo = max(0, i - cfg["lookback"])
    window = bars[lo:i]                      # A 후보 구간(현재 봉 제외)
    if len(window) < 5:
        return None
    # A: 구간 내 최고 고가
    a_idx = max(range(len(window)), key=lambda k: window[k]["h"])
    A = window[a_idx]["h"]
    if a_idx >= len(window) - 2:             # A가 너무 최근(눌림 형성 안 됨) → 제외
        return None
    # 임펄스: A 이전 저점 대비 상승폭
    pre = window[:a_idx + 1]
    base = min(b["l"] for b in pre) if pre else A
    if base <= 0 or (A / base - 1) * 100 < cfg["impulse"]:
        return None
    # B: A 이후 ~ 현재 직전 눌림 저점
    after = window[a_idx + 1:]
    if not after:
        return None
    B = min(b["l"] for b in after)
    pull = (A - B) / A * 100
    if not (cfg["pull_min"] <= pull <= cfg["pull_max"]):
        return None
    # C(현재): 지지 유지 + 반등 + A 아래(여력)
    price = cur["c"]
    green = cur["c"] > cur["o"]
    turning_up = cur["c"] > bars[i - 1]["c"]
    holds_support = cur["l"] >= B * (1 - 0.001)       # B 저점 지지(약간의 여유)
    room_to_A = B < price < A                          # 목표 A까지 여력
    if not (holds_support and room_to_A and (green or turning_up)):
        return None
    stop = B * (1 - 0.001)                              # 손절 = 지지선(B) 바로 아래
    return (stop, A)


def _find_abcd(bars, cfg):
    """하루 첫 ABCD 진입 봉을 찾는다(순차). 반환 (entry_idx, stop, target) or None."""
    for i in range(2, len(bars)):
        sig = detect_abcd_entry(bars, i, cfg)
        if sig is not None:
            return (i, sig[0], sig[1])
    return None


def _exit(bars, ei, stop, target, mode):
    """진입 후 전진 시뮬. 지지선 손절 + (trail=트레일링 추세라이딩 / rr2=2:1 고정목표). 반환 net%."""
    entry = bars[ei]["c"]
    peak = entry
    risk = (entry - stop) / entry if entry > stop else 0.0
    for j in range(ei + 1, len(bars)):
        b = bars[j]
        peak = max(peak, b["h"])
        if b["l"] <= stop:                             # 지지선 손절
            return (stop / entry - 1) * 100 - COST
        if mode == "trail":                            # 활성 +1.5% 후 고점-2.5% 트레일(무캡, 추세 태움)
            if (peak / entry - 1) * 100 >= 1.5:
                tr = peak * (1 - 0.025)
                if b["l"] <= tr:
                    return (tr / entry - 1) * 100 - COST
        elif mode == "rr2":                            # 2:1 — 목표=진입+2×리스크(Aziz)
            tgt = entry * (1 + 2 * risk)
            if b["h"] >= tgt:
                return (tgt / entry - 1) * 100 - COST
        if b["m"] >= "1500":
            return (b["c"] / entry - 1) * 100 - COST
    return (bars[-1]["c"] / entry - 1) * 100 - COST


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-08-25")
    ap.add_argument("--end", default="2026-12-31")
    ap.add_argument("--exit", default="trail", choices=["trail", "rr2"])
    ap.add_argument("--impulse", type=float, default=2.0)
    ap.add_argument("--pull-min", type=float, default=1.0)
    ap.add_argument("--pull-max", type=float, default=5.0)
    ap.add_argument("--lookback", type=int, default=30)
    args = ap.parse_args()
    p = {"impulse": args.impulse, "pull_min": args.pull_min, "pull_max": args.pull_max,
         "lookback": args.lookback}

    conn = _conn()
    reg = regimes(conn, args.start, args.end)
    syms = [r["symbol"] for r in conn.execute(
        "SELECT DISTINCT symbol FROM intraday_bars WHERE trade_date BETWEEN ? AND ?",
        (args.start, args.end)).fetchall()]

    # results[regime] = list of net%
    results = defaultdict(list)
    per_day = defaultdict(list)
    dates = sorted(reg)
    for d in dates:
        for sym in syms:
            bars = load_minute_bars(conn, d, sym)
            if not covered(bars):
                continue
            # look-ahead 없는 피처 부착
            day_open = bars[0]["o"]
            for b in bars:
                b["cfo"] = (b["c"] / day_open - 1) * 100 if day_open else 0
            sig = _find_abcd(bars, p)
            if sig is None:
                continue
            ei, stop, target = sig
            ret = _exit(bars, ei, stop, target, args.exit)
            results[reg[d]].append(ret)
            per_day[(reg[d], d)].append(ret)

    print(f"\n{'='*84}")
    print(f"ABCD 눌림목 백테스트 — {args.start}~{args.end} · exit={args.exit} · "
          f"임펄스≥{args.impulse}% 눌림[{args.pull_min},{args.pull_max}]% lookback{args.lookback}분")
    print(f"레짐 일수: " + " · ".join(f"{r} {sum(1 for x in reg.values() if x==r)}일"
                                      for r in ("상승", "보합", "하락")))
    print(f"{'='*84}")
    print(f"{'레짐':<6}{'표본':>6}{'승률':>8}{'평균손익':>10}{'손익비(R:R)':>12}{'총합':>9}")
    for r in ("상승", "보합", "하락"):
        xs = results.get(r, [])
        if not xs:
            print(f"{r:<6}{0:>6}{'-':>8}{'-':>10}{'-':>12}{'-':>9}")
            continue
        wins = [x for x in xs if x > 0]
        losses = [x for x in xs if x <= 0]
        wr = len(wins) / len(xs) * 100
        avg = sum(xs) / len(xs)
        aw = sum(wins) / len(wins) if wins else 0
        al = abs(sum(losses) / len(losses)) if losses else 0
        rr = aw / al if al > 0 else float("inf")
        print(f"{r:<6}{len(xs):>6}{wr:>7.1f}%{avg:>+9.2f}%{rr:>11.2f}{sum(xs):>+8.1f}%")
    print(f"{'-'*84}")

    # 상승장 일자별(로버스트니스 — 특정일 몰림 아닌지)
    up_days = [(r, d) for (r, d) in per_day if r == "상승"]
    if up_days:
        print("상승장 일자별:")
        for (r, d) in sorted(up_days, key=lambda x: x[1]):
            xs = per_day[(r, d)]
            wr = sum(1 for x in xs if x > 0) / len(xs) * 100
            print(f"  {d}  n={len(xs):>2}  승률 {wr:>3.0f}%  평균 {sum(xs)/len(xs):>+.2f}%  "
                  f"[{' '.join(f'{x:+.1f}' for x in xs)}]")
    print()


if __name__ == "__main__":
    main()
