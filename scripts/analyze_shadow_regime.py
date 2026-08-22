#!/usr/bin/env python3
"""시장감지(엔진②) shadow 검증 — SHADOW-REGIME 로그가 제대로 감지하는지 분석.

엔진②(market_sensing)는 라이브를 안 바꾸고 로그만 남긴다(shadow). 이 도구는 그
`SHADOW-REGIME` 로그를 모아, 새 5장세/전환 판정이 (1)현재 판정과 언제 다른지
(2)전환을 언제 잡았는지 (3)KOSPI 궤적과 함께 보여준다. **활성 전 정확성 확인용.**

읽기 전용(라이브 DB·로그). 매매/서버 영향 없음.

사용:
  sudo journalctl -u stock-trading-bot --since today | python scripts/analyze_shadow_regime.py
  sudo journalctl -u stock-trading-bot --since "2026-08-21" | python scripts/analyze_shadow_regime.py

로그 형식:
  SHADOW-REGIME kospi=1.25 vix=16.0 | 현재(_judge)=risk_off → 5장세=up 전환=- (window3pt)
"""
from __future__ import annotations

import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "stock_trading_bot.sqlite3"

_LINE = re.compile(
    r"SHADOW-REGIME kospi=(?P<kospi>[-0-9.]+) vix=(?P<vix>[^ ]+) \| "
    r"현재\(_judge\)=(?P<cur>\S+) → 5장세=(?P<tier5>\S+) 전환=(?P<trans>\S+)"
)
# 5장세 → 기존 SET 매핑(일치 판단용)
_MAP = {"crash": "risk_off", "down": "risk_off", "flat": "neutral",
        "up": "risk_on", "surge": "risk_on", "volatile": "volatile"}


def parse(lines) -> list[dict]:
    out = []
    for ln in lines:
        m = _LINE.search(ln)
        if not m:
            continue
        ts = ln[:19] if len(ln) >= 19 else ""
        out.append({
            "ts": ts,
            "kospi": float(m["kospi"]),
            "vix": m["vix"],
            "cur": m["cur"],
            "tier5": m["tier5"],
            "trans": None if m["trans"] in ("-", "None") else m["trans"],
        })
    return out


def kospi_series() -> list[tuple[str, float]]:
    try:
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        rows = c.execute(
            "SELECT captured_at, change_rate FROM market_snapshots WHERE symbol='KOSPI' "
            "ORDER BY captured_at"
        ).fetchall()
        c.close()
        return [(str(r[0])[11:16], float(r[1])) for r in rows if r[1] is not None]
    except sqlite3.Error:
        return []


def report(recs: list[dict]) -> None:
    if not recs:
        print("SHADOW-REGIME 로그 없음 — 레짐 틱(30분)마다 기록. 재기동 후 장중 데이터 필요.")
        series = kospi_series()
        if series:
            print(f"\n(참고) 저장된 KOSPI 시계열 {len(series)}건: "
                  + " ".join(f"{t}:{v:+.2f}" for t, v in series[-8:]))
        return
    print(f"\n=== 시장감지 shadow 검증 — SHADOW-REGIME {len(recs)}건 ===")
    # 1) 5장세 분포
    print("\n5장세 판정 분포:", dict(Counter(r["tier5"] for r in recs)))
    # 2) 현재(_judge) vs 새 5장세 일치/불일치
    diff = [r for r in recs if _MAP.get(r["tier5"], "?") != r["cur"]]
    print(f"현재판정 vs 새5장세: 일치 {len(recs)-len(diff)}/{len(recs)}"
          + (f" · 불일치 {len(diff)}건" if diff else " (완전 일치)"))
    for r in diff[:8]:
        print(f"  {r['ts']} kospi={r['kospi']:+.2f} 현재={r['cur']} vs 5장세={r['tier5']}")
    # 3) 폭등 감지(기존엔 없던 티어)
    surge = [r for r in recs if r["tier5"] == "surge"]
    if surge:
        print(f"\n폭등(surge) 감지 {len(surge)}건 — 기존 risk_on에 묻히던 것:")
        for r in surge[:5]:
            print(f"  {r['ts']} kospi={r['kospi']:+.2f}")
    # 4) 전환 감지 이벤트 (핵심 — 8/18 방어)
    trans = [r for r in recs if r["trans"]]
    print(f"\n전환 감지 {len(trans)}건:")
    for r in trans[:12]:
        print(f"  {r['ts']} {r['trans']:<16} kospi={r['kospi']:+.2f} (현재판정={r['cur']})")
    if not trans:
        print("  (없음 — 완만한 장이었거나 window 내 급변 없음)")
    # 5) KOSPI 궤적
    series = kospi_series()
    if series:
        print(f"\nKOSPI 궤적(최근): " + " → ".join(f"{t}:{v:+.2f}" for t, v in series[-10:]))
    print("\n판정: 불일치·전환이 실제 장세와 맞으면 감지 정확 → 활성 검토. "
          "오탐(허위 전환) 많으면 임계(regime.*_transition_pp) 조정.")


def main() -> int:
    recs = parse(sys.stdin) if not sys.stdin.isatty() else []
    report(recs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
