"""장중 재진입 churn 가드 — 오늘 N회 손절된 종목의 당일 재진입 차단.

8/13 참사: 손절당한 종목(126730)을 몇 분 내 재매수하는 루프가 10회 반복돼 -5.3M.
false_positive_cases(EOD 생성)·loss_streak(다음날)이 장중을 못 막던 공백을,
trading_orders 직접 집계(intraday_stoploss_count)로 메운다.
"""

from __future__ import annotations

import tempfile
import uuid

import pytest

import backend.services.engine.loss_streak_guard as lsg


@pytest.fixture()
def db(monkeypatch):
    from backend.config import settings as cfg
    from backend.services.db import initialize_database
    from backend.services.engine.order_executor import _ensure_orders_table

    tmp = tempfile.mktemp(suffix=".sqlite3")
    monkeypatch.setattr(cfg, "APP_DB_PATH", tmp)
    initialize_database()
    _ensure_orders_table()
    return tmp


def _sell(symbol, reason, trade_date="2026-08-13", status="filled"):
    from backend.services.db import get_connection

    with get_connection() as c:
        c.execute(
            "INSERT INTO trading_orders (id, trade_date, signal_id, symbol, name, side, order_type, qty, price, kis_order_no, status, reason, created_at) "
            "VALUES (?, ?, '', ?, ?, 'sell', 'market', 100, 1000, 'k1', ?, ?, ?)",
            (str(uuid.uuid4()), trade_date, symbol, symbol, status, reason, trade_date + "T10:00:00"),
        )


def test_counts_todays_initial_stop_loss(db):
    _sell("126730", "INITIAL_STOP_LOSS")
    _sell("126730", "INITIAL_STOP_LOSS")
    assert lsg.intraday_stoploss_count("126730", "2026-08-13") == 2


def test_excludes_non_stoploss_and_other_days(db):
    _sell("126730", "INITIAL_STOP_LOSS")
    _sell("126730", "TRAILING_STOP")        # 트레일링(승 가능) 제외
    _sell("126730", "eod")                  # EOD 청산 제외
    _sell("126730", "take_profit_scaleout")  # 익절 제외
    _sell("126730", "INITIAL_STOP_LOSS", trade_date="2026-08-12")  # 다른 날 제외
    assert lsg.intraday_stoploss_count("126730", "2026-08-13") == 1


def test_zero_when_none(db):
    assert lsg.intraday_stoploss_count("999999", "2026-08-13") == 0
    assert lsg.intraday_stoploss_count("", "2026-08-13") == 0


def test_gate_blocks_after_threshold(db, monkeypatch):
    """decision_engine 게이트: 오늘 2회 손절 종목 재진입 차단(기본 임계 2)."""
    import backend.services.engine.decision_engine as de
    import backend.services.settings_store as ss

    monkeypatch.setattr(de, "_today_kst", lambda: "2026-08-13")
    monkeypatch.setattr(
        ss, "get_setting",
        lambda key, default=None: {
            "engine.intraday_reentry_block_enabled": True,
            "engine.intraday_max_stoploss_per_symbol": 2,
            "engine.loss_streak_hard_block_enabled": False,
            "engine.entry_fail_cooldown_enabled": False,
        }.get(key, default),
    )
    # 손절 1회 → 통과
    _sell("126730", "INITIAL_STOP_LOSS")
    assert "intraday_reentry_block" not in de._entry_gate_block_reason("126730", 0.9)
    # 손절 2회 → 차단
    _sell("126730", "INITIAL_STOP_LOSS")
    assert "intraday_reentry_block" in de._entry_gate_block_reason("126730", 0.9)
