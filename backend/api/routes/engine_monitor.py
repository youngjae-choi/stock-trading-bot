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
            "engines_todo": ["④매수", "⑤매도", "⑥매매", "UI"],
        }
    return {"ok": True, "payload": payload}
