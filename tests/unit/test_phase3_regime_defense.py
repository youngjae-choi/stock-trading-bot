"""Phase 3 — 레짐 심화 + 폭락장 방어 회귀 테스트.

  P3-1 kospi_change_pct 공란 주입 수정 (RulePack 프롬프트 명시)
  P3-2 new_entry_allowed 강제 (게이트 + preflight 백스톱)
  P3-3 flash crash 감지 — 방어 모드 활성화 + 디바운스 우회
  P3-4 방어 레짐 스케일아웃 오버라이드 (빨리·많이 수확)
  P3-5 인버스 1x 플레이북 (방어 모드에서 하락 수익 경로)
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from backend.config import settings

_KST = ZoneInfo("Asia/Seoul")


def _today() -> str:
    return datetime.now(_KST).strftime("%Y-%m-%d")


# ──────────────────────────────────────────────
# P3-5: 인버스 1x 판정
# ──────────────────────────────────────────────

def test_inverse_1x_detection():
    from backend.services.engine.intraday_profile import is_inverse_1x_product
    assert is_inverse_1x_product("KODEX 인버스") is True
    assert is_inverse_1x_product("TIGER 인버스") is True
    assert is_inverse_1x_product("KODEX 200선물인버스2X") is False
    assert is_inverse_1x_product("KODEX 레버리지") is False
    assert is_inverse_1x_product("삼성전자") is False
    assert is_inverse_1x_product("") is False


# ──────────────────────────────────────────────
# P3-3: flash crash 감지·방어 모드
# ──────────────────────────────────────────────

def _fc_settings(enabled=True, threshold=-2.0):
    return {
        "risk.flash_crash_defense_enabled": enabled,
        "risk.flash_crash_threshold_pct": threshold,
    }


def test_flash_crash_detected_thresholds(monkeypatch):
    import backend.services.settings_store as ss
    import backend.services.engine.intraday_regime_monitor as irm
    monkeypatch.setattr(ss, "get_setting", lambda k, d=None: _fc_settings().get(k, d))
    assert irm._flash_crash_detected(-2.5, 20.0) is True    # KOSPI 급락
    assert irm._flash_crash_detected(-2.0, 20.0) is True    # 경계 포함
    assert irm._flash_crash_detected(-1.0, 20.0) is False
    assert irm._flash_crash_detected(-1.0, 36.0) is True    # VIX 급등
    assert irm._flash_crash_detected(None, None) is False


def test_flash_crash_disabled(monkeypatch):
    import backend.services.settings_store as ss
    import backend.services.engine.intraday_regime_monitor as irm
    monkeypatch.setattr(ss, "get_setting", lambda k, d=None: _fc_settings(enabled=False).get(k, d))
    assert irm._flash_crash_detected(-5.0, 40.0) is False


def test_defense_activation_and_date_scope():
    """활성화 → 오늘 활성. 날짜가 다르면(어제 발동) 비활성 — 다음 거래일 자동 해제."""
    with tempfile.TemporaryDirectory() as tmp_dir, \
         patch.object(settings, "APP_DB_PATH", tmp_dir + "/t.sqlite3"):
        from backend.services.db import initialize_database
        initialize_database()
        import backend.services.engine.intraday_regime_monitor as irm

        assert irm.is_flash_crash_defense_active() is False
        irm._activate_flash_crash_defense(_today(), -2.5, 33.0)
        assert irm.is_flash_crash_defense_active() is True
        # 활성 플래그가 남아 있어도 날짜가 다르면 비활성
        assert irm.is_flash_crash_defense_active(trade_date="2020-01-01") is False
        # 중복 활성화는 no-op (예외 없이 통과)
        irm._activate_flash_crash_defense(_today(), -2.5, 33.0)
        assert irm.is_flash_crash_defense_active() is True


def test_flash_crash_bypasses_debounce(monkeypatch):
    """급락 감지 시 25분 디바운스를 우회해 즉시 레짐 전환한다."""
    import backend.services.engine.intraday_regime_monitor as irm
    monkeypatch.setattr(irm, "get_today_application",
                        lambda d: {"set_id": "s1", "set_name": "aggr", "regime_label": "neutral"})
    monkeypatch.setattr(irm, "_should_skip_transition", lambda d: True)  # 디바운스 활성 상태
    monkeypatch.setattr(irm, "_get_index_board_vix", lambda d: 33.0)
    monkeypatch.setattr(irm, "_get_morning_vix", lambda d: 20.0)
    monkeypatch.setattr(irm, "_get_current_kospi_change", lambda: -2.5)
    monkeypatch.setattr(irm, "_get_index_board_regime", lambda d: "risk_off")
    monkeypatch.setattr(irm, "_flash_crash_detected", lambda k, v: True)
    activated = []
    monkeypatch.setattr(irm, "_activate_flash_crash_defense", lambda d, k, v: activated.append((d, k, v)))
    monkeypatch.setattr(irm, "get_match_preview", lambda *a, **k: {"set_id": "s2", "set_name": "defensive"})
    monkeypatch.setattr(irm, "record_application", lambda **k: None)
    monkeypatch.setattr(irm, "_insert_transition_alert", lambda **k: None)

    result = asyncio.run(irm.check_intraday_regime("test"))
    assert result["action"] == "switched"       # 디바운스에 막히지 않음
    assert activated                            # 방어 모드 활성화 호출됨


def test_no_flash_crash_respects_debounce(monkeypatch):
    """급락이 아니면 기존 디바운스 동작 보존."""
    import backend.services.engine.intraday_regime_monitor as irm
    monkeypatch.setattr(irm, "get_today_application",
                        lambda d: {"set_id": "s1", "set_name": "aggr", "regime_label": "neutral"})
    monkeypatch.setattr(irm, "_should_skip_transition", lambda d: True)
    monkeypatch.setattr(irm, "_get_index_board_vix", lambda d: 15.0)
    monkeypatch.setattr(irm, "_get_morning_vix", lambda d: 15.0)
    monkeypatch.setattr(irm, "_get_current_kospi_change", lambda: 0.3)
    monkeypatch.setattr(irm, "_flash_crash_detected", lambda k, v: False)
    result = asyncio.run(irm.check_intraday_regime("test"))
    assert result["action"] == "skipped" and result["reason"] == "min_interval"


# ──────────────────────────────────────────────
# P3-2/P3-5: 게이트·preflight 차단
# ──────────────────────────────────────────────

def test_gate_blocks_regular_symbol_in_defense_mode(monkeypatch):
    """방어 모드에서 일반 종목 차단, 인버스 1x는 플레이북으로 통과."""
    import backend.services.engine.decision_engine as de
    import backend.services.engine.intraday_regime_monitor as irm
    import backend.services.engine.confidence_calibration as cc
    import backend.services.engine.false_positive as fp
    import backend.services.regime_set_service as rss

    monkeypatch.setattr(de, "get_setting", lambda k, d=None: {
        "engine.crash_playbook_enabled": True,
        "engine.enforce_new_entry_allowed": True,
        "engine.calibration_gate_enabled": False,
        "engine.entry_fail_cooldown_enabled": False,
    }.get(k, d))
    monkeypatch.setattr(irm, "is_flash_crash_defense_active", lambda *a, **k: True)
    monkeypatch.setattr(rss, "get_today_application", lambda d: None)
    monkeypatch.setattr(cc, "is_confidence_blocked", lambda *a, **k: (False, ""))
    monkeypatch.setattr(fp, "recent_entry_fail_count", lambda *a, **k: 0)

    assert "flash_crash_defense" in de._entry_gate_block_reason("005930", 0.8, name="삼성전자")
    assert de._entry_gate_block_reason("114800", 0.8, name="KODEX 인버스") == ""


def test_gate_blocks_inverse_when_playbook_disabled(monkeypatch):
    """플레이북 OFF면 방어 모드에서 인버스 1x도 차단(전면 차단)."""
    import backend.services.engine.decision_engine as de
    import backend.services.engine.intraday_regime_monitor as irm
    monkeypatch.setattr(de, "get_setting", lambda k, d=None: {
        "engine.crash_playbook_enabled": False,
        "engine.enforce_new_entry_allowed": False,
        "engine.calibration_gate_enabled": False,
        "engine.entry_fail_cooldown_enabled": False,
    }.get(k, d))
    monkeypatch.setattr(irm, "is_flash_crash_defense_active", lambda *a, **k: True)
    assert "flash_crash_defense" in de._entry_gate_block_reason("114800", 0.8, name="KODEX 인버스")


def test_preflight_blocks_new_entry_not_allowed(monkeypatch):
    """preflight 백스톱 — 레짐 SET new_entry_allowed=False면 주문 차단."""
    with tempfile.TemporaryDirectory() as tmp_dir, \
         patch.object(settings, "APP_DB_PATH", tmp_dir + "/t.sqlite3"):
        from backend.services.db import initialize_database
        initialize_database()
        import backend.services.engine.order_preflight as pf
        import backend.services.regime_set_service as rss
        monkeypatch.setattr(
            rss, "get_today_application",
            lambda d: {"regime_label": "volatile", "applied_settings": {"new_entry_allowed": False}},
        )
        result = pf.run_preflight(
            signal={"id": "sig-1", "symbol": "005930", "name": "삼성전자", "trigger_price": 100.0},
            final_rule={},
        )
        assert result["checks"]["new_entry_allowed"] == pf.PREFLIGHT_BLOCK
        assert result["ok"] is False


def test_preflight_flash_defense_allows_inverse_1x(monkeypatch):
    """preflight — 방어 모드에서 인버스 1x는 flash_crash_defense 체크 통과."""
    with tempfile.TemporaryDirectory() as tmp_dir, \
         patch.object(settings, "APP_DB_PATH", tmp_dir + "/t.sqlite3"):
        from backend.services.db import initialize_database
        initialize_database()
        import backend.services.engine.order_preflight as pf
        import backend.services.engine.intraday_regime_monitor as irm
        import backend.services.regime_set_service as rss
        monkeypatch.setattr(irm, "is_flash_crash_defense_active", lambda *a, **k: True)
        monkeypatch.setattr(rss, "get_today_application", lambda d: None)

        blocked = pf.run_preflight(
            signal={"id": "sig-2", "symbol": "005930", "name": "삼성전자", "trigger_price": 100.0},
            final_rule={},
        )
        assert blocked["checks"]["flash_crash_defense"] == pf.PREFLIGHT_BLOCK

        allowed = pf.run_preflight(
            signal={"id": "sig-3", "symbol": "114800", "name": "KODEX 인버스", "trigger_price": 100.0},
            final_rule={},
        )
        assert allowed["checks"]["flash_crash_defense"] == pf.PREFLIGHT_OK


# ──────────────────────────────────────────────
# P3-4: 방어 레짐 스케일아웃 오버라이드
# ──────────────────────────────────────────────

def _reset_scaleout_cache():
    import backend.services.engine.position_manager as pm
    pm._SCALEOUT_OVERRIDE_CACHE["at"] = 0.0
    pm._SCALEOUT_OVERRIDE_CACHE["value"] = None


def test_regime_scaleout_overrides_defaults(monkeypatch):
    import backend.services.engine.position_manager as pm
    import backend.services.regime_set_service as rss

    cases = [
        ("risk_off", {}, (0.015, 0.8)),
        ("volatile", {}, (0.012, 1.0)),
        ("neutral", {}, None),
        ("risk_on", {}, None),
        # SET에 명시값 있으면 그것 우선
        ("risk_off", {"scaleout_target_rate": 0.01, "scaleout_ratio": 0.9}, (0.01, 0.9)),
    ]
    for label, extra, expected in cases:
        _reset_scaleout_cache()
        monkeypatch.setattr(
            rss, "get_today_application",
            lambda d, _l=label, _e=extra: {"regime_label": _l, "applied_settings": dict(_e)},
        )
        assert pm._regime_scaleout_overrides() == expected, label


def test_regime_scaleout_override_fail_open(monkeypatch):
    import backend.services.engine.position_manager as pm
    import backend.services.regime_set_service as rss

    def _boom(d):
        raise RuntimeError("db down")

    _reset_scaleout_cache()
    monkeypatch.setattr(rss, "get_today_application", _boom)
    assert pm._regime_scaleout_overrides() is None


def test_scaleout_uses_defensive_override():
    """risk_off 오버라이드(0.015/0.8) — +1.6%에서 80주 확정, 잔량 20주 러너."""
    import backend.services.engine.position_manager as pmod
    from backend.services.engine.position_manager import PositionManager

    pos = {
        "position_id": "005930-t", "symbol": "005930", "name": "삼성전자",
        "qty": 100, "entry_price": 100.0, "entry_time": "", "entry_ts": 0.0,
        "profile_assigned": "MID_VOL", "auto_imported": False,
        "initial_stop_price": 97.0, "active_stop_price": 97.0,
        "highest_price_since_entry": 100.0, "trough_price": 100.0,
        "trailing_active": False, "trailing_stop_price": 97.0,
        "trailing_activate_profit": 0.025, "trailing_stop_rate": 0.03,
        "max_holding_minutes": 180, "force_exit_time": "15:20:00", "harvested": False,
    }
    mgr = PositionManager()
    mgr._positions["005930"] = pos
    sell = AsyncMock(return_value={"ok": True, "symbol": "005930"})
    base_settings = {
        "engine.harvest_mode": True,
        "engine.scaleout_ratio": 0.6,
        "engine.scaleout_target_rate": 0.02,
    }
    with patch("backend.services.engine.position_manager.get_setting",
               side_effect=lambda k, d=None: base_settings.get(k, d)), \
         patch("backend.services.engine.position_manager._upsert_stop_state"), \
         patch("backend.services.engine.position_manager._regime_scaleout_overrides",
               return_value=(0.015, 0.8)), \
         patch.object(PositionManager, "_account_daily_target_reached", new=AsyncMock(return_value=False)), \
         patch("backend.services.engine.order_executor.order_executor.execute_sell", sell):
        # 전역 설정(+2%)으로는 미달이지만 오버라이드(+1.5%)로는 도달하는 가격
        asyncio.run(mgr._scaleout_check(pos, 101.6))
    sell.assert_awaited_once()
    assert sell.call_args.kwargs["qty"] == 80
    assert pos["qty"] == 20
    assert pmod is not None


# ──────────────────────────────────────────────
# P3-1: KOSPI 등락률 프롬프트 주입
# ──────────────────────────────────────────────

def test_kospi_line_from_morning_context():
    from backend.services.engine.rulepack_generation import _kospi_change_line
    line = _kospi_change_line({"kospi": {"price": 2500.5, "change_pct": -2.15}})
    assert "KOSPI" in line and "-2.15%" in line


def test_kospi_line_falls_back_to_realtime(monkeypatch):
    import backend.services.engine.intraday_regime_monitor as irm
    monkeypatch.setattr(irm, "_get_current_kospi_change", lambda: -1.8)
    from backend.services.engine.rulepack_generation import _kospi_change_line
    line = _kospi_change_line({})
    assert "-1.80%" in line and "실시간" in line


def test_kospi_line_explicit_na(monkeypatch):
    import backend.services.engine.intraday_regime_monitor as irm
    monkeypatch.setattr(irm, "_get_current_kospi_change", lambda: None)
    from backend.services.engine.rulepack_generation import _kospi_change_line
    line = _kospi_change_line({})
    assert "N/A" in line  # 빈 문자열 금지 — 명시적 N/A


def test_morning_context_prompt_includes_kospi(monkeypatch):
    import backend.services.engine.intraday_regime_monitor as irm
    monkeypatch.setattr(irm, "_get_current_kospi_change", lambda: None)
    from backend.services.engine.rulepack_generation import _format_morning_context_for_prompt
    text = _format_morning_context_for_prompt({"regime": "risk_off", "market_data": {}})
    assert "KOSPI" in text  # 프롬프트에 KOSPI 라인이 항상 존재
