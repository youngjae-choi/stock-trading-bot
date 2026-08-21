#!/usr/bin/env python3
"""전략 사양서(STRATEGY_SPEC.md) 실측·드리프트 동기화 CLI (얇은 래퍼).

핵심 로직·의도(INTENT)는 `backend/services/engine/strategy_spec.py`에 단일 소스로 있다.
CLI와 서버 워치독이 같은 모듈을 써서 드리프트 기준이 갈라지지 않는다.

사용:
  python scripts/strategy_spec_sync.py            # 실측·드리프트 갱신 후 MD 재작성(멱등)
  python scripts/strategy_spec_sync.py --check     # 드리프트만 검사(MD 미수정), 있으면 exit 1
  python scripts/strategy_spec_sync.py --selftest  # 대조 로직 자기검증

읽기 전용(라이브 DB mode=ro) + MD 파일 쓰기만. KIS 호출 없음. 서버 실행 중에도 안전.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.engine.strategy_spec import (  # noqa: E402
    check_conformance,
    check_drift,
    compute_drift,
    sync_strategy_spec,
)


def _selftest() -> int:
    """대조 로직 자기검증 — 합성 불일치를 심어 드리프트가 잡히는지 확인."""
    intent_s = {"a.mode": "enforce", "a.cap": 4.0, "a.flag": False}
    live_ok = {"a.mode": "enforce", "a.cap": 4.0, "a.flag": False}
    live_bad = {"a.mode": "shadow", "a.cap": 15.0}  # mode 변조 + cap 변조 + flag 누락
    sets_i = {"risk_on": {"stop_loss_rate": -0.035}}
    assert compute_drift(intent_s, live_ok, {}, {}) == [], "일치인데 드리프트 오탐"
    bad = compute_drift(intent_s, live_bad, sets_i, {"risk_on": {"stop_loss_rate": -0.09}})
    assert any("a.mode" in d for d in bad), "mode 불일치 미탐"
    assert any("a.cap" in d for d in bad), "cap 불일치 미탐"
    assert any("a.flag" in d and "미설정" in d for d in bad), "누락 미탐"
    assert any("risk_on.stop_loss_rate" in d for d in bad), "SET 불일치 미탐"
    print(f"✅ selftest 통과 — 합성 불일치 {len(bad)}건 모두 탐지")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="드리프트만 검사(MD 미수정), 있으면 exit 1")
    ap.add_argument("--selftest", action="store_true", help="대조 로직 자기검증")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()

    if args.check:
        drift = check_drift()
        conf = check_conformance()
        rc = 0
        if drift:
            print(f"🔴 드리프트(설정값) {len(drift)}건:")
            for d in drift:
                print("  " + d)
            rc = 1
        else:
            print("✅ 드리프트 없음 — 설정 실측이 의도와 일치")
        if conf:
            print(f"🔴 conformance(구현 맞물림) {len(conf)}건:")
            for c in conf:
                print("  " + c)
            rc = 1
        else:
            print("✅ conformance 일치 — SSOT 주장의 구현·설정이 실제 존재")
        return rc

    res = sync_strategy_spec(write=True)
    status = "✅ 드리프트 없음" if not res["drift"] else f"🔴 드리프트 {res['drift']}건"
    wrote = "재작성함" if res["changed"] else "변화 없음(멱등·미수정)"
    print(f"STRATEGY_SPEC.md 동기화 완료 — {status} · {wrote}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
