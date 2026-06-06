# 탐색엔진 Phase 2 — UI (사유 표기 + 조건/그룹 편집) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Phase 1이 만든 데이터(`trade_entry_tags`·`buy_conditions`·`condition_groups`)를 운영자가 **보고(Trade History/Monitor 사유)·편집(Settings 조건·그룹·할당)·검토(Review 스캐폴드)** 할 수 있게 하는 UI 계층과 그 UI가 필요로 하는 신규 매수조건 CRUD API를 구축한다.

**Architecture:** (1) 백엔드 — 기존 `trades/pairs` 응답에 `trade_entry_tags` 태그를 병합하는 enrich 헬퍼(`trade_pairs_tags.py`), 후보 응답에 선정사유를 더하는 `get_candidates` 확장, 그리고 조건/그룹 CRUD 신규 라우터(`buy_conditions.py`). (2) 프론트 — 기존 패턴(`fetchJson`/`escapeHtml`/bare-function in shared scope, `data-action` 디스패치)을 그대로 따라 statistics(거래내역)·trading-monitor(후보)·settings(편집기)·review(스캐폴드) 화면을 확장. 모든 신규 함수는 기존 split-script 스코프에 추가한다(IIFE/`window.` 노출 불필요 — 모든 console-*.js는 하나의 스코프로 합쳐 로드됨).

**Tech Stack:** Python 3 + FastAPI(`APIRouter`), SQLite(`backend/services/db.get_connection`), pytest + `fastapi.testclient.TestClient`(venv에 존재 확인됨). Vanilla JS(ES5 스타일, 클래식 스크립트). 실행: `PYTHONPATH=. .venv/bin/python -m pytest`, JS는 `node --check`.

**의존(Phase 1, 이미 커밋됨):**
- `backend/services/engine/trade_tagging.py` — `load_tags(trade_date) -> list[dict]` (각 dict: `id, order_id, symbol, trade_date, selection_reason{sources,scores,llm_note}, fired_groups[], condition_states{}, market_context{}, outcome{realized_pnl,win,hold_sec,exit_reason}, created_at`).
- `backend/services/engine/buy_condition_framework.py` — `load_conditions(enabled_only=False) -> {id:{id,name,ctype,params,enabled}}`, `load_groups(enabled_only=False) -> [{id,name,condition_ids,enabled,weight,assigned_to}]`, `seed_defaults()`, `_ensure_tables()`. 테이블: `buy_conditions(id,name,ctype,params_json,enabled,created_at)`, `condition_groups(id,name,condition_ids_json,enabled,weight,assigned_to,created_at)`.

> **주의:** `load_conditions`/`load_groups` 기본값은 `enabled_only=True`다. Settings 편집기는 **비활성 항목도 보여야** 하므로 항상 `enabled_only=False`로 호출한다.

---

## 기존 코드 — 변경 전 사실 (탐색 결과, 추측 아님)

- **거래내역 화면 = "statistics" 화면**이다(별도 trade-history 화면/JS 없음). `console-statistics.js`의 `renderTradePairs()`가 `/api/v1/trades/pairs?start&end` 응답의 `payload.pairs[]`를 행으로 그리고, 행 클릭 시 `stToggleDetail()`로 `renderOrderDetail(p.orders)` accordion을 연다. 각 pair에는 `trade_date, symbol, name, buy_price, sell_price, pnl_amount, pnl_pct, exit_reason, status, orders[]`가 있다(`backend/services/engine/trade_pairs.py:get_trade_pairs`). pair는 **order_id를 직접 노출하지 않지만** `orders[]` 각 항목에 매수/매도 주문이 들어있다.
- **trades/pairs 라우트**: `backend/api/routes/trades.py:47` `get_trade_pairs(start,end)` → `trade_pairs.get_trade_pairs(start,end)` 그대로 반환.
- **Trading Monitor 후보**: `backend/api/routes/trading_monitor.py:460 get_candidates()`가 `hybrid_screening_results.candidates`를 읽어 각 후보에 `code,name,profile,assignment_reason,score,change_rate,buy_readiness{overall_pct,met_count,total_count,conditions[]}`를 붙여 반환. 프론트 `console-trading-monitor.js:177 renderCandidateRow(c)`가 그림. `buy_readiness.conditions[]` 각 항목은 `{name,label,current_value,threshold_label,score_pct,met}`.
- **Settings 화면**(`#screen-settings`)에는 이미 "매수 조건 가드레일" 카드(`#buy-condition-tbody`)가 있고 `console-settings.js:343 loadBuyConditions()`가 min/max 등락률 2행만 채운다. **이 함수/카드는 건드리지 않는다.** 신규 "원자 조건·그룹" 편집기는 **별도 카드 + 신규 함수**로 추가한다(이름 충돌 회피).
- **화면 진입 디스패치**: `console-navigation.js:84` `name === "settings"` 분기에서 이미 `initSettingsUI(); loadBuyConditions(); loadRegimeSets();`를 호출한다. 신규 로더는 `initSettingsUI()`(console-settings.js:612) 내부에 한 줄 추가해 호출한다.
- **`data-action` 디스패치**: `console-actions.js`가 `event.target.closest('[data-action]')`의 `dataset.action`을 함수명으로 호출한다(추가 `data-*` 속성을 인자로 전달). 신규 버튼/입력도 같은 방식.
- **공통 헬퍼**: `fetchJson(url, opts)`(2xx 아니면 throw), `escapeHtml(s)`는 전역 스코프에 이미 존재(console-utils.js/console-api.js). 신규 코드에서 그대로 사용.
- **라우터 등록**: `backend/main.py`에서 `from .api.routes.X import router as X_router` 후 `app.include_router(X_router)`. 신규 라우터도 동일 패턴(trades_router 근처에 추가).
- **테스트 관례**: `tests/unit/`에 함수 직접 호출 단위테스트. 신규 라우트는 `TestClient`로 실제 HTTP 검증(venv에 `fastapi.testclient` 존재 확인). 테스트 격리는 `2099-XX-XX` trade_date + `_delete_for_test`/`_clear_all_for_test`(Phase 1 제공) 사용.

---

## File Structure

| 파일 | 책임 | 생성/수정 |
|------|------|-----------|
| `backend/services/engine/trade_pairs_tags.py` | pair 리스트에 `trade_entry_tags` 태그를 order_id 기준 병합 (순수 함수, 단위테스트 가능) | 생성 |
| `backend/api/routes/trades.py` | `get_trade_pairs` 응답에 `enrich_pairs_with_tags` 적용 | 수정 |
| `backend/api/routes/trading_monitor.py` | `get_candidates` 후보에 `selection_reason`(sources/llm_note) 필드 추가 | 수정 |
| `backend/api/routes/buy_conditions.py` | 조건/그룹 CRUD 라우터 (GET/PUT conditions, GET/PUT groups, regime/profile 메타) | 생성 |
| `backend/main.py` | 신규 라우터 import + `include_router` | 수정 |
| `backend/static/js/screens/console-statistics.js` | pair 행에 선정/매수/매도 사유 컬럼, accordion에 태그 상세 | 수정 |
| `backend/static/js/screens/console-trading-monitor.js` | 후보 행에 선정사유 줄 표시 | 수정 |
| `backend/static/js/screens/console-settings.js` | 원자조건·그룹빌더·할당 편집기(신규 함수 `loadConditionEditor` 등) | 수정 |
| `backend/static/js/screens/console-review.js` | 그룹/조건 통계 read-and-render 스캐폴드(`loadGroupStatsScaffold`) | 수정 |
| `backend/static/console.html` | statistics 헤더 컬럼 2개, settings 신규 카드, review 신규 카드 | 수정 |
| `tests/unit/test_trade_pairs_tags.py` | 병합 헬퍼 단위테스트 | 생성 |
| `tests/unit/test_buy_conditions_api.py` | 조건/그룹 CRUD 라우트 TestClient 테스트 | 생성 |

---

## 신규 API 엔드포인트 명세 (이 Phase가 확정)

라우터 prefix: `/api/v1/buy-conditions` (`backend/api/routes/buy_conditions.py`)

| 메서드 · 경로 | 용도 | 요청 본문 | 응답 (성공) |
|---|---|---|---|
| `GET /api/v1/buy-conditions/conditions` | 원자 조건 전체(비활성 포함) | — | `{ok:true, payload:{conditions:[{id,name,ctype,params,enabled}]}}` |
| `PUT /api/v1/buy-conditions/conditions/{cid}` | 조건 1개의 params/enabled 편집 | `{params?: object, enabled?: bool}` | `{ok:true, payload:{condition:{...}}}` (404 if 없음) |
| `GET /api/v1/buy-conditions/groups` | 그룹 전체(비활성 포함) | — | `{ok:true, payload:{groups:[{id,name,condition_ids,enabled,weight,assigned_to}]}}` |
| `POST /api/v1/buy-conditions/groups` | 그룹 신규 생성(AND 빌더) | `{name:str, condition_ids:[str], enabled?:bool, weight?:float, assigned_to?:str}` | `{ok:true, payload:{group:{...}}}` |
| `PUT /api/v1/buy-conditions/groups/{gid}` | 그룹 편집(조건목록·enabled·weight·할당) | `{name?,condition_ids?,enabled?,weight?,assigned_to?}` | `{ok:true, payload:{group:{...}}}` (404 if 없음) |
| `GET /api/v1/buy-conditions/assign-targets` | 할당 가능한 레짐/RiskProfile 목록(드롭다운 소스) | — | `{ok:true, payload:{regimes:[...], profiles:[...]}}` |

- `assigned_to`는 자유 문자열로 저장(`""`=미할당). 값 형식: `regime:risk_on` / `profile:HIGH_VOL` 등. 프론트가 prefix로 구분.
- `seed_defaults()`는 각 GET 진입 시 1회 호출해 빈 DB에서도 기본 조건/그룹이 보이도록 한다(idempotent — Phase 1a가 보장).

---

## Task 1: 태그 병합 헬퍼 `trade_pairs_tags.enrich_pairs_with_tags`

거래내역(pair) 리스트에 해당 날짜의 `trade_entry_tags`를 **매수 order_id 기준**으로 병합한다. 각 pair의 `orders[]` 중 `side=="buy"` 주문의 `id`(또는 `order_id`)와 태그의 `order_id`를 매칭한다. 매칭 실패 시 symbol+trade_date 폴백.

**Files:**
- Create: `backend/services/engine/trade_pairs_tags.py`
- Test: `tests/unit/test_trade_pairs_tags.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/test_trade_pairs_tags.py`:
```python
import backend.services.engine.trade_pairs_tags as tpt


def test_enrich_matches_by_buy_order_id():
    pairs = [{
        "trade_date": "2099-05-01", "symbol": "005930", "name": "삼성전자",
        "pnl_amount": -1700, "pnl_pct": -1.2, "exit_reason": "stop_loss",
        "orders": [
            {"id": "ord-buy-1", "side": "buy"},
            {"id": "ord-sell-1", "side": "sell"},
        ],
    }]
    tags = [{
        "order_id": "ord-buy-1", "symbol": "005930", "trade_date": "2099-05-01",
        "selection_reason": {"sources": ["거래대금순위#3"], "scores": {}, "llm_note": "반도체 강세"},
        "fired_groups": ["돌파전략"],
        "condition_states": {"체결강도": 0.62, "틱거래량배수": 2.3},
        "market_context": {"regime": "neutral"},
        "outcome": {"realized_pnl": -1700, "win": False, "exit_reason": "stop_loss"},
    }]
    out = tpt.enrich_pairs_with_tags(pairs, tags)
    tag = out[0]["entry_tag"]
    assert tag is not None
    assert tag["selection_reason"]["sources"] == ["거래대금순위#3"]
    assert tag["fired_groups"] == ["돌파전략"]
    assert out[0]["selection_summary"] == "거래대금순위#3 · 반도체 강세"
    assert out[0]["buy_reason_summary"] == "돌파전략"


def test_enrich_falls_back_to_symbol_date_when_no_order_id_match():
    pairs = [{
        "trade_date": "2099-05-02", "symbol": "000660", "name": "SK하이닉스",
        "orders": [{"id": "unknown", "side": "buy"}],
    }]
    tags = [{
        "order_id": "different-id", "symbol": "000660", "trade_date": "2099-05-02",
        "selection_reason": {"sources": ["등락률순위#1"], "scores": {}, "llm_note": ""},
        "fired_groups": ["눌림전략"], "condition_states": {}, "market_context": {}, "outcome": {},
    }]
    out = tpt.enrich_pairs_with_tags(pairs, tags)
    assert out[0]["entry_tag"] is not None
    assert out[0]["selection_summary"] == "등락률순위#1"
    assert out[0]["buy_reason_summary"] == "눌림전략"


def test_enrich_no_tag_leaves_summaries_empty():
    pairs = [{"trade_date": "2099-05-03", "symbol": "111111", "orders": [{"id": "x", "side": "buy"}]}]
    out = tpt.enrich_pairs_with_tags(pairs, [])
    assert out[0]["entry_tag"] is None
    assert out[0]["selection_summary"] == ""
    assert out[0]["buy_reason_summary"] == ""
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_trade_pairs_tags.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.services.engine.trade_pairs_tags'`

- [ ] **Step 3: 구현**

`backend/services/engine/trade_pairs_tags.py`:
```python
"""거래내역(pair) 리스트에 trade_entry_tags 태그를 병합한다(선정/매수 사유 요약 포함).

UI(Trade History)가 한 행에서 "왜 골랐고·왜 샀고·어떻게 끝났나"를 보여주기 위해
trade_pairs.get_trade_pairs() 결과 각 pair에 매수 order_id 기준으로 태그를 붙인다.
"""

from __future__ import annotations

from typing import Any


def _buy_order_ids(pair: dict[str, Any]) -> list[str]:
    """pair.orders[] 중 매수 주문의 id 후보(id 또는 order_id)를 모은다."""
    ids: list[str] = []
    for o in pair.get("orders") or []:
        if str(o.get("side") or "").lower() != "buy":
            continue
        oid = o.get("id") or o.get("order_id")
        if oid:
            ids.append(str(oid))
    return ids


def _selection_summary(tag: dict[str, Any]) -> str:
    """선정사유를 한 줄 요약: sources 조인 + (있으면) llm_note."""
    sr = tag.get("selection_reason") or {}
    sources = sr.get("sources") or []
    note = str(sr.get("llm_note") or "").strip()
    head = " · ".join(str(s) for s in sources)
    if head and note:
        return head + " · " + note
    return head or note


def enrich_pairs_with_tags(pairs: list[dict[str, Any]], tags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """각 pair에 entry_tag + selection_summary + buy_reason_summary 를 더해 반환한다.

    매칭 우선순위: (1) 매수 order_id == tag.order_id, (2) symbol+trade_date 폴백.
    원본 pair dict를 변형하지 않고 얕은 복사본을 반환한다.

    Args:
        pairs: trade_pairs.get_trade_pairs() 결과.
        tags: trade_tagging.load_tags(trade_date) 결과(여러 날 합쳐도 됨).
    """
    by_order: dict[str, dict[str, Any]] = {}
    by_sym_date: dict[tuple[str, str], dict[str, Any]] = {}
    for t in tags:
        oid = str(t.get("order_id") or "")
        if oid:
            by_order.setdefault(oid, t)
        key = (str(t.get("symbol") or ""), str(t.get("trade_date") or ""))
        by_sym_date.setdefault(key, t)

    out: list[dict[str, Any]] = []
    for pair in pairs:
        enriched = dict(pair)
        tag = None
        for oid in _buy_order_ids(pair):
            if oid in by_order:
                tag = by_order[oid]
                break
        if tag is None:
            key = (str(pair.get("symbol") or ""), str(pair.get("trade_date") or ""))
            tag = by_sym_date.get(key)

        enriched["entry_tag"] = tag
        if tag:
            enriched["selection_summary"] = _selection_summary(tag)
            enriched["buy_reason_summary"] = " / ".join(str(g) for g in (tag.get("fired_groups") or []))
        else:
            enriched["selection_summary"] = ""
            enriched["buy_reason_summary"] = ""
        out.append(enriched)
    return out
```

- [ ] **Step 4: 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_trade_pairs_tags.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/trade_pairs_tags.py tests/unit/test_trade_pairs_tags.py
git commit -m "feat: enrich_pairs_with_tags — 거래내역에 trade_entry_tags 선정/매수사유 병합 (탐색엔진 Phase 2)"
```

---

## Task 2: `trades/pairs` 응답에 태그 병합 적용

기존 `get_trade_pairs` 라우트가 pair마다 태그(선정/매수/조건상태/맥락/결과)를 포함해 반환하게 한다. `end_date`까지 날짜 범위의 태그를 모아 병합한다.

**Files:**
- Modify: `backend/api/routes/trades.py:47-58`
- Test: `tests/unit/test_trade_pairs_tags.py` (라우트 헬퍼 호출 검증은 Task 1으로 충분 — 여기선 import sanity만)

- [ ] **Step 1: 현재 라우트 확인 (변경 전)**

`backend/api/routes/trades.py:47-58` 현재:
```python
@router.get("/pairs")
async def get_trade_pairs(
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
):
    """날짜 범위 내 (날짜 × 종목) 거래 결과 페어 조회.

    매수/매도 주문을 날짜+종목 기준으로 묶어 손익을 계산해 반환한다.
    """
    from ...services.engine.trade_pairs import get_trade_pairs as _get
    pairs = _get(start, end)
    return {"ok": True, "payload": {"pairs": pairs, "count": len(pairs)}}
```

- [ ] **Step 2: 라우트 수정 — 태그 병합 추가**

`backend/api/routes/trades.py`의 위 함수 본문을 아래로 교체:
```python
@router.get("/pairs")
async def get_trade_pairs(
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
):
    """날짜 범위 내 (날짜 × 종목) 거래 결과 페어 조회 (선정/매수 사유 태그 포함).

    매수/매도 주문을 날짜+종목 기준으로 묶어 손익을 계산하고,
    trade_entry_tags(선정사유·발화그룹·조건상태·맥락·결과)를 매수 order_id 기준 병합한다.
    """
    from ...services.engine.trade_pairs import get_trade_pairs as _get
    from ...services.engine.trade_tagging import load_tags
    from ...services.engine.trade_pairs_tags import enrich_pairs_with_tags

    pairs = _get(start, end)
    # pair에 등장한 거래일 전부의 태그를 모아 병합 (범위가 좁아 비용 작음)
    trade_dates = sorted({str(p.get("trade_date") or "") for p in pairs if p.get("trade_date")})
    tags: list = []
    for d in trade_dates:
        tags.extend(load_tags(d))
    enriched = enrich_pairs_with_tags(pairs, tags)
    return {"ok": True, "payload": {"pairs": enriched, "count": len(enriched)}}
```

- [ ] **Step 3: import/회귀 sanity**

Run: `PYTHONPATH=. .venv/bin/python -c "import backend.main; print('import ok')"`
Expected: `import ok`

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_trade_pairs_tags.py -q`
Expected: PASS (변경 없음, 회귀 확인).

- [ ] **Step 4: 라우트 수동 검증 (서버 기동 시)**

서버 확인: `curl -s http://127.0.0.1:8000/health`
호출(태그 없는 날짜라도 키 존재 확인):
```bash
curl -s "http://127.0.0.1:8000/api/v1/trades/pairs?start=2099-05-01&end=2099-05-01" | python3 -m json.tool
```
Expected: `payload.pairs` 배열(빈 배열 가능). 데이터 있는 날짜면 각 pair에 `selection_summary`·`buy_reason_summary`·`entry_tag` 키 존재.

- [ ] **Step 5: 커밋**

```bash
git add backend/api/routes/trades.py
git commit -m "feat: trades/pairs 응답에 trade_entry_tags 선정/매수사유 병합 (탐색엔진 Phase 2)"
```

---

## Task 3: Trade History UI — 선정·매수·매도 사유 컬럼 + 태그 상세

statistics 화면(거래내역) 행에 **선정사유**·**매수사유(발화그룹)** 컬럼을 추가하고, accordion 상세에 태그 전체(선정 sources/scores/llm_note + condition_states + market_context + outcome)를 표시한다. **매도사유**는 기존 `exit_reason` 컬럼이 이미 담당 — 그대로 유지.

**Files:**
- Modify: `backend/static/console.html` (statistics 테이블 헤더 — 컬럼 2개 추가)
- Modify: `backend/static/js/screens/console-statistics.js`

- [ ] **Step 1: HTML 헤더 컬럼 추가**

`backend/static/console.html`에서 statistics 거래결과 테이블의 `<thead>`를 찾는다(현재 컬럼: 날짜/종목/매수가/수량/매도가/수량/손익/손익%/청산사유/상태 = colspan 10). `청산사유` 헤더 `<th>` **앞에** 두 헤더를 추가:
```html
                  <th style="text-align:left;">선정사유</th>
                  <th style="text-align:left;">매수사유</th>
```
헤더 `<th>`를 못 찾으면, statistics 테이블의 첫 `<tr>` 헤더 행(날짜로 시작)에서 위치를 잡는다. (헤더가 동적이 아니라면 그대로 추가; 동적이면 Step 3에서 colspan만 12로 맞춤.)

- [ ] **Step 2: colspan 일괄 갱신 (10 → 12)**

`console-statistics.js`에서 빈/에러/로딩 상태의 `colspan="10"`을 모두 `colspan="12"`로 바꾼다(4곳: 로딩중/조회실패/해당 기간 없음/렌더 빈배열). detail accordion 행의 `colspan="10"`(line 153 부근 `'<td colspan="10" ...'`)도 `12`로 바꾼다.

Run: `grep -n 'colspan="10"' backend/static/js/screens/console-statistics.js`
→ 나온 모든 라인을 `12`로 치환.

- [ ] **Step 3: 메인 행에 사유 셀 추가**

`console-statistics.js`의 `renderTradePairs()` 내부 `mainRow` 조립부에서 `exit_reason` 셀 **앞에** 두 셀을 삽입. 현재(line 148 부근):
```javascript
        + '<td style="font-size:11px; color:var(--muted);">' + escapeHtml(p.exit_reason || "-") + '</td>'
```
이 줄 **앞에** 추가:
```javascript
        + '<td style="font-size:11px; color:var(--muted); max-width:160px;">' + escapeHtml(p.selection_summary || "-") + '</td>'
        + '<td style="font-size:11px; color:var(--accent);">' + escapeHtml(p.buy_reason_summary || "-") + '</td>'
```

- [ ] **Step 4: accordion 상세에 태그 블록 추가**

`console-statistics.js`의 `renderTradePairs()`에서 `detailRow` 조립부(line 152 부근):
```javascript
      var detailRow = '<tr class="pair-detail-row" id="detail-' + escapeHtml(rowKey) + '" style="display:' + (isExpanded ? "table-row" : "none") + ';">'
        + '<td colspan="12" style="padding:0; background:var(--panel-2);">'
        + renderOrderDetail(p.orders)
        + '</td></tr>';
```
`renderOrderDetail(p.orders)` 뒤에 `+ renderEntryTagDetail(p.entry_tag)`를 붙인다:
```javascript
      var detailRow = '<tr class="pair-detail-row" id="detail-' + escapeHtml(rowKey) + '" style="display:' + (isExpanded ? "table-row" : "none") + ';">'
        + '<td colspan="12" style="padding:0; background:var(--panel-2);">'
        + renderEntryTagDetail(p.entry_tag)
        + renderOrderDetail(p.orders)
        + '</td></tr>';
```

그리고 `renderOrderDetail` 함수 **바로 위**에 신규 함수 추가:
```javascript
  /* ── 태깅 상세 (선정·조건상태·맥락·결과) ── */
  function renderEntryTagDetail(tag) {
    if (!tag) {
      return '<div style="padding:8px 16px; color:var(--muted); font-size:12px;">태깅 데이터 없음 (탐색엔진 비활성 시점 거래)</div>';
    }
    var sr = tag.selection_reason || {};
    var sources = (sr.sources || []).map(function(s) { return escapeHtml(String(s)); }).join(", ") || "-";
    var note = escapeHtml(sr.llm_note || "-");
    var fired = (tag.fired_groups || []).map(function(g) { return escapeHtml(String(g)); }).join(", ") || "-";

    function kvBlock(title, obj) {
      var keys = Object.keys(obj || {});
      if (!keys.length) return '';
      var cells = keys.map(function(k) {
        var v = obj[k];
        var vs = (typeof v === "boolean") ? (v ? "✓" : "✗") : String(v);
        return '<span style="display:inline-block; margin:2px 8px 2px 0; font-size:11px;">'
          + '<span style="color:var(--muted);">' + escapeHtml(k) + '</span> '
          + '<strong>' + escapeHtml(vs) + '</strong></span>';
      }).join("");
      return '<div style="margin-top:6px;"><div style="font-size:10px; color:var(--muted); margin-bottom:2px;">' + title + '</div>' + cells + '</div>';
    }

    return '<div style="padding:10px 16px; border-bottom:1px solid var(--line);">'
      + '<div style="font-size:11px; color:var(--muted); font-weight:600; margin-bottom:4px;">탐색엔진 태깅</div>'
      + '<div style="font-size:12px;"><span style="color:var(--muted);">선정사유</span> ' + sources + '</div>'
      + '<div style="font-size:12px;"><span style="color:var(--muted);">LLM 메모</span> ' + note + '</div>'
      + '<div style="font-size:12px;"><span style="color:var(--muted);">매수사유(발화그룹)</span> <strong style="color:var(--accent);">' + fired + '</strong></div>'
      + kvBlock("진입 조건상태", tag.condition_states)
      + kvBlock("시장맥락", tag.market_context)
      + kvBlock("결과", tag.outcome)
      + '</div>';
  }
```

- [ ] **Step 5: JS 문법 검사 + 수동 검증**

Run: `node --check backend/static/js/screens/console-statistics.js`
Expected: 출력 없음(종료코드 0).

수동: 브라우저 `http://127.0.0.1:8000/` → 로그인 → **거래내역(Statistics)** 화면 → 거래가 있는 기간 선택. 확인:
1. 표에 "선정사유"·"매수사유" 컬럼이 보이고, 태그 있는 거래는 값(예 "거래대금순위#3 · 반도체 강세" / "돌파전략"), 없으면 "-".
2. 행 클릭 → accordion 상단에 "탐색엔진 태깅" 블록(선정사유/LLM 메모/발화그룹/조건상태/시장맥락/결과)이 보인 뒤 기존 "주문 이력" 표가 이어짐.

- [ ] **Step 6: 커밋**

```bash
git add backend/static/console.html backend/static/js/screens/console-statistics.js
git commit -m "feat: 거래내역에 선정/매수사유 컬럼 + 태깅 상세 accordion (탐색엔진 Phase 2)"
```

---

## Task 4: 후보 응답에 선정사유 추가 (백엔드)

`get_candidates`가 각 후보에 `selection_reason`(sources 요약 + llm_note)을 더해, 모니터가 "왜 오늘 후보인지"를 표시할 수 있게 한다. 기존 `buy_readiness`(met conditions)는 spec의 "met conditions/groups" 요구를 이미 충족 — 유지.

**Files:**
- Modify: `backend/api/routes/trading_monitor.py:516-529`

- [ ] **Step 1: 후보 dict에 selection_reason 추가**

`backend/api/routes/trading_monitor.py`의 `get_candidates()` 루프(line 516 `result.append({...})`) — `build_selection_reason`(Phase 1c 제공)을 사용해 선정사유를 만든다. `result.append` 직전에 추가하고, append dict에 키를 넣는다.

루프 상단 import(파일 상단 import 블록에 한 줄 추가):
```python
from ...services.engine.trade_tagging import build_selection_reason
```
(이미 다른 곳에서 함수 단위 lazy import를 쓰면 그 관례를 따라도 됨 — 그 경우 루프 안에서 `from ...services.engine.trade_tagging import build_selection_reason`로 처리.)

`result.append({...})`의 dict 안, `"buy_readiness": readiness,` 줄 **앞에** 추가:
```python
            "selection_reason": build_selection_reason(c),
```
> `build_selection_reason(c)`는 후보 dict에서 `{sources, scores, llm_note}`를 안전 추출(빠진 필드 누락). `c`에 `change_rate`/`suitability_score`/`score`가 이미 있으므로 그대로 동작.

- [ ] **Step 2: import/회귀 sanity**

Run: `PYTHONPATH=. .venv/bin/python -c "import backend.main; print('import ok')"`
Expected: `import ok`

- [ ] **Step 3: 수동 검증 (서버 기동 시)**

```bash
curl -s "http://127.0.0.1:8000/api/v1/trading-monitor/candidates" | python3 -m json.tool
```
Expected: `payload.candidates[*]`에 `selection_reason:{sources,scores,llm_note}` 키 존재(후보 없으면 빈 배열).

- [ ] **Step 4: 커밋**

```bash
git add backend/api/routes/trading_monitor.py
git commit -m "feat: 매수 후보 응답에 selection_reason(선정사유) 추가 (탐색엔진 Phase 2)"
```

---

## Task 5: Trading Monitor UI — 후보 행에 선정사유 표시

후보 카드 헤더에 선정사유 한 줄을 추가한다(매수 발생 시 매수사유는 Task 3의 거래내역/태깅에서 이미 노출되므로, 모니터는 "선정사유 + 실시간 충족 조건"에 집중).

**Files:**
- Modify: `backend/static/js/screens/console-trading-monitor.js:209-236` (`renderCandidateRow`)

- [ ] **Step 1: 선정사유 요약 헬퍼 + 행 삽입**

`console-trading-monitor.js`의 `renderCandidateRow(c)` 함수 **위**에 헬퍼 추가:
```javascript
  /* 후보 선정사유 한 줄 요약 (sources · llm_note) */
  function _candidateSelectionText(c) {
    var sr = c.selection_reason || {};
    var sources = (sr.sources || []).map(function(s) { return String(s); }).join(" · ");
    var note = (sr.llm_note || "").trim();
    if (sources && note) return sources + " · " + note;
    return sources || note || "";
  }
```

`renderCandidateRow`의 후보 이름/프로파일 블록(line 212-215, `min-width:80px` div) 바로 **뒤**, `<div style="flex:1;">` **앞**에 선정사유 줄을 끼우면 레이아웃이 좁다 → 대신 **카드 헤더 아래(detail 영역 위)** 에 한 줄로 추가한다. detail div 시작부(line 237 `'<div id="' + detailId + '" ...'`) **앞**에 삽입:
```javascript
      + (function() {
          var selText = _candidateSelectionText(c);
          return selText
            ? '<div style="padding:4px 10px; font-size:11px; color:var(--muted); background:var(--panel);">'
              + '<span style="color:var(--accent);">선정사유</span> ' + escapeHtml(selText) + '</div>'
            : '';
        })()
```
> 즉 `renderCandidateRow` 반환 문자열에서 헤더 div(`'</div>'` 닫힘) 다음, `'<div id="' + detailId ...` 직전에 위 표현식을 `+`로 연결한다.

- [ ] **Step 2: JS 문법 검사**

Run: `node --check backend/static/js/screens/console-trading-monitor.js`
Expected: 출력 없음(종료코드 0).

- [ ] **Step 3: 수동 검증 (서버 기동 시)**

브라우저 → **Trading Monitor** 화면(`#screen-trading`). 후보가 있을 때 각 후보 카드 헤더 아래에 "선정사유 …" 줄이 보이고(데이터 없으면 줄 자체 미표시), 클릭 시 기존 조건 충족표(met conditions)가 그대로 펼쳐진다.
(후보가 없으면 빈 상태 — 회귀 없음만 확인.)

- [ ] **Step 4: 커밋**

```bash
git add backend/static/js/screens/console-trading-monitor.js
git commit -m "feat: 매수 후보 카드에 선정사유 줄 표시 (탐색엔진 Phase 2)"
```

---

## Task 6: 조건/그룹 CRUD 라우터 (신규 API) — conditions

원자 조건 GET/PUT 라우트와 그 테스트. 이 Task에서 라우터 파일·등록을 만들고 conditions 2개 엔드포인트를 구현한다(groups는 Task 7).

**Files:**
- Create: `backend/api/routes/buy_conditions.py`
- Modify: `backend/main.py` (import + include_router)
- Test: `tests/unit/test_buy_conditions_api.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/test_buy_conditions_api.py`:
```python
from fastapi.testclient import TestClient

import backend.main as main_mod
import backend.services.engine.buy_condition_framework as bcf

client = TestClient(main_mod.app)


def _seeded():
    bcf._ensure_tables()
    bcf._clear_all_for_test()
    bcf.seed_defaults()


def test_get_conditions_includes_disabled():
    _seeded()
    r = client.get("/api/v1/buy-conditions/conditions")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    conds = body["payload"]["conditions"]
    ctypes = {c["ctype"] for c in conds}
    assert "day_high_breakout" in ctypes
    assert "chegyeol_gangdo_min" in ctypes
    # 모든 조건에 필수 키 존재
    for c in conds:
        assert set(["id", "name", "ctype", "params", "enabled"]).issubset(c.keys())


def test_put_condition_updates_params_and_enabled():
    _seeded()
    r = client.put(
        "/api/v1/buy-conditions/conditions/cond_gangdo",
        json={"params": {"min": 0.70}, "enabled": False},
    )
    assert r.status_code == 200
    cond = r.json()["payload"]["condition"]
    assert cond["params"]["min"] == 0.70
    assert cond["enabled"] is False
    # 영속 확인 (enabled_only=False 로드)
    after = bcf.load_conditions(enabled_only=False)["cond_gangdo"]
    assert after["params"]["min"] == 0.70
    assert after["enabled"] is False


def test_put_condition_missing_returns_404():
    _seeded()
    r = client.put("/api/v1/buy-conditions/conditions/no_such", json={"enabled": True})
    assert r.status_code == 404
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_buy_conditions_api.py -q`
Expected: FAIL — 404 (라우트 없음) 또는 `Connection`/import 에러.

- [ ] **Step 3: 라우터 구현 (conditions)**

`backend/api/routes/buy_conditions.py`:
```python
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
```

- [ ] **Step 4: main.py 등록**

`backend/main.py`의 import 블록에 추가(예: `from .api.routes.trades import router as trades_router` 근처):
```python
from .api.routes.buy_conditions import router as buy_conditions_router
```
include 블록에 추가(`app.include_router(trades_router)` 근처):
```python
app.include_router(buy_conditions_router)
```

- [ ] **Step 5: 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_buy_conditions_api.py -q`
Expected: PASS (3 passed)

Run: `PYTHONPATH=. .venv/bin/python -c "import backend.main; print('import ok')"` → `import ok`.

- [ ] **Step 6: 커밋**

```bash
git add backend/api/routes/buy_conditions.py backend/main.py tests/unit/test_buy_conditions_api.py
git commit -m "feat: 매수조건 CRUD API — GET/PUT conditions + 라우터 등록 (탐색엔진 Phase 2)"
```

---

## Task 7: 조건/그룹 CRUD 라우터 — groups + assign-targets

그룹 GET/POST/PUT 과 할당 대상 메타(레짐/프로파일)를 추가한다.

**Files:**
- Modify: `backend/api/routes/buy_conditions.py` (append)
- Test: `tests/unit/test_buy_conditions_api.py` (append)

- [ ] **Step 1: 실패 테스트 추가**

`tests/unit/test_buy_conditions_api.py` 끝에 추가:
```python
def test_get_groups_includes_defaults():
    _seeded()
    r = client.get("/api/v1/buy-conditions/groups")
    assert r.status_code == 200
    groups = r.json()["payload"]["groups"]
    names = {g["name"] for g in groups}
    assert {"돌파전략", "눌림전략", "모멘텀전략"}.issubset(names)
    for g in groups:
        assert set(["id", "name", "condition_ids", "enabled", "weight", "assigned_to"]).issubset(g.keys())


def test_post_group_creates_and_persists():
    _seeded()
    r = client.post(
        "/api/v1/buy-conditions/groups",
        json={"name": "테스트전략", "condition_ids": ["cond_breakout", "cond_gangdo"],
              "weight": 1.5, "assigned_to": "regime:risk_on"},
    )
    assert r.status_code == 200
    g = r.json()["payload"]["group"]
    assert g["name"] == "테스트전략"
    assert g["condition_ids"] == ["cond_breakout", "cond_gangdo"]
    assert g["weight"] == 1.5
    assert g["assigned_to"] == "regime:risk_on"
    # 영속 확인
    found = [x for x in bcf.load_groups(enabled_only=False) if x["id"] == g["id"]]
    assert found and found[0]["name"] == "테스트전략"


def test_put_group_updates_assignment_and_enabled():
    _seeded()
    r = client.put(
        "/api/v1/buy-conditions/groups/grp_pullback",
        json={"enabled": False, "weight": 0.5, "assigned_to": "profile:HIGH_VOL",
              "condition_ids": ["cond_pullback"]},
    )
    assert r.status_code == 200
    g = r.json()["payload"]["group"]
    assert g["enabled"] is False
    assert g["weight"] == 0.5
    assert g["assigned_to"] == "profile:HIGH_VOL"
    assert g["condition_ids"] == ["cond_pullback"]


def test_put_group_missing_returns_404():
    _seeded()
    r = client.put("/api/v1/buy-conditions/groups/no_such", json={"enabled": True})
    assert r.status_code == 404


def test_assign_targets_lists_regimes_and_profiles():
    r = client.get("/api/v1/buy-conditions/assign-targets")
    assert r.status_code == 200
    p = r.json()["payload"]
    assert "regimes" in p and "profiles" in p
    assert "HIGH_VOL" in p["profiles"]
    assert len(p["regimes"]) >= 1
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_buy_conditions_api.py -q`
Expected: FAIL — groups/assign-targets 라우트 404.

- [ ] **Step 3: 구현 추가**

`backend/api/routes/buy_conditions.py` 끝에 추가:
```python
class GroupCreate(BaseModel):
    name: str
    condition_ids: list[str] = []
    enabled: bool = True
    weight: float = 1.0
    assigned_to: str = ""


class GroupUpdate(BaseModel):
    name: str | None = None
    condition_ids: list[str] | None = None
    enabled: bool | None = None
    weight: float | None = None
    assigned_to: str | None = None


# 할당 가능한 레짐/RiskProfile (드롭다운 소스)
_ASSIGN_REGIMES = ["risk_on", "neutral", "defensive", "volatile"]
_ASSIGN_PROFILES = ["LOW_VOL", "MID_VOL", "HIGH_VOL", "THEME_SPIKE"]


@router.get("/groups")
def get_groups() -> dict[str, Any]:
    """조건 그룹 전체(비활성 포함)를 반환한다."""
    bcf.seed_defaults()
    return {"ok": True, "payload": {"groups": bcf.load_groups(enabled_only=False)}}


@router.post("/groups")
def post_group(body: GroupCreate) -> dict[str, Any]:
    """AND 그룹을 신규 생성한다."""
    bcf._ensure_tables()
    gid = "grp_" + uuid.uuid4().hex[:12]
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO condition_groups (id, name, condition_ids_json, enabled, weight, assigned_to, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (gid, body.name, json.dumps(body.condition_ids, ensure_ascii=False),
             1 if body.enabled else 0, float(body.weight), body.assigned_to, _now()),
        )
    created = next(g for g in bcf.load_groups(enabled_only=False) if g["id"] == gid)
    return {"ok": True, "payload": {"group": created}}


@router.put("/groups/{gid}")
def put_group(gid: str, body: GroupUpdate) -> dict[str, Any]:
    """그룹의 name/condition_ids/enabled/weight/assigned_to 를 편집한다. 없으면 404."""
    bcf._ensure_tables()
    existing = [g for g in bcf.load_groups(enabled_only=False) if g["id"] == gid]
    if not existing:
        raise HTTPException(status_code=404, detail=f"group not found: {gid}")

    sets: list[str] = []
    args: list[Any] = []
    if body.name is not None:
        sets.append("name = ?"); args.append(body.name)
    if body.condition_ids is not None:
        sets.append("condition_ids_json = ?"); args.append(json.dumps(body.condition_ids, ensure_ascii=False))
    if body.enabled is not None:
        sets.append("enabled = ?"); args.append(1 if body.enabled else 0)
    if body.weight is not None:
        sets.append("weight = ?"); args.append(float(body.weight))
    if body.assigned_to is not None:
        sets.append("assigned_to = ?"); args.append(body.assigned_to)
    if sets:
        args.append(gid)
        with get_connection() as conn:
            conn.execute(f"UPDATE condition_groups SET {', '.join(sets)} WHERE id = ?", args)

    updated = next(g for g in bcf.load_groups(enabled_only=False) if g["id"] == gid)
    return {"ok": True, "payload": {"group": updated}}


@router.get("/assign-targets")
def get_assign_targets() -> dict[str, Any]:
    """그룹 할당 가능한 레짐/RiskProfile 목록을 반환한다."""
    return {"ok": True, "payload": {"regimes": _ASSIGN_REGIMES, "profiles": _ASSIGN_PROFILES}}
```

- [ ] **Step 4: 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_buy_conditions_api.py -q`
Expected: PASS (8 passed)

- [ ] **Step 5: 커밋**

```bash
git add backend/api/routes/buy_conditions.py tests/unit/test_buy_conditions_api.py
git commit -m "feat: 매수조건 그룹 CRUD + assign-targets API (탐색엔진 Phase 2)"
```

---

## Task 8: Settings UI — 원자조건·그룹빌더·할당 편집기

신규 카드 3블록(원자조건 / 그룹빌더 / 할당)을 settings 화면에 추가하고, 신규 라우터를 호출하는 로더·핸들러를 `console-settings.js`에 추가한다. 기존 `loadBuyConditions`/가드레일 카드는 그대로 둔다.

**Files:**
- Modify: `backend/static/console.html` (settings 신규 카드)
- Modify: `backend/static/js/screens/console-settings.js` (신규 함수)

- [ ] **Step 1: HTML 신규 카드 추가**

`backend/static/console.html`에서 settings 화면의 "매수 조건 가드레일" 카드(`<tbody id="buy-condition-tbody">`가 든 `<div class="card">`)의 닫는 `</div>` **뒤**, `<div class="section-gap"></div>` 다음에 아래 블록을 삽입:
```html
          <!-- ①-2 탐색엔진 원자 조건 / 그룹 / 할당 -->
          <div class="card">
            <div class="settings-card-hd">
              <div class="settings-card-meta">
                <span class="settings-tag">탐색엔진</span>
                <div class="settings-card-title-txt">원자 매수 조건</div>
                <div class="settings-card-desc">조건별 임계치(params)와 활성 여부를 편집합니다. 변경 즉시 저장됩니다.</div>
              </div>
              <button type="button" class="btn" data-action="loadConditionEditor">새로고침</button>
            </div>
            <table class="settings-table">
              <thead><tr><th>조건명</th><th>타입</th><th>파라미터(JSON)</th><th>활성</th></tr></thead>
              <tbody id="atomic-condition-tbody">
                <tr><td colspan="4" class="muted" style="text-align:center;">로딩중...</td></tr>
              </tbody>
            </table>
          </div>

          <div class="section-gap"></div>

          <div class="card">
            <div class="settings-card-hd">
              <div class="settings-card-meta">
                <span class="settings-tag">탐색엔진</span>
                <div class="settings-card-title-txt">조건 그룹 (AND 전략) · 할당</div>
                <div class="settings-card-desc">조건들을 AND로 묶은 전략. 활성/가중치/레짐·프로파일 할당을 편집합니다.</div>
              </div>
            </div>
            <div id="condition-group-list" style="display:flex; flex-direction:column; gap:10px;">
              <div class="muted">로딩중...</div>
            </div>
            <div style="margin-top:12px; border-top:1px solid var(--line); padding-top:12px;">
              <div style="font-size:12px; color:var(--muted); margin-bottom:6px;">새 그룹 만들기 (AND)</div>
              <input id="new-group-name" type="text" placeholder="그룹명 (예: 돌파전략2)"
                     style="padding:6px; border-radius:4px; background:var(--panel-2); color:var(--text); border:1px solid var(--border); margin-right:6px;">
              <div id="new-group-conditions" style="margin:8px 0; display:flex; flex-wrap:wrap; gap:8px;"></div>
              <button type="button" class="btn primary" data-action="createConditionGroup">그룹 생성</button>
            </div>
          </div>
```

- [ ] **Step 2: console-settings.js — 로더/핸들러 추가**

`console-settings.js`의 `saveGuardrail` 함수 **뒤**(line 406 부근)에 아래 블록 추가:
```javascript
  /* ── 탐색엔진 조건/그룹 편집기 ── */
  var _bcConditions = [];   // [{id,name,ctype,params,enabled}]
  var _bcGroups = [];       // [{id,name,condition_ids,enabled,weight,assigned_to}]
  var _bcAssignTargets = { regimes: [], profiles: [] };

  async function loadConditionEditor() {
    try {
      var [cData, gData, aData] = await Promise.all([
        fetchJson('/api/v1/buy-conditions/conditions'),
        fetchJson('/api/v1/buy-conditions/groups'),
        fetchJson('/api/v1/buy-conditions/assign-targets'),
      ]);
      _bcConditions = (cData.payload && cData.payload.conditions) || [];
      _bcGroups = (gData.payload && gData.payload.groups) || [];
      _bcAssignTargets = (aData.payload) || { regimes: [], profiles: [] };
      renderAtomicConditions();
      renderConditionGroups();
      renderNewGroupCheckboxes();
    } catch (e) {
      var tb = document.getElementById('atomic-condition-tbody');
      if (tb) tb.innerHTML = '<tr><td colspan="4" class="muted">로드 실패: ' + escapeHtml(e.message) + '</td></tr>';
    }
  }

  function renderAtomicConditions() {
    var tb = document.getElementById('atomic-condition-tbody');
    if (!tb) return;
    if (!_bcConditions.length) { tb.innerHTML = '<tr><td colspan="4" class="muted">조건 없음</td></tr>'; return; }
    tb.innerHTML = _bcConditions.map(function(c) {
      var pjson = escapeHtml(JSON.stringify(c.params || {}));
      return '<tr style="border-bottom:1px solid var(--border);">'
        + '<td style="padding:8px 0;">' + escapeHtml(c.name) + '</td>'
        + '<td style="padding:8px 4px; font-size:11px; color:var(--muted);">' + escapeHtml(c.ctype) + '</td>'
        + '<td style="padding:8px 4px;">'
        + '<input type="text" value="' + pjson + '" data-action="saveConditionParams" data-cid="' + escapeHtml(c.id) + '" '
        + 'style="width:200px; padding:4px; border-radius:4px; background:var(--panel-2); color:var(--text); border:1px solid var(--border); font-size:11px;">'
        + '</td>'
        + '<td style="padding:8px 4px;">'
        + '<input type="checkbox" ' + (c.enabled ? 'checked' : '') + ' data-action="toggleCondition" data-cid="' + escapeHtml(c.id) + '">'
        + '</td>'
        + '</tr>';
    }).join('');
  }

  function _assignSelectHtml(group) {
    var opts = ['<option value="">미할당</option>'];
    _bcAssignTargets.regimes.forEach(function(r) {
      var v = 'regime:' + r;
      opts.push('<option value="' + escapeHtml(v) + '"' + (group.assigned_to === v ? ' selected' : '') + '>레짐 · ' + escapeHtml(r) + '</option>');
    });
    _bcAssignTargets.profiles.forEach(function(p) {
      var v = 'profile:' + p;
      opts.push('<option value="' + escapeHtml(v) + '"' + (group.assigned_to === v ? ' selected' : '') + '>프로파일 · ' + escapeHtml(p) + '</option>');
    });
    return '<select data-action="assignGroup" data-gid="' + escapeHtml(group.id) + '" '
      + 'style="padding:4px; border-radius:4px; background:var(--panel-2); color:var(--text); border:1px solid var(--border); font-size:11px;">'
      + opts.join('') + '</select>';
  }

  function renderConditionGroups() {
    var box = document.getElementById('condition-group-list');
    if (!box) return;
    if (!_bcGroups.length) { box.innerHTML = '<div class="muted">그룹 없음</div>'; return; }
    var nameById = {};
    _bcConditions.forEach(function(c) { nameById[c.id] = c.name; });
    box.innerHTML = _bcGroups.map(function(g) {
      var condNames = (g.condition_ids || []).map(function(id) { return escapeHtml(nameById[id] || id); }).join(' AND ');
      return '<div style="border:1px solid var(--line); border-radius:6px; padding:10px;">'
        + '<div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">'
        + '<input type="checkbox" ' + (g.enabled ? 'checked' : '') + ' data-action="toggleGroup" data-gid="' + escapeHtml(g.id) + '">'
        + '<strong style="font-size:13px;">' + escapeHtml(g.name) + '</strong>'
        + '<span style="font-size:10px; color:var(--muted);">가중치</span>'
        + '<input type="number" step="0.1" value="' + (g.weight != null ? g.weight : 1.0) + '" data-action="saveGroupWeight" data-gid="' + escapeHtml(g.id) + '" '
        + 'style="width:60px; padding:3px; border-radius:4px; background:var(--panel-2); color:var(--text); border:1px solid var(--border); font-size:11px;">'
        + _assignSelectHtml(g)
        + '</div>'
        + '<div style="margin-top:6px; font-size:11px; color:var(--muted);">' + (condNames || '(조건 없음)') + '</div>'
        + '</div>';
    }).join('');
  }

  function renderNewGroupCheckboxes() {
    var box = document.getElementById('new-group-conditions');
    if (!box) return;
    box.innerHTML = _bcConditions.map(function(c) {
      return '<label style="font-size:11px; color:var(--muted); display:inline-flex; align-items:center; gap:3px;">'
        + '<input type="checkbox" class="new-group-cond" value="' + escapeHtml(c.id) + '"> ' + escapeHtml(c.name) + '</label>';
    }).join('');
  }

  async function _putCondition(cid, payload) {
    await fetchJson('/api/v1/buy-conditions/conditions/' + encodeURIComponent(cid), {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
  }

  async function saveConditionParams(cid, value) {
    try {
      var parsed = JSON.parse(value);
      await _putCondition(cid, { params: parsed });
    } catch (e) {
      alert('파라미터 저장 실패(JSON 형식 확인): ' + e.message);
    }
  }

  async function toggleCondition(cid, checked) {
    try { await _putCondition(cid, { enabled: !!checked }); }
    catch (e) { alert('조건 토글 실패: ' + e.message); }
  }

  async function _putGroup(gid, payload) {
    await fetchJson('/api/v1/buy-conditions/groups/' + encodeURIComponent(gid), {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
  }

  async function toggleGroup(gid, checked) {
    try { await _putGroup(gid, { enabled: !!checked }); }
    catch (e) { alert('그룹 토글 실패: ' + e.message); }
  }

  async function saveGroupWeight(gid, value) {
    try { await _putGroup(gid, { weight: parseFloat(value) }); }
    catch (e) { alert('가중치 저장 실패: ' + e.message); }
  }

  async function assignGroup(gid, value) {
    try { await _putGroup(gid, { assigned_to: value || '' }); }
    catch (e) { alert('할당 저장 실패: ' + e.message); }
  }

  async function createConditionGroup() {
    var nameEl = document.getElementById('new-group-name');
    var name = nameEl ? nameEl.value.trim() : '';
    if (!name) { alert('그룹명을 입력하세요.'); return; }
    var checked = Array.prototype.slice.call(document.querySelectorAll('.new-group-cond:checked'))
      .map(function(el) { return el.value; });
    if (!checked.length) { alert('조건을 1개 이상 선택하세요(AND).'); return; }
    try {
      await fetchJson('/api/v1/buy-conditions/groups', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name, condition_ids: checked }),
      });
      if (nameEl) nameEl.value = '';
      await loadConditionEditor();
    } catch (e) {
      alert('그룹 생성 실패: ' + e.message);
    }
  }
```

- [ ] **Step 3: `initSettingsUI`에 로더 연결**

`console-settings.js`의 `initSettingsUI()`(line 612) 내부에 `loadBuyConditions();` 다음 줄에 추가:
```javascript
    loadConditionEditor();
```

- [ ] **Step 4: `data-action` 인자 전달 확인**

`console-actions.js`가 checkbox/select/number input의 값을 어떻게 핸들러에 넘기는지 확인:
Run: `grep -n "checked\|\.value\|dataset" backend/static/js/console-actions.js | head -20`
- 만약 `console-actions.js`가 `checked`/`value`를 자동으로 두 번째 인자로 넘기지 않으면(대부분 `data-*`만 전달), 이 Task의 핸들러는 인자를 받도록 짜여 있으므로 디스패처가 `element.checked`/`element.value`를 넘기는 분기를 확인한다. 넘기지 않는 경우, 각 핸들러 호출부를 인라인 `onchange`로 바꾸는 대신 — **간단·확실하게** 각 input에 `data-action`을 유지하되, 핸들러 내부에서 인자가 `undefined`면 DOM에서 직접 읽도록 폴백을 추가한다:
  ```javascript
  // 예: toggleCondition(cid, checked) 폴백
  async function toggleCondition(cid, checked) {
    if (checked === undefined) {
      var el = document.querySelector('[data-action="toggleCondition"][data-cid="' + cid + '"]');
      checked = el ? el.checked : false;
    }
    try { await _putCondition(cid, { enabled: !!checked }); }
    catch (e) { alert('조건 토글 실패: ' + e.message); }
  }
  ```
  같은 폴백 패턴을 `saveConditionParams(value)`·`saveGroupWeight(value)`·`assignGroup(value)`·`saveConditionParams`에도 적용한다(각각 `el.value`로 폴백). **디스패처가 값을 넘기면 폴백은 무해하게 건너뛴다.**

> 실제 디스패처 동작을 grep으로 먼저 확인하고, 값 전달이 되면 폴백 추가는 생략 가능. 불확실하면 폴백을 넣는 쪽이 안전하다.

- [ ] **Step 5: JS 문법 검사 + 수동 검증**

Run: `node --check backend/static/js/screens/console-settings.js`
Expected: 출력 없음(종료코드 0).

수동(서버 기동 시): 브라우저 → **Settings** 화면. 확인:
1. "원자 매수 조건" 표에 9개 조건(당일고가 돌파/체결강도 55%+ 등)과 params JSON 입력칸·활성 체크박스.
2. params를 `{"min": 0.7}`로 바꾸고 포커스 아웃 → 새로고침해도 유지(`GET /conditions`로 재확인).
3. "조건 그룹" 목록에 돌파전략/눌림전략/모멘텀전략/베이스라인, 각 행에 활성 체크·가중치·할당 드롭다운(레짐/프로파일).
4. 할당 드롭다운에서 "프로파일 · HIGH_VOL" 선택 → 새로고침 후 유지.
5. 새 그룹: 이름 입력 + 조건 2개 체크 + "그룹 생성" → 목록에 추가됨.

curl 보조 검증:
```bash
curl -s http://127.0.0.1:8000/api/v1/buy-conditions/conditions | python3 -m json.tool | head -30
curl -s -X PUT http://127.0.0.1:8000/api/v1/buy-conditions/conditions/cond_gangdo \
  -H 'Content-Type: application/json' -d '{"params":{"min":0.6}}' | python3 -m json.tool
curl -s http://127.0.0.1:8000/api/v1/buy-conditions/groups | python3 -m json.tool | head -40
```

- [ ] **Step 6: 커밋**

```bash
git add backend/static/console.html backend/static/js/screens/console-settings.js
git commit -m "feat: Settings 매수조건 편집기 — 원자조건·그룹빌더·레짐/프로파일 할당 (탐색엔진 Phase 2)"
```

---

## Task 9: Review UI — 그룹/조건 통계 read-and-render 스캐폴드

Review 화면에 per-group/per-condition 통계를 보여줄 **자리(placeholder display)** 를 만든다. EV 계산은 Phase 3 — 여기서는 그룹/조건 목록을 표로 그리고 표본/EV 컬럼은 "—"(Phase 3 예정)로 채운다. 데이터 소스는 신규 `GET /groups`·`GET /conditions`(현재는 통계 없음) — Phase 3가 EV 필드를 더하면 같은 표가 채워진다.

**Files:**
- Modify: `backend/static/console.html` (review 화면 신규 카드)
- Modify: `backend/static/js/screens/console-review.js` (`loadGroupStatsScaffold`)

- [ ] **Step 1: HTML 신규 카드 추가**

`backend/static/console.html`에서 review 화면(`#screen-review`)의 거래요약 카드(`<tbody id="review-history-tbody">`가 든 카드) **뒤**에 추가:
```html
          <div class="section-gap"></div>

          <!-- 탐색엔진 — 그룹/조건 EV 스캐폴드 (Phase 3 채움) -->
          <div class="card">
            <div class="settings-card-hd">
              <div class="settings-card-meta">
                <span class="settings-tag">탐색엔진</span>
                <div class="settings-card-title-txt">매수 그룹·조건 성과 (EV)</div>
                <div class="settings-card-desc">그룹/조건별 표본·승률·기대값(EV). EV 집계는 Phase 3에서 채워집니다.</div>
              </div>
              <button type="button" class="btn" data-action="loadGroupStatsScaffold">새로고침</button>
            </div>
            <table class="settings-table">
              <thead><tr><th>구분</th><th>이름</th><th>활성</th><th>가중치</th><th>표본</th><th>승률</th><th>EV</th></tr></thead>
              <tbody id="group-stats-tbody">
                <tr><td colspan="7" class="muted" style="text-align:center;">새로고침을 눌러 로드</td></tr>
              </tbody>
            </table>
          </div>
```

- [ ] **Step 2: console-review.js — 스캐폴드 로더 추가**

`console-review.js`의 `loadReviewData` 함수 **뒤**(line 63 부근)에 추가:
```javascript
  /* 탐색엔진 그룹/조건 성과 스캐폴드 — EV는 Phase 3가 채움(현재 표본/승률/EV = "—") */
  async function loadGroupStatsScaffold() {
    var tb = document.getElementById('group-stats-tbody');
    if (!tb) return;
    tb.innerHTML = '<tr><td colspan="7" class="muted" style="text-align:center;">로딩중...</td></tr>';
    try {
      var [gData, cData] = await Promise.all([
        fetchJson('/api/v1/buy-conditions/groups'),
        fetchJson('/api/v1/buy-conditions/conditions'),
      ]);
      var groups = (gData.payload && gData.payload.groups) || [];
      var conds = (cData.payload && cData.payload.conditions) || [];
      var rows = [];

      groups.forEach(function(g) {
        rows.push(_statsRow('그룹', g.name, g.enabled, g.weight,
          g.stats || null));   // g.stats 는 Phase 3가 추가할 필드
      });
      conds.forEach(function(c) {
        rows.push(_statsRow('조건', c.name, c.enabled, null, c.stats || null));
      });

      if (!rows.length) {
        tb.innerHTML = '<tr><td colspan="7" class="muted" style="text-align:center;">조건/그룹 없음</td></tr>';
        return;
      }
      tb.innerHTML = rows.join('');
    } catch (e) {
      tb.innerHTML = '<tr><td colspan="7" class="muted">로드 실패: ' + escapeHtml(e.message) + '</td></tr>';
    }
  }

  function _statsRow(kind, name, enabled, weight, stats) {
    // stats 가 있으면(Phase 3) 표본/승률/EV 표시, 없으면 "—" placeholder.
    var sample = (stats && stats.sample != null) ? String(stats.sample) : '—';
    var winrate = (stats && stats.winrate != null) ? (stats.winrate * 100).toFixed(0) + '%' : '—';
    var ev = (stats && stats.ev != null) ? Number(stats.ev).toLocaleString() : '—';
    var evCls = (stats && stats.ev != null) ? (stats.ev >= 0 ? 'good' : 'bad') : '';
    return '<tr style="border-bottom:1px solid var(--border);">'
      + '<td style="padding:6px 0; font-size:11px; color:var(--muted);">' + escapeHtml(kind) + '</td>'
      + '<td style="padding:6px 4px;">' + escapeHtml(name) + '</td>'
      + '<td style="padding:6px 4px;">' + (enabled ? '✓' : '✗') + '</td>'
      + '<td style="padding:6px 4px;">' + (weight != null ? weight : '-') + '</td>'
      + '<td style="padding:6px 4px;">' + sample + '</td>'
      + '<td style="padding:6px 4px;">' + winrate + '</td>'
      + '<td style="padding:6px 4px;" class="' + evCls + '">' + ev + '</td>'
      + '</tr>';
  }
```

- [ ] **Step 3: 화면 진입 시 자동 로드 (선택)**

`console-navigation.js`에서 review 화면 진입 분기를 찾는다:
Run: `grep -n '"review"\|loadReviewData\|loadReviewAuditScreen' backend/static/js/console-navigation.js`
- review 진입 분기가 있으면 그 안에 `if (typeof loadGroupStatsScaffold === 'function') loadGroupStatsScaffold();` 한 줄 추가.
- 분기를 못 찾으면(버튼 수동 로드로 충분) Step 1의 "새로고침" 버튼이 `data-action="loadGroupStatsScaffold"`로 동작하므로 추가 변경 불필요 — 그대로 둔다.

- [ ] **Step 4: JS 문법 검사 + 수동 검증**

Run: `node --check backend/static/js/screens/console-review.js`
Expected: 출력 없음(종료코드 0).

수동(서버 기동 시): 브라우저 → **Review** 화면 → "매수 그룹·조건 성과 (EV)" 카드의 "새로고침" 클릭. 그룹(돌파/눌림/모멘텀/베이스라인) + 9개 조건이 표로 뜨고, 표본/승률/EV 컬럼은 모두 "—"(Phase 3 예정). 활성 체크/가중치는 실제 값.

- [ ] **Step 5: 커밋**

```bash
git add backend/static/console.html backend/static/js/screens/console-review.js
git commit -m "feat: Review 그룹/조건 성과 스캐폴드 (EV는 Phase 3 채움) (탐색엔진 Phase 2)"
```

---

## Task 10: 전체 회귀 + 캐시버스터 + 최종 확인

신규 JS 3종 모두 문법 통과, 전체 단위/라우트 테스트 통과, import 정상, 정적 스크립트 캐시버스터 갱신.

**Files:**
- Modify: `backend/static/console.html` (script `?v=` 버전 bump)

- [ ] **Step 1: 캐시버스터 갱신**

`backend/static/console.html`에서 이번에 수정한 JS의 `?v=` 쿼리를 올린다(브라우저 캐시 방지). 현재 `console-settings.js?v=7`·`console-review.js?v=7` → `?v=8`로. `console-statistics.js`·`console-trading-monitor.js`는 `?v=` 없음 → `?v=2` 부여:
```html
  <script src="/static/js/screens/console-trading-monitor.js?v=2"></script>
  ...
  <script src="/static/js/screens/console-settings.js?v=8"></script>
  ...
  <script src="/static/js/screens/console-review.js?v=8"></script>
  <script src="/static/js/screens/console-statistics.js?v=2"></script>
```

- [ ] **Step 2: JS 문법 일괄 검사**

```bash
node --check backend/static/js/screens/console-statistics.js && \
node --check backend/static/js/screens/console-trading-monitor.js && \
node --check backend/static/js/screens/console-settings.js && \
node --check backend/static/js/screens/console-review.js && echo "JS OK"
```
Expected: `JS OK`

- [ ] **Step 3: Python 회귀**

```bash
PYTHONPATH=. .venv/bin/python -c "import backend.main; print('import ok')"
PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_trade_pairs_tags.py tests/unit/test_buy_conditions_api.py -q
```
Expected: `import ok` + 모든 테스트 PASS (3 + 8 = 11 passed).

- [ ] **Step 4: 커밋**

```bash
git add backend/static/console.html
git commit -m "chore: 탐색엔진 Phase 2 정적 스크립트 캐시버스터 갱신 + 회귀 확인"
```

---

## 완료 기준 (Phase 2)
- [ ] `trades/pairs` 응답에 pair별 `entry_tag`·`selection_summary`·`buy_reason_summary` 포함 — 거래내역 표/accordion에 선정·매수·매도(exit) 사유 + 태그 상세 노출.
- [ ] `trading-monitor/candidates` 응답에 `selection_reason` 포함 — 후보 카드에 선정사유 줄 + 기존 met conditions 유지.
- [ ] 신규 라우터 6 엔드포인트(GET/PUT conditions, GET/POST/PUT groups, GET assign-targets) — TestClient 8테스트 PASS.
- [ ] Settings에 원자조건 편집·그룹빌더(AND)·enabled 토글·레짐/프로파일 할당 UI 동작.
- [ ] Review에 그룹/조건 성과 스캐폴드(EV는 "—" placeholder, Phase 3가 채움).
- [ ] `node --check` 4파일 통과 + `import backend.main` 정상.

## 후속 (이 계획 범위 밖)
- **Phase 3:** `GET /groups`·`GET /conditions` 응답에 `stats:{sample,winrate,ev}` 필드 추가(EOD 학습루프가 `trade_entry_tags`에서 그룹/조건/맥락별 EV 집계) → Task 9 스캐폴드 표가 자동으로 채워짐. 가지치기 추천·자동 weight 조정.

---

## Self-Review

**1. Spec coverage (UI 섹션 대조):**
- spec "Trade History — 선정사유 + 매수사유(발화그룹) + 매도/손절사유 + 손익; click→tag detail" → Task 1(병합)+2(라우트)+3(컬럼+accordion 태그 상세). 매도사유=기존 exit_reason 컬럼 유지 명시. 손익=기존 pnl 컬럼. ✓
- spec "Trading Monitor — candidate 선정사유 + met conditions/groups; on buy 매수사유" → Task 4(selection_reason 백엔드)+5(후보 카드 선정사유 줄). met conditions=기존 buy_readiness 유지. "on buy 매수사유"=거래내역 태깅(Task 3)에서 발화그룹 노출(매수 시점 모니터 토스트는 기존 stream 범위, 사유 데이터는 태깅이 source). ✓
- spec "Settings 매수조건 편집 — atomic conditions w/ editable params, group builder(AND), enable toggles, assign group→regime/RiskProfile + NEW API GET/PUT buy_conditions+condition_groups" → Task 6/7(API 6종)+8(UI 3블록). ✓
- spec "Review — minimal display scaffold for per-group/condition stats (EV는 Phase 3)" → Task 9 스캐폴드(EV "—" placeholder). ✓
- 의뢰서 "NEW API endpoints needed: GET/PUT buy_conditions + condition_groups — specify them(FastAPI routes)" → 명세표 6엔드포인트 + Task 6/7 실제 FastAPI 코드. ✓

**2. Placeholder scan:** TBD/TODO/"적절히"/"위와 유사" 없음. 모든 코드 스텝에 완전한 코드. Task 9의 "—"/`placeholder`는 **의도된 UI 표시값**(Phase 3 EV 미집계)이지 계획 공백이 아님 — Self-Review/완료기준/후속에 명시. Task 4의 import 위치, Task 8 Step 4의 디스패처 인자 폴백은 "먼저 grep 확인 후 분기" — 실제 코드와 grep 명령을 제시하므로 공백 아님. ✓

**3. Type consistency:**
- `enrich_pairs_with_tags(pairs, tags)` 반환 pair에 `entry_tag`/`selection_summary`/`buy_reason_summary` → Task 2 라우트가 동일 함수 호출, Task 3 JS가 `p.selection_summary`/`p.buy_reason_summary`/`p.entry_tag` 읽음. ✓
- `load_tags` 반환 dict 키(`selection_reason{sources,scores,llm_note}`/`fired_groups`/`condition_states`/`market_context`/`outcome`) → Task 1 헬퍼·Task 3 `renderEntryTagDetail` 접근 키 일치(Phase 1c 계약과 동일). ✓
- `build_selection_reason(c)` 반환(`sources/scores/llm_note`) → Task 4 후보 `selection_reason`·Task 5 `_candidateSelectionText` 접근 일치(Phase 1c 제공). ✓
- API 응답 봉투 `{ok, payload:{...}}` 일관(`conditions`/`groups`/`condition`/`group`/`regimes`/`profiles`) → 테스트·프론트 접근 키 일치. ✓
- `load_conditions(enabled_only=False)`/`load_groups(enabled_only=False)` 사용 일관(비활성 포함) — 라우트·테스트 모두 명시. ✓
- 그룹 필드(`id,name,condition_ids,enabled,weight,assigned_to`)·조건 필드(`id,name,ctype,params,enabled`) → API·UI·테스트 동일. ✓
- colspan: statistics 테이블 컬럼 10→12(헤더 2추가) — Task 3 Step 2에서 모든 colspan 일괄 갱신 명시(에러/빈상태/accordion). ✓

수정 사항: 없음 — 계획 일관성 확인됨.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-06-exploration-engine-phase2-ui.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — 태스크마다 새 subagent 디스패치(특히 백엔드 Task 1·6·7과 프론트 Task 3·8을 분리), 태스크 간 리뷰.

**2. Inline Execution** — 이 세션에서 executing-plans로 체크포인트 단위 일괄 실행.

**Which approach?**
