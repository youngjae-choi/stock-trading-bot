"""P1-T2: 모의투자(output2) 부분체결 인식 + EOD 매도 체결확인·잔량 재주문 (2026-06-13).

배경:
- 모의투자에서 fill_poller가 output2 폴백 경로를 타며 ccld_qty>0이면
  부분체결 여부와 무관하게 통째 filled 처리 → 부분체결 감지·잔량 재주문이
  모의에서 작동 기회가 없었다.
- S9 EOD 청산은 매도 제출 후 체결 확인을 하지 않아 잔여 포지션이 이월됐다.
"""

from __future__ import annotations

import asyncio
import sqlite3

import backend.services.engine.eod_liquidation as eod
import backend.services.engine.fill_poller as fp


async def _sleep_noop(_seconds: float) -> None:
    return None


# ──────────────────────────────────────────────
# A. output2 폴백 부분체결 인식 (poll_once)
# ──────────────────────────────────────────────

def _sell_order(order_id="o1", qty=1000, status="submitted"):
    return {
        "id": order_id,
        "side": "sell",
        "symbol": "005930",
        "name": "삼성전자",
        "qty": qty,
        "price": 10000.0,
        "trade_date": "2026-06-12",
        "kis_order_no": "0000012345",
        "status": status,
    }


def _setup_poll_output2(monkeypatch, order, out2, *, already_filled=False):
    """poll_once를 DB/KIS 없이 output2 폴백 경로로만 실행하도록 의존성을 대체한다."""
    events: dict[str, list] = {"partial": [], "filled": [], "reorder": []}

    monkeypatch.setattr(fp, "_get_submitted_orders", lambda _td: [order])

    async def _inquiry(_date_str, side="all"):
        return {"output1": []}  # 모의투자 — output1 항상 비어있음

    monkeypatch.setattr(fp, "get_daily_order_inquiry", _inquiry)

    async def _fetch_out2(_symbol, _date_str, _order_no):
        return out2

    monkeypatch.setattr(fp, "_fetch_symbol_output2", _fetch_out2)
    monkeypatch.setattr(fp, "_is_already_filled", lambda _oid: already_filled)
    monkeypatch.setattr(
        fp, "_mark_order_partial",
        lambda _o, qty, price: events["partial"].append((qty, price)),
    )
    monkeypatch.setattr(fp, "_mark_order_filled", lambda _o, data: events["filled"].append(data))

    async def _reorder(_o, ccld_qty, rmn_qty):
        events["reorder"].append((ccld_qty, rmn_qty))

    monkeypatch.setattr(fp, "_maybe_reorder_sell_remainder", _reorder)
    monkeypatch.setattr(fp, "_notify_buy_fill", lambda *_a: None)
    monkeypatch.setattr(fp, "_notify_sell_fill", lambda *_a: None)
    monkeypatch.setattr(fp.asyncio, "sleep", _sleep_noop)
    return events


def test_output2_partial_records_partial_and_tracks_remainder(monkeypatch):
    """① output2 체결수량 < 주문수량 → partial 기록 + 잔량 추적(재주문 후보) 호출."""
    order = _sell_order(qty=1000)
    out2 = {
        "odno": "0000012345",
        "tot_ord_qty": "1000",
        "tot_ccld_qty": "600",
        "pchs_avg_pric": "10000",
    }
    events = _setup_poll_output2(monkeypatch, order, out2)

    result = asyncio.run(fp.poll_once("2026-06-12"))

    assert len(events["partial"]) == 1
    assert events["partial"][0][0] == 600  # 부분 체결수량
    assert events["filled"] == []  # 통째 filled 처리 금지
    assert events["reorder"] == [(600, 400)]  # 잔량 추적 dict 갱신 경로
    assert result["filled"] == 0


def test_output2_partial_without_tot_ord_qty_uses_local_order_qty(monkeypatch):
    """output2에 주문수량 필드가 없어도 로컬 주문수량 기준으로 partial을 판정한다."""
    order = _sell_order(qty=1000)
    out2 = {"odno": "0000012345", "tot_ccld_qty": "600", "pchs_avg_pric": "10000"}
    events = _setup_poll_output2(monkeypatch, order, out2)

    asyncio.run(fp.poll_once("2026-06-12"))

    assert len(events["partial"]) == 1
    assert events["filled"] == []
    assert events["reorder"] == [(600, 400)]


def test_output2_missing_ccld_field_keeps_legacy_behavior(monkeypatch, caplog):
    """② 체결수량 필드 부재 → 섣부른 partial/filled 판정 없이 기존 동작 유지 + 구분 로그."""
    order = _sell_order(qty=1000)
    out2 = {"odno": "0000012345", "pchs_avg_pric": "10000"}  # tot_ccld_qty 없음
    events = _setup_poll_output2(monkeypatch, order, out2)

    with caplog.at_level("INFO", logger="FillPoller"):
        result = asyncio.run(fp.poll_once("2026-06-12"))

    assert events["partial"] == []
    assert events["filled"] == []
    assert events["reorder"] == []
    assert result["filled"] == 0
    assert any("ccld_field_missing" in record.getMessage() for record in caplog.records)


def test_output2_full_fill_still_marks_filled(monkeypatch):
    """체결수량 == 주문수량이면 기존대로 filled 처리한다 (회귀 가드)."""
    order = _sell_order(qty=1000)
    out2 = {
        "odno": "0000012345",
        "tot_ord_qty": "1000",
        "tot_ccld_qty": "1000",
        "pchs_avg_pric": "10000",
    }
    events = _setup_poll_output2(monkeypatch, order, out2)

    result = asyncio.run(fp.poll_once("2026-06-12"))

    assert events["partial"] == []
    assert len(events["filled"]) == 1
    assert events["reorder"] == []
    assert result["filled"] == 1


def test_output2_partial_order_repolled_despite_existing_fill_row(monkeypatch):
    """partial 상태 주문은 fills 행이 이미 있어도 다음 폴링에서 계속 추적된다.

    (기존 _is_already_filled 가드가 partial 주문의 후속 체결/잔량 재주문을 영구 차단하던 버그)
    """
    order = _sell_order(qty=1000, status="partial")
    out2 = {
        "odno": "0000012345",
        "tot_ord_qty": "1000",
        "tot_ccld_qty": "600",
        "pchs_avg_pric": "10000",
    }
    events = _setup_poll_output2(monkeypatch, order, out2, already_filled=True)

    asyncio.run(fp.poll_once("2026-06-12"))

    assert events["reorder"] == [(600, 400)]  # 정체 추적 지속


# ──────────────────────────────────────────────
# B. fills 누적 정합 (partial 중복 기록 방지 — tmp DB)
# ──────────────────────────────────────────────

def _make_tmp_db(tmp_path):
    db_path = tmp_path / "test_fills.db"

    def _connect():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trading_orders (
                id TEXT PRIMARY KEY, trade_date TEXT, symbol TEXT, name TEXT,
                side TEXT, order_type TEXT, qty INTEGER, price REAL,
                kis_order_no TEXT, status TEXT, reason TEXT, created_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fills (
                id TEXT PRIMARY KEY, order_id TEXT, broker_fill_id TEXT,
                symbol TEXT, side TEXT, quantity REAL, price REAL,
                fee REAL DEFAULT 0, tax REAL DEFAULT 0, filled_at TEXT, raw_json TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY, broker_order_id TEXT, symbol TEXT, side TEXT,
                order_type TEXT, quantity REAL, limit_price REAL, status TEXT,
                requested_at TEXT, updated_at TEXT, request_json TEXT, response_json TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO trading_orders (id, trade_date, symbol, side, qty, price, kis_order_no, status) "
            "VALUES ('o1', '2026-06-12', '005930', 'sell', 1000, 10000, '0000012345', 'submitted')"
        )
    return _connect


def _fills_sum(connect, order_id="o1") -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) FROM fills WHERE order_id = ?", (order_id,)
        ).fetchone()
    return int(row[0])


def test_partial_then_full_fill_keeps_fills_sum_equal_to_order_qty(monkeypatch, tmp_path):
    """partial 반복 기록·최종 filled 전환 후에도 fills 합계 == 총 체결수량 (중복 금지)."""
    connect = _make_tmp_db(tmp_path)
    monkeypatch.setattr(fp, "get_connection", connect)
    order = _sell_order(qty=1000)

    fp._mark_order_partial(order, 600, 10000.0)
    assert _fills_sum(connect) == 600

    # 같은 누적 체결수량으로 재폴링 — 중복 행 금지
    fp._mark_order_partial(order, 600, 10000.0)
    assert _fills_sum(connect) == 600

    # 진행: 600 → 800
    fp._mark_order_partial(order, 800, 10000.0)
    assert _fills_sum(connect) == 800

    # 전량 체결 전환 — 잔여분(200)만 추가 기록
    fill_data = {
        "odno": "0000012345",
        "pdno": "005930",
        "tot_ccld_qty": "1000",
        "avg_prvs": "10000",
        "sll_buy_dvsn_cd": "01",
    }
    fp._mark_order_filled(order, fill_data)
    assert _fills_sum(connect) == 1000
    with connect() as conn:
        status = conn.execute("SELECT status FROM trading_orders WHERE id='o1'").fetchone()[0]
    assert status == "filled"


# ──────────────────────────────────────────────
# C. S9 EOD 매도 체결확인 + 잔량 재시도
# ──────────────────────────────────────────────

def _setup_eod(monkeypatch, balance_sequence):
    """run_eod_liquidation을 DB/KIS 없이 실행하도록 의존성을 대체한다.

    Args:
        balance_sequence: _get_open_positions_from_account가 호출 순서대로 반환할 잔고 목록.
    """
    calls = {"sells": [], "alerts": [], "balance_calls": 0}
    seq = list(balance_sequence)

    async def _balance():
        idx = min(calls["balance_calls"], len(seq) - 1)
        calls["balance_calls"] += 1
        return [dict(p) for p in seq[idx]]

    monkeypatch.setattr(eod, "_get_open_positions_from_account", _balance)
    monkeypatch.setattr(eod, "_record_legacy_residual_alert", lambda _td: [])
    monkeypatch.setattr(eod, "find_active_sell_order", lambda *_a, **_k: None)

    async def _execute_sell(**kwargs):
        calls["sells"].append(kwargs)
        return {"ok": True, "status": "submitted", "kis_order_no": "0000099999",
                "symbol": kwargs.get("symbol")}

    monkeypatch.setattr(eod.order_executor, "execute_sell", _execute_sell)
    monkeypatch.setattr(
        eod, "create_integrity_alert_once",
        lambda trade_date, **kwargs: calls["alerts"].append({"trade_date": trade_date, **kwargs}) or True,
    )
    monkeypatch.setattr(eod.asyncio, "sleep", _sleep_noop)
    return calls


_POS = {"symbol": "005930", "name": "삼성전자", "qty": 10, "source": "kis_account"}


def test_eod_residual_after_retry_alerts(monkeypatch):
    """③ 재조회에서 잔여 발견 → 시장가 재시도 1회 + 재시도 후에도 남으면 CRITICAL 알림."""
    calls = _setup_eod(monkeypatch, [[_POS], [_POS], [_POS]])  # 끝까지 안 팔림

    result = asyncio.run(eod.run_eod_liquidation())

    assert len(calls["sells"]) == 2  # 본청산 1 + 재시도 1 (폭주 금지)
    assert calls["sells"][0]["reason"] == "eod"
    assert calls["sells"][1]["reason"] == "EOD_RETRY"
    assert result["retried"] == 1
    assert len(result["residual_after_retry"]) == 1
    assert result["residual_after_retry"][0]["symbol"] == "005930"
    assert len(calls["alerts"]) == 1
    assert calls["alerts"][0]["severity"] == "CRITICAL"
    assert "EOD 미체결 잔여" in calls["alerts"][0]["title"]


def test_eod_retry_clears_residual_no_alert(monkeypatch):
    """④ 재시도 후 잔고가 비면 알림 없이 정상 종료한다."""
    calls = _setup_eod(monkeypatch, [[_POS], [_POS], []])  # 재시도로 청산 완료

    result = asyncio.run(eod.run_eod_liquidation())

    assert len(calls["sells"]) == 2
    assert result["retried"] == 1
    assert result["residual_after_retry"] == []
    assert calls["alerts"] == []


def test_eod_no_residual_skips_retry(monkeypatch):
    """첫 재조회에서 잔고가 비면 재시도·알림 없이 종료한다."""
    calls = _setup_eod(monkeypatch, [[_POS], []])  # 본청산으로 전부 체결

    result = asyncio.run(eod.run_eod_liquidation())

    assert len(calls["sells"]) == 1
    assert result["retried"] == 0
    assert result["residual_after_retry"] == []
    assert calls["alerts"] == []
    # 기존 반환 키 보존
    for key in ("liquidated", "results", "summary", "skipped_duplicates",
                "legacy_residual_positions", "account_lookup_failed"):
        assert key in result


def test_eod_empty_positions_returns_retry_keys(monkeypatch):
    """청산 대상이 없으면 체결확인 대기 없이 retried=0으로 즉시 반환한다."""
    calls = _setup_eod(monkeypatch, [[]])

    result = asyncio.run(eod.run_eod_liquidation())

    assert calls["sells"] == []
    assert calls["balance_calls"] == 1  # 재조회 안 함
    assert result["retried"] == 0
    assert result["residual_after_retry"] == []
