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
