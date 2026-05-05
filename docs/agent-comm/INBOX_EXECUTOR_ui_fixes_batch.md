# INBOX_EXECUTOR_ui_fixes_batch

## 역할
너는 Executor(Codex)다. 아래 4가지 버그/개선을 수행하라.
완료 후 `docs/agent-comm/OUTBOX_EXECUTOR_ui_fixes_batch.md`에 결과를 작성하라.

수정 대상:
- `backend/static/console.html`
- `backend/api/routes/orders.py`
- `backend/services/engine/order_executor.py`
- `backend/api/routes/account.py`

---

## 버그 1 — Trade History 기간 조회 수정

### 문제
`loadAllOrders()` 함수에서 today 이외의 필터(week/month/lastmonth/all)는
`/api/v1/decision/signals/today`를 호출해서 항상 오늘 신호만 표시된다.

```javascript
// 현재 잘못된 코드
} else {
  var limit = stFilter === "all" ? 500 : 120;
  await fetchJson("/api/v1/trades/history?limit=" + limit);   // 응답 미사용
  var signalsResponse = await fetchJson("/api/v1/decision/signals/today");  // 오늘만
  orders = (signalsResponse && signalsResponse.payload && signalsResponse.payload.signals) || [];
}
```

### 수정 A — backend: `GET /api/v1/orders/range` 추가

`backend/services/engine/order_executor.py`에 함수 추가:

```python
def get_orders_by_range(start_date: str, end_date: str, limit: int = 500) -> list[dict[str, Any]]:
    """Return orders between start_date and end_date (YYYY-MM-DD, inclusive)."""
    safe_limit = max(1, min(int(limit), 1000))
    _ensure_orders_table()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM trading_orders WHERE trade_date >= ? AND trade_date <= ? ORDER BY created_at DESC LIMIT ?",
            (start_date, end_date, safe_limit),
        ).fetchall()
    return [dict(row) for row in rows]
```

`backend/api/routes/orders.py`에 엔드포인트 추가:

```python
from datetime import date, timedelta

@router.get("/range")
async def get_orders_range_api(
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    limit: int = Query(500, ge=1, le=1000),
):
    """Return trading orders between start and end date."""
    endpoint = "/api/v1/orders/range"
    logger.info("START: GET %s start=%s end=%s", endpoint, start, end)
    try:
        orders = get_orders_by_range(start, end, limit)
        logger.info("SUCCESS: GET %s count=%d", endpoint, len(orders))
        return {"ok": True, "payload": {"orders": orders, "count": len(orders)}}
    except Exception as exc:
        logger.error("FAIL: GET %s — %s", endpoint, exc)
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})
```

### 수정 B — frontend: `loadAllOrders()` 기간별 조회 수정

`backend/static/console.html`에서 `loadAllOrders()` 함수를 찾아
아래 else 블록만 교체한다 (try 내부, stFilter !== "today" 분기):

```javascript
} else {
  var now = new Date();
  var todayStr = now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0") + "-" + String(now.getDate()).padStart(2, "0");
  var startStr = todayStr;
  if (stFilter === "week") {
    var day = now.getDay();
    var monday = new Date(now);
    monday.setDate(now.getDate() - (day === 0 ? 6 : day - 1));
    startStr = monday.getFullYear() + "-" + String(monday.getMonth() + 1).padStart(2, "0") + "-" + String(monday.getDate()).padStart(2, "0");
  } else if (stFilter === "month") {
    startStr = now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0") + "-01";
  } else if (stFilter === "lastmonth") {
    var lm = new Date(now.getFullYear(), now.getMonth() - 1, 1);
    var lmEnd = new Date(now.getFullYear(), now.getMonth(), 0);
    startStr = lm.getFullYear() + "-" + String(lm.getMonth() + 1).padStart(2, "0") + "-01";
    todayStr = lmEnd.getFullYear() + "-" + String(lmEnd.getMonth() + 1).padStart(2, "0") + "-" + String(lmEnd.getDate()).padStart(2, "0");
  } else if (stFilter === "all") {
    startStr = "2020-01-01";
  }
  var rangeResponse = await fetchJson("/api/v1/orders/range?start=" + startStr + "&end=" + todayStr + "&limit=500");
  orders = (rangeResponse && rangeResponse.payload && rangeResponse.payload.orders) || [];
}
```

기간 필터 후처리 코드(오늘/이번주/이번달/지난달 filter 블록)는 이제 불필요하므로 제거한다.
단 `stFilter === "today"` 분기는 그대로 유지한다.

---

## 버그 2 — Trading Monitor 예수금 표시 수정

### 문제
`backend/api/routes/account.py`의 `_build_balance_payload()`에서
`buyable_cash` 계산 시 `nass_amt`(순자산금액, 매우 큰 값)가 우선 선택됨.
`ord_psbl_cash`(주문가능현금)가 있으면 그걸 써야 한다.

### 수정
`backend/api/routes/account.py`에서 `_build_balance_payload()` 내:

**현재 코드:**
```python
deposit = _to_int(summary.get("dnca_tot_amt"))
buyable_cash = deposit
for key in ("nass_amt", "ord_psbl_cash", "dnca_tot_amt"):
    candidate = _to_int(summary.get(key))
    if candidate > 0:
        buyable_cash = candidate
        break
```

**수정 후:**
```python
deposit = _to_int(summary.get("dnca_tot_amt"))
# 주문가능금액(ord_psbl_cash) 우선, 없으면 예수금(dnca_tot_amt) 사용
# nass_amt는 순자산금액(총자산)이므로 buyable_cash에 사용하지 않는다
buyable_cash = deposit
for key in ("ord_psbl_cash", "dnca_tot_amt"):
    candidate = _to_int(summary.get(key))
    if candidate > 0:
        buyable_cash = candidate
        break
```

---

## 버그 3 — Alert Center 메뉴 복원

`backend/static/console.html`에서 아래 3곳의 `style="display:none"`을 제거한다.

1. 모바일 select option:
```html
<option value="alerts" style="display:none">Alert Center</option>
```
→
```html
<option value="alerts">Alert Center</option>
```

2. 사이드바 버튼:
```html
<button data-screen="alerts" style="display:none">Alert Center <small>alerts</small></button>
```
→
```html
<button data-screen="alerts">Alert Center <small>alerts</small></button>
```

Approval Queue는 숨김 상태 유지 (수정하지 않는다).

---

## 버그 4 — Data & API 화면 UI 통일

`backend/static/console.html`의 `id="screen-data"` 섹션에서
API 호출 로그 카드를 **제외한** 나머지 모든 섹션을 아래와 같이 통일한다.

### 규칙
- 모든 상태 표시 섹션을 `<div class="card">` 안에 배치
- 각 항목은 `<div class="grid cols-4">` 또는 `<div class="grid cols-2">` 안의 `<div class="card compact">` 로 표시
- `natural-card` 클래스 제거
- 기존 id는 모두 유지 (JS 연동 유지)

### 현재 → 목표 구조

```
[Rule System 카드] → compact card 형식으로 변경
  Base RulePack / Risk Profile Pack / Daily Plan / Symbol Assignments 각각 compact card
  
[KIS REST / KIS WebSocket / LLM Router / SQLite DB] → 현재 이미 compact card, 유지

[Data Quality Guard] → natural-card → compact card 2개로 변경
  전체 상태 / 오늘 이벤트 → 각각 compact card

[System Health] → natural-card 4개 → compact card 4개로 변경
  Auto Engine / Rule Composition / WebSocket / Risk Guard

[LLM Provider 상태] → table 방식 유지 (카드 안에 table, 이미 card)

[Telegram 알림] → 현재 고립된 grid cols-4 → 기존 compact card에 합류
  KIS REST / KIS WebSocket / LLM Router / SQLite DB / Telegram 5개를 한 grid에

[API 호출 로그] → 그대로 유지 (수정 금지)
```

### 구체적 교체 대상

#### 4-A: Rule System 섹션 교체

기존:
```html
<div class="card" style="margin-bottom:16px;">
  <div class="card-title">Rule System</div>
  <div style="display:flex; flex-direction:column; gap:4px; font-size:12px;" id="da-rule-system">
    <div style="display:flex; justify-content:space-between; padding:4px 0; border-bottom:1px solid var(--line);">
      <span style="color:var(--muted);">Base RulePack</span>
      <span id="da-base-id">-</span>
    </div>
    ... (6개 항목)
  </div>
</div>
```

교체 후:
```html
<div class="card" style="margin-bottom:16px;">
  <div class="card-title">Rule System</div>
  <div class="grid" style="grid-template-columns:repeat(3, 1fr); gap:10px; margin-top:8px;">
    <div class="card compact"><div class="card-title">Base RulePack</div><div class="metric" id="da-base-id" style="font-size:13px;">-</div></div>
    <div class="card compact"><div class="card-title">Risk Profile Pack</div><div class="metric" id="da-profile-id" style="font-size:13px;">-</div></div>
    <div class="card compact"><div class="card-title">Daily Plan</div><div class="metric" id="da-plan-id" style="font-size:13px;">-</div></div>
    <div class="card compact"><div class="card-title">배정 종목 수</div><div class="metric" id="da-assignments-n" style="font-size:13px;">-개</div></div>
    <div class="card compact"><div class="card-title">고정 익절</div><div class="metric" style="font-size:13px; color:#f85149;">OFF</div></div>
    <div class="card compact"><div class="card-title">트레일링 청산</div><div class="metric" style="font-size:13px; color:#3fb950;">ON</div></div>
  </div>
</div>
```

#### 4-B: Data Quality Guard 섹션 교체

기존:
```html
<div class="card" style="margin-bottom:16px;">
  <div class="card-title">Data Quality Guard</div>
  <div class="grid cols-2">
    <div class="natural-card">
      <h4>전체 상태</h4>
      <p><span class="status ok" id="dq-overall-status">NORMAL</span></p>
      <p class="muted" id="dq-overall-detail">데이터 이상 없음</p>
    </div>
    <div class="natural-card">
      <h4>오늘 이벤트</h4>
      <p><span class="metric" id="dq-event-count" style="font-size:1.5rem">0</span></p>
      <p class="muted" id="dq-event-detail">이상 이벤트 수</p>
    </div>
  </div>
  <div style="margin-top:8px; font-size:12px; color:var(--muted);" id="dq-event-breakdown">
    이벤트 유형별 현황 로딩 중...
  </div>
</div>
```

교체 후:
```html
<div class="card" style="margin-bottom:16px;">
  <div class="card-title">Data Quality Guard</div>
  <div class="grid cols-2" style="margin-top:8px;">
    <div class="card compact">
      <div class="card-title">전체 상태</div>
      <div><span class="status ok" id="dq-overall-status">NORMAL</span></div>
      <div class="muted" id="dq-overall-detail">데이터 이상 없음</div>
    </div>
    <div class="card compact">
      <div class="card-title">오늘 이벤트</div>
      <div class="metric" id="dq-event-count">0</div>
      <div class="muted" id="dq-event-detail">이상 이벤트 수</div>
    </div>
  </div>
  <div style="margin-top:8px; font-size:12px; color:var(--muted);" id="dq-event-breakdown">
    이벤트 유형별 현황 로딩 중...
  </div>
</div>
```

#### 4-C: System Health 섹션 교체

기존:
```html
<div class="card" style="margin-bottom:16px;">
  <div class="card-title">System Health <span>엔진 & 연결 상태</span></div>
  <div class="grid cols-2">
    <div class="natural-card">
      <h4>Auto Engine</h4>
      <p><span class="status ok" id="kisTokenStatus">확인중</span></p>
      <p class="muted" id="kisTokenDetail">Auto Engine 상태</p>
    </div>
    ... (4개 natural-card)
  </div>
</div>
```

교체 후:
```html
<div class="card" style="margin-bottom:16px;">
  <div class="card-title">System Health <span>엔진 & 연결 상태</span></div>
  <div class="grid cols-4" style="margin-top:8px;">
    <div class="card compact">
      <div class="card-title">Auto Engine</div>
      <div><span class="status ok" id="kisTokenStatus">확인중</span></div>
      <div class="muted" id="kisTokenDetail">Auto Engine 상태</div>
    </div>
    <div class="card compact">
      <div class="card-title">Rule Composition</div>
      <div><span class="status ok" id="rulepackStatus">확인중</span></div>
      <div class="muted" id="rulepackDetail">오늘 활성 Rule Composition</div>
    </div>
    <div class="card compact">
      <div class="card-title">WebSocket</div>
      <div><span class="status ok" id="websocketStatus">확인중</span></div>
      <div class="muted" id="websocketDetail">S4 완료 후 자동 구독</div>
    </div>
    <div class="card compact">
      <div class="card-title">Risk Guard</div>
      <div><span class="status ok" id="riskStatus">확인중</span></div>
      <div class="muted" id="riskDetail">긴급정지 상태</div>
    </div>
  </div>
</div>
```

#### 4-D: KIS/LLM/DB/Telegram 통합

현재 KIS REST/WebSocket/LLM Router/SQLite DB 4개 compact card와
Telegram compact card가 분리된 `grid cols-4`에 있다.

두 grid를 하나로 합쳐 5개를 한 줄에 배치:

```html
<div class="grid" style="grid-template-columns:repeat(5,1fr); gap:10px; margin-bottom:16px;">
  <div class="card compact"><div class="card-title">KIS REST</div><div class="metric" id="dh-kisRest">-</div><div class="muted" id="dh-kisRestDetail">확인중</div></div>
  <div class="card compact"><div class="card-title">KIS WebSocket</div><div class="metric" id="dh-kisWs">-</div><div class="muted" id="dh-kisWsDetail">확인중</div></div>
  <div class="card compact"><div class="card-title">LLM Router</div><div class="metric" id="dh-llm">-</div><div class="muted" id="dh-llmDetail">provider 확인중</div></div>
  <div class="card compact"><div class="card-title">SQLite DB</div><div class="metric good" id="dh-db">로컬</div><div class="muted" id="dh-dbDetail">data/ 디렉토리</div></div>
  <div class="card compact"><div class="card-title">Telegram</div><div class="metric" id="da-telegram-status">-</div><div class="muted" id="da-telegram-detail">상태 확인 중</div></div>
</div>
```

기존 `<div class="section-gap">` 및 고립된 Telegram `<div class="grid cols-4">...</div>` 블록은 제거한다.

---

## 검증

```bash
# py_compile
python3 -m py_compile backend/api/routes/orders.py backend/api/routes/account.py backend/services/engine/order_executor.py && echo "py_compile OK"

# HTML parse
python3 -c "
from html.parser import HTMLParser
with open('backend/static/console.html', encoding='utf-8') as f:
    HTMLParser().feed(f.read())
print('HTML parse OK')
"

# grep 검증
echo "=== Alert Center 노출 확인 ==="
grep "data-screen=\"alerts\"" backend/static/console.html | grep -v "display:none" || echo "숨김 해제 확인 필요"

echo "=== nass_amt buyable_cash 제거 확인 ==="
grep "nass_amt" backend/api/routes/account.py | grep -v "#" || echo "nass_amt 제거됨"

echo "=== /api/v1/orders/range 추가 확인 ==="
grep "orders/range" backend/static/console.html | head -3

echo "=== natural-card 제거 확인 ==="
grep -c "natural-card" backend/static/console.html || echo "0"
```

---

## 완료 체크리스트

- [ ] `get_orders_by_range()` 함수 추가 (order_executor.py)
- [ ] `GET /api/v1/orders/range` 엔드포인트 추가 (orders.py)
- [ ] `loadAllOrders()` 기간 필터 수정 (console.html)
- [ ] `_build_balance_payload()` buyable_cash 필드 순서 수정 (account.py)
- [ ] Alert Center 사이드바 버튼 노출 복원 (display:none 제거)
- [ ] Alert Center 모바일 option 노출 복원 (display:none 제거)
- [ ] Data & API Rule System 섹션 → compact card 통일
- [ ] Data & API Data Quality Guard → compact card 통일
- [ ] Data & API System Health → compact card 통일
- [ ] Data & API KIS/LLM/DB/Telegram 5개 통합 grid
- [ ] py_compile OK
- [ ] HTML parse OK

결과는 `docs/agent-comm/OUTBOX_EXECUTOR_ui_fixes_batch.md`에 작성하라.
