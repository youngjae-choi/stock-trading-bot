"""(A) KIS 실보유 상한 clamp — DB/매니저 수량이 KIS 실보유보다 부풀려진(드리프트) 매도를
제출 직전에 차단·clamp해 '매도가능수량부족' 업무거부(=유령 매도, 매일 ~30%)를 없앤다.

원칙:
- held < 요청 → 요청을 held로 clamp(실보유만큼만 매도).
- held == 0 → 매도 스킵 + 포지션 제거(KIS에 없는 유령 보유).
- KIS 잔고조회 실패 → fail-open(정당 매도 절대 차단 안 함, 기존 동작 유지).
- 게이트 engine.sell_kis_qty_clamp_enabled=False → clamp 비활성(원복 스위치).
"""

from __future__ import annotations

import asyncio

import backend.services.engine.order_executor as oe
import backend.services.engine.order_reconciliation as orc
import backend.services.settings_store as ss
from backend.services.engine.symbol_norm import norm_symbol

# conftest의 autouse 스텁이 _cached_kis_held_qty를 no-op으로 바꾸므로, clamp 실동작을
# 검증하는 이 파일은 임포트 시점의 실제 구현을 잡아 두었다가 _setup에서 복원한다.
_REAL_CACHED_HELD = oe._cached_kis_held_qty


class _PM:
    def __init__(self) -> None:
        self.removed: list[str] = []
        self._closing: set[str] = set()

    def remove_position(self, symbol: str) -> None:
        self.removed.append(symbol)
        self._closing.discard(symbol)

    def get_exit_context(self, symbol: str):
        return None


async def _sleep_noop(*_a, **_k) -> None:
    return None


def _setup(monkeypatch, order_cash_fn, *, held_map=None, held_raises=False, clamp_on=True):
    """execute_sell을 DB/KIS 없이 실행하도록 의존성을 대체하고 KIS 실보유 맵을 주입한다."""
    executor = oe.OrderExecutor()
    pm = _PM()
    saved: list[dict] = []

    monkeypatch.setattr(oe, "_ensure_orders_table", lambda: None)
    monkeypatch.setattr(oe.OrderExecutor, "_save_order", lambda self, **k: (saved.append(k), f"order-{len(saved)}")[1])
    monkeypatch.setattr(oe, "position_manager", pm)
    monkeypatch.setattr(oe, "find_active_sell_order", lambda *_a, **_k: None)
    monkeypatch.setattr(oe, "load_order_net_positions", lambda *_a, **_k: [])
    monkeypatch.setattr(oe, "order_cash", order_cash_fn)
    monkeypatch.setattr(oe.asyncio, "sleep", _sleep_noop)

    import backend.services.engine.trade_tagging as tt
    import backend.services.engine.momentum_scanner as ms
    monkeypatch.setattr(tt, "merge_exit_context", lambda *_a, **_k: 0)
    monkeypatch.setattr(ms, "note_exit", lambda *_a, **_k: None)

    async def _fake_held():
        if held_raises:
            raise RuntimeError("balance query down")
        return dict(held_map or {})

    # conftest autouse no-op을 해제하고 실제 clamp 구현으로 복원(이 파일이 clamp를 검증).
    monkeypatch.setattr(oe, "_cached_kis_held_qty", _REAL_CACHED_HELD)
    monkeypatch.setattr(orc, "_kis_held_qty_map", _fake_held)
    monkeypatch.setattr(
        ss, "get_setting",
        lambda key, default=None: clamp_on if key == "engine.sell_kis_qty_clamp_enabled" else default,
    )

    oe._SELL_FAIL_COOLDOWN.clear()
    oe._KIS_HELD_CACHE["map"] = None
    oe._KIS_HELD_CACHE["ts"] = 0.0
    return executor, pm, saved


def _held(symbol: str, qty: int) -> dict[str, int]:
    return {norm_symbol(symbol): qty}


def test_clamp_reduces_qty_to_kis_held(monkeypatch):
    """KIS 실보유(5) < 요청(10) → 실보유만큼만(5) 매도 제출한다."""
    calls: list[dict] = []

    async def _order_cash(**kwargs):
        calls.append(kwargs)
        return {"output": {"ODNO": "0000012345"}}

    executor, pm, _saved = _setup(monkeypatch, _order_cash, held_map=_held("005930", 5))
    result = asyncio.run(executor.execute_sell("005930", 10, price=0, reason="STOP_LOSS", name="삼성전자"))

    assert result["ok"] is True
    assert len(calls) == 1
    assert calls[0]["qty"] == 5  # 요청 10 → 실보유 5로 clamp


def test_skip_when_kis_holds_zero(monkeypatch):
    """KIS 실보유 0(유령 보유) → 매도 미제출 + 포지션 제거."""
    calls: list[dict] = []

    async def _order_cash(**kwargs):
        calls.append(kwargs)
        return {"output": {"ODNO": "1"}}

    executor, pm, _saved = _setup(monkeypatch, _order_cash, held_map={})  # 실보유 없음
    result = asyncio.run(executor.execute_sell("005930", 10, price=0, reason="STOP_LOSS", name="삼성전자"))

    assert result["ok"] is False
    assert result["status"] == "skipped_no_kis_holding"
    assert calls == []  # KIS 매도 미호출 — 거부(유령 매도) 자체를 회피
    assert pm.removed == ["005930"]


def test_fail_open_when_balance_query_fails(monkeypatch):
    """KIS 잔고조회 실패 → clamp 미적용, 원 수량 그대로 제출(정당 매도 차단 금지)."""
    calls: list[dict] = []

    async def _order_cash(**kwargs):
        calls.append(kwargs)
        return {"output": {"ODNO": "1"}}

    executor, pm, _saved = _setup(monkeypatch, _order_cash, held_raises=True)
    result = asyncio.run(executor.execute_sell("005930", 10, price=0, reason="STOP_LOSS", name="삼성전자"))

    assert result["ok"] is True
    assert len(calls) == 1
    assert calls[0]["qty"] == 10  # fail-open — 원 수량 유지


def test_clamp_disabled_by_setting(monkeypatch):
    """게이트 OFF면 실보유가 적어도 clamp하지 않는다(원복 스위치)."""
    calls: list[dict] = []

    async def _order_cash(**kwargs):
        calls.append(kwargs)
        return {"output": {"ODNO": "1"}}

    executor, pm, _saved = _setup(monkeypatch, _order_cash, held_map=_held("005930", 5), clamp_on=False)
    result = asyncio.run(executor.execute_sell("005930", 10, price=0, reason="STOP_LOSS", name="삼성전자"))

    assert result["ok"] is True
    assert calls[0]["qty"] == 10  # 게이트 OFF — clamp 없음


def test_no_clamp_when_held_ge_qty(monkeypatch):
    """KIS 실보유(20) ≥ 요청(10) → 원 수량 그대로 제출."""
    calls: list[dict] = []

    async def _order_cash(**kwargs):
        calls.append(kwargs)
        return {"output": {"ODNO": "1"}}

    executor, pm, _saved = _setup(monkeypatch, _order_cash, held_map=_held("005930", 20))
    result = asyncio.run(executor.execute_sell("005930", 10, price=0, reason="STOP_LOSS", name="삼성전자"))

    assert result["ok"] is True
    assert calls[0]["qty"] == 10


def test_ttl_cache_reused_across_consecutive_sells(monkeypatch):
    """연속 매도 시 TTL 내에는 KIS 잔고조회를 재사용한다(호출 폭주 방지)."""
    held_calls = {"n": 0}

    async def _order_cash(**kwargs):
        return {"output": {"ODNO": "1"}}

    executor, pm, _saved = _setup(monkeypatch, _order_cash, held_map=_held("005930", 50))

    async def _counting_held():
        held_calls["n"] += 1
        return _held("005930", 50)

    monkeypatch.setattr(orc, "_kis_held_qty_map", _counting_held)

    asyncio.run(executor.execute_sell("005930", 10, price=0, reason="STOP_LOSS", name="삼성전자"))
    asyncio.run(executor.execute_sell("005930", 10, price=0, reason="STOP_LOSS", name="삼성전자"))

    assert held_calls["n"] == 1  # 두 번째는 캐시 재사용
