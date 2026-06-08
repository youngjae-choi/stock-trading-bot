from backend.services.engine.order_preflight import _deployment_blocked


def test_deployment_blocked_at_target():
    # 배포율 96% >= 95% → 차단
    assert _deployment_blocked(deployed=96_000_000, total_eval=100_000_000, target=0.95) is True


def test_deployment_not_blocked_below_target():
    assert _deployment_blocked(deployed=80_000_000, total_eval=100_000_000, target=0.95) is False


def test_deployment_gate_disabled_when_total_zero():
    assert _deployment_blocked(deployed=0, total_eval=0, target=0.95) is False
