# INBOX_EXECUTOR_design_v2_backend_core

## 목적
Dantabot 설계변경 v2 — 백엔드 Core 구현.
DB 스키마 확장 + 신규 서비스 파일 생성 + 기존 엔진 파일 수정.

완료 후 `docs/agent-comm/OUTBOX_EXECUTOR_design_v2_backend_core.md`에 결과 작성.

---

## 작업 목록

### Task 1: `backend/services/db.py` 수정

`_schema_statements()` 함수 내 기존 구문 목록 끝에 아래 테이블 정의를 추가한다.

```python
"""
CREATE TABLE IF NOT EXISTS base_rulepacks (
    id              TEXT PRIMARY KEY,
    version         TEXT NOT NULL,
    take_profit_enabled          INTEGER NOT NULL DEFAULT 0,
    force_daily_close            INTEGER NOT NULL DEFAULT 1,
    force_exit_time              TEXT NOT NULL DEFAULT '15:20:00',
    stop_price_can_only_increase INTEGER NOT NULL DEFAULT 1,
    order_execution TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1
)
""",
"""
CREATE TABLE IF NOT EXISTS risk_profile_packs (
    id          TEXT PRIMARY KEY,
    version     TEXT NOT NULL,
    profiles    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 1
)
""",
"""
CREATE TABLE IF NOT EXISTS daily_trading_plans (
    id                   TEXT PRIMARY KEY,
    trade_date           TEXT NOT NULL UNIQUE,
    market_tone          TEXT NOT NULL DEFAULT 'neutral',
    trading_intensity    TEXT NOT NULL DEFAULT 'normal',
    base_rulepack_id     TEXT NOT NULL DEFAULT 'base-v1.0',
    risk_profile_pack_id TEXT NOT NULL DEFAULT 'profile-v1.0',
    new_entry_allowed    INTEGER NOT NULL DEFAULT 1,
    daily_overrides      TEXT NOT NULL DEFAULT '{}',
    symbol_assignments   TEXT NOT NULL DEFAULT '[]',
    excluded_symbols     TEXT NOT NULL DEFAULT '[]',
    llm_summary          TEXT NOT NULL DEFAULT '',
    provider             TEXT NOT NULL DEFAULT '',
    status               TEXT NOT NULL DEFAULT 'draft',
    validation_result    TEXT NOT NULL DEFAULT '{}',
    created_at           TEXT NOT NULL,
    activated_at         TEXT
)
""",
"CREATE INDEX IF NOT EXISTS idx_daily_plan_date ON daily_trading_plans(trade_date)",
"""
CREATE TABLE IF NOT EXISTS symbol_overrides (
    id              TEXT PRIMARY KEY,
    symbol_code     TEXT NOT NULL UNIQUE,
    symbol_name     TEXT NOT NULL DEFAULT '',
    default_profile TEXT NOT NULL DEFAULT 'MID_VOL',
    override_values TEXT NOT NULL DEFAULT '{}',
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
)
""",
"""
CREATE TABLE IF NOT EXISTS rule_compositions (
    id                   TEXT PRIMARY KEY,
    trade_date           TEXT NOT NULL,
    symbol_code          TEXT NOT NULL,
    final_rule           TEXT NOT NULL,
    base_rulepack_id     TEXT NOT NULL,
    risk_profile_pack_id TEXT NOT NULL,
    daily_plan_id        TEXT NOT NULL,
    profile_assigned     TEXT NOT NULL,
    created_at           TEXT NOT NULL
)
""",
"CREATE INDEX IF NOT EXISTS idx_rule_comp_date ON rule_compositions(trade_date)",
"""
CREATE TABLE IF NOT EXISTS position_stop_states (
    position_id               TEXT PRIMARY KEY,
    symbol_code               TEXT NOT NULL,
    entry_price               REAL NOT NULL DEFAULT 0.0,
    highest_price_since_entry REAL NOT NULL DEFAULT 0.0,
    initial_stop_price        REAL NOT NULL DEFAULT 0.0,
    trailing_stop_price       REAL NOT NULL DEFAULT 0.0,
    active_stop_price         REAL NOT NULL DEFAULT 0.0,
    trailing_active           INTEGER NOT NULL DEFAULT 0,
    profile_assigned          TEXT NOT NULL DEFAULT 'MID_VOL',
    last_updated_at           TEXT NOT NULL
)
""",
```

또한 기존 `trading_signals` 테이블을 `_schema_statements()`에 추가한다 (현재 decision_engine.py에서 자체 생성 중 → db.py로 이관):
```python
"""
CREATE TABLE IF NOT EXISTS trading_signals (
    id            TEXT PRIMARY KEY,
    trade_date    TEXT NOT NULL,
    symbol        TEXT NOT NULL,
    name          TEXT NOT NULL DEFAULT '',
    signal_type   TEXT NOT NULL DEFAULT 'BUY',
    trigger_price REAL NOT NULL DEFAULT 0.0,
    confidence    REAL NOT NULL DEFAULT 0.0,
    rule_matched  TEXT NOT NULL DEFAULT '{}',
    profile_assigned TEXT NOT NULL DEFAULT 'MID_VOL',
    status        TEXT NOT NULL DEFAULT 'pending',
    created_at    TEXT NOT NULL
)
""",
"CREATE INDEX IF NOT EXISTS idx_trading_signals_trade_date ON trading_signals(trade_date)",
```

`_seed_system_settings()` 함수 아래에 `_seed_rule_system()` 함수를 추가하고, `initialize_database()` 내에서 호출:

```python
def _seed_rule_system(connection: sqlite3.Connection) -> None:
    """base_rulepacks, risk_profile_packs 초기값 삽입 (이미 있으면 skip)."""
    import json as _json
    now_expr = "strftime('%Y-%m-%dT%H:%M:%fZ','now')"

    # Base RulePack v1.0
    connection.execute(
        f"""
        INSERT OR IGNORE INTO base_rulepacks
            (id, version, take_profit_enabled, force_daily_close, force_exit_time,
             stop_price_can_only_increase, order_execution, created_at, is_active)
        VALUES (?, ?, 0, 1, ?, 1, ?, {now_expr}, 1)
        """,
        (
            "base-v1.0",
            "1.0",
            "15:20:00",
            _json.dumps({"entry_order_type": "limit_or_market_by_policy",
                         "exit_order_type": "market_or_safe_limit"}, ensure_ascii=False),
        ),
    )

    # Risk Profile Pack v1.0
    profiles = {
        "LOW_VOL": {
            "initial_stop_loss": -0.02,
            "trailing_activate_profit": 0.015,
            "trailing_stop_rate": 0.018,
            "max_position_rate": 0.15,
            "max_holding_minutes": 240,
        },
        "MID_VOL": {
            "initial_stop_loss": -0.03,
            "trailing_activate_profit": 0.025,
            "trailing_stop_rate": 0.03,
            "max_position_rate": 0.12,
            "max_holding_minutes": 180,
        },
        "HIGH_VOL": {
            "initial_stop_loss": -0.045,
            "trailing_activate_profit": 0.04,
            "trailing_stop_rate": 0.05,
            "max_position_rate": 0.08,
            "max_holding_minutes": 120,
        },
        "THEME_SPIKE": {
            "initial_stop_loss": -0.06,
            "trailing_activate_profit": 0.05,
            "trailing_stop_rate": 0.06,
            "max_position_rate": 0.05,
            "max_holding_minutes": 60,
            "reentry_allowed": False,
        },
    }
    connection.execute(
        f"""
        INSERT OR IGNORE INTO risk_profile_packs
            (id, version, profiles, created_at, is_active)
        VALUES (?, ?, ?, {now_expr}, 1)
        """,
        ("profile-v1.0", "1.0", _json.dumps(profiles, ensure_ascii=False)),
    )
```

`initialize_database()` 내부:
```python
def initialize_database() -> None:
    logger.info("START: db.initialize_database")
    with get_connection() as connection:
        _execute_many(connection, _schema_statements())
        _seed_system_settings(connection)
        _seed_rule_system(connection)          # ← 추가
    logger.info("SUCCESS: db.initialize_database path=%s", _db_path())
```

### Task 2: `backend/services/engine/rule_resolver.py` 신규 생성

```python
"""Rule Resolver — 종목별 최종 룰 계산 (우선순위 레이어 병합).

우선순위 (높을수록 우선):
  1. Emergency Halt / Global Risk Guard  ← 이 파일 밖에서 적용
  2. 장마감 강제청산 정책              ← 이 파일 밖에서 적용
  3. Symbol Override
  4. Risk Profile
  5. Base RulePack
  6. Daily Trading Plan overrides
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..db import get_connection

logger = logging.getLogger("RuleResolver")

_PROFILES = ("LOW_VOL", "MID_VOL", "HIGH_VOL", "THEME_SPIKE")


def get_active_base_rulepack() -> dict[str, Any]:
    """현재 활성 Base RulePack 반환. 없으면 기본값."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM base_rulepacks WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    if not row:
        logger.warning("WARN: [RuleResolver] base_rulepack 없음 — 기본값 사용")
        return {
            "id": "base-v1.0",
            "version": "1.0",
            "take_profit_enabled": False,
            "force_daily_close": True,
            "force_exit_time": "15:20:00",
            "stop_price_can_only_increase": True,
        }
    d = dict(row)
    try:
        d["order_execution"] = json.loads(d.get("order_execution") or "{}")
    except Exception:
        d["order_execution"] = {}
    d["take_profit_enabled"] = bool(d.get("take_profit_enabled", 0))
    d["force_daily_close"] = bool(d.get("force_daily_close", 1))
    d["stop_price_can_only_increase"] = bool(d.get("stop_price_can_only_increase", 1))
    return d


def get_active_profile_pack() -> dict[str, Any]:
    """현재 활성 Risk Profile Pack 반환."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM risk_profile_packs WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    if not row:
        logger.warning("WARN: [RuleResolver] risk_profile_pack 없음 — 빈 profiles")
        return {"id": "profile-v1.0", "version": "1.0", "profiles": {}}
    d = dict(row)
    try:
        d["profiles"] = json.loads(d.get("profiles") or "{}")
    except Exception:
        d["profiles"] = {}
    return d


def get_active_daily_plan(trade_date: str) -> dict[str, Any] | None:
    """특정 날짜의 활성 Daily Trading Plan 반환."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM daily_trading_plans WHERE trade_date = ? AND status IN ('validated','active')"
            " ORDER BY created_at DESC LIMIT 1",
            (trade_date,),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    for key in ("daily_overrides", "symbol_assignments", "excluded_symbols", "validation_result"):
        try:
            d[key] = json.loads(d.get(key) or "{}") if key in ("daily_overrides", "validation_result") else json.loads(d.get(key) or "[]")
        except Exception:
            d[key] = {} if key in ("daily_overrides", "validation_result") else []
    return d


def get_symbol_overrides() -> dict[str, dict[str, Any]]:
    """활성 symbol_overrides 전체 반환. {symbol_code: override_values}."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT symbol_code, override_values FROM symbol_overrides WHERE is_active = 1"
        ).fetchall()
    result = {}
    for row in rows:
        try:
            result[row["symbol_code"]] = json.loads(row["override_values"] or "{}")
        except Exception:
            result[row["symbol_code"]] = {}
    return result


def resolve_symbol_rule(
    symbol_code: str,
    base_rulepack: dict[str, Any],
    profile_pack: dict[str, Any],
    daily_plan: dict[str, Any] | None,
    symbol_overrides: dict[str, dict[str, Any]],
    global_risk: dict[str, Any],
) -> dict[str, Any]:
    """종목별 최종 룰 계산.

    레이어 병합 순서 (나중에 덮음 = 높은 우선순위):
      base_rulepack → profile → symbol_override
    그 후 Global Risk Guard 강제 적용.
    """
    # 1. Daily Plan에서 배정 프로필 조회
    assignments: dict[str, dict] = {}
    if daily_plan:
        for a in daily_plan.get("symbol_assignments", []):
            code = str(a.get("code") or "").strip()
            if code:
                assignments[code] = a
    assignment = assignments.get(symbol_code, {})
    profile_name = assignment.get("profile", "MID_VOL")
    if profile_name not in _PROFILES:
        profile_name = "MID_VOL"

    profiles = profile_pack.get("profiles", {})
    profile_rule = profiles.get(profile_name, {})

    # 2. 레이어 병합
    final: dict[str, Any] = {}
    final.update({k: v for k, v in base_rulepack.items() if k not in ("id", "version", "created_at", "is_active", "order_execution")})
    final.update(profile_rule)
    final.update(symbol_overrides.get(symbol_code, {}))

    # 3. Global Risk Guard 강제 (절대 완화 불가)
    guard_max_pos_rate = float(global_risk.get("max_position_rate_per_stock", 0.10))
    final["max_position_rate"] = min(
        float(final.get("max_position_rate", guard_max_pos_rate)),
        guard_max_pos_rate,
    )
    final["force_exit_time"] = global_risk.get("force_exit_time", "15:20:00")
    final["new_entry_cutoff_time"] = global_risk.get("new_entry_cutoff_time", "15:10:00")
    final["take_profit_enabled"] = False               # 항상 OFF
    final["stop_price_can_only_increase"] = True       # 항상 ON
    final["profile_assigned"] = profile_name
    final["assignment_reason"] = assignment.get("reason", "")

    return final
```

### Task 3: `backend/services/engine/rule_cache.py` 신규 생성

```python
"""Rule Cache — 장 시작 시 종목별 최종 룰을 메모리에 캐시.

WS tick 처리 시 DB 접근 없이 O(1)로 룰 조회.
09:00 load_daily_rules() → 장중 get_rule() → 장마감 clear_cache()
"""

from __future__ import annotations

import logging
from typing import Any

from ..settings_store import get_setting
from .rule_resolver import (
    get_active_base_rulepack,
    get_active_daily_plan,
    get_active_profile_pack,
    get_symbol_overrides,
    resolve_symbol_rule,
)

logger = logging.getLogger("RuleCache")

_cache: dict[str, dict[str, Any]] = {}   # {symbol_code: final_rule}
_meta: dict[str, Any] = {}               # 오늘 로드된 메타 정보


def _global_risk() -> dict[str, Any]:
    """system_settings에서 Global Risk Guard 값 조회."""
    return {
        "daily_loss_limit": float(get_setting("risk.daily_loss_limit_percent", -2.0) or -2.0),
        "max_positions": int(get_setting("risk.max_positions", 5) or 5),
        "max_position_rate_per_stock": float(get_setting("risk.max_position_rate_per_stock", 0.10) or 0.10),
        "force_exit_time": "15:20:00",
        "new_entry_cutoff_time": "15:10:00",
    }


def load_daily_rules(trade_date: str, symbol_codes: list[str]) -> int:
    """S6 시작 시 호출 — 오늘 전체 후보 종목 룰을 메모리에 캐시.

    Returns:
        캐시된 종목 수.
    """
    global _cache, _meta
    _cache = {}

    base = get_active_base_rulepack()
    pack = get_active_profile_pack()
    plan = get_active_daily_plan(trade_date)
    overrides = get_symbol_overrides()
    risk = _global_risk()

    for code in symbol_codes:
        _cache[code] = resolve_symbol_rule(
            symbol_code=code,
            base_rulepack=base,
            profile_pack=pack,
            daily_plan=plan,
            symbol_overrides=overrides,
            global_risk=risk,
        )

    _meta = {
        "trade_date": trade_date,
        "base_rulepack_id": base.get("id", ""),
        "risk_profile_pack_id": pack.get("id", ""),
        "daily_plan_id": plan.get("id", "") if plan else "",
        "cached_count": len(_cache),
    }
    logger.info("SUCCESS: [RuleCache] loaded symbols=%d date=%s base=%s pack=%s",
                len(_cache), trade_date, _meta["base_rulepack_id"], _meta["risk_profile_pack_id"])
    return len(_cache)


def get_rule(symbol_code: str) -> dict[str, Any] | None:
    """WS tick 처리 시 호출 — DB 접근 없이 캐시에서 반환."""
    return _cache.get(symbol_code)


def get_meta() -> dict[str, Any]:
    """현재 캐시 메타 정보 반환."""
    return dict(_meta)


def clear_cache() -> None:
    """장마감 후 호출 — 캐시 초기화."""
    global _cache, _meta
    count = len(_cache)
    _cache = {}
    _meta = {}
    logger.info("SUCCESS: [RuleCache] cleared count=%d", count)


def get_all_cached() -> dict[str, dict[str, Any]]:
    """전체 캐시 반환 (API 조회용)."""
    return dict(_cache)
```

### Task 4: `backend/services/engine/daily_plan.py` 신규 생성

```python
"""S5 Daily Trading Plan 생성 서비스 (08:45 KST).

S4 스크리닝 결과를 기반으로 LLM이 각 종목에 Risk Profile을 배정한다.
기존 RulePack 전체 생성 방식을 대체한다.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from ..db import get_connection
from . import llm_router
from .hybrid_screening import get_today_screening
from .market_tone import get_today_market_tone

logger = logging.getLogger("DailyPlanService")

_PROFILES = ("LOW_VOL", "MID_VOL", "HIGH_VOL", "THEME_SPIKE")

_VALIDATION_RULES = [
    "schema_valid",
    "profiles_exist",
    "symbol_assignments_valid",
    "global_risk_guard_ok",
    "take_profit_off",
    "stop_price_increase_only",
    "force_exit_on",
    "runtime_interpretable",
]


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _today_kst() -> str:
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


def _build_prompt(candidates: list[dict], market_tone_data: dict | None) -> str:
    tone = market_tone_data.get("tone", "neutral") if market_tone_data else "neutral"
    tone_summary = market_tone_data.get("summary", "") if market_tone_data else ""
    cand_rows = []
    for c in candidates[:30]:
        cand_rows.append({
            "code": c.get("symbol") or c.get("ticker") or "",
            "name": c.get("name") or "",
            "score": round(float(c.get("suitability_score") or c.get("score") or 0), 3),
            "change_rate": c.get("change_rate") or c.get("chg_rate") or 0,
            "trade_amount": c.get("trade_amount") or 0,
            "reason": c.get("reason") or c.get("analysis") or "",
        })

    return f"""# 08:45 Daily Trading Plan 생성

## 역할
오늘 매매 후보 종목에 Risk Profile을 배정한다.
Risk Profile은 LOW_VOL / MID_VOL / HIGH_VOL / THEME_SPIKE 4종이다.

## 배정 기준
- LOW_VOL: 대형주, 저변동성, 안정적 거래대금
- MID_VOL: 일반 중형주, 보통 변동성
- HIGH_VOL: 고변동성, 최근 급등락, 변동성 큰 섹터
- THEME_SPIKE: 당일 급등 테마주, 뉴스/테마 기반, 거래량 급증, 고위험

## 오늘 시장 톤
tone: {tone}
요약: {tone_summary}

## 후보 종목 (S4 스크리닝 결과)
{json.dumps(cand_rows, ensure_ascii=False, indent=2)}

## 출력 형식 (JSON만, 다른 텍스트 없이)
{{
  "trading_intensity": "aggressive|normal|defensive",
  "new_entry_allowed": true,
  "daily_overrides": {{
    "volume_filter_multiplier": 2.0,
    "min_ai_confidence": 0.65,
    "max_theme_spike_positions": 1
  }},
  "symbol_assignments": [
    {{"code": "005930", "name": "삼성전자", "profile": "LOW_VOL", "reason": "대형주 저변동성"}}
  ],
  "excluded_symbols": [],
  "llm_summary": "오늘 시장 톤과 종목 배정에 대한 간략한 요약"
}}
"""


def _validate_plan(plan_data: dict[str, Any]) -> dict[str, str]:
    """8가지 검증. 각 항목: 'pass' | 'fail:사유'."""
    result: dict[str, str] = {}

    # 1. schema_valid
    required_keys = {"trading_intensity", "new_entry_allowed", "symbol_assignments", "daily_overrides"}
    missing = required_keys - set(plan_data.keys())
    result["schema_valid"] = "pass" if not missing else f"fail:missing_keys={missing}"

    # 2. profiles_exist
    assignments = plan_data.get("symbol_assignments", [])
    bad_profiles = [a.get("profile") for a in assignments if a.get("profile") not in _PROFILES]
    result["profiles_exist"] = "pass" if not bad_profiles else f"fail:unknown_profiles={bad_profiles}"

    # 3. symbol_assignments_valid
    valid_assignments = [a for a in assignments if a.get("code") and a.get("profile") in _PROFILES]
    result["symbol_assignments_valid"] = "pass" if valid_assignments else "fail:no_valid_assignments"

    # 4. global_risk_guard_ok — daily_overrides는 리스크를 완화할 수 없음 (현재는 형식 검증만)
    result["global_risk_guard_ok"] = "pass"

    # 5. take_profit_off — Daily Plan에 take_profit 활성화 시도 차단
    overrides = plan_data.get("daily_overrides", {})
    if overrides.get("take_profit_enabled", False):
        result["take_profit_off"] = "fail:take_profit_enabled_in_plan"
    else:
        result["take_profit_off"] = "pass"

    # 6. stop_price_increase_only
    result["stop_price_increase_only"] = "pass"  # Base RulePack에서 강제, plan에선 변경 불가

    # 7. force_exit_on
    if overrides.get("force_daily_close") is False:
        result["force_exit_on"] = "fail:force_daily_close_disabled"
    else:
        result["force_exit_on"] = "pass"

    # 8. runtime_interpretable
    try:
        json.dumps(plan_data)
        result["runtime_interpretable"] = "pass"
    except Exception as e:
        result["runtime_interpretable"] = f"fail:{e}"

    return result


def get_today_daily_plan(trade_date: str | None = None) -> dict[str, Any] | None:
    """오늘 활성 Daily Trading Plan 조회."""
    if not trade_date:
        trade_date = _today_kst()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM daily_trading_plans WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
            (trade_date,),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    for key in ("daily_overrides", "validation_result"):
        try:
            d[key] = json.loads(d.get(key) or "{}")
        except Exception:
            d[key] = {}
    for key in ("symbol_assignments", "excluded_symbols"):
        try:
            d[key] = json.loads(d.get(key) or "[]")
        except Exception:
            d[key] = []
    return d


async def run_daily_plan_generation(trade_date: str | None = None) -> dict[str, Any]:
    """S5: Daily Trading Plan 생성 메인 함수."""
    if not trade_date:
        trade_date = _today_kst()
    logger.info("START: [S5] Daily Plan generation date=%s", trade_date)

    # S4 스크리닝 결과 조회
    screening = get_today_screening(trade_date)
    candidates = screening.get("candidates", []) if screening else []
    if not candidates:
        logger.warning("WARN: [S5] S4 스크리닝 결과 없음 — MID_VOL 기본 배정으로 진행")

    # 시장 톤 조회
    market_tone = get_today_market_tone(trade_date) if hasattr(get_today_market_tone, '__call__') else None

    # LLM 프롬프트 생성 및 호출
    prompt = _build_prompt(candidates, market_tone)
    plan_data: dict[str, Any] = {}
    provider = "none"

    try:
        response_text, provider = await llm_router.call_llm(
            prompt=prompt,
            system="당신은 단타 자동매매 봇의 일일 거래 계획을 생성하는 AI입니다. JSON만 출력하세요.",
            max_tokens=2000,
        )
        # JSON 파싱
        import re
        json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if json_match:
            plan_data = json.loads(json_match.group())
        else:
            raise ValueError("JSON not found in LLM response")
    except Exception as e:
        logger.error("FAIL: [S5] LLM 호출 실패 — 기본값 사용 error=%s", e)
        provider = "none"
        plan_data = {
            "trading_intensity": "normal",
            "new_entry_allowed": True,
            "daily_overrides": {"volume_filter_multiplier": 2.0, "min_ai_confidence": 0.65, "max_theme_spike_positions": 1},
            "symbol_assignments": [
                {"code": c.get("symbol") or c.get("ticker") or "", "name": c.get("name") or "", "profile": "MID_VOL", "reason": "LLM 실패 기본 배정"}
                for c in candidates if (c.get("symbol") or c.get("ticker"))
            ],
            "excluded_symbols": [],
            "llm_summary": f"LLM 호출 실패 ({e}). 모든 종목 MID_VOL 기본 배정.",
        }

    # 검증
    validation = _validate_plan(plan_data)
    all_pass = all(v == "pass" for v in validation.values())
    status = "validated" if all_pass else "draft"

    plan_id = f"daily-{trade_date}"
    now = _now_utc()

    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO daily_trading_plans
                (id, trade_date, market_tone, trading_intensity, base_rulepack_id,
                 risk_profile_pack_id, new_entry_allowed, daily_overrides,
                 symbol_assignments, excluded_symbols, llm_summary, provider,
                 status, validation_result, created_at, activated_at)
            VALUES (?, ?, ?, ?, 'base-v1.0', 'profile-v1.0', ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                plan_id,
                trade_date,
                market_tone.get("tone", "neutral") if market_tone else "neutral",
                plan_data.get("trading_intensity", "normal"),
                1 if plan_data.get("new_entry_allowed", True) else 0,
                json.dumps(plan_data.get("daily_overrides", {}), ensure_ascii=False),
                json.dumps(plan_data.get("symbol_assignments", []), ensure_ascii=False),
                json.dumps(plan_data.get("excluded_symbols", []), ensure_ascii=False),
                plan_data.get("llm_summary", ""),
                provider,
                status,
                json.dumps(validation, ensure_ascii=False),
                now,
            ),
        )

    logger.info("SUCCESS: [S5] Daily Plan saved id=%s status=%s provider=%s", plan_id, status, provider)
    return {
        "ok": True,
        "plan_id": plan_id,
        "trade_date": trade_date,
        "status": status,
        "provider": provider,
        "validation": validation,
        "candidates_count": len(candidates),
        "assignments_count": len(plan_data.get("symbol_assignments", [])),
    }
```

### Task 5: `backend/services/engine/position_manager.py` 전면 수정

기존 파일을 아래로 **완전히 교체**한다.

```python
"""S8 Position Manager — 초기손절 + 트레일링스탑 + 강제청산.

고정 익절(take_profit)은 사용하지 않는다.
손절선은 절대 하향되지 않는다 (stop_price_can_only_increase = True).

청산 우선순위:
  1. INITIAL_STOP_LOSS  — 진입 후 초기 손절선 이탈
  2. TRAILING_STOP      — 트레일링 스탑 이탈
  3. TIME_EXIT          — 최대 보유 시간 초과 (손익분기 미달 시)
  4. DAILY_FORCE_EXIT   — 장마감 강제청산 (15:20 이후)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection
from ..kis.realtime_ws import realtime_ws_manager

logger = logging.getLogger("PositionManager")

_DEFAULT_RULE = {
    "initial_stop_loss": -0.03,
    "trailing_activate_profit": 0.025,
    "trailing_stop_rate": 0.03,
    "max_position_rate": 0.12,
    "max_holding_minutes": 180,
    "force_exit_time": "15:20:00",
    "new_entry_cutoff_time": "15:10:00",
    "profile_assigned": "MID_VOL",
}

EXIT_REASONS = ("INITIAL_STOP_LOSS", "TRAILING_STOP", "TIME_EXIT", "DAILY_FORCE_EXIT", "EMERGENCY_HALT", "MANUAL_EXIT")


def _now_kst() -> datetime:
    return datetime.now(ZoneInfo("Asia/Seoul"))


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", "").strip() or default)
    except (TypeError, ValueError):
        return default


def _upsert_stop_state(position_id: str, data: dict[str, Any]) -> None:
    now = _now_kst().isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO position_stop_states
                (position_id, symbol_code, entry_price, highest_price_since_entry,
                 initial_stop_price, trailing_stop_price, active_stop_price,
                 trailing_active, profile_assigned, last_updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                position_id,
                data["symbol_code"],
                data["entry_price"],
                data["highest_price_since_entry"],
                data["initial_stop_price"],
                data["trailing_stop_price"],
                data["active_stop_price"],
                1 if data["trailing_active"] else 0,
                data["profile_assigned"],
                now,
            ),
        )


class PositionManager:
    """S8: 보유 포지션의 손절/트레일링/강제청산을 실시간 WS tick으로 감시한다."""

    def __init__(self):
        self._positions: dict[str, dict[str, Any]] = {}
        self._closing: set[str] = set()
        self._active = False

    def add_position(
        self,
        symbol: str,
        name: str,
        qty: int,
        entry_price: float,
        final_rule: dict[str, Any],
    ) -> None:
        """포지션 등록. final_rule은 rule_cache.get_rule() 결과를 넘긴다."""
        safe_symbol = str(symbol or "").strip()
        safe_qty = int(qty or 0)
        safe_entry = _to_float(entry_price)
        if not safe_symbol or safe_qty <= 0 or safe_entry <= 0:
            logger.warning("WARN: [S8] invalid position symbol=%s qty=%s entry=%s", symbol, qty, entry_price)
            return

        rule = {**_DEFAULT_RULE, **(final_rule or {})}
        initial_stop_loss = _to_float(rule.get("initial_stop_loss"), -0.03)
        if initial_stop_loss > 0:
            initial_stop_loss = -initial_stop_loss  # 양수로 들어온 경우 보정
        trailing_activate = _to_float(rule.get("trailing_activate_profit"), 0.025)
        trailing_rate = _to_float(rule.get("trailing_stop_rate"), 0.03)
        max_minutes = int(rule.get("max_holding_minutes") or 180)
        profile = str(rule.get("profile_assigned") or "MID_VOL")

        initial_stop_price = safe_entry * (1 + initial_stop_loss)
        position_id = f"{safe_symbol}-{_now_kst().strftime('%H%M%S%f')}"

        self._positions[safe_symbol] = {
            "position_id": position_id,
            "symbol": safe_symbol,
            "name": str(name or ""),
            "qty": safe_qty,
            "entry_price": safe_entry,
            "entry_time": _now_kst().isoformat(),
            "profile_assigned": profile,
            # 손절선 (절대 하향 불가)
            "initial_stop_price": initial_stop_price,
            "active_stop_price": initial_stop_price,
            # 트레일링
            "highest_price_since_entry": safe_entry,
            "trailing_active": False,
            "trailing_stop_price": initial_stop_price,
            "trailing_activate_profit": trailing_activate,
            "trailing_stop_rate": trailing_rate,
            # 시간 기반
            "max_holding_minutes": max_minutes,
            "force_exit_time": str(rule.get("force_exit_time") or "15:20:00"),
        }
        self._closing.discard(safe_symbol)

        _upsert_stop_state(position_id, {
            "symbol_code": safe_symbol,
            "entry_price": safe_entry,
            "highest_price_since_entry": safe_entry,
            "initial_stop_price": initial_stop_price,
            "trailing_stop_price": initial_stop_price,
            "active_stop_price": initial_stop_price,
            "trailing_active": False,
            "profile_assigned": profile,
        })
        logger.info("SUCCESS: [S8] position added symbol=%s profile=%s entry=%.2f stop=%.2f",
                    safe_symbol, profile, safe_entry, initial_stop_price)

    def remove_position(self, symbol: str) -> None:
        safe_symbol = str(symbol or "").strip()
        self._positions.pop(safe_symbol, None)
        self._closing.discard(safe_symbol)
        logger.info("SUCCESS: [S8] position removed symbol=%s", safe_symbol)

    def get_positions(self) -> list[dict[str, Any]]:
        return [dict(p) for p in self._positions.values()]

    async def on_tick(self, tick: dict[str, Any]) -> None:
        symbol = str(tick.get("symbol") or "").strip()
        position = self._positions.get(symbol)
        if not position or symbol in self._closing:
            return

        price = _to_float(tick.get("price"))
        if price <= 0:
            return

        # 트레일링 상태 업데이트
        self._update_trailing(position, price)

        reason = self._exit_reason(position, price)
        if not reason:
            return

        self._closing.add(symbol)
        logger.info("START: [S8] exit symbol=%s reason=%s price=%.2f", symbol, reason, price)
        try:
            from .order_executor import order_executor
            await order_executor.execute_sell(symbol=symbol, qty=int(position["qty"]), price=0, reason=reason)
            logger.info("SUCCESS: [S8] exit order symbol=%s reason=%s", symbol, reason)
        except Exception as exc:
            self._closing.discard(symbol)
            logger.error("FAIL: [S8] exit order failed symbol=%s error=%s", symbol, exc)

    def _update_trailing(self, position: dict[str, Any], price: float) -> None:
        """트레일링 스탑 상태 업데이트. 손절선은 절대 하향하지 않는다."""
        entry_price = _to_float(position["entry_price"])
        prev_high = _to_float(position["highest_price_since_entry"])
        new_high = max(prev_high, price)
        position["highest_price_since_entry"] = new_high

        trailing_activate = _to_float(position["trailing_activate_profit"])
        trailing_rate = _to_float(position["trailing_stop_rate"])

        # 트레일링 활성화 여부
        if not position["trailing_active"] and price >= entry_price * (1 + trailing_activate):
            position["trailing_active"] = True
            logger.info("INFO: [S8] trailing activated symbol=%s high=%.2f", position["symbol"], new_high)

        # 트레일링 손절선 계산
        new_trailing_stop = new_high * (1 - trailing_rate)
        position["trailing_stop_price"] = new_trailing_stop

        # active_stop_price는 절대 하향 불가
        prev_active = _to_float(position["active_stop_price"])
        new_active = max(prev_active, position["initial_stop_price"], new_trailing_stop if position["trailing_active"] else 0)
        position["active_stop_price"] = new_active

        # DB 갱신 (매 tick마다 하면 부하 → 고점 변경 시에만)
        if new_high > prev_high:
            _upsert_stop_state(position["position_id"], {
                "symbol_code": position["symbol"],
                "entry_price": entry_price,
                "highest_price_since_entry": new_high,
                "initial_stop_price": _to_float(position["initial_stop_price"]),
                "trailing_stop_price": new_trailing_stop,
                "active_stop_price": new_active,
                "trailing_active": position["trailing_active"],
                "profile_assigned": position.get("profile_assigned", "MID_VOL"),
            })

    def _exit_reason(self, position: dict[str, Any], price: float) -> str:
        now = _now_kst()
        active_stop = _to_float(position["active_stop_price"])

        # 1. 강제청산 시간 (최우선)
        force_time_str = str(position.get("force_exit_time") or "15:20:00")
        try:
            h, m, s = map(int, force_time_str.split(":"))
            force_dt = now.replace(hour=h, minute=m, second=s, microsecond=0)
            if now >= force_dt:
                return "DAILY_FORCE_EXIT"
        except Exception:
            pass

        # 2. 초기손절 / 트레일링 손절 (active_stop_price 이탈)
        if price <= active_stop:
            if position["trailing_active"]:
                return "TRAILING_STOP"
            return "INITIAL_STOP_LOSS"

        # 3. 시간 손절 (최대 보유 시간 초과 + 손익분기 미달)
        try:
            entry_time = datetime.fromisoformat(position["entry_time"])
            if entry_time.tzinfo is None:
                entry_time = entry_time.replace(tzinfo=ZoneInfo("Asia/Seoul"))
            max_minutes = int(position.get("max_holding_minutes") or 180)
            entry_price = _to_float(position["entry_price"])
            pnl_pct = (price - entry_price) / entry_price if entry_price > 0 else 0
            if now - entry_time >= timedelta(minutes=max_minutes) and pnl_pct < 0.005:
                return "TIME_EXIT"
        except Exception:
            pass

        return ""

    def activate(self) -> None:
        if not self._active:
            realtime_ws_manager.register_tick_callback(self.on_tick)
            self._active = True
            logger.info("SUCCESS: [S8] PositionManager activated")

    def deactivate(self) -> None:
        if self._active:
            realtime_ws_manager.unregister_tick_callback(self.on_tick)
            self._active = False
            logger.info("SUCCESS: [S8] PositionManager deactivated")


position_manager = PositionManager()
```

### Task 6: `backend/services/engine/decision_engine.py` 수정

기존 파일에서 아래 변경 사항만 적용한다:

1. import에서 `from .rulepack_store import get_active_rulepack_for_date` 제거
2. 아래 import 추가:
   ```python
   from .rule_cache import load_daily_rules, get_rule, clear_cache, get_meta
   ```
3. `DecisionEngine.__init__`에서 `self._rulepack` 제거
4. `activate()` 메서드에서:
   - `rulepack = get_active_rulepack_for_date(today)` 및 관련 early-return 블록 제거
   - candidates 로드 직후, `self._candidates` 구성 후에 `load_daily_rules(today, list(self._candidates.keys()))` 호출
   - `return` 값에 `"cache_meta": get_meta()` 추가
5. `_on_tick()`에서 `rules = self._rulepack.get("layer3_entry", {}) ...` 라인 제거
6. `_evaluate_rules()`에서:
   - `rules` 파라미터를 `final_rule` 으로 변경
   - `ai_conf_min = float(final_rule.get("ai_confidence_min", 0.0) or 0.0)` 유지
   - rule은 `get_rule(symbol)` 로 조회해 넘김
7. `_emit_signal()`에서 INSERT 쿼리에 `profile_assigned` 컬럼 추가:
   - `candidate`에서 profile을 가져오거나 `get_rule(symbol).get("profile_assigned", "MID_VOL")`
8. `deactivate()`에서 `clear_cache()` 호출 추가
9. `_ensure_signals_table()` 함수는 유지하되 db.py에 이관됐으므로 `CREATE TABLE IF NOT EXISTS` 중복 실행은 무해함 (변경 불필요)

### Task 7: 검증

모든 수정/생성 파일에 대해:
```bash
python3 -m py_compile backend/services/db.py
python3 -m py_compile backend/services/engine/rule_resolver.py
python3 -m py_compile backend/services/engine/rule_cache.py
python3 -m py_compile backend/services/engine/daily_plan.py
python3 -m py_compile backend/services/engine/position_manager.py
python3 -m py_compile backend/services/engine/decision_engine.py
```

전부 통과해야 완료.

---

## 완료 기준

- [ ] db.py: 6개 신규 테이블 + trading_signals 이관 + seeding 함수
- [ ] rule_resolver.py: resolve_symbol_rule() 구현
- [ ] rule_cache.py: load/get/clear 구현
- [ ] daily_plan.py: run_daily_plan_generation() 구현
- [ ] position_manager.py: 트레일링 중심, take_profit 제거, position_stop_states 연동
- [ ] decision_engine.py: rule_cache 의존으로 전환
- [ ] py_compile 전부 통과
