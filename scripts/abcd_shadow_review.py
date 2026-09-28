#!/usr/bin/env python3
"""ABCD 수급리더 한정 SHADOW 성과 스코어보드 — enforce 판정 게이트(read-only).

ABCD는 전 유니버스 백테스트서 손실이라 enforce 불가. 유일 미검증 변수 = Aziz 'stocks in play'
(=수급 리더) 한정 효과. 이 스크립트는 **수급 데이터가 있는 날**에 한해 수급 리더(supply_score≥0.5)
로만 ABCD 진입을 재구성하고 트레일 청산 성과를 레짐별로 집계한다. 저장된 데이터로 재구성하므로
라이브 shadow 로그와 동치(매매 무영향). 상승일이 쌓이는 대로 자동으로 채워진다.

**enforce 기준(제안): 상승일 수급리더 ABCD가 표본 ≥20건 AND 승률 >50% AND 평균손익 >0 이면
그때 상승 레짐 enforce 판정.** 그 전엔 shadow 유지.

사용: python scripts/abcd_shadow_review.py [--start ..] [--end ..] [--exit trail|rr2]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import abcd_backtest as ab  # noqa: E402  (동일 디렉터리 백테스트 로직 재사용)


def supply_leaders(conn, date: str) -> set[str] | None:
    """그날 수급 리더(supply_score≥0.5) 집합. 수급 데이터 자체가 없으면 None(그 날 제외)."""
    row = conn.execute(
        "SELECT items FROM universe_filter_results WHERE trade_date=? ORDER BY rowid DESC LIMIT 1",
        (date,)).fetchone()
    if not row or not row["items"]:
        return None
    items = json.loads(row["items"])
    if not any("supply_score" in (it or {}) for it in items):
        return None                          # 수급 계측 이전 날 → 제외
    leaders = set()
    for it in items:
        try:
            if float(it.get("supply_score", 0) or 0) >= 0.5:
                leaders.add(str(it.get("symbol")))
        except (TypeError, ValueError):
            continue
    return leaders


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-09-20")
    ap.add_argument("--end", default="2026-12-31")
    ap.add_argument("--exit", default="trail", choices=["trail", "rr2"])
    args = ap.parse_args()
    cfg = {"lookback": 30, "impulse": 2.0, "pull_min": 1.0, "pull_max": 5.0}

    conn = ab._conn()
    reg = ab.regimes(conn, args.start, args.end)
    results = defaultdict(list)
    days_with_supply = []
    days_no_supply = []

    for d in sorted(reg):
        leaders = supply_leaders(conn, d)
        if leaders is None:
            days_no_supply.append(d)
            continue
        days_with_supply.append((d, reg[d], len(leaders)))
        for sym in leaders:
            bars = ab.load_minute_bars(conn, d, sym)
            if not ab.covered(bars):
                continue
            day_open = bars[0]["o"]
            for b in bars:
                b["cfo"] = (b["c"] / day_open - 1) * 100 if day_open else 0
            sig = ab._find_abcd(bars, cfg)
            if sig is None:
                continue
            ei, stop, target = sig
            results[reg[d]].append(ab._exit(bars, ei, stop, target, args.exit))

    print(f"\n{'='*80}")
    print(f"ABCD 수급리더 SHADOW 스코어보드 — {args.start}~{args.end} · exit={args.exit}")
    print(f"{'='*80}")
    print(f"수급데이터 있는 날: {len(days_with_supply)}일 · 없는 날(제외): {len(days_no_supply)}일")
    if days_with_supply:
        print("  " + " · ".join(f"{d}({r},리더{n})" for d, r, n in days_with_supply))
    print(f"{'-'*80}")
    print(f"{'레짐':<6}{'표본':>6}{'승률':>8}{'평균손익':>10}{'손익비':>9}")
    any_row = False
    for r in ("상승", "보합", "하락"):
        xs = results.get(r, [])
        if not xs:
            continue
        any_row = True
        wins = [x for x in xs if x > 0]
        losses = [x for x in xs if x <= 0]
        wr = len(wins) / len(xs) * 100
        aw = sum(wins) / len(wins) if wins else 0
        al = abs(sum(losses) / len(losses)) if losses else 0
        rr = aw / al if al > 0 else float("inf")
        print(f"{r:<6}{len(xs):>6}{wr:>7.1f}%{sum(xs)/len(xs):>+9.2f}%{rr:>8.2f}")
    if not any_row:
        print("(수급리더 ABCD 진입 표본 없음 — 상승일 수급데이터 누적 대기)")
    print(f"{'-'*80}")
    up = results.get("상승", [])
    print("■ enforce 판정(제안 기준: 상승일 표본≥20 · 승률>50% · 평균>0):")
    if len(up) >= 20 and sum(1 for x in up if x > 0) / len(up) > 0.5 and sum(up) / len(up) > 0:
        print("  ✅ 기준 충족 — 상승 레짐 ABCD enforce 검토 가능")
    else:
        wr = (sum(1 for x in up if x > 0) / len(up) * 100) if up else 0
        print(f"  ⏳ 미충족 (상승 표본 {len(up)}/20 · 승률 {wr:.0f}%) — shadow 유지, 상승일 누적 대기")
    print()


if __name__ == "__main__":
    main()
