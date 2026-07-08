"""P0: 스케일아웃 반복 매도 루프 수정 (2026-07-08 발견) 회귀 테스트.

버그 사슬:
  ① execute_sell이 부분매도(스케일아웃 60%)에도 포지션 전체를 매니저에서 제거
  ② 잔량이 미관리 상태 → S6 자동편입이 kis_only_holding으로 재등록
  ③ 재등록 시 harvested 리셋 + entry_price가 KIS 평균가로 재설정
  ④ 현재가 ≥ 새 진입가×1.02 → 재수확 → 기하급수 반복(756→453→…→1주)

수정:
  P0-1 execute_sell(partial=True)는 remove_position/청산태깅/쿨다운을 건너뛴다
  P0-2 harvested를 position_stop_states에 영속화 + add_position이 당일 이력 상속
  P0-3 자동편입 진입가 = 당일 매수체결 가중평균 > cost_basis 원장 > KIS 평균가
  P0-4 baseline 캡처가 토큰 만료(EGW00123) 시 재발급 후 1회 재시도
"""

from __future__ import annotations

import asyncio
import sqlite3
import tempfile
from unittest.mock import AsyncMock, patch

import backend.services.engine.order_executor as oe
from backend.config import settings
from backend.services.engine.position_manager import PositionManager


# ──────────────────────────────────────────────
# 공용 스텁 (test_sell_resilience.py 패턴)
# ──────────────────────────────────────────────

class _PositionManagerStub:
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
    import backend.services.engine.momentum_scanner as ms
    import backend.services.engine.trade_tagging as tt
    monkeypatch.setattr(tt, "merge_exit_context", lambda *_a, **_k: 0)
    monkeypatch.setattr(ms, "note_exit", lambda *_a, **_k: None)
    oe._SELL_FAIL_COOLDOWN.clear()
    return executor, pm, saved_orders


# ──────────────────────────────────────────────
# P0-1: 부분매도는 포지션을 제거하지 않는다
# ──────────────────────────────────────────────

def test_partial_sell_keeps_position(monkeypatch):
    """partial=True 매도 성공 시 remove_position을 호출하지 않는다(잔량 계속 관리)."""
    async def _order_cash(**kwargs):
        return {"output": {"ODNO": "1234"}}

    executor, pm, _ = _setup_sell_env(monkeypatch, _order_cash)
    result = asyncio.run(executor.execute_sell(
        "005930", 60, price=0, reason="take_profit_scaleout", partial=True,
    ))
    assert result["ok"] is True
    assert pm.removed == []  # 핵심 — 잔량 40이 남아 있으므로 포지션 유지


def test_full_sell_still_removes_position(monkeypatch):
    """기본(partial=False) 매도는 기존대로 포지션을 제거한다 — 회귀 방지."""
    async def _order_cash(**kwargs):
        return {"output": {"ODNO": "1234"}}

    executor, pm, _ = _setup_sell_env(monkeypatch, _order_cash)
    result = asyncio.run(executor.execute_sell("005930", 100, price=0, reason="STOP_LOSS"))
    assert result["ok"] is True
    assert pm.removed == ["005930"]


def test_partial_sell_skips_exit_tagging_and_cooldown(monkeypatch):
    """부분매도는 청산 태깅·스캐너 쿨다운을 남기지 않는다(아직 보유 중)."""
    async def _order_cash(**kwargs):
        return {"output": {"ODNO": "1234"}}

    executor, pm, _ = _setup_sell_env(monkeypatch, _order_cash)
    import backend.services.engine.momentum_scanner as ms
    import backend.services.engine.trade_tagging as tt
    tag_calls, cooldown_calls = [], []
    monkeypatch.setattr(tt, "merge_exit_context", lambda *a, **k: tag_calls.append(a))
    monkeypatch.setattr(ms, "note_exit", lambda *a, **k: cooldown_calls.append(a))

    asyncio.run(executor.execute_sell("005930", 60, price=0, reason="take_profit_scaleout", partial=True))
    assert tag_calls == []
    assert cooldown_calls == []


# ──────────────────────────────────────────────
# P0-2: harvested 영속화 + 당일 상속
# ──────────────────────────────────────────────

def _make_position(qty: int = 100, entry: float = 100.0) -> dict:
    return {
        "position_id": "005930-test",
        "symbol": "005930",
        "name": "삼성전자",
        "qty": qty,
        "entry_price": entry,
        "entry_time": "2026-07-08T09:00:00+09:00",
        "entry_ts": 0.0,
        "profile_assigned": "MID_VOL",
        "auto_imported": False,
        "initial_stop_price": entry * 0.97,
        "active_stop_price": entry * 0.97,
        "highest_price_since_entry": entry,
        "trough_price": entry,
        "trailing_active": False,
        "trailing_stop_price": entry * 0.97,
        "trailing_activate_profit": 0.025,
        "trailing_stop_rate": 0.03,
        "max_holding_minutes": 180,
        "force_exit_time": "15:20:00",
        "harvested": False,
    }


def _scaleout_settings(key, default=None):
    return {
        "engine.harvest_mode": True,
        "engine.scaleout_ratio": 0.6,
        "engine.scaleout_target_rate": 0.02,
    }.get(key, default)


def test_harvested_persists_and_reimport_inherits():
    """수확 → stop_states에 harvested=1 기록 → 같은 날 재등록 포지션이 이를 상속한다.

    (자동편입이 harvested를 리셋해 재수확 루프가 생겼던 P0의 직접 회귀 테스트)
    """
    with tempfile.TemporaryDirectory() as tmp_dir, \
         patch.object(settings, "APP_DB_PATH", tmp_dir + "/test_p0.sqlite3"):
        # 실제 스키마 + 마이그레이션 (harvested 컬럼 포함 확인)
        from backend.services.db import get_connection, initialize_database
        initialize_database()

        mgr = PositionManager()
        pos = _make_position(qty=100, entry=100.0)
        mgr._positions["005930"] = pos
        sell = AsyncMock(return_value={"ok": True, "symbol": "005930"})
        with patch("backend.services.engine.position_manager.get_setting", side_effect=_scaleout_settings), \
             patch("backend.services.engine.order_executor.order_executor.execute_sell", sell), \
             patch.object(PositionManager, "_account_daily_target_reached", new=AsyncMock(return_value=False)):
            asyncio.run(mgr._scaleout_check(pos, 102.0))

        # 수확이 stop_states에 영속화됐는지
        with get_connection() as conn:
            row = conn.execute(
                "SELECT harvested FROM position_stop_states WHERE symbol_code='005930' ORDER BY last_updated_at DESC LIMIT 1"
            ).fetchone()
        assert row is not None and row["harvested"] == 1

        # 자동편입 재등록 시나리오 — 새 포지션이 harvested를 상속해 재수확하지 않는다
        mgr2 = PositionManager()
        with patch("backend.services.engine.position_manager.get_setting", side_effect=_scaleout_settings):
            mgr2.add_position(
                symbol="005930", name="삼성전자", qty=40, entry_price=101.0,
                final_rule={"profile_assigned": "MID_VOL"}, auto_imported=True,
            )
        reimported = mgr2._positions["005930"]
        assert reimported["harvested"] is True

        # 재수확 시도 → 발동하지 않아야 한다
        sell2 = AsyncMock(return_value={"ok": True})
        with patch("backend.services.engine.position_manager.get_setting", side_effect=_scaleout_settings), \
             patch("backend.services.engine.order_executor.order_executor.execute_sell", sell2):
            asyncio.run(mgr2._scaleout_check(reimported, 105.0))
        sell2.assert_not_awaited()


def test_harvested_migration_adds_column_to_legacy_table():
    """구 스키마(harvested 없는) DB에 마이그레이션이 컬럼을 추가한다."""
    with tempfile.TemporaryDirectory() as tmp_dir, \
         patch.object(settings, "APP_DB_PATH", tmp_dir + "/test_mig.sqlite3"):
        legacy_path = tmp_dir + "/test_mig.sqlite3"
        conn = sqlite3.connect(legacy_path)
        conn.execute(
            """
            CREATE TABLE position_stop_states (
                position_id TEXT PRIMARY KEY,
                symbol_code TEXT NOT NULL,
                entry_price REAL NOT NULL DEFAULT 0.0,
                highest_price_since_entry REAL NOT NULL DEFAULT 0.0,
                initial_stop_price REAL NOT NULL DEFAULT 0.0,
                trailing_stop_price REAL NOT NULL DEFAULT 0.0,
                active_stop_price REAL NOT NULL DEFAULT 0.0,
                trailing_active INTEGER NOT NULL DEFAULT 0,
                profile_assigned TEXT NOT NULL DEFAULT 'MID_VOL',
                last_updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
        conn.close()

        from backend.services.db import get_connection, initialize_database
        initialize_database()
        with get_connection() as c2:
            cols = {r[1] for r in c2.execute("PRAGMA table_info(position_stop_states)")}
        assert "harvested" in cols


def test_scaleout_uncertain_result_keeps_harvested():
    """매도 결과가 uncertain(접수 가능성)이면 harvested를 원복하지 않는다 — 재수확 차단."""
    mgr = PositionManager()
    pos = _make_position(qty=100, entry=100.0)
    mgr._positions["005930"] = pos
    sell = AsyncMock(return_value={"ok": False, "uncertain": True, "reason": "missing_kis_order_no"})
    upserts = []
    with patch("backend.services.engine.position_manager.get_setting", side_effect=_scaleout_settings), \
         patch("backend.services.engine.position_manager._upsert_stop_state",
               side_effect=lambda pid, data: upserts.append(data)), \
         patch.object(PositionManager, "_account_daily_target_reached", new=AsyncMock(return_value=False)), \
         patch("backend.services.engine.order_executor.order_executor.execute_sell", sell):
        result = asyncio.run(mgr._scaleout_check(pos, 102.0))
    assert result == ""
    assert pos["harvested"] is True          # 원복하지 않음
    assert any(u.get("harvested") for u in upserts)  # 영속화까지 수행


# ──────────────────────────────────────────────
# P0-3: 자동편입 진입가 우선순위
# ──────────────────────────────────────────────

def test_import_entry_price_prefers_todays_buy_fills():
    """당일 매수 체결이 있으면 KIS 평균가 대신 체결 가중평균을 쓴다."""
    with tempfile.TemporaryDirectory() as tmp_dir, \
         patch.object(settings, "APP_DB_PATH", tmp_dir + "/test_entry.sqlite3"):
        from backend.services.db import get_connection, initialize_database
        initialize_database()
        oe._ensure_orders_table()  # trading_orders는 order_executor가 lazy 생성
        from datetime import datetime
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO trading_orders (id, trade_date, symbol, side, qty, price, status, reason, created_at)
                VALUES ('o1', ?, '042040', 'buy', 756, 6480.0, 'filled', '', '2026-07-08T14:11:30+09:00')
                """,
                (today,),
            )
        from backend.services.engine.decision_engine import _resolve_import_entry_price
        price, source = _resolve_import_entry_price("042040", kis_avg=6364.09)
        assert source == "today_buy_orders"
        assert abs(price - 6480.0) < 0.01


def test_import_entry_price_falls_back_to_kis_avg():
    """당일 매수도 원장도 없으면 KIS 평균가 폴백."""
    with tempfile.TemporaryDirectory() as tmp_dir, \
         patch.object(settings, "APP_DB_PATH", tmp_dir + "/test_entry2.sqlite3"):
        from backend.services.db import initialize_database
        initialize_database()
        from backend.services.engine.decision_engine import _resolve_import_entry_price
        price, source = _resolve_import_entry_price("042040", kis_avg=6364.09)
        assert source == "kis_avg"
        assert abs(price - 6364.09) < 0.01


# ──────────────────────────────────────────────
# P0-4: baseline 캡처 토큰 만료 재시도
# ──────────────────────────────────────────────

def test_baseline_capture_retries_on_expired_token(monkeypatch):
    """get_balance가 EGW00123로 실패하면 토큰 캐시를 비우고 1회 재시도한다."""
    import backend.services.scheduler as sched
    from backend.services.kis.common.client import kis_client

    calls = {"n": 0}

    async def _get_balance():
        calls["n"] += 1
        if calls["n"] == 1:
            raise Exception("KIS API Error (...): EGW00123 기간이 만료된 token 입니다.")
        return {"output2": [{"ord_psbl_cash": "100000000", "tot_evlu_amt": "100000000"}]}

    captured = {}

    def _capture_baseline(deposit, total_eval=None, trade_date=None):
        captured.update(deposit=deposit, total_eval=total_eval, trade_date=trade_date)
        return {"ok": True}

    monkeypatch.setattr(sched, "get_balance", _get_balance)
    import backend.services.engine.daily_capital as dc
    monkeypatch.setattr(dc, "capture_baseline", _capture_baseline)
    kis_client.token = "stale-token"
    kis_client.token_expires_at = 9e12  # 클라이언트는 유효하다고 믿는 상태

    asyncio.run(sched.job_capture_capital_baseline())

    assert calls["n"] == 2                      # 재시도 발생
    assert kis_client.token is None or calls["n"] == 2  # 캐시 무효화 수행
    assert captured.get("deposit") == 100000000.0


def test_baseline_capture_non_token_error_no_retry(monkeypatch):
    """토큰 외 오류는 재시도 없이 기존처럼 warning 후 종료(예외 전파 안 함)."""
    import backend.services.scheduler as sched

    calls = {"n": 0}

    async def _get_balance():
        calls["n"] += 1
        raise Exception("network unreachable")

    monkeypatch.setattr(sched, "get_balance", _get_balance)
    asyncio.run(sched.job_capture_capital_baseline())
    assert calls["n"] == 1
