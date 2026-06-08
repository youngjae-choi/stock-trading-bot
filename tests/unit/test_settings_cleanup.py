"""Dead 설정 정리 회귀 테스트.

감사 결과 live get_setting 읽기가 0인(dead) 설정 키들이 시드되지 않음을 보장하고,
계속 사용 중인(kept) 키들은 여전히 시드됨을 확인한다. 또한 dead 탐색 분기가 제거된
select_sizing_params 의 반환 계약((None, max_positions))을 고정한다.
"""

from backend.config import settings
from backend.services import db as db_mod
from backend.services.engine.exploration_gate import select_sizing_params
from backend.services.settings_store import get_setting

# live 읽기가 0이고 S10 TUNABLE_SETTINGS 에도 없는 dead 키들 — 시드되면 안 됨
REMOVED_KEYS = [
    "engine.max_positions",
    "engine.s4_hybrid_screening_threshold",
    "screening.s4_hybrid_threshold",
    "engine.stop_loss",
    "override_take_profit_rate",
    "exploration.budget_rate",
    "exploration.max_positions",
]


def test_removed_keys_are_not_seeded(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "APP_DB_PATH", str(tmp_path / "s.sqlite3"))
    db_mod.initialize_database()
    for key in REMOVED_KEYS:
        assert get_setting(key, None) is None, f"{key} 가 여전히 시드됨"


def test_kept_keys_still_seeded(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "APP_DB_PATH", str(tmp_path / "s.sqlite3"))
    db_mod.initialize_database()
    assert get_setting("risk.max_positions", None) is not None
    assert get_setting("exploration.deploy_target_rate", None) is not None


def test_select_sizing_params_returns_existing_max():
    assert select_sizing_params({"max_positions": 5}) == (None, 5)


def test_select_sizing_params_defaults_max_to_7():
    assert select_sizing_params({}) == (None, 7)
