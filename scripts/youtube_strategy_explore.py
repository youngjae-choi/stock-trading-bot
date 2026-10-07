#!/usr/bin/env python3
"""[탐색용·판정 제외] 백테스트 거래의 진입 이후 고정 시간 수익률 — 청산 규칙과 분리해 '진입 타이밍 자체의 정보'를 본다.
시장 기준선 = 같은 날 같은 분(分)에 유니버스 전체 종목을 샀을 때의 평균 수익률."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import youtube_strategy_backtest as bt  # noqa: E402

HOR = (30, 60, 120)  # 분
for name in ("P1", "P2"):
    tr = pd.read_parquet(bt.ROOT / "bt" / f"{name}_trades.parquet")
    rows = []
    for day, g in tr.groupby("day"):
        m = pd.read_parquet(next(Path(bt.ROOT / "minute").glob(f"*/{day}.parquet")))
        m = m.assign(tm=m.time.str[:2].astype(int) * 60 + m.time.str[2:].astype(int)).sort_values(["symbol", "tm"])
        by = {s: (x.tm.values, x.open.values) for s, x in m.groupby("symbol")}

        def px(sym, minute):
            tm, op = by[sym]
            i = int(np.searchsorted(tm, minute, "left"))
            return op[i] if i < len(tm) and tm[i] - minute <= 3 and op[i] > 0 else None

        mk: dict = {}

        def market(T, tgt):
            if (T, tgt) not in mk:
                v = [b_ / a_ - 1 for s2 in by for a_, b_ in [(px(s2, T), px(s2, tgt))] if a_ and b_]
                mk[(T, tgt)] = float(np.mean(v)) if v else np.nan
            return mk[(T, tgt)]

        for _, r in g.iterrows():
            T = int(r["T"])
            e = px(r.sym, T)
            if not e:
                continue
            rec = {"day": day, "T": T}
            for h in HOR + (-1,):
                tgt = min(T + h, bt.FORCE_MIN) if h > 0 else bt.FORCE_MIN
                x = px(r.sym, tgt)
                rec[f"s{h}"] = x / e - 1 if x else np.nan
                rec[f"m{h}"] = market(T, tgt)
            rows.append(rec)
    df = pd.DataFrame(rows)
    print(f"\n=== {name} (거래 {len(df)}건) 진입 후 고정시간 총수익률(비용 제외) — 신호 vs 시장평균, 초과분 t(날짜 클러스터)")
    for part, sub in (("IS", df[df.day <= bt.IS_END]), ("OOS", df[df.day > bt.IS_END])):
        for h in HOR + (-1,):
            ex = (sub[f"s{h}"] - sub[f"m{h}"]).dropna()
            d = sub.loc[ex.index, "day"].values
            st = bt.cstat(ex.values, d)
            print(f"  {part} {'15:10까지' if h < 0 else f'+{h}분':>7}: 신호 {sub[f's{h}'].mean()*100:+.3f}%  시장 {sub[f'm{h}'].mean()*100:+.3f}%  초과 {st['mean']*100:+.3f}% t={st['t']:+.2f} (n={st['n']})")
