# 탐색 엔진 Phase 1a — 조건 프레임워크 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 매수 조건을 "원자 조건 → AND 그룹(전략) → 그룹들 OR" 로 구성·평가하는 설정 가능한 조건 프레임워크의 순수 로직·데이터모델을 만든다(KIS/WS 없이 완전 단위테스트 가능).

**Architecture:** 신규 모듈 `buy_condition_framework.py` 가 (1) `buy_conditions`·`condition_groups` DB 테이블, (2) 기본 조건/그룹 시드, (3) 정규화된 `state` dict에 대한 원자조건 평가기 + 그룹 AND + 그룹들 OR 평가기를 제공한다. `state` dict의 실제 값 채움(체결강도·VWAP·10초봉 등)은 Phase 1b, 매수경로 통합은 후속. 본 계획은 **순수 로직**만 다룬다.

**Tech Stack:** Python 3, SQLite(`backend/services/db.py get_connection`), pytest. 실행: `PYTHONPATH=. .venv/bin/python -m pytest`.

**설계서:** `docs/superpowers/specs/2026-06-06-exploration-buy-strategy-engine-design.md`

**state 계약(평가기 입력 — Phase 1b가 채움):**
```python
state = {
  "change_rate": 2.3,          # 등락률 %
  "체결강도": 0.62,             # 매수체결비율 0~1 (WS shnu_rate)
  "tick_vol_mult": 2.3,        # 틱 거래량 배수
  "tsi": 11.0,                 # 일봉 TSI (None 가능)
  "vwap_position": "above",    # above/below/None
  "day_high_breakout": True,   # 당일 고가 갱신
  "pullback_rebound": False,   # 눌림 후 반등
  "rising_bars": 3,            # 연속 상승 10초봉 수
  "time_hhmm": "10:30",        # 현재 시각 HH:MM
}
```

---

## File Structure

| 파일 | 책임 |
|---|---|
| `backend/services/engine/buy_condition_framework.py` (신규) | 테이블 보장 + 시드 + 조건/그룹 로드 + 평가기(원자·AND·OR) |
| `tests/unit/test_buy_condition_framework.py` (신규) | 평가기·시드·로드 단위테스트 |

---

### Task 1: 원자 조건 평가기 (`evaluate_condition`)

**Files:**
- Create: `backend/services/engine/buy_condition_framework.py`
- Test: `tests/unit/test_buy_condition_framework.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/test_buy_condition_framework.py`:
```python
import backend.services.engine.buy_condition_framework as bcf


_S = {
    "change_rate": 2.3, "체결강도": 0.62, "tick_vol_mult": 2.3, "tsi": 11.0,
    "vwap_position": "above", "day_high_breakout": True, "pullback_rebound": False,
    "rising_bars": 3, "time_hhmm": "10:30",
}


def test_change_rate_band():
    c = {"ctype": "change_rate_band", "params": {"min": 1.5, "max": 5.0}}
    assert bcf.evaluate_condition(c, _S) is True
    assert bcf.evaluate_condition(c, {**_S, "change_rate": 6.0}) is False
    assert bcf.evaluate_condition(c, {**_S, "change_rate": 1.0}) is False


def test_chegyeol_gangdo_min():
    c = {"ctype": "chegyeol_gangdo_min", "params": {"min": 0.55}}
    assert bcf.evaluate_condition(c, _S) is True
    assert bcf.evaluate_condition(c, {**_S, "체결강도": 0.50}) is False


def test_tick_volume_mult_min():
    c = {"ctype": "tick_volume_mult_min", "params": {"min": 2.0}}
    assert bcf.evaluate_condition(c, _S) is True
    assert bcf.evaluate_condition(c, {**_S, "tick_vol_mult": 1.5}) is False


def test_tsi_positive_passes_on_missing():
    c = {"ctype": "tsi_positive", "params": {}}
    assert bcf.evaluate_condition(c, _S) is True
    assert bcf.evaluate_condition(c, {**_S, "tsi": None}) is True   # 결손은 통과(차단 금지)
    assert bcf.evaluate_condition(c, {**_S, "tsi": -5.0}) is False


def test_vwap_above():
    c = {"ctype": "vwap_above", "params": {}}
    assert bcf.evaluate_condition(c, _S) is True
    assert bcf.evaluate_condition(c, {**_S, "vwap_position": "below"}) is False


def test_bool_conditions():
    assert bcf.evaluate_condition({"ctype": "day_high_breakout", "params": {}}, _S) is True
    assert bcf.evaluate_condition({"ctype": "pullback_rebound", "params": {}}, _S) is False


def test_momentum_rising_bars():
    c = {"ctype": "momentum_rising_bars", "params": {"min_bars": 3}}
    assert bcf.evaluate_condition(c, _S) is True
    assert bcf.evaluate_condition(c, {**_S, "rising_bars": 2}) is False


def test_time_window():
    c = {"ctype": "time_window", "params": {"start": "09:30", "end": "15:00"}}
    assert bcf.evaluate_condition(c, _S) is True
    assert bcf.evaluate_condition(c, {**_S, "time_hhmm": "15:10"}) is False


def test_unknown_ctype_is_false():
    assert bcf.evaluate_condition({"ctype": "nonsense", "params": {}}, _S) is False
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_buy_condition_framework.py -q`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: 구현**

`backend/services/engine/buy_condition_framework.py`:
```python
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
        return True if tsi is None else _f(tsi) > 0  # 결손은 통과(차단 금지)
    if ctype == "vwap_above":
        return str(state.get("vwap_position")) == "above"
    if ctype == "day_high_breakout":
        return bool(state.get("day_high_breakout"))
    if ctype == "pullback_rebound":
        return bool(state.get("pullback_rebound"))
    if ctype == "momentum_rising_bars":
        return int(_f(state.get("rising_bars"))) >= int(_f(p.get("min_bars"), 1))
    if ctype == "time_window":
        t = str(state.get("time_hhmm") or "")
        return str(p.get("start") or "00:00") <= t <= str(p.get("end") or "23:59")
    return False
```

- [ ] **Step 4: 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_buy_condition_framework.py -q`
Expected: PASS.

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/buy_condition_framework.py tests/unit/test_buy_condition_framework.py
git commit -m "feat: 매수 조건 프레임워크 — 원자 조건 평가기(9종)"
```

---

### Task 2: 그룹 AND + 그룹들 OR 평가기

**Files:**
- Modify: `backend/services/engine/buy_condition_framework.py`
- Test: `tests/unit/test_buy_condition_framework.py`

- [ ] **Step 1: 실패 테스트 추가**

```python
def test_group_and_all_pass():
    conds = {
        "c1": {"id": "c1", "ctype": "day_high_breakout", "params": {}},
        "c2": {"id": "c2", "ctype": "chegyeol_gangdo_min", "params": {"min": 0.55}},
    }
    group = {"id": "g1", "name": "돌파", "condition_ids": ["c1", "c2"]}
    assert bcf.evaluate_group(group, conds, _S) is True
    assert bcf.evaluate_group(group, conds, {**_S, "체결강도": 0.4}) is False  # AND 하나 실패


def test_group_empty_conditions_is_false():
    assert bcf.evaluate_group({"id": "g", "name": "x", "condition_ids": []}, {}, _S) is False


def test_evaluate_groups_or():
    conds = {
        "c1": {"id": "c1", "ctype": "day_high_breakout", "params": {}},
        "c2": {"id": "c2", "ctype": "pullback_rebound", "params": {}},
    }
    groups = [
        {"id": "g1", "name": "돌파", "condition_ids": ["c1"]},
        {"id": "g2", "name": "눌림", "condition_ids": ["c2"]},
    ]
    out = bcf.evaluate_groups_or(groups, conds, _S)  # 돌파만 충족
    assert out["any"] is True
    assert out["fired"] == ["돌파"]
    out2 = bcf.evaluate_groups_or(groups, conds, {**_S, "day_high_breakout": False})
    assert out2["any"] is False
    assert out2["fired"] == []
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_buy_condition_framework.py -q`
Expected: FAIL (`AttributeError: evaluate_group`).

- [ ] **Step 3: 구현 — 모듈에 추가**

```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_buy_condition_framework.py -q`
Expected: PASS.

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/buy_condition_framework.py tests/unit/test_buy_condition_framework.py
git commit -m "feat: 조건 그룹 AND + 그룹들 OR 평가기"
```

---

### Task 3: DB 테이블 + 기본 조건/그룹 시드 + 로드

**Files:**
- Modify: `backend/services/engine/buy_condition_framework.py`
- Test: `tests/unit/test_buy_condition_framework.py`

- [ ] **Step 1: 실패 테스트 추가**

```python
def test_seed_and_load_roundtrip():
    bcf._ensure_tables()
    bcf._clear_all_for_test()
    bcf.seed_defaults()
    conds = bcf.load_conditions()
    groups = bcf.load_groups()
    # 기본 조건에 핵심 ctype 존재
    ctypes = {c["ctype"] for c in conds.values()}
    assert "day_high_breakout" in ctypes
    assert "chegyeol_gangdo_min" in ctypes
    # 기본 그룹 3패턴 + 베이스라인
    names = {g["name"] for g in groups}
    assert {"돌파전략", "눌림전략", "모멘텀전략"}.issubset(names)
    # 그룹의 condition_ids가 실제 conditions를 가리킴 (참조 무결성)
    for g in groups:
        for cid in g["condition_ids"]:
            assert cid in conds
    bcf._clear_all_for_test()


def test_seed_is_idempotent():
    bcf._ensure_tables()
    bcf._clear_all_for_test()
    bcf.seed_defaults()
    n1 = len(bcf.load_conditions())
    bcf.seed_defaults()  # 재호출
    n2 = len(bcf.load_conditions())
    assert n1 == n2  # 중복 시드 안 함
    bcf._clear_all_for_test()
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_buy_condition_framework.py -q`
Expected: FAIL (`AttributeError: _ensure_tables`).

- [ ] **Step 3: 구현 — 모듈에 추가**

```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_buy_condition_framework.py -q`
Expected: PASS (all).
또한: `PYTHONPATH=. .venv/bin/python -c "import backend.main; print('import ok')"` → import ok.

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/buy_condition_framework.py tests/unit/test_buy_condition_framework.py
git commit -m "feat: 조건/그룹 DB 테이블 + 기본 시드(3패턴+베이스라인) + 로드"
```

---

## 완료 기준 (Phase 1a)
- [ ] 9종 원자 조건 평가기 + 그룹 AND + 그룹들 OR — 단위테스트 전체 PASS.
- [ ] buy_conditions·condition_groups 테이블 + idempotent 시드 + 로드.
- [ ] `import backend.main` 정상.
- [ ] 순수 로직이라 KIS/WS 불필요.

## 후속 (이 계획 범위 밖)
- **Phase 1b:** WS 틱→10초봉 집계 + 체결강도/VWAP/돌파/눌림/모멘텀 → `state` dict 채움.
- **Phase 1c:** 통짜 태깅(trade_entry_tags) + 선정사유 기록.
- **Phase 1d:** S6 매수경로에 `evaluate_groups_or` 통합 + 등락률 S3 소스 + 모의전용 게이트 + 풀예수금·다종목 사이징.
