# INBOX_EXECUTOR_ui_cleanup_batch — UI 정리 배치 작업

## 작업 대상 파일

`backend/static/console.html` 하나만 수정한다.

---

## Task 1 — Today Control 화면 정리

### 1-A. 상단 topbar 4개 status pill 제거

`<div class="top-status">` 블록 전체를 삭제한다.

```html
<div class="top-status">
  <span class="pill"><span class="dot green" id="engineDot"></span><span id="engineText">Auto Engine RUNNING</span></span>
  <span class="pill"><span class="dot blue"></span><span id="phaseText">현재 단계 계산중</span></span>
  <span class="pill"><span class="dot green" id="restDot"></span><span id="restStatusText">KIS REST 확인중</span></span>
  <span class="pill"><span class="dot blue" id="socketDot"></span><span id="socketStatusText">WebSocket 확인중</span></span>
</div>
```

JS에서 `engineDot`, `engineText`, `restDot`, `restStatusText`, `socketDot`, `socketStatusText`, `phaseText` 변수를 참조하는 곳은 **삭제하지 말고** `document.getElementById` 결과가 null이어도 에러 안 나도록 그대로 둔다 (이미 null-safe 패턴이면 그대로).

### 1-B. System Health 카드를 Today Control에서 제거

아래 블록을 `screen-today`에서 삭제한다 (Data & API로 이동, Task 3에서 추가):

```html
<div class="card">
  <div class="card-title">System Health <span>핵심 연결 상태</span></div>
  <div class="grid cols-2">
    ... (kisTokenStatus, rulepackStatus, websocketStatus, riskStatus)
  </div>
</div>
```

이 카드가 `.split` div 안에서 Today's Timeline 카드와 나란히 있으면, `.split` 구조도 함께 해체한다.
즉, Today's Timeline 카드만 단독으로 남긴다.

### 1-C. Today's Timeline + Recent Operation Logs → 하나의 카드로 병합

기존:
- 카드1: `Today's Timeline` (timeline div)
- 카드2: `Recent Operation Logs` (log-list div)

교체할 단일 카드:

```html
<div class="card">
  <div class="card-title">오늘 운영 현황 <span>타임라인 & 최근 이벤트</span></div>
  <div style="display:flex; gap:24px; align-items:flex-start; flex-wrap:wrap;">
    <div style="flex:1; min-width:220px;">
      <div style="font-size:11px; color:var(--muted); font-weight:600; margin-bottom:8px; letter-spacing:0.05em;">타임라인</div>
      <div class="timeline" id="timeline"></div>
    </div>
    <div style="flex:1; min-width:220px;">
      <div style="font-size:11px; color:var(--muted); font-weight:600; margin-bottom:8px; letter-spacing:0.05em;">최근 이벤트</div>
      <div class="log-list" id="todayLogs"></div>
    </div>
  </div>
</div>
```

---

## Task 2 — Statistics → 거래내역 (이름 변경 + 필터 추가 + 메뉴 이동)

### 2-A. 화면 제목 및 설명 변경

```html
<!-- 변경 전 -->
<h1 class="page-title">Statistics</h1>
<p class="page-desc">기간별 거래 이력, 손익, 매매수를 확인합니다...</p>

<!-- 변경 후 -->
<h1 class="page-title">거래내역</h1>
<p class="page-desc">오늘 체결 내역과 진행 중 주문을 실시간으로 확인하고, 기간별 거래 이력을 조회합니다.</p>
```

### 2-B. 기간 필터에 "오늘", "이번주" 추가 + 기본값 변경

현재 필터 버튼 줄:
```html
<button class="btn" id="sf-all" onclick="setStatsFilter('all')">전체</button>
<button class="btn primary" id="sf-month" onclick="setStatsFilter('month')">이번달</button>
<button class="btn" id="sf-lastmonth" onclick="setStatsFilter('lastmonth')">지난달</button>
```

아래로 교체:
```html
<button class="btn primary" id="sf-today" onclick="setStatsFilter('today')">오늘</button>
<button class="btn" id="sf-week" onclick="setStatsFilter('week')">이번주</button>
<button class="btn" id="sf-month" onclick="setStatsFilter('month')">이번달</button>
<button class="btn" id="sf-lastmonth" onclick="setStatsFilter('lastmonth')">지난달</button>
<button class="btn" id="sf-all" onclick="setStatsFilter('all')">전체</button>
```

### 2-C. JS `setStatsFilter` 함수 수정

`setStatsFilter` 함수에서 버튼 id 목록을 아래로 수정:
```javascript
["today", "week", "all", "month", "lastmonth"].forEach(function(f) {
  var btn = document.getElementById("sf-" + f);
  if (btn) btn.className = "btn" + (f === filter ? " primary" : "");
});
```

### 2-D. JS `filterStItems` 함수에 today/week 케이스 추가

```javascript
function filterStItems(items) {
  if (stFilter === "all") return items;
  var now = new Date();
  var year = now.getFullYear();
  var month = String(now.getMonth() + 1).padStart(2, "0");
  var todayStr = year + "-" + month + "-" + String(now.getDate()).padStart(2, "0");
  if (stFilter === "today") {
    return items.filter(function(i) { return (i.trade_date || "") === todayStr; });
  }
  if (stFilter === "week") {
    var day = now.getDay(); // 0=Sun
    var monday = new Date(now);
    monday.setDate(now.getDate() - (day === 0 ? 6 : day - 1));
    var mondayStr = monday.getFullYear() + "-" + String(monday.getMonth()+1).padStart(2,"0") + "-" + String(monday.getDate()).padStart(2,"0");
    return items.filter(function(i) { return (i.trade_date || "") >= mondayStr; });
  }
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
```

### 2-E. `stFilter` 초기값을 `"today"`로 변경

JS에서 `var stFilter` 또는 `let stFilter` 선언을 찾아:
```javascript
var stFilter = "today";  // 기존 "month"에서 변경
```

### 2-F. 화면 상단에 오늘 체결/미체결 섹션 추가

기간 필터 줄 바로 위(page-head 바로 아래)에 삽입:

```html
<!-- 오늘 실시간 주문 현황 -->
<div style="display:flex; gap:16px; margin-bottom:16px; flex-wrap:wrap;">
  <div class="card" style="flex:1; min-width:280px;">
    <div class="card-title" style="display:flex; justify-content:space-between; align-items:center;">
      <span>오늘 체결 내역</span>
      <button class="btn" onclick="loadTodayTrades()">새로고침</button>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>시간</th><th>종목</th><th>구분</th><th>수량</th><th>체결가</th><th>손익률</th></tr>
        </thead>
        <tbody id="trades-executed-tbody">
          <tr><td colspan="6" class="muted" style="text-align:center;">체결 내역 없음</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <div class="card" style="flex:1; min-width:280px;">
    <div class="card-title" style="display:flex; justify-content:space-between; align-items:center;">
      <span>거래중 (미체결)</span>
      <button class="btn" onclick="loadTodayTrades()">새로고침</button>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>시간</th><th>종목</th><th>구분</th><th>수량</th><th>주문가</th><th>상태</th></tr>
        </thead>
        <tbody id="trades-pending-tbody">
          <tr><td colspan="6" class="muted" style="text-align:center;">진행중 주문 없음</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</div>
```

### 2-G. `loadTodayTrades()` JS 함수 추가

```javascript
async function loadTodayTrades() {
  try {
    var r = await apiFetch('/api/v1/orders/today');
    var orders = (r && r.ok && r.payload && r.payload.orders) || [];
    var executed = orders.filter(function(o) { return o.status === 'executed' || o.status === 'filled' || o.status === 'completed'; });
    var pending = orders.filter(function(o) { return o.status === 'pending' || o.status === 'submitted' || o.status === 'processing'; });

    var execTbody = document.getElementById('trades-executed-tbody');
    if (execTbody) {
      execTbody.innerHTML = executed.length === 0
        ? '<tr><td colspan="6" class="muted" style="text-align:center;">오늘 체결 내역 없음</td></tr>'
        : executed.map(function(o) {
          var side = o.side === 'buy' ? '<span class="status ok">매수</span>' : '<span class="status warn">매도</span>';
          var pnl = o.pnl_pct != null ? ((o.pnl_pct >= 0 ? '+' : '') + o.pnl_pct.toFixed(2) + '%') : '-';
          var pnlCls = o.pnl_pct != null ? (o.pnl_pct >= 0 ? 'green' : 'red') : '';
          return '<tr>'
            + '<td>' + (o.created_at || '').slice(11,19) + '</td>'
            + '<td>' + (o.name || '') + '<br><span style="font-size:11px;color:var(--muted);">' + (o.symbol || '') + '</span></td>'
            + '<td>' + side + '</td>'
            + '<td>' + (o.qty || '-') + '</td>'
            + '<td>' + (o.price ? Number(o.price).toLocaleString() + '원' : '-') + '</td>'
            + '<td class="' + pnlCls + '">' + pnl + '</td>'
            + '</tr>';
        }).join('');
    }

    var pendTbody = document.getElementById('trades-pending-tbody');
    if (pendTbody) {
      pendTbody.innerHTML = pending.length === 0
        ? '<tr><td colspan="6" class="muted" style="text-align:center;">진행중 주문 없음</td></tr>'
        : pending.map(function(o) {
          var side = o.side === 'buy' ? '<span class="status ok">매수</span>' : '<span class="status warn">매도</span>';
          var statusCls = o.status === 'pending' ? 'warn' : 'info';
          return '<tr>'
            + '<td>' + (o.created_at || '').slice(11,19) + '</td>'
            + '<td>' + (o.name || '') + '<br><span style="font-size:11px;color:var(--muted);">' + (o.symbol || '') + '</span></td>'
            + '<td>' + side + '</td>'
            + '<td>' + (o.qty || '-') + '</td>'
            + '<td>' + (o.price ? Number(o.price).toLocaleString() + '원' : '-') + '</td>'
            + '<td><span class="status ' + statusCls + '">' + (o.status || '-') + '</span></td>'
            + '</tr>';
        }).join('');
    }
  } catch(e) {}
}
```

### 2-H. `showScreen`에서 "statistics" 진입 시 `loadTodayTrades()` 호출 추가

`showScreen()` 함수 내 `name === "statistics"` 분기에 `loadTodayTrades();` 추가.

### 2-I. 메뉴/select에서 statistics 위치를 3번째로 이동

**사이드바 nav 교체:**

```html
<nav class="nav" id="nav">
  <button class="active" data-screen="today">Today Control <small>main</small></button>
  <button data-screen="trading">Trading Monitor <small>live</small></button>
  <button data-screen="statistics">거래내역 <small>trades</small></button>
  <button data-screen="rulepack">AI RulePack <small>rules</small></button>
  <button data-screen="funnel">Funnel Monitor <small>screening</small></button>
  <button data-screen="review">Review & Audit <small>learn</small></button>
  <button data-screen="data">Data & API <small>health</small></button>
  <button data-screen="api-logs">API Logs <small>admin</small></button>
  <button data-screen="engine-test">KIS System Test <small>test</small></button>
  <button data-screen="settings">Settings <small>admin</small></button>
</nav>
```

**모바일 select 교체:**

```html
<select id="mobileMenu" class="mobile-menu" aria-label="화면 선택">
  <option value="today">Today Control</option>
  <option value="trading">Trading Monitor</option>
  <option value="statistics">거래내역</option>
  <option value="rulepack">AI RulePack</option>
  <option value="funnel">Funnel Monitor</option>
  <option value="review">Review & Audit</option>
  <option value="data">Data & API</option>
  <option value="api-logs">API Logs</option>
  <option value="engine-test">KIS System Test</option>
  <option value="settings">Settings</option>
</select>
```

---

## Task 3 — API Logs 화면 정리

### 3-A. 상단 3개 compact 카드 삭제

아래 블록 전체 삭제:

```html
<div class="grid cols-3">
  <div class="card compact">
    <div class="card-title">최근 집계 <span>count</span></div>
    ...
  </div>
  <div class="card compact">
    <div class="card-title">출처 구분 <span>source</span></div>
    ...
  </div>
  <div class="card compact">
    <div class="card-title">운영 메모 <span>note</span></div>
    ...
  </div>
</div>

<div class="section-gap"></div>
```

`apiLogsMetric`, `apiLogsLastUpdate`, `apiLogsMode`, `apiLogsNote` 관련 JS 참조도 에러 없이 처리되도록 null-safe로 유지 (실제 element가 없으면 그냥 skip).

### 3-B. 호출시간 포맷 변경

`renderApiLogs` 함수 내 `calledAt` 처리 부분을 찾아 포맷을 `YY-MM-DD HH:MM:SS`로 변경:

```javascript
var calledAt = entry.called_at || entry.timestamp || '-';
// 아래로 교체:
var rawTime = entry.called_at || entry.timestamp || '';
var calledAt = '-';
if (rawTime && rawTime.length >= 19) {
  // ISO 8601: 2026-05-03T07:16:57.xxx+00:00 → 26-05-03 07:16:57
  calledAt = rawTime.slice(2, 10) + ' ' + rawTime.slice(11, 19);
} else if (rawTime) {
  calledAt = rawTime;
}
```

---

## Task 4 — Settings 화면: Risk Settings + 포지션 청산 조건 Override 통합

Risk Settings 카드와 포지션 청산 조건 Override 카드를 하나로 합친다.

현재 두 카드 위치: `screen-settings` 내
- Risk Settings: `.split` 내 첫 번째 카드 (일일손실한도, 주간손실한도, 월간손실한도, 최대보유종목, 종목당최대비중, 기본운용모드)
- 포지션 청산 조건 Override: 별도 카드 (exitOverrideSettingsTableBody 테이블)

Risk Settings 카드 아래에 구분선과 함께 포지션 청산 조건 Override 내용을 합친다.
결과 카드:

```html
<div class="card">
  <div class="card-title">리스크 & 청산 설정 <span>system_settings</span></div>
  <p class="muted" style="margin-bottom:12px;">RulePack 생성 시 이 설정값을 기준으로 위험 한도가 자동 적용됩니다.</p>
  <div class="form-grid" id="riskSettingsForm">
    <!-- 기존 Risk Settings form-grid 내용 그대로 -->
  </div>
  <hr style="border:none; border-top:1px solid var(--border,var(--line)); margin:16px 0;">
  <div style="font-size:12px; color:var(--muted); margin-bottom:8px; font-weight:600;">청산 조건 Override (비워두면 RulePack 값 사용)</div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>항목</th><th>현재값</th><th>새 값</th><th>저장</th><th>예시</th></tr>
      </thead>
      <tbody id="exitOverrideSettingsTableBody">
        <tr><td colspan="5" class="muted">설정을 불러오는 중입니다...</td></tr>
      </tbody>
    </table>
  </div>
</div>
```

원래 별도였던 `포지션 청산 조건 Override` 카드는 삭제한다 (내용이 위 통합 카드로 이동).
`.split` 구조 내 Risk Settings 카드가 Notification 카드와 나란히 있었다면, 통합 후에도 Notification 카드는 그대로 `.split` 안에 유지한다. Risk Settings 카드만 위 통합 카드로 교체.

---

## Task 5 — Data & API 화면에 System Health 카드 추가

`screen-data`의 4개 compact 카드 그리드 바로 아래 (`<div class="section-gap"></div>` 이후)에 추가:

```html
<div class="card" style="margin-bottom:16px;">
  <div class="card-title">System Health <span>엔진 & 연결 상태</span></div>
  <div class="grid cols-2">
    <div class="natural-card">
      <h4>Auto Engine</h4>
      <p><span class="status ok" id="kisTokenStatus">확인중</span></p>
      <p class="muted" id="kisTokenDetail">RulePack 적용 상태</p>
    </div>
    <div class="natural-card">
      <h4>RulePack</h4>
      <p><span class="status ok" id="rulepackStatus">확인중</span></p>
      <p class="muted" id="rulepackDetail">오늘 활성 RulePack</p>
    </div>
    <div class="natural-card">
      <h4>WebSocket</h4>
      <p><span class="status ok" id="websocketStatus">확인중</span></p>
      <p class="muted" id="websocketDetail">S4 완료 후 자동 구독</p>
    </div>
    <div class="natural-card">
      <h4>Risk Guard</h4>
      <p><span class="status ok" id="riskStatus">확인중</span></p>
      <p class="muted" id="riskDetail">긴급정지 상태</p>
    </div>
  </div>
</div>
```

이 카드는 `loadDataHealth()` 호출 시 기존 JS가 `kisTokenStatus`, `rulepackStatus`, `websocketStatus`, `riskStatus` id를 갱신하므로 동적으로 동작한다.

---

## 완료 기준

```bash
python3 - <<'PY'
content = open('backend/static/console.html').read()
checks = [
  ('top-status 제거', '<div class="top-status">' not in content),
  ('System Health in screen-data', 'kisTokenStatus' in content),
  ('System Health NOT in screen-today split', True),  # 수동 확인
  ('Timeline+Logs 통합 카드', '오늘 운영 현황' in content),
  ('거래내역 제목', '<h1 class="page-title">거래내역</h1>' in content),
  ('sf-today 버튼', 'id="sf-today"' in content),
  ('sf-week 버튼', 'id="sf-week"' in content),
  ('trades-executed-tbody', 'trades-executed-tbody' in content),
  ('trades-pending-tbody', 'trades-pending-tbody' in content),
  ('loadTodayTrades function', 'function loadTodayTrades' in content),
  ('statistics 3번째 메뉴', True),  # 수동 확인
  ('API Logs 3카드 제거', '최근 집계' not in content),
  ('calledAt YY-MM-DD format', 'rawTime.slice(2, 10)' in content),
  ('리스크 청산 통합 카드', '리스크 & 청산 설정' in content),
  ('포지션 청산 Override 별도 카드 제거', content.count('포지션 청산 조건 Override') <= 1),
  ('System Health Data 카드 추가', 'System Health' in content),
]
for name, check in checks:
  if isinstance(check, bool):
    print(f'{"✅" if check else "❌"} {name}')
  else:
    print(f'{"✅" if check in content else "❌"} {name}')
PY
```

OUTBOX: `docs/agent-comm/OUTBOX_EXECUTOR_ui_cleanup_batch.md`
