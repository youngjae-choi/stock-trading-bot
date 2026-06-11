"""B1: 매도 제출실패 시 포지션 보존 + 부분체결 잔량 재주문 (2026-06-11).

배경(실계좌 전환 안전벨트):
- 매도 주문 제출이 완전히 실패(KIS 예외, 재시도 소진)해도 포지션을 보존해
  손절 감시에서 빠지는 '유령 보유'를 막는다. 대신 60초 쿨다운으로 재청산 폭주를 방지.
- 매도 부분체결이 정체(2회 연속 체결수량 미진행)되면 잔량만 시장가로 1회 재주문한다.
  매수 partial은 건드리지 않는다(EOD 취소 경로 존재).
"""

from __future__ import annotations

import asyncio
import time

import backend.services.engine.fill_poller as fp
import backend.services.engine.order_executor as oe


# ──────────────────────────────────────────────
# 공용 스텁/헬퍼
# ──────────────────────────────────────────────

class _PositionManagerStub:
    """remove_position 호출 여부와 _closing 마크를 기록하는 스텁."""

    def __init__(self) -> None:
        self.removed: list[str] = []
        self._closing: set[str] = set()

    def remove_position(self, symbol: str) -> None:
        self.removed.append(symbol)
        self._closing.discard(symbol)

    def get_exit_context(self, symbol: str):
        return None


async def _sleep_noop(_seconds: float) -> None:
    return None


def _setup_sell_env(monkeypatch, order_cash_fn):
    """execute_sell을 DB/KIS 없이 실행할 수 있도록 의존성을 모두 대체한다."""
    executor = oe.OrderExecutor()
    pm = _PositionManagerStub()
    saved_orders: list[dict] = []

    def _fake_save_order(self, **kwargs):
        saved_orders.append(kwargs)
        return f"order-{len(saved_orders)}"

    monkeypatch.setattr(oe, "_ensure_orders_table", lambda: None)
    monkeypatch.setattr(oe.OrderExecutor, "_save_order", _fake_save_order)
    monkeypatch.setattr(oe, "position_manager", pm)
    monkeypatch.setattr(oe, "find_active_sell_order", lambda *_a, **_k: None)
    monkeypatch.setattr(oe, "load_order_net_positions", lambda *_a, **_k: [])
    monkeypatch.setattr(oe, "order_cash", order_cash_fn)
    monkeypatch.setattr(oe.asyncio, "sleep", _sleep_noop)
    # 성공 경로의 best-effort 후처리(태깅/쿨다운)가 라이브 DB를 건드리지 않게 차단
    import backend.services.engine.trade_tagging as tt
    import backend.services.engine.momentum_scanner as ms
    monkeypatch.setattr(tt, "merge_exit_context", lambda *_a, **_k: 0)
    monkeypatch.setattr(ms, "note_exit", lambda *_a, **_k: None)
    # 테스트 간 모듈 상태 오염 방지
    oe._SELL_FAIL_COOLDOWN.clear()
    return executor, pm, saved_orders


# ──────────────────────────────────────────────
# ① 매도 전체실패 → 포지션 보존 + 쿨다운 등록
# ──────────────────────────────────────────────

def test_sell_total_failure_preserves_position_and_sets_cooldown(monkeypatch):
    """제출이 전부 실패(예외 종료)하면 remove_position을 호출하지 않고 쿨다운을 기록한다."""
    calls = []

    async def _boom(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("KIS down")

    executor, pm, saved = _setup_sell_env(monkeypatch, _boom)
    result = asyncio.run(executor.execute_sell("005930", 10, price=0, reason="STOP_LOSS", name="삼성전자"))

    assert result["ok"] is False
    assert pm.removed == []  # 포지션 보존 — 유령 보유 방지
    assert "005930" in oe._SELL_FAIL_COOLDOWN  # 쿨다운 등록
    assert len(calls) == 3  # limit 1차 + market 2회 재시도
    assert saved and saved[-1]["status"] == "failed"  # trading_orders 'failed' 기록 유지


def test_sell_total_failure_clears_closing_mark(monkeypatch):
    """제출실패 시 on_tick의 _closing 마크를 해제해 손절 감시가 재개되게 한다."""
    async def _boom(**kwargs):
        raise RuntimeError("KIS down")

    executor, pm, _saved = _setup_sell_env(monkeypatch, _boom)
    pm._closing.add("005930")
    asyncio.run(executor.execute_sell("005930", 10, price=0, reason="STOP_LOSS", name="삼성전자"))
    assert "005930" not in pm._closing


# ──────────────────────────────────────────────
# ② 쿨다운 중 재호출 → skip
# ──────────────────────────────────────────────

def test_sell_during_cooldown_skips_without_kis_call(monkeypatch):
    """쿨다운 60초 이내 재호출이면 KIS 호출 없이 skipped_sell_cooldown으로 즉시 반환한다."""
    calls = []

    async def _order_cash(**kwargs):
        calls.append(kwargs)
        return {"output": {"ODNO": "1234"}}

    executor, pm, saved = _setup_sell_env(monkeypatch, _order_cash)
    oe._SELL_FAIL_COOLDOWN["005930"] = time.monotonic()  # 방금 실패한 상태

    result = asyncio.run(executor.execute_sell("005930", 10, price=0, reason="STOP_LOSS", name="삼성전자"))

    assert result["ok"] is False
    assert result["status"] == "skipped_sell_cooldown"
    assert calls == []  # KIS 미호출
    assert pm.removed == []


def test_sell_after_cooldown_expiry_proceeds_and_clears_cooldown(monkeypatch):
    """쿨다운 만료 후에는 정상 제출되고, 성공 시 쿨다운/포지션이 정리된다."""
    async def _order_cash(**kwargs):
        return {"output": {"ODNO": "1234"}}

    executor, pm, _saved = _setup_sell_env(monkeypatch, _order_cash)
    oe._SELL_FAIL_COOLDOWN["005930"] = time.monotonic() - (oe._SELL_FAIL_COOLDOWN_SEC + 1)

    result = asyncio.run(executor.execute_sell("005930", 10, price=0, reason="STOP_LOSS", name="삼성전자"))

    assert result["ok"] is True
    assert "005930" not in oe._SELL_FAIL_COOLDOWN  # 성공 시 쿨다운 해제
    assert pm.removed == ["005930"]  # 성공 경로 remove_position은 기존대로


def test_sell_uncertain_path_still_removes_position(monkeypatch):
    """주문번호 미획득(uncertain) 경로의 remove_position(중복매도 방지)은 변경하지 않는다."""
    async def _order_cash(**kwargs):
        return {"output": {}}  # 접수됐지만 ODNO 누락

    async def _ccld_fail(*_a, **_k):
        raise RuntimeError("ccld unavailable")

    import backend.services.kis.domestic.service as kis_svc
    monkeypatch.setattr(kis_svc, "get_daily_order_inquiry", _ccld_fail)

    executor, pm, _saved = _setup_sell_env(monkeypatch, _order_cash)
    result = asyncio.run(executor.execute_sell("005930", 10, price=0, reason="STOP_LOSS", name="삼성전자"))

    assert result["ok"] is False
    assert result.get("uncertain") is True
    assert pm.removed == ["005930"]  # 중복매도 방지 목적 — 유지
    assert "005930" not in oe._SELL_FAIL_COOLDOWN  # 제출 자체는 성공이므로 쿨다운 없음


# ──────────────────────────────────────────────
# ③④⑤ 부분체결 잔량 재주문 (fill_poller)
# ──────────────────────────────────────────────

def _reset_partial_state():
    fp._PARTIAL_PROGRESS.clear()
    fp._REMAINDER_REORDERED.clear()


def _patch_reorder_recorder(monkeypatch):
    reorders: list[tuple[str, int]] = []

    async def _fake_reorder(order, rmn_qty):
        reorders.append((str(order.get("id")), int(rmn_qty)))

    monkeypatch.setattr(fp, "_reorder_sell_remainder", _fake_reorder)
    return reorders


def _patch_setting(monkeypatch, enabled: bool):
    import backend.services.settings_store as ss
    monkeypatch.setattr(ss, "get_setting", lambda _key, default=None: enabled)


def _sell_order(order_id="o1", qty=1000):
    return {"id": order_id, "side": "sell", "symbol": "005930", "name": "삼성전자",
            "qty": qty, "trade_date": "2026-06-11", "kis_order_no": "0000012345"}


def test_partial_stall_two_polls_triggers_remainder_reorder_once(monkeypatch):
    """매도 partial이 2회 연속 정체되면 잔량 재주문을 정확히 1회만 낸다."""
    _reset_partial_state()
    reorders = _patch_reorder_recorder(monkeypatch)
    _patch_setting(monkeypatch, True)
    order = _sell_order()

    asyncio.run(fp._maybe_reorder_sell_remainder(order, ccld_qty=600, rmn_qty=400))  # 기준점
    asyncio.run(fp._maybe_reorder_sell_remainder(order, ccld_qty=600, rmn_qty=400))  # 정체 1회
    assert reorders == []
    asyncio.run(fp._maybe_reorder_sell_remainder(order, ccld_qty=600, rmn_qty=400))  # 정체 2회 → 발동
    assert reorders == [("o1", 400)]
    asyncio.run(fp._maybe_reorder_sell_remainder(order, ccld_qty=600, rmn_qty=400))  # 추가 정체
    assert reorders == [("o1", 400)]  # 같은 주문 재주문은 1회만


def test_partial_progress_resets_stall_counter(monkeypatch):
    """체결수량이 증가(진행 중)하면 정체 카운터가 리셋되어 재주문하지 않는다."""
    _reset_partial_state()
    reorders = _patch_reorder_recorder(monkeypatch)
    _patch_setting(monkeypatch, True)
    order = _sell_order()

    asyncio.run(fp._maybe_reorder_sell_remainder(order, ccld_qty=500, rmn_qty=500))
    asyncio.run(fp._maybe_reorder_sell_remainder(order, ccld_qty=500, rmn_qty=500))  # 정체 1회
    asyncio.run(fp._maybe_reorder_sell_remainder(order, ccld_qty=700, rmn_qty=300))  # 진행 → 리셋
    asyncio.run(fp._maybe_reorder_sell_remainder(order, ccld_qty=700, rmn_qty=300))  # 정체 1회
    assert reorders == []


def test_partial_reorder_disabled_by_setting(monkeypatch):
    """risk.partial_fill_reorder_enabled=False면 감지·로그만 하고 재주문하지 않는다."""
    _reset_partial_state()
    reorders = _patch_reorder_recorder(monkeypatch)
    _patch_setting(monkeypatch, False)
    order = _sell_order()

    for _ in range(4):
        asyncio.run(fp._maybe_reorder_sell_remainder(order, ccld_qty=600, rmn_qty=400))
    assert reorders == []


def test_buy_partial_never_reorders(monkeypatch):
    """매수 partial은 잔량 재주문 대상이 아니다(EOD 취소 경로 존재)."""
    _reset_partial_state()
    reorders = _patch_reorder_recorder(monkeypatch)
    _patch_setting(monkeypatch, True)
    order = dict(_sell_order(), side="buy")

    for _ in range(4):
        asyncio.run(fp._maybe_reorder_sell_remainder(order, ccld_qty=600, rmn_qty=400))
    assert reorders == []


def test_reorder_helper_submits_market_sell_with_origin_reference(monkeypatch):
    """_reorder_sell_remainder는 잔량만 시장가 매도로 제출하고 원주문 id를 signal_id에 남긴다."""
    _reset_partial_state()
    kis_calls: list[dict] = []
    saved_orders: list[dict] = []

    async def _order_cash(**kwargs):
        kis_calls.append(kwargs)
        return {"output": {"ODNO": "0000099999"}}

    import backend.services.kis.domestic.service as kis_svc
    monkeypatch.setattr(kis_svc, "order_cash", _order_cash)

    def _fake_save_order(self, **kwargs):
        saved_orders.append(kwargs)
        return "new-order-1"

    monkeypatch.setattr(oe.OrderExecutor, "_save_order", _fake_save_order)

    asyncio.run(fp._reorder_sell_remainder(_sell_order(), rmn_qty=400))

    assert len(kis_calls) == 1
    assert kis_calls[0]["side"] == "sell"
    assert kis_calls[0]["qty"] == 400
    assert kis_calls[0]["ord_dvsn"] == "01"  # 시장가
    assert len(saved_orders) == 1
    assert saved_orders[0]["side"] == "sell"
    assert saved_orders[0]["reason"] == "PARTIAL_FILL_REMAINDER"
    assert saved_orders[0]["signal_id"] == "o1"  # 원주문 참조
    assert saved_orders[0]["qty"] == 400
    assert saved_orders[0]["status"] == "submitted"


def test_reorder_failure_never_raises(monkeypatch):
    """잔량 재주문 내부 오류는 폴링 루프로 전파되지 않는다."""
    _reset_partial_state()
    _patch_setting(monkeypatch, True)

    async def _boom(order, rmn_qty):
        raise RuntimeError("KIS down")

    monkeypatch.setattr(fp, "_reorder_sell_remainder", _boom)
    order = _sell_order()
    for _ in range(3):
        # 예외 없이 통과해야 한다
        asyncio.run(fp._maybe_reorder_sell_remainder(order, ccld_qty=600, rmn_qty=400))
