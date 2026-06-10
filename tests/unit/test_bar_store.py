"""10초봉 영구 저장(bar_store) 단위 테스트 — 백테스트 데이터 토대 (2026-06-10).

배경: BarEngine의 10초봉은 deque(최대 360개)로 휘발된다. 봉 마감 시 버퍼 적재
→ 스케줄러 flush로 intraday_bars 테이블에 영구 저장하는 경로를 검증한다.
DB는 tmp_path sqlite + monkeypatch(get_connection)로 격리한다.
"""

import sqlite3

import backend.services.engine.bar_store as bs
from backend.services.engine.intraday_bar_engine import BarEngine


def _setup_db(tmp_path, monkeypatch, enabled=True):
    db = tmp_path / "t.sqlite3"

    class _Conn:
        def __enter__(self):
            self._c = sqlite3.connect(db)
            self._c.row_factory = sqlite3.Row
            return self._c

        def __exit__(self, *a):
            self._c.commit()
            self._c.close()

    monkeypatch.setattr(bs, "get_connection", lambda: _Conn())
    monkeypatch.setattr(bs, "get_setting", lambda key, default=None: enabled)
    # 모듈 상태(버퍼·enabled 캐시) 초기화 — 테스트 간 오염 방지
    bs._buffer.clear()
    bs._enabled_cache = None
    return db


def _bar(**over):
    base = {
        "bar_ts": "090010",
        "open": 100.0,
        "high": 110.0,
        "low": 99.0,
        "close": 105.0,
        "volume": 1234.0,
        "shnu_rate": 0.62,
    }
    base.update(over)
    return base


def test_enqueue_then_flush_persists_rows(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    bs.enqueue_bar("005930", _bar(bar_ts="090010"))
    bs.enqueue_bar("005930", _bar(bar_ts="090020", close=106.0))
    bs.enqueue_bar("000660", _bar(bar_ts="090010", volume=50.0))

    saved = bs.flush_bars()
    assert saved == 3

    with bs.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM intraday_bars ORDER BY symbol, bar_ts"
        ).fetchall()
    assert len(rows) == 3
    first = rows[0]
    assert first["symbol"] == "000660"
    assert first["bar_ts"] == "090010"
    assert first["open"] == 100.0
    assert first["high"] == 110.0
    assert first["low"] == 99.0
    assert first["close"] == 105.0
    assert first["volume"] == 50.0
    assert first["shnu_rate"] == 0.62
    assert first["trade_date"]  # 적재 시각 기준 KST 날짜가 채워진다
    assert first["created_at"]
    # flush 후 버퍼는 비워진다
    assert bs.flush_bars() == 0


def test_enqueue_noop_when_disabled(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch, enabled=False)
    bs.enqueue_bar("005930", _bar())
    assert len(bs._buffer) == 0
    assert bs.flush_bars() == 0


def test_flush_empty_buffer_returns_zero(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    assert bs.flush_bars() == 0


def test_cleanup_old_bars_respects_retention(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    bs._ensure_table()
    with bs.get_connection() as conn:
        for trade_date in ("2020-01-02", "2020-01-03", "2099-12-31"):
            conn.execute(
                """INSERT INTO intraday_bars
                   (trade_date, symbol, bar_ts, open, high, low, close, volume, shnu_rate, created_at)
                   VALUES (?, '005930', '090010', 1, 1, 1, 1, 1, 0.5, 't')""",
                (trade_date,),
            )
    removed = bs.cleanup_old_bars(retention_days=30)
    assert removed == 2
    with bs.get_connection() as conn:
        rows = conn.execute("SELECT trade_date FROM intraday_bars").fetchall()
    assert [r["trade_date"] for r in rows] == ["2099-12-31"]


def test_bar_engine_enqueues_closed_bar(tmp_path, monkeypatch):
    """새 버킷 틱 진입 시 직전 봉이 확정되어 bar_store로 전달되는지 검증."""
    _setup_db(tmp_path, monkeypatch)
    captured = []
    monkeypatch.setattr(bs, "enqueue_bar", lambda symbol, bar: captured.append((symbol, bar)))

    eng = BarEngine()
    tick = {"symbol": "005930", "price": 100.0, "cntg_vol": 10.0,
            "stck_cntg_hour": "090001", "shnu_rate": "55"}
    eng.ingest_tick(tick)
    eng.ingest_tick({**tick, "price": 102.0, "stck_cntg_hour": "090005"})
    # 같은 버킷(090000) 동안은 마감 없음
    assert captured == []
    # 새 버킷(090010) 진입 → 직전 봉 확정·적재
    eng.ingest_tick({**tick, "price": 103.0, "stck_cntg_hour": "090012"})
    assert len(captured) == 1
    symbol, bar = captured[0]
    assert symbol == "005930"
    assert bar["bar_ts"] == "090000"
    assert bar["open"] == 100.0
    assert bar["high"] == 102.0
    assert bar["close"] == 102.0
    assert bar["volume"] == 20.0
    assert bar["shnu_rate"] == 0.55  # 마감 시점 체결강도(0~1)


def test_bar_engine_tick_path_survives_enqueue_failure(tmp_path, monkeypatch):
    """enqueue 예외가 틱 경로를 절대 차단하지 않는다."""
    _setup_db(tmp_path, monkeypatch)

    def _boom(symbol, bar):
        raise RuntimeError("storage down")

    monkeypatch.setattr(bs, "enqueue_bar", _boom)
    eng = BarEngine()
    tick = {"symbol": "005930", "price": 100.0, "cntg_vol": 10.0, "stck_cntg_hour": "090001"}
    eng.ingest_tick(tick)
    eng.ingest_tick({**tick, "price": 105.0, "stck_cntg_hour": "090011"})  # 마감 시 예외 발생해도 통과
    assert eng.get_last_price("005930") == 105.0
    assert len(eng.get_bars("005930")) == 2
