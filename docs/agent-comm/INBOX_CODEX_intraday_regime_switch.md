# INBOX: Codex — 장중 레짐 SET 전환 백엔드 구현

**우선순위:** HIGH  
**담당:** Codex (Backend Executor)  
**작성:** Sisyphus 2026-05-23

---

## 배경

현재 레짐 SET은 아침 브리핑(morning_context) 기준으로 하루 1회 선택된다.  
모의계좌 데이터 수집을 위해 장중에도 시장 조건이 바뀌면 SET을 전환하도록 구현한다.

**핵심 원칙:**
- 신규매수: 전환 즉시 새 SET 적용
- 기존 포지션: 진입 시점 SET 유지 (손절/익절선 불변) → `positions.entry_set_id`로 추적
- VIX: 아침 값 고정 (장중 KIS 실시간 VIX 없음)
- 레짐 재판단: 장중 KOSPI 등락률 + 아침 VIX로 판단
- 전환 기록: 하루 여러 번 가능 → `regime_set_applications` 구조 변경

---

## 1. DB 스키마 변경

### 1-A. `regime_set_applications` — UNIQUE 제약 제거 + 컬럼 추가

`backend/services/db.py`의 `_schema_statements()`에서  
`regime_set_applications` 테이블 정의를 변경:

```sql
-- 기존: trade_date TEXT NOT NULL UNIQUE
-- 변경: UNIQUE 제약 제거, 복합 유니크 (trade_date, applied_at)
CREATE TABLE IF NOT EXISTS regime_set_applications (
    id TEXT PRIMARY KEY,
    trade_date TEXT NOT NULL,
    applied_at TEXT NOT NULL,          -- 전환 시각 KST ISO8601
    set_id TEXT NOT NULL,
    set_name TEXT NOT NULL DEFAULT '',
    match_reason TEXT NOT NULL DEFAULT '',
    match_score REAL NOT NULL DEFAULT 0.0,
    applied_settings TEXT NOT NULL DEFAULT '{}',
    regime_label TEXT,
    vix_value REAL,
    kospi_change_pct REAL,
    trigger TEXT NOT NULL DEFAULT 'morning',  -- 'morning' | 'intraday'
    current_flag INTEGER NOT NULL DEFAULT 0,  -- 1 = 현재 활성 SET
    total_trades INTEGER,
    win_count INTEGER,
    total_pnl REAL,
    result_updated_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(set_id) REFERENCES regime_sets(id)
);
```

**기존 테이블 마이그레이션:**  
`ensure_tables()` 또는 `initialize_database()` 내에서  
`ALTER TABLE regime_set_applications ADD COLUMN IF NOT EXISTS` 방식으로  
신규 컬럼(`applied_at`, `trigger`, `current_flag`)을 기존 DB에 추가.  
SQLite는 `ADD COLUMN IF NOT EXISTS`를 지원하지 않으므로 아래 패턴 사용:

```python
def _migrate_regime_set_applications(conn):
    existing = {r['name'] for r in conn.execute('PRAGMA table_info(regime_set_applications)')}
    if 'applied_at' not in existing:
        conn.execute("ALTER TABLE regime_set_applications ADD COLUMN applied_at TEXT NOT NULL DEFAULT ''")
    if 'trigger' not in existing:
        conn.execute("ALTER TABLE regime_set_applications ADD COLUMN trigger TEXT NOT NULL DEFAULT 'morning'")
    if 'current_flag' not in existing:
        conn.execute("ALTER TABLE regime_set_applications ADD COLUMN current_flag INTEGER NOT NULL DEFAULT 0")
    # 기존 레코드에 current_flag=1 설정 (각 trade_date의 최신 레코드)
    conn.execute("""
        UPDATE regime_set_applications SET current_flag=1
        WHERE id IN (
            SELECT id FROM regime_set_applications
            WHERE (trade_date, created_at) IN (
                SELECT trade_date, MAX(created_at) FROM regime_set_applications GROUP BY trade_date
            )
        )
    """)
```

`initialize_database()` 에서 `_migrate_regime_set_applications(connection)` 호출 추가.

### 1-B. `positions` — `entry_set_id` 컬럼 추가

```python
def _migrate_positions_entry_set(conn):
    existing = {r['name'] for r in conn.execute('PRAGMA table_info(positions)')}
    if 'entry_set_id' not in existing:
        conn.execute("ALTER TABLE positions ADD COLUMN entry_set_id TEXT")
```

`initialize_database()` 에서 호출 추가.

---

## 2. `regime_set_service.py` 수정

### 2-A. `record_application` 함수 수정

기존: `INSERT OR REPLACE` (trade_date UNIQUE 기반)  
변경: 새 레코드 INSERT + 이전 레코드 `current_flag=0` 처리

```python
def record_application(
    trade_date: str,
    matched_set: dict,
    regime_label: str,
    vix: float | None,
    kospi_change_pct: float | None,
    trigger: str = "morning",   # 'morning' | 'intraday'
) -> None:
    """
    SET 전환을 기록한다.
    - 해당 trade_date의 기존 레코드 current_flag=0으로 전환
    - 새 레코드 INSERT with current_flag=1
    """
    now = datetime.now(KST).isoformat()
    new_id = str(uuid.uuid4())
    with get_connection() as conn:
        # 기존 current_flag=1 → 0
        conn.execute(
            "UPDATE regime_set_applications SET current_flag=0 WHERE trade_date=?",
            (trade_date,)
        )
        # 새 레코드 INSERT
        conn.execute("""
            INSERT INTO regime_set_applications
                (id, trade_date, applied_at, set_id, set_name, match_reason,
                 match_score, applied_settings, regime_label, vix_value,
                 kospi_change_pct, trigger, current_flag, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?)
        """, (
            new_id, trade_date, now,
            matched_set.get("set_id", ""),
            matched_set.get("set_name", ""),
            matched_set.get("match_reason", ""),
            matched_set.get("match_score", 0.0),
            json.dumps(matched_set.get("applied_settings", {})),
            regime_label,
            vix,
            kospi_change_pct,
            trigger,
            now,
        ))
        conn.commit()
```

### 2-B. `get_today_application` 함수 수정

```python
def get_today_application(trade_date: str) -> dict | None:
    """오늘 현재 활성 SET 반환 (current_flag=1)"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM regime_set_applications WHERE trade_date=? AND current_flag=1",
            (trade_date,)
        ).fetchone()
    return dict(row) if row else None
```

### 2-C. `get_today_transitions` 신규 함수

```python
def get_today_transitions(trade_date: str) -> list[dict]:
    """오늘 SET 전환 이력 전체 반환 (시간순)"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM regime_set_applications WHERE trade_date=? ORDER BY applied_at ASC",
            (trade_date,)
        ).fetchall()
    return [dict(r) for r in rows]
```

---

## 3. `backend/services/engine/intraday_regime_monitor.py` 신규 작성

```python
"""
장중 레짐 SET 모니터링 및 전환.

스케줄: 09:30, 10:00, 10:30, 11:00, 11:30, 12:00, 12:30,
        13:00, 13:30, 14:00, 14:30, 15:00 KST (30분 간격)

판단 로직:
1. 오늘 morning_context에서 VIX 아침 값 읽기
2. KIS API로 KOSPI 현재 등락률 가져오기
   - 없으면 market_snapshots 최신값 사용
   - 그것도 없으면 스킵
3. regime_label 재판단:
   - vix > 28 → volatile
   - vix > 22 AND kospi_change < -1.0 → risk_off
   - kospi_change > 0.5 AND vix < 22 → risk_on
   - 나머지 → neutral
4. match_set() 호출 → 현재 active SET과 다르면 전환
5. 전환 시 system_alert INSERT (severity=warning, Today Control에 표시)
"""
import json
import logging
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection
from ..regime_set_service import match_set, get_today_application, get_today_transitions

logger = logging.getLogger("IntradayRegimeMonitor")
KST = ZoneInfo("Asia/Seoul")

# 레짐 전환 최소 간격 (분) — 너무 잦은 전환 방지
MIN_TRANSITION_INTERVAL_MINUTES = 25


def _today() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def _get_morning_vix(trade_date: str) -> float | None:
    """아침 브리핑에서 저장된 VIX 값 반환"""
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT market_data FROM morning_context WHERE trade_date=?",
                (trade_date,)
            ).fetchone()
        if row:
            mkt = json.loads(dict(row).get("market_data") or "{}")
            return mkt.get("vix", {}).get("price")
    except Exception as e:
        logger.warning("WARN: morning VIX 조회 실패: %s", e)
    return None


def _get_current_kospi_change() -> float | None:
    """
    현재 KOSPI 등락률 가져오기.
    1순위: market_snapshots 최신 값
    2순위: None (스킵)
    """
    try:
        with get_connection() as conn:
            row = conn.execute(
                """SELECT data_json FROM market_snapshots
                   ORDER BY captured_at DESC LIMIT 1""",
            ).fetchone()
        if row:
            data = json.loads(dict(row).get("data_json") or "{}")
            # market_snapshots 구조에 따라 경로 조정
            kospi = data.get("kospi") or data.get("KOSPI") or {}
            change = kospi.get("change_pct") or kospi.get("chg_rate")
            if change is not None:
                return float(change)
    except Exception as e:
        logger.warning("WARN: KOSPI 등락률 조회 실패: %s", e)
    return None


def _judge_regime(vix: float | None, kospi_change: float | None) -> str:
    """
    VIX + KOSPI 등락률로 레짐 재판단.
    VIX는 아침 값 고정, KOSPI는 현재값.
    """
    v = vix or 20.0  # VIX 없으면 중립 기준값
    k = kospi_change if kospi_change is not None else 0.0

    if v > 28:
        return "volatile"
    if v > 22 and k < -1.0:
        return "risk_off"
    if k < -1.5:
        return "risk_off"
    if k > 0.5 and v < 22:
        return "risk_on"
    return "neutral"


def _should_skip_transition(trade_date: str) -> bool:
    """최근 전환 후 MIN_TRANSITION_INTERVAL_MINUTES 미만이면 스킵"""
    transitions = get_today_transitions(trade_date)
    if not transitions:
        return False
    last = transitions[-1]
    last_at_str = last.get("applied_at") or last.get("created_at") or ""
    if not last_at_str:
        return False
    try:
        last_at = datetime.fromisoformat(last_at_str)
        now = datetime.now(KST)
        elapsed = (now - last_at).total_seconds() / 60
        return elapsed < MIN_TRANSITION_INTERVAL_MINUTES
    except Exception:
        return False


def _insert_transition_alert(
    trade_date: str,
    old_set_name: str,
    new_set_name: str,
    old_regime: str,
    new_regime: str,
    vix: float | None,
    kospi_change: float | None,
) -> None:
    """Today Control에 표시될 system_alert 삽입"""
    now = datetime.now(KST)
    time_str = now.strftime("%H:%M")
    message = (
        f"[장중 레짐 전환] {time_str} "
        f"{old_regime} ({old_set_name}) → {new_regime} ({new_set_name})"
    )
    if vix is not None:
        message += f" | VIX {vix:.1f}"
    if kospi_change is not None:
        message += f" | KOSPI {kospi_change:+.2f}%"

    try:
        with get_connection() as conn:
            conn.execute("""
                INSERT INTO system_alerts
                    (id, alert_type, severity, message, trade_date, created_at, is_read)
                VALUES (?, 'regime_transition', 'warning', ?, ?, ?, 0)
            """, (str(uuid.uuid4()), message, trade_date, now.isoformat()))
            conn.commit()
    except Exception as e:
        logger.warning("WARN: regime transition alert INSERT 실패: %s", e)


async def check_intraday_regime(slot: str = "") -> dict[str, Any]:
    """
    장중 레짐 모니터링 메인 함수.
    scheduler에서 30분 간격으로 호출.
    
    반환:
      {ok, action: 'switched'|'no_change'|'skipped', ...}
    """
    trade_date = _today()
    now_str = datetime.now(KST).strftime("%H:%M")
    logger.info("START: IntradayRegimeMonitor slot=%s trade_date=%s", slot or now_str, trade_date)

    # 현재 활성 SET
    current_app = get_today_application(trade_date)
    if not current_app:
        logger.info("SKIP: IntradayRegimeMonitor — 오늘 아침 SET 없음 (아침 브리핑 미완료)")
        return {"ok": True, "action": "skipped", "reason": "no_morning_set"}

    current_set_id = current_app.get("set_id")
    current_regime = current_app.get("regime_label") or "neutral"

    # 최소 간격 체크
    if _should_skip_transition(trade_date):
        logger.info("SKIP: IntradayRegimeMonitor — 최소 전환 간격 미충족")
        return {"ok": True, "action": "skipped", "reason": "min_interval"}

    # 시장 데이터
    vix = _get_morning_vix(trade_date)          # 아침 VIX 고정
    kospi_change = _get_current_kospi_change()   # 현재 KOSPI 등락률

    if kospi_change is None:
        logger.info("SKIP: IntradayRegimeMonitor — KOSPI 등락률 없음")
        return {"ok": True, "action": "skipped", "reason": "no_kospi_data"}

    # 레짐 재판단
    new_regime = _judge_regime(vix, kospi_change)

    # match_set으로 새 SET 찾기 (DB 기록 없이 preview 방식)
    from ..regime_set_service import get_match_preview
    new_match = get_match_preview(new_regime, vix, kospi_change, trade_date)

    new_set_id = new_match.get("set_id")

    # 동일 SET이면 변화 없음
    if new_set_id == current_set_id:
        logger.info(
            "NO_CHANGE: IntradayRegimeMonitor — SET 유지 set_id=%s regime=%s",
            current_set_id, current_regime
        )
        return {"ok": True, "action": "no_change", "set_id": current_set_id}

    # 전환 실행
    logger.info(
        "SWITCH: IntradayRegimeMonitor %s → %s (%s → %s)",
        current_set_id, new_set_id, current_regime, new_regime
    )

    from ..regime_set_service import record_application
    record_application(
        trade_date=trade_date,
        matched_set=new_match,
        regime_label=new_regime,
        vix=vix,
        kospi_change_pct=kospi_change,
        trigger="intraday",
    )

    # 알림 삽입
    _insert_transition_alert(
        trade_date=trade_date,
        old_set_name=current_app.get("set_name", current_set_id),
        new_set_name=new_match.get("set_name", new_set_id or ""),
        old_regime=current_regime,
        new_regime=new_regime,
        vix=vix,
        kospi_change=kospi_change,
    )

    logger.info("SUCCESS: IntradayRegimeMonitor switched to set_id=%s", new_set_id)
    return {
        "ok": True,
        "action": "switched",
        "from_set": current_set_id,
        "to_set": new_set_id,
        "from_regime": current_regime,
        "to_regime": new_regime,
        "vix": vix,
        "kospi_change": kospi_change,
    }
```

---

## 4. `backend/services/scheduler.py` — 장중 레짐 모니터 job 등록

기존 `job_intraday_refresh` 등록 근처에 아래 추가:

```python
async def job_intraday_regime_monitor(slot: str) -> None:
    """장중 레짐 SET 모니터링 — 30분 간격"""
    try:
        from .engine.intraday_regime_monitor import check_intraday_regime
        result = await check_intraday_regime(slot=slot)
        logger.info("job_intraday_regime_monitor slot=%s result=%s", slot, result.get("action"))
    except Exception as exc:
        logger.error("FAIL: job_intraday_regime_monitor slot=%s error=%s", slot, exc)
```

job 등록 (09:30~15:00 매 30분):
```python
import functools
_REGIME_MONITOR_SLOTS = [
    "09:30", "10:00", "10:30", "11:00", "11:30",
    "12:00", "12:30", "13:00", "13:30", "14:00", "14:30", "15:00"
]
for _slot in _REGIME_MONITOR_SLOTS:
    _sh, _sm = int(_slot.split(":")[0]), int(_slot.split(":")[1])
    scheduler.add_job(
        functools.partial(job_intraday_regime_monitor, slot=_slot),
        CronTrigger(hour=_sh, minute=_sm, timezone="Asia/Seoul"),
        id=f"job_intraday_regime_monitor_{_slot.replace(':', '')}",
        replace_existing=True,
        misfire_grace_time=300,
    )
```

---

## 5. API 확장 — `/api/v1/regime/today` 에 transitions 추가

`backend/api/routes/regime_sets.py`의 `get_today_regime` 엔드포인트에서  
`get_today_transitions()` 결과도 함께 반환:

```python
@router.get("/today")
async def get_today_regime(trade_date: str = Query(default=None)):
    from ...services.regime_set_service import get_today_application, get_today_transitions
    ...
    transitions = get_today_transitions(target_date)
    return {
        "ok": True,
        "date": target_date,
        "application": application,         # 현재 활성 SET
        "transitions": transitions,          # 오늘 전환 이력 전체
        "transition_count": len(transitions),
    }
```

---

## 6. `positions.entry_set_id` 채우기

`regime_set_service.match_set()` 호출 결과를 `positions` INSERT 시 저장하는 로직은  
**이번 INBOX에서는 migration만** (컬럼 추가만). 실제 포지션 진입 시 저장은 별도 태스크.

---

## 7. 검증

```bash
python -m py_compile \
  backend/services/db.py \
  backend/services/regime_set_service.py \
  backend/services/engine/intraday_regime_monitor.py \
  backend/services/scheduler.py
```

market_snapshots 테이블 실제 컬럼명을 먼저 `PRAGMA table_info(market_snapshots)` 로 확인 후  
`_get_current_kospi_change()` 경로 조정할 것.

---

## 8. OUTBOX

`docs/agent-comm/OUTBOX_CODEX_intraday_regime_switch.md` 에:
- 마이그레이션 실행 결과
- market_snapshots 실제 컬럼 구조
- compile 통과 여부
- `check_intraday_regime()` 직접 호출 테스트 결과
