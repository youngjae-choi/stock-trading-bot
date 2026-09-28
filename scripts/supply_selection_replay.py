#!/usr/bin/env python3
"""수급 1차 선정 재보정 replay (Phase 1, read-only).

문제(2026-09-28 실측): 수급 오버레이가 enforce인데 사실상 무력.
  - weight 0.3이 낮아 등락률+거래량 base가 지배 → 진짜 순매수 리더(엑스게이트 외국인+3083)가 7위로 매몰.
  - tanh 포화 10000이 커서 순매수 금액이 대부분 0.4~0.5 중립으로 뭉침(분리력 상실).
  - gate_min -0.5(signed)가 느슨해 외국인 -2013 순매도(아이씨티케이)도 통과(오늘 배제 0건).

이 스크립트는 universe_filter_results(오늘 저장된 실제 14종목·실제 순매수 금액)에
재보정 파라미터(saturation·weight·gate)를 적용해 **현행 vs 재보정 순위**를 비교한다.
라이브 미변경(read-only). 목적: 코드/설정 변경 전에 "재보정이 리더를 올리고 순매도를 거르는지" 수치 증명.

사용: python scripts/supply_selection_replay.py [--date YYYY-MM-DD] [--sat 1500] [--weight 0.6] [--gate -0.1] [--topn 9]
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "stock_trading_bot.sqlite3"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def load_items(conn, date: str) -> list[dict]:
    row = conn.execute(
        "SELECT items FROM universe_filter_results WHERE trade_date=? ORDER BY rowid DESC LIMIT 1",
        (date,),
    ).fetchone()
    if not row:
        return []
    try:
        return json.loads(row["items"])
    except (TypeError, ValueError):
        return []


def recompute(items: list[dict], sat: float, weight: float, gate_signed_min: float) -> tuple[list[dict], list[dict]]:
    """재보정 supply_score·combined 계산 + gate 적용 후 combined 내림차순 정렬."""
    out = []
    for it in items:
        base = _num(it.get("score"))
        frgn = it.get("frgn_ntby_amount")
        orgn = it.get("orgn_ntby_amount")
        available = it.get("supply_available", frgn is not None or orgn is not None)
        combined_amt = _num(frgn) + _num(orgn)
        signed = math.tanh(combined_amt / sat) if sat > 0 else 0.0
        supply_score = (signed + 1.0) / 2.0 if available else 0.5
        gated_out = available and signed < gate_signed_min
        new_combined = (1.0 - weight) * base + weight * supply_score
        out.append({
            "symbol": it.get("symbol"),
            "name": it.get("name"),
            "change_rate": _num(it.get("change_rate")),
            "base": base,
            "cur_rank": it.get("rank"),
            "cur_supply_rank": it.get("supply_rank"),
            "frgn": _num(frgn),
            "orgn": _num(orgn),
            "combined_amt": combined_amt,
            "signed": signed,
            "supply_score": supply_score,
            "new_combined": new_combined,
            "gated_out": gated_out,
        })
    kept = [x for x in out if not x["gated_out"]]
    kept.sort(key=lambda x: x["new_combined"], reverse=True)
    for i, x in enumerate(kept, 1):
        x["new_rank"] = i
    return out, kept


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-09-28")
    ap.add_argument("--sat", type=float, default=1500.0, help="tanh 포화 스케일(순매수 금액)")
    ap.add_argument("--weight", type=float, default=0.6, help="수급 가중(1차 승격이면 >0.5)")
    ap.add_argument("--gate", type=float, default=-0.1, help="gate signed 하한(이 미만 순매도 배제)")
    ap.add_argument("--topn", type=int, default=9)
    args = ap.parse_args()

    conn = _conn()
    items = load_items(conn, args.date)
    if not items:
        print(f"[{args.date}] universe_filter_results 항목 없음")
        return

    all_out, kept = recompute(items, args.sat, args.weight, args.gate)
    excluded = [x for x in all_out if x["gated_out"]]

    print(f"\n{'='*96}")
    print(f"수급 1차 선정 재보정 replay — {args.date}  (sat={args.sat:.0f} weight={args.weight:.2f} gate_signed<{args.gate})")
    print(f"현행 파라미터: sat=10000 weight=0.30 gate_signed<-0.5  →  today gate제외 0건, 리더 매몰")
    print(f"{'='*96}")

    print(f"\n■ 재보정 순위 (수급 1차) — top{args.topn} 선정")
    print(f"{'新':>3}{'現':>4} {'종목':<12}{'등락%':>7}{'외국인':>8}{'기관':>7}{'순매수계':>9}{'수급점':>7}{'결합':>7}")
    for x in kept:
        star = " ★top" if x["new_rank"] <= args.topn else ""
        nm = (x["name"] or "")[:6]
        print(f"{x['new_rank']:>3}{str(x['cur_rank']):>4} {nm:<12}{x['change_rate']:>+7.1f}"
              f"{x['frgn']:>+8.0f}{x['orgn']:>+7.0f}{x['combined_amt']:>+9.0f}"
              f"{x['supply_score']:>7.3f}{x['new_combined']:>7.3f}{star}")

    if excluded:
        print(f"\n■ 게이트 배제(순매도) {len(excluded)}건 — 현행은 0건이라 이들이 다 통과했음")
        for x in excluded:
            nm = (x["name"] or "")[:6]
            print(f"    {nm:<12} 등락{x['change_rate']:>+6.1f}% 외국인{x['frgn']:>+7.0f} 기관{x['orgn']:>+6.0f} "
                  f"순매수계{x['combined_amt']:>+8.0f} (現순위 {x['cur_rank']})")

    # 현행 top_n vs 재보정 top_n 차집합
    cur_top = sorted(all_out, key=lambda z: (z["cur_rank"] or 999))[:args.topn]
    cur_syms = {z["symbol"] for z in cur_top}
    new_top = kept[:args.topn]
    new_syms = {z["symbol"] for z in new_top}
    added = [z for z in new_top if z["symbol"] not in cur_syms]
    dropped = [z for z in cur_top if z["symbol"] not in new_syms]
    print(f"\n■ top{args.topn} 변화")
    print(f"  신규 진입(수급 리더): {', '.join((z['name'] or '')[:6]+f'(계{z['combined_amt']:+.0f})' for z in added) or '없음'}")
    print(f"  탈락(급등/순매도)   : {', '.join((z['name'] or '')[:6]+f'(계{z['combined_amt']:+.0f})' for z in dropped) or '없음'}")
    print()


if __name__ == "__main__":
    main()
