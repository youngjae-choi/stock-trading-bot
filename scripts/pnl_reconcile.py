#!/usr/bin/env python3
"""신뢰 P&L 스코어보드 (Phase 0) — 평균원가 실현손익을 단일 SSOT로 확립.

같은 날 P&L이 5개 소스에서 17배 상충(deposit_krw 주말버그·오버나잇 이월·스냅샷 타이밍).
EOD 보유가 0이면(데이트레이더) 진짜 손익 = 실현손익. 이 스크립트가 fills에서 평균원가법으로
실현손익을 매도일 귀속으로 재계산해 신뢰 가능한 단일 일별/기간 손익을 보고한다(read-only).
저장된 지표들과 대조해 왜 갈리는지(이월)도 보여준다.

사용: python scripts/pnl_reconcile.py [--start YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "stock_trading_bot.sqlite3"


def _conn():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def realized_by_day(conn, start):
    """평균원가법 실현손익(매도일 귀속) + 일별 매수/매도량(이월 감지)."""
    fills = conn.execute(
        "SELECT substr(filled_at,1,10) d, symbol, side, quantity q, price p,"
        " COALESCE(fee,0) fee, COALESCE(tax,0) tax FROM fills"
        " WHERE substr(filled_at,1,10) >= ? ORDER BY filled_at, id", (start,)).fetchall()
    pos = defaultdict(lambda: [0.0, 0.0])   # symbol -> [qty, cost_total]
    realized = defaultdict(float)
    buyq = defaultdict(float)
    sellq = defaultdict(float)
    for f in fills:
        sym, q, p, d = f["symbol"], f["q"], f["p"], f["d"]
        if f["side"] == "buy":
            pos[sym][0] += q
            pos[sym][1] += q * p + f["fee"]
            buyq[d] += q
        else:
            held, cost = pos[sym]
            avg = cost / held if held > 0 else p
            sell_qty = min(q, held) if held > 0 else q
            realized[d] += q * p - f["fee"] - f["tax"] - sell_qty * avg
            pos[sym][0] = max(0.0, held - q)
            pos[sym][1] = avg * pos[sym][0]
            sellq[d] += q
    open_now = {s: v for s, v in pos.items() if v[0] > 0.5}
    return realized, buyq, sellq, open_now


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-09-01")
    args = ap.parse_args()
    conn = _conn()
    realized, buyq, sellq, open_now = realized_by_day(conn, args.start)

    print(f"\n{'='*82}\n신뢰 P&L 스코어보드 — 평균원가 실현손익(SSOT) · {args.start}~\n{'='*82}")
    print(f"{'날짜':<12}{'실현손익(SSOT)':>16}{'매수량':>9}{'매도량':>9}{'이월':>10}{'ds.net_pnl':>13}")
    total = 0.0
    for d in sorted(realized):
        ds = conn.execute("SELECT net_pnl FROM daily_trade_summary WHERE trade_date=?", (d,)).fetchone()
        carry = buyq[d] - sellq[d]
        total += realized[d]
        flag = "  ←이월" if abs(carry) > 1 else ""
        print(f"{d:<12}{realized[d]:>+16,.0f}{buyq[d]:>9,.0f}{sellq[d]:>9,.0f}{carry:>+10,.0f}"
              f"{(ds['net_pnl'] if ds else 0):>+13,.0f}{flag}")
    print(f"{'─'*82}")
    print(f"{'기간 실현손익 합계(SSOT)':<24}{total:>+16,.0f}")
    if open_now:
        print(f"\n※ 아직 미청산(이월 잔여) {len(open_now)}종목 — 실현 미반영분:")
        for s, v in list(open_now.items())[:10]:
            print(f"   {s}: {v[0]:.0f}주 (평균원가 {v[1]/v[0]:,.0f})")
    print("\n[해석] SSOT=평균원가 실현손익(매도일 귀속). clean 데이트레이드일엔 ds.net_pnl과 근사,")
    print("       이월일엔 갈림(이월이 날짜를 넘나듦). 계좌/equity 지표는 deposit버그+이월로 신뢰불가.")
    print()


if __name__ == "__main__":
    main()
