# [CODEX] 레짐별 성과 분석 — 백엔드 구현

## 목표
"시장이 어떤 상황일 때 우리는 어떻게 거래하겠다" 최적 셋팅값 탐색을 위한
**데이터 수집 + 분석 API 4종** 구현.

---

## 작업 1 — `daily_context_snapshot` 테이블 생성 (db.py)

파일: `backend/services/db.py`

`_ensure_tables()` 또는 최초 호출 시 생성하는 함수에 아래 테이블 추가.
(파일 내 다른 CREATE TABLE IF NOT EXISTS 패턴을 그대로 따를 것)

```sql
CREATE TABLE IF NOT EXISTS daily_context_snapshot (
    trade_date           TEXT PRIMARY KEY,
    regime               TEXT NOT NULL DEFAULT 'neutral',
    risk_level           TEXT NOT NULL DEFAULT 'normal',
    rulepack_id          TEXT NOT NULL DEFAULT '',
    stop_loss_rate       REAL,
    take_profit_rate     REAL,
    max_positions        INTEGER,
    max_position_size_rate REAL,
    trailing_activate_profit REAL,
    trailing_stop_rate   REAL,
    new_entry_allowed    INTEGER DEFAULT 1,
    raw_rulepack_json    TEXT NOT NULL DEFAULT '{}',
    created_at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_daily_context_snapshot_trade_date
    ON daily_context_snapshot(trade_date);
```

---

## 작업 2 — Decision Engine activate() 시 컨텍스트 스냅샷 저장

파일: `backend/services/engine/decision_engine.py`

### 2-A. 함수 추가 (모듈 레벨, activate 함수 위에 추가)

```python
def _save_daily_context_snapshot(today: str) -> None:
    """오늘의 레짐 + RulePack 파라미터를 daily_context_snapshot에 저장한다.
    
    S6 activate() 시점에 호출 — 비치명적, 실패해도 거래 흐름 유지.
    """
    try:
        from ..db import get_connection
        from .market_tone import get_today_morning_context
        from .rulepack_generation import get_active_rulepack

        ctx = get_today_morning_context(today) or {}
        rulepack = get_active_rulepack(today) or {}
        risk = rulepack.get("risk_limits") or {}

        import json as _json
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        with get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO daily_context_snapshot
                    (trade_date, regime, risk_level, rulepack_id,
                     stop_loss_rate, take_profit_rate, max_positions,
                     max_position_size_rate, trailing_activate_profit,
                     trailing_stop_rate, new_entry_allowed,
                     raw_rulepack_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    today,
                    ctx.get("regime", "neutral"),
                    ctx.get("risk_level", "normal"),
                    rulepack.get("rulepack_id", ""),
                    risk.get("stop_loss_rate"),
                    risk.get("take_profit_rate"),
                    risk.get("max_positions"),
                    risk.get("max_position_size_rate"),
                    None,  # trailing_activate_profit — profile-level
                    None,  # trailing_stop_rate — profile-level
                    1 if rulepack.get("new_entry_allowed", True) else 0,
                    _json.dumps(rulepack, ensure_ascii=False),
                    now,
                ),
            )
        logger.info("INFO: [S6] daily_context_snapshot saved trade_date=%s regime=%s", today, ctx.get("regime"))
    except Exception as exc:
        logger.warning("WARN: [S6] daily_context_snapshot 저장 실패 (비치명) — %s", exc)
```

### 2-B. activate() 함수 내 호출

`activate()` 함수의 `_ensure_signals_table()` 호출 직후 한 줄 추가:

```python
_save_daily_context_snapshot(today)
```

---

## 작업 3 — `rulepack_generation.py`에 `get_active_rulepack` 함수 확인/추가

파일: `backend/services/engine/rulepack_generation.py`

이미 `get_active_rulepack(trade_date)` 함수가 있으면 그대로 사용.
없으면 아래 함수 추가:

```python
def get_active_rulepack(trade_date: str) -> dict | None:
    """특정 날짜의 active/validated 상태 RulePack을 반환한다."""
    import json as _json
    try:
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT rulepack_json FROM daily_rulepacks
                WHERE trade_date = ? AND status IN ('active','validated')
                ORDER BY created_at DESC LIMIT 1
                """,
                (trade_date,),
            ).fetchone()
        if row:
            return _json.loads(row[0]) if isinstance(row[0], str) else dict(row[0])
    except Exception:
        pass
    return None
```

(테이블명/컬럼명은 실제 코드에 맞게 수정할 것)

---

## 작업 4 — 레짐 분석 API 라우트 파일 신규 생성

파일: `backend/api/routes/regime_analytics.py` (신규 생성)

```python
"""레짐별 성과 분석 API — 시장 상황 × 설정값 × 결과 상관관계."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query

from ...services.db import get_connection

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])
logger = logging.getLogger("RegimeAnalyticsAPI")


def _get_date_range(days: int) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    end = now.strftime("%Y-%m-%d")
    start = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    return start, end


@router.get("/regime-performance")
async def get_regime_performance(days: int = Query(default=90, ge=7, le=365)) -> dict:
    """레짐별 집계 성과 반환.
    
    Returns:
        {
            "ok": true,
            "days": 90,
            "regimes": {
                "risk_on": {
                    "days": 5, "total_trades": 23, "win_count": 15, "loss_count": 8,
                    "win_rate_pct": 65.2, "avg_pnl_krw": 12500, "total_pnl_krw": 287500,
                    "best_day": "2026-05-20", "worst_day": "2026-05-15",
                    "avg_stop_loss_rate": -0.02, "avg_max_positions": 9
                },
                "neutral": {...},
                "risk_off": {...},
                "volatile": {...}
            },
            "date_range": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"},
            "data_days": 12
        }
    """
    start, end = _get_date_range(days)
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    s.regime,
                    s.risk_level,
                    s.stop_loss_rate,
                    s.take_profit_rate,
                    s.max_positions,
                    r.trade_date,
                    r.total_trades,
                    r.win_count,
                    r.loss_count,
                    r.total_pnl
                FROM daily_context_snapshot s
                LEFT JOIN daily_review_reports r ON s.trade_date = r.trade_date
                WHERE s.trade_date >= ? AND s.trade_date <= ?
                ORDER BY s.trade_date DESC
                """,
                (start, end),
            ).fetchall()
    except Exception as exc:
        logger.error("regime-performance query failed: %s", exc)
        return {"ok": False, "error": str(exc)}

    from collections import defaultdict
    regime_data: dict[str, list] = defaultdict(list)
    for row in rows:
        d = dict(row)
        regime_data[d.get("regime") or "neutral"].append(d)

    result: dict[str, dict] = {}
    for regime, entries in regime_data.items():
        valid = [e for e in entries if e.get("total_trades") is not None]
        if not valid:
            result[regime] = {
                "days": len(entries), "total_trades": 0, "win_count": 0,
                "loss_count": 0, "win_rate_pct": 0.0, "avg_pnl_krw": 0,
                "total_pnl_krw": 0, "best_day": None, "worst_day": None,
                "avg_stop_loss_rate": None, "avg_max_positions": None,
            }
            continue

        total_trades = sum(e.get("total_trades") or 0 for e in valid)
        win_count = sum(e.get("win_count") or 0 for e in valid)
        loss_count = sum(e.get("loss_count") or 0 for e in valid)
        total_pnl = sum(e.get("total_pnl") or 0 for e in valid)
        win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0.0

        sorted_by_pnl = sorted(valid, key=lambda e: e.get("total_pnl") or 0)
        worst_day = sorted_by_pnl[0]["trade_date"] if sorted_by_pnl else None
        best_day = sorted_by_pnl[-1]["trade_date"] if sorted_by_pnl else None

        stop_vals = [e["stop_loss_rate"] for e in entries if e.get("stop_loss_rate") is not None]
        pos_vals = [e["max_positions"] for e in entries if e.get("max_positions") is not None]

        result[regime] = {
            "days": len(entries),
            "total_trades": total_trades,
            "win_count": win_count,
            "loss_count": loss_count,
            "win_rate_pct": round(win_rate, 1),
            "avg_pnl_krw": round(total_pnl / len(valid)) if valid else 0,
            "total_pnl_krw": round(total_pnl),
            "best_day": best_day,
            "worst_day": worst_day,
            "avg_stop_loss_rate": round(sum(stop_vals) / len(stop_vals), 4) if stop_vals else None,
            "avg_max_positions": round(sum(pos_vals) / len(pos_vals), 1) if pos_vals else None,
        }

    return {
        "ok": True,
        "days": days,
        "regimes": result,
        "date_range": {"start": start, "end": end},
        "data_days": len(rows),
    }


@router.get("/parameter-history")
async def get_parameter_history(days: int = Query(default=90, ge=7, le=365)) -> dict:
    """날짜별 레짐 + 파라미터 + 성과 히스토리 반환 (차트용).
    
    Returns:
        {
            "ok": true,
            "rows": [
                {
                    "date": "2026-05-20",
                    "regime": "risk_on",
                    "risk_level": "normal",
                    "stop_loss_rate": -0.02,
                    "take_profit_rate": 0.05,
                    "max_positions": 10,
                    "total_trades": 8,
                    "win_count": 6,
                    "win_rate_pct": 75.0,
                    "total_pnl": 45000
                },
                ...
            ]
        }
    """
    start, end = _get_date_range(days)
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    s.trade_date AS date,
                    s.regime,
                    s.risk_level,
                    s.stop_loss_rate,
                    s.take_profit_rate,
                    s.max_positions,
                    s.max_position_size_rate,
                    COALESCE(r.total_trades, 0) AS total_trades,
                    COALESCE(r.win_count, 0) AS win_count,
                    COALESCE(r.loss_count, 0) AS loss_count,
                    COALESCE(r.total_pnl, 0) AS total_pnl
                FROM daily_context_snapshot s
                LEFT JOIN daily_review_reports r ON s.trade_date = r.trade_date
                WHERE s.trade_date >= ? AND s.trade_date <= ?
                ORDER BY s.trade_date ASC
                """,
                (start, end),
            ).fetchall()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    result = []
    for row in rows:
        d = dict(row)
        trades = d.get("total_trades") or 0
        wins = d.get("win_count") or 0
        d["win_rate_pct"] = round(wins / trades * 100, 1) if trades > 0 else None
        result.append(d)

    return {"ok": True, "rows": result}


@router.get("/regime-recommendation")
async def get_regime_recommendation(days: int = Query(default=90, ge=14, le=365)) -> dict:
    """레짐별 최적 설정값 추천 반환.
    
    데이터가 부족한 레짐은 기본값 + 주의 플래그 반환.
    
    Returns:
        {
            "ok": true,
            "recommendations": {
                "risk_on": {
                    "confidence": "high",   # high/medium/low/no_data
                    "data_days": 12,
                    "settings": {
                        "max_positions": 9,
                        "stop_loss_rate": -0.020,
                        "take_profit_rate": 0.050,
                        "max_position_size_rate": 0.10
                    },
                    "rationale": "12일 데이터 기준 평균 승률 68.3%, 평균 손절 -2.0%"
                },
                ...
            },
            "min_data_days_for_confidence": 10
        }
    """
    # 성과 데이터 먼저 가져오기
    perf_response = await get_regime_performance(days=days)
    if not perf_response.get("ok"):
        return {"ok": False, "error": "regime-performance query failed"}

    regimes_data = perf_response.get("regimes", {})

    MIN_DAYS = 10  # 신뢰도 high 기준
    MED_DAYS = 4   # 신뢰도 medium 기준

    # 레짐별 기본값 (데이터 없을 때 fallback)
    defaults = {
        "risk_on":   {"max_positions": 10, "stop_loss_rate": -0.020, "take_profit_rate": 0.050, "max_position_size_rate": 0.10},
        "neutral":   {"max_positions": 7,  "stop_loss_rate": -0.020, "take_profit_rate": 0.040, "max_position_size_rate": 0.10},
        "risk_off":  {"max_positions": 5,  "stop_loss_rate": -0.015, "take_profit_rate": 0.030, "max_position_size_rate": 0.08},
        "volatile":  {"max_positions": 3,  "stop_loss_rate": -0.015, "take_profit_rate": 0.040, "max_position_size_rate": 0.07},
    }

    recommendations = {}
    for regime in ["risk_on", "neutral", "risk_off", "volatile"]:
        data = regimes_data.get(regime, {})
        data_days = data.get("days", 0)
        win_rate = data.get("win_rate_pct", 0)
        avg_stop = data.get("avg_stop_loss_rate")
        avg_pos = data.get("avg_max_positions")

        if data_days >= MIN_DAYS and data.get("total_trades", 0) > 0:
            confidence = "high"
            # 실적 기반 설정 추천
            settings = {
                "max_positions": round(avg_pos) if avg_pos else defaults[regime]["max_positions"],
                "stop_loss_rate": round(avg_stop, 3) if avg_stop else defaults[regime]["stop_loss_rate"],
                "take_profit_rate": defaults[regime]["take_profit_rate"],
                "max_position_size_rate": defaults[regime]["max_position_size_rate"],
            }
            rationale = f"{data_days}일 데이터 기준 승률 {win_rate}%, 평균 손절 {avg_stop:.3f}" if avg_stop else f"{data_days}일 데이터 기준 승률 {win_rate}%"
        elif data_days >= MED_DAYS and data.get("total_trades", 0) > 0:
            confidence = "medium"
            settings = defaults[regime].copy()
            if avg_pos:
                settings["max_positions"] = round(avg_pos)
            rationale = f"{data_days}일 데이터 (부족) — 기본값 + 부분 조정"
        elif data_days > 0:
            confidence = "low"
            settings = defaults[regime].copy()
            rationale = f"{data_days}일 데이터 (매우 부족) — 기본값 사용"
        else:
            confidence = "no_data"
            settings = defaults[regime].copy()
            rationale = "데이터 없음 — 기본값 사용"

        recommendations[regime] = {
            "confidence": confidence,
            "data_days": data_days,
            "total_trades": data.get("total_trades", 0),
            "win_rate_pct": win_rate,
            "settings": settings,
            "rationale": rationale,
        }

    return {
        "ok": True,
        "recommendations": recommendations,
        "min_data_days_for_confidence": MIN_DAYS,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
```

---

## 작업 5 — main.py에 라우터 등록

파일: `backend/main.py`

기존 라우터 import/include 패턴과 동일하게 추가:

```python
# import 섹션에 추가
from .api.routes.regime_analytics import router as regime_analytics_router

# app.include_router 섹션에 추가
app.include_router(regime_analytics_router)
```

---

## 검증 기준

1. `python -m py_compile backend/services/engine/decision_engine.py` — 에러 0
2. `python -m py_compile backend/api/routes/regime_analytics.py` — 에러 0
3. 서버 기동 시 `/api/v1/analytics/regime-performance` 200 응답
4. `/api/v1/analytics/parameter-history` 200 응답
5. `/api/v1/analytics/regime-recommendation` 200 응답 (데이터 없어도 기본값 반환)

---

## 주의사항

- 기존 테이블명·컬럼명은 반드시 실제 코드 확인 후 맞출 것
- `get_active_rulepack` 함수가 이미 있으면 중복 생성 금지
- `daily_review_reports.total_pnl` 컬럼명이 다르면 실제 컬럼명으로 수정
- 모든 DB 작업은 try/except로 감싸고 실패 시 빈 결과 반환

작업 완료 후 `docs/agent-comm/OUTBOX_CODEX_20260523_regime_analytics_backend.md` 에 결과 보고.
