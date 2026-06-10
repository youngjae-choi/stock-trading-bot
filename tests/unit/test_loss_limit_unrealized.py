"""A4 — daily_loss_limit 평가손익(unrealized) 포함 + fail-closed 검증.

배경: 기존 가드는 realized 중심 + equity(account_snapshots, 미기록 테이블) 의존이라
실제로는 한 번도 percent를 산출하지 못했다. 새 로직은
(realized + unrealized) / baseline(장개시 예수금) 기준으로 평가하고,
'조회 실패(예외)'와 '데이터 없음(정상)'을 구분해 전자는 fail-closed 차단한다.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import backend.services.engine.order_preflight as op

RULE = {"daily_loss_limit": -2.0}
TRADE_DATE = "2099-01-10"
BASELINE = 1_000_000.0


def _realized_stub(pnl_krw, data_found=True):
    return {
        "pnl_krw": pnl_krw,
        "equity_krw": None,
        "source": "trading_signals.realized_pnl",
        "data_found": data_found,
        "includes_unrealized": False,
    }


def _patch(monkeypatch, *, realized, unrealized, baseline=BASELINE, market_hours=True):
    """관측 소스를 시나리오에 맞게 대체한다."""
    if isinstance(realized, Exception):
        def _raise(_d):
            raise realized
        monkeypatch.setattr(op, "_realized_daily_pnl", _raise)
    else:
        monkeypatch.setattr(op, "_realized_daily_pnl", lambda _d: realized)
    monkeypatch.setattr(op, "_unrealized_pnl_krw", lambda: unrealized)
    monkeypatch.setattr(op, "get_baseline", lambda _d=None: baseline)
    monkeypatch.setattr(op, "_is_market_hours", lambda now=None: market_hours)


# ── 시나리오 ①: 실현 0 + 평가 -3% → 한도 -2% 차단 ─────────────────────────


def test_unrealized_loss_alone_breaches_limit(monkeypatch):
    _patch(
        monkeypatch,
        realized=_realized_stub(None, data_found=False),  # 당일 실현손익 데이터 없음(정상)
        unrealized=(-30_000.0, 1, 1),  # 평가손실 -3%
    )
    result = op.evaluate_daily_loss_limit(RULE, trade_date=TRADE_DATE)
    assert result["breached"] is True
    assert result["observed_percent"] is not None
    assert abs(result["observed_percent"] - (-3.0)) < 1e-6
    assert result.get("fail_closed") is False


# ── 시나리오 ②: 실현 -1% + 평가 -0.5% = -1.5% → 통과 ──────────────────────


def test_combined_loss_below_limit_passes(monkeypatch):
    _patch(
        monkeypatch,
        realized=_realized_stub(-10_000.0),
        unrealized=(-5_000.0, 1, 1),
    )
    result = op.evaluate_daily_loss_limit(RULE, trade_date=TRADE_DATE)
    assert result["breached"] is False
    assert abs(result["observed_percent"] - (-1.5)) < 1e-6
    assert result.get("fail_closed") is False


def test_combined_loss_at_or_beyond_limit_blocks(monkeypatch):
    _patch(
        monkeypatch,
        realized=_realized_stub(-10_000.0),
        unrealized=(-15_000.0, 2, 2),  # 합계 -2.5%
    )
    result = op.evaluate_daily_loss_limit(RULE, trade_date=TRADE_DATE)
    assert result["breached"] is True


# ── 시나리오 ③: 소스 전부 예외 → fail-closed 차단 ─────────────────────────


def test_all_sources_failing_triggers_fail_closed(monkeypatch):
    _patch(
        monkeypatch,
        realized=RuntimeError("db corrupted"),
        unrealized=(0.0, 0, 0),
    )
    result = op.evaluate_daily_loss_limit(RULE, trade_date=TRADE_DATE)
    assert result["breached"] is False
    assert result.get("fail_closed") is True
    assert result["observed_percent"] is None


def test_fail_closed_not_triggered_outside_market_hours(monkeypatch):
    _patch(
        monkeypatch,
        realized=RuntimeError("db corrupted"),
        unrealized=(0.0, 0, 0),
        market_hours=False,
    )
    result = op.evaluate_daily_loss_limit(RULE, trade_date=TRADE_DATE)
    assert result.get("fail_closed") is False


def test_fail_closed_not_triggered_without_baseline(monkeypatch):
    # baseline 미기록(조회 성공·데이터 없음) 상태에서는 fail-closed 하지 않는다
    _patch(
        monkeypatch,
        realized=RuntimeError("db corrupted"),
        unrealized=(0.0, 0, 0),
        baseline=None,
    )
    result = op.evaluate_daily_loss_limit(RULE, trade_date=TRADE_DATE)
    assert result.get("fail_closed") is False


def test_run_preflight_blocks_on_fail_closed(monkeypatch):
    _patch(
        monkeypatch,
        realized=RuntimeError("db corrupted"),
        unrealized=(0.0, 0, 0),
    )
    # 손실한도 외 게이트·DB 접근 격리
    monkeypatch.setattr(op, "is_new_buy_blocked_by_emergency_halt", lambda: (False, ""))
    monkeypatch.setattr(op, "_budget_cap_check", lambda d: (False, ""))
    monkeypatch.setattr(
        op, "_now_kst",
        lambda: datetime(2099, 1, 10, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
    )

    def _no_db():
        raise RuntimeError("db isolated in test")

    monkeypatch.setattr(op, "get_connection", _no_db)
    monkeypatch.setattr(
        "backend.services.engine.data_quality_guard.get_current_status",
        lambda: "NORMAL",
    )

    result = op.run_preflight(
        {"id": "t-sig", "symbol": "005930", "trigger_price": 70000},
        RULE,
        current_positions_count=0,
    )
    assert result["checks"]["daily_loss_limit"] == "block"
    assert any("손실한도 산출 불가" in r for r in result["block_reasons"])


# ── 시나리오 ④: 데이터 없음(정상) → 통과 ──────────────────────────────────


def test_no_data_normal_state_passes(monkeypatch):
    # 아침 첫 매수: 실현손익 데이터 없음(조회 성공) + 보유 포지션 없음 → 손실 0, 통과
    _patch(
        monkeypatch,
        realized=_realized_stub(None, data_found=False),
        unrealized=(0.0, 0, 0),
    )
    result = op.evaluate_daily_loss_limit(RULE, trade_date=TRADE_DATE)
    assert result["breached"] is False
    assert result.get("fail_closed") is False
    assert result["observed_percent"] == 0.0


def test_no_data_and_no_baseline_passes_without_block(monkeypatch):
    # baseline조차 아직 없는 정상 결측 — 차단 금지
    _patch(
        monkeypatch,
        realized=_realized_stub(None, data_found=False),
        unrealized=(0.0, 0, 0),
        baseline=None,
    )
    result = op.evaluate_daily_loss_limit(RULE, trade_date=TRADE_DATE)
    assert result["breached"] is False
    assert result.get("fail_closed") is False
    assert result["observed_percent"] is None


# ── 보조: unrealized 산출 불가 시 realized-only 폴백 + 라벨 명시 ───────────


def test_unrealized_unavailable_falls_back_to_realized_only(monkeypatch):
    _patch(
        monkeypatch,
        realized=_realized_stub(-10_000.0),
        unrealized=(None, 0, 2),  # 포지션 2개, 가격 전부 미확보
    )
    result = op.evaluate_daily_loss_limit(RULE, trade_date=TRADE_DATE)
    assert result["breached"] is False
    assert abs(result["observed_percent"] - (-1.0)) < 1e-6
    assert "realized_only" in result["source"]


def test_unrealized_pnl_helper_uses_memory_prices(monkeypatch):
    """_unrealized_pnl_krw — position_manager 메모리 + bar_engine 가격만 사용."""
    from backend.services.engine.position_manager import position_manager
    from backend.services.engine.decision_engine import decision_engine

    monkeypatch.setattr(
        position_manager,
        "_positions",
        {
            "005930": {"symbol": "005930", "qty": 10, "entry_price": 1000.0},
            "000660": {"symbol": "000660", "qty": 5, "entry_price": 2000.0},
        },
    )

    class _FakeBarEngine:
        def get_last_price(self, symbol):
            return {"005930": 970.0, "000660": None}.get(symbol)

    monkeypatch.setattr(decision_engine, "_bar_engine", _FakeBarEngine(), raising=False)

    unrealized, priced, total = op._unrealized_pnl_krw()
    assert total == 2
    assert priced == 1  # 000660은 가격 미확보 → 제외
    assert abs(unrealized - (-300.0)) < 1e-6  # (970-1000)*10


def test_unrealized_pnl_helper_no_positions(monkeypatch):
    from backend.services.engine.position_manager import position_manager

    monkeypatch.setattr(position_manager, "_positions", {})
    assert op._unrealized_pnl_krw() == (0.0, 0, 0)
