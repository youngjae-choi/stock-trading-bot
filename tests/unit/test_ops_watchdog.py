"""운영 감시봇(Ops Watchdog) — 체크별 정상/이상 판정 + 거래일 가드 + 시각 게이팅 + 중복 억제.

운영 DB 미접촉: settings.APP_DB_PATH를 임시 파일로 monkeypatch.
LLM·코드 자동수정 없음 — 이상은 system_alerts(Alert Center)에 기록만.
"""

import datetime as dt

import backend.services.engine.ops_watchdog as ow
from backend.config import settings
from backend.services import db as db_mod

# 거래일/비거래일 고정 시각 (2026-06-08 월요일=거래일, 2026-06-07 일요일=비거래일)
_MON_0930 = dt.datetime(2026, 6, 8, 9, 30, tzinfo=ow.KST)
_MON_0800 = dt.datetime(2026, 6, 8, 8, 0, tzinfo=ow.KST)
_MON_0935 = dt.datetime(2026, 6, 8, 9, 35, tzinfo=ow.KST)
_SUN_0930 = dt.datetime(2026, 6, 7, 9, 30, tzinfo=ow.KST)
_TD = "2026-06-08"


def _iso_db(tmp_path, monkeypatch, full=False):
    """full=False: 빈 DB(체크 함수 단위 테스트용, 최소 테이블만 _ddl로 생성).
    full=True: initialize_database로 system_alerts 등 실제 스키마 생성(run 통합 테스트용)."""
    p = tmp_path / "ops_watch.sqlite3"
    monkeypatch.setattr(settings, "APP_DB_PATH", str(p))
    if full:
        db_mod.initialize_database()


def _ddl(conn):
    """체크가 조회하는 출력 테이블을 최소 컬럼으로 생성(스키마 드리프트 무관)."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS market_tone_results(id INTEGER PRIMARY KEY, trade_date TEXT);
        CREATE TABLE IF NOT EXISTS daily_trading_plans(id INTEGER PRIMARY KEY, trade_date TEXT, status TEXT);
        CREATE TABLE IF NOT EXISTS universe_filter_results(id INTEGER PRIMARY KEY, trade_date TEXT, filtered_count INTEGER, created_at TEXT);
        CREATE TABLE IF NOT EXISTS hybrid_screening_results(id INTEGER PRIMARY KEY, trade_date TEXT, output_count INTEGER, overall_confidence REAL, created_at TEXT);
        CREATE TABLE IF NOT EXISTS daily_capital_baseline(id INTEGER PRIMARY KEY, trade_date TEXT);
        CREATE TABLE IF NOT EXISTS trading_signals(id INTEGER PRIMARY KEY, trade_date TEXT, signal_type TEXT);
        CREATE TABLE IF NOT EXISTS trading_orders(id INTEGER PRIMARY KEY, trade_date TEXT, side TEXT, status TEXT);
        CREATE TABLE IF NOT EXISTS order_preflight_checks(id INTEGER PRIMARY KEY, symbol TEXT, block_reasons TEXT, result TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS daily_review_reports(id INTEGER PRIMARY KEY, trade_date TEXT);
        CREATE TABLE IF NOT EXISTS pipeline_run_audit(id INTEGER PRIMARY KEY, trade_date TEXT, step TEXT, status TEXT, message TEXT, started_at TEXT);
        """
    )
    conn.commit()


# ─────────────────────── 개별 체크 ───────────────────────

def test_chk_s2_premarket(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    with db_mod.get_connection() as conn:
        _ddl(conn)
        assert ow._chk_s2_premarket(conn, _TD) is not None  # 없으면 이상
        conn.execute("INSERT INTO market_tone_results(trade_date) VALUES(?)", (_TD,))
        conn.commit()
        assert ow._chk_s2_premarket(conn, _TD) is None  # 있으면 정상


def test_chk_s2_premarket_adds_audit_message(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    with db_mod.get_connection() as conn:
        _ddl(conn)
        conn.execute(
            "INSERT INTO pipeline_run_audit(trade_date, step, status, message, started_at)"
            " VALUES(?,?,?,?,?)",
            (_TD, "S2", "failed", "KIS 시장지수 조회 timeout", "2026-06-08T08:30:01"),
        )
        conn.commit()
        res = ow._chk_s2_premarket(conn, _TD)
        assert res is not None and "timeout" in res[1]


def test_chk_trade_prep(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    with db_mod.get_connection() as conn:
        _ddl(conn)
        assert ow._chk_trade_prep(conn, _TD) is not None
        conn.execute("INSERT INTO daily_trading_plans(trade_date, status) VALUES(?,?)", (_TD, "draft"))
        conn.commit()
        assert ow._chk_trade_prep(conn, _TD) is not None  # active 아니면 여전히 이상
        conn.execute("INSERT INTO daily_trading_plans(trade_date, status) VALUES(?,?)", (_TD, "active"))
        conn.commit()
        assert ow._chk_trade_prep(conn, _TD) is None


def test_chk_quality_universe(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    with db_mod.get_connection() as conn:
        _ddl(conn)
        assert ow._chk_quality_universe(conn, _TD)[0] == "S3 유니버스 결과 없음"
        conn.execute(
            "INSERT INTO universe_filter_results(trade_date, filtered_count, created_at) VALUES(?,?,?)",
            (_TD, 0, "2026-06-08T09:01"),
        )
        conn.commit()
        assert ow._chk_quality_universe(conn, _TD)[0] == "S3 유니버스 0건"
        conn.execute(
            "INSERT INTO universe_filter_results(trade_date, filtered_count, created_at) VALUES(?,?,?)",
            (_TD, 42, "2026-06-08T09:02"),
        )
        conn.commit()
        assert ow._chk_quality_universe(conn, _TD) is None  # 최신행 42건 → 정상


def test_chk_quality_screening(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    with db_mod.get_connection() as conn:
        _ddl(conn)
        assert ow._chk_quality_screening(conn, _TD) is not None  # 없음
        conn.execute(
            "INSERT INTO hybrid_screening_results(trade_date, output_count, overall_confidence, created_at)"
            " VALUES(?,?,?,?)",
            (_TD, 0, 0.0, "2026-06-08T09:03"),
        )
        conn.commit()
        assert ow._chk_quality_screening(conn, _TD) is not None  # 0건 → 부실
        conn.execute(
            "INSERT INTO hybrid_screening_results(trade_date, output_count, overall_confidence, created_at)"
            " VALUES(?,?,?,?)",
            (_TD, 5, 0.62, "2026-06-08T09:04"),
        )
        conn.commit()
        assert ow._chk_quality_screening(conn, _TD) is None


def test_chk_baseline(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    with db_mod.get_connection() as conn:
        _ddl(conn)
        assert ow._chk_baseline(conn, _TD) is not None
        conn.execute("INSERT INTO daily_capital_baseline(trade_date) VALUES(?)", (_TD,))
        conn.commit()
        assert ow._chk_baseline(conn, _TD) is None


def test_chk_buy_not_executed(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    with db_mod.get_connection() as conn:
        _ddl(conn)
        # 신호 없음 → 정상(매수 안 나간 게 정상)
        assert ow._chk_buy_not_executed(conn, _TD) is None
        # 매수신호 2건, 주문 0건 → 이상 + preflight 사유 동봉
        conn.execute("INSERT INTO trading_signals(trade_date, signal_type) VALUES(?,?)", (_TD, "BUY"))
        conn.execute("INSERT INTO trading_signals(trade_date, signal_type) VALUES(?,?)", (_TD, "BUY"))
        conn.execute(
            "INSERT INTO order_preflight_checks(symbol, block_reasons, result, created_at) VALUES(?,?,?,?)",
            ("005930", '["신규매수금지시간"]', "blocked", "2026-06-08T09:20"),
        )
        conn.commit()
        res = ow._chk_buy_not_executed(conn, _TD)
        assert res is not None and "신규매수금지시간" in res[1] and "2건" in res[1]
        # 체결주문 발생 → 정상
        conn.execute("INSERT INTO trading_orders(trade_date, side, status) VALUES(?,?,?)", (_TD, "buy", "filled"))
        conn.commit()
        assert ow._chk_buy_not_executed(conn, _TD) is None


def test_chk_postprocess(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    with db_mod.get_connection() as conn:
        _ddl(conn)
        assert ow._chk_postprocess(conn, _TD) is not None
        conn.execute("INSERT INTO daily_review_reports(trade_date) VALUES(?)", (_TD,))
        conn.commit()
        assert ow._chk_postprocess(conn, _TD) is None


# ─────────────────────── run_ops_watchdog 통합 ───────────────────────

def test_run_skips_non_trading_day(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch, full=True)
    with db_mod.get_connection() as conn:
        _ddl(conn)
    out = ow.run_ops_watchdog(now=_SUN_0930)  # 일요일
    assert out.get("skipped") == "non_trading_day"
    assert out["created"] == 0


def test_run_time_gating_before_open(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch, full=True)
    with db_mod.get_connection() as conn:
        _ddl(conn)
    out = ow.run_ops_watchdog(now=_MON_0800)  # 08:00 — 어떤 체크도 적용 시각 전
    assert out["checks"] == 0
    assert out["created"] == 0


def test_run_detects_and_records(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch, full=True)
    with db_mod.get_connection() as conn:
        _ddl(conn)  # 전부 비어있음 → 여러 이상 발생
    out = ow.run_ops_watchdog(now=_MON_0930)
    assert out["created"] >= 1
    with db_mod.get_connection() as conn:
        rows = conn.execute(
            "SELECT title FROM system_alerts WHERE alert_type='ops_watch' AND trade_date=?", (_TD,)
        ).fetchall()
    titles = {r["title"] for r in rows}
    assert "거래준비(S1~S5-A) 미완료/미활성" in titles
    assert out["created"] == len(titles)


def test_run_dedups_same_anomaly(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch, full=True)
    with db_mod.get_connection() as conn:
        _ddl(conn)
    first = ow.run_ops_watchdog(now=_MON_0930)
    assert first["created"] >= 1
    second = ow.run_ops_watchdog(now=_MON_0935)  # 5분 뒤 동일 이상
    assert second["created"] == 0  # 미확인 알림 존재 → 중복 억제
    with db_mod.get_connection() as conn:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM system_alerts WHERE alert_type='ops_watch' AND trade_date=?", (_TD,)
        ).fetchone()[0]
    assert cnt == first["created"]  # 누적 없음
