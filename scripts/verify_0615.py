#!/usr/bin/env python3
"""6/15(월) 리셋 후 첫 거래일 검증 — P1 청산·정합·복기·학습 4대 점검.

리셋(6/13): 6/12 앵커 +4,621,320(실현), 보유 6,499만원(미실현 +3.4M)은 6/15 청산 시 실현 예정.
이 스크립트는 장중/EOD 아무 때나 실행 가능. EOD(15:20 이후) 실행이 가장 의미 있음.

실행: .venv/bin/python scripts/verify_0615.py [trade_date]
"""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

BASE = "http://127.0.0.1:8000"


def _get(path: str) -> dict:
    try:
        with urllib.request.urlopen(BASE + path, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception as exc:  # noqa: BLE001
        return {"_error": str(exc)}


def main() -> None:
    td = sys.argv[1] if len(sys.argv) > 1 else datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    print(f"━━━ 6/15 검증 (기준일 {td}) ━━━\n")

    # 1) 계좌: 보유 포지션 청산 여부 + 누적
    bal = _get("/api/v1/account/balance").get("payload", {})
    positions = bal.get("positions", []) or []
    held_eval = bal.get("stock_eval", 0)
    cum = bal.get("cumulative_pnl", 0)
    realized = cum - bal.get("pnl_total", 0)
    print("【1】 청산 상태 (EOD 후 보유 0이어야 정상)")
    print(f"   보유종목 {len(positions)}개 · 평가 {held_eval:,.0f}원 · 미실현 {bal.get('pnl_total',0):,.0f}")
    print(f"   → {'✅ 청산 완료(보유 0)' if not positions or held_eval == 0 else '⚠️ 보유 잔존 — 청산 확인 필요'}")
    print(f"   계좌 누적 {cum:,.0f} = 실현 {realized:,.0f} + 미실현 {bal.get('pnl_total',0):,.0f}\n")

    # 2) Daily Results 정합 (6/5 이후 누적 실현 = 계좌 실현)
    dr = _get(f"/api/v1/trading-monitor/daily-results?start_date=2026-06-05&end_date={td}").get("payload", [])
    tot = sum((r.get("total_pnl", 0) or 0) for r in dr if not r.get("non_trading"))
    print("【2】 Daily Results 누적 vs 계좌 실현")
    for r in sorted(dr, key=lambda x: x["trade_date"]):
        if r.get("non_trading"):
            continue
        print(f"   {r['trade_date']}  {r.get('total_pnl',0) or 0:>14,.0f}  [{r.get('pnl_status')}]")
    print(f"   ─ 누적 {tot:,.0f}  vs  계좌 실현 {realized:,.0f}  → {'✅ 일치' if abs(tot-realized) < 1000 else '⚠️ 불일치 차이 '+format(tot-realized, ',.0f')}\n")

    # 3) 당일 복기 verified 여부
    today_row = next((r for r in dr if r["trade_date"] == td), None)
    print("【3】 당일 복기 상태")
    if today_row:
        st = today_row.get("pnl_status")
        print(f"   {td}: P&L {today_row.get('total_pnl',0) or 0:,.0f} · 상태 [{st}] · "
              f"승{today_row.get('win_count',0)}/패{today_row.get('loss_count',0)}")
        print(f"   → {'✅ verified' if st == 'verified' else '⚠️ '+str(st)+' — 체결/복기 확인 필요'}")
    else:
        print(f"   {td} 행 없음 (장중이면 EOD 후 생성)\n")
    print()

    # 4) 학습 루프 재가동 (당일 missed/shadow 신규 기록)
    print("【4】 학습 루프 재가동 (리셋 후 당일 신규 기록 쌓이는지)")
    try:
        sys.path.insert(0, ".")
        from backend.services.db import get_connection
        with get_connection() as c:
            m = c.execute("SELECT COUNT(*) n FROM missed_opportunities WHERE trade_date=?", (td,)).fetchone()["n"]
            s = c.execute("SELECT COUNT(*) n FROM shadow_trades WHERE trade_date=?", (td,)).fetchone()["n"]
        print(f"   missed_opportunities {m}건 · shadow_trades {s}건")
        print(f"   → {'✅ 학습 신규 기록' if (m or s) else '장중이면 EOD 후 기록됨'}")
    except Exception as exc:  # noqa: BLE001
        print(f"   DB 조회 실패: {exc}")


if __name__ == "__main__":
    main()
