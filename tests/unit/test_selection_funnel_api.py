"""GET /api/v1/funnel/selection — 단계별 선정 퍼널 API 테스트.

운영 DB 미접촉: settings.APP_DB_PATH를 임시 파일로 monkeypatch.
인증 의존성은 dependency_overrides로 우회.
"""

import json

from fastapi.testclient import TestClient

import backend.main as main_mod
from backend.api.dependencies import require_console_user
from backend.config import settings
from backend.services import db as db_mod

client = TestClient(main_mod.app)


def _isolated_db(tmp_path, monkeypatch):
    p = tmp_path / "funnel_test.sqlite3"
    monkeypatch.setattr(settings, "APP_DB_PATH", str(p))
    db_mod.initialize_database()
    main_mod.app.dependency_overrides[require_console_user] = lambda: {"user": "test"}


def _teardown():
    main_mod.app.dependency_overrides.pop(require_console_user, None)


def test_selection_funnel_maps_stages(tmp_path, monkeypatch):
    _isolated_db(tmp_path, monkeypatch)
    try:
        with db_mod.get_connection() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS universe_filter_results ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT, trade_date TEXT, items TEXT,"
                " raw_count INTEGER, filtered_count INTEGER, created_at TEXT)"
            )
            conn.execute(
                "INSERT INTO universe_filter_results(trade_date, items, raw_count, filtered_count, created_at)"
                " VALUES(?,?,?,?,?)",
                (
                    "2026-06-07",
                    json.dumps([
                        {"symbol": "388790", "name": "라이콤", "score": 0.81, "rank": 1, "change_rate": 20.4},
                        {"symbol": "126730", "name": "코칩", "score": 0.77, "rank": 2, "change_rate": 2.6},
                    ]),
                    89,
                    2,
                    "2026-06-07T09:01:00",
                ),
            )

        r = client.get("/api/v1/funnel/selection?trade_date=2026-06-07")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        stages = body["payload"]["stages"]
        assert [s["id"] for s in stages] == ["raw", "s3", "s4", "s5"]

        raw, s3, s4, s5 = stages
        assert raw["passed_count"] == 89
        # S3 통과 매핑
        assert s3["passed_count"] == 2
        assert s3["passed"][0]["symbol"] == "388790"
        assert s3["passed"][0]["name"] == "라이콤"
        assert s3["passed"][0]["score"] == 0.81
        # 데이터 없는 단계는 graceful 빈 배열
        assert s4["passed_count"] == 0 and s4["passed"] == []
        assert s5["dropped_count"] == 0 and s5["dropped"] == []
    finally:
        _teardown()


def test_selection_funnel_empty_day_is_graceful(tmp_path, monkeypatch):
    _isolated_db(tmp_path, monkeypatch)
    try:
        r = client.get("/api/v1/funnel/selection?trade_date=2099-01-01")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        stages = body["payload"]["stages"]
        assert len(stages) == 4
        assert all(s.get("passed_count", 0) == 0 for s in stages)
    finally:
        _teardown()
