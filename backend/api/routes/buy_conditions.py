"""탐색엔진 매수조건/그룹 편집 API — 원자 조건 + AND 그룹 + 레짐/프로파일 할당.

Settings 화면이 조건 임계치·enabled·그룹 구성·할당을 편집한다.
DB 정의·로드는 buy_condition_framework(Phase 1a)를 재사용한다.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.db import get_connection
from ...services.engine import buy_condition_framework as bcf

router = APIRouter(prefix="/api/v1/buy-conditions", tags=["buy-conditions"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConditionUpdate(BaseModel):
    params: dict[str, Any] | None = None
    enabled: bool | None = None


@router.get("/conditions")
def get_conditions() -> dict[str, Any]:
    """원자 조건 전체(비활성 포함)를 반환한다."""
    bcf.seed_defaults()
    conds = bcf.load_conditions(enabled_only=False)
    return {"ok": True, "payload": {"conditions": list(conds.values())}}


@router.put("/conditions/{cid}")
def put_condition(cid: str, body: ConditionUpdate) -> dict[str, Any]:
    """조건 1개의 params/enabled 를 편집한다. 없으면 404."""
    bcf._ensure_tables()
    existing = bcf.load_conditions(enabled_only=False).get(cid)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"condition not found: {cid}")

    sets: list[str] = []
    args: list[Any] = []
    if body.params is not None:
        sets.append("params_json = ?")
        args.append(json.dumps(body.params, ensure_ascii=False))
    if body.enabled is not None:
        sets.append("enabled = ?")
        args.append(1 if body.enabled else 0)
    if sets:
        args.append(cid)
        with get_connection() as conn:
            conn.execute(f"UPDATE buy_conditions SET {', '.join(sets)} WHERE id = ?", args)

    updated = bcf.load_conditions(enabled_only=False)[cid]
    return {"ok": True, "payload": {"condition": updated}}


class GroupCreate(BaseModel):
    name: str
    condition_ids: list[str] = []
    enabled: bool = True
    weight: float = 1.0
    assigned_to: str = ""


class GroupUpdate(BaseModel):
    name: str | None = None
    condition_ids: list[str] | None = None
    enabled: bool | None = None
    weight: float | None = None
    assigned_to: str | None = None


# 할당 가능한 레짐/RiskProfile (드롭다운 소스)
_ASSIGN_REGIMES = ["risk_on", "neutral", "defensive", "volatile"]
_ASSIGN_PROFILES = ["LOW_VOL", "MID_VOL", "HIGH_VOL", "THEME_SPIKE"]


@router.get("/groups")
def get_groups() -> dict[str, Any]:
    """조건 그룹 전체(비활성 포함)를 반환한다."""
    bcf.seed_defaults()
    return {"ok": True, "payload": {"groups": bcf.load_groups(enabled_only=False)}}


@router.post("/groups")
def post_group(body: GroupCreate) -> dict[str, Any]:
    """AND 그룹을 신규 생성한다."""
    bcf._ensure_tables()
    gid = "grp_" + uuid.uuid4().hex[:12]
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO condition_groups (id, name, condition_ids_json, enabled, weight, assigned_to, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (gid, body.name, json.dumps(body.condition_ids, ensure_ascii=False),
             1 if body.enabled else 0, float(body.weight), body.assigned_to, _now()),
        )
    created = next(g for g in bcf.load_groups(enabled_only=False) if g["id"] == gid)
    return {"ok": True, "payload": {"group": created}}


@router.put("/groups/{gid}")
def put_group(gid: str, body: GroupUpdate) -> dict[str, Any]:
    """그룹의 name/condition_ids/enabled/weight/assigned_to 를 편집한다. 없으면 404."""
    bcf._ensure_tables()
    existing = [g for g in bcf.load_groups(enabled_only=False) if g["id"] == gid]
    if not existing:
        raise HTTPException(status_code=404, detail=f"group not found: {gid}")

    sets: list[str] = []
    args: list[Any] = []
    if body.name is not None:
        sets.append("name = ?"); args.append(body.name)
    if body.condition_ids is not None:
        sets.append("condition_ids_json = ?"); args.append(json.dumps(body.condition_ids, ensure_ascii=False))
    if body.enabled is not None:
        sets.append("enabled = ?"); args.append(1 if body.enabled else 0)
    if body.weight is not None:
        sets.append("weight = ?"); args.append(float(body.weight))
    if body.assigned_to is not None:
        sets.append("assigned_to = ?"); args.append(body.assigned_to)
    if sets:
        args.append(gid)
        with get_connection() as conn:
            conn.execute(f"UPDATE condition_groups SET {', '.join(sets)} WHERE id = ?", args)

    updated = next(g for g in bcf.load_groups(enabled_only=False) if g["id"] == gid)
    return {"ok": True, "payload": {"group": updated}}


@router.get("/assign-targets")
def get_assign_targets() -> dict[str, Any]:
    """그룹 할당 가능한 레짐/RiskProfile 목록을 반환한다."""
    return {"ok": True, "payload": {"regimes": _ASSIGN_REGIMES, "profiles": _ASSIGN_PROFILES}}
