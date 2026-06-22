"""보유종목 손절 감시 공백 해결 — A/B/C 회귀 가드 (2026-06-22).

배경: 보유종목 손절·트레일링은 100% WS 틱 기반인데, 무틱 종목(KIS가 실시간을 안 보내는
ETN/ETF, 구독 거절·절단 종목)을 구할 안전망이 없어 손절이 장중 방치됐다.
- A: REST 백업을 '전역 stale'→'종목별 stale'로 (무틱 종목만 개별 폴링)
- B: 구독 구성은 보유 우선·상한(_subscription_symbols) — 보유는 절대 절단 안 됨
- C: KIS 구독 거절(rt_cd≠0)을 감지·기록
"""

import asyncio
import time


# ──────────────────────────────────────────────────────────────────────────────
# A. check_exits_via_rest — 종목별 stale 선별 (전역 alive여도 무틱 종목은 폴링)
# ──────────────────────────────────────────────────────────────────────────────

def _fake_position(symbol, active_stop):
    return {"symbol": symbol, "qty": 10, "active_stop_price": active_stop,
            "trailing_active": False, "entry_price": active_stop * 1.05}


def test_rest_backup_polls_only_stale_symbols(monkeypatch):
    from backend.services.engine.position_manager import PositionManager
    import backend.services.engine.position_manager as pm_mod

    pm = PositionManager()
    pm._positions = {"FRESH": _fake_position("FRESH", 100.0), "STALE": _fake_position("STALE", 100.0)}

    now = time.monotonic()
    # FRESH는 방금 틱, STALE은 기록 없음(=한 번도 못 받음) → STALE만 폴링돼야 한다.
    pm._last_tick_by_symbol = {"FRESH": now}
    pm._last_tick_monotonic = now  # 전역은 'alive' — 과거 로직이면 전 종목 skip됐다.

    monkeypatch.setattr(pm_mod, "get_setting", lambda k, d=None: {"risk.stop_loss_backup_enabled": True,
                                                                  "risk.stop_loss_backup_stale_sec": 90}.get(k, d))

    queried = []

    async def fake_price(symbol):
        queried.append(symbol)
        return {"output": {"stck_prpr": "105"}}  # 손절선(100) 위 → 청산 트리거 안 함

    # domestic_service.get_current_price 모킹 (함수 내부 지연 import 대응)
    import backend.services.kis.domestic.service as dsvc
    monkeypatch.setattr(dsvc, "get_current_price", fake_price)

    # 이 테스트는 '어느 종목을 폴링하나'(선별)만 검증 — 가격 처리/청산 로직은 무력화.
    async def _noop_process(position, price):
        return ""
    monkeypatch.setattr(pm, "_process_price", _noop_process)

    result = asyncio.run(pm.check_exits_via_rest())

    assert queried == ["STALE"], f"무틱 종목만 폴링해야 함, got {queried}"
    assert result["checked"] == 1
    assert "STALE" in result["stale"] and "FRESH" not in result["stale"]


def test_rest_backup_falls_back_to_balance_price(monkeypatch):
    """ETN 등 inquire-price가 0이면 잔고(output1 prpr)로 폴백해 손절 판정한다 (E)."""
    from backend.services.engine.position_manager import PositionManager
    import backend.services.engine.position_manager as pm_mod

    pm = PositionManager()
    pm._positions = {"520037": _fake_position("520037", 35000.0)}
    pm._last_tick_by_symbol = {}  # 무틱 → stale
    monkeypatch.setattr(pm_mod, "get_setting", lambda k, d=None: {"risk.stop_loss_backup_enabled": True,
                                                                  "risk.stop_loss_backup_stale_sec": 90}.get(k, d))

    import backend.services.kis.domestic.service as dsvc

    async def bad_price(symbol):
        return {"output": {"stck_prpr": "0"}}  # ETN inquire-price 무효

    async def balance():
        return {"output1": [{"pdno": "520037", "prpr": "37500"}]}  # 잔고는 정상 가격

    monkeypatch.setattr(dsvc, "get_current_price", bad_price)
    monkeypatch.setattr(dsvc, "get_balance", balance)

    seen = {}

    async def _capture(position, price):
        seen["price"] = price
        return ""
    monkeypatch.setattr(pm, "_process_price", _capture)

    result = asyncio.run(pm.check_exits_via_rest())
    assert seen.get("price") == 37500.0, "잔고 폴백 가격으로 손절 판정해야 함"
    assert result["checked"] == 1 and result["errors"] == []


def test_rest_backup_skips_when_all_fresh(monkeypatch):
    from backend.services.engine.position_manager import PositionManager
    import backend.services.engine.position_manager as pm_mod

    pm = PositionManager()
    pm._positions = {"A": _fake_position("A", 100.0), "B": _fake_position("B", 100.0)}
    now = time.monotonic()
    pm._last_tick_by_symbol = {"A": now, "B": now}
    pm._last_tick_monotonic = now
    monkeypatch.setattr(pm_mod, "get_setting", lambda k, d=None: {"risk.stop_loss_backup_enabled": True,
                                                                  "risk.stop_loss_backup_stale_sec": 90}.get(k, d))
    result = asyncio.run(pm.check_exits_via_rest())
    assert result.get("skipped") == "all_fresh" and result["checked"] == 0


def test_on_tick_records_per_symbol_time():
    from backend.services.engine.position_manager import PositionManager
    pm = PositionManager()
    asyncio.run(pm.on_tick({"symbol": "005930", "price": "70000"}))
    assert "005930" in pm._last_tick_by_symbol
    assert pm._last_tick_monotonic is not None


# ──────────────────────────────────────────────────────────────────────────────
# B. _subscription_symbols — 보유는 항상 앞·절대 절단 안 됨 (후보가 상한 초과해도)
# ──────────────────────────────────────────────────────────────────────────────

def test_subscription_held_never_truncated():
    from backend.services.engine.decision_engine import _subscription_symbols
    held = ["H1", "H2", "H3"]
    candidates = [f"C{i}" for i in range(100)]  # 후보 100개 (상한 10 초과)
    out = _subscription_symbols(held, candidates, cap=10)
    # 보유 3종목 전부 포함되고 맨 앞에 위치
    assert out[:3] == ["H1", "H2", "H3"]
    assert all(h in out for h in held)
    # 전체는 상한(10) 이내 — 보유 우선이라 후보는 7개만
    assert len(out) == 10
    assert out.count("H1") == 1  # 중복 없음


def test_subscription_dedup_held_in_candidates():
    from backend.services.engine.decision_engine import _subscription_symbols
    out = _subscription_symbols(["H1"], ["H1", "C1"], cap=10)
    assert out == ["H1", "C1"]


# ──────────────────────────────────────────────────────────────────────────────
# C. _handle_subscribe_ack — 구독 거절(rt_cd≠0) 감지·기록, 성공은 해제
# ──────────────────────────────────────────────────────────────────────────────

def test_subscribe_reject_recorded():
    from backend.services.kis.realtime_ws import RealtimeWSManager
    m = RealtimeWSManager()
    payload = {"header": {"tr_id": "H0STCNT0", "tr_key": "520037"},
               "body": {"rt_cd": "1", "msg1": "초과 등록 종목수"}}
    m._handle_subscribe_ack(payload, payload["header"], "H0STCNT0")
    assert "520037" in m._subscribe_rejected


def test_subscribe_success_clears_reject():
    from backend.services.kis.realtime_ws import RealtimeWSManager
    m = RealtimeWSManager()
    m._subscribe_rejected = {"005930": "이전 거절"}
    payload = {"header": {"tr_id": "H0STCNT0", "tr_key": "005930"},
               "body": {"rt_cd": "0", "msg1": "SUBSCRIBE SUCCESS"}}
    m._handle_subscribe_ack(payload, payload["header"], "H0STCNT0")
    assert "005930" not in m._subscribe_rejected


def test_subscribe_already_is_benign():
    from backend.services.kis.realtime_ws import RealtimeWSManager
    m = RealtimeWSManager()
    payload = {"header": {"tr_id": "H0STCNT0", "tr_key": "005930"},
               "body": {"rt_cd": "1", "msg1": "ALREADY IN SUBSCRIBE"}}
    m._handle_subscribe_ack(payload, payload["header"], "H0STCNT0")
    assert "005930" not in m._subscribe_rejected  # 이미 구독 = 정상


def test_subscribe_health_shape():
    from backend.services.kis.realtime_ws import RealtimeWSManager
    m = RealtimeWSManager()
    m._symbols = ["A", "B"]
    h = m.get_subscribe_health()
    assert h["subscribed"] == ["A", "B"] and "rejected" in h and "connected" in h
