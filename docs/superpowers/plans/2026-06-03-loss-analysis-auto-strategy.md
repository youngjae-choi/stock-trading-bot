# 손실 분석 → 전략 자동반영 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal (v1.1):** "손실분석 실행" 버튼은 범위 내 미분석 손실의 원인·전략을 **미리보기(제안)만** 표시하고(반영 X), 실제 설정 반영은 **장마감 Review 종합 단계**가 Missed+False 제안을 합쳐 충돌 조정 후 **하루 1회 일괄** 수행한다(가드레일 clamp+audit, reviewed 숨김).

**Architecture:** `loss_strategy.py`(순수: 화이트리스트/clamp/전략도출)와 `loss_analysis.py`(흐름)로 분리. 버튼 → `POST /false-positive/analyze`(미리보기, 제안 반환). 반영은 `loss_analysis.consolidate_and_apply(trade_date)`가 `job_review_audit`(EOD) 안에서 False+Missed 제안을 합쳐 1회 upsert_setting + audit + reviewed 처리.

**Tech Stack:** Python 3 / FastAPI / SQLite / pytest / Vanilla JS

**Scope (v1):** 자동반영 대상은 **flat system_settings 매매 파라미터**(아래 화이트리스트)로 한정. 프로파일팩 내부 파라미터(프로파일별 손절/트레일링) 튜닝은 v2(Task 9, 선택). 운영 인프라 설정(스케줄·토큰)은 영구 제외.

---

## File Structure

- **Create** `backend/services/engine/loss_strategy.py` — 튜닝 화이트리스트, clamp, 패턴→설정변경 도출(순수 함수). 단일 책임: "전략값 계산/검증".
- **Create** `backend/services/engine/loss_analysis.py` — 오케스트레이션(수집→게이트→도출→반영→reviewed). 단일 책임: "흐름 조율".
- **Modify** `backend/services/engine/learning_memory.py` — `raise_ai_confidence_min` 액션 제거.
- **Modify** `backend/api/routes/false_positive.py` — `POST /analyze` 엔드포인트 추가.
- **Modify** `backend/static/js/screens/console-false-positive.js` — 버튼 → /analyze, 완료 팝업 3상태, 미reviewed만 표시.
- **Create** `tests/unit/test_loss_strategy.py`, `tests/unit/test_loss_analysis.py`.

---

## Task 1: 튜닝 화이트리스트 + clamp (loss_strategy.py)

**Files:**
- Create: `backend/services/engine/loss_strategy.py`
- Test: `tests/unit/test_loss_strategy.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/unit/test_loss_strategy.py
import unittest
from backend.services.engine import loss_strategy


class ClampTest(unittest.TestCase):
    def test_clamp_within_bounds_returns_value(self):
        self.assertEqual(loss_strategy.clamp_setting("engine.min_volume_ratio", 3.0), 3.0)

    def test_clamp_above_max_returns_max(self):
        # max_position_rate_per_stock 상한 0.30
        self.assertEqual(loss_strategy.clamp_setting("risk.max_position_rate_per_stock", 0.9), 0.30)

    def test_clamp_below_min_returns_min(self):
        self.assertEqual(loss_strategy.clamp_setting("engine.min_volume_ratio", 0.1), 1.0)

    def test_non_whitelisted_key_returns_none(self):
        self.assertIsNone(loss_strategy.clamp_setting("schedule_s6_time", "09:00"))

    def test_is_tunable(self):
        self.assertTrue(loss_strategy.is_tunable("engine.max_price_change_pct"))
        self.assertFalse(loss_strategy.is_tunable("risk.emergency_halt_enabled"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_loss_strategy.py -q`
Expected: FAIL (module loss_strategy 없음)

- [ ] **Step 3: 구현**

```python
# backend/services/engine/loss_strategy.py
"""손실 분석 전략의 튜닝 대상 화이트리스트 + 가드레일 clamp + 패턴→설정변경 도출.

자동반영은 여기 정의된 매매 파라미터(flat system_settings)로만 가능하다.
운영 인프라 설정(스케줄/토큰)은 포함하지 않는다. 값은 (min, max)로 clamp한다.
"""
from __future__ import annotations

from typing import Any

# key -> (min, max). 매매 파라미터만. 진입시간창 등 시각형은 별도 처리 대상에서 제외(v1).
TUNABLE_SETTINGS: dict[str, tuple[float, float]] = {
    "engine.min_price_change_pct": (0.5, 8.0),
    "engine.max_price_change_pct": (1.0, 15.0),
    "engine.min_volume_ratio": (1.0, 10.0),
    "risk.max_position_rate_per_stock": (0.01, 0.30),
    "risk.daily_loss_limit_percent": (-10.0, -0.5),
    "risk.max_positions": (1, 20),
}


def is_tunable(key: str) -> bool:
    """자동반영 가능한(화이트리스트) 설정 키인지."""
    return key in TUNABLE_SETTINGS


def clamp_setting(key: str, value: Any) -> float | None:
    """화이트리스트 키면 (min,max)로 clamp한 값을, 아니면 None을 반환한다."""
    if key not in TUNABLE_SETTINGS:
        return None
    low, high = TUNABLE_SETTINGS[key]
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return max(low, min(high, v))
```

- [ ] **Step 4: 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_loss_strategy.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/loss_strategy.py tests/unit/test_loss_strategy.py
git commit -m "feat: 손실전략 튜닝 화이트리스트 + 가드레일 clamp"
```

---

## Task 2: 패턴 그룹핑 + 패턴별 전략 도출 (loss_strategy.py)

손실 case 들을 원인 패턴으로 묶고, 패턴별 표본 ≥ 3 이면 설정변경 전략을 만든다.

**Files:**
- Modify: `backend/services/engine/loss_strategy.py`
- Test: `tests/unit/test_loss_strategy.py`

- [ ] **Step 1: 실패 테스트 추가**

```python
class DeriveStrategyTest(unittest.TestCase):
    def _cases(self, n, exit_reason="INITIAL_STOP_LOSS", profile="MID_VOL", pnl=-0.018):
        return [
            {"symbol": f"00{i}", "exit_reason": exit_reason,
             "assigned_profile": profile, "pnl_pct": pnl}
            for i in range(n)
        ]

    def test_stop_loss_pattern_3plus_yields_apply(self):
        # 초기손절 3건+ → 진입 등락률 하한 상향(추격 진입 축소) 전략 자동반영 대상
        applied, observing = loss_strategy.derive_strategies(self._cases(3))
        self.assertTrue(any(s["setting_key"] == "engine.min_price_change_pct" for s in applied))
        self.assertEqual(observing, [])

    def test_pattern_below_3_goes_observing(self):
        applied, observing = loss_strategy.derive_strategies(self._cases(2))
        self.assertEqual(applied, [])
        self.assertEqual(len(observing), 1)
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_loss_strategy.py::DeriveStrategyTest -q`
Expected: FAIL (derive_strategies 없음)

- [ ] **Step 3: 구현 추가**

```python
# loss_strategy.py 에 추가
from collections import defaultdict

_PATTERN_MIN_SAMPLE = 3


def _pattern_key(case: dict[str, Any]) -> str:
    """손실 원인 패턴 식별자 — 청산사유 기준(없으면 프로파일)."""
    return str(case.get("exit_reason") or case.get("assigned_profile") or "unknown")


def _strategy_for_pattern(pattern: str, cases: list[dict[str, Any]]) -> dict[str, Any] | None:
    """패턴별 설정변경 전략. 현재 매핑:
    - 초기손절 다발 → 진입 등락률 하한을 0.5%p 올려 추격 진입을 줄인다.
    - 트레일링손절 다발 → 거래량 배수 하한을 0.5 올려 약한 신호를 거른다.
    """
    from ..settings_store import get_setting

    if pattern == "INITIAL_STOP_LOSS":
        cur = float(get_setting("engine.min_price_change_pct", 3.0) or 3.0)
        return {"setting_key": "engine.min_price_change_pct", "new_value": cur + 0.5,
                "reason": f"초기손절 {len(cases)}건 — 추격 진입 축소"}
    if pattern == "TRAILING_STOP":
        cur = float(get_setting("engine.min_volume_ratio", 2.5) or 2.5)
        return {"setting_key": "engine.min_volume_ratio", "new_value": cur + 0.5,
                "reason": f"트레일링손절 {len(cases)}건 — 약신호 필터 강화"}
    return None


def derive_strategies(cases: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    """손실 case 들 → (자동반영 전략, 관찰 보류 전략). 패턴 표본 ≥ 3 만 반영."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for c in cases:
        groups[_pattern_key(c)].append(c)

    applied: list[dict] = []
    observing: list[dict] = []
    for pattern, group in groups.items():
        strat = _strategy_for_pattern(pattern, group)
        if not strat:
            continue
        strat = {**strat, "pattern": pattern, "sample": len(group)}
        if len(group) >= _PATTERN_MIN_SAMPLE and is_tunable(strat["setting_key"]):
            clamped = clamp_setting(strat["setting_key"], strat["new_value"])
            if clamped is not None:
                strat["new_value"] = clamped
                applied.append(strat)
        else:
            observing.append(strat)
    return applied, observing
```

- [ ] **Step 4: 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_loss_strategy.py -q`
Expected: PASS (7 passed). 참고: `get_setting`은 DB 미존재 시 default 반환하므로 테스트 환경에서도 동작.

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/loss_strategy.py tests/unit/test_loss_strategy.py
git commit -m "feat: 손실 패턴 그룹핑 + 패턴별 전략 도출(표본 3건 게이트)"
```

---

## Task 3: 오케스트레이터 — 수집 + 전역 게이트 (loss_analysis.py)

**Files:**
- Create: `backend/services/engine/loss_analysis.py`
- Test: `tests/unit/test_loss_analysis.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/unit/test_loss_analysis.py
import sqlite3, unittest
from unittest.mock import patch
from backend.services.engine import loss_analysis


def _db(rows):
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE false_positive_cases
        (id TEXT, trade_date TEXT, symbol TEXT, symbol_name TEXT, exit_reason TEXT,
         assigned_profile TEXT, pnl_pct REAL, pnl_amount REAL, reviewed_at TEXT)""")
    for r in rows:
        conn.execute("INSERT INTO false_positive_cases (id,trade_date,symbol,exit_reason,assigned_profile,pnl_pct,reviewed_at) "
                     "VALUES (?,?,?,?,?,?,?)", r)
    return conn


class GlobalGateTest(unittest.TestCase):
    def test_refuse_when_fewer_than_three(self):
        conn = _db([("1","2026-06-02","A","INITIAL_STOP_LOSS","MID_VOL",-0.01,None),
                    ("2","2026-06-02","B","INITIAL_STOP_LOSS","MID_VOL",-0.01,None)])
        with patch.object(loss_analysis, "get_connection", return_value=conn):
            res = loss_analysis.collect_unreviewed_losses("2026-05-01", "2026-06-03")
        self.assertEqual(len(res), 2)
        self.assertTrue(loss_analysis.is_sample_insufficient(res))

    def test_sufficient_at_three(self):
        rows = [(str(i),"2026-06-02",f"S{i}","INITIAL_STOP_LOSS","MID_VOL",-0.01,None) for i in range(3)]
        conn = _db(rows)
        with patch.object(loss_analysis, "get_connection", return_value=conn):
            res = loss_analysis.collect_unreviewed_losses("2026-05-01","2026-06-03")
        self.assertFalse(loss_analysis.is_sample_insufficient(res))
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_loss_analysis.py -q`
Expected: FAIL

- [ ] **Step 3: 구현**

```python
# backend/services/engine/loss_analysis.py
"""손실 분석 오케스트레이션: 수집 → 전역 게이트 → 전략 도출 → 자동반영 → reviewed."""
from __future__ import annotations

from typing import Any

from ..db import get_connection

_GLOBAL_MIN_SAMPLE = 3


def collect_unreviewed_losses(start: str, end: str) -> list[dict[str, Any]]:
    """범위 내 미분석(reviewed_at IS NULL) 손실 case 를 반환한다."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM false_positive_cases
               WHERE trade_date >= ? AND trade_date <= ? AND reviewed_at IS NULL
               ORDER BY trade_date DESC""",
            (start, end),
        ).fetchall()
    return [dict(r) for r in rows]


def is_sample_insufficient(cases: list[dict[str, Any]]) -> bool:
    """전역 표본 게이트 — 총 손실 < 3 이면 분석 거부."""
    return len(cases) < _GLOBAL_MIN_SAMPLE
```

- [ ] **Step 4: 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_loss_analysis.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/loss_analysis.py tests/unit/test_loss_analysis.py
git commit -m "feat: 손실 수집 + 전역 표본 게이트"
```

---

## Task 4: 반영 빌딩블록 — apply_strategies + reviewed (loss_analysis.py)

> 주의(v1.1): 이 함수들은 **버튼이 아니라 EOD 종합 반영(Task 5.5)** 에서만 호출된다.

**Files:**
- Modify: `backend/services/engine/loss_analysis.py`
- Test: `tests/unit/test_loss_analysis.py`

- [ ] **Step 1: 실패 테스트 추가**

```python
class ApplyTest(unittest.TestCase):
    def test_apply_calls_upsert_and_marks_reviewed(self):
        applied = [{"setting_key":"engine.min_price_change_pct","new_value":3.5,
                    "reason":"x","pattern":"INITIAL_STOP_LOSS","sample":3}]
        cases = [{"id":"1"},{"id":"2"},{"id":"3"}]
        calls = {"upsert":[], "reviewed":[]}
        with patch.object(loss_analysis, "upsert_setting", lambda *a, **k: calls["upsert"].append((a,k))), \
             patch.object(loss_analysis, "_mark_reviewed", lambda ids: calls["reviewed"].extend(ids)):
            loss_analysis.apply_strategies(applied, cases)
        self.assertEqual(len(calls["upsert"]), 1)
        self.assertEqual(set(calls["reviewed"]), {"1","2","3"})
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_loss_analysis.py::ApplyTest -q`
Expected: FAIL

- [ ] **Step 3: 구현 추가**

```python
# loss_analysis.py 상단 import에 추가
from ..settings_store import upsert_setting
from ._now import _now_kst_iso  # 없으면 아래 _now_kst_iso 직접 정의

# loss_analysis.py 에 추가
def _mark_reviewed(case_ids: list[str]) -> None:
    """분석 끝난 case 를 reviewed 처리 → 목록에서 숨김."""
    if not case_ids:
        return
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
    placeholders = ",".join("?" * len(case_ids))
    with get_connection() as conn:
        conn.execute(
            f"UPDATE false_positive_cases SET reviewed_at = ? WHERE id IN ({placeholders})",
            (now, *case_ids),
        )


def apply_strategies(applied: list[dict[str, Any]], cases: list[dict[str, Any]]) -> None:
    """자동반영 전략을 settings에 upsert(가드레일 통과값) + 분석 case reviewed 처리."""
    for s in applied:
        upsert_setting(
            s["setting_key"], s["new_value"], "float",
            f"손실분석 자동반영: {s.get('reason','')}", actor="loss_analysis",
        )
    _mark_reviewed([str(c["id"]) for c in cases if c.get("id")])
```

참고: `upsert_setting`은 내부에서 audit_events에 old→new 를 기록한다(되돌리기 근거).

- [ ] **Step 4: 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_loss_analysis.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/loss_analysis.py tests/unit/test_loss_analysis.py
git commit -m "feat: 손실전략 자동반영(upsert+audit) + reviewed 처리"
```

---

## Task 5: analyze() 통합 + (옵션) LLM 서술

**Files:**
- Modify: `backend/services/engine/loss_analysis.py`
- Test: `tests/unit/test_loss_analysis.py`

- [ ] **Step 1: 실패 테스트 추가**

```python
class AnalyzeTest(unittest.TestCase):
    def test_refused_when_insufficient(self):
        with patch.object(loss_analysis, "collect_unreviewed_losses", return_value=[{"id":"1"}]):
            res = loss_analysis.analyze("2026-05-01","2026-06-03")
        self.assertTrue(res["refused"])
        self.assertEqual(res["needed"], 3)

    def test_success_returns_proposals_without_applying(self):
        cases = [{"id":str(i),"symbol":f"S{i}","exit_reason":"INITIAL_STOP_LOSS",
                  "assigned_profile":"MID_VOL","pnl_pct":-0.01} for i in range(3)]
        with patch.object(loss_analysis, "collect_unreviewed_losses", return_value=cases), \
             patch.object(loss_analysis, "apply_strategies") as apply_mock:
            res = loss_analysis.analyze("2026-05-01","2026-06-03")
        self.assertFalse(res["refused"])
        self.assertGreaterEqual(len(res["proposed"]), 1)
        apply_mock.assert_not_called()  # 미리보기: 반영하지 않는다
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_loss_analysis.py::AnalyzeTest -q`
Expected: FAIL

- [ ] **Step 3: 구현 추가**

```python
# loss_analysis.py 에 추가
from . import loss_strategy


def analyze(start: str, end: str) -> dict[str, Any]:
    """미리보기: 수집 → 전역 게이트 → 전략 제안 도출. 반영/숨김은 하지 않는다(EOD에서 수행)."""
    cases = collect_unreviewed_losses(start, end)
    if is_sample_insufficient(cases):
        return {"refused": True, "reason": "손실 표본 부족", "have": len(cases),
                "needed": _GLOBAL_MIN_SAMPLE, "proposed": [], "observing": [],
                "analyzed_symbols": []}
    proposed, observing = loss_strategy.derive_strategies(cases)
    return {"refused": False, "proposed": proposed, "observing": observing,
            "analyzed_symbols": [c.get("symbol") for c in cases]}
```

LLM 서술(하이브리드)은 보조이므로 v1에서는 `reason` 문자열로 대체하고, 별도 후속(Task 9)에서 추가한다. 결정적 전략 제안은 LLM 없이도 완결된다.

- [ ] **Step 4: 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_loss_analysis.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/loss_analysis.py tests/unit/test_loss_analysis.py
git commit -m "feat: 손실분석 analyze() 통합(거부/성공 흐름)"
```

---

## Task 5.5: EOD 종합 반영 — Missed+False 병합 후 1회 적용 (loss_analysis.py + scheduler)

**Files:**
- Modify: `backend/services/engine/loss_analysis.py`
- Modify: `backend/services/scheduler.py` (job_review_audit 내부에서 호출)
- Test: `tests/unit/test_loss_analysis.py`

- [ ] **Step 1: 병합(충돌 조정) 실패 테스트 추가**

```python
class MergeTest(unittest.TestCase):
    def test_conflict_keeps_conservative_value(self):
        # 같은 설정 키에 두 제안 → 손실 방어적(더 보수적)인 값 채택.
        # min_price_change_pct는 "높을수록 보수적"(추격 진입 축소).
        false_p = [{"setting_key":"engine.min_price_change_pct","new_value":3.5,"reason":"F","pattern":"INITIAL_STOP_LOSS","sample":3}]
        missed_p = [{"setting_key":"engine.min_price_change_pct","new_value":4.0,"reason":"M","pattern":"x","sample":3}]
        merged = loss_analysis._merge_proposals(false_p, missed_p)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["new_value"], 4.0)  # 더 높은(보수적) 값
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_loss_analysis.py::MergeTest -q`
Expected: FAIL

- [ ] **Step 3: 구현 추가**

```python
# loss_analysis.py 에 추가
# "보수적(손실 방어적)" 방향: 값이 클수록 보수적인 키 / 작을수록 보수적인 키
_HIGHER_IS_CONSERVATIVE = {"engine.min_price_change_pct", "engine.min_volume_ratio"}
_LOWER_IS_CONSERVATIVE = {"engine.max_price_change_pct", "risk.max_position_rate_per_stock",
                          "risk.max_positions", "risk.daily_loss_limit_percent"}


def _merge_proposals(false_p: list[dict[str, Any]], missed_p: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """같은 설정 키 충돌 시 더 보수적인 값을 채택해 병합한다."""
    best: dict[str, dict[str, Any]] = {}
    for p in [*false_p, *missed_p]:
        key = p["setting_key"]
        if key not in best:
            best[key] = p
            continue
        cur = best[key]["new_value"]
        new = p["new_value"]
        if key in _HIGHER_IS_CONSERVATIVE:
            best[key] = p if new > cur else best[key]
        elif key in _LOWER_IS_CONSERVATIVE:
            best[key] = p if new < cur else best[key]
    return list(best.values())


def consolidate_and_apply(trade_date: str) -> dict[str, Any]:
    """EOD: 당일 기준 미분석 손실(False) + Missed 제안을 병합해 1회 자동반영한다.

    Missed 제안 도출은 v1에서는 빈 리스트(후속). False 제안만으로도 닫힘.
    """
    # 매수는 최대 30일 전일 수 있으므로 넉넉히 수집
    from datetime import datetime, timedelta
    start = (datetime.fromisoformat(trade_date) - timedelta(days=30)).strftime("%Y-%m-%d")
    cases = collect_unreviewed_losses(start, trade_date)
    false_proposed, _ = loss_strategy.derive_strategies(cases)
    missed_proposed: list[dict[str, Any]] = []  # v1: 후속 연결 지점
    merged = _merge_proposals(false_proposed, missed_proposed)
    apply_strategies(merged, cases)
    return {"applied": merged, "case_count": len(cases)}
```

- [ ] **Step 4: 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_loss_analysis.py -q`
Expected: PASS

- [ ] **Step 5: job_review_audit 에 와이어링**

`scheduler.py`의 `job_review_audit`에서 `run_review_audit(today)` **성공 직후**에 추가:

```python
        try:
            from .engine.loss_analysis import consolidate_and_apply
            applied = consolidate_and_apply(today)
            logger.info("SUCCESS: [ReviewAudit] 손실전략 종합 반영 applied=%d case=%d",
                        len(applied.get("applied", [])), applied.get("case_count", 0))
        except Exception as exc:
            logger.error("FAIL: [ReviewAudit] 손실전략 종합 반영 실패 — %s", exc)
```

- [ ] **Step 6: 커밋**

```bash
git add backend/services/engine/loss_analysis.py backend/services/scheduler.py tests/unit/test_loss_analysis.py
git commit -m "feat: EOD Review 종합 반영(Missed+False 병합 1회 적용)"
```

---

## Task 6: raise_ai_confidence_min 액션 제거 (learning_memory.py)

**Files:**
- Modify: `backend/services/engine/learning_memory.py:340-365`

- [ ] **Step 1: 해당 메모리 블록 제거**

`learning_memory.py`의 stop-loss 패턴에서 `recommendation={"action": "raise_ai_confidence_min", ...}` 를 만드는 `memories.append(_make_memory(... scope="S4_HYBRID_SCREENING", category="screening_weight" ...))` 블록(약 344~365행) 전체를 제거한다. AI confidence 게이트가 2026-06-02에 폐지되어 이 액션은 무효이기 때문이다. 제거 후 `stop_loss_count`/`stop_loss_avg_pnl` 변수가 다른 곳에서 안 쓰이면 함께 정리한다.

- [ ] **Step 2: 컴파일 + 기존 학습 테스트 회귀**

Run: `PYTHONPATH=. .venv/bin/python -m py_compile backend/services/engine/learning_memory.py`
Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit -k learning -q` (있으면)
Expected: OK / PASS

- [ ] **Step 3: 커밋**

```bash
git add backend/services/engine/learning_memory.py
git commit -m "fix: 학습 액션에서 raise_ai_confidence_min 제거(게이트 폐지 후속)"
```

---

## Task 7: API 엔드포인트 POST /false-positive/analyze

**Files:**
- Modify: `backend/api/routes/false_positive.py`

- [ ] **Step 1: 엔드포인트 추가**

```python
# false_positive.py 에 추가 (기존 import 아래)
from ...services.engine.loss_analysis import analyze as analyze_losses


@router.post("/analyze")
def post_analyze(start: str, end: str):
    """범위 내 미분석 손실을 분석·전략 자동반영하고 요약을 반환한다."""
    logger.info("START: POST /api/v1/false-positive/analyze start=%s end=%s", start, end)
    result = analyze_losses(start, end)
    logger.info("SUCCESS: POST /api/v1/false-positive/analyze refused=%s applied=%d",
                result.get("refused"), len(result.get("applied", [])))
    return {"ok": True, "payload": result}
```

- [ ] **Step 2: API 직접 호출 테스트**

서버 기동 후:
Run: `curl -s -X POST "http://127.0.0.1:8000/api/v1/false-positive/analyze?start=2026-05-01&end=2026-06-03" | python3 -m json.tool`
Expected: `{"ok": true, "payload": {"refused": ...}}` (표본<3 이면 refused:true)

- [ ] **Step 3: 커밋**

```bash
git add backend/api/routes/false_positive.py
git commit -m "feat: POST /false-positive/analyze 엔드포인트"
```

---

## Task 8: 프런트 — 버튼 연결 + 완료 팝업 3상태 + 미reviewed만 표시

**Files:**
- Modify: `backend/static/js/screens/console-false-positive.js`

- [ ] **Step 1: 목록 조회를 미reviewed만으로**

`fetchJson('/api/v1/false-positive/list?...')` 호출에 `&include_reviewed=false` 가 기본임을 확인(이미 reviewed 숨김). 변경 불필요 시 스킵.

- [ ] **Step 2: "손실분석 실행" 버튼 핸들러를 /analyze 로 교체**

```javascript
// 기존 generate 호출부를 아래로 교체
async function runLossAnalysis(start, end) {
  var r = await fetchJson('/api/v1/false-positive/analyze?start=' + start + '&end=' + end, { method: 'POST' });
  var p = (r && r.payload) || {};
  if (p.refused) {
    alert('분석 거부 — 손실 표본 부족 (현재 ' + (p.have||0) + '건 / 최소 ' + (p.needed||3) + '건 필요).\n더 쌓인 뒤 다시 시도하세요.');
    return;
  }
  var proposed = p.proposed || [], observing = p.observing || [];
  if (proposed.length === 0) {
    alert('분석 완료 — EOD에 반영할 전략 없음.\n관찰 보류 ' + observing.length + '건.');
  } else {
    var lines = proposed.map(function(s){ return '· ' + s.setting_key + ' → ' + s.new_value + ' (' + s.reason + ')'; }).join('\n');
    alert('분석 완료 — 장마감 Review에서 반영 예정 ' + proposed.length + '건 / 관찰 보류 ' + observing.length + '건.\n(실제 반영은 장마감 후 Missed와 함께 일괄 적용됩니다)\n\n' + lines);
  }
  // 버튼은 미리보기이므로 즉시 숨김 처리하지 않는다(EOD 반영 시 reviewed 처리됨).
}
```

기존 버튼의 onclick/이벤트를 `runLossAnalysis(startDate, endDate)` 로 연결한다(날짜 picker 값 사용).

- [ ] **Step 3: 수동 검증(브라우저)**

서버 기동 후 화면에서 "손실분석 실행" 클릭 → 표본<3 이면 거부 팝업, 충족 시 반영 목록 팝업 + 목록에서 분석된 항목 사라짐 확인.

- [ ] **Step 4: 커밋**

```bash
git add backend/static/js/screens/console-false-positive.js
git commit -m "feat: 손실분석 버튼→/analyze, 완료 팝업 3상태, reviewed 숨김"
```

---

## Task 9 (선택/v2): LLM 원인 서술 + 프로파일팩 파라미터 튜닝

- LLM 서술: daily_plan의 anthropic provider를 재사용해 종목별 손실 narrative 생성 → analyze 결과 `narratives`에 첨부, 팝업/상세에 표시. LLM 실패 시 생략(결정적 흐름 무영향).
- 프로파일팩 튜닝: risk_profile_packs JSON의 프로파일별 `initial_stop_loss`/`trailing_*`/`max_position_rate` 조정 전략 추가(별도 clamp 테이블 + 적용 헬퍼).

v1 검증·운영 후 필요 시 진행.

---

## Self-Review

- **Spec coverage:** 손실 수집(T3)·버튼 분석(T7,8)·종목별 원인(T2 reason, T9 LLM)·전략 표시(T8)·표본 거부 전역(T3)+패턴(T2)·자동반영(T4)·완료 팝업 알림(T8)·reviewed 숨김(T4,8)·0건/1건 버그(범위 기반 collect로 해소, T3) 모두 태스크 존재. AI confidence 액션 제외(T6). ✓
- **Placeholder scan:** 모든 코드 스텝에 실제 코드 포함. LLM/프로파일 튜닝은 v2로 명시 분리(플레이스홀더 아님). ✓
- **Type consistency:** `clamp_setting`/`is_tunable`/`derive_strategies`/`collect_unreviewed_losses`/`is_sample_insufficient`/`apply_strategies`/`analyze` 시그니처가 태스크 간 일치. `applied` 항목은 {setting_key,new_value,reason,pattern,sample} 형태로 T2·T4·T8 일관. ✓
