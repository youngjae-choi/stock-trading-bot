# INBOX_EXECUTOR_trading_infra

## 작업 목적

Phase 2 백엔드 인프라 구현:
1. `daily_trading_plans` DB 컬럼 추가 (마이그레이션)
2. S5 완전 자동 파이프라인: `generated → validated → active`
3. 장중 수동 재실행 차단 (09:00~15:30 KST)
4. Order Pre-Flight Check 서비스 신규 구현
5. `order_executor.py`: rulepack_store 제거 → rule_cache + Pre-Flight 연동

작업 디렉토리: `/home/young/repos/stock-trading-bot`

---

## 변경 1 — DB 마이그레이션: `daily_trading_plans` 컬럼 추가

### `backend/services/db.py` 수정

`initialize_database()` 함수 안에서 `_schema_statements()` 실행 후, **기존 테이블이 있어도 새 컬럼을 추가**하는 마이그레이션 블록을 추가한다.

SQLite는 `ADD COLUMN`만 지원하고 `NOT NULL`에 DEFAULT가 있어야 기존 row에도 동작한다.

```python
# _migration_statements() 함수 신규 추가:
def _migration_statements() -> list[tuple[str, str]]:
    """기존 테이블에 누락된 컬럼을 추가하는 마이그레이션 목록.
    각 항목: (컬럼 존재 확인용 컬럼명, ALTER TABLE 구문)
    """
    return [
        ("creation_mode",  "ALTER TABLE daily_trading_plans ADD COLUMN creation_mode TEXT NOT NULL DEFAULT 'auto'"),
        ("created_by",     "ALTER TABLE daily_trading_plans ADD COLUMN created_by TEXT NOT NULL DEFAULT 'scheduler'"),
        ("s3_result_id",   "ALTER TABLE daily_trading_plans ADD COLUMN s3_result_id TEXT NOT NULL DEFAULT ''"),
        ("s4_result_id",   "ALTER TABLE daily_trading_plans ADD COLUMN s4_result_id TEXT NOT NULL DEFAULT ''"),
        ("validated_at",   "ALTER TABLE daily_trading_plans ADD COLUMN validated_at TEXT"),
        ("superseded_at",  "ALTER TABLE daily_trading_plans ADD COLUMN superseded_at TEXT"),
    ]
```

`initialize_database()` 내부에서 스키마 생성 후 마이그레이션 실행:
```python
# 마이그레이션: 기존 테이블에 누락된 컬럼 추가
with get_connection() as connection:
    existing_cols = {
        row[1] for row in connection.execute("PRAGMA table_info(daily_trading_plans)").fetchall()
    }
    for col_name, alter_sql in _migration_statements():
        if col_name not in existing_cols:
            connection.execute(alter_sql)
            logger.info("DB migration: added column %s to daily_trading_plans", col_name)
```

---

## 변경 2 — S5 완전 자동 파이프라인

### `backend/services/engine/daily_plan.py` 수정

#### 2-1. `run_daily_plan_generation()` 함수 시그니처 및 로직 변경

```python
async def run_daily_plan_generation(
    trade_date: str | None = None,
    creation_mode: str = "auto",   # auto | manual | dry_run
    created_by: str = "scheduler", # scheduler | user | system
    s3_result_id: str = "",
    s4_result_id: str = "",
) -> dict[str, Any]:
```

#### 2-2. INSERT 구문에 새 컬럼 추가

기존:
```python
INSERT OR REPLACE INTO daily_trading_plans
    (id, trade_date, market_tone, ..., status, validation_result, created_at, activated_at)
VALUES (?, ?, ..., ?, ?, ?, NULL)
```

변경:
```python
INSERT OR REPLACE INTO daily_trading_plans
    (id, trade_date, market_tone, trading_intensity, base_rulepack_id,
     risk_profile_pack_id, new_entry_allowed, daily_overrides,
     symbol_assignments, excluded_symbols, llm_summary, provider,
     status, validation_result, creation_mode, created_by,
     s3_result_id, s4_result_id, created_at, activated_at, validated_at, superseded_at)
VALUES (?, ?, ?, ?, 'base-v1.0', 'profile-v1.0', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)
```

#### 2-3. 저장 후 상태 = `generated` (검증 전)

현재:
```python
status = "validated" if all_pass else "draft"
```
변경:
```python
status = "generated"   # 항상 generated로 저장, 자동 파이프라인에서 validated/active로 전환
```

#### 2-4. 저장 후 자동 validation + activation 파이프라인

INSERT 완료 후 아래 두 단계를 자동 실행한다 (dry_run 모드는 제외):

```python
# 자동 검증 + 활성화 (dry_run 제외)
if creation_mode != "dry_run":
    plan_id, final_status = await _auto_validate_and_activate(plan_id, trade_date, plan_data)
    status = final_status
```

`_auto_validate_and_activate()` 함수 신규 추가:

```python
async def _auto_validate_and_activate(plan_id: str, trade_date: str, plan_data: dict) -> tuple[str, str]:
    """생성 직후 자동 검증 후 검증 통과 시 자동 active 처리."""
    validation = _validate_plan(plan_data)
    all_pass = all(v == "pass" for v in validation.values())
    now = _now_utc()

    if all_pass:
        # 이전 active plan을 superseded 처리
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE daily_trading_plans
                SET status = 'superseded', superseded_at = ?
                WHERE trade_date = ? AND status = 'active' AND id != ?
                """,
                (now, trade_date, plan_id),
            )
            conn.execute(
                """
                UPDATE daily_trading_plans
                SET status = 'active', validation_result = ?, validated_at = ?, activated_at = ?
                WHERE id = ?
                """,
                (json.dumps(validation, ensure_ascii=False), now, now, plan_id),
            )
        logger.info("SUCCESS: [S5] Auto-activated plan_id=%s trade_date=%s", plan_id, trade_date)
        return plan_id, "active"
    else:
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE daily_trading_plans
                SET status = 'validation_failed', validation_result = ?, validated_at = ?
                WHERE id = ?
                """,
                (json.dumps(validation, ensure_ascii=False), now, plan_id),
            )
        logger.warning("WARN: [S5] Validation failed plan_id=%s checks=%s", plan_id, validation)
        return plan_id, "validation_failed"
```

#### 2-5. `get_today_daily_plan()` 반환값에 새 컬럼 포함

`SELECT` 쿼리에 `creation_mode, created_by, s3_result_id, s4_result_id, validated_at, superseded_at` 컬럼 추가. 반환 dict에도 포함.

---

## 변경 3 — 장중 수동 재실행 차단

### `backend/api/routes/daily_plan.py` 수정

`POST /api/v1/daily-plan/generate` 엔드포인트에 시간 체크 추가:

```python
from zoneinfo import ZoneInfo

@router.post("/generate")
async def generate():
    """S5 수동 즉시 실행 — 장중(09:00~15:30 KST) 금지."""
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    market_start = now_kst.replace(hour=9, minute=0, second=0, microsecond=0)
    market_end   = now_kst.replace(hour=15, minute=30, second=0, microsecond=0)
    if market_start <= now_kst <= market_end:
        raise HTTPException(
            status_code=403,
            detail="장중(09:00~15:30 KST) 수동 재실행 금지. 장 종료 후 실행하세요.",
        )
    result = await run_daily_plan_generation(
        trade_date=_today_kst(),
        creation_mode="manual",
        created_by="user",
    )
    return {"ok": True, "payload": result}
```

---

## 변경 4 — Order Pre-Flight Check 서비스 신규 구현

### `backend/services/engine/order_preflight.py` 신규 생성

```python
"""S6-P Order Pre-Flight Check — KIS 주문 직전 안전 검증."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from ..db import get_connection

logger = logging.getLogger("OrderPreflight")

PREFLIGHT_OK = "ok"
PREFLIGHT_BLOCK = "block"


def _now_kst() -> datetime:
    return datetime.now(ZoneInfo("Asia/Seoul"))


def _now_utc_iso() -> str:
    from datetime import timezone
    return datetime.now(timezone.utc).isoformat()


def run_preflight(
    signal: dict,
    final_rule: dict,
    current_positions_count: int = 0,
) -> dict:
    """주문 직전 안전 검증. 반환값: {ok, preflight_id, checks, block_reason}"""
    checks = {}
    block_reasons = []

    now = _now_kst()

    # 1. 장 운영 시간 (09:00~15:20 매수 가능, 15:20 이후 신규매수 금지)
    market_open  = now.replace(hour=9,  minute=0, second=0, microsecond=0)
    entry_cutoff = now.replace(hour=15, minute=20, second=0, microsecond=0)
    if not (market_open <= now < entry_cutoff):
        checks["market_hours"] = PREFLIGHT_BLOCK
        block_reasons.append("신규매수 시간 외 (09:00~15:20)")
    else:
        checks["market_hours"] = PREFLIGHT_OK

    # 2. 종목당 최대 비중 (final_rule에서 position_size_pct 한도 확인)
    position_size_pct = float(final_rule.get("position_size_pct", 100.0) or 100.0)
    if position_size_pct > 30.0:
        checks["position_size"] = PREFLIGHT_BLOCK
        block_reasons.append(f"position_size_pct={position_size_pct} 초과 (최대 30%)")
    else:
        checks["position_size"] = PREFLIGHT_OK

    # 3. 최대 보유 종목 수 초과
    max_positions = int(final_rule.get("max_positions", 10) or 10)
    if current_positions_count >= max_positions:
        checks["max_positions"] = PREFLIGHT_BLOCK
        block_reasons.append(f"최대 보유 종목 도달 ({current_positions_count}/{max_positions})")
    else:
        checks["max_positions"] = PREFLIGHT_OK

    # 4. 트리거 가격 유효성
    trigger_price = float(signal.get("trigger_price") or 0)
    if trigger_price <= 0:
        checks["price_valid"] = PREFLIGHT_BLOCK
        block_reasons.append("trigger_price 유효하지 않음")
    else:
        checks["price_valid"] = PREFLIGHT_OK

    # 5. 신뢰도 최소값 (final_rule)
    ai_conf_min = float(final_rule.get("ai_confidence_min", 0.0) or 0.0)
    confidence = float(signal.get("confidence") or 0.0)
    if confidence < ai_conf_min:
        checks["ai_confidence"] = PREFLIGHT_BLOCK
        block_reasons.append(f"confidence={confidence:.2f} < 최소 {ai_conf_min:.2f}")
    else:
        checks["ai_confidence"] = PREFLIGHT_OK

    passed = len(block_reasons) == 0
    preflight_id = str(uuid.uuid4())
    created_at = _now_utc_iso()

    # DB 저장
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO order_preflight_checks
                    (id, signal_id, symbol, checks, block_reasons, result, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    preflight_id,
                    signal.get("id", ""),
                    signal.get("symbol", ""),
                    str(checks),
                    "|".join(block_reasons),
                    PREFLIGHT_OK if passed else PREFLIGHT_BLOCK,
                    created_at,
                ),
            )
    except Exception as e:
        logger.warning("WARN: preflight DB save failed: %s", e)

    if passed:
        logger.info("PREFLIGHT OK signal_id=%s symbol=%s", signal.get("id"), signal.get("symbol"))
    else:
        logger.warning("PREFLIGHT BLOCK signal_id=%s symbol=%s reasons=%s", signal.get("id"), signal.get("symbol"), block_reasons)

    return {
        "ok": passed,
        "preflight_id": preflight_id,
        "checks": checks,
        "block_reason": block_reasons[0] if block_reasons else None,
        "block_reasons": block_reasons,
    }
```

### `backend/services/db.py` — `order_preflight_checks` 테이블 추가

`_schema_statements()` 반환 리스트에 추가:

```python
"""
CREATE TABLE IF NOT EXISTS order_preflight_checks (
    id            TEXT PRIMARY KEY,
    signal_id     TEXT NOT NULL DEFAULT '',
    symbol        TEXT NOT NULL DEFAULT '',
    checks        TEXT NOT NULL DEFAULT '{}',
    block_reasons TEXT NOT NULL DEFAULT '',
    result        TEXT NOT NULL DEFAULT 'ok',   -- ok | block
    created_at    TEXT NOT NULL
)
""",
"CREATE INDEX IF NOT EXISTS idx_preflight_signal ON order_preflight_checks(signal_id)",
"CREATE INDEX IF NOT EXISTS idx_preflight_symbol ON order_preflight_checks(symbol)",
```

---

## 변경 5 — `order_executor.py` 수정

### 5-1. import 변경

제거:
```python
from .rulepack_store import get_active_rulepack_for_date
```

추가:
```python
from .rule_cache import get_rule
from .order_preflight import run_preflight
from .position_manager import position_manager
```

### 5-2. `execute_signal()` 내부 수정

현재:
```python
rulepack = get_active_rulepack_for_date(today) or {}
```

변경:
```python
final_rule = get_rule(signal.get("symbol", "")) or {}
```

이후 `_risk_limits()`, `_machine_rules()` 등 rulepack 관련 헬퍼 호출 부분은 `final_rule`을 직접 사용하도록 변경. `final_rule` 안에 이미 `position_size_pct`, `max_positions`, `ai_confidence_min` 등이 플랫하게 들어있다.

### 5-3. Pre-Flight Check 삽입

`order_cash()` 호출 직전에 Pre-Flight 실행:

```python
# Pre-Flight Check
current_pos_count = len(position_manager.get_positions())
preflight = run_preflight(signal, final_rule, current_positions_count=current_pos_count)
if not preflight["ok"]:
    logger.warning(
        "BLOCK: [S7] Pre-Flight 차단 signal_id=%s symbol=%s reason=%s",
        signal_id, symbol, preflight.get("block_reason"),
    )
    # trading_signals 상태 업데이트
    with get_connection() as conn:
        conn.execute(
            "UPDATE trading_signals SET status = 'preflight_blocked' WHERE id = ?",
            (signal_id,),
        )
    return {"ok": False, "reason": "preflight_blocked", "detail": preflight.get("block_reason")}
```

`order_cash()` 호출 코드는 기존 그대로 유지. Pre-Flight를 통과한 경우에만 실행.

### 5-4. rulepack 관련 헬퍼 함수 정리

`_machine_rules()`, `_risk_limits()` 함수는 더 이상 필요 없다. 단, 제거 시 다른 곳에서 import 하는지 먼저 확인:
```bash
grep -rn "_machine_rules\|_risk_limits" backend/
```
import 없으면 제거, 있으면 유지.

---

## 검증

```bash
python3 -m py_compile backend/services/db.py
python3 -m py_compile backend/services/engine/daily_plan.py
python3 -m py_compile backend/services/engine/order_preflight.py
python3 -m py_compile backend/services/engine/order_executor.py
python3 -m py_compile backend/api/routes/daily_plan.py
```

모두 통과해야 함.

---

## 완료 후

`docs/agent-comm/OUTBOX_EXECUTOR_trading_infra.md` 에 결과 작성.

형식:
```
# OUTBOX_EXECUTOR_trading_infra
## 결과 요약
## 완료 체크리스트
- [x] 변경 1 — DB 마이그레이션 (6개 컬럼)
- [x] 변경 2 — S5 자동 파이프라인 (generated→validated→active)
- [x] 변경 3 — 장중 수동 재실행 차단
- [x] 변경 4 — order_preflight.py 신규 + DB 테이블
- [x] 변경 5 — order_executor.py (rule_cache 연동 + Pre-Flight)
- [x] py_compile 전부 통과
## 특이사항
```
