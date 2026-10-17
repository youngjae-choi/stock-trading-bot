"""매수 정지 섀도우 신호 DB 기록(shadow_entry_signals) — 종목-일 1행·첫 가격 보존·실패 무해 (2026-10-16)."""
import tempfile

import pytest


@pytest.fixture()
def tmp_db(monkeypatch):
    from backend.config import settings as cfg
    from backend.services.db import initialize_database

    monkeypatch.setattr(cfg, "APP_DB_PATH", tempfile.mktemp(suffix=".sqlite3"))
    initialize_database()


class _Bar:
    def get_vwap(self, symbol):
        return 10000.0


def _engine():
    from backend.services.engine.decision_engine import DecisionEngine

    e = DecisionEngine.__new__(DecisionEngine)
    e._bar_engine = _Bar()
    e._current_regime = lambda: "risk_off"
    return e


def test_first_price_kept_and_hits_counted(tmp_db, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import backend.services.engine.decision_engine as de

    monkeypatch.setattr(de, "_now_kst", lambda: datetime(2026, 10, 19, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")))
    from backend.services.db import get_connection

    e = _engine()
    e._record_shadow_signal("005930", 9900, False)
    e._record_shadow_signal("005930", 9800, False)
    with get_connection() as c:
        rows = c.execute("SELECT symbol, first_price, hits, regime, vwap_dist, momentum FROM shadow_entry_signals").fetchall()
    assert [tuple(r) for r in rows] == [("005930", 9900.0, 2, "risk_off", -1.0, 0)]


def test_failure_is_swallowed(monkeypatch):
    import backend.services.engine.decision_engine as de

    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(de, "get_connection", boom)
    _engine()._record_shadow_signal("005930", 9900, True)  # 예외 없이 끝나야 한다


def test_pre_execute_window_not_recorded(tmp_db, monkeypatch):
    """09:30 전 신호는 실매수 불가 — 첫 신호로 기록하면 재현이 왜곡된다."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import backend.services.engine.decision_engine as de
    from backend.services.db import get_connection

    monkeypatch.setattr(de, "_now_kst", lambda: datetime(2026, 10, 19, 9, 10, tzinfo=ZoneInfo("Asia/Seoul")))
    _engine()._record_shadow_signal("005930", 9900, False)
    with get_connection() as c:
        assert c.execute("SELECT COUNT(*) FROM shadow_entry_signals").fetchone()[0] == 0
