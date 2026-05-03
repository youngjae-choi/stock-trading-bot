# INBOX_EXECUTOR_ui_overhaul — 콘솔 UI 전면 점검 및 Statistics 페이지 추가

## 작업 목적

`backend/static/console.html` (3071줄) 한 파일만 수정한다.
반드시 전체 파일을 먼저 읽은 뒤 작업한다.

---

## 현황 진단 (수정 전 확인)

### 동작하지 않는 버튼 (JS 핸들러 없음)
| 화면 | 버튼 | 처리 |
|------|------|------|
| Today Control | "시스템 점검" | `loadConsoleData()` 호출로 교체 |
| Today Control | "로그 다운로드" | 제거 |
| Data & API | "데이터 재점검" | `loadDataHealth()` 호출로 교체 |
| Review & Audit | "AI 복기 생성" | "일일 요약 생성" 으로 텍스트 변경 + `runDailySummary()` 연결 |
| Review & Audit | "CSV 다운로드" | 제거 |

### Mock 전용 화면 (실 API 연결 필요)
| 화면 | 문제 | 해결책 |
|------|------|--------|
| Funnel Monitor | 전체 정적 mock | `GET /api/v1/screening/today` 연결 |
| Execution & Risk | 전체 정적 mock | `GET /api/v1/orders/today` 연결 |
| Data & API | PostgreSQL/Telegram 등 허위 표시 | `GET /api/v1/market-tone/providers` 로 LLM 상태 표시 |
| Review & Audit | 전체 정적 mock | `GET /api/v1/trades/history` 연결 |

---

## daily_trade_summary 실제 DB 컬럼 (서비스 코드 기준)

`trade_date`, `total_orders`, `buy_orders`, `sell_orders`, `failed_orders`,
`realized_pnl`, `realized_pnl_pct`, `symbols_traded` (JSON 배열),
`market_tone`, `rulepack_id`, `created_at`, `updated_at`

→ 이 컬럼을 기준으로 UI를 구성한다. win_count 등은 없으므로 사용 금지.

---

## Task 1 — Today Control 버튼 수정

약 936~938줄 (page-head의 button 두 개):

변경 전:
```html
<button class="btn primary">시스템 점검</button>
<button class="btn">로그 다운로드</button>
```

변경 후:
```html
<button class="btn" onclick="loadConsoleData()">새로고침</button>
```

---

## Task 2 — Data & API 화면 전면 교체

### 2-1. "데이터 재점검" 버튼 교체
변경 전: `<button class="btn primary">데이터 재점검</button>`
변경 후: `<button class="btn" onclick="loadDataHealth()">새로고침</button>`

### 2-2. 상단 4개 metric 카드 교체

기존 KIS REST, KIS WebSocket, PostgreSQL, Telegram 카드를 아래로 교체:

```html
<div class="grid cols-4">
  <div class="card compact"><div class="card-title">KIS REST</div><div class="metric" id="dh-kisRest">-</div><div class="muted" id="dh-kisRestDetail">확인중</div></div>
  <div class="card compact"><div class="card-title">KIS WebSocket</div><div class="metric" id="dh-kisWs">-</div><div class="muted" id="dh-kisWsDetail">확인중</div></div>
  <div class="card compact"><div class="card-title">LLM Router</div><div class="metric" id="dh-llm">-</div><div class="muted" id="dh-llmDetail">provider 확인중</div></div>
  <div class="card compact"><div class="card-title">SQLite DB</div><div class="metric good" id="dh-db">로컬</div><div class="muted">data/ 디렉토리</div></div>
</div>
```

### 2-3. 데이터 품질 체크 테이블 → LLM Provider 상태 카드로 교체

기존 "데이터 품질 체크" 카드 전체를 아래로 교체:

```html
<div class="card">
  <div class="card-title">LLM Provider 상태 <span>llm_router 우선순위 순서</span></div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>Provider</th><th>역할</th><th>모델</th><th>상태</th></tr>
      </thead>
      <tbody id="llmProvidersTableBody">
        <tr><td colspan="4" class="muted">불러오는 중...</td></tr>
      </tbody>
    </table>
  </div>
</div>
```

### 2-4. JS: `loadDataHealth()` 함수 추가 (스크립트 끝 `init()` 함수 직전에 삽입)

```javascript
async function loadDataHealth() {
  try {
    var healthData = await fetchJson("/api/v1/bot/data-health");
    var p = healthData.payload || {};
    var health = p.health || {};

    function setDH(id, text, cls) {
      var el = document.getElementById("dh-" + id);
      if (el) { el.textContent = text; if (cls) el.className = "metric " + cls; }
    }
    function setDHDetail(id, text) {
      var el = document.getElementById("dh-" + id + "Detail");
      if (el) el.textContent = text;
    }

    var kisRest = health.kis_rest || {};
    setDH("kisRest", kisRest.status === "ok" ? "정상" : "오류", kisRest.status === "ok" ? "good" : "bad");
    setDHDetail("kisRest", kisRest.detail || "-");

    var ws = health.websocket || {};
    setDH("kisWs", ws.status === "ok" ? "연결중" : "끊김", ws.status === "ok" ? "good" : "warn");
    setDHDetail("kisWs", ws.detail || "-");
  } catch (e) { /* ignore */ }

  try {
    var llmData = await fetchJson("/api/v1/market-tone/providers");
    var providers = llmData.payload || [];
    var activeCount = providers.filter(function(p) { return p.enabled; }).length;
    var dhLlm = document.getElementById("dh-llm");
    var dhLlmDetail = document.getElementById("dh-llmDetail");
    if (dhLlm) { dhLlm.textContent = activeCount + "/" + providers.length + " 활성"; dhLlm.className = "metric " + (activeCount > 0 ? "good" : "warn"); }
    if (dhLlmDetail) dhLlmDetail.textContent = providers.filter(function(p) { return p.enabled; }).map(function(p) { return p.name; }).join(" → ") || "없음";

    var tbody = document.getElementById("llmProvidersTableBody");
    if (tbody) {
      if (providers.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="muted">provider 없음 — .env에 API 키를 설정하세요</td></tr>';
      } else {
        tbody.innerHTML = providers.map(function(p) {
          return '<tr>'
            + '<td><strong>' + escapeHtml(p.name || "") + '</strong></td>'
            + '<td>' + escapeHtml(p.role || "") + '</td>'
            + '<td>' + escapeHtml(p.model || "") + '</td>'
            + '<td><span class="status ' + (p.enabled ? "ok" : "warn") + '">' + (p.enabled ? "활성" : "비활성 (API 키 없음)") + '</span></td>'
            + '</tr>';
        }).join("");
      }
    }
  } catch (e) {
    var tbody2 = document.getElementById("llmProvidersTableBody");
    if (tbody2) tbody2.innerHTML = '<tr><td colspan="4" class="muted">불러오기 실패: ' + escapeHtml(e.message) + '</td></tr>';
  }
}
```

### 2-5. `showScreen()` 함수에 Data & API 탭 진입 시 자동 로드 추가

`showScreen()` 함수 내부 (name === "positions" 블록과 같은 레벨)에 추가:
```javascript
if (name === "data") {
  loadDataHealth();
}
```

---

## Task 3 — Funnel Monitor 실 데이터 연결

### 3-1. page-head에 새로고침 버튼 추가

`screen-funnel`의 `page-head` div 안에 추가:
```html
<button class="btn" onclick="loadFunnelData()">새로고침</button>
```

### 3-2. 상단 4개 metric 카드에 id 추가 (숫자 부분)

현재 하드코딩된 2500, 200, 15, 4를 id가 있는 span으로 교체:
- `<div class="metric">2,500</div>` → `<div class="metric" id="funnel-total">2,500</div>`
- `<div class="metric">200</div>` → `<div class="metric" id="funnel-layer1">200</div>`
- `<div class="metric">15</div>` → `<div class="metric" id="funnel-layer2">-</div>`
- `<div class="metric">4</div>` → `<div class="metric" id="funnel-candidates">-</div>`

### 3-3. 후보 15개 선정 결과 테이블 tbody에 id 추가

`<tbody>` → `<tbody id="funnel-candidates-tbody">`

### 3-4. JS: `loadFunnelData()` 함수 추가

```javascript
async function loadFunnelData() {
  try {
    var overviewData = await fetchJson("/api/v1/bot/overview");
    var funnel = overviewData.payload && overviewData.payload.funnel;
    if (funnel) {
      var totalEl = document.getElementById("funnel-total");
      var l1El = document.getElementById("funnel-layer1");
      if (totalEl) totalEl.textContent = (funnel.market_total || "-").toLocaleString();
      if (l1El) l1El.textContent = (funnel.layer1 || "-").toLocaleString();
    }
  } catch (e) { /* ignore overview fail */ }

  try {
    var screenData = await fetchJson("/api/v1/screening/today");
    var sc = screenData.payload && screenData.payload.screening;
    if (sc) {
      var l2El = document.getElementById("funnel-layer2");
      var candEl = document.getElementById("funnel-candidates");
      if (l2El) l2El.textContent = sc.output_count != null ? sc.output_count : "-";
      if (candEl) candEl.textContent = sc.output_count != null ? sc.output_count : "-";

      var tbody = document.getElementById("funnel-candidates-tbody");
      var candidates = sc.candidates;
      if (tbody && Array.isArray(candidates) && candidates.length > 0) {
        tbody.innerHTML = candidates.map(function(c) {
          var score = c.suitability_score != null ? c.suitability_score.toFixed(2) : "-";
          var conf = c.confidence != null ? c.confidence.toFixed(2) : "-";
          return '<tr>'
            + '<td>' + escapeHtml(c.symbol || "") + '</td>'
            + '<td>' + escapeHtml(c.name || "") + '</td>'
            + '<td>' + score + '</td>'
            + '<td>-</td><td>-</td>'
            + '<td>' + score + '</td>'
            + '<td>' + conf + '</td>'
            + '<td><span class="status info">감시중</span></td>'
            + '<td>' + escapeHtml(c.reason || "") + '</td>'
            + '</tr>';
        }).join("");
      } else if (tbody && sc.output_count === 0) {
        tbody.innerHTML = '<tr><td colspan="9" class="muted" style="text-align:center;">오늘 스크리닝 결과 없음 (S4 미실행)</td></tr>';
      }
    }
  } catch (e) {
    var tbody2 = document.getElementById("funnel-candidates-tbody");
    if (tbody2) tbody2.innerHTML = '<tr><td colspan="9" class="muted">불러오기 실패: ' + escapeHtml(e.message) + '</td></tr>';
  }
}
```

`showScreen()` 함수에 추가:
```javascript
if (name === "funnel") {
  loadFunnelData();
}
```

---

## Task 4 — Execution & Risk 실 데이터 연결

### 4-1. page-head에 새로고침 버튼 추가

`screen-risk`의 page-head 안에:
```html
<button class="btn" onclick="loadExecutionRisk()">새로고침</button>
```

### 4-2. 4개 metric 카드에 id 추가

- 당일 손익 `<div class="metric good">+0.12%</div>` → `<div class="metric" id="risk-pnl">-</div>`
- 손실한도는 readonly이므로 유지
- 주문 실행 `<div class="metric">3</div>` → `<div class="metric" id="risk-orders-count">-</div>`, `<div class="muted">오늘 총 주문</div>` 유지
- 주문 차단 `<div class="metric warn">2</div>` → `<div class="metric" id="risk-blocked-count">-</div>` (static "-"으로 초기화)

### 4-3. 주문 실행 로그 테이블 tbody에 id 추가

`<tbody>` → `<tbody id="risk-orders-tbody">`
(기존 mock 데이터 3개 row는 삭제하고 아래 placeholder로 교체)
```html
<tr><td colspan="7" class="muted" style="text-align:center;">새로고침을 눌러 불러오기</td></tr>
```

### 4-4. 주문 차단 로그 카드 내용 교체

기존 `log-list` div의 3개 log-item을 아래로 교체:
```html
<p class="muted" style="font-size:13px;">실시간 차단 로그는 서버 로그에서 확인하세요.<br>KIS System Test → 서버 로그 패널 (필터: "BLOCK" 또는 "차단")</p>
```

### 4-5. JS: `loadExecutionRisk()` 함수 추가

```javascript
async function loadExecutionRisk() {
  try {
    var data = await fetchJson("/api/v1/orders/today");
    var orders = data.payload && data.payload.orders || [];

    var ordersCountEl = document.getElementById("risk-orders-count");
    if (ordersCountEl) ordersCountEl.textContent = orders.length;

    var tbody = document.getElementById("risk-orders-tbody");
    if (tbody) {
      if (orders.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="muted" style="text-align:center;">오늘 주문 없음</td></tr>';
      } else {
        tbody.innerHTML = orders.map(function(ord) {
          var sideLabel = ord.side === "buy" ? "매수" : "매도";
          var timeStr = (ord.created_at || "").split("T")[1] || "";
          if (timeStr.includes(".")) timeStr = timeStr.split(".")[0];
          var statusCls = ord.status === "filled" ? "ok" : ord.status === "failed" ? "danger" : "info";
          var statusLabel = { submitted: "제출됨", filled: "전량체결", failed: "실패", cancelled: "취소" }[ord.status] || ord.status || "-";
          return '<tr>'
            + '<td>' + timeStr + '</td>'
            + '<td>' + escapeHtml((ord.symbol || "") + (ord.name ? " " + ord.name : "")) + '</td>'
            + '<td>' + sideLabel + '</td>'
            + '<td>' + (ord.qty || 0).toLocaleString() + '</td>'
            + '<td>' + (ord.price || 0).toLocaleString() + '</td>'
            + '<td>' + escapeHtml(ord.reason || "-") + '</td>'
            + '<td><span class="status ' + statusCls + '">' + statusLabel + '</span></td>'
            + '</tr>';
        }).join("");
      }
    }
  } catch (e) {
    var tbody2 = document.getElementById("risk-orders-tbody");
    if (tbody2) tbody2.innerHTML = '<tr><td colspan="7" class="muted" style="text-align:center;">불러오기 실패: ' + escapeHtml(e.message) + '</td></tr>';
  }
}
```

`showScreen()` 함수에 추가:
```javascript
if (name === "risk") {
  loadExecutionRisk();
}
```

---

## Task 5 — Review & Audit 실 데이터 연결

### 5-1. 버튼 교체

변경 전:
```html
<button class="btn primary">AI 복기 생성</button>
<button class="btn">CSV 다운로드</button>
```

변경 후:
```html
<button class="btn primary" onclick="runDailySummary()">일일 요약 생성 (S10)</button>
<button class="btn" onclick="loadReviewData()">새로고침</button>
```

### 5-2. 4개 metric 카드 id 추가 및 초기값 변경

- 총 손익: `<div class="metric good">+0.42%</div>` → `<div class="metric" id="review-pnl">-</div>`
- 승률 (여기서는 수익일 비율): `<div class="metric">58%</div>` → `<div class="metric" id="review-winrate">-</div>`, `<div class="muted">7전 4승</div>` → `<div class="muted" id="review-winrate-detail">-</div>`
- 룰 준수율 카드는 제거하고 "매매일수" 카드로 교체: `<div class="card compact"><div class="card-title">매매일수</div><div class="metric" id="review-trade-days">-</div><div class="muted">데이터 있는 날</div></div>`
- 학습 후보 카드는 제거하고 "총 주문수" 카드로 교체: `<div class="card compact"><div class="card-title">총 주문수</div><div class="metric" id="review-total-orders">-</div><div class="muted">전체 집계</div></div>`

### 5-3. AI 복기 요약 영역 교체

기존 3개 natural-card (잘된 점, 개선할 점, 놓친 기회)를 아래로 교체:
```html
<div class="natural-card">
  <h4>가장 최근 거래일 요약</h4>
  <p id="review-latest-summary">-</p>
</div>
<div class="natural-card">
  <h4>시장 톤</h4>
  <p id="review-latest-tone">-</p>
</div>
<div class="natural-card">
  <h4>RulePack</h4>
  <p id="review-latest-rulepack">-</p>
</div>
```

### 5-4. 자동학습 Rule Suggestions 카드 → 최근 거래 이력 카드로 교체 (오른쪽 카드)

기존 자동학습 테이블 카드를 아래로 교체:
```html
<div class="card">
  <div class="card-title" style="display:flex; justify-content:space-between; align-items:center;">
    <span>일별 거래 이력 <span>Statistics 화면에서 상세 확인 가능</span></span>
    <button class="btn" onclick="showScreen('statistics')">Statistics →</button>
  </div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>날짜</th><th>주문</th><th>매수</th><th>매도</th><th>손익</th><th>시장톤</th></tr>
      </thead>
      <tbody id="review-history-tbody">
        <tr><td colspan="6" class="muted">로딩중...</td></tr>
      </tbody>
    </table>
  </div>
</div>
```

### 5-5. Pattern Memory 카드 제거

Pattern Memory 카드 전체(section-gap 포함)를 제거한다.
(실제 데이터가 없고 mock이므로)

### 5-6. JS: `loadReviewData()`, `runDailySummary()` 함수 추가

```javascript
async function loadReviewData() {
  try {
    var data = await fetchJson("/api/v1/trades/history?limit=30");
    var items = data.payload && data.payload.items || [];

    var tradeDays = items.length;
    var totalOrders = 0;
    var profitDays = 0;
    var pnlSum = 0;
    items.forEach(function(item) {
      totalOrders += item.total_orders || 0;
      pnlSum += item.realized_pnl_pct || 0;
      if ((item.realized_pnl_pct || 0) > 0) profitDays++;
    });
    var winrate = tradeDays > 0 ? Math.round(profitDays / tradeDays * 100) : 0;

    function setRV(id, text, cls) {
      var el = document.getElementById(id);
      if (el) { el.textContent = text; if (cls) el.className = "metric " + cls; }
    }

    setRV("review-trade-days", tradeDays + "일");
    setRV("review-total-orders", totalOrders + "건");
    var pnlCls = pnlSum >= 0 ? "good" : "bad";
    setRV("review-pnl", (pnlSum >= 0 ? "+" : "") + pnlSum.toFixed(2) + "%", pnlCls);
    setRV("review-winrate", winrate + "%", winrate >= 50 ? "good" : "warn");
    var wrDetail = document.getElementById("review-winrate-detail");
    if (wrDetail) wrDetail.textContent = profitDays + "수익일 / " + tradeDays + "거래일";

    if (items.length > 0) {
      var latest = items[0];
      var summEl = document.getElementById("review-latest-summary");
      var toneEl = document.getElementById("review-latest-tone");
      var rpEl = document.getElementById("review-latest-rulepack");
      if (summEl) summEl.textContent = latest.trade_date + " · 주문 " + (latest.total_orders || 0) + "건 · 손익 " + (latest.realized_pnl_pct || 0).toFixed(2) + "%";
      if (toneEl) toneEl.textContent = latest.market_tone || "(없음)";
      if (rpEl) rpEl.textContent = latest.rulepack_id || "(없음)";
    }

    var tbody = document.getElementById("review-history-tbody");
    if (tbody) {
      if (items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="muted" style="text-align:center;">거래 이력 없음 (S10 실행 전)</td></tr>';
      } else {
        tbody.innerHTML = items.map(function(item) {
          var pnl = item.realized_pnl_pct || 0;
          var pnlStr = (pnl >= 0 ? "+" : "") + pnl.toFixed(2) + "%";
          return '<tr style="cursor:pointer;" onclick="showScreen(\'statistics\')">'
            + '<td>' + (item.trade_date || "") + '</td>'
            + '<td>' + (item.total_orders || 0) + '</td>'
            + '<td>' + (item.buy_orders || 0) + '</td>'
            + '<td>' + (item.sell_orders || 0) + '</td>'
            + '<td class="' + (pnl >= 0 ? "good" : "bad") + '">' + pnlStr + '</td>'
            + '<td>' + escapeHtml(item.market_tone || "-") + '</td>'
            + '</tr>';
        }).join("");
      }
    }
  } catch (e) {
    var tbody3 = document.getElementById("review-history-tbody");
    if (tbody3) tbody3.innerHTML = '<tr><td colspan="6" class="muted">불러오기 실패: ' + escapeHtml(e.message) + '</td></tr>';
  }
}

async function runDailySummary() {
  if (!confirm("오늘 거래를 집계하고 DB를 백업할까요? (S10 실행)")) return;
  try {
    await fetchJson("/api/v1/trades/run-summary", { method: "POST" });
    alert("일일 요약 생성 완료. 새로고침합니다.");
    loadReviewData();
  } catch (e) {
    alert("실패: " + e.message);
  }
}
```

`showScreen()` 함수에 추가:
```javascript
if (name === "review") {
  loadReviewData();
}
```

---

## Task 6 — Statistics 화면 신규 추가 ⭐ (핵심)

### 6-1. 사이드바 nav 버튼 추가

`<button data-screen="review">Review & Audit <small>learn</small></button>` 바로 다음에:
```html
<button data-screen="statistics">Statistics <small>history</small></button>
```

### 6-2. mobile select에 option 추가

`<option value="review">` 다음에:
```html
<option value="statistics">Statistics</option>
```

### 6-3. 새 섹션 삽입

`</section>` (screen-review 닫힘) 바로 다음, `<section class="screen" id="screen-engine-test">` 바로 앞에 삽입:

```html
<section class="screen" id="screen-statistics">
  <div class="page-head">
    <div>
      <h1 class="page-title">Statistics</h1>
      <p class="page-desc">기간별 거래 이력, 손익, 매매수를 확인합니다. 날짜 행을 클릭하면 해당일 주문·신호 상세를 볼 수 있습니다.</p>
    </div>
    <button class="btn" onclick="loadStatistics()">새로고침</button>
  </div>

  <div style="display:flex; gap:8px; margin-bottom:16px; align-items:center; flex-wrap:wrap;">
    <span style="color:var(--muted); font-size:13px;">기간:</span>
    <button class="btn" id="sf-all" onclick="setStatsFilter('all')">전체</button>
    <button class="btn primary" id="sf-month" onclick="setStatsFilter('month')">이번달</button>
    <button class="btn" id="sf-lastmonth" onclick="setStatsFilter('lastmonth')">지난달</button>
    <input type="date" id="sf-date" style="padding:5px; border-radius:5px; background:var(--panel-2); color:var(--text); border:1px solid var(--line);" onchange="loadStatisticsDetail(this.value)">
  </div>

  <div style="display:grid; grid-template-columns:repeat(5,1fr); gap:12px; margin-bottom:16px;">
    <div class="card compact"><div class="card-title">매매일수</div><div class="metric" id="st-days">-</div><div class="muted">S10 집계 기준</div></div>
    <div class="card compact"><div class="card-title">총 주문수</div><div class="metric" id="st-orders">-</div><div class="muted">전체 기간</div></div>
    <div class="card compact"><div class="card-title">수익일 비율</div><div class="metric" id="st-winrate">-</div><div class="muted" id="st-winrate-detail">-</div></div>
    <div class="card compact"><div class="card-title">누적 손익</div><div class="metric" id="st-pnl">-</div><div class="muted">실현 기준 합산</div></div>
    <div class="card compact"><div class="card-title">일 평균 손익</div><div class="metric" id="st-avg-pnl">-</div><div class="muted">거래일 기준</div></div>
  </div>

  <div class="card">
    <div class="card-title">일별 거래 이력 <span>행 클릭 → 해당일 상세 조회</span></div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>날짜</th><th>주문수</th><th>매수</th><th>매도</th><th>실패</th><th>일 손익</th><th>누적 손익</th><th>시장톤</th><th>상세</th></tr>
        </thead>
        <tbody id="st-history-tbody">
          <tr><td colspan="9" class="muted">로딩중...</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <div class="section-gap"></div>

  <div class="card" id="st-detail-card" style="display:none;">
    <div class="card-title" style="display:flex; justify-content:space-between; align-items:center;">
      <span><strong id="st-detail-date">-</strong> 상세</span>
      <button class="btn" onclick="document.getElementById('st-detail-card').style.display='none'">닫기</button>
    </div>

    <div style="display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:16px;">
      <div class="card compact"><div class="card-title">주문수</div><div class="metric" id="st-d-orders">-</div></div>
      <div class="card compact"><div class="card-title">손익</div><div class="metric" id="st-d-pnl">-</div></div>
      <div class="card compact"><div class="card-title">시장톤</div><div class="metric" id="st-d-tone">-</div></div>
      <div class="card compact"><div class="card-title">RulePack</div><div class="metric" id="st-d-rulepack" style="font-size:13px;">-</div></div>
    </div>

    <div class="card-title" style="margin-top:16px; margin-bottom:8px;">주문 내역</div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>시간</th><th>종목</th><th>구분</th><th>수량</th><th>가격</th><th>사유</th><th>상태</th></tr>
        </thead>
        <tbody id="st-d-orders-tbody">
          <tr><td colspan="7" class="muted">날짜를 선택하세요</td></tr>
        </tbody>
      </table>
    </div>

    <div class="card-title" style="margin-top:16px; margin-bottom:8px;">매수 신호</div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>시간</th><th>종목코드</th><th>종목명</th><th>진입가</th><th>신뢰도</th><th>상태</th></tr>
        </thead>
        <tbody id="st-d-signals-tbody">
          <tr><td colspan="6" class="muted">날짜를 선택하세요</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</section>
```

### 6-4. JS: Statistics 관련 함수들 추가

```javascript
/* ── Statistics ── */
var stAllItems = [];
var stFilter = "month";

function setStatsFilter(filter) {
  stFilter = filter;
  ["all", "month", "lastmonth"].forEach(function(f) {
    var btn = document.getElementById("sf-" + f);
    if (btn) btn.className = "btn" + (f === filter ? " primary" : "");
  });
  renderStatsSummary();
}

function filterStItems(items) {
  if (stFilter === "all") return items;
  var now = new Date();
  var year = now.getFullYear();
  var month = String(now.getMonth() + 1).padStart(2, "0");
  if (stFilter === "month") {
    var prefix = year + "-" + month;
    return items.filter(function(i) { return (i.trade_date || "").startsWith(prefix); });
  }
  if (stFilter === "lastmonth") {
    var lm = now.getMonth() === 0 ? 12 : now.getMonth();
    var ly = now.getMonth() === 0 ? year - 1 : year;
    var lmStr = ly + "-" + String(lm).padStart(2, "0");
    return items.filter(function(i) { return (i.trade_date || "").startsWith(lmStr); });
  }
  return items;
}

async function loadStatistics() {
  try {
    var data = await fetchJson("/api/v1/trades/history?limit=120");
    stAllItems = data.payload && data.payload.items || [];
    renderStatsSummary();
  } catch (e) {
    var tbody = document.getElementById("st-history-tbody");
    if (tbody) tbody.innerHTML = '<tr><td colspan="9" class="muted">불러오기 실패: ' + escapeHtml(e.message) + '</td></tr>';
  }
}

function renderStatsSummary() {
  var items = filterStItems(stAllItems);
  var days = items.length;
  var totalOrders = 0, profitDays = 0, pnlSum = 0;
  items.forEach(function(item) {
    totalOrders += item.total_orders || 0;
    pnlSum += item.realized_pnl_pct || 0;
    if ((item.realized_pnl_pct || 0) > 0) profitDays++;
  });
  var winrate = days > 0 ? Math.round(profitDays / days * 100) : 0;
  var avgPnl = days > 0 ? pnlSum / days : 0;

  function setST(id, text, cls) {
    var el = document.getElementById(id);
    if (el) { el.textContent = text; if (cls) el.className = "metric " + cls; }
  }
  setST("st-days", days + "일");
  setST("st-orders", totalOrders + "건");
  setST("st-winrate", winrate + "%", winrate >= 50 ? "good" : "warn");
  var wd = document.getElementById("st-winrate-detail");
  if (wd) wd.textContent = profitDays + "수익일 / " + days + "거래일";
  setST("st-pnl", (pnlSum >= 0 ? "+" : "") + pnlSum.toFixed(2) + "%", pnlSum >= 0 ? "good" : "bad");
  setST("st-avg-pnl", (avgPnl >= 0 ? "+" : "") + avgPnl.toFixed(2) + "%", avgPnl >= 0 ? "good" : "bad");

  /* 누적 손익 (오래된 날부터 누적) */
  var reversed = items.slice().reverse();
  var cumPnl = 0;
  var cumMap = {};
  reversed.forEach(function(item) {
    cumPnl += item.realized_pnl_pct || 0;
    cumMap[item.trade_date] = cumPnl;
  });

  var tbody = document.getElementById("st-history-tbody");
  if (!tbody) return;
  if (items.length === 0) {
    tbody.innerHTML = '<tr><td colspan="9" class="muted" style="text-align:center;">해당 기간 데이터 없음 (S10을 실행해 집계하세요)</td></tr>';
    return;
  }
  tbody.innerHTML = items.map(function(item) {
    var pnl = item.realized_pnl_pct || 0;
    var cum = cumMap[item.trade_date] || 0;
    var pnlStr = (pnl >= 0 ? "+" : "") + pnl.toFixed(2) + "%";
    var cumStr = (cum >= 0 ? "+" : "") + cum.toFixed(2) + "%";
    return '<tr style="cursor:pointer;" onclick="loadStatisticsDetail(\'' + item.trade_date + '\')">'
      + '<td><strong>' + (item.trade_date || "") + '</strong></td>'
      + '<td>' + (item.total_orders || 0) + '</td>'
      + '<td>' + (item.buy_orders || 0) + '</td>'
      + '<td>' + (item.sell_orders || 0) + '</td>'
      + '<td>' + (item.failed_orders || 0) + '</td>'
      + '<td class="' + (pnl >= 0 ? "good" : "bad") + '">' + pnlStr + '</td>'
      + '<td class="' + (cum >= 0 ? "good" : "bad") + '">' + cumStr + '</td>'
      + '<td>' + escapeHtml(item.market_tone || "-") + '</td>'
      + '<td><button class="btn" onclick="event.stopPropagation(); loadStatisticsDetail(\'' + item.trade_date + '\')">상세</button></td>'
      + '</tr>';
  }).join("");
}

async function loadStatisticsDetail(tradeDate) {
  if (!tradeDate) return;
  var detailCard = document.getElementById("st-detail-card");
  var dateEl = document.getElementById("st-detail-date");
  if (detailCard) detailCard.style.display = "block";
  if (dateEl) dateEl.textContent = tradeDate;
  var sfDate = document.getElementById("sf-date");
  if (sfDate) sfDate.value = tradeDate;

  try {
    var data = await fetchJson("/api/v1/trades/history/" + tradeDate);
    var p = data.payload || {};
    var summary = p.summary || {};
    var orders = p.orders || [];
    var signals = p.signals || [];

    var pnl = summary.realized_pnl_pct || 0;
    var pnlStr = (pnl >= 0 ? "+" : "") + pnl.toFixed(2) + "%";

    function setSD(id, text, cls) {
      var el = document.getElementById(id);
      if (el) { el.textContent = text; if (cls) el.className = "metric " + cls; }
    }
    setSD("st-d-orders", (summary.total_orders || 0) + "건");
    setSD("st-d-pnl", pnlStr, pnl >= 0 ? "good" : "bad");
    setSD("st-d-tone", summary.market_tone || "-");
    setSD("st-d-rulepack", summary.rulepack_id || "-");

    var ordersTbody = document.getElementById("st-d-orders-tbody");
    if (ordersTbody) {
      if (orders.length === 0) {
        ordersTbody.innerHTML = '<tr><td colspan="7" class="muted" style="text-align:center;">주문 없음</td></tr>';
      } else {
        ordersTbody.innerHTML = orders.map(function(ord) {
          var sideLabel = ord.side === "buy" ? "매수" : "매도";
          var timeStr = ((ord.created_at || "").split("T")[1] || "").split(".")[0];
          var statusMap = { submitted: "제출됨", filled: "체결됨", failed: "실패", cancelled: "취소" };
          var statusCls = ord.status === "filled" ? "ok" : ord.status === "failed" ? "danger" : "info";
          return '<tr>'
            + '<td>' + timeStr + '</td>'
            + '<td>' + escapeHtml((ord.symbol || "") + (ord.name ? " " + ord.name : "")) + '</td>'
            + '<td>' + sideLabel + '</td>'
            + '<td>' + (ord.qty || 0).toLocaleString() + '</td>'
            + '<td>' + (ord.price || 0).toLocaleString() + '</td>'
            + '<td>' + escapeHtml(ord.reason || "-") + '</td>'
            + '<td><span class="status ' + statusCls + '">' + (statusMap[ord.status] || ord.status || "-") + '</span></td>'
            + '</tr>';
        }).join("");
      }
    }

    var signalsTbody = document.getElementById("st-d-signals-tbody");
    if (signalsTbody) {
      if (signals.length === 0) {
        signalsTbody.innerHTML = '<tr><td colspan="6" class="muted" style="text-align:center;">신호 없음</td></tr>';
      } else {
        signalsTbody.innerHTML = signals.map(function(sig) {
          var timeStr = ((sig.created_at || sig.time || "").split("T")[1] || sig.time || "").split(".")[0];
          return '<tr>'
            + '<td>' + timeStr + '</td>'
            + '<td>' + escapeHtml(sig.symbol || "") + '</td>'
            + '<td>' + escapeHtml(sig.name || "") + '</td>'
            + '<td>' + (sig.entry_price != null ? sig.entry_price.toLocaleString() : "-") + '</td>'
            + '<td>' + (sig.confidence != null ? sig.confidence.toFixed(2) : "-") + '</td>'
            + '<td>' + escapeHtml(sig.status || "-") + '</td>'
            + '</tr>';
        }).join("");
      }
    }

    if (detailCard) detailCard.scrollIntoView({ behavior: "smooth" });
  } catch (e) {
    var tb = document.getElementById("st-d-orders-tbody");
    if (tb) tb.innerHTML = '<tr><td colspan="7" class="muted">불러오기 실패: ' + escapeHtml(e.message) + '</td></tr>';
  }
}
```

`showScreen()` 함수에 추가:
```javascript
if (name === "statistics") {
  loadStatistics();
}
```

---

## Task 7 — KIS System Test에 S10 추가

### 7-1. S9 카드 다음에 S10 카드 삽입

```html
<!-- S10 -->
<div class="card" id="et-card-s10">
  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
    <div>
      <strong>S10 — 일일 요약 + DB 백업</strong>
      <div style="font-size:12px; color:var(--muted); margin-top:2px;">18:00 KST · trading_orders 집계 → daily_trade_summary + SQLite 백업</div>
    </div>
    <span class="badge" id="et-badge-s10">대기</span>
  </div>
  <button class="btn" style="width:100%; margin-bottom:10px;" onclick="engineTestRun('s10')">▶ 일일 요약 생성</button>
  <pre class="et-result" id="et-result-s10" style="display:none;"></pre>
</div>
```

### 7-2. STEP_URLS에 s10 추가

기존:
```javascript
s9: "/api/v1/orders/liquidate-all"
```
변경 후:
```javascript
s9: "/api/v1/orders/liquidate-all",
s10: "/api/v1/trades/run-summary"
```

### 7-3. engineTestClearAll() 배열에 "s10" 추가

```javascript
["s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9", "s10"].forEach(...)
```

---

## 완료 기준

```bash
python3 -c "from html.parser import HTMLParser; p=HTMLParser(); p.feed(open('backend/static/console.html').read()); print('HTML OK')"

python3 -c "
content = open('backend/static/console.html').read()
checks = [
  ('screen-statistics', 'Statistics 화면'),
  ('st-history-tbody', 'Statistics 이력 테이블'),
  ('st-detail-card', 'Statistics 상세 패널'),
  ('llmProvidersTableBody', 'LLM Provider 테이블'),
  ('funnel-candidates-tbody', 'Funnel 후보 테이블 id'),
  ('risk-orders-tbody', 'Risk 주문 테이블 id'),
  ('review-history-tbody', 'Review 이력 테이블 id'),
  ('et-card-s10', 'S10 테스트 카드'),
  ('loadDataHealth', 'loadDataHealth 함수'),
  ('loadFunnelData', 'loadFunnelData 함수'),
  ('loadStatistics', 'loadStatistics 함수'),
  ('loadStatisticsDetail', 'loadStatisticsDetail 함수'),
]
for id, name in checks:
    found = id in content
    print(f'{name} [{id}]: {\"OK\" if found else \"MISSING\"}')
"
```

OUTBOX 결과는 `docs/agent-comm/OUTBOX_EXECUTOR_ui_overhaul.md` 에 작성하라.
