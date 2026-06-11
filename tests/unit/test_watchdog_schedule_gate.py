"""OpsWatchdog 체크 게이트의 스케줄 설정 연동 (2026-06-11).

배경: S1~S5 실행시간이 09:01/09:05로 이동(6/10)했는데 와치독 게이트가 구 스케줄
하드코딩(08:35 등)이라 매일 08:35~09:01에 s2_premarket 허위 anomaly가 발생했다.
수정: 게이트 시작 시각을 schedule_*_time 설정 + grace로 동적 산출한다.
"""

import backend.services.engine.ops_watchdog as ow


def test_gate_follows_s2_schedule_setting(monkeypatch):
    monkeypatch.setattr(ow, "get_setting", lambda k, d=None: "09:01" if k == "schedule_s2_time" else d)
    # 09:01 + grace 10분 = 09:11 → 551분
    assert ow._gate_min_from_schedule("schedule_s2_time", default_min=8 * 60 + 35, grace_min=10) == 9 * 60 + 11


def test_gate_falls_back_to_default_when_setting_missing(monkeypatch):
    monkeypatch.setattr(ow, "get_setting", lambda k, d=None: d)
    assert ow._gate_min_from_schedule("schedule_s2_time", default_min=8 * 60 + 35, grace_min=10) == 8 * 60 + 35


def test_gate_falls_back_on_bad_value(monkeypatch):
    monkeypatch.setattr(ow, "get_setting", lambda k, d=None: "실시간")
    assert ow._gate_min_from_schedule("schedule_s2_time", default_min=500, grace_min=10) == 500


def test_registry_resolves_callable_start(monkeypatch):
    # callable start_min이 게이트 판정에 사용되는지: 현재 시각 09:05, 게이트 09:11 → 미적용(스킵)
    monkeypatch.setattr(ow, "get_setting", lambda k, d=None: "09:01" if k == "schedule_s2_time" else d)
    c = next(c for c in ow._REGISTRY if c.id == "s2_premarket")
    start = c.start_min() if callable(c.start_min) else c.start_min
    assert start == 9 * 60 + 11
