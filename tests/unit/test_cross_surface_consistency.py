"""교차 화면 일관성 회귀 가드 (2026-06-19).

배경: 같은 "당일 성적"을 Daily Results / Review 매수판단 / 손실패턴 / LLM 복기 4곳이
각자 계산해 6/19가 1/9 vs 3/7로 갈렸다(조회 윈도우 의존 FIFO 페어링이 원인).
근본 수정: day_score 하나(SSOT)를 S10이 1회 계산→DB저장→모두가 그 값만 읽는다.

이 테스트는 그 정합이 다시 깨지지 않도록 강제한다:
  ① SSOT 구조 불변식 — 종목수 = 완료 + 미청산, 손실리스트 = 패, 승+패+보합 = 완료.
  ② Daily Results 엔드포인트가 **저장 day_score를 읽고**(윈도우 재계산 금지), 조회 범위를
     바꿔도 승/패가 불변임.
  ③ LLM 복기 컨텍스트의 "확정 매매성적" 줄이 같은 day_score에서 나옴.

누군가 어딘가에 또 따로 계산하는 코드를 넣으면 여기서 즉시 실패한다.
"""

import sqlite3

import pytest

from backend.services.engine.trade_pairs import compute_daily_score


def _pair(symbol, trade_date, status, pnl_pct, orders=None):
    return {
        "symbol": symbol, "trade_date": trade_date, "status": status,
        "pnl_pct": pnl_pct, "pnl_amount": int((pnl_pct or 0) * 100),
        "orders": orders or [], "name": symbol, "exit_reason": None,
    }


# ──────────────────────────────────────────────────────────────────────────────
# ① SSOT 구조 불변식 — 카드 간 숫자가 묶이는 관계 (PM 혼란의 "13종목 vs 3승7패" 방지)
# ──────────────────────────────────────────────────────────────────────────────

def _sample_day():
    return compute_daily_score("2026-06-19", pairs=[
        _pair("A", "2026-06-19", "매도완료", 1.2),    # 승
        _pair("B", "2026-06-19", "매도완료", 0.4),    # 승
        _pair("C", "2026-06-19", "매도완료", 2.1),    # 승
        _pair("D", "2026-06-19", "매도완료", -1.0),   # 패
        _pair("E", "2026-06-19", "매도완료", -0.5),   # 패
        _pair("F", "2026-06-19", "매도완료", -2.2),   # 패
        _pair("G", "2026-06-19", "매도완료", -0.3),   # 패
        _pair("H", "2026-06-19", "매도완료", -1.1),   # 패
        _pair("I", "2026-06-19", "매도완료", -0.7),   # 패
        _pair("J", "2026-06-19", "매도완료", -1.9),   # 패
        _pair("K", "2026-06-19", "매수완료", None),   # 미청산
        _pair("L", "2026-06-19", "매수완료", None),   # 미청산
        _pair("M", "2026-06-19", "매수완료", None),   # 미청산
        _pair("Z", "2026-06-18", "매도완료", -5.0),   # 전일 → 제외
    ])


def test_invariant_symbols_equals_completed_plus_open():
    """Review 하단 '13종목 = 완료 10 + 미청산 3' 가 항상 성립."""
    s = _sample_day()
    assert s["symbols"] == s["completed"] + s["open_positions"]
    assert s["symbols"] == 13 and s["completed"] == 10 and s["open_positions"] == 3


def test_invariant_wins_losses_flat_sum_to_completed():
    s = _sample_day()
    assert s["wins"] + s["losses"] + s["flat"] == s["completed"]
    assert s["wins"] == 3 and s["losses"] == 7


def test_invariant_losers_count_equals_losses():
    """손실패턴 카드(losers) 건수 = 패 건수. 둘이 어긋나면 화면이 갈린다."""
    s = _sample_day()
    assert len(s["losers"]) == s["losses"]


# ──────────────────────────────────────────────────────────────────────────────
# ② Daily Results 엔드포인트 — 저장 day_score 읽기 + 윈도우 무관
# ──────────────────────────────────────────────────────────────────────────────

_DRR_DDL = """
CREATE TABLE daily_review_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT,
    total_trades INTEGER DEFAULT 0,
    missed_entries_count INTEGER DEFAULT 0,
    false_positive_count INTEGER DEFAULT 0,
    integrity_warnings TEXT,
    pnl_status TEXT,
    equity_pnl REAL,
    equity_eod_total_eval REAL,
    day_score TEXT,
    created_at TEXT DEFAULT '2026-06-19T16:00:00'
);
CREATE TABLE daily_trade_summary (
    trade_date TEXT PRIMARY KEY,
    buy_orders INTEGER, realized_pnl REAL, realized_pnl_pct REAL,
    net_pnl REAL, net_pnl_pct REAL, pnl_status TEXT
);
CREATE TABLE market_tone_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT, tone TEXT, confidence REAL,
    created_at TEXT DEFAULT '2026-06-19T15:30:00'
);
"""


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """최소 스키마의 임시 DB로 settings.APP_DB_PATH를 갈아끼운다."""
    from backend.config import settings as cfg

    db_file = tmp_path / "xsurface.sqlite3"
    con = sqlite3.connect(db_file)
    con.executescript(_DRR_DDL)
    # 저장 day_score: 윈도우 재계산이면 절대 못 나오는 값(3승7패)을 넣어, '저장값을 읽는다'를 증명.
    con.execute(
        "INSERT INTO daily_review_reports (trade_date, day_score, equity_eod_total_eval) VALUES (?,?,?)",
        ("2026-06-19", '{"wins": 3, "losses": 7, "completed": 10, "open_positions": 3, '
                       '"symbols": 13, "win_rate": 30.0, "losers": []}', 115_146_855.0),
    )
    con.execute(
        "INSERT INTO daily_review_reports (trade_date, day_score, equity_eod_total_eval) VALUES (?,?,?)",
        ("2026-06-18", '{"wins": 3, "losses": 3, "completed": 6, "open_positions": 0, '
                       '"symbols": 6, "win_rate": 50.0, "losers": []}', 112_205_055.0),
    )
    con.commit()
    con.close()
    monkeypatch.setattr(cfg, "APP_DB_PATH", str(db_file))
    return db_file


def _row_for(resp, td):
    return next(r for r in resp["payload"] if r["trade_date"] == td)


def test_daily_results_reads_stored_day_score(temp_db):
    """Daily Results 6/19 = 저장 day_score(3승7패). 재계산 폴백이면 0/0이 나와 실패."""
    from backend.api.routes.trading_monitor import get_daily_results

    resp = get_daily_results()
    r19 = _row_for(resp, "2026-06-19")
    assert (r19["win_count"], r19["loss_count"]) == (3, 7)
    r18 = _row_for(resp, "2026-06-18")
    assert (r18["win_count"], r18["loss_count"]) == (3, 3)


def test_daily_results_window_independent(temp_db):
    """조회 범위(start_date)를 바꿔도 승/패는 저장값이라 불변 — 윈도우 의존 드리프트 제거 증명."""
    from backend.api.routes.trading_monitor import get_daily_results

    wide = _row_for(get_daily_results("2026-06-01", "2026-06-19"), "2026-06-19")
    narrow = _row_for(get_daily_results("2026-06-19", "2026-06-19"), "2026-06-19")
    assert (wide["win_count"], wide["loss_count"]) == (narrow["win_count"], narrow["loss_count"]) == (3, 7)


# ──────────────────────────────────────────────────────────────────────────────
# ③ LLM 복기 컨텍스트 — 같은 day_score에서 '확정 매매성적' 생성
# ──────────────────────────────────────────────────────────────────────────────

def test_review_context_uses_day_score(monkeypatch):
    """_build_review_context_md의 확정 매매성적 줄이 day_score 값과 일치(자체 재계산 금지)."""
    import backend.services.engine.review_audit as ra

    # DB를 건드리는 보조 조회(mc/app)는 None이어도 무방하도록 get_connection을 비운다.
    class _NullConn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, *a, **k):
            class _C:
                def fetchone(self_inner): return None
                def fetchall(self_inner): return []
            return _C()

    monkeypatch.setattr(ra, "get_connection", lambda: _NullConn())

    result = {"day_score": {"completed": 10, "wins": 3, "losses": 7,
                            "win_rate": 30.0, "open_positions": 3}}
    md = ra._build_review_context_md(result, "2026-06-19")
    assert "완료 10건 / 승 3 / 패 7" in md
    assert "미청산 3건" in md
    assert "자체 재계산 금지" in md
