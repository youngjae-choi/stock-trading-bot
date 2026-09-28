"""VWAP 눌림목 게이트 폴백 — 실시간 VWAP 미가용 시 intraday_bars로 VWAP 복원.

재기동 시 bar_engine 메모리가 날아가 실시간 VWAP=None → 게이트 fail-open으로 추격 진입이
새던 문제(2026-08-29 백테스트: 추격 -0.7%). intraday_bars(장중 적재·재기동 유지)에서
Σ(close×vol)/Σ(vol)로 폴백 VWAP를 계산해 누수를 막는다.
"""

import backend.services.engine.decision_engine_utils as u
from backend.config import settings
from backend.services import db as db_mod


def _seed(conn, symbol, trade_date, bars):
    """bars = [(close, volume), ...] 를 intraday_bars에 시딩."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS intraday_bars(id INTEGER PRIMARY KEY, trade_date TEXT, "
        "symbol TEXT, bar_ts TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL, "
        "shnu_rate REAL, created_at TEXT)"
    )
    for i, (c, v) in enumerate(bars):
        conn.execute(
            "INSERT INTO intraday_bars(trade_date,symbol,bar_ts,close,volume) VALUES(?,?,?,?,?)",
            (trade_date, symbol, str(i), c, v),
        )
    conn.commit()


def _iso(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "APP_DB_PATH", str(tmp_path / "vwapfb.sqlite3"))


def test_fallback_vwap_today(tmp_path, monkeypatch):
    """오늘 봉으로 VWAP = Σ(close×vol)/Σ(vol) 계산."""
    _iso(tmp_path, monkeypatch)
    with db_mod.get_connection() as conn:
        _seed(conn, "005930", "2026-08-28", [(100, 10), (110, 10)])  # (100*10+110*10)/20 = 105
    assert u._fallback_vwap_from_bars("005930", today="2026-08-28") == 105.0


def test_fallback_uses_prior_day_when_today_absent(tmp_path, monkeypatch):
    """오늘 봉이 없으면 직전 거래일(≤today) VWAP로 폴백."""
    _iso(tmp_path, monkeypatch)
    with db_mod.get_connection() as conn:
        _seed(conn, "005930", "2026-08-27", [(200, 5), (200, 5)])  # VWAP=200
    assert u._fallback_vwap_from_bars("005930", today="2026-08-28") == 200.0


def test_fallback_prefers_today_over_prior(tmp_path, monkeypatch):
    """오늘·직전일 둘 다 있으면 오늘 것을 쓴다(재기동 대비)."""
    _iso(tmp_path, monkeypatch)
    with db_mod.get_connection() as conn:
        _seed(conn, "005930", "2026-08-27", [(200, 10)])
        _seed(conn, "005930", "2026-08-28", [(100, 10)])
    assert u._fallback_vwap_from_bars("005930", today="2026-08-28") == 100.0


def test_fallback_none_when_no_bars(tmp_path, monkeypatch):
    """해당 종목 봉이 전혀 없으면 None(그때만 fail-open)."""
    _iso(tmp_path, monkeypatch)
    with db_mod.get_connection() as conn:
        _seed(conn, "005930", "2026-08-28", [(100, 10)])
    assert u._fallback_vwap_from_bars("999999", today="2026-08-28") is None


def test_fallback_none_when_table_absent(tmp_path, monkeypatch):
    """intraday_bars 테이블 자체가 없어도 예외 없이 None."""
    _iso(tmp_path, monkeypatch)
    with db_mod.get_connection():
        pass  # 빈 DB — 테이블 미생성
    assert u._fallback_vwap_from_bars("005930", today="2026-08-28") is None


# ── 오늘 시가 — 시가대비 추격 판정용 (2026-09-05 엣지) ─────────────────────────

def _seed_open(conn, symbol, trade_date, bars):
    """bars = [(bar_ts, open), ...] 를 intraday_bars에 시딩."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS intraday_bars(id INTEGER PRIMARY KEY, trade_date TEXT, "
        "symbol TEXT, bar_ts TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL, "
        "shnu_rate REAL, created_at TEXT)"
    )
    for ts, o in bars:
        conn.execute(
            "INSERT INTO intraday_bars(trade_date,symbol,bar_ts,open) VALUES(?,?,?,?)",
            (trade_date, symbol, ts, o),
        )
    conn.commit()


def test_day_open_returns_first_bar_open(tmp_path, monkeypatch):
    """장 첫 봉(최소 bar_ts)의 open을 시가로 반환 — bar_ts 순서 무관."""
    _iso(tmp_path, monkeypatch)
    with db_mod.get_connection() as conn:
        _seed_open(conn, "005930", "2026-08-28", [("093000", 100.0), ("090000", 95.0), ("100000", 110.0)])
    assert u._day_open_from_bars("005930", today="2026-08-28") == 95.0  # 최소 bar_ts=09:00


def test_day_open_none_when_no_bars(tmp_path, monkeypatch):
    _iso(tmp_path, monkeypatch)
    with db_mod.get_connection() as conn:
        _seed_open(conn, "005930", "2026-08-28", [("090000", 95.0)])
    assert u._day_open_from_bars("999999", today="2026-08-28") is None


# ── 거래량 마름 — P2 진입 게이트 (2026-09-28 edge_backtest 검증) ────────────────

def _seed_vol(conn, symbol, trade_date, vols):
    """vols = [volume, ...] 를 bar_ts 순서대로 intraday_bars에 시딩."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS intraday_bars(id INTEGER PRIMARY KEY, trade_date TEXT, "
        "symbol TEXT, bar_ts TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL, "
        "shnu_rate REAL, created_at TEXT)"
    )
    for i, v in enumerate(vols):
        conn.execute(
            "INSERT INTO intraday_bars(trade_date,symbol,bar_ts,volume) VALUES(?,?,?,?)",
            (trade_date, symbol, f"{i:04d}", v),
        )
    conn.commit()


def test_vol_dryup_computes_recent_over_prior(tmp_path, monkeypatch):
    """최근5봉 평균 / 직전 5~15봉(=그전 10봉) 평균. 마르면 <1."""
    _iso(tmp_path, monkeypatch)
    with db_mod.get_connection() as conn:
        # 직전 10봉(0~9)=200, 최근 5봉(10~14)=100 → 100/200 = 0.5
        _seed_vol(conn, "005930", "2026-08-28", [200] * 10 + [100] * 5)
    assert u._vol_dryup_from_bars("005930", today="2026-08-28") == 0.5


def test_vol_dryup_surge_over_one(tmp_path, monkeypatch):
    """진입 직전 거래량 급증(투매)이면 >1 → 게이트가 차단할 값."""
    _iso(tmp_path, monkeypatch)
    with db_mod.get_connection() as conn:
        _seed_vol(conn, "005930", "2026-08-28", [100] * 10 + [400] * 5)  # 400/100 = 4.0
    assert u._vol_dryup_from_bars("005930", today="2026-08-28") == 4.0


def test_vol_dryup_none_when_too_few_bars(tmp_path, monkeypatch):
    """봉<15개면 None(fail-open — 게이트 통과)."""
    _iso(tmp_path, monkeypatch)
    with db_mod.get_connection() as conn:
        _seed_vol(conn, "005930", "2026-08-28", [100] * 14)
    assert u._vol_dryup_from_bars("005930", today="2026-08-28") is None


def test_vol_dryup_none_when_no_bars(tmp_path, monkeypatch):
    """해당 종목 봉 없음 → None."""
    _iso(tmp_path, monkeypatch)
    with db_mod.get_connection() as conn:
        _seed_vol(conn, "005930", "2026-08-28", [100] * 20)
    assert u._vol_dryup_from_bars("999999", today="2026-08-28") is None
