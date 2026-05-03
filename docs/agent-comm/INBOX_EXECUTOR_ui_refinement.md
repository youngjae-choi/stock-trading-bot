# INBOX_EXECUTOR_ui_refinement — UI 세부 수정

## 작업 파일
`backend/static/console.html` 하나만 수정.

---

## Task 1 — 거래내역 (Trade History) 개선

### 1-A. 메뉴명 영문으로 변경

nav 버튼과 mobile select에서 "거래내역"을 "Trade History"로 변경:
```html
<button data-screen="statistics">Trade History <small>trades</small></button>
<option value="statistics">Trade History</option>
```

### 1-B. 화면 제목 변경
```html
<h1 class="page-title">Trade History</h1>
<p class="page-desc">기간별 전체 주문 내역 (체결·미체결 포함)을 조회합니다.</p>
```

### 1-C. 상단 2개 카드(오늘 체결 내역, 거래중 미체결) 완전 제거

아래 블록 전체를 삭제한다:
```html
<div style="display:flex; gap:16px; margin-bottom:16px; flex-wrap:wrap;">
  <div class="card" style="flex:1; min-width:280px;">
    <div class="card-title" ...>오늘 체결 내역</div>
    ...
    <tbody id="trades-executed-tbody">
  </div>
  <div class="card" style="flex:1; min-width:280px;">
    <div class="card-title" ...>거래중 (미체결)</div>
    ...
    <tbody id="trades-pending-tbody">
  </div>
</div>
```

### 1-D. 기간 필터 위치: 5개 요약 지표 카드 바로 위에 유지

필터 바:
```html
<div style="display:flex; gap:8px; margin-bottom:16px; align-items:center; flex-wrap:wrap;">
  <span style="color:var(--muted); font-size:13px;">기간:</span>
  <button class="btn primary" id="sf-today" onclick="setStatsFilter('today')">오늘</button>
  <button class="btn" id="sf-week" onclick="setStatsFilter('week')">이번주</button>
  <button class="btn" id="sf-month" onclick="setStatsFilter('month')">이번달</button>
  <button class="btn" id="sf-lastmonth" onclick="setStatsFilter('lastmonth')">지난달</button>
  <button class="btn" id="sf-all" onclick="setStatsFilter('all')">전체</button>
  <input type="date" id="sf-date" style="padding:5px; border-radius:5px; background:var(--panel-2); color:var(--text); border:1px solid var(--line);" onchange="loadStatisticsDetail(this.value)">
</div>
```

### 1-E. "일별 거래 이력" 카드를 "전체 주문 내역" 단일 테이블로 교체

기존 `일별 거래 이력` 카드(st-history-tbody)와 상세 카드(st-detail-card)를 제거하고 아래로 교체:

```html
<div class="card">
  <div class="card-title" style="display:flex; justify-content:space-between; align-items:center;">
    <span id="st-table-title">주문 내역</span>
    <button class="btn" onclick="loadAllOrders()">새로고침</button>
  </div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>시간</th>
          <th>종목명</th>
          <th>코드</th>
          <th>구분</th>
          <th>수량</th>
          <th>가격</th>
          <th>상태</th>
        </tr>
      </thead>
      <tbody id="st-orders-tbody">
        <tr><td colspan="7" class="muted" style="text-align:center;">로딩중...</td></tr>
      </tbody>
    </table>
  </div>
</div>
```

### 1-F. `loadAllOrders()` JS 함수 추가

기존 `loadStatistics()` 는 `/api/v1/trades/history`를 호출한다.
주문내역은 `/api/v1/orders/today` (오늘) 또는 `/api/v1/trades/history` (기간별)로 가져온다.

```javascript
async function loadAllOrders() {
  var tbody = document.getElementById('st-orders-tbody');
  var title = document.getElementById('st-table-title');
  if (tbody) tbody.innerHTML = '<tr><td colspan="7" class="muted" style="text-align:center;">로딩중...</td></tr>';

  try {
    var orders = [];
    if (stFilter === 'today') {
      // 오늘 주문: trading_orders 기반
      var r = await apiFetch('/api/v1/orders/today');
      orders = (r && r.ok && r.payload && r.payload.orders) || [];
    } else {
      // 기간별: trading_signals 기반 (체결 + 미체결 포함)
      var limit = (stFilter === 'all') ? 500 : 120;
      var r2 = await apiFetch('/api/v1/trades/history?limit=' + limit);
      // history는 일별 요약이므로 signals도 함께 조회
      var r3 = await apiFetch('/api/v1/decision/signals/today');
      orders = (r3 && r3.ok && r3.payload && r3.payload.signals) || [];
    }

    // 날짜 필터 적용
    var now = new Date();
    var todayStr = now.getFullYear() + '-' + String(now.getMonth()+1).padStart(2,'0') + '-' + String(now.getDate()).padStart(2,'0');
    if (stFilter === 'week') {
      var day = now.getDay();
      var monday = new Date(now);
      monday.setDate(now.getDate() - (day === 0 ? 6 : day - 1));
      var mondayStr = monday.getFullYear() + '-' + String(monday.getMonth()+1).padStart(2,'0') + '-' + String(monday.getDate()).padStart(2,'0');
      orders = orders.filter(function(o) { return (o.trade_date || (o.created_at||'').slice(0,10)) >= mondayStr; });
    }

    var filterLabel = { today:'오늘', week:'이번주', month:'이번달', lastmonth:'지난달', all:'전체' };
    if (title) title.textContent = (filterLabel[stFilter] || '') + ' 주문 내역';

    if (!tbody) return;
    if (orders.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" class="muted" style="text-align:center;">해당 기간 주문 없음</td></tr>';
      return;
    }

    tbody.innerHTML = orders.map(function(o) {
      var side = o.side === 'buy' ? '<span class="status ok">매수</span>' : '<span class="status warn">매도</span>';
      var statusMap = { executed:'체결', filled:'체결', completed:'체결', pending:'대기', submitted:'접수', failed:'실패', cancelled:'취소' };
      var statusCls = (o.status==='executed'||o.status==='filled'||o.status==='completed') ? 'ok' : (o.status==='failed'||o.status==='cancelled') ? 'error' : 'warn';
      var statusLabel = statusMap[o.status] || o.status || '-';
      var timeStr = (o.created_at || '').slice(0,19).replace('T',' ');
      return '<tr>'
        + '<td style="font-size:12px;">' + timeStr + '</td>'
        + '<td>' + (o.name || '-') + '</td>'
        + '<td style="font-size:12px; color:var(--muted);">' + (o.symbol || '-') + '</td>'
        + '<td>' + side + '</td>'
        + '<td>' + (o.qty || '-') + '</td>'
        + '<td>' + (o.price ? Number(o.price).toLocaleString()+'원' : '-') + '</td>'
        + '<td><span class="status ' + statusCls + '">' + statusLabel + '</span></td>'
        + '</tr>';
    }).join('');
  } catch(e) {
    if (tbody) tbody.innerHTML = '<tr><td colspan="7" class="muted" style="text-align:center;">조회 실패: ' + (e.message||'') + '</td></tr>';
  }
}
```

### 1-G. `showScreen('statistics')` 진입 시 `loadAllOrders()` 호출

기존 `loadStatistics()` 호출을 `loadAllOrders()`로 교체 또는 함께 호출.

### 1-H. 5개 요약 지표 카드는 유지

기간 필터 선택 시 요약 수치만 반영하면 되므로 `renderStatsSummary()`는 유지.
단, `stAllItems`가 없을 때 렌더링이 깨지지 않도록 null-safe 유지.

---

## Task 2 — Today Control: 오늘 운영 현황 세로 통합 피드

현재: 타임라인(가로 스크롤)과 최근 이벤트를 나란히 배치한 카드.
목표: 단일 세로 피드 — 스텝별로 예정시간 + 상태 + 관련 이벤트 인라인 표시.

### 2-A. HTML: "오늘 운영 현황" 카드 내부 교체

현재 `.split`이 있던 자리의 카드 내용을:

```html
<div class="card">
  <div class="card-title" style="display:flex; justify-content:space-between; align-items:center;">
    <span>오늘 운영 현황</span>
    <button class="btn" style="font-size:11px; padding:2px 8px;" onclick="loadConsoleData()">새로고침</button>
  </div>
  <div id="today-ops-feed" style="display:flex; flex-direction:column; gap:0;"></div>
</div>
```

### 2-B. JS: `renderTimeline()` 함수를 `renderTodayFeed()` 로 교체

`renderTimeline()` 함수를 찾아 아래로 완전 교체한다.
`todayLogs` 배열은 `overviewData.logs`에서, `timeline` 배열은 `overviewData.timeline`에서 가져온다.

```javascript
function renderTodayFeed() {
  var feed = document.getElementById('today-ops-feed');
  if (!feed || !overviewData) return;

  var steps = overviewData.timeline || [];
  var logs = overviewData.logs || [];

  // 각 스텝에 가장 가까운 로그를 매칭 (스텝명 키워드 기반)
  var keywordMap = {
    'KIS 토큰': ['KIS', '토큰'],
    'AI 시장 톤': ['시장 톤', 'tone='],
    '유니버스 필터': ['유니버스', '필터'],
    'AI 스크리닝': ['스크리닝', '후보'],
    'RulePack': ['RulePack', 'rulepack'],
    '실시간 매매': ['매수 신호', '매매 시작'],
    '중간 리포트': ['중간'],
    '당일매매 청산': ['청산'],
    'AI 복기': ['복기'],
    '일일 리포트': ['리포트'],
  };

  function matchLog(stepName) {
    var keywords = [];
    Object.keys(keywordMap).forEach(function(k) {
      if (stepName.indexOf(k) >= 0) keywords = keywordMap[k];
    });
    if (!keywords.length) return null;
    return logs.find(function(l) {
      return keywords.some(function(kw) { return (l.text||'').indexOf(kw) >= 0; });
    }) || null;
  }

  var statusIcon = { '완료': '✅', '실행중': '🔄', '대기': '○' };
  var statusColor = { '완료': 'var(--green,#22c55e)', '실행중': 'var(--blue,#3b82f6)', '대기': 'var(--muted,#888)' };

  feed.innerHTML = steps.map(function(step) {
    var icon = statusIcon[step.status] || '○';
    var color = statusColor[step.status] || 'var(--muted)';
    var log = matchLog(step.name || '');
    var logHtml = log
      ? '<div style="font-size:11px; color:var(--muted); margin-top:2px; padding-left:4px; border-left:2px solid var(--border,var(--line));">'
        + (log.time ? '<span style="margin-right:6px;">' + log.time + '</span>' : '')
        + escapeHtml(log.text || '') + '</div>'
      : '';
    return '<div style="display:flex; gap:12px; align-items:flex-start; padding:8px 0; border-bottom:1px solid var(--border,var(--line));">'
      + '<div style="font-size:16px; line-height:1; width:20px; text-align:center; flex-shrink:0;">' + icon + '</div>'
      + '<div style="flex:1; min-width:0;">'
        + '<div style="display:flex; gap:8px; align-items:baseline;">'
          + '<span style="font-size:12px; color:var(--muted); min-width:40px;">' + (step.time||'') + '</span>'
          + '<span style="font-size:13px; font-weight:600;">' + escapeHtml(step.name||'') + '</span>'
          + '<span style="font-size:11px; color:' + color + '; margin-left:auto;">' + (step.status||'') + '</span>'
        + '</div>'
        + logHtml
      + '</div>'
    + '</div>';
  }).join('');
}
```

### 2-C. `renderTimeline()` 호출부를 모두 `renderTodayFeed()` 로 교체

파일 전체에서 `renderTimeline()` 호출을 `renderTodayFeed()`로 교체한다.

### 2-D. 기존 `<div class="timeline" id="timeline">` 요소는 제거

Task 1-C에서 삽입한 `id="timeline"` div가 있으면 `id="today-ops-feed"` 방식으로 대체됐으므로 제거.
`id="todayLogs"` div도 더 이상 별도로 렌더링하지 않으므로 제거.

---

## Task 3 — API Logs: 당일 로그만

### 3-A. `loadApiLogs()` 함수에 오늘 날짜 필터 파라미터 추가

```javascript
async function loadApiLogs() {
  var today = new Date();
  var dateStr = today.getFullYear() + '-'
    + String(today.getMonth()+1).padStart(2,'0') + '-'
    + String(today.getDate()).padStart(2,'0');
  var result = await fetchJson('/api/v1/bot/api-logs?date=' + dateStr);
  // 백엔드가 date 파라미터 미지원 시 클라이언트에서 필터
  if (result && result.payload && Array.isArray(result.payload)) {
    result.payload = result.payload.filter(function(e) {
      var ts = e.called_at || e.timestamp || '';
      return ts.startsWith(dateStr);
    });
  }
  renderApiLogs(result.payload);
}
```

---

## Task 4 — Settings 개선

### 4-A. Notification 카드 완전 제거

`screen-settings` 내 아래 카드 전체 삭제:
```html
<div class="card">
  <div class="card-title">Notification</div>
  <div class="natural-card">
    <h4>Telegram</h4>
    ...
  </div>
  <div class="natural-card">
    <h4>권한 정책</h4>
    ...
  </div>
</div>
```

### 4-B. "리스크 & 청산 설정" 카드 명확화

현재 카드에는 두 종류의 수치가 섞여 있어 혼동이 생긴다:
- **포트폴리오 한도**: 일일손실한도, 주간손실한도, 월간손실한도, 최대보유종목, 종목당최대비중, 기본운용모드
- **포지션 청산 기준**: 손절률(stop_loss), 익절률(take_profit), 트레일링 활성기준

아래로 카드 내용을 교체해 두 섹션을 명확하게 구분한다:

```html
<div class="card">
  <div class="card-title">리스크 & 청산 설정 <span>system_settings</span></div>
  <p class="muted" style="margin-bottom:12px; font-size:12px;">이 설정값을 기준으로 RulePack의 위험 한도가 자동 적용됩니다.</p>

  <!-- 포트폴리오 위험 한도 -->
  <div style="font-size:11px; color:var(--muted); font-weight:600; margin-bottom:8px; letter-spacing:0.05em;">포트폴리오 위험 한도 (전체 계좌 기준)</div>
  <div class="form-grid" id="riskSettingsForm">
    <div class="field">
      <label>일일 손실 한도</label>
      <input id="risk-daily-loss" value="-2.0%" readonly>
      <small class="muted">당일 계좌 전체 손익이 이 이하로 떨어지면 신규 매수를 중단</small>
    </div>
    <div class="field">
      <label>주간 손실 한도</label>
      <input id="risk-weekly-loss" value="-5.0%" readonly>
    </div>
    <div class="field">
      <label>월간 손실 한도</label>
      <input id="risk-monthly-loss" value="-8.0%" readonly>
    </div>
    <div class="field">
      <label>최대 보유 종목</label>
      <input id="risk-max-positions" value="5" readonly>
    </div>
    <div class="field">
      <label>종목당 최대 비중</label>
      <input id="risk-position-size" value="10%" readonly>
    </div>
    <div class="field">
      <label>기본 운용 모드</label>
      <select id="risk-mode">
        <option>AUTO</option>
        <option>MONITOR</option>
        <option>HALT</option>
      </select>
    </div>
  </div>

  <hr style="border:none; border-top:1px solid var(--border,var(--line)); margin:16px 0;">

  <!-- 포지션별 청산 기준 -->
  <div style="font-size:11px; color:var(--muted); font-weight:600; margin-bottom:4px; letter-spacing:0.05em;">포지션별 청산 기준 (개별 종목 기준)</div>
  <p class="muted" style="font-size:11px; margin-bottom:10px;">포트폴리오 한도(위)와 별개로, 개별 종목 진입가 대비 손절/익절 기준을 설정합니다. 비워두면 RulePack 값을 사용합니다.</p>
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

### 4-C. `.split` 구조 해제

Notification 카드 제거 후 `.split`이 남아 있으면 제거하고 단일 컬럼 레이아웃으로 변경.

---

## Task 5 — Data & API: Telegram 상태 카드 추가

`screen-data`의 LLM Provider 상태 카드 아래에 추가:

```html
<div class="section-gap"></div>
<div class="card">
  <div class="card-title">알림 연동 상태</div>
  <div class="natural-card" style="display:flex; gap:16px; align-items:center;">
    <div>
      <h4 style="margin:0 0 4px;">Telegram Bot</h4>
      <p style="margin:0;"><span class="status ok" id="telegram-status">확인중</span></p>
    </div>
    <div style="color:var(--muted); font-size:12px;" id="telegram-detail">
      RulePack 생성, 주문 발생, 차단, 긴급정지, 일일 리포트 발송
    </div>
  </div>
</div>
```

`loadDataHealth()` 내에 telegram 상태 갱신 추가 (간단히 overview의 health 데이터로 체크):
```javascript
// loadDataHealth 또는 loadConsoleData 내부에 추가
var telegramEl = document.getElementById('telegram-status');
var telegramDetail = document.getElementById('telegram-detail');
if (telegramEl) {
  telegramEl.textContent = '활성';
  telegramEl.className = 'status ok';
}
```

---

## 완료 기준

```bash
python3 - <<'PY'
c = open('backend/static/console.html').read()
checks = [
  ('Trade History 메뉴명', 'Trade History' in c),
  ('오늘 체결 내역 카드 제거', 'trades-executed-tbody' not in c),
  ('거래중 미체결 카드 제거', 'trades-pending-tbody' not in c),
  ('st-orders-tbody 통합 테이블', 'st-orders-tbody' in c),
  ('loadAllOrders 함수', 'function loadAllOrders' in c),
  ('today-ops-feed', 'today-ops-feed' in c),
  ('renderTodayFeed 함수', 'function renderTodayFeed' in c),
  ('renderTimeline 제거', 'function renderTimeline' not in c),
  ('API Logs 당일 필터', 'dateStr' in c),
  ('Notification 카드 제거', '권한 정책' not in c),
  ('포트폴리오 위험 한도 라벨', '포트폴리오 위험 한도' in c),
  ('포지션별 청산 기준 라벨', '포지션별 청산 기준' in c),
  ('Telegram Data&API 이동', 'telegram-status' in c),
]
for name, check in checks:
  print(f'{"✅" if check else "❌"} {name}')
PY
```

OUTBOX: `docs/agent-comm/OUTBOX_EXECUTOR_ui_refinement.md`
