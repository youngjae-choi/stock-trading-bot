"""A5: 포지션 MFE/MAE·보유시간 추적 → 청산 태그 outcome 기록 (2026-06-10).

배경: trade_entry_tags.outcome_json에 realized_pnl/exit_reason만 백필돼
"트레일링 3%가 맞나" 같은 매도 전략 검증이 불가능했다.
- PositionManager가 보유 중 peak/trough/entry_ts를 추적하고
  get_exit_context()로 mfe_pct/mae_pct/hold_sec를 노출한다.
- trade_tagging.merge_exit_context()가 기존 outcome 키를 보존한 채 ctx를 merge한다.
- backfill_outcomes_for_date()는 realized_pnl이 이미 있는 행만 건너뛰고,
  exit context가 먼저 기록된 행에는 pnl을 merge한다(덮어쓰기 금지).
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from unittest.mock import AsyncMock, patch

import backend.services.engine.trade_tagging as tt
from backend.services.engine.position_manager import PositionManager

_FIXED_NOW = datetime.fromisoformat("2026-06-10T10:00:00+09:00")


# ──────────────────────────────────────────────
# PositionManager — exit context (MFE/MAE/hold)
# ──────────────────────────────────────────────

def _make_manager_with_position() -> PositionManager:
    manager = PositionManager()
    with patch("backend.services.engine.position_manager._upsert_stop_state"), \
         patch("backend.services.engine.position_manager._now_kst", return_value=_FIXED_NOW):
        manager.add_position(
            symbol="005930",
            name="삼성전자",
            qty=10,
            entry_price=100.0,
            final_rule={
                "initial_stop_loss": -0.03,
                "trailing_activate_profit": 0.025,
                "trailing_stop_rate": 0.03,
                "force_exit_time": "15:20:00",
            },
        )
    manager._get_today_tone = lambda: "fallback"
    return manager


def test_exit_context_after_tick_flow_mfe_mae_hold():
    """진입 100 → 110(고점) → 95(트레일링 이탈 exit) 흐름 후 MFE +10% / MAE -5% / hold>0."""
    manager = _make_manager_with_position()
    # 보유시간 60초 시뮬레이션 (entry_ts를 60초 과거로)
    manager._positions["005930"]["entry_ts"] -= 60

    sell_mock = AsyncMock(return_value={})
    with patch("backend.services.engine.position_manager._upsert_stop_state"), \
         patch("backend.services.engine.position_manager._now_kst", return_value=_FIXED_NOW), \
         patch("backend.services.engine.order_executor.order_executor.execute_sell", sell_mock):
        asyncio.run(manager.on_tick({"symbol": "005930", "price": "100"}))
        asyncio.run(manager.on_tick({"symbol": "005930", "price": "110"}))
        asyncio.run(manager.on_tick({"symbol": "005930", "price": "95"}))

        # 110 >= 102.5 → 트레일링 활성, stop 106.7 → 95 tick에서 exit 주문 발생
        sell_mock.assert_awaited_once()

        ctx = manager.get_exit_context("005930")

    assert ctx is not None
    assert ctx["mfe_pct"] == 10.0
    assert ctx["mae_pct"] == -5.0
    assert ctx["hold_sec"] > 0
    assert ctx["peak_price"] == 110.0
    assert ctx["trough_price"] == 95.0


def test_exit_context_returns_none_without_position():
    """포지션이 없으면 None."""
    manager = PositionManager()
    assert manager.get_exit_context("999999") is None


def test_exit_context_returns_none_for_auto_imported():
    """auto_imported(진입가 KIS 평균가, 진입 맥락 불명) 포지션은 None."""
    manager = PositionManager()
    with patch("backend.services.engine.position_manager._upsert_stop_state"), \
         patch("backend.services.engine.position_manager._now_kst", return_value=_FIXED_NOW):
        manager.add_position(
            symbol="000660",
            name="SK하이닉스",
            qty=1,
            entry_price=120000.0,
            final_rule={},
            auto_imported=True,
        )
    assert manager.get_exit_context("000660") is None


# ──────────────────────────────────────────────
# trade_tagging — merge_exit_context / backfill merge
# ──────────────────────────────────────────────

def _setup_db(tmp_path, monkeypatch):
    db = tmp_path / "t.sqlite3"

    class _Conn:
        def __enter__(self):
            self._c = sqlite3.connect(db)
            self._c.row_factory = sqlite3.Row
            return self._c

        def __exit__(self, *a):
            self._c.commit()
            self._c.close()

    monkeypatch.setattr(tt, "get_connection", lambda: _Conn())
    return db


def _insert_tag(symbol, trade_date="2026-06-10", outcome="{}", tag_id=None):
    with tt.get_connection() as conn:
        conn.execute(
            """INSERT INTO trade_entry_tags
               (id, order_id, symbol, trade_date, selection_reason_json, fired_groups_json,
                condition_states_json, market_context_json, outcome_json, created_at)
               VALUES (?, '', ?, ?, '{}', '[]', '{}', '{}', ?, 't')""",
            (tag_id or f"tag-{symbol}-{trade_date}", symbol, trade_date, outcome),
        )


def _load_outcomes(symbol):
    with tt.get_connection() as conn:
        rows = conn.execute(
            "SELECT outcome_json FROM trade_entry_tags WHERE symbol = ?", (symbol,)
        ).fetchall()
    return [json.loads(r["outcome_json"]) for r in rows]


def test_merge_exit_context_preserves_existing_keys(tmp_path, monkeypatch):
    """merge_exit_context는 기존 outcome 키를 보존하면서 ctx 키를 추가한다."""
    _setup_db(tmp_path, monkeypatch)
    tt._ensure_table()
    _insert_tag("000430", outcome=json.dumps({"realized_pnl": 1500.0, "win": True}))

    updated = tt.merge_exit_context(
        "000430", "2026-06-10",
        {"mfe_pct": 4.2, "mae_pct": -1.1, "hold_sec": 1800, "peak_price": 1042.0, "trough_price": 989.0},
    )
    assert updated == 1

    outcome = _load_outcomes("000430")[0]
    assert outcome["realized_pnl"] == 1500.0  # 기존 키 보존
    assert outcome["win"] is True
    assert outcome["mfe_pct"] == 4.2          # ctx 키 추가
    assert outcome["mae_pct"] == -1.1
    assert outcome["hold_sec"] == 1800


def test_merge_exit_context_none_or_empty_returns_zero(tmp_path, monkeypatch):
    """ctx가 None/빈 dict면 0을 반환하고 아무것도 갱신하지 않는다."""
    _setup_db(tmp_path, monkeypatch)
    tt._ensure_table()
    _insert_tag("000430")

    assert tt.merge_exit_context("000430", "2026-06-10", None) == 0
    assert tt.merge_exit_context("000430", "2026-06-10", {}) == 0
    assert _load_outcomes("000430")[0] == {}


def test_backfill_merges_pnl_into_exit_context_rows(tmp_path, monkeypatch):
    """exit context가 먼저 기록된 행에도 EOD 백필이 realized_pnl을 merge한다(덮어쓰기 금지)."""
    _setup_db(tmp_path, monkeypatch)
    tt._ensure_table()
    _insert_tag("000430")
    tt.merge_exit_context("000430", "2026-06-10", {"mfe_pct": 10.0, "mae_pct": -5.0, "hold_sec": 60})

    pairs = [{"symbol": "000430", "trade_date": "2026-06-10", "status": "매도완료",
              "pnl_amount": -198510.0, "pnl_pct": -1.61}]
    updated = tt.backfill_outcomes_for_date(
        "2026-06-10", pairs=pairs, exit_map={"000430": "trailing_stop"}
    )
    assert updated == 1

    outcome = _load_outcomes("000430")[0]
    assert outcome["mfe_pct"] == 10.0          # 먼저 기록된 exit context 유지
    assert outcome["mae_pct"] == -5.0
    assert outcome["hold_sec"] == 60
    assert outcome["realized_pnl"] == -198510.0  # pnl merge 공존
    assert outcome["win"] is False
    assert outcome["exit_reason"] == "trailing_stop"


def test_backfill_still_skips_rows_with_realized_pnl(tmp_path, monkeypatch):
    """realized_pnl이 이미 있는 행은 백필이 건너뛴다 (기존 의미 유지)."""
    _setup_db(tmp_path, monkeypatch)
    tt._ensure_table()
    _insert_tag("084650", outcome=json.dumps({"realized_pnl": 1.0, "win": True, "mfe_pct": 2.0}))

    pairs = [{"symbol": "084650", "trade_date": "2026-06-10", "status": "매도완료",
              "pnl_amount": -5.0, "pnl_pct": -0.1}]
    updated = tt.backfill_outcomes_for_date("2026-06-10", pairs=pairs, exit_map={})
    assert updated == 0

    outcome = _load_outcomes("084650")[0]
    assert outcome["realized_pnl"] == 1.0
    assert outcome["mfe_pct"] == 2.0
