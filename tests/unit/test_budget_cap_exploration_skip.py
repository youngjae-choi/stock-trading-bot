"""budget_cap — 배포 게이트 활성(탐색모드) 시 누적매수 캡 건너뛰기 (PM 결정 2026-06-10).

배경: 6/10 누적매수 기준 budget_cap(baseline×budget_rate)이 09:40 이후 매수 1,578건을
전면 차단. 누적 기준이라 매도해도 룸이 회복되지 않아 풀배포·교체매매 모델과 정면 충돌.
95% 배포 게이트(현재 배포액 기준)가 동일 역할을 수행하므로, deploy_target_rate>0이면
budget_cap을 생략한다(checks에 'skipped_deploy_gate'로 가시화).
"""

import backend.services.engine.order_preflight as op


def _signal():
    return {"id": "t-sig", "symbol": "005930", "price": 70000, "confidence": 0.9}


def _rule():
    return {"min_confidence": 0.0}


def test_budget_cap_skipped_when_deploy_gate_active(monkeypatch):
    # 예산 소진 상태를 강제해도, 배포 게이트 활성이면 차단되지 않아야 한다
    monkeypatch.setattr(op, "_budget_cap_check", lambda d: (True, "일일 투입예산 소진 (테스트)"))
    result = op.run_preflight(
        _signal(), _rule(),
        current_positions_count=0,
        deployed_value=10_000_000.0,
        total_eval=100_000_000.0,
        deploy_target_rate=0.95,
    )
    assert result["checks"]["budget_cap"] == "skipped_deploy_gate"
    assert all("투입예산" not in r for r in (result.get("block_reasons") or []))


def test_budget_cap_still_blocks_without_deploy_gate(monkeypatch):
    # 배포 게이트 미사용(비탐색) 경로에서는 기존 동작 유지
    monkeypatch.setattr(op, "_budget_cap_check", lambda d: (True, "일일 투입예산 소진 (테스트)"))
    result = op.run_preflight(_signal(), _rule(), current_positions_count=0)
    assert result["checks"]["budget_cap"] == "block"
    assert any("투입예산" in r for r in (result.get("block_reasons") or []))
