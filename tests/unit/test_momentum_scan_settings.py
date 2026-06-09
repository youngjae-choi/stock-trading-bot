from backend.config import settings
from backend.services import db as db_mod
from backend.services.settings_store import get_setting


def test_momentum_scan_seeds(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "APP_DB_PATH", str(tmp_path / "s.sqlite3"))
    db_mod.initialize_database()
    assert get_setting("momentum_scan.enabled", None) is True
    assert int(get_setting("momentum_scan.interval_min", 0)) == 3
    assert int(get_setting("momentum_scan.max_subscriptions", 0)) == 40
