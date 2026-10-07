"""외부 리서치 보관소(external_strategy_research) — 스키마 생성 + 엔진 코드 미참조 보장 (2026-10-07)."""
import re
import tempfile
from pathlib import Path


def test_table_created_on_init(monkeypatch):
    from backend.config import settings as cfg
    from backend.services.db import get_connection, initialize_database

    monkeypatch.setattr(cfg, "APP_DB_PATH", tempfile.mktemp(suffix=".sqlite3"))
    initialize_database()
    with get_connection() as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(external_strategy_research)")}
    assert {"id", "source", "kind", "title", "body", "fit", "status", "created_at"} <= cols


def test_no_engine_code_reads_external_research():
    """순수 기록 테이블 — db.py 스키마 정의 외 어떤 backend 코드도 참조하면 안 된다(매매 영향 0)."""
    root = Path(__file__).resolve().parents[2] / "backend"
    hits = [str(p.relative_to(root)) for p in root.rglob("*.py")
            if re.search(r"external_strategy_research", p.read_text(encoding="utf-8")) and p.name != "db.py"]
    assert hits == []
