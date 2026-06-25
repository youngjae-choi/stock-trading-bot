"""6/26 KIS↔DB 드리프트 수정 사후 검증 (읽기 전용).

배포(2026-06-25 재기동)된 A1·A3·A2·B 수정이 6/26 실거래에서 효과를 냈는지 점검한다.
- 무결성 경고: 이월 오탐 없이 진짜 phantom만 잡히는지 (A3) + 경고 총량 추이
- P&L 정합: day_score(SSOT) vs daily_trade_summary 일치, pnl_source (A2)
- position_cost_basis: 당일 auto_imported/reconciled 원가 기록 여부 (A2 활성 증거)
- KIS↔DB: 서버 /kis/balance(서버 내부 KIS 호출) vs 봇 추적 포지션 일치
- fail-loud: journal에서 체결기록 실패 CRITICAL/알림 유무 (B)

KIS는 직접 호출하지 않고 가동 중 서버 엔드포인트를 통해서만 본다(토큰 단일발급 제약).
사용법: .venv/bin/python scripts/verify_drift_0626.py [YYYY-MM-DD]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = "http://127.0.0.1:8000"


def _get(path: str):
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=12) as r:
            return json.loads(r.read().decode())
    except Exception as exc:  # noqa: BLE001
        return {"_error": str(exc)}


def main() -> int:
    td = sys.argv[1] if len(sys.argv) > 1 else None
    if not td:
        from datetime import datetime, timezone, timedelta
        td = (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d")

    print(f"\n{'='*60}\n  드리프트 수정 사후 검증 — {td}\n{'='*60}")

    # ── 1. 무결성 경고 (A3) ──────────────────────────────────────────
    from backend.services.engine.position_integrity import summarize_order_integrity
    r = summarize_order_integrity(td)
    ws = r.get("integrity_warnings") or r.get("warnings") or []
    print(f"\n[1] 무결성 (A3) — pnl_status={r.get('pnl_status')} pnl_source={r.get('pnl_source')}")
    if not ws:
        print("    ✅ 경고 없음")
    else:
        for w in ws:
            print(f"    - {w}")
    carryover_fp = [w for w in ws if "매도 수량이 매수" in w or "순매도 음수" in w]
    print(f"    매도초과/순매도음수 경고 {len(carryover_fp)}건 (이월 오탐이면 A3 회귀 의심 — 종목 매수이력 대조 필요)")

    # ── 2. P&L 정합 (A2) ─────────────────────────────────────────────
    from backend.services.db import get_connection
    print("\n[2] P&L 정합 (A2)")
    with get_connection() as conn:
        drr = conn.execute(
            "SELECT day_score FROM daily_review_reports WHERE trade_date=?", (td,)
        ).fetchone()
        dts = conn.execute(
            "SELECT realized_pnl, pnl_source FROM daily_trade_summary WHERE trade_date=?", (td,)
        ).fetchone()
    ds = json.loads(drr["day_score"]) if drr and drr["day_score"] else {}
    if ds:
        print(f"    day_score: 완료 {ds.get('completed')} / 승 {ds.get('wins')} / 패 {ds.get('losses')}")
    else:
        print("    day_score 미저장 (S10 미실행?)")
    if dts:
        print(f"    daily_trade_summary: realized_pnl={dts['realized_pnl']:.0f} pnl_source={dts['pnl_source']}")
        if dts["pnl_source"] == "fills+cost_basis":
            print("    ✅ cost_basis 기여 반영됨 (A2 활성)")
    else:
        print("    daily_trade_summary 미저장")

    # ── 3. cost_basis 원장 (A2 활성 증거) ────────────────────────────
    print("\n[3] position_cost_basis 원장 (A2)")
    with get_connection() as conn:
        cbs = conn.execute(
            "SELECT symbol, qty, avg_price, source FROM position_cost_basis WHERE trade_date=?", (td,)
        ).fetchall()
    if cbs:
        for c in cbs:
            print(f"    - {c['symbol']} qty={c['qty']} avg={c['avg_price']:.1f} src={c['source']}")
        print(f"    ✅ {len(cbs)}건 기록 (흡수/정합 포지션 원가 확보)")
    else:
        print("    기록 없음 (당일 흡수/정합 포지션이 없었으면 정상)")

    # ── 4. KIS↔DB 드리프트 (서버 경유) ───────────────────────────────
    print("\n[4] KIS↔DB 포지션 정합 (서버 /kis/balance vs 추적 포지션)")
    bal = _get("/api/v1/kis/balance")
    pos = _get("/api/v1/orders/positions")
    if "_error" in bal or "_error" in pos:
        print(f"    조회 실패 (서버 미가동?): bal={bal.get('_error')} pos={pos.get('_error')}")
    else:
        tracked = {p["symbol"]: p.get("qty") for p in pos.get("payload", {}).get("positions", [])}
        # KIS holdings extraction is best-effort

        def _find(o):
            if isinstance(o, dict):
                for v in o.values():
                    if isinstance(v, list) and v and isinstance(v[0], dict) and any("hldg" in str(k).lower() or "pdno" in str(k).lower() for k in v[0]):
                        return v
                    r = _find(v)
                    if r:
                        return r
            return None
        kl = _find(bal) or []
        kis = {}
        for p in kl:
            s = p.get("pdno") or p.get("symbol")
            q = p.get("hldg_qty") or p.get("qty")
            if s:
                try:
                    kis[str(s)] = int(float(q or 0))
                except (TypeError, ValueError):
                    pass
        only_kis = [s for s in kis if s not in tracked]
        only_db = [s for s in tracked if s not in kis]
        print(f"    KIS {len(kis)}종목 / 봇추적 {len(tracked)}종목")
        print(f"    KIS만 보유(추적 누락): {only_kis or '없음'}")
        print(f"    봇만 추적(KIS 없음): {only_db or '없음'}")
        if not only_kis and not only_db:
            print("    ✅ 완전 일치")

    # ── 5. fail-loud 알림 (B) ────────────────────────────────────────
    print("\n[5] FillPoller fail-loud (B) — 당일 CRITICAL 체결기록 실패")
    try:
        out = subprocess.run(
            ["journalctl", "-u", "stock-trading-bot.service", "--since", f"{td} 00:00", "--no-pager"],
            capture_output=True, text=True, timeout=20,
        ).stdout
        crit = [l for l in out.splitlines() if "CRIT" in l and ("체결기록" in l or "fill" in l.lower())]
        miss = [l for l in out.splitlines() if "체결필드 반복 부재" in l]
        print(f"    체결기록 실패 CRITICAL: {len(crit)}건" + (" ✅ 없음" if not crit else " ⚠️ 발생 — 확인 필요"))
        for l in crit[:5]:
            print(f"      {l[-120:]}")
        if miss:
            print(f"    output2 체결필드 반복부재 알림: {len(miss)}건 (ETN 확인 권장)")
    except Exception as exc:  # noqa: BLE001
        print(f"    journal 조회 실패: {exc}")

    print(f"\n{'='*60}\n  요약: 무결성경고 {len(ws)} / cost_basis {len(cbs)} / "
          f"P&L source={dts['pnl_source'] if dts else 'N/A'}\n{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
