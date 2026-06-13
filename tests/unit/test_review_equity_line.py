"""S10 복기 — 자본변화(equity) 라인 병기 + 이월 잔여 거래 분리 (P2, 2026-06-13).

배경: 복기는 FIFO 짝 실현손익만 집계해 계좌 실제 자본변화와 다르다
(6/12: 복기 -290,507원 vs 계좌 +8M — 미실현·비용·이월 미반영).
콘솔 당일손익과 같은 기준(A안: total_eval - baseline)을 복기 보고서에 병기하고,
전일 이월 포지션 청산을 당일 신규 거래와 분리해 승률 왜곡을 막는다.
"""

import asyncio
import sqlite3

import backend.services.engine.daily_capital as dc
import backend.services.engine.review_audit as ra
import backend.services.engine.trade_pairs as tp_mod


# ──────────────────────────────────────────────────────────────────────────────
# ① equity 스냅샷 계산
# ──────────────────────────────────────────────────────────────────────────────

def test_equity_snapshot_computed(monkeypatch):
    async def fake_total_eval():
        return 108_000_000.0

    monkeypatch.setattr(ra, "_fetch_eod_total_eval", fake_total_eval)
    monkeypatch.setattr(dc, "get_baseline", lambda d=None: 100_000_000.0)

    snap = asyncio.run(ra._compute_equity_snapshot("2026-06-12"))
    assert snap["equity_eod_total_eval"] == 108_000_000.0
    assert snap["equity_pnl"] == 8_000_000.0
    assert abs(snap["equity_pnl_pct"] - 8.0) < 1e-9


# ──────────────────────────────────────────────────────────────────────────────
# ② 잔고 조회 실패 시 None + 비치명
# ──────────────────────────────────────────────────────────────────────────────

def test_equity_snapshot_balance_failure_is_nonfatal(monkeypatch):
    async def boom():
        raise RuntimeError("KIS token issuance failed")

    monkeypatch.setattr(ra, "_fetch_eod_total_eval", boom)

    snap = asyncio.run(ra._compute_equity_snapshot("2026-06-12"))
    assert snap == {
        "equity_eod_total_eval": None,
        "equity_pnl": None,
        "equity_pnl_pct": None,
    }


def test_equity_snapshot_without_baseline_keeps_total_eval(monkeypatch):
    async def fake_total_eval():
        return 108_000_000.0

    monkeypatch.setattr(ra, "_fetch_eod_total_eval", fake_total_eval)
    monkeypatch.setattr(dc, "get_baseline", lambda d=None: None)

    snap = asyncio.run(ra._compute_equity_snapshot("2026-06-12"))
    assert snap["equity_eod_total_eval"] == 108_000_000.0
    assert snap["equity_pnl"] is None
    assert snap["equity_pnl_pct"] is None


# ──────────────────────────────────────────────────────────────────────────────
# 마크다운 보고서 표기
# ──────────────────────────────────────────────────────────────────────────────

def _base_result(**overrides):
    result = {
        "trade_date": "2026-06-12",
        "total_trades": 1,
        "win_count": 1,
        "loss_count": 0,
        "realized_pnl": -290507.0,
        "realized_pnl_pct": -0.29,
        "total_orders": 2,
        "buy_orders": 1,
        "sell_orders": 1,
        "failed_orders": 0,
        "pnl_status": "verified",
        "pnl_source": "fills",
        "missed_entries": [],
        "false_positives": [],
        "missed_entries_count": 0,
        "false_positive_count": 0,
        "trade_pairs": [],
        "exit_summary": {},
        "integrity_warnings": [],
    }
    result.update(overrides)
    return result


def test_markdown_includes_equity_row_and_difference_note():
    md = ra._build_review_markdown(
        _base_result(equity_pnl=8_000_000.0, equity_pnl_pct=8.0, equity_eod_total_eval=108_000_000.0)
    )
    assert "자본변화" in md
    assert "+8,000,000원" in md
    assert "+8.00%" in md
    # 짝 실현손익과의 차이 설명 한 줄
    assert "미실현" in md and "이월" in md


def test_markdown_equity_unavailable_marker():
    md = ra._build_review_markdown(_base_result(equity_pnl=None, equity_pnl_pct=None))
    assert "자본변화" in md
    assert "산출 불가" in md


# ──────────────────────────────────────────────────────────────────────────────
# ③ 이월 짝 분리 집계
# ──────────────────────────────────────────────────────────────────────────────

def _pair(symbol, name, status, pair_date, buy_date, sell_date=None, pnl_amount=0.0):
    orders = [{"side": "buy", "trade_date": buy_date, "created_at": f"{buy_date}T09:30:00"}]
    if sell_date:
        orders.append({"side": "sell", "trade_date": sell_date, "created_at": f"{sell_date}T14:30:00"})
    return {
        "symbol": symbol,
        "name": name,
        "status": status,
        "trade_date": pair_date,
        "pnl_amount": pnl_amount,
        "pnl_pct": 1.0 if pnl_amount >= 0 else -1.0,
        "buy_price": 1000.0,
        "sell_price": 1010.0,
        "exit_reason": "TRAILING_STOP",
        "orders": orders,
    }


def test_split_carried_pairs_separates_prior_day_buys():
    d = "2026-06-12"
    today_pair = _pair("111111", "당일종목", "매도완료", d, d, d, 50_000.0)
    carried_pair = _pair("222222", "이월종목", "매도완료", d, "2026-06-11", d, 30_000.0)
    holding_pair = _pair("333333", "보유종목", "매수완료", d, d)

    day_pairs, carried = ra._split_carried_pairs([today_pair, carried_pair, holding_pair], d)
    assert carried == [carried_pair]
    assert today_pair in day_pairs and holding_pair in day_pairs


def test_markdown_carried_section_separated():
    d = "2026-06-12"
    today_pair = _pair("111111", "당일종목", "매도완료", d, d, d, 50_000.0)
    carried_pair = _pair("222222", "이월종목", "매도완료", d, "2026-06-11", d, 30_000.0)
    md = ra._build_review_markdown(_base_result(trade_pairs=[today_pair, carried_pair]))

    assert "이월 포지션 청산" in md
    # 이월 종목은 "완료된 거래"(당일) 테이블이 아닌 이월 섹션에만 표기
    completed_section = md.split("이월 포지션 청산")[0]
    assert "이월종목" not in completed_section
    assert "당일종목" in completed_section
    carried_section = md.split("이월 포지션 청산")[1]
    assert "이월종목" in carried_section


# ──────────────────────────────────────────────────────────────────────────────
# ①+③+④ run_review_audit 통합 — 저장·이월 분리·기존 필드 회귀 없음
# ──────────────────────────────────────────────────────────────────────────────

_OLD_REPORT_SCHEMA = """
CREATE TABLE daily_review_reports (
    id TEXT, trade_date TEXT, total_trades INTEGER, win_count INTEGER,
    loss_count INTEGER, total_pnl REAL, profile_summary TEXT, exit_summary TEXT,
    trailing_quality TEXT, no_trade_count INTEGER, memory_count INTEGER,
    created_at TEXT, missed_entries TEXT, false_positives TEXT,
    missed_entries_count INTEGER, false_positive_count INTEGER,
    pnl_status TEXT NOT NULL DEFAULT 'unverified',
    pnl_source TEXT NOT NULL DEFAULT 'orders_without_fills',
    integrity_warnings TEXT NOT NULL DEFAULT '[]',
    legacy_residual_positions TEXT NOT NULL DEFAULT '[]'
)
"""


def _setup_tmp_db(db_path, trade_date):
    con = sqlite3.connect(db_path)
    con.executescript(
        f"""
        CREATE TABLE trading_signals (
            id TEXT, trade_date TEXT, symbol TEXT, status TEXT, created_at TEXT,
            realized_pnl REAL, risk_profile TEXT, exit_reason TEXT,
            entry_price REAL, trigger_price REAL
        );
        CREATE TABLE trading_orders (
            id TEXT, trade_date TEXT, signal_id TEXT, symbol TEXT, name TEXT,
            side TEXT, order_type TEXT, qty INTEGER, price REAL,
            kis_order_no TEXT, status TEXT, reason TEXT, created_at TEXT
        );
        CREATE TABLE profile_performance_daily (
            id TEXT, trade_date TEXT, profile TEXT, trade_count INTEGER,
            win_count INTEGER, total_pnl REAL, avg_pnl REAL, created_at TEXT
        );
        CREATE TABLE exit_reason_performance_daily (
            id TEXT, trade_date TEXT, exit_reason TEXT, trade_count INTEGER,
            avg_pnl REAL, created_at TEXT
        );
        CREATE TABLE trailing_quality_daily (
            id TEXT, trade_date TEXT, avg_recovery_rate REAL, early_exit_rate REAL,
            total_trailing_exits INTEGER, created_at TEXT
        );
        CREATE TABLE no_trade_daily_reasons (
            id TEXT, trade_date TEXT, reason TEXT, detail TEXT, created_at TEXT
        );
        {_OLD_REPORT_SCHEMA};
        """
    )
    # 체결 BUY 시그널 1건 (당일 신규, 승리)
    con.execute(
        "INSERT INTO trading_signals (id, trade_date, symbol, status, created_at, realized_pnl, risk_profile)"
        " VALUES ('s1', ?, '111111', 'executed', ?, 50000.0, 'MID_VOL')",
        (trade_date, f"{trade_date}T09:30:00"),
    )
    # 체결 buy/sell 주문 (filled_buy_symbols + exit map)
    con.executemany(
        "INSERT INTO trading_orders (id, trade_date, signal_id, symbol, name, side, order_type, qty, price,"
        " kis_order_no, status, reason, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("o1", trade_date, "s1", "111111", "당일종목", "buy", "limit", 10, 1000.0, "K1", "filled", "", f"{trade_date}T09:30:00"),
            ("o2", trade_date, "s1", "111111", "당일종목", "sell", "limit", 10, 1010.0, "K2", "filled", "TRAILING_STOP", f"{trade_date}T14:00:00"),
        ],
    )
    con.commit()
    con.close()


class _Conn:
    def __init__(self, db_path):
        self._path = db_path

    def __enter__(self):
        self._c = sqlite3.connect(self._path)
        self._c.row_factory = sqlite3.Row
        return self._c

    def __exit__(self, *a):
        self._c.commit()
        self._c.close()


def test_run_review_audit_persists_equity_and_splits_carried(tmp_path, monkeypatch):
    d = "2026-06-12"
    db = str(tmp_path / "t.sqlite3")
    _setup_tmp_db(db, d)

    monkeypatch.setattr(ra, "get_connection", lambda: _Conn(db))

    # 거래일 가드 통과
    import backend.services.engine.trading_calendar as cal
    monkeypatch.setattr(cal, "is_trading_day", lambda dd: True)

    # KIS 호출 경로 차단 (orphan/residual reconcile)
    import backend.services.engine.order_reconciliation as orc
    import backend.services.engine.residual_reconciliation as rrc

    async def _no_rec(dd):
        return {"checked": False}

    async def _no_rrc(dd):
        return {"reconciled": 0}

    monkeypatch.setattr(orc, "reconcile_orders_with_kis", _no_rec)
    monkeypatch.setattr(rrc, "reconcile_residual_positions_with_kis", _no_rrc)

    # 짝 동기화·주문요약·무결성·마크다운·LLM 액션플랜 격리
    monkeypatch.setattr(ra, "_sync_realized_pnl_from_trade_pairs", lambda dd: None)
    monkeypatch.setattr(ra, "get_today_orders", lambda dd: [])
    monkeypatch.setattr(
        ra,
        "summarize_order_integrity",
        lambda dd: {"pnl_status": "verified", "pnl_source": "fills", "warnings": [], "legacy_residual_positions": []},
    )
    monkeypatch.setattr(ra, "create_integrity_alert_once", lambda *a, **k: None)
    monkeypatch.setattr(ra, "_write_review_markdown", lambda result: str(tmp_path / "audit.md"))

    async def _no_action_plan(result):
        return None

    monkeypatch.setattr(ra, "_send_action_plan_for_approval", _no_action_plan)

    # equity 주입: total_eval 108M / baseline 100M
    async def fake_total_eval():
        return 108_000_000.0

    monkeypatch.setattr(ra, "_fetch_eod_total_eval", fake_total_eval)
    monkeypatch.setattr(dc, "get_baseline", lambda dd=None: 100_000_000.0)

    # trade_pairs: 당일 신규 1 + 이월(전일 매수) 1
    today_pair = _pair("111111", "당일종목", "매도완료", d, d, d, 50_000.0)
    carried_pair = _pair("222222", "이월종목", "매도완료", d, "2026-06-11", d, 30_000.0)
    monkeypatch.setattr(tp_mod, "get_trade_pairs", lambda s, e: [today_pair, carried_pair])

    result = asyncio.run(ra.run_review_audit(d))

    # ① equity 라인 — result + DB 저장
    assert result["ok"] is True
    assert result["equity_pnl"] == 8_000_000.0
    assert abs(result["equity_pnl_pct"] - 8.0) < 1e-9
    assert result["equity_eod_total_eval"] == 108_000_000.0

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT * FROM daily_review_reports WHERE trade_date=?", (d,)).fetchone()
    con.close()
    assert row is not None
    assert row["equity_pnl"] == 8_000_000.0
    assert row["equity_eod_total_eval"] == 108_000_000.0

    # ③ 이월 분리 — 당일 승률/total_trades에서 제외, 별도 버킷 집계
    assert result["total_trades"] == 1
    assert result["win_count"] == 1
    assert result["carried_count"] == 1
    assert result["carried_pnl"] == 30_000.0

    # ④ 기존 보고서 필드 회귀 없음
    assert row["total_trades"] == 1
    assert row["win_count"] == 1
    assert row["loss_count"] == 0
    assert row["total_pnl"] == 50_000.0
    assert row["pnl_status"] == "verified"
    assert row["pnl_source"] == "fills"
    assert result["total_pnl"] == 50_000.0
    assert "trade_pairs" in result and len(result["trade_pairs"]) == 2


def test_run_review_audit_equity_failure_stores_null(tmp_path, monkeypatch):
    """KIS 잔고 조회 실패 시 equity 컬럼은 NULL로 저장되고 리뷰는 정상 완료된다."""
    d = "2026-06-12"
    db = str(tmp_path / "t.sqlite3")
    _setup_tmp_db(db, d)

    monkeypatch.setattr(ra, "get_connection", lambda: _Conn(db))

    import backend.services.engine.trading_calendar as cal
    monkeypatch.setattr(cal, "is_trading_day", lambda dd: True)

    import backend.services.engine.order_reconciliation as orc
    import backend.services.engine.residual_reconciliation as rrc

    async def _no_rec(dd):
        return {"checked": False}

    async def _no_rrc(dd):
        return {"reconciled": 0}

    monkeypatch.setattr(orc, "reconcile_orders_with_kis", _no_rec)
    monkeypatch.setattr(rrc, "reconcile_residual_positions_with_kis", _no_rrc)
    monkeypatch.setattr(ra, "_sync_realized_pnl_from_trade_pairs", lambda dd: None)
    monkeypatch.setattr(ra, "get_today_orders", lambda dd: [])
    monkeypatch.setattr(
        ra,
        "summarize_order_integrity",
        lambda dd: {"pnl_status": "verified", "pnl_source": "fills", "warnings": [], "legacy_residual_positions": []},
    )
    monkeypatch.setattr(ra, "create_integrity_alert_once", lambda *a, **k: None)
    monkeypatch.setattr(ra, "_write_review_markdown", lambda result: str(tmp_path / "audit.md"))

    async def _no_action_plan(result):
        return None

    monkeypatch.setattr(ra, "_send_action_plan_for_approval", _no_action_plan)

    async def boom():
        raise RuntimeError("KIS unavailable")

    monkeypatch.setattr(ra, "_fetch_eod_total_eval", boom)
    monkeypatch.setattr(tp_mod, "get_trade_pairs", lambda s, e: [])

    result = asyncio.run(ra.run_review_audit(d))
    assert result["ok"] is True
    assert result["equity_pnl"] is None
    assert result["equity_pnl_pct"] is None

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT * FROM daily_review_reports WHERE trade_date=?", (d,)).fetchone()
    con.close()
    assert row["equity_pnl"] is None
    assert row["equity_eod_total_eval"] is None
