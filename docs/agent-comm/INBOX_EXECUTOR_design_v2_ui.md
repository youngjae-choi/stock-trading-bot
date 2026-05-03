# INBOX_EXECUTOR_design_v2_ui

## 목적
Dantabot 설계변경 v2 — console.html 전면 UI 개편.
수정 파일: `backend/static/console.html` 단일 파일.

완료 후 `docs/agent-comm/OUTBOX_EXECUTOR_design_v2_ui.md`에 결과 작성.

---

## 현재 파일 구조 (반드시 먼저 읽을 것)

`backend/static/console.html` 을 읽은 후 작업한다. 3930줄 파일이다.

---

## 1. 메뉴/네비게이션 변경

### 1-1. 좌측 nav 버튼 변경

현재:
```html
<button class="active" data-screen="today">Today Control <small>main</small></button>
<button data-screen="trading">Trading Monitor <small>live</small></button>
<button data-screen="statistics">Trade History <small>trades</small></button>
<button data-screen="rulepack">AI RulePack <small>rules</small></button>
<button data-screen="funnel">Funnel Monitor <small>screening</small></button>
<button data-screen="review">Review & Audit <small>learn</small></button>
<button data-screen="data">Data & API <small>health</small></button>
<button data-screen="api-logs">API Logs <small>admin</small></button>
<button data-screen="engine-test">KIS System Test <small>test</small></button>
<button data-screen="settings">Settings <small>admin</small></button>
```

변경 (api-logs 버튼 제거, rulepack 버튼 텍스트 변경):
```html
<button class="active" data-screen="today">Today Control <small>main</small></button>
<button data-screen="trading">Trading Monitor <small>live</small></button>
<button data-screen="statistics">Trade History <small>trades</small></button>
<button data-screen="rulepack">Daily Plan & RulePack <small>rules</small></button>
<button data-screen="funnel">Funnel Monitor <small>screening</small></button>
<button data-screen="review">Review & Audit <small>learn</small></button>
<button data-screen="data">Data & API <small>health</small></button>
<button data-screen="engine-test">KIS System Test <small>test</small></button>
<button data-screen="settings">Settings <small>admin</small></button>
```

### 1-2. 모바일 select 변경

현재 `<option value="api-logs">API Logs</option>` 제거.
`<option value="rulepack">AI RulePack</option>` → `<option value="rulepack">Daily Plan & RulePack</option>`.

### 1-3. screen-api-logs 섹션

`<section class="screen" id="screen-api-logs">` 전체 블록을 **삭제**한다.

---

## 2. Today Control 화면 (`screen-today`) 변경

### 2-1. 상단 카드 그리드 변경

기존 4개 compact 카드 (`grid cols-4`)를 유지하면서, 그 아래에 새 카드 행 추가:

기존 4카드 행 직후, `<div class="section-gap">` 이전에 아래 삽입:

```html
<div class="grid cols-4" style="margin-top:12px;">
  <div class="card compact">
    <div class="card-title">Base RulePack <span>version</span></div>
    <div class="metric" id="tc-base-rulepack-ver" style="font-size:14px;">-</div>
    <div class="muted" id="tc-base-rulepack-desc">고정 룰팩</div>
  </div>
  <div class="card compact">
    <div class="card-title">Risk Profile Pack <span>version</span></div>
    <div class="metric" id="tc-profile-pack-ver" style="font-size:14px;">-</div>
    <div class="muted" id="tc-profile-pack-desc">4종 프로필</div>
  </div>
  <div class="card compact">
    <div class="card-title">Daily Plan <span>today</span></div>
    <div class="metric" id="tc-daily-plan-id" style="font-size:12px;">-</div>
    <div class="muted" id="tc-daily-plan-status">-</div>
  </div>
  <div class="card compact">
    <div class="card-title">매매 강도 <span>intensity</span></div>
    <div class="metric" id="tc-trading-intensity">-</div>
    <div class="muted" id="tc-theme-spike-limit">THEME_SPIKE 허용 -개</div>
  </div>
</div>
```

### 2-2. Funnel Progress 변경

기존 `div.funnel` 안의 `funnel-step` 목록에, 마지막 단계 이후 아래 추가:

```html
<div class="funnel-step" style="border-top:1px solid var(--border); padding-top:8px; margin-top:8px; width:100%;">
  <div style="display:flex; gap:16px; flex-wrap:wrap; font-size:11px;">
    <span><span style="color:#6cb6ff;">■</span> LOW_VOL: <strong id="tc-low-vol-count">-</strong></span>
    <span><span style="color:#3fb950;">■</span> MID_VOL: <strong id="tc-mid-vol-count">-</strong></span>
    <span><span style="color:#d29922;">■</span> HIGH_VOL: <strong id="tc-high-vol-count">-</strong></span>
    <span><span style="color:#f85149;">■</span> THEME_SPIKE: <strong id="tc-theme-spike-count">-</strong></span>
  </div>
</div>
```

### 2-3. JS: loadConsoleData() 또는 Today Control 로딩 함수에 추가

Daily Plan 상태를 로드하는 코드 추가:
```javascript
async function loadTodayPlanStatus() {
  try {
    const r = await fetch('/api/v1/daily-plan/today');
    const d = await r.json();
    const plan = d.payload || {};
    document.getElementById('tc-daily-plan-id').textContent = plan.id || '미생성';
    document.getElementById('tc-daily-plan-status').textContent = plan.status || '-';
    document.getElementById('tc-trading-intensity').textContent = plan.trading_intensity || '-';
    const overrides = plan.daily_overrides || {};
    document.getElementById('tc-theme-spike-limit').textContent =
      'THEME_SPIKE 허용 ' + (overrides.max_theme_spike_positions ?? '-') + '개';
    // Profile 배정 수 계산
    const assignments = plan.symbol_assignments || [];
    const counts = {LOW_VOL:0, MID_VOL:0, HIGH_VOL:0, THEME_SPIKE:0};
    assignments.forEach(a => { if (counts[a.profile] !== undefined) counts[a.profile]++; });
    document.getElementById('tc-low-vol-count').textContent = counts.LOW_VOL;
    document.getElementById('tc-mid-vol-count').textContent = counts.MID_VOL;
    document.getElementById('tc-high-vol-count').textContent = counts.HIGH_VOL;
    document.getElementById('tc-theme-spike-count').textContent = counts.THEME_SPIKE;
  } catch(e) { /* silent */ }

  try {
    const rb = await fetch('/api/v1/rule/base');
    const db = await rb.json();
    document.getElementById('tc-base-rulepack-ver').textContent = db.payload?.id || '-';
  } catch(e) {}

  try {
    const rp = await fetch('/api/v1/rule/profiles');
    const dp = await rp.json();
    document.getElementById('tc-profile-pack-ver').textContent = dp.payload?.id || '-';
  } catch(e) {}
}
```

`showScreen('today')` 진입 시 또는 `loadConsoleData()` 내에서 `loadTodayPlanStatus()` 호출.

---

## 3. Trading Monitor 화면 (`screen-trading`) 전면 개편

### 3-1. "오늘 매매 조건" 카드 → "오늘 적용 정책"으로 교체

기존 `class="card-title"` 에 "오늘 매매 조건" 텍스트를 찾아 아래로 교체:

```html
<div class="card" style="flex:1; min-width:240px;">
  <div class="card-title">오늘 적용 정책</div>
  <div style="display:flex; flex-direction:column; gap:5px; font-size:12px;" id="tm-policy-list">
    <div style="display:flex; justify-content:space-between; padding:3px 0; border-bottom:1px solid var(--border);">
      <span style="color:var(--muted);">Base RulePack</span>
      <span id="tm-policy-base">-</span>
    </div>
    <div style="display:flex; justify-content:space-between; padding:3px 0; border-bottom:1px solid var(--border);">
      <span style="color:var(--muted);">Risk Profile Pack</span>
      <span id="tm-policy-pack">-</span>
    </div>
    <div style="display:flex; justify-content:space-between; padding:3px 0; border-bottom:1px solid var(--border);">
      <span style="color:var(--muted);">Daily Plan</span>
      <span id="tm-policy-plan">-</span>
    </div>
    <div style="display:flex; justify-content:space-between; padding:3px 0; border-bottom:1px solid var(--border);">
      <span style="color:var(--muted);">고정 익절</span>
      <span style="color:#f85149; font-weight:600;">OFF</span>
    </div>
    <div style="display:flex; justify-content:space-between; padding:3px 0; border-bottom:1px solid var(--border);">
      <span style="color:var(--muted);">청산 방식</span>
      <span>Trailing Stop + 장마감</span>
    </div>
    <div style="display:flex; justify-content:space-between; padding:3px 0; border-bottom:1px solid var(--border);">
      <span style="color:var(--muted);">신규매수 컷오프</span>
      <span id="tm-policy-cutoff">15:10</span>
    </div>
    <div style="display:flex; justify-content:space-between; padding:3px 0;">
      <span style="color:var(--muted);">강제청산 시작</span>
      <span id="tm-policy-force-exit">15:20</span>
    </div>
  </div>
</div>
```

### 3-2. 매수 종목 모니터링 — 완전 교체

기존 `id="tm-buy-list"` 부모 카드 전체를 아래로 교체:

```html
<div class="card" style="flex:1; min-width:300px;">
  <div class="card-title" style="display:flex; justify-content:space-between; align-items:center;">
    <span>매수 대기 종목 모니터링</span>
    <span id="tm-buy-refresh-countdown" style="font-size:11px; color:var(--muted);">-</span>
  </div>
  <p style="font-size:11px; color:var(--muted); margin-bottom:12px;">
    각 종목의 매수 조건 충족률. 클릭하면 조건별 상세 보기. 조건은 Daily Plan에서 동적으로 결정됩니다.
  </p>
  <div id="tm-buy-list" style="display:flex; flex-direction:column; gap:6px;"></div>
</div>
```

### 3-3. 매도 종목 모니터링 (보유 포지션) — 완전 교체

기존 `id="tm-sell-list"` 부모 카드 전체를 아래로 교체:

```html
<div class="card" style="flex:1; min-width:300px;">
  <div class="card-title" style="display:flex; justify-content:space-between; align-items:center;">
    <span>보유 포지션 모니터링</span>
    <span id="tm-sell-refresh-countdown" style="font-size:11px; color:var(--muted);">-</span>
  </div>
  <p style="font-size:11px; color:var(--muted); margin-bottom:12px;">
    초기손절 / 트레일링스탑 / 강제청산 기준 감시. 손절선까지 여유가 작을수록 위험.
  </p>
  <div id="tm-sell-list" style="display:flex; flex-direction:column; gap:6px;"></div>
</div>
```

### 3-4. Trading Monitor JS 함수들 — 교체

기존 `loadTradingMonitor()` 함수를 찾아 아래로 교체:

```javascript
async function loadTradingMonitor() {
  // 오늘 적용 정책 로드
  try {
    const rb = await fetch('/api/v1/rule/base');
    const db = await rb.json();
    document.getElementById('tm-policy-base').textContent = db.payload?.id || '-';
  } catch(e) {}
  try {
    const rp = await fetch('/api/v1/rule/profiles');
    const dp = await rp.json();
    document.getElementById('tm-policy-pack').textContent = dp.payload?.id || '-';
  } catch(e) {}
  try {
    const rdp = await fetch('/api/v1/daily-plan/today');
    const ddp = await rdp.json();
    document.getElementById('tm-policy-plan').textContent = ddp.payload?.id || '미생성';
  } catch(e) {}

  // 매수 대기 후보 로드
  await loadTradingCandidates();
  // 보유 포지션 로드
  await loadTradingPositions();
}

async function loadTradingCandidates() {
  const container = document.getElementById('tm-buy-list');
  try {
    const r = await fetch('/api/v1/trading-monitor/candidates');
    const d = await r.json();
    const candidates = d.payload?.candidates || [];
    if (!candidates.length) {
      container.innerHTML = '<div style="color:var(--muted); text-align:center; padding:20px 0; font-size:13px;">매수 대기 종목 없음</div>';
      return;
    }
    container.innerHTML = candidates.map(c => renderCandidateRow(c)).join('');
  } catch(e) {
    container.innerHTML = '<div style="color:var(--muted); text-align:center; padding:20px 0; font-size:13px;">데이터 로딩 실패</div>';
  }
}

function renderCandidateRow(c) {
  const readiness = c.buy_readiness || {};
  const pct = readiness.overall_pct || 0;
  const metCount = readiness.met_count || 0;
  const totalCount = readiness.total_count || 0;
  const conditions = readiness.conditions || [];

  const barColor = pct >= 70 ? '#3fb950' : pct >= 50 ? '#d29922' : '#f85149';
  const profileColors = {LOW_VOL:'#6cb6ff', MID_VOL:'#3fb950', HIGH_VOL:'#d29922', THEME_SPIKE:'#f85149'};
  const profileColor = profileColors[c.profile] || '#aaa';

  const conditionsHtml = conditions.map(cond => {
    const cColor = cond.met ? '#3fb950' : '#f85149';
    const cIcon = cond.met ? '✓' : '✗';
    const barW = Math.round(cond.score_pct);
    return `
      <tr>
        <td style="padding:3px 6px; font-size:11px; color:var(--muted);">${cond.label}</td>
        <td style="padding:3px 6px; font-size:11px;">${cond.current_value}</td>
        <td style="padding:3px 6px; font-size:11px; color:var(--muted);">${cond.threshold_label}</td>
        <td style="padding:3px 6px; text-align:center; color:${cColor}; font-size:11px;">${cIcon}</td>
        <td style="padding:3px 6px; min-width:80px;">
          <div style="background:var(--bg2); border-radius:3px; height:6px; width:100%; overflow:hidden;">
            <div style="background:${cColor}; height:100%; width:${barW}%; transition:width 0.3s;"></div>
          </div>
          <span style="font-size:9px; color:var(--muted);">${cond.score_pct}%</span>
        </td>
      </tr>`;
  }).join('');

  const rowId = 'cand-' + c.code;
  const detailId = 'cand-detail-' + c.code;

  return `
    <div style="border:1px solid var(--border); border-radius:6px; overflow:hidden;">
      <div id="${rowId}" onclick="toggleCandidateDetail('${c.code}')"
           style="display:flex; align-items:center; gap:10px; padding:8px 10px; cursor:pointer; background:var(--bg2);">
        <div style="min-width:80px;">
          <div style="font-size:13px; font-weight:600;">${c.name}</div>
          <div style="font-size:10px; color:${profileColor}; font-weight:600;">${c.profile}</div>
        </div>
        <div style="flex:1;">
          <div style="display:flex; justify-content:space-between; font-size:10px; color:var(--muted); margin-bottom:2px;">
            <span>매수 준비도</span>
            <span style="font-weight:700; color:${barColor};">${pct}%</span>
          </div>
          <div style="background:var(--bg); border-radius:4px; height:8px; overflow:hidden;">
            <div style="background:${barColor}; height:100%; width:${Math.round(pct)}%; transition:width 0.5s;"></div>
          </div>
        </div>
        <div style="min-width:36px; text-align:center;">
          <div style="font-size:11px; font-weight:700; color:${barColor};">${metCount}/${totalCount}</div>
          <div style="font-size:9px; color:var(--muted);">조건</div>
        </div>
        <div style="font-size:11px; color:${c.ws_subscribed ? '#3fb950' : 'var(--muted)'};">
          ${c.ws_subscribed ? '● WS' : '○ WS'}
        </div>
      </div>
      <div id="${detailId}" style="display:none; padding:8px 10px; background:var(--bg);">
        <table style="width:100%; border-collapse:collapse;">
          <thead>
            <tr style="font-size:10px; color:var(--muted);">
              <th style="text-align:left; padding:2px 6px;">조건</th>
              <th style="text-align:left; padding:2px 6px;">현재값</th>
              <th style="text-align:left; padding:2px 6px;">기준</th>
              <th style="padding:2px 6px;">충족</th>
              <th style="padding:2px 6px;">근접도</th>
            </tr>
          </thead>
          <tbody>${conditionsHtml}</tbody>
        </table>
        <div style="margin-top:8px; font-size:11px; font-weight:600; color:${barColor}; text-align:right;">
          종합 준비도 ${pct}% — ${pct >= 70 ? '매수 가능' : pct >= 50 ? '접근 중' : '조건 미달'}
        </div>
      </div>
    </div>`;
}

function toggleCandidateDetail(code) {
  const detailEl = document.getElementById('cand-detail-' + code);
  if (!detailEl) return;
  detailEl.style.display = detailEl.style.display === 'none' ? 'block' : 'none';
}

async function loadTradingPositions() {
  const container = document.getElementById('tm-sell-list');
  try {
    const r = await fetch('/api/v1/trading-monitor/positions');
    const d = await r.json();
    const positions = d.payload?.positions || [];
    if (!positions.length) {
      container.innerHTML = '<div style="color:var(--muted); text-align:center; padding:20px 0; font-size:13px;">보유 포지션 없음</div>';
      return;
    }
    container.innerHTML = positions.map(p => renderPositionRow(p)).join('');
  } catch(e) {
    container.innerHTML = '<div style="color:var(--muted); text-align:center; padding:20px 0; font-size:13px;">데이터 로딩 실패</div>';
  }
}

function renderPositionRow(p) {
  const entry = p.entry_price || 0;
  const current = p.market_price || entry;
  const pnlPct = entry > 0 ? ((current - entry) / entry * 100) : 0;
  const activeStop = p.active_stop_price || p.stop_loss_price || 0;
  const stopDistPct = current > 0 && activeStop > 0 ? ((current - activeStop) / current * 100) : 0;
  const highSince = p.highest_price_since_entry || entry;
  const trailingActive = p.trailing_active;
  const profile = p.profile_assigned || 'MID_VOL';

  const pnlColor = pnlPct >= 0 ? '#3fb950' : '#f85149';
  const stopColor = stopDistPct < 1.0 ? '#f85149' : stopDistPct < 2.0 ? '#d29922' : '#3fb950';
  const stopBarW = Math.min(Math.max((stopDistPct / 5.0) * 100, 0), 100);
  const profileColors = {LOW_VOL:'#6cb6ff', MID_VOL:'#3fb950', HIGH_VOL:'#d29922', THEME_SPIKE:'#f85149'};
  const profileColor = profileColors[profile] || '#aaa';

  return `
    <div style="border:1px solid var(--border); border-radius:6px; padding:10px 12px; background:var(--bg2);">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
        <div>
          <span style="font-size:13px; font-weight:600;">${p.name || p.symbol}</span>
          <span style="font-size:10px; color:${profileColor}; font-weight:600; margin-left:6px;">${profile}</span>
          ${trailingActive ? '<span style="font-size:10px; background:#1c3a1c; color:#3fb950; border-radius:3px; padding:1px 5px; margin-left:4px;">Trailing ON</span>' : ''}
        </div>
        <div style="font-size:13px; font-weight:700; color:${pnlColor};">${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%</div>
      </div>
      <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:4px; font-size:11px; margin-bottom:8px;">
        <div><span style="color:var(--muted);">진입가</span> ${entry.toLocaleString()}</div>
        <div><span style="color:var(--muted);">현재가</span> ${current.toLocaleString()}</div>
        <div><span style="color:var(--muted);">최고가</span> ${highSince.toLocaleString()}</div>
        <div><span style="color:var(--muted);">손절선</span> <span style="color:${stopColor}; font-weight:600;">${activeStop.toLocaleString()}</span></div>
        <div><span style="color:var(--muted);">수량</span> ${p.qty || 0}주</div>
        <div><span style="color:var(--muted);">수익</span> ${((current - entry) * (p.qty || 0)).toLocaleString()}원</div>
      </div>
      <div>
        <div style="display:flex; justify-content:space-between; font-size:10px; color:var(--muted); margin-bottom:2px;">
          <span>손절선까지 여유</span>
          <span style="color:${stopColor}; font-weight:700;">${stopDistPct.toFixed(2)}%</span>
        </div>
        <div style="background:var(--bg); border-radius:4px; height:6px; overflow:hidden;">
          <div style="background:${stopColor}; height:100%; width:${stopBarW.toFixed(0)}%; transition:width 0.5s;"></div>
        </div>
      </div>
    </div>`;
}
```

`showScreen('trading')` 진입 시 `loadTradingMonitor()` 호출.

---

## 4. Daily Plan & RulePack 화면 (`screen-rulepack`) 전면 교체

기존 `<section class="screen" id="screen-rulepack">` 블록 전체를 아래로 교체:

```html
<section class="screen" id="screen-rulepack">
  <div class="page-head">
    <div>
      <h1 class="page-title">Daily Plan & RulePack</h1>
      <p class="page-desc">오늘 적용되는 Base RulePack, Risk Profile Pack, Daily Trading Plan의 합성 결과를 확인합니다.</p>
    </div>
    <div style="display:flex; gap:8px;">
      <button class="btn" onclick="generateDailyPlan()">Daily Plan 생성</button>
      <button class="btn" onclick="loadDailyPlanScreen()">새로고침</button>
    </div>
  </div>

  <!-- 오늘 요약 카드 4개 -->
  <div class="grid cols-4">
    <div class="card compact">
      <div class="card-title">시장 톤 <span>market tone</span></div>
      <div class="metric" id="dp-market-tone">-</div>
      <div class="muted" id="dp-trading-intensity">매매 강도: -</div>
    </div>
    <div class="card compact">
      <div class="card-title">신규매수 <span>new entry</span></div>
      <div class="metric" id="dp-new-entry">-</div>
      <div class="muted" id="dp-plan-status">Plan 상태: -</div>
    </div>
    <div class="card compact">
      <div class="card-title">종목 배정 <span>assignments</span></div>
      <div class="metric" id="dp-assignments-count">-</div>
      <div class="muted" id="dp-excluded-count">제외: -종목</div>
    </div>
    <div class="card compact">
      <div class="card-title">LLM Provider <span>source</span></div>
      <div class="metric" id="dp-provider" style="font-size:14px;">-</div>
      <div class="muted" id="dp-created-at">-</div>
    </div>
  </div>

  <div class="section-gap"></div>

  <!-- 청산 정책 안내 -->
  <div class="card" style="border-left:3px solid #3fb950;">
    <div class="card-title">청산 조건</div>
    <ul style="margin:0; padding-left:16px; font-size:12px; color:var(--muted); line-height:1.8;">
      <li>고정 익절은 사용하지 않습니다.</li>
      <li>각 종목은 배정된 Risk Profile에 따라 초기 손절선을 설정합니다.</li>
      <li>수익이 기준 이상 발생하면 트레일링 스탑이 활성화됩니다.</li>
      <li>고점 갱신 시 손절선은 상향되며, 손절선은 절대 하향되지 않습니다.</li>
      <li>모든 포지션은 장마감(15:20) 전 강제 청산됩니다.</li>
    </ul>
  </div>

  <div class="section-gap"></div>

  <!-- Risk Profile 4종 요약 -->
  <div class="card">
    <div class="card-title">Risk Profile Pack <span id="dp-profile-pack-id">-</span></div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Profile</th><th>초기손절</th><th>트레일링 활성</th><th>트레일링 손절</th>
            <th>최대비중</th><th>최대보유</th><th>재진입</th>
          </tr>
        </thead>
        <tbody id="dp-profiles-tbody">
          <tr><td colspan="7" class="muted" style="text-align:center;">로딩중</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <div class="section-gap"></div>

  <!-- 종목별 Profile 배정 -->
  <div class="card">
    <div class="card-title">종목별 Profile 배정 <span id="dp-plan-id-badge">-</span></div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>종목코드</th><th>종목명</th><th>배정 Profile</th><th>배정 사유</th></tr>
        </thead>
        <tbody id="dp-assignments-tbody">
          <tr><td colspan="4" class="muted" style="text-align:center;">데이터 없음</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <div class="section-gap"></div>

  <!-- 검증 결과 -->
  <div class="card">
    <div class="card-title">검증 결과</div>
    <div id="dp-validation-list" style="display:flex; flex-direction:column; gap:4px;"></div>
  </div>

  <div class="section-gap"></div>

  <!-- 제외 종목 + LLM 요약 -->
  <div style="display:flex; gap:16px; flex-wrap:wrap;">
    <div class="card" style="flex:1; min-width:200px;">
      <div class="card-title">제외 종목</div>
      <div id="dp-excluded-list" style="font-size:12px; color:var(--muted);">없음</div>
    </div>
    <div class="card" style="flex:2; min-width:280px;">
      <div class="card-title">LLM 분석 요약</div>
      <div id="dp-llm-summary" style="font-size:12px; color:var(--muted); line-height:1.6;">-</div>
    </div>
  </div>

  <div class="section-gap"></div>

  <!-- JSON 원본 보기 -->
  <div class="card">
    <div class="card-title" style="display:flex; justify-content:space-between; align-items:center;">
      <span>원본 Daily Trading Plan JSON</span>
      <button class="btn" style="font-size:11px;" onclick="toggleDpJson()">펼치기/접기</button>
    </div>
    <pre id="dp-raw-json" style="display:none; font-size:11px; overflow:auto; max-height:300px; background:var(--bg2); padding:10px; border-radius:6px;"></pre>
  </div>
</section>
```

Daily Plan & RulePack JS:
```javascript
async function loadDailyPlanScreen() {
  try {
    const r = await fetch('/api/v1/daily-plan/today');
    const d = await r.json();
    const plan = d.payload;
    if (!plan) {
      document.getElementById('dp-market-tone').textContent = '미생성';
      document.getElementById('dp-plan-status').textContent = 'Plan 없음';
      return;
    }

    document.getElementById('dp-market-tone').textContent = plan.market_tone || '-';
    document.getElementById('dp-trading-intensity').textContent = '매매 강도: ' + (plan.trading_intensity || '-');
    document.getElementById('dp-new-entry').textContent = plan.new_entry_allowed ? '허용' : '차단';
    document.getElementById('dp-plan-status').textContent = 'Plan 상태: ' + (plan.status || '-');
    document.getElementById('dp-assignments-count').textContent = (plan.symbol_assignments || []).length + '종목';
    document.getElementById('dp-excluded-count').textContent = '제외: ' + (plan.excluded_symbols || []).length + '종목';
    document.getElementById('dp-provider').textContent = plan.provider || '-';
    document.getElementById('dp-created-at').textContent = (plan.created_at || '').slice(0, 16);
    document.getElementById('dp-plan-id-badge').textContent = plan.id || '';

    // 종목별 배정
    const profileColors = {LOW_VOL:'#6cb6ff', MID_VOL:'#3fb950', HIGH_VOL:'#d29922', THEME_SPIKE:'#f85149'};
    const assignments = plan.symbol_assignments || [];
    const tbody = document.getElementById('dp-assignments-tbody');
    tbody.innerHTML = assignments.length ? assignments.map(a => {
      const pc = profileColors[a.profile] || '#aaa';
      return `<tr>
        <td>${a.code || ''}</td>
        <td>${a.name || ''}</td>
        <td><span style="color:${pc}; font-weight:600;">${a.profile || '-'}</span></td>
        <td style="font-size:11px; color:var(--muted);">${a.reason || ''}</td>
      </tr>`;
    }).join('') : '<tr><td colspan="4" class="muted" style="text-align:center;">배정 없음</td></tr>';

    // 제외 종목
    const excluded = plan.excluded_symbols || [];
    document.getElementById('dp-excluded-list').innerHTML = excluded.length
      ? excluded.map(e => `<div>${e.name || ''} (${e.code || ''}) — ${e.reason || ''}</div>`).join('')
      : '<span>없음</span>';

    // LLM 요약
    document.getElementById('dp-llm-summary').textContent = plan.llm_summary || '-';

    // 검증 결과
    const validation = plan.validation_result || {};
    const validEl = document.getElementById('dp-validation-list');
    const labelMap = {
      schema_valid: 'JSON Schema 검증',
      profiles_exist: 'Risk Profile 존재 검증',
      symbol_assignments_valid: 'Symbol Assignment 검증',
      global_risk_guard_ok: 'Global Risk Guard 검증',
      take_profit_off: '고정 익절 OFF 검증',
      stop_price_increase_only: '손절선 하향 금지 검증',
      force_exit_on: '장마감 강제청산 ON 검증',
      runtime_interpretable: 'Runtime 해석 가능 검증',
    };
    validEl.innerHTML = Object.entries(labelMap).map(([k, label]) => {
      const v = validation[k] || '미검증';
      const pass = v === 'pass';
      return `<div style="display:flex; justify-content:space-between; padding:4px 0; border-bottom:1px solid var(--border); font-size:12px;">
        <span>${label}</span>
        <span style="color:${pass ? '#3fb950' : '#f85149'}; font-weight:600;">${pass ? '✓ PASS' : '✗ ' + v}</span>
      </div>`;
    }).join('');

    // JSON 원본
    document.getElementById('dp-raw-json').textContent = JSON.stringify(plan, null, 2);
  } catch(e) {
    console.error('loadDailyPlanScreen error:', e);
  }

  // Risk Profile Pack
  try {
    const rp = await fetch('/api/v1/rule/profiles');
    const dp = await rp.json();
    const pack = dp.payload || {};
    document.getElementById('dp-profile-pack-id').textContent = pack.id || '';
    const profiles = pack.profiles || {};
    const tbody = document.getElementById('dp-profiles-tbody');
    const profileOrder = ['LOW_VOL', 'MID_VOL', 'HIGH_VOL', 'THEME_SPIKE'];
    const profileColors = {LOW_VOL:'#6cb6ff', MID_VOL:'#3fb950', HIGH_VOL:'#d29922', THEME_SPIKE:'#f85149'};
    tbody.innerHTML = profileOrder.map(name => {
      const p = profiles[name] || {};
      const pc = profileColors[name] || '#aaa';
      return `<tr>
        <td><span style="color:${pc}; font-weight:600;">${name}</span></td>
        <td>${((p.initial_stop_loss || 0) * 100).toFixed(1)}%</td>
        <td>+${((p.trailing_activate_profit || 0) * 100).toFixed(1)}%</td>
        <td>${((p.trailing_stop_rate || 0) * 100).toFixed(1)}%</td>
        <td>${((p.max_position_rate || 0) * 100).toFixed(0)}%</td>
        <td>${p.max_holding_minutes || '-'}분</td>
        <td>${p.reentry_allowed === false ? '불가' : '허용'}</td>
      </tr>`;
    }).join('');
  } catch(e) {}
}

async function generateDailyPlan() {
  const btn = event.target;
  btn.disabled = true;
  btn.textContent = '생성 중...';
  try {
    const r = await fetch('/api/v1/daily-plan/generate', {method:'POST'});
    const d = await r.json();
    if (d.ok) {
      await loadDailyPlanScreen();
      btn.textContent = '생성 완료';
    } else {
      btn.textContent = '실패';
    }
  } catch(e) {
    btn.textContent = '오류';
  }
  setTimeout(() => { btn.disabled = false; btn.textContent = 'Daily Plan 생성'; }, 2000);
}

function toggleDpJson() {
  const el = document.getElementById('dp-raw-json');
  el.style.display = el.style.display === 'none' ? 'block' : 'none';
}
```

`showScreen('rulepack')` 진입 시 `loadDailyPlanScreen()` 호출.

---

## 5. Funnel Monitor 화면 (`screen-funnel`) 변경

### 5-1. 상단 카드에 Profile별 후보 수 추가

기존 Funnel Monitor 카드 그리드 끝에 아래 카드 추가:
```html
<div class="card compact">
  <div class="card-title">Profile 배정 현황</div>
  <div style="font-size:11px; line-height:1.8;">
    <div><span style="color:#6cb6ff;">LOW_VOL</span> <strong id="fn-low-count">-</strong></div>
    <div><span style="color:#3fb950;">MID_VOL</span> <strong id="fn-mid-count">-</strong></div>
    <div><span style="color:#d29922;">HIGH_VOL</span> <strong id="fn-high-count">-</strong></div>
    <div><span style="color:#f85149;">THEME_SPIKE</span> <strong id="fn-spike-count">-</strong></div>
  </div>
</div>
```

### 5-2. 후보 선정 결과 테이블에 컬럼 추가

기존 테이블 헤더에 "배정 Profile", "배정 사유" 컬럼 추가.
후보 데이터 렌더링 시 Daily Plan의 `symbol_assignments`를 조회해 해당 종목의 Profile을 표시.

Funnel Monitor JS 기존 렌더링 함수 내에서 각 종목 행 생성 시:
```javascript
// 기존 후보 테이블 행 렌더링 함수에서 profile 컬럼 추가
// Daily Plan에서 매핑 데이터 가져오기
async function loadFunnelMonitor() {
  // ... 기존 로직 유지 ...
  // 추가: Daily Plan 조회해 profile 매핑 빌드
  let profileMap = {};
  try {
    const rp = await fetch('/api/v1/daily-plan/today');
    const dp = await rp.json();
    const assignments = dp.payload?.symbol_assignments || [];
    assignments.forEach(a => { profileMap[a.code] = {profile: a.profile, reason: a.reason}; });
    // Profile별 카운트
    const counts = {LOW_VOL:0, MID_VOL:0, HIGH_VOL:0, THEME_SPIKE:0};
    assignments.forEach(a => { if (counts[a.profile] !== undefined) counts[a.profile]++; });
    document.getElementById('fn-low-count').textContent = counts.LOW_VOL;
    document.getElementById('fn-mid-count').textContent = counts.MID_VOL;
    document.getElementById('fn-high-count').textContent = counts.HIGH_VOL;
    document.getElementById('fn-spike-count').textContent = counts.THEME_SPIKE;
  } catch(e) {}
  // profileMap을 후보 테이블 렌더링 시 사용
}
```

---

## 6. Trade History 화면 (`screen-statistics`) 변경

### 6-1. Telegram 상태 카드 제거

Trade History 화면 하단에 있는 Telegram 상태 관련 카드/섹션을 찾아 **제거**한다.
(id="telegram-status" 또는 유사 id를 가진 카드)

### 6-2. 주문 내역 테이블 헤더에 컬럼 추가

기존 헤더에 아래 컬럼 추가:
```html
<th>Risk Profile</th>
<th>청산 사유</th>
```

주문 행 렌더링 시 `risk_profile`, `exit_reason` 필드 표시.

---

## 7. Data & API 화면 (`screen-data`) 변경

### 7-1. "Rule System" 섹션 추가

기존 Data & API 화면의 첫 번째 카드 그리드 직전에 아래 카드 추가:

```html
<div class="card">
  <div class="card-title">Rule System</div>
  <div style="display:flex; flex-direction:column; gap:4px; font-size:12px;" id="da-rule-system">
    <div style="display:flex; justify-content:space-between; padding:4px 0; border-bottom:1px solid var(--border);">
      <span style="color:var(--muted);">Base RulePack</span>
      <span id="da-base-id">-</span>
    </div>
    <div style="display:flex; justify-content:space-between; padding:4px 0; border-bottom:1px solid var(--border);">
      <span style="color:var(--muted);">Risk Profile Pack</span>
      <span id="da-profile-id">-</span>
    </div>
    <div style="display:flex; justify-content:space-between; padding:4px 0; border-bottom:1px solid var(--border);">
      <span style="color:var(--muted);">Daily Plan</span>
      <span id="da-plan-id">-</span>
    </div>
    <div style="display:flex; justify-content:space-between; padding:4px 0; border-bottom:1px solid var(--border);">
      <span style="color:var(--muted);">Symbol Assignments</span>
      <span id="da-assignments-n">-개</span>
    </div>
    <div style="display:flex; justify-content:space-between; padding:4px 0; border-bottom:1px solid var(--border);">
      <span style="color:var(--muted);">고정 익절</span>
      <span style="color:#f85149; font-weight:600;">OFF</span>
    </div>
    <div style="display:flex; justify-content:space-between; padding:4px 0;">
      <span style="color:var(--muted);">트레일링 청산</span>
      <span style="color:#3fb950; font-weight:600;">ON</span>
    </div>
  </div>
</div>
```

### 7-2. Telegram 상태 섹션 추가 (Trade History에서 이동)

Data & API 화면의 "알림 연동 상태" 또는 "LLM Provider 상태" 카드 이후에 Telegram 상태 카드 추가:

```html
<div class="card compact" id="telegram-status">
  <div class="card-title">Telegram 알림 연동</div>
  <div class="metric" id="da-telegram-status" style="font-size:14px;">-</div>
  <div class="muted" id="da-telegram-detail">상태 확인 중</div>
</div>
```

### 7-3. API 호출 로그 섹션 추가

Data & API 화면 마지막에 아래 섹션 추가:

```html
<div class="section-gap"></div>
<div class="card">
  <div class="card-title" style="display:flex; justify-content:space-between; align-items:center;">
    <span>API 호출 로그 <span style="font-size:10px; font-weight:400;">(당일)</span></span>
    <button class="btn" style="font-size:11px;" onclick="loadDataApiLogs()">새로고침</button>
  </div>
  <div class="table-wrap" style="max-height:300px; overflow-y:auto;">
    <table>
      <thead>
        <tr><th>시간</th><th>메서드</th><th>경로</th><th>상태</th><th>응답시간</th></tr>
      </thead>
      <tbody id="da-api-logs-tbody">
        <tr><td colspan="5" class="muted" style="text-align:center;">로딩중</td></tr>
      </tbody>
    </table>
  </div>
</div>
```

API 로그 로딩 JS:
```javascript
async function loadDataApiLogs() {
  const tbody = document.getElementById('da-api-logs-tbody');
  if (!tbody) return;
  try {
    const today = new Date().toISOString().slice(0,10);
    const r = await fetch('/api/v1/logs/api?date=' + today);
    const d = await r.json();
    const logs = d.payload || d.logs || [];
    const todayLogs = logs.filter(l => {
      const ts = l.called_at || l.timestamp || '';
      return ts.startsWith(today);
    });
    if (!todayLogs.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="muted" style="text-align:center;">오늘 로그 없음</td></tr>';
      return;
    }
    tbody.innerHTML = todayLogs.slice(0, 100).map(l => {
      const ts = (l.called_at || l.timestamp || '').slice(11, 19);
      const status = l.status_code || l.status || '-';
      const statusColor = status >= 200 && status < 300 ? '#3fb950' : '#f85149';
      return `<tr>
        <td style="font-size:11px;">${ts}</td>
        <td style="font-size:11px;">${l.method || '-'}</td>
        <td style="font-size:11px; max-width:200px; overflow:hidden; text-overflow:ellipsis;">${l.path || l.endpoint || '-'}</td>
        <td style="color:${statusColor}; font-size:11px;">${status}</td>
        <td style="font-size:11px;">${l.duration_ms || l.elapsed_ms || '-'}ms</td>
      </tr>`;
    }).join('');
  } catch(e) {
    tbody.innerHTML = '<tr><td colspan="5" class="muted" style="text-align:center;">로그 조회 실패</td></tr>';
  }
}
```

Data & API JS 로딩 함수에서 Rule System 로드 추가:
```javascript
async function loadDataAndApi() {
  // 기존 로직 유지
  // 추가
  try {
    const rb = await fetch('/api/v1/rule/base');
    const db = await rb.json();
    document.getElementById('da-base-id').textContent = db.payload?.id || '-';
  } catch(e) {}
  try {
    const rp = await fetch('/api/v1/rule/profiles');
    const dp = await rp.json();
    document.getElementById('da-profile-id').textContent = dp.payload?.id || '-';
  } catch(e) {}
  try {
    const rdp = await fetch('/api/v1/daily-plan/today');
    const ddp = await rdp.json();
    const plan = ddp.payload || {};
    document.getElementById('da-plan-id').textContent = plan.id || '미생성';
    document.getElementById('da-assignments-n').textContent = (plan.symbol_assignments || []).length + '개';
  } catch(e) {}
  // Telegram 상태
  try {
    const da = document.getElementById('da-telegram-status');
    const dd = document.getElementById('da-telegram-detail');
    if (da) da.textContent = '활성';
    if (dd) dd.textContent = 'Telegram Bot 연동';
  } catch(e) {}
  // API 로그
  await loadDataApiLogs();
}
```

`showScreen('data')` 진입 시 `loadDataAndApi()` 호출.

---

## 8. KIS System Test 화면 (`screen-engine-test`) 변경

아래 텍스트를 파일 전체에서 찾아 교체 (대소문자 구분 없이):

| 기존 | 변경 |
|------|------|
| `S5 - RulePack 자동 생성` | `S5 - Daily Trading Plan 생성` |
| `08:45 KST - LLM → rulepacks (자동 활성화)` | `08:45 KST - LLM → daily_trading_plan (종목별 Profile 배정)` |
| `09:00 KST - WS 연결 + RulePack 조건 감시` | `09:00 KST - WS 연결 + Base RulePack + Risk Profile + Daily Plan 조건 감시` |
| `장중 · WS tick → 손절/익절 감시` | `장중 · WS tick → 초기손절/트레일링스탑/강제청산 감시` |
| `RulePack 자동 생성 실행` (버튼) | `Daily Plan 생성 실행` |

버튼 onclick도 `generateDailyPlan()` 또는 `/api/v1/daily-plan/generate` POST 호출로 변경.

추가 테스트 버튼 삽입 (기존 S5 버튼 근처):
```html
<button class="btn" onclick="testRiskProfilePack()">Risk Profile Pack 검증</button>
<button class="btn" onclick="testDailyPlanValidate()">Daily Plan 검증</button>
<button class="btn" onclick="testRuleComposition()">Rule Composition 미리보기</button>
```

JS:
```javascript
async function testRiskProfilePack() {
  const r = await fetch('/api/v1/rule/profiles');
  const d = await r.json();
  alert('Risk Profile Pack:\n' + JSON.stringify(d.payload?.profiles ? Object.keys(d.payload.profiles) : 'N/A', null, 2));
}
async function testDailyPlanValidate() {
  const r = await fetch('/api/v1/daily-plan/validate', {method:'POST'});
  const d = await r.json();
  alert('Daily Plan 검증:\n' + JSON.stringify(d.payload?.validation || d, null, 2));
}
async function testRuleComposition() {
  const code = prompt('종목코드를 입력하세요 (예: 005930)');
  if (!code) return;
  const r = await fetch('/api/v1/rule/composition/' + code);
  const d = await r.json();
  alert('Rule Composition:\n' + JSON.stringify(d.payload, null, 2));
}
```

---

## 9. Settings 화면 (`screen-settings`) 변경

### 9-1. take_profit 항목 제거/비활성화

`take_profit` 또는 `익절률`이 포함된 input/label을 찾아:
- input은 disabled + value="OFF" 로 표시
- 또는 완전히 제거
- label 텍스트에 `(사용 안 함)` 추가

### 9-2. Default Exit Policy 섹션 추가

Settings 화면에 기존 "리스크 & 청산 설정" 카드 아래에 삽입:

```html
<div class="card">
  <div class="card-title">Default Exit Policy</div>
  <div style="display:flex; flex-direction:column; gap:10px; font-size:12px;">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <span>고정 익절 사용</span>
      <span style="color:#f85149; font-weight:600;">OFF (고정)</span>
    </div>
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <span>초기 손절</span>
      <span style="color:#3fb950; font-weight:600;">ON</span>
    </div>
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <span>트레일링 스탑</span>
      <span style="color:#3fb950; font-weight:600;">ON</span>
    </div>
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <span>손절선 하향 금지</span>
      <span style="color:#3fb950; font-weight:600;">ON (고정)</span>
    </div>
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <span>장마감 강제청산</span>
      <span style="color:#3fb950; font-weight:600;">ON (고정)</span>
    </div>
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <label>신규매수 금지 시간</label>
      <input type="text" value="15:10" style="width:80px; text-align:center;" id="setting-cutoff-time">
    </div>
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <label>강제청산 시작 시간</label>
      <input type="text" value="15:20" style="width:80px; text-align:center;" id="setting-force-exit-time">
    </div>
  </div>
</div>
```

### 9-3. Risk Profile Pack 관리 UI 추가

```html
<div class="card">
  <div class="card-title" style="display:flex; justify-content:space-between; align-items:center;">
    <span>Risk Profile Pack <span id="settings-profile-ver" style="font-size:10px; color:var(--muted);"></span></span>
    <button class="btn" onclick="saveRiskProfilePack()">저장 (새 버전 생성)</button>
  </div>
  <p style="font-size:11px; color:var(--muted); margin-bottom:10px;">
    저장 시 새 버전이 자동 생성됩니다. 기존 버전 이력은 보존됩니다.
  </p>
  <div class="table-wrap">
    <table id="settings-profiles-table">
      <thead>
        <tr>
          <th>Profile</th>
          <th>초기손절(%)</th>
          <th>트레일링 활성(%)</th>
          <th>트레일링 손절(%)</th>
          <th>최대비중(%)</th>
          <th>최대보유(분)</th>
          <th>재진입</th>
        </tr>
      </thead>
      <tbody id="settings-profiles-tbody">
        <tr><td colspan="7" class="muted" style="text-align:center;">로딩중</td></tr>
      </tbody>
    </table>
  </div>
</div>
```

Settings Profile Pack JS:
```javascript
let _settingsProfileData = {};

async function loadSettingsProfiles() {
  try {
    const r = await fetch('/api/v1/rule/profiles');
    const d = await r.json();
    const pack = d.payload || {};
    document.getElementById('settings-profile-ver').textContent = pack.id || '';
    _settingsProfileData = JSON.parse(JSON.stringify(pack.profiles || {}));
    renderSettingsProfilesTable(_settingsProfileData);
  } catch(e) {}
}

function renderSettingsProfilesTable(profiles) {
  const profileOrder = ['LOW_VOL', 'MID_VOL', 'HIGH_VOL', 'THEME_SPIKE'];
  const tbody = document.getElementById('settings-profiles-tbody');
  tbody.innerHTML = profileOrder.map(name => {
    const p = profiles[name] || {};
    return `<tr>
      <td style="font-weight:600;">${name}</td>
      <td><input type="number" step="0.1" value="${((p.initial_stop_loss||0)*100).toFixed(1)}" 
           onchange="_settingsProfileData['${name}'].initial_stop_loss=parseFloat(this.value)/100"
           style="width:70px; text-align:center;"></td>
      <td><input type="number" step="0.1" value="${((p.trailing_activate_profit||0)*100).toFixed(1)}"
           onchange="_settingsProfileData['${name}'].trailing_activate_profit=parseFloat(this.value)/100"
           style="width:70px; text-align:center;"></td>
      <td><input type="number" step="0.1" value="${((p.trailing_stop_rate||0)*100).toFixed(1)}"
           onchange="_settingsProfileData['${name}'].trailing_stop_rate=parseFloat(this.value)/100"
           style="width:70px; text-align:center;"></td>
      <td><input type="number" step="1" value="${((p.max_position_rate||0)*100).toFixed(0)}"
           onchange="_settingsProfileData['${name}'].max_position_rate=parseFloat(this.value)/100"
           style="width:60px; text-align:center;"></td>
      <td><input type="number" step="10" value="${p.max_holding_minutes||180}"
           onchange="_settingsProfileData['${name}'].max_holding_minutes=parseInt(this.value)"
           style="width:60px; text-align:center;"></td>
      <td><select onchange="_settingsProfileData['${name}'].reentry_allowed=this.value==='true'" style="font-size:11px;">
           <option value="true" ${p.reentry_allowed!==false?'selected':''}>허용</option>
           <option value="false" ${p.reentry_allowed===false?'selected':''}>불가</option>
         </select></td>
    </tr>`;
  }).join('');
}

async function saveRiskProfilePack() {
  if (!confirm('저장하면 새 Profile Pack 버전이 생성됩니다. 계속하시겠습니까?')) return;
  try {
    const r = await fetch('/api/v1/rule/profiles', {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({profiles: _settingsProfileData}),
    });
    const d = await r.json();
    if (d.ok) {
      alert('저장 완료: ' + d.payload.id);
      await loadSettingsProfiles();
    } else {
      alert('저장 실패: ' + JSON.stringify(d));
    }
  } catch(e) {
    alert('저장 오류: ' + e.message);
  }
}
```

`showScreen('settings')` 진입 시 `loadSettingsProfiles()` 호출.

---

## 10. Review & Audit 화면 변경

기존 시장 톤/RulePack 요약 카드 이후에 Profile별 성과 카드 추가:

```html
<div class="card">
  <div class="card-title">Risk Profile별 성과</div>
  <div class="grid cols-4" id="review-profile-pnl">
    <div class="card compact">
      <div class="card-title">LOW_VOL <span style="color:#6cb6ff;">■</span></div>
      <div class="metric" id="review-pnl-low">-</div>
      <div class="muted" id="review-cnt-low">0거래</div>
    </div>
    <div class="card compact">
      <div class="card-title">MID_VOL <span style="color:#3fb950;">■</span></div>
      <div class="metric" id="review-pnl-mid">-</div>
      <div class="muted" id="review-cnt-mid">0거래</div>
    </div>
    <div class="card compact">
      <div class="card-title">HIGH_VOL <span style="color:#d29922;">■</span></div>
      <div class="metric" id="review-pnl-high">-</div>
      <div class="muted" id="review-cnt-high">0거래</div>
    </div>
    <div class="card compact">
      <div class="card-title">THEME_SPIKE <span style="color:#f85149;">■</span></div>
      <div class="metric" id="review-pnl-spike">-</div>
      <div class="muted" id="review-cnt-spike">0거래</div>
    </div>
  </div>
</div>
```

기존 Review & Audit JS 로딩 함수 끝에 아래 추가 (orders/fills 테이블에서 profile별 집계):
```javascript
// Profile별 성과 집계 (orders/fills에 risk_profile 컬럼 추가 후 사용 가능)
// 현재는 placeholder 표시
['low', 'mid', 'high', 'spike'].forEach(k => {
  const el = document.getElementById('review-pnl-' + k);
  if (el) el.textContent = '-';
});
```

---

## 11. 공통 확인사항

1. **기존 JS 함수 유지**: `loadConsoleData()`, `loadAccountBalance()`, `loadTodayOrders()`, `toggleDecisionEngine()`, `showScreen()` 등 기존 함수는 변경하지 않는다.
2. **graceful fallback**: 새 API(`/api/v1/daily-plan/`, `/api/v1/rule/`, `/api/v1/trading-monitor/`) 호출 실패 시 빈 상태를 표시하고 오류로 중단되지 않는다.
3. **style 일관성**: 기존 CSS 변수(`var(--bg)`, `var(--muted)`, `var(--border)`) 사용. 외부 라이브러리 추가 금지.

---

## 검증

```bash
node -e "
const fs = require('fs');
const code = fs.readFileSync('backend/static/console.html', 'utf8');
// 스크립트 블록 추출
const scripts = code.match(/<script[\s\S]*?<\/script>/gi) || [];
let allOk = true;
scripts.forEach((s, i) => {
  const js = s.replace(/<script[^>]*>/,'').replace(/<\/script>/,'');
  try { new Function(js); } catch(e) { allOk = false; console.log('Script block', i, 'error:', e.message); }
});
console.log(allOk ? 'PASS: JS syntax ok' : 'FAIL: JS errors found');
// 핵심 id 존재 확인
const ids = ['tc-base-rulepack-ver','tc-profile-pack-ver','tc-daily-plan-id','dp-profiles-tbody',
              'dp-assignments-tbody','dp-validation-list','da-rule-system','da-api-logs-tbody',
              'settings-profiles-tbody','tm-buy-list','tm-sell-list'];
ids.forEach(id => {
  if (!code.includes('id=\"' + id + '\"')) console.log('MISSING id:', id);
  else console.log('OK id:', id);
});
// api-logs 메뉴 없어야 함
console.log(code.includes('data-screen=\"api-logs\"') ? 'FAIL: api-logs nav still exists' : 'OK: api-logs nav removed');
// Daily Plan & RulePack 메뉴 있어야 함
console.log(code.includes('Daily Plan & RulePack') ? 'OK: menu renamed' : 'FAIL: menu not renamed');
"
```

---

## 완료 기준

- [ ] API Logs 메뉴 버튼 제거, screen-api-logs 섹션 제거
- [ ] `AI RulePack` → `Daily Plan & RulePack` (메뉴, 화면 제목)
- [ ] Today Control: RulePack/Profile/Plan 버전 카드 + Profile 배정 수
- [ ] Trading Monitor: "오늘 적용 정책" + 매수 준비도 시각화 (동적 조건, 클릭 확장) + 보유 포지션 trailing 상태
- [ ] Daily Plan & RulePack 화면 전면 재구성 (8섹션)
- [ ] Funnel Monitor: Profile 배정 표시
- [ ] Trade History: Telegram 카드 제거
- [ ] Data & API: Rule System 섹션 + Telegram 섹션 + API 로그 섹션
- [ ] KIS System Test: S5/S6/S8 문구 변경 + 추가 테스트 버튼
- [ ] Settings: take_profit 비활성화 + Default Exit Policy + Risk Profile Pack 편집 UI
- [ ] Review & Audit: Profile별 성과 카드
- [ ] JS syntax 검증 통과
