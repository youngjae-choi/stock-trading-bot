# INBOX_EXECUTOR_design_v2_backend_api

## 목적
Dantabot 설계변경 v2 — 백엔드 API Routes + main.py + scheduler 구현.
이 INBOX는 backend_core 작업이 완료된 후 실행한다.

완료 후 `docs/agent-comm/OUTBOX_EXECUTOR_design_v2_backend_api.md`에 결과 작성.

---

## 전제조건 (core 작업 완료 확인)
- `backend/services/engine/rule_resolver.py` 존재
- `backend/services/engine/rule_cache.py` 존재
- `backend/services/engine/daily_plan.py` 존재

---

## Task 1: `backend/api/routes/rule.py` 신규 생성

```python
"""Rule System API — Base RulePack, Risk Profile Pack, Rule Composition."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.engine.rule_resolver import (
    get_active_base_rulepack,
    get_active_profile_pack,
    get_active_daily_plan,
    get_symbol_overrides,
    resolve_symbol_rule,
)
from ...services.engine.rule_cache import get_all_cached, get_meta
from ...services.db import get_connection
from ...services.settings_store import get_setting

router = APIRouter(prefix="/api/v1/rule", tags=["rule"])
logger = logging.getLogger("RuleAPI")


def _global_risk() -> dict[str, Any]:
    return {
        "daily_loss_limit": float(get_setting("risk.daily_loss_limit_percent", -2.0) or -2.0),
        "max_positions": int(get_setting("risk.max_positions", 5) or 5),
        "max_position_rate_per_stock": float(get_setting("risk.max_position_rate_per_stock", 0.10) or 0.10),
        "force_exit_time": "15:20:00",
        "new_entry_cutoff_time": "15:10:00",
    }


@router.get("/base")
def get_base_rulepack():
    return {"ok": True, "payload": get_active_base_rulepack()}


@router.get("/base/list")
def list_base_rulepacks():
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, version, is_active, created_at FROM base_rulepacks ORDER BY created_at DESC"
        ).fetchall()
    return {"ok": True, "payload": [dict(r) for r in rows]}


@router.get("/profiles")
def get_profile_pack():
    pack = get_active_profile_pack()
    return {"ok": True, "payload": pack}


@router.get("/profiles/list")
def list_profile_packs():
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, version, is_active, created_at FROM risk_profile_packs ORDER BY created_at DESC"
        ).fetchall()
    return {"ok": True, "payload": [dict(r) for r in rows]}


class ProfilePackUpdate(BaseModel):
    profiles: dict[str, Any]


@router.put("/profiles")
def update_profile_pack(body: ProfilePackUpdate):
    """프로필 값 수정 → 새 버전 자동 생성 + 활성화."""
    _PROFILES = ("LOW_VOL", "MID_VOL", "HIGH_VOL", "THEME_SPIKE")
    for p in _PROFILES:
        if p not in body.profiles:
            raise HTTPException(status_code=400, detail=f"Missing profile: {p}")

    # 현재 활성 pack의 버전 조회해 다음 버전 계산
    with get_connection() as conn:
        row = conn.execute(
            "SELECT version FROM risk_profile_packs WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    current_version = row["version"] if row else "1.0"
    try:
        major, minor = current_version.split(".")
        new_version = f"{major}.{int(minor) + 1}"
    except Exception:
        new_version = "1.1"

    new_id = f"profile-v{new_version}"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    with get_connection() as conn:
        # 기존 활성 pack 비활성화
        conn.execute("UPDATE risk_profile_packs SET is_active = 0")
        # 신규 버전 삽입
        conn.execute(
            "INSERT INTO risk_profile_packs (id, version, profiles, created_at, is_active) VALUES (?, ?, ?, ?, 1)",
            (new_id, new_version, json.dumps(body.profiles, ensure_ascii=False)),
        )

    logger.info("SUCCESS: [RuleAPI] profile pack updated id=%s version=%s", new_id, new_version)
    return {"ok": True, "payload": {"id": new_id, "version": new_version}}


@router.get("/composition/today")
def get_rule_composition_today():
    """오늘 캐시된 전체 종목 최종 룰 반환."""
    cached = get_all_cached()
    meta = get_meta()
    return {"ok": True, "payload": {"meta": meta, "compositions": cached}}


@router.get("/composition/{symbol_code}")
def get_rule_composition_symbol(symbol_code: str):
    """특정 종목 최종 룰 미리보기 (캐시 없어도 즉시 계산)."""
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")

    base = get_active_base_rulepack()
    pack = get_active_profile_pack()
    plan = get_active_daily_plan(today)
    overrides = get_symbol_overrides()
    risk = _global_risk()

    final_rule = resolve_symbol_rule(
        symbol_code=symbol_code,
        base_rulepack=base,
        profile_pack=pack,
        daily_plan=plan,
        symbol_overrides=overrides,
        global_risk=risk,
    )
    return {"ok": True, "payload": final_rule}
```

---

## Task 2: `backend/api/routes/daily_plan.py` 신규 생성

```python
"""Daily Trading Plan API."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException

from ...services.engine.daily_plan import (
    get_today_daily_plan,
    run_daily_plan_generation,
    _validate_plan,
)
from ...services.db import get_connection

router = APIRouter(prefix="/api/v1/daily-plan", tags=["daily-plan"])
logger = logging.getLogger("DailyPlanAPI")


def _today_kst() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


@router.get("/today")
def get_today():
    plan = get_today_daily_plan(_today_kst())
    return {"ok": True, "payload": plan}


@router.get("/{date}")
def get_by_date(date: str):
    plan = get_today_daily_plan(date)
    if not plan:
        raise HTTPException(status_code=404, detail="Daily plan not found")
    return {"ok": True, "payload": plan}


@router.post("/generate")
async def generate():
    """S5 수동 즉시 실행."""
    result = await run_daily_plan_generation(_today_kst())
    return {"ok": True, "payload": result}


@router.post("/validate")
async def validate_plan():
    """오늘 draft plan 검증만 실행 (활성화 없음)."""
    plan = get_today_daily_plan(_today_kst())
    if not plan:
        raise HTTPException(status_code=404, detail="No plan found for today")
    validation = _validate_plan({
        "trading_intensity": plan.get("trading_intensity"),
        "new_entry_allowed": plan.get("new_entry_allowed"),
        "symbol_assignments": plan.get("symbol_assignments", []),
        "daily_overrides": plan.get("daily_overrides", {}),
    })
    all_pass = all(v == "pass" for v in validation.values())
    return {"ok": True, "payload": {"validation": validation, "all_pass": all_pass}}


@router.post("/activate")
def activate():
    """검증 통과된 plan을 active 상태로 전환."""
    today = _today_kst()
    plan = get_today_daily_plan(today)
    if not plan:
        raise HTTPException(status_code=404, detail="No plan found for today")
    if plan.get("status") not in ("validated", "active"):
        raise HTTPException(status_code=400, detail=f"Plan status is '{plan.get('status')}', must be validated first")

    with get_connection() as conn:
        now = datetime.now().isoformat()
        conn.execute(
            "UPDATE daily_trading_plans SET status = 'active', activated_at = ? WHERE trade_date = ?",
            (now, today),
        )
    logger.info("SUCCESS: [DailyPlanAPI] activated trade_date=%s", today)
    return {"ok": True, "payload": {"trade_date": today, "status": "active"}}
```

---

## Task 3: `backend/api/routes/symbol_override.py` 신규 생성

```python
"""Symbol Override API."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.db import get_connection

router = APIRouter(prefix="/api/v1/symbol-overrides", tags=["symbol-overrides"])
logger = logging.getLogger("SymbolOverrideAPI")


class OverrideBody(BaseModel):
    symbol_name: str = ""
    default_profile: str = "MID_VOL"
    override_values: dict[str, Any] = {}
    is_active: bool = True


@router.get("")
def list_overrides():
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM symbol_overrides ORDER BY updated_at DESC").fetchall()
    return {"ok": True, "payload": [dict(r) for r in rows]}


@router.put("/{symbol_code}")
def upsert_override(symbol_code: str, body: OverrideBody):
    now = datetime.now(timezone.utc).isoformat()
    _PROFILES = ("LOW_VOL", "MID_VOL", "HIGH_VOL", "THEME_SPIKE")
    if body.default_profile not in _PROFILES:
        raise HTTPException(status_code=400, detail=f"Invalid profile: {body.default_profile}")

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM symbol_overrides WHERE symbol_code = ?", (symbol_code,)
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE symbol_overrides
                   SET symbol_name=?, default_profile=?, override_values=?, is_active=?, updated_at=?
                   WHERE symbol_code=?""",
                (body.symbol_name, body.default_profile,
                 json.dumps(body.override_values, ensure_ascii=False),
                 1 if body.is_active else 0, now, symbol_code),
            )
        else:
            conn.execute(
                """INSERT INTO symbol_overrides
                   (id, symbol_code, symbol_name, default_profile, override_values, is_active, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), symbol_code, body.symbol_name, body.default_profile,
                 json.dumps(body.override_values, ensure_ascii=False),
                 1 if body.is_active else 0, now, now),
            )
    logger.info("SUCCESS: [SymbolOverrideAPI] upserted symbol_code=%s", symbol_code)
    return {"ok": True, "payload": {"symbol_code": symbol_code}}


@router.delete("/{symbol_code}")
def delete_override(symbol_code: str):
    with get_connection() as conn:
        conn.execute("DELETE FROM symbol_overrides WHERE symbol_code = ?", (symbol_code,))
    return {"ok": True, "payload": {"symbol_code": symbol_code}}
```

---

## Task 4: `backend/api/routes/trading_monitor.py` 신규 생성

```python
"""Trading Monitor API — 매수 대기 후보 + 보유 포지션 + 매수 준비도 조회."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from ...services.engine.daily_plan import get_today_daily_plan
from ...services.engine.rule_cache import get_all_cached, get_rule
from ...services.engine.position_manager import position_manager
from ...services.db import get_connection

router = APIRouter(prefix="/api/v1/trading-monitor", tags=["trading-monitor"])
logger = logging.getLogger("TradingMonitorAPI")


def _today_kst() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


def _compute_buy_readiness(candidate: dict[str, Any], rule: dict[str, Any] | None) -> dict[str, Any]:
    """매수 준비도 계산.

    조건 목록과 임계치는 rule + candidate에서 동적으로 구성한다.
    각 조건은 {name, label, current_value, threshold_label, score_pct, met} 형태.
    score_pct: 0.0~100.0 (조건 근접 정도)
    """
    conditions: list[dict[str, Any]] = []

    # AI 신뢰도
    ai_conf = float(candidate.get("suitability_score") or candidate.get("confidence") or 0.0)
    ai_min = float((rule or {}).get("ai_confidence_min", 0.65))
    ai_score = min(ai_conf / ai_min, 1.0) * 100 if ai_min > 0 else 100.0
    conditions.append({
        "name": "ai_confidence",
        "label": "AI 신뢰도",
        "current_value": round(ai_conf, 3),
        "threshold_label": f">= {ai_min:.2f}",
        "score_pct": round(ai_score, 1),
        "met": ai_conf >= ai_min,
    })

    # 거래량 배수 (candidate에 volume_ratio 있으면 사용)
    vol_ratio = float(candidate.get("volume_ratio") or candidate.get("vol_ratio") or 0.0)
    vol_min = float((rule or {}).get("volume_ratio_min", 2.0))
    if vol_ratio > 0:
        vol_score = min(vol_ratio / vol_min, 1.0) * 100 if vol_min > 0 else 100.0
        conditions.append({
            "name": "volume_ratio",
            "label": "거래량 배수",
            "current_value": round(vol_ratio, 2),
            "threshold_label": f">= {vol_min:.1f}x",
            "score_pct": round(vol_score, 1),
            "met": vol_ratio >= vol_min,
        })

    # 등락률 (과도한 급등은 제외)
    change_rate = float(candidate.get("change_rate") or candidate.get("chg_rate") or 0.0)
    if change_rate != 0:
        # 양수 등락이 좋지만 너무 높으면 리스크 (>15% 이상이면 위험)
        rate_score = max(0.0, min(change_rate / 10.0, 1.0)) * 100 if change_rate > 0 else 0.0
        conditions.append({
            "name": "change_rate",
            "label": "등락률",
            "current_value": round(change_rate, 2),
            "threshold_label": "0% ~ 15%",
            "score_pct": round(rate_score, 1),
            "met": 0 < change_rate < 15,
        })

    # VWAP (candidate에 vwap_position 있으면 표시)
    vwap_pos = candidate.get("vwap_position")
    if vwap_pos is not None:
        vwap_met = str(vwap_pos).lower() in ("above", "상단", "위")
        conditions.append({
            "name": "vwap_position",
            "label": "VWAP 상단",
            "current_value": str(vwap_pos),
            "threshold_label": "상단",
            "score_pct": 100.0 if vwap_met else 0.0,
            "met": vwap_met,
        })

    # 종합 점수 계산 (단순 평균)
    if conditions:
        overall = sum(c["score_pct"] for c in conditions) / len(conditions)
    else:
        overall = 0.0

    return {
        "overall_pct": round(overall, 1),
        "met_count": sum(1 for c in conditions if c["met"]),
        "total_count": len(conditions),
        "conditions": conditions,
    }


@router.get("/candidates")
def get_candidates():
    """매수 대기 후보 종목 목록 + Profile + 매수 준비도."""
    today = _today_kst()
    plan = get_today_daily_plan(today)
    if not plan:
        return {"ok": True, "payload": {"candidates": [], "plan_id": None}}

    all_rules = get_all_cached()
    assignments = {a["code"]: a for a in plan.get("symbol_assignments", [])}
    excluded = {e["code"] for e in plan.get("excluded_symbols", [])}

    # hybrid_screening_results에서 오늘 후보 조회
    with get_connection() as conn:
        row = conn.execute(
            "SELECT candidates FROM hybrid_screening_results WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
            (today,),
        ).fetchone()

    import json as _json
    raw_candidates: list[dict] = []
    if row:
        try:
            raw_candidates = _json.loads(row["candidates"] or "[]")
        except Exception:
            raw_candidates = []

    # daily_overrides 조건 읽기
    overrides = plan.get("daily_overrides", {})

    result = []
    for c in raw_candidates:
        code = str(c.get("symbol") or c.get("ticker") or "").strip()
        if not code or code in excluded:
            continue
        assignment = assignments.get(code, {})
        rule = all_rules.get(code) or {}

        # daily_overrides로 rule 보완
        if overrides.get("min_ai_confidence"):
            rule["ai_confidence_min"] = overrides["min_ai_confidence"]
        if overrides.get("volume_filter_multiplier"):
            rule["volume_ratio_min"] = overrides["volume_filter_multiplier"]

        readiness = _compute_buy_readiness(c, rule)
        result.append({
            "code": code,
            "name": c.get("name") or "",
            "profile": assignment.get("profile") or rule.get("profile_assigned") or "MID_VOL",
            "assignment_reason": assignment.get("reason") or "",
            "score": c.get("suitability_score") or c.get("score") or 0,
            "change_rate": c.get("change_rate") or 0,
            "ws_subscribed": code in all_rules,
            "buy_readiness": readiness,
        })

    result.sort(key=lambda x: x["buy_readiness"]["overall_pct"], reverse=True)
    return {"ok": True, "payload": {
        "candidates": result,
        "plan_id": plan.get("id"),
        "daily_overrides": overrides,
    }}


@router.get("/positions")
def get_positions():
    """보유 포지션 + 트레일링 스탑 상태."""
    positions = position_manager.get_positions()

    # position_stop_states DB에서 최신 상태 반영
    if positions:
        with get_connection() as conn:
            for pos in positions:
                row = conn.execute(
                    "SELECT * FROM position_stop_states WHERE position_id = ?",
                    (pos.get("position_id", ""),),
                ).fetchone()
                if row:
                    pos.update({
                        "highest_price_since_entry": row["highest_price_since_entry"],
                        "initial_stop_price": row["initial_stop_price"],
                        "trailing_stop_price": row["trailing_stop_price"],
                        "active_stop_price": row["active_stop_price"],
                        "trailing_active": bool(row["trailing_active"]),
                    })

    return {"ok": True, "payload": {"positions": positions}}
```

---

## Task 5: `backend/main.py` 수정

기존 import 블록과 `app.include_router()` 블록에 아래를 추가한다.

import 추가 (기존 `from .api.routes.trading_data import ...` 근처):
```python
from .api.routes.rule import router as rule_router
from .api.routes.daily_plan import router as daily_plan_router
from .api.routes.symbol_override import router as symbol_override_router
from .api.routes.trading_monitor import router as trading_monitor_router
```

include_router 추가 (기존 라우터들 다음):
```python
app.include_router(rule_router)
app.include_router(daily_plan_router)
app.include_router(symbol_override_router)
app.include_router(trading_monitor_router)
```

---

## Task 6: `backend/services/scheduler.py` 수정

기존 S5 RulePack 생성 job을 Daily Plan 생성으로 교체한다.

기존 job (예: `job_rulepack_generation` 또는 유사 이름) 을 찾아:
1. import에서 `rulepack_generation` 관련 import 제거, `daily_plan` import 추가:
   ```python
   from .engine.daily_plan import run_daily_plan_generation
   ```
2. 기존 S5 job 함수를 아래로 교체:
   ```python
   async def _job_daily_plan():
       logger.info("START: [Scheduler] S5 Daily Plan generation")
       try:
           result = await run_daily_plan_generation()
           logger.info("SUCCESS: [Scheduler] S5 Daily Plan result=%s", result)
       except Exception as exc:
           logger.error("FAIL: [Scheduler] S5 Daily Plan error=%s", exc)
   ```
3. scheduler job 등록 시간: 기존 S5 시간(08:45 KST)으로 유지.
   `scheduler.add_job(_job_daily_plan, 'cron', hour=8, minute=45, timezone='Asia/Seoul', id='job_daily_plan')`

---

## Task 7: 검증

```bash
python3 -m py_compile backend/api/routes/rule.py
python3 -m py_compile backend/api/routes/daily_plan.py
python3 -m py_compile backend/api/routes/symbol_override.py
python3 -m py_compile backend/api/routes/trading_monitor.py
python3 -m py_compile backend/main.py
python3 -m py_compile backend/services/scheduler.py
```

전부 통과해야 완료.

---

## 완료 기준

- [ ] rule.py: GET base, profiles + PUT profiles (새 버전 생성) + GET composition
- [ ] daily_plan.py: today/date 조회 + generate + validate + activate
- [ ] symbol_override.py: list + upsert + delete
- [ ] trading_monitor.py: candidates (매수 준비도 포함) + positions (trailing 상태)
- [ ] main.py: 4개 라우터 등록
- [ ] scheduler.py: S5 job을 daily_plan으로 교체
- [ ] py_compile 전부 통과
