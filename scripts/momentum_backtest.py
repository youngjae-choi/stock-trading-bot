#!/usr/bin/env python3
"""유니버스 모멘텀 백테스트 — 상승/폭등일에 '리더(강세)를 사서 태웠으면' 순기대값 검증.

우리 실거래는 눌림(약체)뿐이라 '리더 매수'의 표본이 0이다(게이트가 강세진입을 막음). 이 도구는
상승/폭등(risk_on) 레짐일에 **그날 구독 유니버스 전체**(intraday_bars 종목)에 모멘텀 진입
(ORB 돌파 + VWAP 위 + 상대강도)을 시뮬하고, 추세추종 청산(트레일)으로 라운드트립 순기대값을
계산한다. "코스피 +4%면 시스템도 +4%" 목표의 달성 가능성을 데이터로 본다.

edge_backtest/exit_backtest가 '우리가 실제 한 거래' 기반인 것과 달리, 이건 '했어야 할 거래'를
유니버스에서 시뮬한다(반사실 백테스트). 읽기전용. 매매/서버 영향 없음.

가정(단순화, 보수적):
  · 진입 = ORB(첫 OR_END까지 고가)를 exec_start 이후 첫 상향돌파 & VWAP 위 & 시가대비≥rs_min.
    진입가 = OR 고가(돌파 레벨). 못 뚫으면 그날 그 종목 미진입.
  · 청산 = 한 바 안에서 손절(저가)이 먼저(보수적). 트레일은 peak×(1-trail).
  · 왕복비용 0.23% 차감. 유동성 필터(min_vol·min_bars)로 잡주 제외.
"""
from __future__ import annotations

import argparse
import sqlite3
import statistics
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "stock_trading_bot.sqlite3"
COST = 0.23


def _conn():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def risk_on_days(conn, start, end):
    return [r["trade_date"] for r in conn.execute(
        "SELECT trade_date FROM regime_set_applications WHERE current_flag=1 AND regime_label='risk_on'"
        " AND trade_date BETWEEN ? AND ? GROUP BY trade_date ORDER BY trade_date", (start, end))]


def universe(conn, date, min_vol, min_bars):
    return [r["symbol"] for r in conn.execute(
        "SELECT symbol, SUM(volume) v, COUNT(*) n FROM intraday_bars WHERE trade_date=?"
        " GROUP BY symbol HAVING v>=? AND n>=?", (date, min_vol, min_bars))]


def bars_of(conn, date, symbol):
    return conn.execute(
        "SELECT bar_ts, open, high, low, close, volume FROM intraday_bars"
        " WHERE trade_date=? AND symbol=? ORDER BY bar_ts", (date, symbol)).fetchall()


# 진입: ORB 돌파 + VWAP 위 + 상대강도. 반환 (entry_ts, entry_price, entry_idx) 또는 None.
def momentum_entry(bars, cfg):
    or_end, exec_start, rs_min = cfg["or_end"], cfg["exec_start"], cfg["rs_min"]
    day_open = (bars[0]["open"] or bars[0]["close"] or 0)
    if day_open <= 0:
        return None
    or_high = max((b["high"] or 0) for b in bars if b["bar_ts"] < or_end) if any(b["bar_ts"] < or_end for b in bars) else 0
    if or_high <= 0:
        return None
    pv = vv = 0.0
    for i, b in enumerate(bars):
        c = b["close"] or 0
        v = b["volume"] or 0
        pv += c * v
        vv += v
        vwap = pv / vv if vv > 0 else c
        if b["bar_ts"] >= exec_start and (b["high"] or 0) > or_high and c > vwap:
            cfo = (c / day_open - 1) * 100
            if cfo >= rs_min:
                return b["bar_ts"], or_high, i
    return None


# 청산: 진입 이후 경로 추세추종. 반환 pnl%(소수 아님, 예 +3.0).
def ride_exit(bars, entry_idx, entry_price, cfg):
    P = entry_price
    stop = P * (1 + cfg["stop"])
    scalp = cfg.get("scalp")           # None이면 순수 트레일(태우기)
    tr_act, tr_stop = cfg["trail_act"], cfg["trail_stop"]
    peak = P
    trailing = False
    for b in bars[entry_idx + 1:]:
        hi = b["high"] or 0
        lo = b["low"] or 0
        if hi <= 0 or lo <= 0:
            continue
        floor = stop
        if trailing:
            floor = max(stop, peak * (1 - tr_stop))
        if lo <= floor:                       # 손절/트레일 청산(보수적: 저가 먼저)
            return (floor / P - 1) * 100
        if scalp is not None and hi >= P * (1 + scalp):
            return scalp * 100                # 스칼프 목표 도달
        peak = max(peak, hi)
        if not trailing and hi >= P * (1 + tr_act):
            trailing = True
    last = bars[-1]["close"] or P
    return (last / P - 1) * 100               # EOD 종가


ENTRY_CFGS = {
    "ORB":       dict(or_end="093000", exec_start="093000", rs_min=0.0),
    "ORB+강세2":  dict(or_end="093000", exec_start="093000", rs_min=2.0),
    "ORB+강세4":  dict(or_end="093000", exec_start="093000", rs_min=4.0),
}
EXIT_CFGS = {
    "스칼프+2%(현행류)": dict(stop=-0.04, scalp=0.02, trail_act=0.035, trail_stop=0.025),
    "태우기 트레일3%":   dict(stop=-0.04, scalp=None, trail_act=0.02, trail_stop=0.03),
    "태우기 트레일5%":   dict(stop=-0.05, scalp=None, trail_act=0.02, trail_stop=0.05),
    "EOD홀드(손절-5)":  dict(stop=-0.05, scalp=None, trail_act=99.0, trail_stop=0.99),
}


def stat(pnls):
    if not pnls:
        return "n=0"
    w = sum(1 for p in pnls if p > 0)
    avg = statistics.mean(pnls)
    return f"n={len(pnls):<4} 승률 {w/len(pnls)*100:5.1f}%  평균순 {avg-COST:+.2f}%  평균승 {statistics.mean([p for p in pnls if p>0]) if w else 0:+.2f}%  평균패 {statistics.mean([p for p in pnls if p<=0]) if w<len(pnls) else 0:+.2f}%"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-07-23")
    ap.add_argument("--end", default="2026-12-31")
    ap.add_argument("--min-vol", type=float, default=300000)
    ap.add_argument("--min-bars", type=int, default=100)
    args = ap.parse_args()
    conn = _conn()
    days = risk_on_days(conn, args.start, args.end)
    print(f"\n=== 유니버스 모멘텀 백테스트 — risk_on {len(days)}일 · 왕복비용 {COST}% 차감 ===")
    print(f"    유동성필터 vol>={args.min_vol:,.0f}·bars>={args.min_bars}\n")

    # 각 (진입×청산) 조합의 전체 순기대값
    print(f"{'진입설정':<10}{'청산설정':<18}{'결과'}")
    print("-" * 76)
    per_day_entries = {}  # entry_label -> {date: [pnl_at_entry_paths]}
    for e_lab, e_cfg in ENTRY_CFGS.items():
        # 진입 확정(경로·인덱스) 캐시
        entries = []  # (date, symbol, bars, entry_idx, entry_price)
        for d in days:
            for s in universe(conn, d, args.min_vol, args.min_bars):
                bs = bars_of(conn, d, s)
                if len(bs) < args.min_bars:
                    continue
                ent = momentum_entry(bs, e_cfg)
                if ent:
                    entries.append((d, s, bs, ent[2], ent[1]))
        per_day_entries[e_lab] = entries
        for x_lab, x_cfg in EXIT_CFGS.items():
            pnls = [ride_exit(bs, idx, px, x_cfg) for (_d, _s, bs, idx, px) in entries]
            print(f"{e_lab:<10}{x_lab:<18}{stat(pnls)}")
        print()

    # 일별: ORB+강세4 × 태우기트레일3 기준 진입수·평균순 (그날 리더 태우면 얼마)
    print("=== 일별 (ORB+강세4 × 태우기트레일3) — '리더 태우면 그날 순기대값?' ===")
    e_cfg = ENTRY_CFGS["ORB+강세4"]; x_cfg = EXIT_CFGS["태우기 트레일3%"]
    print(f"{'날짜':<12}{'진입수':>6}{'모멘텀평균순':>12}{'유니버스':>8}")
    for d in days:
        day_pnls = []
        uni = universe(conn, d, args.min_vol, args.min_bars)
        for s in uni:
            bs = bars_of(conn, d, s)
            if len(bs) < args.min_bars:
                continue
            ent = momentum_entry(bs, e_cfg)
            if ent:
                day_pnls.append(ride_exit(bs, ent[2], ent[1], x_cfg) - COST)
        mom = statistics.mean(day_pnls) if day_pnls else 0
        print(f"{d:<12}{len(day_pnls):>6}{mom:>+11.2f}%{len(uni):>8}")


if __name__ == "__main__":
    main()
