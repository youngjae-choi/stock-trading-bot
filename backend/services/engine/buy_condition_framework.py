"""설정 가능한 매수 조건 프레임워크 — 원자 조건 → AND 그룹 → 그룹들 OR.

평가기는 정규화된 state dict(체결강도·VWAP·10초봉 등)에 대해 동작한다.
state 값 채움은 Phase 1b, 매수경로 통합은 후속. 본 모듈은 순수 로직 + DB 정의.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from ..db import get_connection

logger = logging.getLogger("BuyConditionFramework")


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def evaluate_condition(condition: dict[str, Any], state: dict[str, Any]) -> bool:
    """원자 조건 1개를 state에 대해 평가. 알 수 없는 ctype은 False."""
    ctype = str(condition.get("ctype") or "")
    p = condition.get("params") or {}
    if ctype == "change_rate_band":
        cr = _f(state.get("change_rate"))
        return _f(p.get("min")) <= cr <= _f(p.get("max"), 999.0)
    if ctype == "chegyeol_gangdo_min":
        return _f(state.get("체결강도")) >= _f(p.get("min"))
    if ctype == "tick_volume_mult_min":
        return _f(state.get("tick_vol_mult")) >= _f(p.get("min"))
    if ctype == "tsi_positive":
        tsi = state.get("tsi")
        # min=0(기본) → 현재 동작(tsi>0)과 동일. 결손은 통과(차단 금지).
        return True if tsi is None else _f(tsi) > _f(p.get("min"))
    if ctype == "vwap_above":
        # raw vwap/price 있으면 margin_pct 적용, 없으면 기존 vwap_position 폴백.
        # margin_pct=0(기본) → price>=vwap 로 above와 동일.
        vwap = state.get("vwap")
        price = state.get("price")
        if vwap is not None and price is not None and _f(vwap) > 0:
            return _f(price) >= _f(vwap) * (1 + _f(p.get("margin_pct")) / 100.0)
        return str(state.get("vwap_position")) == "above"
    if ctype == "day_high_breakout":
        # raw prior_day_high/price 있으면 buffer_pct 적용, 없으면 기존 bool 폴백.
        # buffer_pct=0(기본) → price>=prior_day_high 로 돌파와 동일.
        pdh = state.get("prior_day_high")
        price = state.get("price")
        if pdh is not None and price is not None and _f(pdh) > 0:
            return _f(price) >= _f(pdh) * (1 + _f(p.get("buffer_pct")) / 100.0)
        return bool(state.get("day_high_breakout"))
    if ctype == "pullback_rebound":
        return bool(state.get("pullback_rebound"))
    if ctype == "momentum_rising_bars":
        return int(_f(state.get("rising_bars"))) >= int(_f(p.get("min_bars"), 1))
    if ctype == "time_window":
        t = str(state.get("time_hhmm") or "")
        return str(p.get("start") or "00:00") <= t <= str(p.get("end") or "23:59")
    return False


def evaluate_group(group: dict[str, Any], conditions_by_id: dict[str, Any], state: dict[str, Any]) -> bool:
    """그룹의 모든 조건(AND) 충족 여부. 조건 없으면 False."""
    cond_ids = group.get("condition_ids") or []
    if not cond_ids:
        return False
    for cid in cond_ids:
        cond = conditions_by_id.get(cid)
        if cond is None or not evaluate_condition(cond, state):
            return False
    return True


def evaluate_groups_or(
    groups: list[dict[str, Any]], conditions_by_id: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any]:
    """그룹들 OR — 발화한 그룹명 리스트와 any 여부."""
    fired = [
        str(g.get("name") or g.get("id"))
        for g in groups
        if evaluate_group(g, conditions_by_id, state)
    ]
    return {"any": len(fired) > 0, "fired": fired}


def _ensure_tables() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS buy_conditions (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                ctype       TEXT NOT NULL,
                params_json TEXT NOT NULL DEFAULT '{}',
                enabled     INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS condition_groups (
                id                 TEXT PRIMARY KEY,
                name               TEXT NOT NULL,
                condition_ids_json TEXT NOT NULL DEFAULT '[]',
                enabled            INTEGER NOT NULL DEFAULT 1,
                weight             REAL NOT NULL DEFAULT 1.0,
                assigned_to        TEXT NOT NULL DEFAULT '',
                created_at         TEXT NOT NULL
            )
            """
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# 기본 조건 정의: (고정 id, name, ctype, params)
_DEFAULT_CONDITIONS = [
    ("cond_breakout", "당일고가 돌파", "day_high_breakout", {}),
    ("cond_pullback", "눌림 후 반등", "pullback_rebound", {}),
    ("cond_momentum", "10초봉 3연속 상승", "momentum_rising_bars", {"min_bars": 3}),
    ("cond_gangdo", "체결강도 55%+", "chegyeol_gangdo_min", {"min": 0.55}),
    ("cond_tickvol", "틱거래량 2배+", "tick_volume_mult_min", {"min": 2.0}),
    ("cond_vwap", "VWAP 상단", "vwap_above", {}),
    ("cond_crband", "등락률 1.5~5%", "change_rate_band", {"min": 1.5, "max": 5.0}),
    ("cond_tsi", "일봉 TSI>0", "tsi_positive", {}),
    ("cond_time", "시간창 09:30~15:00", "time_window", {"start": "09:30", "end": "15:00"}),
]

# 기본 그룹: (고정 id, name, [condition_ids])
_DEFAULT_GROUPS = [
    ("grp_breakout", "돌파전략", ["cond_breakout", "cond_gangdo", "cond_tickvol", "cond_vwap"]),
    ("grp_pullback", "눌림전략", ["cond_pullback", "cond_gangdo", "cond_vwap"]),
    ("grp_momentum", "모멘텀전략", ["cond_momentum", "cond_gangdo", "cond_tickvol"]),
    ("grp_baseline", "베이스라인(기존게이트)", ["cond_crband", "cond_tsi", "cond_time"]),
]


def seed_defaults() -> None:
    """기본 조건/그룹을 시드. 고정 id라 INSERT OR IGNORE 로 idempotent."""
    _ensure_tables()
    now = _now()
    with get_connection() as conn:
        for cid, name, ctype, params in _DEFAULT_CONDITIONS:
            conn.execute(
                "INSERT OR IGNORE INTO buy_conditions (id, name, ctype, params_json, enabled, created_at) "
                "VALUES (?, ?, ?, ?, 1, ?)",
                (cid, name, ctype, json.dumps(params, ensure_ascii=False), now),
            )
        for gid, name, cond_ids in _DEFAULT_GROUPS:
            conn.execute(
                "INSERT OR IGNORE INTO condition_groups (id, name, condition_ids_json, enabled, weight, assigned_to, created_at) "
                "VALUES (?, ?, ?, 1, 1.0, '', ?)",
                (gid, name, json.dumps(cond_ids, ensure_ascii=False), now),
            )


def load_conditions(enabled_only: bool = True) -> dict[str, dict[str, Any]]:
    """{id: {id, name, ctype, params, enabled}}."""
    _ensure_tables()
    sql = "SELECT * FROM buy_conditions"
    if enabled_only:
        sql += " WHERE enabled = 1"
    out: dict[str, dict[str, Any]] = {}
    with get_connection() as conn:
        for row in conn.execute(sql).fetchall():
            d = dict(row)
            out[d["id"]] = {
                "id": d["id"], "name": d["name"], "ctype": d["ctype"],
                "params": json.loads(d.get("params_json") or "{}"),
                "enabled": bool(d.get("enabled")),
            }
    return out


def load_groups(enabled_only: bool = True) -> list[dict[str, Any]]:
    """[{id, name, condition_ids, enabled, weight, assigned_to}]."""
    _ensure_tables()
    sql = "SELECT * FROM condition_groups"
    if enabled_only:
        sql += " WHERE enabled = 1"
    out: list[dict[str, Any]] = []
    with get_connection() as conn:
        for row in conn.execute(sql).fetchall():
            d = dict(row)
            out.append({
                "id": d["id"], "name": d["name"],
                "condition_ids": json.loads(d.get("condition_ids_json") or "[]"),
                "enabled": bool(d.get("enabled")), "weight": float(d.get("weight") or 1.0),
                "assigned_to": d.get("assigned_to") or "",
            })
    return out


def _clear_all_for_test() -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM buy_conditions")
        conn.execute("DELETE FROM condition_groups")
