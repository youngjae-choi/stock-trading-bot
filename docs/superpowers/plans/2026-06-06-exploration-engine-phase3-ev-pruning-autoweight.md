# 탐색엔진 Phase 3 — EV 측정·가지치기 + 자동가중 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Phase 1c가 쌓은 통짜 태그(`trade_entry_tags`)를 차원별(발화그룹·선정소스·레짐)로 집계해 기대값 EV를 계산하고, **EV 음수 대상부터(negative-knowledge first)** 가지치기 추천을 도출하며, 추천을 `condition_groups.weight`에 자동 반영한다. 집계·반영은 새 파이프라인이 아니라 **기존 EOD 학습루프(`run_review_audit` → `run_learning_memory_builder` → `consolidate_and_apply`)에 1개 스텝을 얹는 방식**으로 결선한다.

**Architecture:** 두 개의 신규 모듈로 분리한다. (1) `ev_analysis.py` — 태그 리스트에 대한 **순수 함수**(`compute_ev_by_dimension`, `recommend_pruning`)로 KIS/WS/DB 없이 합성 태그 dict만으로 완전 단위테스트 가능. (2) `ev_pruning.py` — DB 부수효과를 갖는 얇은 결선층(`apply_auto_weight`로 `condition_groups.weight` UPDATE, `run_ev_pruning`으로 멀티데이 태그 로드→집계→추천→선택적 적용→`learning_memories`에 negative-knowledge 요약 1행 기록). 순수 로직과 부수효과를 파일로 분리해 테스트 가능성과 책임을 명확히 한다. EOD 결선은 `scheduler.py`의 기존 ReviewAudit 잡 끝(Step 6)에 추가하며, `run_review_audit` 본체는 건드리지 않는다(기존 동작 무손상 + 비차단 try/except).

**Tech Stack:** Python 3 (stdlib `json`, `uuid`, `datetime`, `zoneinfo`), pytest. DB 접근은 `backend.services.db.get_connection`. 입력 데이터는 `backend.services.engine.trade_tagging.load_tags(trade_date) -> list[dict]`. 가중 대상은 `backend.services.engine.buy_condition_framework`의 `condition_groups` 테이블. 학습 기록은 `learning_memories` 테이블(Phase 기존 스키마 재사용). 실행: `PYTHONPATH=. .venv/bin/python`.

**설계서:** `docs/superpowers/specs/2026-06-06-exploration-buy-strategy-engine-design.md` ("측정·가지치기 (Phase 3)" + "⑤ 개선" + negative-knowledge-first)

---

## Shared Contracts (이 Phase가 의존/확정하는 계약)

### 입력 — `trade_tagging.load_tags(trade_date)` 가 반환하는 태그 dict (Phase 1c 확정)
각 태그는 다음 키를 갖는다(JSON 컬럼은 이미 파이썬 객체로 복원됨):
```python
{
  "id": "...", "order_id": "...", "symbol": "005930", "trade_date": "2026-06-06",
  "selection_reason": {"sources": ["등락률순위#3", "거래대금상위"],
                       "scores": {"universe_score": 0.36, "llm_suitability": 0.72},
                       "llm_note": "반도체 섹터 강세"},
  "fired_groups": ["돌파전략"],                       # OR 중 발화 그룹명 리스트
  "condition_states": {"체결강도": 0.62, "틱거래량배수": 2.3, "돌파": True, ...},
  "market_context": {"regime": "neutral", "market_tone": "negative",
                     "time_bucket": "10:30", "vix": 18.2},
  "outcome": {"realized_pnl": -1700, "win": False, "hold_sec": 1820,
              "exit_reason": "stop_loss"},          # 청산 전 태그는 {} (미정산)
  "created_at": "...",
}
```
> **핵심:** EV/승률은 `outcome`이 채워진(정산된) 태그만 대상으로 한다. `outcome == {}` 또는 `realized_pnl` 부재 태그는 표본에서 제외한다.

### 가중 대상 — `condition_groups` 테이블 (Phase 1a 확정)
```sql
condition_groups (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, condition_ids_json TEXT,
  enabled INTEGER NOT NULL DEFAULT 1, weight REAL NOT NULL DEFAULT 1.0,
  assigned_to TEXT, created_at TEXT
)
```
- `load_groups()` 는 `weight`(float)를 반환한다. **자동가중은 이 `weight` 컬럼을 그룹 `name` 기준으로 UPDATE** 한다(태그의 `fired_groups` 가 그룹 **name** 을 담으므로 name 으로 매칭).

### 기존 학습루프 (재사용 — 새로 만들지 않음)
- `backend/services/engine/review_audit.py: run_review_audit(trade_date)` — EOD 결정론적 집계(이 Phase는 본체 미변경).
- `backend/services/engine/learning_memory.py` — `learning_memories` 테이블에 `(memory_id, trade_date, scope, category, summary, evidence, recommendation, auto_apply_allowed, requires_approval, status, expires_at, created_at)` 행을 기록하는 패턴. 이 Phase의 negative-knowledge 요약도 **같은 테이블·같은 컬럼**에 1행으로 기록한다(category="ev_pruning").
- `backend/services/scheduler.py` — ReviewAudit 잡이 Step 0~5를 순차 실행. 이 Phase는 **Step 6** 으로 EV 가지치기를 추가한다.

### EV 공식 + 차원 (spec "측정·가지치기")
```
EV = win_rate * avg_win  −  loss_rate * avg_loss
```
- `win_rate = wins / n`, `loss_rate = (n − wins) / n`.
- `avg_win` = 이긴 태그들의 `realized_pnl` 평균(이긴 태그 없으면 0.0).
- `avg_loss` = **진 태그들의 `realized_pnl` 절댓값** 평균(진 태그 없으면 0.0). 즉 손실 크기는 양수로 다룬다.
- `win` 판정: 태그의 `outcome.win`(bool)을 1순위로, 없으면 `realized_pnl > 0`.
- **차원(dimension):**
  - `"fired_group"` — 태그의 `fired_groups` 리스트의 각 그룹명을 키로(한 태그가 여러 그룹 발화 시 각 그룹 버킷에 모두 합산).
  - `"selection_source"` — 태그의 `selection_reason.sources` 리스트의 각 소스를 키로(다중 소스 시 모든 소스 버킷에 합산).
  - `"regime"` — 태그의 `market_context.regime` 1개를 키로.
  - `"condition"`(follow-up note) — per-fired_group 이 must-have. per-condition(개별 원자조건 임계 충족 여부별 EV)은 후속 노트로 남긴다(Task 1 구현엔 포함하지 않음, 본 계획 "후속" 절 참조).

---

## File Structure

| 파일 | 책임 | 생성/수정 |
|------|------|-----------|
| `backend/services/engine/ev_analysis.py` | **순수 함수** — `compute_ev_by_dimension`, `recommend_pruning`(태그 리스트만 입력, DB 무관) | 생성 |
| `backend/services/engine/ev_pruning.py` | **결선층** — `apply_auto_weight`(condition_groups.weight UPDATE), `_write_ev_memory`(learning_memories 1행), `run_ev_pruning`(멀티데이 로드→집계→추천→선택적 적용→메모리) | 생성 |
| `tests/unit/test_ev_analysis.py` | 순수 함수 단위테스트(합성 태그 dict) | 생성 |
| `tests/unit/test_ev_pruning.py` | 결선층 단위테스트(실제 DB, 2099-XX 테스트 trade_date) | 생성 |
| `backend/services/scheduler.py` | ReviewAudit 잡 끝에 Step 6(EV 가지치기) 추가 — 비차단 try/except | 수정 |

> 책임 분리: `ev_analysis.py`(순수, 합성 dict 로 100% 단위테스트) ↔ `ev_pruning.py`(DB 부수효과·기존 루프 결선). EOD 트리거는 scheduler 한 곳에만 추가하고 `run_review_audit` 본체는 무손상.

---

## Task 1: `compute_ev_by_dimension` — 차원별 EV 집계 (순수 함수)

태그 리스트를 받아 차원(fired_group/selection_source/regime)별로 `{key: {n, wins, win_rate, avg_win, avg_loss, ev}}` 를 계산한다. 정산 안 된 태그(`outcome` 비었거나 `realized_pnl` 부재)는 제외한다.

**Files:**
- Create: `backend/services/engine/ev_analysis.py`
- Test: `tests/unit/test_ev_analysis.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/unit/test_ev_analysis.py`:

```python
import backend.services.engine.ev_analysis as ev


def _tag(*, fired, sources, regime, pnl, win):
    """합성 태그 dict — Phase 1c load_tags 반환 형태와 동일한 키만 사용."""
    return {
        "fired_groups": list(fired),
        "selection_reason": {"sources": list(sources), "scores": {}, "llm_note": ""},
        "market_context": {"regime": regime, "market_tone": "neutral",
                           "time_bucket": "10:30", "vix": 18.0},
        "outcome": {"realized_pnl": pnl, "win": win,
                    "hold_sec": 600, "exit_reason": "x"},
    }


def test_ev_by_fired_group_basic_math():
    # 돌파전략: 2승(+1000,+2000) 2패(-500,-1500), n=4
    tags = [
        _tag(fired=["돌파전략"], sources=[], regime="neutral", pnl=1000, win=True),
        _tag(fired=["돌파전략"], sources=[], regime="neutral", pnl=2000, win=True),
        _tag(fired=["돌파전략"], sources=[], regime="neutral", pnl=-500, win=False),
        _tag(fired=["돌파전략"], sources=[], regime="neutral", pnl=-1500, win=False),
    ]
    out = ev.compute_ev_by_dimension(tags, "fired_group")
    g = out["돌파전략"]
    assert g["n"] == 4
    assert g["wins"] == 2
    assert g["win_rate"] == 0.5
    assert g["avg_win"] == 1500.0          # (1000+2000)/2
    assert g["avg_loss"] == 1000.0         # (|−500|+|−1500|)/2
    # EV = 0.5*1500 − 0.5*1000 = 250
    assert g["ev"] == 250.0


def test_ev_negative_group():
    # 큰 손실 그룹: 1승(+200) 3패(-1000,-1000,-1000)
    tags = [
        _tag(fired=["눌림전략"], sources=[], regime="neutral", pnl=200, win=True),
        _tag(fired=["눌림전략"], sources=[], regime="neutral", pnl=-1000, win=False),
        _tag(fired=["눌림전략"], sources=[], regime="neutral", pnl=-1000, win=False),
        _tag(fired=["눌림전략"], sources=[], regime="neutral", pnl=-1000, win=False),
    ]
    out = ev.compute_ev_by_dimension(tags, "fired_group")
    g = out["눌림전략"]
    assert g["win_rate"] == 0.25
    assert g["avg_win"] == 200.0
    assert g["avg_loss"] == 1000.0
    # EV = 0.25*200 − 0.75*1000 = 50 − 750 = −700
    assert g["ev"] == -700.0


def test_multi_group_tag_counts_in_each_bucket():
    # 한 태그가 2개 그룹 발화 → 두 버킷 모두 +1
    tags = [_tag(fired=["돌파전략", "모멘텀전략"], sources=[], regime="neutral",
                 pnl=500, win=True)]
    out = ev.compute_ev_by_dimension(tags, "fired_group")
    assert out["돌파전략"]["n"] == 1
    assert out["모멘텀전략"]["n"] == 1


def test_selection_source_dimension():
    tags = [
        _tag(fired=[], sources=["등락률순위#3"], regime="neutral", pnl=1000, win=True),
        _tag(fired=[], sources=["거래대금상위"], regime="neutral", pnl=-1000, win=False),
        _tag(fired=[], sources=["등락률순위#3", "거래대금상위"], regime="neutral",
             pnl=-2000, win=False),
    ]
    out = ev.compute_ev_by_dimension(tags, "selection_source")
    assert out["등락률순위#3"]["n"] == 2          # 첫·셋째
    assert out["거래대금상위"]["n"] == 2          # 둘째·셋째


def test_regime_dimension():
    tags = [
        _tag(fired=[], sources=[], regime="risk_on", pnl=1000, win=True),
        _tag(fired=[], sources=[], regime="defensive", pnl=-1000, win=False),
    ]
    out = ev.compute_ev_by_dimension(tags, "regime")
    assert set(out.keys()) == {"risk_on", "defensive"}
    assert out["risk_on"]["wins"] == 1


def test_unsettled_tags_excluded():
    # outcome 비었거나 realized_pnl 없는 태그는 표본에서 제외
    tags = [
        {"fired_groups": ["돌파전략"], "selection_reason": {"sources": []},
         "market_context": {"regime": "neutral"}, "outcome": {}},                 # 미정산
        {"fired_groups": ["돌파전략"], "selection_reason": {"sources": []},
         "market_context": {"regime": "neutral"},
         "outcome": {"win": True}},                                              # pnl 없음
        _tag(fired=["돌파전략"], sources=[], regime="neutral", pnl=1000, win=True),
    ]
    out = ev.compute_ev_by_dimension(tags, "fired_group")
    assert out["돌파전략"]["n"] == 1               # 정산된 1건만


def test_win_inferred_from_pnl_when_win_missing():
    # outcome.win 부재 시 realized_pnl>0 로 승패 판정
    tags = [
        {"fired_groups": ["돌파전략"], "selection_reason": {"sources": []},
         "market_context": {"regime": "neutral"},
         "outcome": {"realized_pnl": 800}},        # win 키 없음 → 양수면 승
    ]
    out = ev.compute_ev_by_dimension(tags, "fired_group")
    assert out["돌파전략"]["wins"] == 1
    assert out["돌파전략"]["win_rate"] == 1.0


def test_empty_tags_returns_empty_dict():
    assert ev.compute_ev_by_dimension([], "fired_group") == {}


def test_unknown_dimension_raises():
    import pytest
    with pytest.raises(ValueError):
        ev.compute_ev_by_dimension([], "nonsense_dim")
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_ev_analysis.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.services.engine.ev_analysis'`

- [ ] **Step 3: 최소 구현 작성**

`backend/services/engine/ev_analysis.py`:

```python
"""탐색엔진 EV 측정·가지치기 — 순수 함수 (DB/WS 무관, 합성 태그 dict 로 단위테스트 가능).

입력은 trade_tagging.load_tags() 가 반환하는 태그 dict 리스트다.
EV = win_rate*avg_win − loss_rate*avg_loss (승률만이 아니라 손익비 포함).
정산 안 된 태그(outcome 비었거나 realized_pnl 부재)는 표본에서 제외한다.
"""

from __future__ import annotations

from typing import Any

# 지원 차원. "condition"(개별 원자조건 임계 충족별 EV)은 후속 — per-fired_group 이 must-have.
_DIMENSIONS = ("fired_group", "selection_source", "regime")


def _settled_pnl(tag: dict[str, Any]) -> float | None:
    """정산된 태그면 realized_pnl(float)을, 미정산이면 None 을 반환한다."""
    outcome = tag.get("outcome") or {}
    if not isinstance(outcome, dict) or "realized_pnl" not in outcome:
        return None
    try:
        return float(outcome["realized_pnl"])
    except (TypeError, ValueError):
        return None


def _is_win(tag: dict[str, Any], pnl: float) -> bool:
    """승패 판정 — outcome.win(bool) 1순위, 없으면 realized_pnl>0."""
    outcome = tag.get("outcome") or {}
    win = outcome.get("win")
    if isinstance(win, bool):
        return win
    return pnl > 0.0


def _keys_for_dimension(tag: dict[str, Any], dimension: str) -> list[str]:
    """태그가 기여할 버킷 키(들)를 차원별로 반환한다.

    fired_group/selection_source 는 리스트라 다중 키, regime 은 단일 키.
    """
    if dimension == "fired_group":
        return [str(g) for g in (tag.get("fired_groups") or []) if str(g)]
    if dimension == "selection_source":
        sources = (tag.get("selection_reason") or {}).get("sources") or []
        return [str(s) for s in sources if str(s)]
    if dimension == "regime":
        regime = (tag.get("market_context") or {}).get("regime")
        return [str(regime)] if regime not in (None, "") else []
    raise ValueError(f"unknown dimension: {dimension}")


def compute_ev_by_dimension(tags: list[dict[str, Any]], dimension: str) -> dict[str, dict[str, float]]:
    """차원별 EV 집계 → {key: {n, wins, win_rate, avg_win, avg_loss, ev}}.

    Args:
        tags: trade_tagging.load_tags() 형태의 태그 dict 리스트.
        dimension: "fired_group" | "selection_source" | "regime".
    """
    if dimension not in _DIMENSIONS:
        raise ValueError(f"unknown dimension: {dimension}")

    # key -> {"win_pnls": [..], "loss_pnls": [..]} (loss_pnls 는 양수 손실 크기)
    buckets: dict[str, dict[str, list[float]]] = {}
    for tag in tags:
        pnl = _settled_pnl(tag)
        if pnl is None:
            continue  # 미정산 제외
        win = _is_win(tag, pnl)
        for key in _keys_for_dimension(tag, dimension):
            b = buckets.setdefault(key, {"win_pnls": [], "loss_pnls": []})
            if win:
                b["win_pnls"].append(pnl)
            else:
                b["loss_pnls"].append(abs(pnl))

    results: dict[str, dict[str, float]] = {}
    for key, b in buckets.items():
        wins = len(b["win_pnls"])
        losses = len(b["loss_pnls"])
        n = wins + losses
        if n == 0:
            continue
        win_rate = wins / n
        loss_rate = losses / n
        avg_win = sum(b["win_pnls"]) / wins if wins else 0.0
        avg_loss = sum(b["loss_pnls"]) / losses if losses else 0.0
        ev = win_rate * avg_win - loss_rate * avg_loss
        results[key] = {
            "n": n,
            "wins": wins,
            "win_rate": round(win_rate, 6),
            "avg_win": round(avg_win, 6),
            "avg_loss": round(avg_loss, 6),
            "ev": round(ev, 6),
        }
    return results
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_ev_analysis.py -q`
Expected: PASS (9 passed)

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/ev_analysis.py tests/unit/test_ev_analysis.py
git commit -m "feat: compute_ev_by_dimension — 차원별 EV 집계 순수 함수 (탐색엔진 Phase 3)"
```

---

## Task 2: `recommend_pruning` — EV 음수 우선 가지치기 추천 (순수 함수)

`compute_ev_by_dimension` 결과를 받아 **표본 충분(n≥min_sample) AND EV<0** 인 대상을 추천한다. 기본은 `downweight`, 표본이 매우 크고(`disable_sample`, 기본 90) 지속 음수일 때만 `disable`. 출력은 negative-first 정렬(EV 오름차순).

**Files:**
- Modify: `backend/services/engine/ev_analysis.py` (append `recommend_pruning`)
- Test: `tests/unit/test_ev_analysis.py` (append)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/unit/test_ev_analysis.py` 끝에 추가:

```python
def test_recommend_pruning_negative_first_downweight():
    ev_results = {
        "돌파전략": {"n": 40, "wins": 24, "win_rate": 0.6, "avg_win": 1500,
                   "avg_loss": 800, "ev": 580.0},     # 양수 → 추천 없음
        "눌림전략": {"n": 40, "wins": 10, "win_rate": 0.25, "avg_win": 200,
                   "avg_loss": 1000, "ev": -700.0},   # 음수+표본충분 → downweight
        "소표본전략": {"n": 5, "wins": 1, "win_rate": 0.2, "avg_win": 100,
                    "avg_loss": 900, "ev": -700.0},   # 음수지만 표본부족 → 제외
    }
    recs = ev.recommend_pruning(ev_results, min_sample=30)
    targets = {r["target"]: r for r in recs}
    assert "눌림전략" in targets
    assert targets["눌림전략"]["action"] == "downweight"
    assert "돌파전략" not in targets        # 양수 EV
    assert "소표본전략" not in targets      # 표본 부족
    # reason 에 n·ev 가 들어간다(설명가능성)
    assert "EV" in targets["눌림전략"]["reason"]


def test_recommend_pruning_disable_only_huge_sample():
    ev_results = {
        "대표본음수": {"n": 120, "wins": 30, "win_rate": 0.25, "avg_win": 200,
                    "avg_loss": 1200, "ev": -850.0},
    }
    recs = ev.recommend_pruning(ev_results, min_sample=30, disable_sample=90)
    assert recs[0]["target"] == "대표본음수"
    assert recs[0]["action"] == "disable"


def test_recommend_pruning_sorted_negative_first():
    ev_results = {
        "약음수": {"n": 50, "wins": 22, "win_rate": 0.44, "avg_win": 900,
                 "avg_loss": 1000, "ev": -100.0},
        "강음수": {"n": 50, "wins": 12, "win_rate": 0.24, "avg_win": 300,
                 "avg_loss": 1100, "ev": -800.0},
    }
    recs = ev.recommend_pruning(ev_results, min_sample=30)
    # 더 나쁜(EV 더 낮은) 대상이 먼저
    assert [r["target"] for r in recs] == ["강음수", "약음수"]


def test_recommend_pruning_empty_when_all_positive():
    ev_results = {"좋은전략": {"n": 50, "wins": 40, "win_rate": 0.8, "avg_win": 1000,
                            "avg_loss": 500, "ev": 700.0}}
    assert ev.recommend_pruning(ev_results, min_sample=30) == []
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_ev_analysis.py -k recommend_pruning -q`
Expected: FAIL — `AttributeError: module 'backend.services.engine.ev_analysis' has no attribute 'recommend_pruning'`

- [ ] **Step 3: 최소 구현 작성**

`backend/services/engine/ev_analysis.py` 끝에 추가:

```python
def recommend_pruning(
    ev_results: dict[str, dict[str, float]],
    min_sample: int = 30,
    disable_sample: int = 90,
) -> list[dict[str, Any]]:
    """EV 음수 대상을 negative-first 로 가지치기 추천한다 — "사지/고르지 말아야 할" 도출.

    표본 n≥min_sample AND ev<0 인 대상만 추천한다. 기본 action 은 "downweight",
    표본이 매우 크고(n≥disable_sample) 지속 음수일 때만 "disable"(운 좋은 전략 안 죽임).
    출력은 EV 오름차순(가장 나쁜 것 먼저).

    Args:
        ev_results: compute_ev_by_dimension() 출력 {key: {n, ev, ...}}.
        min_sample: 가지치기 최소 표본(기본 30).
        disable_sample: disable 로 격상할 대표본 임계(기본 90).
    """
    recs: list[dict[str, Any]] = []
    for target, stat in ev_results.items():
        n = int(stat.get("n", 0))
        ev_value = float(stat.get("ev", 0.0))
        if n < min_sample or ev_value >= 0.0:
            continue
        action = "disable" if n >= disable_sample else "downweight"
        win_rate = float(stat.get("win_rate", 0.0))
        reason = (
            f"표본 {n}건 · 승률 {win_rate:.0%} · EV {ev_value:+.0f} "
            f"({'대표본 지속 음수 → 비활성' if action == 'disable' else 'EV 음수 → 가중 하향'})"
        )
        recs.append({"target": target, "action": action, "reason": reason,
                     "n": n, "ev": round(ev_value, 6)})
    recs.sort(key=lambda r: r["ev"])  # 가장 나쁜 것 먼저 (negative-first)
    return recs
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_ev_analysis.py -q`
Expected: PASS (13 passed)

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/ev_analysis.py tests/unit/test_ev_analysis.py
git commit -m "feat: recommend_pruning — EV 음수 우선 가지치기 추천(downweight/disable) (탐색엔진 Phase 3)"
```

---

## Task 3: `apply_auto_weight` — condition_groups.weight 자동 조정 (DB)

추천 리스트를 받아 `fired_group` 추천(=그룹명)만 골라 `condition_groups.weight` 를 그룹 `name` 기준으로 조정한다. `downweight` 는 `weight *= 0.5`(floor 0.1, **하드제로 금지**), `disable` 은 `weight = 0.1` + `enabled = 0`(완전차단=floor 까지만, 운 좋은 전략 보존). selection_source/regime 추천은 그룹이 아니므로 weight 조정 대상이 아니며 건너뛴다(반환 skipped 에 표기).

**Files:**
- Create: `backend/services/engine/ev_pruning.py`
- Test: `tests/unit/test_ev_pruning.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/unit/test_ev_pruning.py`:

```python
import backend.services.engine.buy_condition_framework as bcf
import backend.services.engine.ev_pruning as evp
from backend.services.db import get_connection


def _seed_group(name: str, weight: float, enabled: int = 1) -> str:
    """테스트용 그룹 1개를 condition_groups 에 직접 삽입하고 id 반환."""
    import uuid
    from datetime import datetime, timezone
    bcf._ensure_tables()
    gid = f"test_grp_{uuid.uuid4().hex[:8]}"
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO condition_groups (id, name, condition_ids_json, enabled, weight, assigned_to, created_at) "
            "VALUES (?, ?, '[]', ?, ?, '', ?)",
            (gid, name, enabled, weight, datetime.now(timezone.utc).isoformat()),
        )
    return gid


def _weight_enabled(gid: str) -> tuple[float, int]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT weight, enabled FROM condition_groups WHERE id = ?", (gid,)
        ).fetchone()
    return float(row["weight"]), int(row["enabled"])


def _cleanup(gid: str) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM condition_groups WHERE id = ?", (gid,))


def test_apply_auto_weight_downweight_halves_with_floor():
    gid = _seed_group("EVTEST_다운", weight=1.0)
    try:
        result = evp.apply_auto_weight([
            {"target": "EVTEST_다운", "action": "downweight", "reason": "r", "n": 40, "ev": -500.0},
        ])
        w, en = _weight_enabled(gid)
        assert w == 0.5            # 1.0 * 0.5
        assert en == 1            # downweight 는 비활성화 안 함
        assert result["adjusted"] == 1
    finally:
        _cleanup(gid)


def test_apply_auto_weight_downweight_respects_floor():
    gid = _seed_group("EVTEST_플로어", weight=0.15)
    try:
        evp.apply_auto_weight([
            {"target": "EVTEST_플로어", "action": "downweight", "reason": "r", "n": 40, "ev": -500.0},
        ])
        w, _ = _weight_enabled(gid)
        assert w == 0.1            # 0.075 → floor 0.1 (하드제로 금지)
    finally:
        _cleanup(gid)


def test_apply_auto_weight_disable_sets_floor_and_disabled():
    gid = _seed_group("EVTEST_디스", weight=0.8)
    try:
        evp.apply_auto_weight([
            {"target": "EVTEST_디스", "action": "disable", "reason": "r", "n": 120, "ev": -900.0},
        ])
        w, en = _weight_enabled(gid)
        assert w == 0.1            # 완전 0 아님 — floor 까지만
        assert en == 0            # disable 은 enabled=0
    finally:
        _cleanup(gid)


def test_apply_auto_weight_skips_non_group_targets():
    # selection_source/regime 추천(그룹 아님)은 weight 조정 대상 아님
    result = evp.apply_auto_weight([
        {"target": "등락률순위#3", "action": "downweight", "reason": "r", "n": 40, "ev": -300.0},
    ])
    assert result["adjusted"] == 0
    assert "등락률순위#3" in result["skipped"]


def test_apply_auto_weight_empty_is_noop():
    result = evp.apply_auto_weight([])
    assert result["adjusted"] == 0
    assert result["skipped"] == []
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_ev_pruning.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.services.engine.ev_pruning'`

- [ ] **Step 3: 최소 구현 작성**

`backend/services/engine/ev_pruning.py`:

```python
"""탐색엔진 Phase 3 결선층 — EV 가지치기를 condition_groups.weight 에 반영하고
기존 EOD 학습루프(learning_memories)에 negative-knowledge 요약을 1행 기록한다.

순수 집계·추천 로직은 ev_analysis.py(단위테스트). 본 모듈은 DB 부수효과만 담당한다.
새 파이프라인이 아니라 기존 학습루프(run_review_audit → learning_memory)에 디테일을 얹는다.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection
from . import ev_analysis
from .trade_tagging import load_tags

logger = logging.getLogger("EVPruning")

_WEIGHT_FLOOR = 0.1          # 하드제로 금지 — 운 좋은 전략을 죽이지 않는 최소 가중
_DOWNWEIGHT_FACTOR = 0.5     # downweight 시 가중 절반


def _now_kst_iso() -> str:
    """현재 Asia/Seoul 시각 ISO 문자열."""
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def apply_auto_weight(recommendations: list[dict[str, Any]]) -> dict[str, Any]:
    """가지치기 추천을 condition_groups.weight 에 반영한다(그룹명 = name 매칭).

    downweight: weight *= 0.5 (floor 0.1). disable: weight = floor + enabled=0
    (대표본 지속 음수일 때만 — 완전 0 으로 죽이지 않고 floor 까지만 내린다).
    그룹이 아닌 target(selection_source/regime)은 skipped 로 반환한다.

    Args:
        recommendations: recommend_pruning() 출력 [{target, action, ...}].
    """
    adjusted: list[str] = []
    skipped: list[str] = []
    with get_connection() as conn:
        for rec in recommendations or []:
            target = str(rec.get("target") or "")
            action = str(rec.get("action") or "")
            row = conn.execute(
                "SELECT id, weight FROM condition_groups WHERE name = ?", (target,)
            ).fetchone()
            if row is None:
                skipped.append(target)  # 그룹명이 아님(선정소스/레짐) — weight 대상 아님
                continue
            cur_weight = float(row["weight"] or 1.0)
            if action == "disable":
                new_weight = _WEIGHT_FLOOR
                conn.execute(
                    "UPDATE condition_groups SET weight = ?, enabled = 0 WHERE id = ?",
                    (new_weight, row["id"]),
                )
            else:  # downweight (기본)
                new_weight = max(cur_weight * _DOWNWEIGHT_FACTOR, _WEIGHT_FLOOR)
                conn.execute(
                    "UPDATE condition_groups SET weight = ? WHERE id = ?",
                    (new_weight, row["id"]),
                )
            adjusted.append(target)
            logger.info("INFO: [EV] weight 조정 group=%s action=%s %.3f→%.3f",
                        target, action, cur_weight, new_weight)
    return {"adjusted": len(adjusted), "adjusted_groups": adjusted, "skipped": skipped}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_ev_pruning.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/ev_pruning.py tests/unit/test_ev_pruning.py
git commit -m "feat: apply_auto_weight — EV 추천을 condition_groups.weight 에 반영(floor 0.1·하드제로 금지) (탐색엔진 Phase 3)"
```

---

## Task 4: `run_ev_pruning` — 멀티데이 결선 + negative-knowledge 메모리

여러 거래일 태그를 로드→3차원 EV 집계→차원별 추천→(`apply=True`면) 자동가중 적용→`learning_memories` 에 "고르지/사지 말아야 할" 요약 1행 기록. 기존 학습루프(`learning_memory.py`)와 동일한 테이블·컬럼을 재사용한다.

**Files:**
- Modify: `backend/services/engine/ev_pruning.py` (append `_write_ev_memory`, `run_ev_pruning`)
- Test: `tests/unit/test_ev_pruning.py` (append)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/unit/test_ev_pruning.py` 끝에 추가:

```python
import backend.services.engine.trade_tagging as tt


def _record_settled(trade_date, order_id, fired, sources, regime, pnl, win):
    """정산 완료 태그 1행을 실제 trade_entry_tags 에 기록한다(테스트 데이터)."""
    tt.record_entry_tag(
        order_id=order_id, symbol="005930", trade_date=trade_date,
        selection_reason={"sources": list(sources), "scores": {}, "llm_note": ""},
        fired_groups=list(fired),
        condition_states={"체결강도": 0.6},
        market_context={"regime": regime, "market_tone": "neutral",
                        "time_bucket": "10:30", "vix": 18.0},
    )
    tt.set_outcome(order_id=order_id,
                   outcome={"realized_pnl": pnl, "win": win, "hold_sec": 600,
                            "exit_reason": "x"})


def _clear_memory(trade_date):
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM learning_memories WHERE trade_date = ? AND category = 'ev_pruning'",
            (trade_date,),
        )


def test_run_ev_pruning_aggregates_and_writes_memory_without_apply():
    d = "2099-07-01"
    tt._delete_for_test(d)
    _clear_memory(d)
    gid = _seed_group("EVRUN_음수그룹", weight=1.0)
    try:
        # 음수 EV 그룹 31표본: 8승(+200) 23패(-1000) → EV 음수
        for i in range(8):
            _record_settled(d, f"w{i}", ["EVRUN_음수그룹"], ["등락률순위#3"], "neutral", 200, True)
        for i in range(23):
            _record_settled(d, f"l{i}", ["EVRUN_음수그룹"], ["등락률순위#3"], "neutral", -1000, False)

        result = evp.run_ev_pruning(d, lookback_days=5, min_sample=30, apply=False)

        # 집계: fired_group EV 결과에 음수그룹 존재
        assert result["sample_size"] == 31
        fg = result["ev_results"]["fired_group"]["EVRUN_음수그룹"]
        assert fg["n"] == 31
        assert fg["ev"] < 0
        # 추천: negative-first 로 음수그룹 downweight
        targets = [r["target"] for r in result["recommendations"]]
        assert "EVRUN_음수그룹" in targets
        # apply=False → weight 미변경
        w, _ = _weight_enabled(gid)
        assert w == 1.0
        assert result["applied"]["adjusted"] == 0
        # learning_memories 에 negative-knowledge 1행 기록됨
        with get_connection() as conn:
            mem = conn.execute(
                "SELECT scope, category, summary, recommendation FROM learning_memories "
                "WHERE trade_date = ? AND category = 'ev_pruning'", (d,)
            ).fetchone()
        assert mem is not None
        assert mem["category"] == "ev_pruning"
        rec = json.loads(mem["recommendation"])
        assert any(r["target"] == "EVRUN_음수그룹" for r in rec["pruning"])
    finally:
        _cleanup(gid)
        tt._delete_for_test(d)
        _clear_memory(d)


def test_run_ev_pruning_apply_adjusts_weight():
    d = "2099-07-02"
    tt._delete_for_test(d)
    _clear_memory(d)
    gid = _seed_group("EVRUN_적용그룹", weight=1.0)
    try:
        for i in range(8):
            _record_settled(d, f"aw{i}", ["EVRUN_적용그룹"], [], "neutral", 200, True)
        for i in range(23):
            _record_settled(d, f"al{i}", ["EVRUN_적용그룹"], [], "neutral", -1000, False)

        result = evp.run_ev_pruning(d, lookback_days=5, min_sample=30, apply=True)
        assert result["applied"]["adjusted"] == 1
        w, _ = _weight_enabled(gid)
        assert w == 0.5            # downweight 적용됨
    finally:
        _cleanup(gid)
        tt._delete_for_test(d)
        _clear_memory(d)


def test_run_ev_pruning_insufficient_sample_no_recommendation():
    d = "2099-07-03"
    tt._delete_for_test(d)
    _clear_memory(d)
    gid = _seed_group("EVRUN_소표본", weight=1.0)
    try:
        # 표본 5건만 (min_sample=30 미달) → 추천 없음, weight 불변
        for i in range(5):
            _record_settled(d, f"s{i}", ["EVRUN_소표본"], [], "neutral", -1000, False)
        result = evp.run_ev_pruning(d, lookback_days=5, min_sample=30, apply=True)
        assert result["recommendations"] == []
        w, _ = _weight_enabled(gid)
        assert w == 1.0
    finally:
        _cleanup(gid)
        tt._delete_for_test(d)
        _clear_memory(d)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_ev_pruning.py -k run_ev_pruning -q`
Expected: FAIL — `AttributeError: module 'backend.services.engine.ev_pruning' has no attribute 'run_ev_pruning'`

- [ ] **Step 3: 최소 구현 작성**

`backend/services/engine/ev_pruning.py` 끝에 추가:

```python
_DIMENSIONS = ("fired_group", "selection_source", "regime")


def _load_multiday_tags(trade_date: str, lookback_days: int) -> list[dict[str, Any]]:
    """trade_date 기준 과거 lookback_days(포함) 거래일의 태그를 모두 모은다.

    Args:
        trade_date: 기준 거래일 YYYY-MM-DD.
        lookback_days: 거슬러 올라갈 일수(캘린더 기준, 단순 합집합).
    """
    base = datetime.fromisoformat(f"{trade_date}T00:00:00")
    tags: list[dict[str, Any]] = []
    for offset in range(lookback_days + 1):
        d = (base - timedelta(days=offset)).date().isoformat()
        tags.extend(load_tags(d))
    return tags


def _write_ev_memory(
    trade_date: str,
    ev_results: dict[str, dict[str, dict[str, float]]],
    recommendations: list[dict[str, Any]],
    sample_size: int,
) -> None:
    """negative-knowledge("고르지/사지 말아야 할") 요약을 learning_memories 에 1행 기록한다.

    기존 학습루프와 동일한 테이블·컬럼 사용(category="ev_pruning"). 추천이 없으면
    "현재 가지칠 대상 없음" 요약을 남겨 관측 가능성을 유지한다.

    Args:
        trade_date: 기준 거래일.
        ev_results: {dimension: compute_ev_by_dimension 결과}.
        recommendations: recommend_pruning 출력(전 차원 병합).
        sample_size: 집계에 쓰인 정산 태그 수.
    """
    now = _now_kst_iso()
    expires_at = (datetime.fromisoformat(f"{trade_date}T00:00:00") + timedelta(days=7)).date().isoformat()
    if recommendations:
        worst = recommendations[0]
        summary = (
            f"[{trade_date}] EV 가지치기 — 사지/고르지 말아야 할 {len(recommendations)}건. "
            f"최악: {worst['target']} ({worst['reason']})."
        )
    else:
        summary = f"[{trade_date}] EV 가지치기 — 표본 {sample_size}건, 현재 가지칠 음수EV 대상 없음."

    memory_id = str(uuid.uuid4())
    evidence = {"sample_size": sample_size, "ev_results": ev_results}
    recommendation = {
        "action": "prune_negative_ev_targets",
        "pruning": recommendations,
        "guidance": "EV 음수 그룹/선정소스는 다음날 매수에서 가중↓/회피한다(negative knowledge).",
        "rag_usage": "리뷰·다음날 선정/매수 컨텍스트 — '사지/고르지 말아야 할' 참고 메모리",
    }
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM learning_memories WHERE trade_date = ? AND category = 'ev_pruning'",
            (trade_date,),
        )
        conn.execute(
            """
            INSERT INTO learning_memories
                (memory_id, trade_date, scope, category, summary, evidence,
                 recommendation, auto_apply_allowed, requires_approval, status,
                 expires_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory_id, trade_date, "S6_BUY_ENGINE", "ev_pruning", summary,
                json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
                json.dumps(recommendation, ensure_ascii=False, separators=(",", ":")),
                0, 0, "active", expires_at, now,
            ),
        )


def run_ev_pruning(
    trade_date: str,
    lookback_days: int = 10,
    min_sample: int = 30,
    apply: bool = False,
) -> dict[str, Any]:
    """EOD 결선: 멀티데이 태그 로드→3차원 EV 집계→추천→(apply 시)자동가중→메모리 기록.

    기존 EOD 학습루프에 얹는 스텝이다. 새 파이프라인이 아니다.

    Args:
        trade_date: 기준 거래일 YYYY-MM-DD.
        lookback_days: 집계 lookback 일수(기본 10).
        min_sample: 가지치기 최소 표본(기본 30).
        apply: True 면 condition_groups.weight 자동 반영, False 면 추천·메모리만.
    """
    logger.info("START: [EV] run_ev_pruning trade_date=%s lookback=%d apply=%s",
                trade_date, lookback_days, apply)
    tags = _load_multiday_tags(trade_date, lookback_days)
    settled = [t for t in tags if (t.get("outcome") or {}).get("realized_pnl") is not None]
    sample_size = len(settled)

    ev_results: dict[str, dict[str, dict[str, float]]] = {}
    recommendations: list[dict[str, Any]] = []
    for dim in _DIMENSIONS:
        dim_ev = ev_analysis.compute_ev_by_dimension(tags, dim)
        ev_results[dim] = dim_ev
        recommendations.extend(ev_analysis.recommend_pruning(dim_ev, min_sample=min_sample))
    recommendations.sort(key=lambda r: r["ev"])  # 전 차원 병합 후 negative-first 재정렬

    applied = {"adjusted": 0, "adjusted_groups": [], "skipped": []}
    if apply:
        applied = apply_auto_weight(recommendations)

    _write_ev_memory(trade_date, ev_results, recommendations, sample_size)

    logger.info("SUCCESS: [EV] run_ev_pruning trade_date=%s sample=%d recs=%d adjusted=%d",
                trade_date, sample_size, len(recommendations), applied["adjusted"])
    return {
        "ok": True,
        "trade_date": trade_date,
        "sample_size": sample_size,
        "ev_results": ev_results,
        "recommendations": recommendations,
        "applied": applied,
    }
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_ev_pruning.py -q`
Expected: PASS (8 passed)

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/ev_pruning.py tests/unit/test_ev_pruning.py
git commit -m "feat: run_ev_pruning — 멀티데이 EV 집계+추천+자동가중+negative-knowledge 메모리(기존 학습루프 재사용) (탐색엔진 Phase 3)"
```

---

## Task 5: EOD 학습루프 결선 — scheduler ReviewAudit 잡에 Step 6 추가

기존 ReviewAudit 잡(Step 0~5: false_positive → review_audit → missed → learning_memory → loss_streak → consolidate_and_apply) 끝에 **Step 6(EV 가지치기)** 를 비차단으로 추가한다. `run_review_audit` 본체는 손대지 않는다(기존 동작 무손상).

**Files:**
- Modify: `backend/services/scheduler.py` (Step 5 직후, `job_postprocess` 류 ReviewAudit 잡 함수 내)
- Test: `tests/unit/test_ev_pruning.py` (import smoke — 별도 추가 없이 기존 통과로 충족; 결선은 통합 동작이라 수동 확인)

- [ ] **Step 1: 결선 지점 확인**

Run: `grep -n "손실전략 종합 반영 applied" backend/services/scheduler.py`
Expected: `consolidate_and_apply` 로깅 라인(현 1198 부근) — 이 직후가 Step 6 삽입 지점.

- [ ] **Step 2: Step 6 삽입**

`backend/services/scheduler.py` 의 아래 블록(Step 5 — 손실전략 종합 반영)을 찾는다:

```python
    # ── Step 5: EOD 손실전략 종합 반영 (Missed + False 병합 → 1회 자동 upsert)
    try:
        from .engine.loss_analysis import consolidate_and_apply
        applied = consolidate_and_apply(today)
        logger.info("SUCCESS: [ReviewAudit] 손실전략 종합 반영 applied=%d case=%d",
                    len(applied.get("applied", [])), applied.get("case_count", 0))
    except Exception as exc:
        logger.error("FAIL: [ReviewAudit] 손실전략 종합 반영 실패 — %s", exc)
```

그 **블록 바로 다음 줄**에 아래 Step 6 블록을 추가한다(같은 들여쓰기, 함수 끝 빈 줄 전):

```python

    # ── Step 6: 탐색엔진 EV 가지치기 + 자동가중 (Phase 3 — 기존 학습루프에 얹는 스텝)
    # 멀티데이 태그(trade_entry_tags)로 그룹/선정소스/레짐별 EV 집계 → 음수 우선 가지치기
    # 추천 → condition_groups.weight 자동 반영 → "사지/고르지 말아야 할" negative-knowledge
    # 메모리 기록. 표본 부족 시 추천 없이 관측만(탐색 중 고손실일 자동 방어전환 방지).
    try:
        from .engine.ev_pruning import run_ev_pruning

        ev_result = run_ev_pruning(today, lookback_days=10, min_sample=30, apply=True)
        logger.info(
            "SUCCESS: [ReviewAudit] EV 가지치기 sample=%d recs=%d adjusted=%d",
            ev_result.get("sample_size", 0),
            len(ev_result.get("recommendations", [])),
            ev_result.get("applied", {}).get("adjusted", 0),
        )
    except Exception as exc:
        logger.error("FAIL: [ReviewAudit] EV 가지치기 실패 — %s", exc)
```

- [ ] **Step 3: import 회귀 + 전체 단위테스트 확인**

Run: `PYTHONPATH=. .venv/bin/python -c "import backend.services.scheduler; print('import ok')"`
Expected: `import ok`

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_ev_analysis.py tests/unit/test_ev_pruning.py -q`
Expected: PASS (전체 통과 — analysis 13 + pruning 8 = 21 passed)

- [ ] **Step 4: 커밋**

```bash
git add backend/services/scheduler.py
git commit -m "feat: EOD ReviewAudit 잡에 EV 가지치기 Step 6 결선(기존 학습루프 재사용, 비차단) (탐색엔진 Phase 3)"
```

---

## Self-Review

**1. Spec coverage (의뢰 SCOPE 1~4 + spec "측정·가지치기" 대조):**
- SCOPE 1 `compute_ev_by_dimension(tags, dimension)` → `{key:{n,wins,win_rate,avg_win,avg_loss,ev}}`, EV=win_rate*avg_win−loss_rate*avg_loss, 차원 fired_group/selection_source/regime → **Task 1**. per-condition 은 follow-up 노트로 명시(Shared Contracts + 후속 절). ✓
- SCOPE 2 `recommend_pruning(ev_results, min_sample=30)` NEGATIVE FIRST, n≥min_sample AND ev<0 → downweight, 대표본 지속음수만 disable → **Task 2**. ✓
- SCOPE 3 `apply_auto_weight` → condition_groups.weight 조정, floor 0.1, 하드제로 금지(disable 도 floor 까지만) → **Task 3**. ✓
- SCOPE 4 EOD 결선: run_review_audit 잡 뒤에서 멀티데이 태그 로드→EV→추천→선택 적용→learning_memory 에 negative-knowledge 요약 + 기존 학습루프 재사용(새 파이프라인 아님) → **Task 4(메모리·결선) + Task 5(scheduler Step 6)**. ✓
- spec "표본 ≥ N(예 30)" → min_sample 기본 30. ✓ "EV 높은 그룹 weight↑, 낮은 그룹 weight↓"의 핵심(negative-first 하향) 구현, 상향은 본 Phase 범위 밖 — spec 강조점(negative-first)과 의뢰 SCOPE 에 맞춰 하향만 다룸(후속 절에 상향 노트). ✓
- spec "weight 0(완전차단)은 표본 매우 많고 지속 부진할 때만" → disable=대표본(disable_sample 90)만, 그것도 floor 0.1(완전 0 아님)로 운 좋은 전략 보존. ✓
- spec 안전장치 "탐색 중 고손실일 자동 방어전환 방지 — 표본 충분 시에만 가지치기" → min_sample 미달 시 추천 없음(Task 4 `test_run_ev_pruning_insufficient_sample_no_recommendation`) + Step 6 주석. ✓
- "기존 재사용(consolidate_and_apply·learning_memories·설정 자동반영)에 디테일만 얹는다" → learning_memories 동일 테이블·컬럼 재사용(category="ev_pruning"), scheduler 기존 잡에 Step 6 1개만 추가, run_review_audit 본체 무변경. ✓

**2. Placeholder scan:** TBD/TODO/"적절히 처리"/"위와 유사" 없음. 모든 코드 스텝에 완전한 실제 코드 포함. ✓

**3. Type consistency:**
- `compute_ev_by_dimension` 반환 키(n/wins/win_rate/avg_win/avg_loss/ev) — Task 1 테스트·Task 2 입력·Task 4 evidence 전부 동일. ✓
- `recommend_pruning` 반환 dict 키(target/action/reason/n/ev) — Task 2 테스트·Task 3 `apply_auto_weight` 입력(`rec["target"]`,`rec["action"]`)·Task 4 정렬키(`r["ev"]`) 일치. ✓
- `apply_auto_weight` 반환 키(adjusted/adjusted_groups/skipped) — Task 3 테스트·Task 4 기본값·Task 5 로깅(`applied["adjusted"]`) 일치. ✓
- `run_ev_pruning` 반환 키(ok/trade_date/sample_size/ev_results/recommendations/applied) — Task 4 테스트·Task 5 로깅 일치. ✓
- `condition_groups` 매칭은 `name` 기준(태그 fired_groups 가 name 담음) — Shared Contracts·Task 3 SQL·Task 3 테스트(`_seed_group` name)·spec 일치. ✓
- `learning_memories` INSERT 컬럼 순서 — learning_memory.py 의 동일 12컬럼 INSERT 와 정확히 동일(memory_id…created_at). ✓
- `load_tags`/`record_entry_tag`/`set_outcome`/`_delete_for_test` 시그니처 — Phase 1c 계약과 일치(키워드 전용 호출). ✓
- `bcf._ensure_tables` — Phase 1a 정의 사용(Task 3 테스트가 호출). ✓

수정 사항 없음 — 계획 일관성 확인됨.

---

## 완료 기준 (Phase 3)
- [ ] `compute_ev_by_dimension`(3차원)·`recommend_pruning`(negative-first) 순수 함수 — 단위테스트 전체 PASS.
- [ ] `apply_auto_weight` — condition_groups.weight floor 0.1·하드제로 금지 — DB 테스트 PASS.
- [ ] `run_ev_pruning` — 멀티데이 집계+추천+자동가중+learning_memories(category=ev_pruning) 기록 — DB 테스트 PASS.
- [ ] scheduler ReviewAudit 잡에 Step 6 결선 + `import backend.services.scheduler` 정상.
- [ ] `run_review_audit` 본체 무변경(기존 동작 무손상).

## 후속 (이 계획 범위 밖)
- **per-condition EV(차원 "condition"):** 개별 원자조건의 임계 충족 여부별 EV(예 "체결강도≥0.55 인 진입 vs 미만"의 EV 비교). condition_states + buy_conditions params 의 임계 대조 로직 필요 → must-have 인 per-fired_group 이후 후속.
- **positive 자동가중(weight↑):** EV 높은 그룹 가중 상향. 본 Phase 는 spec 강조점(negative-knowledge-first)에 맞춰 하향(downweight/disable)만 다룸.
- **Review UI 표기:** 차원별 EV 표 + 가지치기 추천 노출(Phase 2/UI 영역). 본 Phase 는 데이터·메모리까지.
- **탐색모드 게이트 연동:** 탐색모드 플래그 ON 동안 가지치기 보류 정책의 플래그 결선(Phase 1d 게이트와 연동).

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-06-exploration-engine-phase3-ev-pruning-autoweight.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — 태스크마다 새 subagent 디스패치, 태스크 간 리뷰, 빠른 반복.

**2. Inline Execution** — 이 세션에서 executing-plans 로 체크포인트 단위 일괄 실행.

**Which approach?**
