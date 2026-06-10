"""trade_entry_tags outcome EOD 백필 — EV 가지치기 표본 0 버그 수정 (2026-06-10).

배경: set_outcome(order_id 기반)은 호출처가 없고 태그는 order_id=''로 기록돼
outcome_json이 영원히 '{}' — EV 가지치기 표본이 항상 0이었다(학습 루프 무입력).
수정: EOD에 매도완료 trade pair를 symbol+trade_date로 태그에 백필한다.
매수가 실행되지 않은 심볼(차단/관찰 태그)은 정산하지 않고 그대로 둔다.
"""

import json
import sqlite3

import backend.services.engine.trade_tagging as tt


def _setup_db(tmp_path, monkeypatch):
    db = tmp_path / "t.sqlite3"

    class _Conn:
        def __enter__(self):
            self._c = sqlite3.connect(db)
            self._c.row_factory = sqlite3.Row
            return self._c

        def __exit__(self, *a):
            self._c.commit()
            self._c.close()

    monkeypatch.setattr(tt, "get_connection", lambda: _Conn())
    return db


def _insert_tag(symbol, trade_date="2026-06-10", outcome="{}"):
    with tt.get_connection() as conn:
        conn.execute(
            """INSERT INTO trade_entry_tags
               (id, order_id, symbol, trade_date, selection_reason_json, fired_groups_json,
                condition_states_json, market_context_json, outcome_json, created_at)
               VALUES (?, '', ?, ?, '{}', '[]', '{}', '{}', ?, 't')""",
            (f"tag-{symbol}-{trade_date}", symbol, trade_date, outcome),
        )


def test_backfill_settles_completed_pairs(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    tt._ensure_table()
    _insert_tag("000430")          # 매도완료 → 정산 대상
    _insert_tag("018000")          # 매수 없음(차단 태그) → 미정산 유지

    pairs = [
        {"symbol": "000430", "trade_date": "2026-06-10", "status": "매도완료",
         "pnl_amount": -198510.0, "pnl_pct": -1.61},
        {"symbol": "999999", "trade_date": "2026-06-10", "status": "보유중",
         "pnl_amount": None, "pnl_pct": None},
    ]
    updated = tt.backfill_outcomes_for_date(
        "2026-06-10", pairs=pairs, exit_map={"000430": "initial_stop_loss"}
    )
    assert updated == 1

    with tt.get_connection() as conn:
        rows = {
            r["symbol"]: json.loads(r["outcome_json"])
            for r in conn.execute("SELECT symbol, outcome_json FROM trade_entry_tags")
        }
    assert rows["000430"]["realized_pnl"] == -198510.0
    assert rows["000430"]["win"] is False
    assert rows["000430"]["exit_reason"] == "initial_stop_loss"
    assert rows["018000"] == {}  # 미매수 태그는 그대로


def test_backfill_does_not_overwrite_existing_outcome(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    tt._ensure_table()
    _insert_tag("084650", outcome=json.dumps({"realized_pnl": 1.0, "win": True}))
    pairs = [{"symbol": "084650", "trade_date": "2026-06-10", "status": "매도완료",
              "pnl_amount": -5.0, "pnl_pct": -0.1}]
    updated = tt.backfill_outcomes_for_date("2026-06-10", pairs=pairs, exit_map={})
    assert updated == 0
    with tt.get_connection() as conn:
        row = conn.execute(
            "SELECT outcome_json FROM trade_entry_tags WHERE symbol='084650'"
        ).fetchone()
    assert json.loads(row["outcome_json"])["realized_pnl"] == 1.0
