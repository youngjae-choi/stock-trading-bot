import backend.services.engine.momentum_scanner as ms


def test_note_exit_sets_cooldown(monkeypatch):
    ms._recent_exit_at.clear()
    monkeypatch.setattr(ms, "_now_ts", lambda: 1000.0)
    ms.note_exit("457370")
    assert ms._in_cooldown("457370") is True
    monkeypatch.setattr(ms, "_now_ts", lambda: 1000.0 + 11 * 60)  # > _COOLDOWN_MIN(10)
    assert ms._in_cooldown("457370") is False
