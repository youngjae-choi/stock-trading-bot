# INBOX_EXECUTOR_ui_restructure_stage1 — UI 1단계 구조 변경

## 작업 목적

`backend/static/console.html` 하나만 수정한다.

1. 파란색 배너(`api-banner`) 전체 제거
2. Execution & Risk 메뉴 제거
3. Live Decisions + Positions & Exit → Trading Monitor 통합 (탭 방식)
4. 메뉴 순서 변경
5. Funnel Monitor 설명 문구 동적화

---

## Task 1 — 파란색 배너 완전 제거

### 1-A. HTML div 제거
아래 줄을 찾아 삭제:
```html
<div class="api-banner info active" id="apiStateBanner">백엔드 상태를 확인하는 중입니다. 응답 전까지는 정적 화면과 mock 안내가 표시됩니다.</div>
```

### 1-B. CSS 제거
`.api-banner` 관련 CSS 블록 전체 삭제 (`.api-banner`, `.api-banner.active`, `.api-banner.info`, `.api-banner.warn` 등 모든 `.api-banner` 규칙).

### 1-C. JS 변수 및 함수 제거/정리
- `var apiStateBanner = document.getElementById("apiStateBanner");` 줄 삭제
- `function setApiBanner(kind, message) { ... }` 함수 전체 삭제
- `setApiBanner(...)` 호출 2곳도 찾아서 해당 줄 삭제 (약 2622, 2629줄 근처)

---

## Task 2 — 메뉴 순서 변경 및 Execution & Risk 제거

### 2-A. 사이드바 `<nav>` 교체

현재:
```html
<nav class="nav" id="nav">
  <button class="active" data-screen="today">Today Control <small>main</small></button>
  <button data-screen="rulepack">AI RulePack <small>rules</small></button>
  <button data-screen="funnel">Funnel Monitor <small>screening</small></button>
  <button data-screen="live">Live Decisions <small>realtime</small></button>
  <button data-screen="positions">Positions & Exit <small>exit</small></button>
  <button data-screen="risk">Execution & Risk <small>logs</small></button>
  <button data-screen="data">Data & API <small>health</small></button>
  <button data-screen="api-logs">API Logs <small>admin</small></button>
  <button data-screen="review">Review & Audit <small>learn</small></button>
  <button data-screen="statistics">Statistics <small>history</small></button>
  <button data-screen="engine-test">KIS System Test <small>test</small></button>
  <button data-screen="settings">Settings <small>admin</small></button>
</nav>
```

아래로 교체:
```html
<nav class="nav" id="nav">
  <button class="active" data-screen="today">Today Control <small>main</small></button>
  <button data-screen="trading">Trading Monitor <small>live</small></button>
  <button data-screen="rulepack">AI RulePack <small>rules</small></button>
  <button data-screen="funnel">Funnel Monitor <small>screening</small></button>
  <button data-screen="data">Data & API <small>health</small></button>
  <button data-screen="api-logs">API Logs <small>admin</small></button>
  <button data-screen="review">Review & Audit <small>learn</small></button>
  <button data-screen="statistics">Statistics <small>history</small></button>
  <button data-screen="engine-test">KIS System Test <small>test</small></button>
  <button data-screen="settings">Settings <small>admin</small></button>
</nav>
```

### 2-B. 모바일 `<select>` 교체

현재:
```html
<select id="mobileMenu" class="mobile-menu" aria-label="화면 선택">
  <option value="today">Today Control</option>
  <option value="rulepack">AI RulePack</option>
  <option value="funnel">Funnel Monitor</option>
  <option value="live">Live Decisions</option>
  <option value="positions">Positions & Exit</option>
  <option value="risk">Execution & Risk</option>
  <option value="data">Data & API</option>
  <option value="api-logs">API Logs</option>
  <option value="review">Review & Audit</option>
  <option value="statistics">Statistics</option>
  <option value="engine-test">KIS System Test</option>
  <option value="settings">Settings</option>
</select>
```

아래로 교체:
```html
<select id="mobileMenu" class="mobile-menu" aria-label="화면 선택">
  <option value="today">Today Control</option>
  <option value="trading">Trading Monitor</option>
  <option value="rulepack">AI RulePack</option>
  <option value="funnel">Funnel Monitor</option>
  <option value="data">Data & API</option>
  <option value="api-logs">API Logs</option>
  <option value="review">Review & Audit</option>
  <option value="statistics">Statistics</option>
  <option value="engine-test">KIS System Test</option>
  <option value="settings">Settings</option>
</select>
```

---

## Task 3 — Trading Monitor 신규 화면 추가

`screen-today` 섹션 바로 뒤, `screen-rulepack` 섹션 바로 앞에 `screen-trading` 섹션을 삽입한다.

삽입할 HTML:

```html
<section class="screen" id="screen-trading">
  <div class="page-head">
    <div>
      <h1 class="page-title">Trading Monitor</h1>
      <p class="page-desc">매수 후보 신호 현황과 보유 포지션 관리를 한 화면에서 확인합니다.</p>
    </div>
  </div>

  <!-- 탭 전환 버튼 -->
  <div style="display:flex; gap:0; margin-bottom:16px; border-bottom:2px solid var(--border);">
    <button class="tab-btn active" id="trading-tab-btn-buy" onclick="showTradingTab('buy')" style="padding:8px 20px; background:none; border:none; border-bottom:2px solid transparent; cursor:pointer; font-size:14px; font-weight:600; color:var(--text-muted); margin-bottom:-2px;">매수 대기</button>
    <button class="tab-btn" id="trading-tab-btn-sell" onclick="showTradingTab('sell')" style="padding:8px 20px; background:none; border:none; border-bottom:2px solid transparent; cursor:pointer; font-size:14px; font-weight:600; color:var(--text-muted); margin-bottom:-2px;">보유 종목</button>
  </div>

  <!-- ── 매수 대기 탭 (Live Decisions 내용) ── -->
  <div id="trading-tab-buy">
    <div class="card" id="tm-engine-card">
      <div class="card-title">Decision Engine 상태</div>
      <div id="tm-engine-status" style="display:flex; flex-wrap:wrap; gap:16px; align-items:center; margin-bottom:12px;">
        <div>상태: <span id="tm-engine-active" class="status warn">로딩중</span></div>
        <div>WS: <span id="tm-engine-ws" class="muted">-</span></div>
        <div>후보 종목: <span id="tm-engine-candidates" class="muted">-</span></div>
        <div>신호 발행: <span id="tm-engine-signals-sent" class="muted">-</span></div>
      </div>
      <div style="display:flex; gap:8px;">
        <button class="btn primary" onclick="liveDecisionActivate()">수동 활성화</button>
        <button class="btn" onclick="liveDecisionDeactivate()">비활성화</button>
      </div>
    </div>

    <div class="section-gap"></div>

    <div class="card">
      <div class="card-title" style="display:flex; justify-content:space-between; align-items:center;">
        <span>오늘 매수 신호</span>
        <button class="btn" onclick="loadTradingMonitor()">새로고침</button>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>시간</th><th>종목코드</th><th>종목명</th><th>진입가</th><th>신뢰도</th><th>상태</th></tr>
          </thead>
          <tbody id="tm-signals-tbody">
            <tr><td colspan="6" class="muted" style="text-align:center;">로딩중...</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <div style="margin-top:8px; font-size:12px; color:var(--text-muted); text-align:right;" id="tm-buy-footer">
      KIS REST 토큰은 백엔드 singleton 캐시 기준이며, KIS WebSocket은 S4 스크리닝 완료 후 자동 구독됩니다.
    </div>
  </div>

  <!-- ── 보유 종목 탭 (Positions & Exit 내용) ── -->
  <div id="trading-tab-sell" style="display:none;">
    <div class="card" id="tm-account-card">
      <div class="card-title" style="display:flex; justify-content:space-between; align-items:center;">
        <span>계좌 정보</span>
        <button class="btn" onclick="loadAccountBalance()">새로고침</button>
      </div>
      <div id="tm-account-info" style="margin-bottom:12px;">
        <div class="muted" style="font-size:13px;" id="tm-account-no">계좌번호: -</div>
        <div style="display:flex; gap:24px; margin-top:6px;">
          <div>예수금: <strong id="tm-deposit">-</strong>원</div>
          <div>총평가금액: <strong id="tm-total-eval">-</strong>원</div>
        </div>
      </div>
      <div class="card-title" style="margin-top:16px; margin-bottom:8px;">보유 종목</div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>종목코드</th><th>종목명</th><th>수량</th><th>매입평균가</th><th>현재가</th><th>손익률</th></tr>
          </thead>
          <tbody id="tm-holdings-tbody">
            <tr><td colspan="6" class="muted" style="text-align:center;">로딩중...</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="section-gap"></div>

    <div class="card">
      <div class="card-title" style="display:flex; justify-content:space-between; align-items:center;">
        <span>실시간 포지션 감시</span>
        <div style="display:flex; gap:8px;">
          <button class="btn" onclick="loadPositionMonitoring()">새로고침</button>
          <button class="btn danger" onclick="liquidateAll()">전체 청산</button>
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>종목코드</th><th>종목명</th><th>수량</th><th>진입가</th><th>현재가</th><th>손익률</th><th>손절가</th><th>익절가</th><th>트레일링</th><th>보유시간</th></tr>
          </thead>
          <tbody id="tm-monitor-tbody">
            <tr><td colspan="10" class="muted" style="text-align:center;">로딩중...</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="section-gap"></div>

    <div class="card">
      <div class="card-title" style="display:flex; justify-content:space-between; align-items:center;">
        <span>오늘 주문내역</span>
        <button class="btn" onclick="loadTodayOrders()">새로고침</button>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>시간</th><th>종목</th><th>구분</th><th>수량</th><th>가격</th><th>주문번호</th><th>상태</th></tr>
          </thead>
          <tbody id="tm-orders-tbody">
            <tr><td colspan="7" class="muted" style="text-align:center;">로딩중...</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="section-gap"></div>

    <div class="grid cols-3">
      <div class="card"><div class="card-title">청산 안전장치</div><p>당일 단타 포지션은 15:20에 자동 청산 검토 상태로 전환됩니다.</p></div>
      <div class="card"><div class="card-title">트레일링 조건</div><p>수익 +2.0% 이상 도달 후 고점 대비 -1.0% 하락 시 청산합니다.</p></div>
      <div class="card"><div class="card-title">시간손절 조건</div><p>30분 보유 후 +0.5% 미만이면 청산 후보로 분류합니다.</p></div>
    </div>

    <div style="margin-top:8px; font-size:12px; color:var(--text-muted); text-align:right;" id="tm-sell-footer"></div>
  </div>
</section>
```

---

## Task 4 — Funnel Monitor 설명 문구 수정

아래를 찾아:
```html
<p class="page-desc">전체 종목이 어떤 조건으로 200개 유니버스와 15개 후보로 압축됐는지 확인합니다.</p>
```

아래로 교체:
```html
<p class="page-desc">전체 종목이 어떤 조건으로 유니버스와 후보 종목으로 압축됐는지 확인합니다. 숫자는 매일 달라집니다.</p>
```

---

## Task 5 — JS 함수 추가 및 showScreen() 수정

### 5-A. `showTradingTab()` 함수 추가

기존 JS 함수 영역에 추가:

```javascript
  function showTradingTab(tab) {
    var buyTab = document.getElementById("trading-tab-buy");
    var sellTab = document.getElementById("trading-tab-sell");
    var buyBtn = document.getElementById("trading-tab-btn-buy");
    var sellBtn = document.getElementById("trading-tab-btn-sell");
    if (!buyTab || !sellTab) return;

    if (tab === "buy") {
      buyTab.style.display = "";
      sellTab.style.display = "none";
      if (buyBtn) { buyBtn.style.color = "var(--accent)"; buyBtn.style.borderBottomColor = "var(--accent)"; }
      if (sellBtn) { sellBtn.style.color = "var(--text-muted)"; sellBtn.style.borderBottomColor = "transparent"; }
      loadTradingMonitor();
    } else {
      buyTab.style.display = "none";
      sellTab.style.display = "";
      if (buyBtn) { buyBtn.style.color = "var(--text-muted)"; buyBtn.style.borderBottomColor = "transparent"; }
      if (sellBtn) { sellBtn.style.color = "var(--accent)"; sellBtn.style.borderBottomColor = "var(--accent)"; }
      loadAccountBalance();
      loadPositionMonitoring();
      loadTodayOrders();
    }
  }
```

### 5-B. `loadTradingMonitor()` 함수 추가

```javascript
  async function loadTradingMonitor() {
    try {
      var statusData = await fetchJson("/api/v1/decision/status");
      var p = statusData.payload || {};
      var activeEl = document.getElementById("tm-engine-active");
      var wsEl = document.getElementById("tm-engine-ws");
      var candEl = document.getElementById("tm-engine-candidates");
      var sigEl = document.getElementById("tm-engine-signals-sent");
      if (activeEl) setStatusChip(activeEl, p.active ? "ok" : "warn", p.active ? "활성" : "비활성");
      if (wsEl) wsEl.textContent = p.ws_connected ? "연결됨" : "미연결";
      if (candEl) candEl.textContent = (p.candidates || 0) + "개";
      if (sigEl) sigEl.textContent = (p.signals_sent || 0) + "건";
    } catch(e) { console.warn("loadTradingMonitor status error", e); }

    try {
      var signalsData = await fetchJson("/api/v1/decision/signals/today");
      var signals = (signalsData.payload || {}).signals || [];
      var tbody = document.getElementById("tm-signals-tbody");
      if (!tbody) return;
      if (signals.length === 0) {
        tbody.innerHTML = "<tr><td colspan='6' class='muted' style='text-align:center;'>오늘 매수 신호 없음</td></tr>";
        return;
      }
      tbody.innerHTML = signals.map(function(s) {
        var t = (s.created_at || "").substring(11,16);
        var statusCls = s.status === "executed" ? "ok" : s.status === "failed" ? "bad" : "warn";
        return "<tr>"
          + "<td>" + t + "</td>"
          + "<td>" + (s.symbol || "-") + "</td>"
          + "<td>" + (s.name || "-") + "</td>"
          + "<td>" + (s.trigger_price ? Math.round(s.trigger_price).toLocaleString() + "원" : "-") + "</td>"
          + "<td>" + (s.confidence ? (s.confidence * 100).toFixed(0) + "%" : "-") + "</td>"
          + "<td><span class='status " + statusCls + "'>" + (s.status || "-") + "</span></td>"
          + "</tr>";
      }).join("");
    } catch(e) { console.warn("loadTradingMonitor signals error", e); }
  }
```

### 5-C. 기존 `loadAccountBalance()`, `loadPositionMonitoring()`, `loadTodayOrders()` 함수 수정

이 함수들은 현재 `positions-*` id를 참조한다. Trading Monitor의 `tm-*` id도 함께 업데이트하도록 각 함수를 수정한다.

**방법:** 각 함수에서 getElementById로 요소를 찾을 때, `positions-*` id와 `tm-*` id를 모두 시도하는 헬퍼를 사용하거나, 두 id 모두에 값을 쓰도록 수정한다.

가장 간단한 방법은 각 함수 내에서 `positions-account-no` 와 `tm-account-no` 를 둘 다 업데이트하는 줄을 추가하는 것이다.

**`loadAccountBalance()` 수정 예시:**
```javascript
// 기존에 positions-account-no를 업데이트하는 줄 바로 뒤에
if (document.getElementById("tm-account-no")) {
  document.getElementById("tm-account-no").textContent = /* same value */;
}
```

실제로는 `loadAccountBalance()` 전체를 읽어서, `positions-deposit`, `positions-total-eval`, `positions-account-no`, `positions-holdings-tbody` 각 element를 업데이트하는 줄 다음에 `tm-deposit`, `tm-total-eval`, `tm-account-no`, `tm-holdings-tbody` 도 같은 값으로 업데이트하는 줄을 추가한다.

**`loadPositionMonitoring()` 수정 예시:**
`positions-monitor-tbody` 업데이트 후 `tm-monitor-tbody` 도 같은 innerHTML 적용.

**`loadTodayOrders()` 수정 예시:**
`orders-today-tbody` 업데이트 후 `tm-orders-tbody` 도 같은 innerHTML 적용.

### 5-D. `showScreen()` 함수 수정

`showScreen()` 함수 내에 `trading` 탭 진입 시 로드 로직을 추가한다:

현재 `showScreen()` 함수에서 `if (name === "risk") { loadExecutionRisk(); }` 부분을 찾아 아래로 교체:

```javascript
    if (name === "trading") {
      loadTradingMonitor();
    }
```

기존 `if (name === "live") { ... }` 와 `if (name === "positions") { ... }` 가 있다면 그대로 유지한다 (기존 screen-live, screen-positions HTML 섹션이 남아있으면 작동에 문제없음).

---

## Task 6 — 기존 screen-live, screen-positions, screen-risk 처리

- `screen-live`, `screen-positions`, `screen-risk` HTML 섹션은 **삭제하지 않는다**.
- 메뉴에서만 제거되었으므로 직접 접근 불가하지만 JS 함수들은 계속 정상 작동한다.
- 이렇게 하면 기존 JS 함수(`loadLiveData`, `liveDecisionActivate` 등)를 건드리지 않아도 된다.

---

## 완료 기준

```python
python3 -c "
from html.parser import HTMLParser
class Check(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.nav_screens = []
    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if 'id' in d: self.ids.append(d['id'])
        if d.get('data-screen'): self.nav_screens.append(d['data-screen'])

c = Check()
c.feed(open('backend/static/console.html', encoding='utf-8').read())
checks = [
    ('Trading Monitor screen exists', 'screen-trading' in c.ids),
    ('Trading Monitor in nav', 'trading' in c.nav_screens),
    ('Execution Risk NOT in nav', 'risk' not in c.nav_screens),
    ('apiStateBanner removed', 'apiStateBanner' not in open('backend/static/console.html').read()),
    ('tm-signals-tbody exists', 'tm-signals-tbody' in c.ids),
    ('tm-monitor-tbody exists', 'tm-monitor-tbody' in c.ids),
    ('showTradingTab function', 'showTradingTab' in open('backend/static/console.html').read()),
    ('loadTradingMonitor function', 'loadTradingMonitor' in open('backend/static/console.html').read()),
    ('Funnel desc fixed', '200개 유니버스' not in open('backend/static/console.html').read()),
]
for name, ok in checks:
    print(f'{name}: {\"OK\" if ok else \"FAIL\"}')
"
```

기대 출력: 모든 항목 OK

OUTBOX 결과는 `docs/agent-comm/OUTBOX_EXECUTOR_ui_restructure_stage1.md` 에 작성하라.
