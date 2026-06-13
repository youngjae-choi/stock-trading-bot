"""장중 유입 종목 Risk Profile 휴리스틱 배정 + intraday_plan_events 이력 테스트.

DB는 tmp_path sqlite + monkeypatch(get_connection)로 격리한다 (라이브 DB 접근 금지).
"""

import json
import sqlite3

import backend.services.engine.intraday_profile as ip
import backend.services.engine.rule_cache as rc


# ---------------------------------------------------------------------------
# classify_profile 휴리스틱
# ---------------------------------------------------------------------------

def test_leverage_etf_is_high_vol():
    cand = {"symbol": "122630", "name": "KODEX 레버리지", "change_rate": 3.0, "volume_surge": 50}
    profile, reason = ip.classify_profile(cand, "risk_on")
    assert profile == "HIGH_VOL"
    assert "파생" in reason


def test_inverse_and_2x_keywords_are_high_vol():
    assert ip.classify_profile({"name": "KODEX 인버스"}, None)[0] == "HIGH_VOL"
    assert ip.classify_profile({"name": "TIGER 2X 미국나스닥"}, None)[0] == "HIGH_VOL"


def test_surge_13pct_is_theme_spike():
    cand = {"symbol": "001234", "name": "어떤제약", "change_rate": 13.0, "volume_surge": 100}
    profile, reason = ip.classify_profile(cand, "neutral")
    assert profile == "THEME_SPIKE"
    assert "급등" in reason or "과열" in reason


def test_volume_surge_500_is_theme_spike():
    cand = {"symbol": "001234", "name": "어떤전자", "change_rate": 2.0, "volume_surge": 612}
    assert ip.classify_profile(cand, None)[0] == "THEME_SPIKE"


def test_bond_mixed_keywords_are_low_vol():
    cand = {"symbol": "273130", "name": "KODEX 종합채권(AA-이상)액티브", "change_rate": 0.3, "volume_surge": 10}
    assert ip.classify_profile(cand, "risk_on")[0] == "LOW_VOL"
    assert ip.classify_profile({"name": "TIGER 배당성장"}, None)[0] == "LOW_VOL"
    assert ip.classify_profile({"name": "KBSTAR 채권혼합"}, None)[0] == "LOW_VOL"


def test_default_is_mid_vol():
    cand = {"symbol": "005930", "name": "삼성전자", "change_rate": 4.0, "volume_surge": 120}
    profile, reason = ip.classify_profile(cand, "neutral")
    assert profile == "MID_VOL"
    assert reason  # 사유 문자열 존재


def test_risk_off_relaxes_spike_threshold_to_8pct():
    cand = {"symbol": "001234", "name": "어떤소재", "change_rate": 9.0, "volume_surge": 100}
    # neutral 레짐에서는 12% 미만이라 MID_VOL
    assert ip.classify_profile(cand, "neutral")[0] == "MID_VOL"
    # risk_off에서는 8% 이상이면 THEME_SPIKE (보수화 — 더 작은 사이징 5%)
    profile, reason = ip.classify_profile(cand, "risk_off")
    assert profile == "THEME_SPIKE"
    assert "risk_off" in reason  # 레짐 반영 여부 명시


def test_reason_mentions_regime():
    _, reason = ip.classify_profile({"name": "삼성전자"}, "volatile")
    assert "volatile" in reason


# ---------------------------------------------------------------------------
# rule_cache 주입 — plan 배정 종목은 절대 덮어쓰지 않음
# ---------------------------------------------------------------------------

def _patch_rule_layers(monkeypatch, plan):
    import backend.services.engine.rule_resolver as rr
    monkeypatch.setattr(rc, "get_active_base_rulepack", lambda: {"id": "base-v1.0"})
    monkeypatch.setattr(
        rc, "get_active_profile_pack",
        lambda: {"id": "profile-v1.0", "profiles": {
            "LOW_VOL": {"max_position_rate": 0.15},
            "MID_VOL": {"max_position_rate": 0.12},
            "HIGH_VOL": {"max_position_rate": 0.08},
            "THEME_SPIKE": {"max_position_rate": 0.05},
        }},
    )
    monkeypatch.setattr(rc, "get_active_daily_plan", lambda d: plan)
    monkeypatch.setattr(rc, "get_symbol_overrides", lambda: {})
    monkeypatch.setattr(rc, "get_setting", lambda k, d=None: d)
    monkeypatch.setattr(rr, "_get_active_rulepack_entry_rules", lambda d: {})


def test_plan_assigned_symbol_not_overwritten(monkeypatch):
    plan = {
        "id": "plan-1",
        "symbol_assignments": [{"code": "005930", "profile": "LOW_VOL", "reason": "S5 배정"}],
        "daily_overrides": {},
    }
    _patch_rule_layers(monkeypatch, plan)
    rc.clear_cache()

    # 장중 유입 분류가 plan 배정 종목/신규 종목 모두에 등록 시도됨
    rc.set_intraday_profile("005930", "THEME_SPIKE", "급등")     # plan 배정 → 적용 금지
    rc.set_intraday_profile("123456", "HIGH_VOL", "파생형 ETF")  # 신규 → 적용

    rc.load_daily_rules("2099-06-10", ["005930", "123456"])
    assert rc.get_rule("005930")["profile_assigned"] == "LOW_VOL"   # plan 우선
    assert rc.get_rule("123456")["profile_assigned"] == "HIGH_VOL"  # 휴리스틱 주입
    assert rc.get_rule("123456")["assignment_reason"] == "파생형 ETF"
    # 사이징 파라미터도 프로파일 레이어에서 반영
    assert rc.get_rule("123456")["max_position_rate"] == 0.08

    # 로드 후에는 plan 배정 종목 등록 자체가 거부된다
    assert rc.set_intraday_profile("005930", "HIGH_VOL", "x") is False
    assert rc.set_intraday_profile("654321", "MID_VOL", "기본") is True
    rc.clear_cache()


def test_intraday_profile_survives_reload(monkeypatch):
    """모멘텀 추가마다 load_daily_rules가 재호출돼도 주입 프로파일이 유지된다."""
    _patch_rule_layers(monkeypatch, None)
    rc.clear_cache()
    rc.set_intraday_profile("111111", "THEME_SPIKE", "급등/테마 과열")
    rc.load_daily_rules("2099-06-10", ["111111"])
    rc.load_daily_rules("2099-06-10", ["111111", "222222"])  # 재로드
    assert rc.get_rule("111111")["profile_assigned"] == "THEME_SPIKE"
    assert rc.get_rule("222222")["profile_assigned"] == "MID_VOL"  # 기본값
    rc.clear_cache()


# ---------------------------------------------------------------------------
# intraday_plan_events 이력 기록
# ---------------------------------------------------------------------------

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

    monkeypatch.setattr(ip, "get_connection", lambda: _Conn())
    return db


def test_record_event_row_shape(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    symbols = [
        {"symbol": "122630", "name": "KODEX 레버리지", "profile": "HIGH_VOL", "reason": "파생형 ETF/ETN"},
        {"symbol": "001234", "name": "어떤제약", "profile": "THEME_SPIKE", "reason": "급등/테마 과열"},
    ]
    ok = ip.record_intraday_event(
        trigger="momentum_scan",
        regime="risk_off",
        market_tone="negative",
        symbols_added=symbols,
        trade_date="2099-06-10",
    )
    assert ok is True

    rows = ip.fetch_intraday_events("2099-06-10")
    assert len(rows) == 1
    row = rows[0]
    assert row["trade_date"] == "2099-06-10"
    assert row["trigger"] == "momentum_scan"
    assert row["regime"] == "risk_off"
    assert row["market_tone"] == "negative"
    assert row["event_time"]
    assert row["created_at"]
    assert row["symbols_added"] == symbols  # JSON round-trip


def test_record_event_skips_empty_symbols(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    assert ip.record_intraday_event(
        trigger="intraday_refresh", regime=None, market_tone=None, symbols_added=[],
        trade_date="2099-06-11",
    ) is False
    assert ip.fetch_intraday_events("2099-06-11") == []


# ---------------------------------------------------------------------------
# 배선 — add_momentum_candidates / API
# ---------------------------------------------------------------------------

def test_add_momentum_candidates_assigns_profile_and_records_event(monkeypatch):
    import asyncio
    import backend.services.engine.decision_engine as de

    eng = de.decision_engine
    eng._candidates = {}
    monkeypatch.setattr(de, "load_daily_rules", lambda today, syms: len(syms))
    monkeypatch.setattr(de.position_manager, "get_positions", lambda: [])
    monkeypatch.setattr(de, "get_setting", lambda k, d=None: d, raising=False)

    async def fake_start(symbols):
        pass

    monkeypatch.setattr(de.realtime_ws_manager, "start", fake_start)
    monkeypatch.setattr(eng, "_current_regime", lambda: "risk_off")
    monkeypatch.setattr(
        eng, "_build_market_context",
        lambda today: {"regime": "risk_off", "market_tone": "negative"},
    )

    stored: dict[str, tuple] = {}
    monkeypatch.setattr(de, "set_intraday_profile", lambda s, p, r: stored.setdefault(s, (p, r)) is None or True)
    recorded: list[dict] = []
    monkeypatch.setattr(
        de, "record_intraday_event",
        lambda **kw: recorded.append(kw) or True,
    )

    new = [
        {"symbol": "122630", "name": "KODEX 레버리지", "change_rate": 2.0, "volume_surge": 10},
        {"symbol": "001234", "name": "어떤소재", "change_rate": 9.0, "volume_surge": 10},
    ]
    out = asyncio.run(eng.add_momentum_candidates(new))
    assert out["added"] == 2
    assert stored["122630"][0] == "HIGH_VOL"
    assert stored["001234"][0] == "THEME_SPIKE"  # risk_off 완화 임계(≥8%)
    assert len(recorded) == 1
    ev = recorded[0]
    assert ev["trigger"] == "momentum_scan"
    assert ev["regime"] == "risk_off"
    assert ev["market_tone"] == "negative"
    assert {s["symbol"] for s in ev["symbols_added"]} == {"122630", "001234"}
    for item in ev["symbols_added"]:
        assert set(["symbol", "name", "profile", "reason"]).issubset(item.keys())
    eng._candidates = {}


def test_intraday_events_api_contract(monkeypatch):
    from fastapi.testclient import TestClient
    import backend.main as main_mod
    import backend.api.routes.daily_plan as dp

    monkeypatch.setattr(
        dp, "fetch_intraday_events",
        lambda date: [{
            "id": 1, "trade_date": date, "event_time": "2099-06-10T10:03:00+09:00",
            "trigger": "momentum_scan", "regime": "neutral", "market_tone": "neutral",
            "symbols_added": [{"symbol": "001234", "name": "어떤전자",
                               "profile": "THEME_SPIKE", "reason": "급등/테마 과열"}],
            "created_at": "2099-06-10T10:03:00+09:00",
        }],
    )
    client = TestClient(main_mod.app)
    r = client.get("/api/v1/daily-plan/intraday-events", params={"date": "2099-06-10"})
    assert r.status_code == 200
    body = r.json()
    assert body["date"] == "2099-06-10"
    assert body["count"] == 1
    assert body["events"][0]["trigger"] == "momentum_scan"
    assert body["events"][0]["symbols_added"][0]["profile"] == "THEME_SPIKE"

    # date 필수 + 형식 검증
    assert client.get("/api/v1/daily-plan/intraday-events").status_code == 422
    assert client.get("/api/v1/daily-plan/intraday-events", params={"date": "bad"}).status_code == 400


def test_record_event_is_best_effort(monkeypatch):
    def _boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(ip, "get_connection", _boom)
    ok = ip.record_intraday_event(
        trigger="momentum_scan", regime="neutral", market_tone="neutral",
        symbols_added=[{"symbol": "000001", "name": "x", "profile": "MID_VOL", "reason": "기본"}],
        trade_date="2099-06-12",
    )
    assert ok is False  # 예외 전파 없이 False
