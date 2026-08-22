"""엔진 모니터 API — 6엔진 상태를 한 번에 (콘솔 Engine Monitor 화면용).

monitor_engines.py(CLI)의 웹 버전. 각 엔진의 상태·라이브 값 + SSOT 드리프트/
conformance를 JSON으로. 읽기 전용.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter

from ...services.db import get_connection

logger = logging.getLogger("EngineMonitorAPI")
router = APIRouter(prefix="/api/v1/engine-monitor", tags=["engine-monitor"])


def _get(conn, key, default=None):
    row = conn.execute("SELECT value_json FROM system_settings WHERE key=?", (key,)).fetchone()
    if row:
        try:
            return json.loads(row["value_json"])
        except Exception:
            return row["value_json"]
    try:
        from ...services.engine.strategy_spec import INTENT_CODE_DEFAULTS
        if key in INTENT_CODE_DEFAULTS:
            return INTENT_CODE_DEFAULTS[key]
    except Exception:
        pass
    return default


def _engine_setting_groups():
    """설정 그룹을 6엔진과 일치 — 각 엔진 모듈의 SETTING_KEYS를 단일 출처로."""
    from ...services.engine.buy_engine import GATE_SETTING_KEYS
    from ...services.engine.execution_engine import EXEC_SETTING_KEYS
    from ...services.engine.sell_engine import SELL_SETTING_KEYS
    return [
        ("① 전략설정(확신도)", ["conviction.regime_weight", "conviction.pullback_full_dist_pct"]),
        ("② 시장감지·전환", ["regime.down_pct", "regime.up_pct", "regime.surge_pct", "regime.vix_volatile",
                        "regime.down_transition_pp", "regime.up_transition_pp",
                        "regime.transition_window_min", "regime.transition_response_active",
                        "regime.transition_trail_tighten_factor"]),
        ("③ 종목선정", ["selection.change_weight", "selection.surge_weight"]),
        ("④ 매수(게이트)", GATE_SETTING_KEYS),
        ("⑤ 매도(수확)", SELL_SETTING_KEYS),
        ("⑥ 매매(사이징)", EXEC_SETTING_KEYS),
        ("리스크(공통 안전벨트)", ["risk.daily_loss_limit_percent", "risk.auto_halt_loss_percent",
                          "risk.flash_crash_threshold_pct"]),
    ]


@router.get("/settings")
async def engine_settings() -> dict:
    """전략 엔진 설정(SSOT 추적) — Settings 화면 '전략 엔진 설정' 섹션용. 값+의도+그룹."""
    from ...services.engine.strategy_spec import INTENT_CODE_DEFAULTS, INTENT_SETTINGS
    intent = {**INTENT_CODE_DEFAULTS, **INTENT_SETTINGS}
    with get_connection() as conn:
        groups = []
        for title, keys in _engine_setting_groups():
            items = []
            for k in keys:
                cur = _get(conn, k, None)
                items.append({
                    "key": k, "value": cur, "intent": intent.get(k),
                    "in_db": conn.execute("SELECT 1 FROM system_settings WHERE key=?", (k,)).fetchone() is not None,
                })
            groups.append({"title": title, "items": items})
    return {"ok": True, "payload": {"groups": groups}}


@router.get("/status")
async def engine_status() -> dict:
    """6엔진 상태 + SSOT 정합 스냅샷."""
    try:
        from ...services.engine.strategy_spec import check_conformance, check_drift
        drift, conf = check_drift(), check_conformance()
    except Exception as exc:
        drift, conf = [f"체크 실패: {exc}"], []

    with get_connection() as conn:
        # Alert Center 요약(미확인 경고 — PM이 Alert 화면 안 봐도 여기서 감지)
        try:
            arow = conn.execute(
                "SELECT COUNT(*) n, SUM(CASE WHEN severity='CRITICAL' THEN 1 ELSE 0 END) crit "
                "FROM system_alerts WHERE acknowledged=0"
            ).fetchone()
            alerts = {"unacked": arow["n"] or 0, "critical": arow["crit"] or 0}
        except Exception:
            alerts = {"unacked": 0, "critical": 0}
        # 엔진② KOSPI 시계열(최근 거래일)
        series = conn.execute(
            "SELECT substr(captured_at,12,5) t, change_rate v FROM market_snapshots "
            "WHERE symbol='KOSPI' AND substr(captured_at,1,10)="
            "(SELECT MAX(substr(captured_at,1,10)) FROM market_snapshots WHERE symbol='KOSPI') "
            "ORDER BY captured_at"
        ).fetchall()
        # 엔진④매수·⑤매도 — 현재 레짐으로 라이브 파라미터 해석(실매 소비 경로와 동일 권위)
        _r5 = str(_get(conn, "regime.current_5tier", "flat") or "flat")
        try:
            from ...services.engine.buy_engine import resolve_buy_gates
            from ...services.engine.sell_engine import resolve_sell_params
            _g, _s = resolve_buy_gates(_r5), resolve_sell_params(_r5)
        except Exception:
            _g, _s = {}, {}
        _e4 = {
            "regime": _r5,
            "vwap_mode": _g.get("vwap_pullback_mode"),
            "max_vwap_dist": _g.get("entry_max_vwap_dist_pct"),
            "band_min": _g.get("min_price_change_pct"),
            "band_max": _g.get("max_price_change_pct"),
            "min_vol": _g.get("min_volume_ratio"),
            "leverage": _g.get("leverage_restriction"),
            "wired": True,  # decision_engine VWAP게이트 + _entry_gate_block 경유
        }
        _e5 = {
            "harvest": _s.get("harvest_mode"),
            "scaleout_target": _s.get("scaleout_target_rate"),
            "scaleout_ratio": _s.get("scaleout_ratio"),
            "stop_loss": _s.get("stop_loss_rate"),
            "trail": _s.get("trailing_stop_rate"),
            "wired": True,  # position_manager 스케일아웃 + 트레일 경유
        }
        payload = {
            "ssot": {"drift": len(drift), "conformance": len(conf),
                     "ok": not drift and not conf,
                     "items": (drift + conf)[:8]},
            "alerts": alerts,
            "engine1_sizing": {
                "active": _get(conn, "sizing.model_active", False),
                "per_rate_min": _get(conn, "sizing.per_position_rate_min", 0.05),
                "per_rate_max": _get(conn, "risk.max_position_rate_per_stock", 0.15),
                "positions_min": _get(conn, "sizing.positions_min", 6),
                "positions_max": _get(conn, "sizing.positions_max", 19),
                "surge_rate_max": _get(conn, "sizing.surge_per_position_rate_max", 0.15),
            },
            "engine2_regime": {
                "current_5tier": _get(conn, "regime.current_5tier", "-"),
                "current_transition": _get(conn, "regime.current_transition", "-"),
                "response_active": _get(conn, "regime.transition_response_active", False),
                "trail_tighten_factor": _get(conn, "regime.transition_trail_tighten_factor", 1.0),
                "thresholds": {
                    "down": _get(conn, "regime.down_pct", -1.5),
                    "up": _get(conn, "regime.up_pct", 0.5),
                    "surge": _get(conn, "regime.surge_pct", 2.5),
                    "down_transition_pp": _get(conn, "regime.down_transition_pp", -1.0),
                    "up_transition_pp": _get(conn, "regime.up_transition_pp", 1.0),
                },
                "kospi_series": [{"t": r["t"], "v": r["v"]} for r in series],
            },
            "engine3_selection": {
                "change_weight": _get(conn, "selection.change_weight", 0.5),
                "surge_weight": _get(conn, "selection.surge_weight", 0.5),
                "wired": False,
            },
            "engine4_buy": _e4,
            "engine5_sell": _e5,
            "engine6_execution": {
                "model_active": _get(conn, "sizing.model_active", False),
                "conviction": "레짐×눌림 결합",
                "wired": True,  # order_executor._compute_new_model_sizing 경유
            },
            "engines_todo": ["엔진③ 종목선정 배선(감지검증 후)", "decision_engine 분해(점진적)"],
        }
    return {"ok": True, "payload": payload}
