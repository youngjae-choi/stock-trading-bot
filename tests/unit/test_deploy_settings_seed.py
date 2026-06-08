from backend.config import settings
from backend.services import db as db_mod
from backend.services.settings_store import get_setting


def test_new_settings_seeded(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "APP_DB_PATH", str(tmp_path / "s.sqlite3"))
    db_mod.initialize_database()
    assert float(get_setting("exploration.deploy_target_rate", 0)) == 0.95
    assert int(get_setting("intraday_refresh.max_replacement_per_day", 0)) == 20
    assert int(get_setting("intraday_refresh.replacement_cooldown_min", 0)) == 30
    assert get_setting("intraday_refresh.replacement_execute_enabled", None) is True
