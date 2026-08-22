#!/usr/bin/env python3
"""6엔진 통합 모니터 — 월요일 각 엔진을 한 화면에서 점검.

각 엔진의 상태(활성/shadow/구축/미착수) + 라이브 값 + 드리프트/conformance를 한 번에.
로그 상세(SIZING-ACTIVE·SHADOW-REGIME 카운트)는 journalctl을 파이프하면 집계한다.

사용:
  python scripts/monitor_engines.py                               # DB+설정+SSOT 상태
  sudo journalctl -u stock-trading-bot --since today | python scripts/monitor_engines.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DB = ROOT / "data" / "stock_trading_bot.sqlite3"


def _conn():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def _get(conn, key, default=""):
    row = conn.execute("SELECT value_json FROM system_settings WHERE key=?", (key,)).fetchone()
    if row:
        return row["value_json"]
    try:
        from backend.services.engine.strategy_spec import INTENT_CODE_DEFAULTS
        if key in INTENT_CODE_DEFAULTS:
            return f"{INTENT_CODE_DEFAULTS[key]}(코드기본)"
    except Exception:
        pass
    return default


def _count_logs(text, tag):
    return sum(1 for ln in text.splitlines() if tag in ln)


def main() -> int:
    log_text = "" if sys.stdin.isatty() else sys.stdin.read()
    conn = _conn()
    print("=" * 68)
    print(" 6엔진 통합 모니터 — 월요일 점검")
    print("=" * 68)

    # ── SSOT 폐루프 ──
    try:
        from backend.services.engine.strategy_spec import check_conformance, check_drift
        drift, conf = check_drift(), check_conformance()
        print(f"\n[SSOT 폐루프] 드리프트 {len(drift)}건 · conformance {len(conf)}건 "
              f"{'✅ 정합' if not drift and not conf else '🔴 확인필요'}")
        for x in (drift + conf)[:5]:
            print("   " + x)
    except Exception as exc:
        print(f"\n[SSOT] 체크 실패: {exc}")

    # ── 엔진① 사이징(활성) ──
    print("\n[엔진① 사이징] 활성:", _get(conn, "sizing.model_active"),
          "| 종목당", _get(conn, "sizing.per_position_rate_min"), "~",
          _get(conn, "risk.max_position_rate_per_stock"),
          "| 폭등상한", _get(conn, "sizing.surge_per_position_rate_max"))
    if log_text:
        print(f"   오늘 SIZING-ACTIVE {_count_logs(log_text, 'SIZING-ACTIVE')}건 · "
              f"SHADOW-SIZING {_count_logs(log_text, 'SHADOW-SIZING')}건")

    # ── 엔진② 시장감지(shadow) + 대응(gated) ──
    cur5 = _get(conn, "regime.current_5tier", "-")
    curt = _get(conn, "regime.current_transition", "-")
    print(f"\n[엔진② 시장감지] 현재 5장세={cur5} 전환={curt} "
          f"| 대응활성={_get(conn, 'regime.transition_response_active')} "
          f"트레일배수={_get(conn, 'regime.transition_trail_tighten_factor')}")
    ks = conn.execute(
        "SELECT COUNT(*) n, MIN(substr(captured_at,12,5)) a, MAX(substr(captured_at,12,5)) b "
        "FROM market_snapshots WHERE symbol='KOSPI' AND substr(captured_at,1,10)="
        "(SELECT MAX(substr(captured_at,1,10)) FROM market_snapshots WHERE symbol='KOSPI')"
    ).fetchone()
    print(f"   KOSPI 시계열(최근일): {ks['n']}점 {ks['a']}~{ks['b']}")
    if log_text:
        print(f"   오늘 SHADOW-REGIME {_count_logs(log_text, 'SHADOW-REGIME')}건")

    # ── 엔진③ 종목선정(모듈 구축, 미배선) ──
    print(f"\n[엔진③ 종목선정] 점수 가중치 등락률={_get(conn, 'selection.change_weight', '0.5(기본)')}"
          f" 거래량={_get(conn, 'selection.surge_weight', '0.5(기본)')} (모듈 구축, 미배선)")

    # ── ④⑤⑥ ──
    print("\n[엔진④ 매수·⑤ 매도·⑥ 매매] 미착수(엔진①②③ 우선)")
    print("\n" + "=" * 68)
    print(" 요약: ① 활성 · ② 감지shadow+대응gated · ③ 모듈 · ④⑤⑥ 미착수")
    print("=" * 68)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
