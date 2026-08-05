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
# ③ 결정론 EOD 요약(텔레그램) — 같은 day_score(SSOT)에서 '확정 매매성적' 생성
#    (LLM 복기 컨텍스트는 제거됨 — 요약은 day_score만 읽는다)
# ──────────────────────────────────────────────────────────────────────────────

def _capture_eod_summary(monkeypatch, result):
    """_send_action_plan_for_approval이 만든 텔레그램 본문을 캡처해 반환."""
    import asyncio

    import backend.services.alert_service as alert_service
    import backend.services.engine.review_audit as ra

    sent = {}

    async def _fake_send(title, body):
        sent["title"] = title
        sent["body"] = body

    monkeypatch.setattr(alert_service, "send_telegram_alert", _fake_send)
    asyncio.run(ra._send_action_plan_for_approval(result))
    return sent


def test_eod_summary_uses_day_score(monkeypatch):
    """EOD 요약의 완료/승/패가 day_score 값과 일치(자체 재계산 금지)."""
    result = {"trade_date": "2026-06-19", "realized_pnl_pct": 1.23,
              "day_score": {"completed": 10, "wins": 3, "losses": 7,
                            "win_rate": 30.0, "open_positions": 3}}
    sent = _capture_eod_summary(monkeypatch, result)
    assert "완료 10건 (승 3·패 7)" in sent["body"]
    assert "2026-06-19" in sent["title"]


# ──────────────────────────────────────────────────────────────────────────────
# ④ A2: 요약 거래수·승패가 day_score(SSOT)와 일치 — 시그널 기반 값과 갈리지 않음
# ──────────────────────────────────────────────────────────────────────────────

def test_eod_summary_prefers_day_score_over_signal_counts(monkeypatch):
    """요약은 day_score만 읽는다 — 시그널 기반 total_trades/win_count가 달라도 무시."""
    result = {"trade_date": "2026-06-24", "realized_pnl_pct": 0.0,
              "total_trades": 6, "win_count": 2, "loss_count": 4,
              "day_score": {"completed": 3, "wins": 2, "losses": 1,
                            "win_rate": 66.7, "open_positions": 1}}
    sent = _capture_eod_summary(monkeypatch, result)
    assert "완료 3건 (승 2·패 1)" in sent["body"]
    assert "6건" not in sent["body"]


def test_cross_surface_auto_imported_consistency(tmp_path, monkeypatch):
    """2 정상 짝 + 1 흡수 매도 → day_score.completed == Review 표시 거래수 == 페어합 실현손익."""
    import backend.services.engine.position_cost_basis as cb
    from backend.config import settings as cfg
    from backend.services import db as db_mod
    from backend.services.engine.trade_pairs import (
        compute_daily_score,
        get_today_realized_pnl,
        get_trade_pairs,
    )

    p = tmp_path / "xsurf_a2.sqlite3"
    monkeypatch.setattr(cfg, "APP_DB_PATH", str(p))
    db_mod.initialize_database()
    td = "2026-06-24"
    with db_mod.get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS trading_orders(
              id INTEGER PRIMARY KEY AUTOINCREMENT, trade_date TEXT, signal_id TEXT,
              symbol TEXT, name TEXT, side TEXT, order_type TEXT, qty INTEGER, price REAL,
              kis_order_no TEXT, status TEXT, reason TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS fills(
              id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER, price REAL, quantity REAL);
            """
        )

        def _o(symbol, side, qty, price, no, ca):
            conn.execute(
                "INSERT INTO trading_orders(trade_date,symbol,name,side,order_type,qty,price,kis_order_no,status,created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (td, symbol, "종목", side, "limit", qty, price, no, "filled", f"{td}T{ca}"),
            )

        _o("457370", "buy", 100, 10000, "B1", "10:00:00")
        _o("457370", "sell", 100, 10500, "S1", "11:00:00")   # 정상 짝 +50000
        _o("005930", "buy", 10, 70000, "B2", "10:05:00")
        _o("005930", "sell", 10, 71000, "S2", "11:05:00")    # 정상 짝 +10000
        _o("069500", "sell", 5, 9000, "S3", "11:10:00")      # 흡수 매도(매수 fill 없음)
        conn.commit()
    cb.upsert_cost_basis("069500", 5, 8000.0, "auto_imported", "2026-06-23")  # 전일 흡수 +5000

    pairs = get_trade_pairs(td, td)
    day_score = compute_daily_score(td, pairs=pairs)

    # 흡수 매도가 완료로 집계됐는지 (정상2 + 흡수1 = 3)
    assert day_score["completed"] == 3
    assert day_score["wins"] == 3

    # get_today_realized_pnl == 그날 페어 pnl_amount 합
    pairs_sum = sum(x["pnl_amount"] for x in pairs if x.get("pnl_amount") is not None)
    assert get_today_realized_pnl(td) == pairs_sum == 65000.0


def test_carried_classification_uses_cost_basis_date():
    """전일 흡수·당일 매도 페어는 cost_basis_trade_date로 '이월' 분류(당일 신규 아님)."""
    import backend.services.engine.review_audit as ra

    td = "2026-06-24"
    carried_pair = {
        "symbol": "069500", "trade_date": td, "status": "매도완료",
        "pnl_pct": 12.5, "pnl_amount": 5000, "orders": [],  # 매수 주문 없음
        "cost_basis_source": "auto_imported", "cost_basis_trade_date": "2026-06-23",
    }
    same_day_pair = {
        "symbol": "457370", "trade_date": td, "status": "매도완료",
        "pnl_pct": 5.0, "pnl_amount": 50000,
        "orders": [{"side": "buy", "trade_date": td}, {"side": "sell", "trade_date": td}],
        "cost_basis_source": None, "cost_basis_trade_date": None,
    }
    assert ra._pair_buy_date(carried_pair) == "2026-06-23"
    day_pairs, carried = ra._split_carried_pairs([carried_pair, same_day_pair], td)
    assert carried == [carried_pair]
    assert same_day_pair in day_pairs
