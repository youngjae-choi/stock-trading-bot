# 탐색엔진 Phase 1c — 통짜 태깅 (trade_entry_tags) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 매수 체결 순간 "선정사유 + 발화그룹 + 전체 조건상태 + 시장맥락"을 1행으로 기록하고 청산 시 결과(outcome)를 채우는 `trade_entry_tags` 데이터 계층과 헬퍼 모듈을 구축한다. 이것이 Phase 3 EV 가지치기의 데이터 토대다.

**Architecture:** 순수 SQLite 데이터 계층. `backend/services/engine/trade_tagging.py` 단일 모듈이 테이블 생성(`_ensure_table`), 매수 시 태그 기록(`record_entry_tag`), 청산 시 결과 채움(`set_outcome`), 일자별 조회(`load_tags`), S4 후보 dict에서 선정사유 추출(`build_selection_reason`)을 제공한다. 모든 dict/list 컬럼은 JSON 직렬화해 TEXT로 저장한다. `market_context`와 `outcome`은 **호출부가 dict로 전달**해 단위 테스트 가능성을 유지한다(이 Phase에서 order_executor 통합·WS 조건수집은 다루지 않는다 — Phase 1b/1d 영역). 테스트는 실제 `get_connection()`(daily_capital 패턴과 동일)으로 `2099-XX-XX` 테스트 trade_date를 쓰고 `_delete_for_test`로 정리한다.

**Tech Stack:** Python 3 (stdlib `sqlite3`, `json`, `uuid`, `datetime`), pytest. DB 접근은 `backend.services.db.get_connection`. 실행: `PYTHONPATH=. .venv/bin/python`.

---

## Shared Contract — `trade_entry_tags` 스키마 (이 Phase가 확정 — Phase 3가 의존)

```sql
CREATE TABLE IF NOT EXISTS trade_entry_tags (
    id                    TEXT PRIMARY KEY,
    order_id              TEXT NOT NULL DEFAULT '',
    symbol                TEXT NOT NULL DEFAULT '',
    trade_date            TEXT NOT NULL DEFAULT '',
    selection_reason_json TEXT NOT NULL DEFAULT '{}',
    fired_groups_json     TEXT NOT NULL DEFAULT '[]',
    condition_states_json TEXT NOT NULL DEFAULT '{}',
    market_context_json   TEXT NOT NULL DEFAULT '{}',
    outcome_json          TEXT NOT NULL DEFAULT '{}',
    created_at            TEXT NOT NULL
)
```

인덱스: `idx_trade_entry_tags_trade_date(trade_date)`, `idx_trade_entry_tags_order_id(order_id)`.

JSON 컬럼 의미 (spec "태깅" 구조):
- `selection_reason_json`: `{"sources": [...], "scores": {...}, "llm_note": "..."}` — ① 왜 후보로 선정됐나 (S3/S4).
- `fired_groups_json`: `["돌파전략", ...]` — ③ OR 중 발화 그룹.
- `condition_states_json`: `{"체결강도": 0.62, "틱거래량배수": 2.3, ...}` — 진입 순간 모든 원자조건 값.
- `market_context_json`: `{"regime", "market_tone", "time_bucket", "vix"}` — ④ 어떤 상황. `regime`/`market_tone`은 `daily_plan`/`market_tone_results`에서 오지만, 이 Phase의 함수는 **호출부가 만든 dict를 그대로 받는다**(테스트 가능성 유지).
- `outcome_json`: `{"realized_pnl", "win", "hold_sec", "exit_reason"}` — 청산 시 채움. 실제 값 출처는 `review_audit._sync_realized_pnl_from_trade_pairs` / `trade_pairs.get_trade_pairs`(매도완료 페어의 pnl_amount·pnl_pct·hold)다. 이 Phase의 `set_outcome`은 그 dict를 받아 UPDATE만 한다.

---

## File Structure

| 파일 | 역할 | 생성/수정 |
|------|------|-----------|
| `backend/services/engine/trade_tagging.py` | 태깅 데이터 계층 모듈 전체 (`_ensure_table`, `record_entry_tag`, `set_outcome`, `load_tags`, `build_selection_reason`, `_delete_for_test`) | 생성 |
| `tests/unit/test_trade_tagging.py` | 위 모듈 단위 테스트 | 생성 |

> 단일 책임: 태깅 DB 로직만. order_executor 매수경로 통합(record 호출 주입), WS 기반 condition_states 수집, market_context 실데이터 결선은 **별도 Phase(1b/1d)** 작업이며 이 계획에 포함하지 않는다. 본 계획은 데이터 토대만 완성한다.

---

## Task 1: 테이블 + record_entry_tag + load_tags 라운드트립

매수 태그를 기록하고 일자별로 다시 읽어 JSON 필드가 dict/list로 복원되는지 검증한다.

**Files:**
- Create: `backend/services/engine/trade_tagging.py`
- Test: `tests/unit/test_trade_tagging.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/unit/test_trade_tagging.py`:

```python
import backend.services.engine.trade_tagging as tt


def test_record_and_load_roundtrip():
    d = "2099-03-01"
    tt._delete_for_test(d)

    tag_id = tt.record_entry_tag(
        order_id="ord-1",
        symbol="005930",
        trade_date=d,
        selection_reason={"sources": ["등락률순위#3", "거래대금상위"],
                          "scores": {"universe_score": 0.36, "llm_suitability": 0.72},
                          "llm_note": "반도체 섹터 강세"},
        fired_groups=["돌파전략"],
        condition_states={"체결강도": 0.62, "틱거래량배수": 2.3, "돌파": True, "눌림": False},
        market_context={"regime": "neutral", "market_tone": "negative",
                        "time_bucket": "10:30", "vix": 18.2},
    )
    assert isinstance(tag_id, str) and tag_id

    tags = tt.load_tags(d)
    assert len(tags) == 1
    row = tags[0]
    assert row["id"] == tag_id
    assert row["order_id"] == "ord-1"
    assert row["symbol"] == "005930"
    assert row["trade_date"] == d
    # JSON 필드가 파이썬 객체로 복원됨
    assert row["selection_reason"]["sources"] == ["등락률순위#3", "거래대금상위"]
    assert row["selection_reason"]["scores"]["llm_suitability"] == 0.72
    assert row["fired_groups"] == ["돌파전략"]
    assert row["condition_states"]["돌파"] is True
    assert row["condition_states"]["눌림"] is False
    assert row["market_context"]["regime"] == "neutral"
    assert row["market_context"]["vix"] == 18.2
    # outcome 은 아직 비어 있음 (빈 dict)
    assert row["outcome"] == {}

    tt._delete_for_test(d)


def test_load_tags_empty_returns_empty_list():
    d = "2099-03-02"
    tt._delete_for_test(d)
    assert tt.load_tags(d) == []
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_trade_tagging.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.services.engine.trade_tagging'`

- [ ] **Step 3: 최소 구현 작성**

`backend/services/engine/trade_tagging.py`:

```python
"""탐색엔진 통짜 태깅 데이터 계층 (trade_entry_tags).

매수 체결 시 1행 기록(선정사유+발화그룹+조건상태+시장맥락), 청산 시 결과(outcome) 채움.
이 통짜 기록으로 Phase 3가 임의 조건/그룹/맥락별 승률·EV를 오프라인 집계해 가지치기한다.

market_context/outcome 은 호출부가 dict로 전달한다(테스트 가능성 유지):
- market_context: regime/market_tone 은 daily_plan / market_tone_results 에서 온다.
- outcome: realized_pnl/win/hold_sec/exit_reason 은 청산 후 trade_pairs(매도완료) 에서 온다.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection

logger = logging.getLogger("TradeTagging")


def _now_kst_iso() -> str:
    """현재 Asia/Seoul 시각을 ISO 문자열로 반환한다."""
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def _ensure_table() -> None:
    """trade_entry_tags 테이블과 인덱스를 없으면 생성한다."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trade_entry_tags (
                id                    TEXT PRIMARY KEY,
                order_id              TEXT NOT NULL DEFAULT '',
                symbol                TEXT NOT NULL DEFAULT '',
                trade_date            TEXT NOT NULL DEFAULT '',
                selection_reason_json TEXT NOT NULL DEFAULT '{}',
                fired_groups_json     TEXT NOT NULL DEFAULT '[]',
                condition_states_json TEXT NOT NULL DEFAULT '{}',
                market_context_json   TEXT NOT NULL DEFAULT '{}',
                outcome_json          TEXT NOT NULL DEFAULT '{}',
                created_at            TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trade_entry_tags_trade_date ON trade_entry_tags(trade_date)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trade_entry_tags_order_id ON trade_entry_tags(order_id)"
        )


def _dumps(value: Any) -> str:
    """dict/list 를 JSON 문자열로 직렬화한다(한글 보존)."""
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def record_entry_tag(
    *,
    order_id: str,
    symbol: str,
    trade_date: str,
    selection_reason: dict,
    fired_groups: list,
    condition_states: dict,
    market_context: dict,
) -> str:
    """매수 체결 시 태그 1행을 기록하고 태그 id 를 반환한다.

    Args:
        order_id: trading_orders.id (매수 주문 로컬 id).
        symbol: 종목 코드.
        trade_date: YYYY-MM-DD 거래일.
        selection_reason: {"sources": [...], "scores": {...}, "llm_note": "..."}.
        fired_groups: OR 중 발화한 그룹명 리스트.
        condition_states: 진입 순간 모든 원자조건 값 dict.
        market_context: {"regime", "market_tone", "time_bucket", "vix"} dict.
    """
    _ensure_table()
    tag_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO trade_entry_tags
                (id, order_id, symbol, trade_date, selection_reason_json,
                 fired_groups_json, condition_states_json, market_context_json,
                 outcome_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tag_id,
                str(order_id or ""),
                str(symbol or ""),
                str(trade_date or ""),
                _dumps(selection_reason),
                _dumps(fired_groups if fired_groups is not None else []),
                _dumps(condition_states),
                _dumps(market_context),
                "{}",
                _now_kst_iso(),
            ),
        )
    logger.info("SUCCESS: 태그 기록 tag_id=%s order_id=%s symbol=%s", tag_id, order_id, symbol)
    return tag_id


def load_tags(trade_date: str) -> list[dict]:
    """해당 거래일의 모든 태그를 JSON 필드를 파싱해 반환한다.

    Args:
        trade_date: YYYY-MM-DD 거래일.
    """
    _ensure_table()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM trade_entry_tags WHERE trade_date = ? ORDER BY created_at ASC",
            (trade_date,),
        ).fetchall()
    return [_parse_row(dict(row)) for row in rows]


def _parse_row(row: dict) -> dict:
    """DB row 의 *_json 컬럼을 파이썬 객체로 풀어 사용 친화적 dict 로 변환한다."""
    def _loads(text: Any, fallback: Any) -> Any:
        if not text:
            return fallback
        try:
            return json.loads(text)
        except (TypeError, ValueError):
            return fallback

    return {
        "id": row.get("id"),
        "order_id": row.get("order_id"),
        "symbol": row.get("symbol"),
        "trade_date": row.get("trade_date"),
        "selection_reason": _loads(row.get("selection_reason_json"), {}),
        "fired_groups": _loads(row.get("fired_groups_json"), []),
        "condition_states": _loads(row.get("condition_states_json"), {}),
        "market_context": _loads(row.get("market_context_json"), {}),
        "outcome": _loads(row.get("outcome_json"), {}),
        "created_at": row.get("created_at"),
    }


def _delete_for_test(trade_date: str) -> None:
    """테스트 정리용: 해당 거래일 태그를 모두 삭제한다."""
    _ensure_table()
    with get_connection() as conn:
        conn.execute("DELETE FROM trade_entry_tags WHERE trade_date = ?", (trade_date,))
```

> 주의: `record_entry_tag` 는 키워드 전용(`*`) 시그니처다. 테스트도 키워드로 호출한다(Step 1 참고).

- [ ] **Step 4: 테스트 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_trade_tagging.py -v`
Expected: PASS (2 passed) — `test_record_and_load_roundtrip`, `test_load_tags_empty_returns_empty_list`

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/trade_tagging.py tests/unit/test_trade_tagging.py
git commit -m "feat: trade_entry_tags 테이블 + record_entry_tag/load_tags 라운드트립 (탐색엔진 Phase 1c)"
```

---

## Task 2: set_outcome — 청산 결과 채움

청산 후 `order_id` 로 해당 태그의 `outcome_json` 을 UPDATE 한다. 매칭되는 order_id 가 여러 행이면 모두 갱신(보통 1행), 없으면 0 갱신.

**Files:**
- Modify: `backend/services/engine/trade_tagging.py` (append `set_outcome`)
- Test: `tests/unit/test_trade_tagging.py` (append)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/unit/test_trade_tagging.py` 끝에 추가:

```python
def test_set_outcome_fills_by_order_id():
    d = "2099-03-03"
    tt._delete_for_test(d)
    tt.record_entry_tag(
        order_id="ord-out",
        symbol="000660",
        trade_date=d,
        selection_reason={"sources": ["거래대금상위"], "scores": {}, "llm_note": ""},
        fired_groups=["눌림전략"],
        condition_states={"체결강도": 0.55},
        market_context={"regime": "neutral", "market_tone": "neutral",
                        "time_bucket": "13:00", "vix": 15.0},
    )

    updated = tt.set_outcome(
        order_id="ord-out",
        outcome={"realized_pnl": -1700, "win": False, "hold_sec": 1820,
                 "exit_reason": "stop_loss"},
    )
    assert updated == 1

    row = tt.load_tags(d)[0]
    assert row["outcome"]["realized_pnl"] == -1700
    assert row["outcome"]["win"] is False
    assert row["outcome"]["hold_sec"] == 1820
    assert row["outcome"]["exit_reason"] == "stop_loss"
    tt._delete_for_test(d)


def test_set_outcome_missing_order_returns_zero():
    updated = tt.set_outcome(order_id="no-such-order", outcome={"win": True})
    assert updated == 0
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_trade_tagging.py::test_set_outcome_fills_by_order_id tests/unit/test_trade_tagging.py::test_set_outcome_missing_order_returns_zero -v`
Expected: FAIL — `AttributeError: module 'backend.services.engine.trade_tagging' has no attribute 'set_outcome'`

- [ ] **Step 3: 최소 구현 작성**

`backend/services/engine/trade_tagging.py` 의 `_delete_for_test` 정의 **앞**에 추가:

```python
def set_outcome(*, order_id: str, outcome: dict) -> int:
    """청산 후 order_id 로 태그의 outcome_json 을 갱신하고 갱신된 행 수를 반환한다.

    Args:
        order_id: 매수 주문의 trading_orders.id.
        outcome: {"realized_pnl", "win", "hold_sec", "exit_reason"} dict.
    """
    _ensure_table()
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE trade_entry_tags SET outcome_json = ? WHERE order_id = ?",
            (_dumps(outcome), str(order_id or "")),
        )
        updated = cursor.rowcount
    if updated == 0:
        logger.warning("WARN: set_outcome 매칭 태그 없음 order_id=%s", order_id)
    else:
        logger.info("SUCCESS: outcome 갱신 order_id=%s rows=%d", order_id, updated)
    return updated
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_trade_tagging.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/trade_tagging.py tests/unit/test_trade_tagging.py
git commit -m "feat: set_outcome — 청산 시 order_id 로 outcome_json 채움 (탐색엔진 Phase 1c)"
```

---

## Task 3: build_selection_reason — S4 후보에서 선정사유 추출

S4 후보 dict(`hybrid_screening.py` candidates 항목: symbol, name, score, suitability_score, change_rate, tsi, volume_rank, trade_rank, llm_note/reason 등)에서 `record_entry_tag` 가 받을 `selection_reason` dict(`sources`/`scores`/`llm_note`)를 만든다. 빠진 필드는 안전하게 누락한다.

**Files:**
- Modify: `backend/services/engine/trade_tagging.py` (append `build_selection_reason`)
- Test: `tests/unit/test_trade_tagging.py` (append)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/unit/test_trade_tagging.py` 끝에 추가:

```python
def test_build_selection_reason_full_candidate():
    candidate = {
        "symbol": "005930", "name": "삼성전자",
        "score": 0.36, "suitability_score": 0.72,
        "change_rate": 2.3, "tsi": 42.0,
        "volume_rank": 5, "trade_rank": 3,
        "llm_note": "반도체 섹터 강세 모멘텀",
    }
    sr = tt.build_selection_reason(candidate)
    # sources: 순위 기반 surfacing 근거
    assert "거래대금순위#3" in sr["sources"]
    assert "거래량순위#5" in sr["sources"]
    # scores: 점수 근거 (universe_score = score, llm_suitability = suitability_score)
    assert sr["scores"]["universe_score"] == 0.36
    assert sr["scores"]["llm_suitability"] == 0.72
    assert sr["scores"]["change_rate"] == 2.3
    assert sr["scores"]["일봉TSI"] == 42.0
    assert sr["llm_note"] == "반도체 섹터 강세 모멘텀"


def test_build_selection_reason_sparse_candidate():
    candidate = {"symbol": "000660", "score": 0.1}
    sr = tt.build_selection_reason(candidate)
    # 누락 필드는 sources/scores 에서 빠지고, 존재하는 것만 들어간다
    assert sr["sources"] == []
    assert sr["scores"] == {"universe_score": 0.1}
    assert sr["llm_note"] == ""


def test_build_selection_reason_ignores_sentinel_trade_rank():
    # trade_rank 미수신 sentinel(>100, 예 9999)은 source 로 넣지 않는다
    candidate = {"symbol": "005930", "trade_rank": 9999, "volume_rank": 2}
    sr = tt.build_selection_reason(candidate)
    assert "거래량순위#2" in sr["sources"]
    assert all("거래대금" not in s for s in sr["sources"])
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_trade_tagging.py -k build_selection_reason -v`
Expected: FAIL — `AttributeError: module 'backend.services.engine.trade_tagging' has no attribute 'build_selection_reason'`

- [ ] **Step 3: 최소 구현 작성**

`backend/services/engine/trade_tagging.py` 의 `set_outcome` 정의 **앞**에 추가:

```python
def _maybe_float(value: Any) -> float | None:
    """숫자로 변환 가능하면 float, 아니면 None 을 반환한다."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_selection_reason(candidate: dict) -> dict:
    """S4 후보 dict 에서 record_entry_tag 용 selection_reason 을 추출한다.

    선정사유 = 어떤 소스가 종목을 surfacing 했나(sources) + 점수 근거(scores) + LLM 메모(llm_note).
    빠진 필드는 안전하게 누락한다. (hybrid_screening candidates 항목 기준:
    score=유니버스 블렌드 점수, suitability_score=LLM 적합도, trade_rank>100 은 미수신 sentinel)

    Args:
        candidate: S3/S4 후보 종목 dict.
    """
    candidate = candidate or {}

    sources: list[str] = []
    trade_rank = candidate.get("trade_rank")
    if isinstance(trade_rank, (int, float)) and 0 < trade_rank <= 100:
        sources.append(f"거래대금순위#{int(trade_rank)}")
    volume_rank = candidate.get("volume_rank")
    if isinstance(volume_rank, (int, float)) and 0 < volume_rank <= 100:
        sources.append(f"거래량순위#{int(volume_rank)}")

    scores: dict[str, float] = {}
    universe_score = _maybe_float(candidate.get("score"))
    if universe_score is not None:
        scores["universe_score"] = universe_score
    suitability = _maybe_float(candidate.get("suitability_score"))
    if suitability is not None:
        scores["llm_suitability"] = suitability
    change_rate = _maybe_float(candidate.get("change_rate"))
    if change_rate is not None:
        scores["change_rate"] = change_rate
    tsi = _maybe_float(candidate.get("tsi"))
    if tsi is not None:
        scores["일봉TSI"] = tsi

    llm_note = str(candidate.get("llm_note") or candidate.get("reason") or "").strip()

    return {"sources": sources, "scores": scores, "llm_note": llm_note}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_trade_tagging.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/trade_tagging.py tests/unit/test_trade_tagging.py
git commit -m "feat: build_selection_reason — S4 후보에서 선정사유(sources/scores/llm_note) 추출 (탐색엔진 Phase 1c)"
```

---

## Self-Review

**1. Spec coverage:**
- spec "태깅" JSON(selection_reason/fired_groups/condition_states/market_context/outcome) → Task 1 record_entry_tag + 스키마가 5개 JSON 컬럼 전부 커버. ✓
- "매수 체결 시 1행 기록" → Task 1. ✓ "청산 시 결과 채움" → Task 2 set_outcome. ✓
- "선정사유까지 태깅"(등락률/거래대금/LLM 비교 가능) → Task 3 build_selection_reason 의 sources/scores. ✓
- market_context regime/market_tone 출처(daily_plan/market_tone_results) 명시 + 함수는 dict 인자 수령(테스트 가능성) → Architecture/Contract 노트 + Task 1 시그니처. ✓
- outcome 출처(trade_pairs 매도완료 pnl) 명시 → Contract 노트. ✓
- `_ensure_table`, `load_tags`(json 파싱 복원) → Task 1. ✓
- 의뢰서 "suggested tasks" 3개(테이블+record+load 라운드트립 / set_outcome / build_selection_reason) → Task 1/2/3 일치. ✓
- 범위 외(order_executor 통합, WS 조건수집, Phase 3 EV 집계)는 File Structure 노트에서 명시적으로 제외. ✓

**2. Placeholder scan:** TBD/TODO/"적절히 처리"/"위와 유사" 없음. 모든 코드 스텝에 완전한 실제 코드 포함. ✓

**3. Type consistency:**
- `record_entry_tag`/`set_outcome` 키워드 전용(`*`) 시그니처 — 테스트 호출도 키워드 사용으로 일치. ✓
- `load_tags` 반환 dict 키(`selection_reason`, `fired_groups`, `condition_states`, `market_context`, `outcome` — *_json 접미사 없음)와 테스트 접근 키 일치. ✓
- `set_outcome` 반환 = 갱신 행 수(int), 테스트 `assert updated == 1`/`== 0` 일치. ✓
- `build_selection_reason` 반환 키(`sources`/`scores`/`llm_note`)가 `record_entry_tag` 의 `selection_reason` 인자 모양과 일치 → 실제 결합 가능. ✓
- `_dumps`/`_parse_row`/`_maybe_float` 모두 정의 후 사용. ✓

수정 사항 없음 — 계획 일관성 확인됨.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-06-exploration-engine-phase1c-trade-tagging.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — 태스크마다 새 subagent 디스패치, 태스크 간 리뷰, 빠른 반복.

**2. Inline Execution** — 이 세션에서 executing-plans 로 체크포인트 단위 일괄 실행.

**Which approach?**
