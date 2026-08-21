#!/usr/bin/env python3
"""SHADOW-SIZING / SHADOW-MAXPOS 로그 분석 — 신모델(예수금비중) vs 현재 비교.

order_executor `_shadow_new_sizing` + order_preflight SHADOW-MAXPOS가 남긴 로그를
집계해, 예수금비중 사이징 신모델을 **활성화해도 안전한지** 데이터로 판단한다.
읽기 전용(로그 파싱). 매매/서버 영향 없음.

사용:
  sudo journalctl -u stock-trading-bot --since today | python scripts/analyze_shadow_sizing.py
  cat some.log | python scripts/analyze_shadow_sizing.py
"""
from __future__ import annotations

import re
import statistics
import sys
from collections import defaultdict

_SIZING = re.compile(
    r"SHADOW-SIZING symbol=(?P<sym>\S+) regime=(?P<regime>\S+) vwap_dist=(?P<vd>\S+) "
    r"conv=(?P<conv>[\d.]+) \| 현재 qty=(?P<cq>\d+)\((?P<ck>[\d.]+)원\) → "
    r"신모델 qty=(?P<nq>\d+)\(비중(?P<rate>[\d.]+)%·(?P<nk>[\d.]+)원·목표(?P<tp>\d+)종목\)"
)
_MAXPOS = re.compile(
    r"SHADOW-MAXPOS symbol=(?P<sym>\S+) 현재제약=(?P<cur>\S+) 보유=(?P<held>\d+) "
    r"\| 신모델 ceiling=(?P<cap>\d+)"
)


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), 2) if xs else None


def main() -> int:
    sizing = []
    maxpos = []
    for line in sys.stdin:
        m = _SIZING.search(line)
        if m:
            d = m.groupdict()
            sizing.append({
                "sym": d["sym"], "regime": d["regime"],
                "vd": None if d["vd"] == "NA" else float(d["vd"]),
                "conv": float(d["conv"]), "cur_krw": float(d["ck"]),
                "new_krw": float(d["nk"]), "rate": float(d["rate"]),
                "target_pos": int(d["tp"]),
            })
            continue
        m = _MAXPOS.search(line)
        if m:
            maxpos.append(m.groupdict())

    if not sizing and not maxpos:
        print("SHADOW 로그 없음 — 재기동 후 매수가 발생해야 로그가 쌓인다.")
        return 0

    if sizing:
        n = len(sizing)
        cur_tot = sum(s["cur_krw"] for s in sizing)
        new_tot = sum(s["new_krw"] for s in sizing)
        print(f"=== SHADOW-SIZING {n}건 (신모델 예수금비중 vs 현재) ===")
        print(f"확신도 평균 {_mean([s['conv'] for s in sizing])} · 종목당비중 평균 {_mean([s['rate'] for s in sizing])}%")
        print(f"종목당 투입액: 현재 평균 {_mean([s['cur_krw'] for s in sizing]):,}원 → 신모델 {_mean([s['new_krw'] for s in sizing]):,}원")
        print(f"신모델/현재 투입비 = {new_tot/cur_tot:.2f}배" if cur_tot else "현재 투입 0")
        print(f"신모델 목표종목수 평균 {_mean([s['target_pos'] for s in sizing])} (범위 {min(s['target_pos'] for s in sizing)}~{max(s['target_pos'] for s in sizing)})")
        print("\n레짐별:")
        by_r = defaultdict(list)
        for s in sizing:
            by_r[s["regime"]].append(s)
        for r, items in sorted(by_r.items()):
            print(f"  {r:<12} {len(items):>3}건 · 확신 {_mean([i['conv'] for i in items])} · 비중 {_mean([i['rate'] for i in items])}% · 목표 {_mean([i['target_pos'] for i in items])}종목")

    if maxpos:
        print(f"\n=== SHADOW-MAXPOS {len(maxpos)}건 ===")
        cur_kinds = defaultdict(int)
        for m in maxpos:
            cur_kinds[m["cur"]] += 1
        for k, c in sorted(cur_kinds.items(), key=lambda x: -x[1]):
            print(f"  현재제약 {k}: {c}건")
        print(f"  (신모델 ceiling = {maxpos[-1]['cap']} 종목)")

    print("\n판단 기준: 신모델/현재 투입비가 과도(예: >2배)하면 활성 전 비중 하향. "
          "목표종목수가 6~19 안에서 확신도 따라 움직이면 정상.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
