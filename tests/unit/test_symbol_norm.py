"""ETN 심볼 Q-prefix 정규화 — 매칭/짝맞춤/무결성 계층 통일 (P1-T3).

배경(2026-06-11): 랭킹 API는 ETN을 'Q520100' 형식으로 주고, KIS 잔고·매도는
'520100'으로 온다. 매수는 Q-형, 매도는 무Q-형으로 기록돼
"520100: buy 0 / sell 614" 무결성 오류, FIFO 짝맞춤 실패, 중복매도 가드
무력화가 발생했다. 정규화는 **비교/매칭 시점에만** 적용하고
주문 제출·표시·DB 저장은 원본을 유지한다.

운영 DB 미접촉: 모든 DB 테스트는 tmp_path SQLite + get_connection monkeypatch.
"""

import sqlite3

import pytest

from backend.services.engine.symbol_norm import norm_symbol, symbol_variants


# ──────────────────────────────────────────────
# ① ~ ④ norm_symbol 단위 규칙
# ──────────────────────────────────────────────

def test_q_prefix_etn_is_normalized():
    # ① 대문자 'Q' + 숫자 6자리 → Q 제거
    assert norm_symbol("Q520100") == "520100"
    assert norm_symbol("Q580044") == "580044"


def test_bare_six_digit_code_unchanged():
    # ② 일반 6자리 코드는 불변
    assert norm_symbol("520100") == "520100"
    assert norm_symbol("005930") == "005930"


def test_alphanumeric_etf_code_unchanged():
    # ③ '0192S0' 같은 영숫자 ETF/ETN 코드는 절대 건드리지 않는다
    assert norm_symbol("0192S0") == "0192S0"
    assert norm_symbol("0193L0") == "0193L0"


def test_lowercase_q_is_not_normalized():
    # ④ 소문자 'q520100'은 KIS 정식 코드 아님 — 정규화하지 않고 원본 유지(방침).
    #    소문자 데이터가 보이면 정규화로 가리지 말고 원인 조사 대상.
    assert norm_symbol("q520100") == "q520100"


def test_norm_symbol_strips_and_handles_empty():
    assert norm_symbol("  Q520100  ") == "520100"
    assert norm_symbol("  520100  ") == "520100"
    assert norm_symbol("") == ""
    assert norm_symbol(None) == ""


def test_q_prefix_requires_exactly_six_digits():
    # 6자리 미만/초과, 숫자 아님 → 불변
    assert norm_symbol("Q52010") == "Q52010"
    assert norm_symbol("Q5201000") == "Q5201000"
    assert norm_symbol("QA20100") == "QA20100"
    assert norm_symbol("Q") == "Q"


def test_symbol_variants_expansion():
    # SQL IN 필터용 변형: 원본 + 정규화형 + Q부착형(숫자 6자리일 때만)
    assert symbol_variants("Q520100") == ["Q520100", "520100"]
    assert set(symbol_variants("520100")) == {"520100", "Q520100"}
    assert symbol_variants("0192S0") == ["0192S0"]
    assert symbol_variants("") == []
    assert symbol_variants(None) == []


# ──────────────────────────────────────────────
# DB 픽스처 — trading_orders / fills 임시 SQLite
# ──────────────────────────────────────────────

_ORDER_COLUMNS = (
    "id, trade_date, signal_id, symbol, name, side, order_type, "
    "qty, price, kis_order_no, status, reason, created_at"
)


def _make_db(tmp_path, orders, fills=()):
    db = tmp_path / "symbol_norm_t.sqlite3"
    con = sqlite3.connect(db)
    con.execute(
        """CREATE TABLE trading_orders (
            id TEXT, trade_date TEXT, signal_id TEXT, symbol TEXT, name TEXT,
            side TEXT, order_type TEXT, qty INTEGER, price REAL,
            kis_order_no TEXT, status TEXT, reason TEXT, created_at TEXT)"""
    )
    con.execute("CREATE TABLE fills (order_id TEXT, price REAL, quantity REAL)")
    con.executemany(
        f"INSERT INTO trading_orders ({_ORDER_COLUMNS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        orders,
    )
    con.executemany("INSERT INTO fills (order_id, price, quantity) VALUES (?,?,?)", fills)
    con.commit()
    con.close()
    return db


class _Conn:
    def __init__(self, db):
        self._db = db

    def __enter__(self):
        self._c = sqlite3.connect(self._db)
        self._c.row_factory = sqlite3.Row
        return self._c

    def __exit__(self, *a):
        self._c.close()


@pytest.fixture
def etn_split_db(tmp_path):
    """6/11 실사례 재현: 매수 'Q520100' 614주 체결, 매도 '520100' 614주 체결."""
    return _make_db(
        tmp_path,
        orders=[
            ("b1", "2026-06-11", "", "Q520100", "메리츠 KIS CD금리", "buy", "limit",
             614, 9750.0, "0001", "filled", "", "2026-06-11T09:05:00+09:00"),
            ("s1", "2026-06-11", "", "520100", "메리츠 KIS CD금리", "sell", "limit",
             614, 9800.0, "0002", "filled", "TRAILING_STOP", "2026-06-11T13:00:00+09:00"),
        ],
        fills=[("b1", 9750.0, 614.0), ("s1", 9800.0, 614.0)],
    )


# ──────────────────────────────────────────────
# ⑤ trade_pairs — Q매수 ↔ 무Q매도 FIFO 짝맞춤
# ──────────────────────────────────────────────

def test_trade_pairs_matches_q_buy_with_bare_sell(etn_split_db, monkeypatch):
    import backend.services.engine.trade_pairs as tp

    monkeypatch.setattr(tp, "get_connection", lambda: _Conn(etn_split_db))
    pairs = tp.get_trade_pairs("2026-06-11", "2026-06-11")

    assert len(pairs) == 1, "Q매수와 무Q매도가 한 쌍으로 묶여야 한다"
    pair = pairs[0]
    assert pair["status"] == "매도완료"
    assert pair["buy_qty"] == 614
    assert pair["sell_qty"] == 614
    assert pair["pnl_amount"] == round((9800 - 9750) * 614)
    assert pair["exit_reason"] == "TRAILING_STOP"
    # 표시/시그널 조인 심볼은 매수 시점 원본(Q-형) 유지 — 시그널·태그가 매수 심볼로 기록됨
    assert pair["symbol"] == "Q520100"


# ──────────────────────────────────────────────
# ⑥ position_integrity — buy0/sell614 유령 제거 + 중복매도 가드
# ──────────────────────────────────────────────

def test_integrity_ghost_negative_position_disappears(etn_split_db, monkeypatch):
    import backend.services.engine.position_integrity as pi

    monkeypatch.setattr(pi, "get_connection", lambda: _Conn(etn_split_db))
    summary = pi.summarize_order_integrity("2026-06-11")

    assert summary["sell_qty_exceeds_buy_qty"] == [], "buy 0 / sell 614 유령이 없어야 한다"
    assert summary["net_negative_positions"] == []


def test_load_order_net_positions_nets_q_and_bare(etn_split_db, monkeypatch):
    import backend.services.engine.position_integrity as pi

    monkeypatch.setattr(pi, "get_connection", lambda: _Conn(etn_split_db))
    summaries = pi.load_order_net_positions("2026-06-11")

    assert len(summaries) == 1
    assert summaries[0]["buy_qty"] == 614
    assert summaries[0]["sell_qty"] == 614
    assert summaries[0]["net_qty"] == 0


def test_load_order_net_positions_candidate_filter_crosses_forms(etn_split_db, monkeypatch):
    import backend.services.engine.position_integrity as pi

    monkeypatch.setattr(pi, "get_connection", lambda: _Conn(etn_split_db))
    # 무Q 후보로 조회해도 Q-형 매수가 잡혀야 한다 (order_executor net 가드 경로)
    summaries = pi.load_order_net_positions("2026-06-11", ["520100"])
    assert len(summaries) == 1
    assert summaries[0]["net_qty"] == 0


def test_find_active_sell_order_matches_across_forms(tmp_path, monkeypatch):
    import backend.services.engine.position_integrity as pi

    db = _make_db(
        tmp_path,
        orders=[
            ("s1", "2026-06-11", "", "520100", "", "sell", "limit",
             614, 9800.0, "", "submitted", "TRAILING_STOP", "2026-06-11T13:00:00+09:00"),
        ],
    )
    monkeypatch.setattr(pi, "get_connection", lambda: _Conn(db))

    # 중복매도 가드: Q-형 심볼로 조회해도 무Q 제출 매도를 찾아야 한다
    found = pi.find_active_sell_order("2026-06-11", "Q520100")
    assert found is not None and found["id"] == "s1"
    # 무Q 조회도 동작 유지
    found = pi.find_active_sell_order("2026-06-11", "520100")
    assert found is not None and found["id"] == "s1"
    # 다른 심볼은 매칭 안 됨
    assert pi.find_active_sell_order("2026-06-11", "Q999999") is None
    # 영숫자 코드는 Q 가공 없이 정확 일치만
    assert pi.find_active_sell_order("2026-06-11", "0192S0") is None


# ──────────────────────────────────────────────
# review_audit — exit 조인 / filled buy 심볼 집합
# ──────────────────────────────────────────────

def test_exit_reason_map_joins_across_forms(etn_split_db, monkeypatch):
    import backend.services.engine.review_audit as ra

    monkeypatch.setattr(ra, "get_connection", lambda: _Conn(etn_split_db))
    monkeypatch.setattr(ra, "_table_exists", lambda _t: True)
    exit_map = ra.build_exit_reason_map("2026-06-11")

    # 매도는 '520100'으로 기록 — Q-형 시그널 심볼로도 조인돼야 학습표본이 산다
    signal = {"symbol": "Q520100", "status": "executed"}
    assert ra._fallback_exit_reason(signal, exit_map) == "trailing_stop"
    # 무Q 키도 그대로 동작
    assert exit_map.get("520100") == "trailing_stop"


def test_filled_buy_symbols_covers_both_forms(etn_split_db, monkeypatch):
    import backend.services.engine.review_audit as ra
    from backend.services.engine.symbol_norm import norm_symbol as _norm

    monkeypatch.setattr(ra, "get_connection", lambda: _Conn(etn_split_db))
    monkeypatch.setattr(ra, "_table_exists", lambda _t: True)
    filled = ra._load_filled_buy_symbols("2026-06-11")

    # 매수는 'Q520100'으로 기록 — 시그널이 어느 형이든 membership이 성립해야 한다
    assert "Q520100" in filled
    assert _norm("520100") in filled


# ──────────────────────────────────────────────
# decision_engine — KIS 잔고(무Q) ↔ 메모리 포지션(Q-형) 동기화
# ──────────────────────────────────────────────

class _FakePositionManager:
    def __init__(self, positions):
        self._positions = positions
        self.removed = []
        self.qty_updates = []
        self.imported = []

    def get_positions(self):
        return [dict(p) for p in self._positions]

    def remove_position(self, symbol):
        self.removed.append(symbol)

    def update_position_quantity(self, symbol, qty):
        self.qty_updates.append((symbol, qty))
        return True

    def sync_account_position(self, **kwargs):
        self.imported.append(kwargs)
        return True


def test_sync_managed_positions_matches_kis_bare_to_q_form(monkeypatch):
    import backend.services.engine.decision_engine as de
    import backend.services.engine.position_manager as pm_module

    fake_pm = _FakePositionManager([{"symbol": "Q520100", "qty": 614}])
    monkeypatch.setattr(pm_module, "position_manager", fake_pm)
    monkeypatch.setattr(de, "_has_recent_submitted_buy", lambda *_a, **_k: False)

    # KIS 잔고는 무Q '520100'으로 옴 — Q-형 메모리 포지션과 매칭돼야 한다
    account_positions = [{"symbol": "520100", "name": "메리츠 KIS CD금리", "qty": "614", "avg_price": "9750"}]
    de._sync_managed_positions_with_account(account_positions)

    assert fake_pm.removed == [], "KIS에 (무Q로) 존재하는 포지션이 제거되면 안 된다"
    # 수량 동기화는 메모리 원본 심볼(Q-형)로 호출
    assert fake_pm.qty_updates == [("Q520100", 614)]
    # 동일 보유를 KIS-only로 오인해 중복 import하면 안 된다
    assert fake_pm.imported == []
