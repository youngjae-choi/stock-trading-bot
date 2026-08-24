"""정합성 감시봇(Sanity Watchdog) — R1~R6 체크별 정상/이상 판정.

PM이 눈으로 잡던 "이거 이상해"를 규칙화한 6종. 운영 단계 점검(_chk_s2 등)과 달리
"시스템의 믿음 vs 실제 현실"이 어긋난 순간을 잡는다. LLM·자동수정 없음 — Alert만.

운영 DB 미접촉: settings.APP_DB_PATH를 임시 파일로 monkeypatch. 시각 의존 체크(R1 age,
R3 staleness)는 ow._now_kst를 고정한다.
"""

import datetime as dt

import backend.services.engine.ops_watchdog as ow
from backend.config import settings
from backend.services import db as db_mod

_TD = "2026-08-24"  # 월요일 = 거래일
_NOW = dt.datetime(2026, 8, 24, 11, 30, tzinfo=ow.KST)


def _iso_db(tmp_path, monkeypatch, full=False):
    p = tmp_path / "sanity_watch.sqlite3"
    monkeypatch.setattr(settings, "APP_DB_PATH", str(p))
    if full:
        db_mod.initialize_database()


def _ddl(conn):
    """정합성 체크가 조회하는 테이블을 최소 컬럼으로 생성."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS regime_set_applications(
            id INTEGER PRIMARY KEY, trade_date TEXT, applied_at TEXT, set_id TEXT, regime_label TEXT,
            kospi_change_pct REAL, trigger TEXT, current_flag INTEGER, created_at TEXT);
        CREATE TABLE IF NOT EXISTS market_snapshots(
            id INTEGER PRIMARY KEY, symbol TEXT, change_rate REAL, captured_at TEXT);
        CREATE TABLE IF NOT EXISTS trading_orders(
            id INTEGER PRIMARY KEY, trade_date TEXT, side TEXT, status TEXT, reason TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS trading_signals(
            id INTEGER PRIMARY KEY, trade_date TEXT, signal_type TEXT);
        CREATE TABLE IF NOT EXISTS universe_filter_results(
            id INTEGER PRIMARY KEY, trade_date TEXT, filtered_count INTEGER, created_at TEXT);
        CREATE TABLE IF NOT EXISTS daily_holdings_snapshot(
            id INTEGER PRIMARY KEY, trade_date TEXT, symbol TEXT, norm_symbol TEXT, qty INTEGER);
        CREATE TABLE IF NOT EXISTS position_cost_basis(
            id INTEGER PRIMARY KEY, trade_date TEXT, symbol TEXT, norm_symbol TEXT, qty INTEGER);
        """
    )
    conn.commit()


def _apply_regime(conn, label, kospi, *, applied_at, trigger="intraday"):
    conn.execute(
        "INSERT INTO regime_set_applications(trade_date, applied_at, set_id, regime_label, kospi_change_pct,"
        " trigger, current_flag, created_at) VALUES(?,?,?,?,?,?,1,?)",
        (_TD, applied_at, "SET-TEST", label, kospi, trigger, applied_at),
    )
    conn.commit()


def _kospi_snap(conn, change, captured_at):
    conn.execute(
        "INSERT INTO market_snapshots(symbol, change_rate, captured_at) VALUES('KOSPI',?,?)",
        (change, captured_at),
    )
    conn.commit()


# ─────────────────── R1 레짐↔현실 괴리 ───────────────────

def test_r1_bullish_regime_in_crash_alerts(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    monkeypatch.setattr(ow, "_now_kst", lambda: _NOW)
    with db_mod.get_connection() as conn:
        _ddl(conn)
        # 시스템=risk_on(상승판단), 30분 전 적용, 그런데 코스피 -3% 폭락
        _apply_regime(conn, "risk_on", 0.5, applied_at="2026-08-24T11:00:00+09:00")
        _kospi_snap(conn, -3.0, "2026-08-24T11:29:00+09:00")
        res = ow._chk_regime_reality(conn, _TD)
        assert res is not None and "괴리" in res[0]


def test_r1_neutral_regime_in_crash_alerts(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    monkeypatch.setattr(ow, "_now_kst", lambda: _NOW)
    with db_mod.get_connection() as conn:
        _ddl(conn)
        _apply_regime(conn, "neutral", -0.2, applied_at="2026-08-24T11:00:00+09:00")
        _kospi_snap(conn, -2.5, "2026-08-24T11:29:00+09:00")
        assert ow._chk_regime_reality(conn, _TD) is not None


def test_r1_risk_off_in_crash_is_normal(tmp_path, monkeypatch):
    """오늘 실제 상태 — risk_off는 하락장에 올바른 방어. 오탐 없어야 함."""
    _iso_db(tmp_path, monkeypatch)
    monkeypatch.setattr(ow, "_now_kst", lambda: _NOW)
    with db_mod.get_connection() as conn:
        _ddl(conn)
        _apply_regime(conn, "risk_off", -2.43, applied_at="2026-08-24T11:00:00+09:00")
        _kospi_snap(conn, -3.16, "2026-08-24T11:29:00+09:00")
        assert ow._chk_regime_reality(conn, _TD) is None


def test_r1_defensive_in_rally_alerts(tmp_path, monkeypatch):
    """방어중인데 시장 급반등 — 기회상실 반대 괴리도 잡는다."""
    _iso_db(tmp_path, monkeypatch)
    monkeypatch.setattr(ow, "_now_kst", lambda: _NOW)
    with db_mod.get_connection() as conn:
        _ddl(conn)
        _apply_regime(conn, "risk_off", 0.1, applied_at="2026-08-24T11:00:00+09:00")
        _kospi_snap(conn, 2.8, "2026-08-24T11:29:00+09:00")
        assert ow._chk_regime_reality(conn, _TD) is not None


def test_r1_fresh_transition_suppressed(tmp_path, monkeypatch):
    """방금(5분 전) 적용된 레짐은 지속조건 미충족 → 오탐 억제."""
    _iso_db(tmp_path, monkeypatch)
    monkeypatch.setattr(ow, "_now_kst", lambda: _NOW)
    with db_mod.get_connection() as conn:
        _ddl(conn)
        _apply_regime(conn, "risk_on", 0.5, applied_at="2026-08-24T11:25:00+09:00")  # 5분 전
        _kospi_snap(conn, -3.0, "2026-08-24T11:29:00+09:00")
        assert ow._chk_regime_reality(conn, _TD) is None


# ─────────────────── R2 주문 연속 실패 ───────────────────

def test_r2_all_buys_failed_alerts(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    with db_mod.get_connection() as conn:
        _ddl(conn)
        for _ in range(3):
            conn.execute(
                "INSERT INTO trading_orders(trade_date, side, status, reason, created_at) VALUES(?,?,?,?,?)",
                (_TD, "buy", "failed", "40910000 모의투자 계좌가 아닙니다", "2026-08-24T09:10"),
            )
        conn.commit()
        res = ow._chk_order_reject_streak(conn, _TD)
        assert res is not None and "40910000" in res[1]


def test_r2_some_success_is_normal(tmp_path, monkeypatch):
    """오늘 실제 — failed 1·filled 7 → 계좌 살아있음, 오탐 없어야 함."""
    _iso_db(tmp_path, monkeypatch)
    with db_mod.get_connection() as conn:
        _ddl(conn)
        conn.execute("INSERT INTO trading_orders(trade_date, side, status) VALUES(?,?,?)", (_TD, "buy", "failed"))
        for _ in range(7):
            conn.execute("INSERT INTO trading_orders(trade_date, side, status) VALUES(?,?,?)", (_TD, "buy", "filled"))
        conn.commit()
        assert ow._chk_order_reject_streak(conn, _TD) is None


def test_r2_below_threshold_is_normal(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    with db_mod.get_connection() as conn:
        _ddl(conn)
        for _ in range(2):  # 임계 3 미만
            conn.execute("INSERT INTO trading_orders(trade_date, side, status) VALUES(?,?,?)", (_TD, "buy", "failed"))
        conn.commit()
        assert ow._chk_order_reject_streak(conn, _TD) is None


# ─────────────────── R3 시세 정체(staleness) ───────────────────

def test_r3_stale_kospi_alerts(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    monkeypatch.setattr(ow, "_now_kst", lambda: _NOW)
    with db_mod.get_connection() as conn:
        _ddl(conn)
        _kospi_snap(conn, -1.0, "2026-08-24T11:00:00+09:00")  # 30분 전 = 임계 10분 초과
        res = ow._chk_market_data_stale(conn, _TD)
        assert res is not None and "정체" in res[0]


def test_r3_fresh_kospi_is_normal(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    monkeypatch.setattr(ow, "_now_kst", lambda: _NOW)
    with db_mod.get_connection() as conn:
        _ddl(conn)
        _kospi_snap(conn, -1.0, "2026-08-24T11:28:00+09:00")  # 2분 전
        assert ow._chk_market_data_stale(conn, _TD) is None


def test_r3_no_kospi_alerts(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    monkeypatch.setattr(ow, "_now_kst", lambda: _NOW)
    with db_mod.get_connection() as conn:
        _ddl(conn)
        res = ow._chk_market_data_stale(conn, _TD)
        assert res is not None  # 장중 코스피 시세 자체가 없음


# ─────────────────── R4 진입 마비 ───────────────────

def test_r4_candidates_no_signals_alerts(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    monkeypatch.setattr(ow, "_entry_suspended", lambda td: False)
    with db_mod.get_connection() as conn:
        _ddl(conn)
        conn.execute(
            "INSERT INTO universe_filter_results(trade_date, filtered_count, created_at) VALUES(?,?,?)",
            (_TD, 12, "2026-08-24T09:05"),
        )
        conn.commit()
        res = ow._chk_entry_paralysis(conn, _TD)
        assert res is not None and "마비" in res[0]


def test_r4_signals_present_is_normal(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    monkeypatch.setattr(ow, "_entry_suspended", lambda td: False)
    with db_mod.get_connection() as conn:
        _ddl(conn)
        conn.execute(
            "INSERT INTO universe_filter_results(trade_date, filtered_count, created_at) VALUES(?,?,?)",
            (_TD, 12, "2026-08-24T09:05"),
        )
        conn.execute("INSERT INTO trading_signals(trade_date, signal_type) VALUES(?,?)", (_TD, "BUY"))
        conn.commit()
        assert ow._chk_entry_paralysis(conn, _TD) is None


def test_r4_no_candidates_is_normal(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    monkeypatch.setattr(ow, "_entry_suspended", lambda td: False)
    with db_mod.get_connection() as conn:
        _ddl(conn)  # 후보 없음
        assert ow._chk_entry_paralysis(conn, _TD) is None


def test_r4_suspended_is_normal(tmp_path, monkeypatch):
    """하락전환 래치 등 의도된 진입중단이면 마비 아님."""
    _iso_db(tmp_path, monkeypatch)
    monkeypatch.setattr(ow, "_entry_suspended", lambda td: True)
    with db_mod.get_connection() as conn:
        _ddl(conn)
        conn.execute(
            "INSERT INTO universe_filter_results(trade_date, filtered_count, created_at) VALUES(?,?,?)",
            (_TD, 12, "2026-08-24T09:05"),
        )
        conn.commit()
        assert ow._chk_entry_paralysis(conn, _TD) is None


# ─────────────────── R5 포지션↔설정 모순 ───────────────────

def test_r5_overexposure_alerts(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    monkeypatch.setattr(ow, "_active_max_positions", lambda td: 3)
    with db_mod.get_connection() as conn:
        _ddl(conn)
        for i in range(4):  # 4종목 보유 > max 3
            conn.execute(
                "INSERT INTO daily_holdings_snapshot(trade_date, symbol, norm_symbol, qty) VALUES(?,?,?,?)",
                (_TD, f"00593{i}", f"00593{i}", 10),
            )
        conn.commit()
        res = ow._chk_position_conflict(conn, _TD)
        assert res is not None and "초과" in res[0]


def test_r5_within_limit_is_normal(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    monkeypatch.setattr(ow, "_active_max_positions", lambda td: 3)
    with db_mod.get_connection() as conn:
        _ddl(conn)
        for i in range(2):
            conn.execute(
                "INSERT INTO daily_holdings_snapshot(trade_date, symbol, norm_symbol, qty) VALUES(?,?,?,?)",
                (_TD, f"00593{i}", f"00593{i}", 10),
            )
        conn.commit()
        assert ow._chk_position_conflict(conn, _TD) is None


# ─────────────────── R6 DB↔KIS 수량 드리프트 ───────────────────

def test_r6_phantom_holding_alerts(tmp_path, monkeypatch):
    """DB 원장 10주인데 KIS 실보유 5주 → 유령 5주."""
    _iso_db(tmp_path, monkeypatch)
    with db_mod.get_connection() as conn:
        _ddl(conn)
        conn.execute(
            "INSERT INTO position_cost_basis(trade_date, symbol, norm_symbol, qty) VALUES(?,?,?,?)",
            (_TD, "005930", "005930", 10),
        )
        conn.execute(
            "INSERT INTO daily_holdings_snapshot(trade_date, symbol, norm_symbol, qty) VALUES(?,?,?,?)",
            (_TD, "005930", "005930", 5),
        )
        conn.commit()
        res = ow._chk_qty_drift(conn, _TD)
        assert res is not None and "유령" in res[0]


def test_r6_matching_qty_is_normal(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    with db_mod.get_connection() as conn:
        _ddl(conn)
        conn.execute(
            "INSERT INTO position_cost_basis(trade_date, symbol, norm_symbol, qty) VALUES(?,?,?,?)",
            (_TD, "005930", "005930", 5),
        )
        conn.execute(
            "INSERT INTO daily_holdings_snapshot(trade_date, symbol, norm_symbol, qty) VALUES(?,?,?,?)",
            (_TD, "005930", "005930", 5),
        )
        conn.commit()
        assert ow._chk_qty_drift(conn, _TD) is None


def test_r6_kis_more_than_db_is_normal(tmp_path, monkeypatch):
    """KIS>DB(외부매수·미반영)는 유령매도 아님 → R6 발동 안 함."""
    _iso_db(tmp_path, monkeypatch)
    with db_mod.get_connection() as conn:
        _ddl(conn)
        conn.execute(
            "INSERT INTO position_cost_basis(trade_date, symbol, norm_symbol, qty) VALUES(?,?,?,?)",
            (_TD, "005930", "005930", 5),
        )
        conn.execute(
            "INSERT INTO daily_holdings_snapshot(trade_date, symbol, norm_symbol, qty) VALUES(?,?,?,?)",
            (_TD, "005930", "005930", 10),
        )
        conn.commit()
        assert ow._chk_qty_drift(conn, _TD) is None


# ─────────────────── 킬스위치 ───────────────────

def test_kill_switch_disables_rule(tmp_path, monkeypatch):
    """watchdog.regime_reality_enabled=False면 R1 비활성 (설정 킬스위치)."""
    _iso_db(tmp_path, monkeypatch)
    monkeypatch.setattr(ow, "_now_kst", lambda: _NOW)
    # 킬스위치 키만 False, 나머지 키는 기본값 반환 → R1이 조기 return None 이어야 함
    monkeypatch.setattr(
        ow, "get_setting",
        lambda k, d=None: False if k == "watchdog.regime_reality_enabled" else d,
    )
    with db_mod.get_connection() as conn:
        _ddl(conn)
        _apply_regime(conn, "risk_on", 0.5, applied_at="2026-08-24T11:00:00+09:00")
        _kospi_snap(conn, -3.0, "2026-08-24T11:29:00+09:00")
        assert ow._chk_regime_reality(conn, _TD) is None
