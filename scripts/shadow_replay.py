#!/usr/bin/env python3
"""섀도우 신호 재현 — 매수 정지 중 엔진이 '샀을' 종목을 1분봉으로 재현한다(읽기 전용, 2026-10-16).

  python scripts/shadow_replay.py                         # DB shadow_entry_signals 전체
  python scripts/shadow_replay.py --start 2026-10-19      # 기간 지정
  python scripts/shadow_replay.py --from-log journal.txt  # SHADOW_PAUSED 로그(journalctl 출력)에서

평가 기준(개선 제안 #6): 절대 수익만 보지 않는다. **같은 분에 그날 유니버스(전일 거래대금 상위 500)를
무작위로 샀을 때(기준선)** 대비 초과 수익을 함께 낸다. 이 유니버스는 1년간 장중 평균 −0.375%/일
흘러내렸으므로(docs/REVIEW_20261016_crash_shadow.md) 절대 수익만으로는 신호의 질을 판단할 수 없다.

체결: 신호 다음 분 시가. 청산(라이브 근사): 손절 −3% · +1% 도달 후 본전+0.23% · +2%에서 절반 수확 후
고점 대비 1.5% 트레일 · 15:10 시가 강제청산. 비용 왕복 0.23%. t = 날짜 클러스터.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
MINUTE = ROOT / "data" / "market" / "minute"
COST = 0.23
LOG_PAT = re.compile(r"(20\d\d-\d\d-\d\d \d\d:\d\d:\d\d),\d+ - DecisionEngine.*SHADOW_PAUSED.*symbol=(\w+) price=([\d.]+)")


def load_db(start: str, end: str) -> pd.DataFrame:
    sys.path.insert(0, str(ROOT))
    from backend.config import settings  # noqa: E402

    con = sqlite3.connect(f"file:{settings.APP_DB_PATH}?mode=ro", uri=True)
    df = pd.read_sql_query(
        "SELECT trade_date, symbol, first_time, first_price FROM shadow_entry_signals"
        " WHERE trade_date BETWEEN ? AND ?", con, params=(start, end))
    return df.rename(columns={"first_time": "t", "first_price": "price"})


def load_log(path: str) -> pd.DataFrame:
    """로그 시각은 UTC → KST. 09:30~14:30 안의 종목-일 첫 신호만."""
    seen: dict[tuple[str, str], tuple[str, float]] = {}
    for line in open(path, encoding="utf-8", errors="ignore"):
        m = LOG_PAT.search(line)
        if not m:
            continue
        t = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S") + timedelta(hours=9)
        if not ("09:30" <= t.strftime("%H:%M") <= "14:30"):
            continue  # 실매수 가능 시간대의 첫 신호(엔진 DB 기록과 같은 규칙)
        k = (t.strftime("%Y-%m-%d"), m.group(2))
        seen.setdefault(k, (t.strftime("%H:%M:%S"), float(m.group(3))))
    return pd.DataFrame([(d, s, t, p) for (d, s), (t, p) in seen.items()],
                        columns=["trade_date", "symbol", "t", "price"])


def simulate(b: pd.DataFrame, i0: int, stop: float = -0.03, end: str = "1510") -> float:
    """b: 한 종목 분봉(time 정렬, 0..n 인덱스). i0 봉 시가 진입. 비용 전 수익%."""
    e = float(b.open.iloc[i0])
    st, hi, part, w, armed = e * (1 + stop), e, 0.0, 1.0, False
    for i in range(i0, len(b)):
        r = b.iloc[i]
        if r.time >= end:
            return part + w * (r.open / e - 1) * 100
        if r.low <= st:
            px = min(st, r.open) if i > i0 else st
            return part + w * (px / e - 1) * 100
        hi = max(hi, r.high)
        if hi >= e * 1.01:
            st = max(st, e * 1.0023)
        if not armed and hi >= e * 1.02:
            part, w, armed = 1.0, 0.5, True  # 절반을 +2%에 확정
        if armed:
            st = max(st, hi * 0.985)
    return part + w * (b.close.iloc[-1] / e - 1) * 100


def _next_minute(hhmmss: str) -> str:
    t = datetime.strptime(hhmmss[:5], "%H:%M") + timedelta(minutes=1)
    return t.strftime("%H%M")


def replay(sig: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for d, grp in sig.groupby("trade_date"):
        day = d.replace("-", "")
        f = MINUTE / day[:4] / f"{day}.parquet"
        if not f.exists():
            print(f"분봉 없음 {d} — {len(grp)}건 건너뜀")
            continue
        mb = pd.read_parquet(f)
        mb = mb[mb.time < "1530"].sort_values(["symbol", "time"])
        bars = {s: x.reset_index(drop=True) for s, x in mb.groupby("symbol")}
        for _, s in grp.iterrows():
            if not ("09:30" <= s.t[:5] <= "14:30"):
                continue  # 실매수 가능 시간대만(engine.entry_execute_start_time·컷오프)
            nxt = _next_minute(s.t)
            base = []
            for b2 in bars.values():
                j = b2.index[b2.time >= nxt]
                k = b2.index[b2.time >= "1510"]
                if len(j) and len(k) and j[0] < k[0]:
                    base.append(simulate(b2, int(j[0])))
            b = bars.get(s.symbol)
            if b is None:
                rows.append(dict(trade_date=d, symbol=s.symbol, t=s.t, covered=False))
                continue
            j = b.index[b.time >= nxt]
            if not len(j):
                continue
            rows.append(dict(trade_date=d, symbol=s.symbol, t=s.t, covered=True,
                             ret=simulate(b, int(j[0])), base=float(np.mean(base)) if base else np.nan))
    return pd.DataFrame(rows)


def cluster_t(df: pd.DataFrame, col: str) -> float:
    m = df[col].mean()
    resid = (df[col] - m).groupby(df.trade_date).sum()
    se = np.sqrt((resid ** 2).sum()) / len(df)
    return float(m / se) if se else float("nan")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2000-01-01")
    ap.add_argument("--end", default="2999-12-31")
    ap.add_argument("--from-log", default=None)
    ap.add_argument("--csv", default=None, help="거래별 결과 저장 경로")
    a = ap.parse_args()
    sig = load_log(a.from_log) if a.from_log else load_db(a.start, a.end)
    sig = sig[(sig.trade_date >= a.start) & (sig.trade_date <= a.end)]
    if sig.empty:
        print("섀도우 신호 없음")
        return 0
    res = replay(sig)
    if a.csv:
        res.to_csv(a.csv, index=False)
    c = res[res.get("covered", False) == True] if len(res) else res  # noqa: E712
    print(f"신호 {len(sig)}건(종목-일) · 실매수 시간대·분봉 있음 {len(c)}건 · 거래일 {c.trade_date.nunique() if len(c) else 0}")
    if c.empty:
        return 0
    c = c.assign(net=c.ret - COST, excess=c.ret - c.base)
    print(f"순수익/건 {c.net.mean():+.3f}%  승률 {(c.net > 0).mean():.0%}  t={cluster_t(c, 'ret'):+.2f}")
    print(f"기준선(같은 분 유니버스, 같은 청산) {c.base.mean():+.3f}%  →  초과 {c.excess.mean():+.3f}%  t={cluster_t(c, 'excess'):+.2f}")
    print(c.groupby("trade_date").agg(n=("symbol", "count"), net=("net", "mean"), excess=("excess", "mean")).round(3))
    if len(c) < 30:
        print("※ 30건 미만 — 통계적 판단 불가(참고용)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
