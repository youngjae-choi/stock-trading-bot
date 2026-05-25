# INBOX: Gemini — 화면 재배치 프론트엔드 구현

**우선순위:** HIGH  
**담당:** Gemini (Frontend Agent)  
**작성:** Sisyphus 2026-05-23

---

## 목표

4개 화면 수정: Daily Plan, Settings, Daily Results, Trade Review

---

## 1. Daily Plan (`screen-rulepack`) — 이름 복원 + 추론 체인

### 1-A. 라벨 복원
- 사이드바 버튼: `매매 계획 <small>plan & regime</small>` → `Daily Plan <small>plan & regime</small>`
- 화면 제목: `<h1>매매 계획</h1>` → `<h1>Daily Plan</h1>`
- 모바일 select: `<option value="rulepack">매매 계획</option>` → `Daily Plan`
- 하단 탭바: aria-label `매매 계획` → `Daily Plan`

### 1-B. 레짐 분석 섹션 제거
`#dp-regime-analytics-section` 전체 블록 삭제.  
`console-navigation.js` 의 rulepack 블록에서 `loadRegimeAnalyticsScreen()` 호출 제거.

### 1-C. "오늘의 Regime Set" 카드에 추론 체인 추가

기존 `#dp-regime-set-card` 카드 내부에 추론 체인 시각화 추가.
카드 아랫부분에 아래 HTML 삽입 (JS에서 동적으로 채움):

```html
<!-- 추론 체인 -->
<div id="dp-set-chain" style="display:flex; gap:0; align-items:stretch; margin-top:12px; flex-wrap:wrap;">
  <!-- JS가 채움: 아침 브리핑 → 레짐 판단 → SET 선택 → 적용 설정 -->
</div>
```

`console-daily-plan.js` 의 레짐 SET 로드 블록에서, Set 카드 렌더 후 추론 체인도 렌더:

```javascript
// 추론 체인 렌더
var chainEl = document.getElementById('dp-set-chain');
if (chainEl && app) {
  var regimeColors = {risk_on:'#3fb950', neutral:'#8b9bb4', risk_off:'#f85149', volatile:'#d29922'};
  var regimeLabels = {risk_on:'Risk On', neutral:'중립', risk_off:'Risk Off', volatile:'변동성'};
  var rLabel = regimeLabels[app.regime_label] || app.regime_label || '-';
  var rColor = regimeColors[app.regime_label] || '#8b9bb4';
  
  var steps = [
    {
      icon: '🌅',
      title: '아침 브리핑',
      lines: [
        app.vix_value != null ? 'VIX ' + app.vix_value.toFixed(1) : null,
        app.kospi_change_pct != null ? 'KOSPI ' + (app.kospi_change_pct >= 0 ? '+' : '') + app.kospi_change_pct.toFixed(2) + '%' : null
      ].filter(Boolean)
    },
    {
      icon: '📊',
      title: '레짐 판단',
      lines: ['<span style="color:' + rColor + '; font-weight:700;">' + rLabel + '</span>'],
      color: rColor
    },
    {
      icon: '🎯',
      title: 'SET 선택',
      lines: [
        '<span style="font-weight:600;">' + escapeHtml(app.set_name || '-') + '</span>',
        app.is_prebuilt ? '<span style="font-size:10px; background:#d29922; color:#000; border-radius:3px; padding:1px 5px;">예측 SET</span>' : ''
      ].filter(Boolean)
    },
    {
      icon: '⚙️',
      title: '적용 설정',
      lines: (function() {
        var s = app.applied_settings || {};
        var r = [];
        if (s.max_positions != null) r.push('포지션 최대 ' + s.max_positions + '개');
        if (s.stop_loss_rate != null) r.push('손절 ' + (s.stop_loss_rate * 100).toFixed(1) + '%');
        if (s.take_profit_rate != null) r.push('익절 +' + (s.take_profit_rate * 100).toFixed(1) + '%');
        return r;
      })()
    }
  ];
  
  chainEl.innerHTML = steps.map(function(step, i) {
    var arrow = i < steps.length - 1
      ? '<div style="display:flex; align-items:center; padding:0 4px; color:var(--muted); font-size:16px;">→</div>'
      : '';
    return '<div style="flex:1; min-width:120px; background:var(--bg2); border-radius:8px; padding:10px 12px; font-size:12px;">'
      + '<div style="font-size:10px; color:var(--muted); margin-bottom:4px;">' + step.icon + ' ' + step.title + '</div>'
      + step.lines.map(function(l) { return '<div>' + l + '</div>'; }).join('')
      + '</div>' + arrow;
  }).join('');
}
```

---

## 2. Settings (`screen-settings`) — Regime SET 관리 섹션 추가

Settings 화면 (`screen-settings`) 맨 아래에 새 카드 추가:

```html
<div class="section-gap"></div>

<div class="card" id="regime-sets-card">
  <div class="card-title" style="display:flex; justify-content:space-between; align-items:center;">
    <span>Regime SET 관리 <span style="font-size:11px; color:var(--muted); font-weight:400;">시장 상황별 매매 파라미터</span></span>
    <button type="button" class="btn" data-action="loadRegimeSets">새로고침</button>
  </div>
  <p class="muted" style="font-size:12px; margin-bottom:12px;">
    SET을 클릭하면 설정을 확인하고 수정할 수 있습니다. 시스템은 매일 아침 브리핑 결과로 최적 SET을 자동 선택하며, 성과에 따라 파라미터를 미세 조정합니다.
  </p>
  <div id="regime-sets-list">
    <div class="muted" style="text-align:center; padding:20px;">로딩 중...</div>
  </div>
</div>
```

`backend/static/js/screens/console-settings.js` 파일에 아래 함수 추가:

```javascript
async function loadRegimeSets() {
  var container = document.getElementById('regime-sets-list');
  if (!container) return;
  try {
    var r = await fetch('/api/v1/regime/sets?active_only=false');
    var d = await r.json();
    if (!d.ok || !d.items) { container.innerHTML = '<div class="muted">불러오기 실패</div>'; return; }
    
    var REGIME_COLORS = {risk_on:'#3fb950', neutral:'#8b9bb4', risk_off:'#f85149', volatile:'#d29922'};
    var REGIME_LABELS = {risk_on:'Risk On', neutral:'중립', risk_off:'Risk Off', volatile:'변동성'};
    
    container.innerHTML = d.items.map(function(set) {
      var tc = set.trigger_conditions || {};
      var sc = set.settings || {};
      var regimeLabel = tc.regime_label || '-';
      var regimeColor = REGIME_COLORS[regimeLabel] || '#8b9bb4';
      var isPrebuilt = set.is_prebuilt;
      
      return '<div class="regime-set-item" id="rset-' + escapeHtml(set.id) + '" style="border:1px solid var(--border); border-radius:8px; margin-bottom:8px; overflow:hidden;">'
        + '<div style="display:flex; align-items:center; gap:10px; padding:12px 14px; cursor:pointer; background:var(--bg2);" onclick="toggleRegimeSetEdit(\'' + escapeHtml(set.id) + '\')">'
          + '<span style="width:10px; height:10px; border-radius:50%; background:' + regimeColor + '; flex-shrink:0; display:inline-block;"></span>'
          + '<div style="flex:1;">'
            + '<span style="font-weight:600; font-size:13px;">' + escapeHtml(set.name) + '</span>'
            + (isPrebuilt ? ' <span style="font-size:10px; background:#d29922; color:#000; border-radius:3px; padding:1px 5px; margin-left:4px;">예측 SET</span>' : '')
            + '<div style="font-size:11px; color:var(--muted); margin-top:2px;">'
              + escapeHtml(set.description || '')
            + '</div>'
          + '</div>'
          + '<div style="font-size:11px; color:var(--muted); text-align:right; white-space:nowrap;">'
            + '포지션 ' + (sc.max_positions || '-') + '개<br>'
            + '손절 ' + ((sc.stop_loss_rate || 0) * 100).toFixed(1) + '%'
          + '</div>'
          + '<span style="color:var(--muted); font-size:14px; margin-left:8px;">▼</span>'
        + '</div>'
        + '<div id="rset-edit-' + escapeHtml(set.id) + '" style="display:none; padding:14px; border-top:1px solid var(--border);">'
          + '<div class="form-grid" style="grid-template-columns:repeat(auto-fill, minmax(160px, 1fr)); gap:10px; margin-bottom:12px;">'
            + _regimeSetField('최대 포지션', 'rset-max_positions-' + set.id, sc.max_positions, 'number', '1', '20')
            + _regimeSetField('손절선 (%)', 'rset-stop_loss_rate-' + set.id, ((sc.stop_loss_rate || 0) * 100).toFixed(2), 'number', '-20', '0')
            + _regimeSetField('목표 익절 (%)', 'rset-take_profit_rate-' + set.id, ((sc.take_profit_rate || 0) * 100).toFixed(2), 'number', '0', '30')
            + _regimeSetField('트레일링 발동 (%)', 'rset-trailing_activate_profit-' + set.id, ((sc.trailing_activate_profit || 0) * 100).toFixed(2), 'number', '0', '30')
            + _regimeSetField('트레일링 폭 (%)', 'rset-trailing_stop_rate-' + set.id, ((sc.trailing_stop_rate || 0) * 100).toFixed(2), 'number', '0', '10')
          + '</div>'
          + '<div style="display:flex; align-items:center; gap:12px; margin-bottom:12px;">'
            + '<label style="font-size:12px; display:flex; align-items:center; gap:6px; cursor:pointer;">'
              + '<input type="checkbox" id="rset-new_entry_allowed-' + set.id + '"' + (sc.new_entry_allowed ? ' checked' : '') + '>'
              + '신규매수 허용'
            + '</label>'
          + '</div>'
          + '<div style="display:flex; gap:8px;">'
            + '<button type="button" class="btn primary" onclick="saveRegimeSet(\'' + escapeHtml(set.id) + '\')">저장</button>'
            + '<button type="button" class="btn" onclick="toggleRegimeSetEdit(\'' + escapeHtml(set.id) + '\')">취소</button>'
          + '</div>'
          + '<div id="rset-save-msg-' + escapeHtml(set.id) + '" style="font-size:12px; margin-top:8px;"></div>'
        + '</div>'
      + '</div>';
    }).join('');
  } catch(e) {
    container.innerHTML = '<div class="muted">오류: ' + escapeHtml(e.message) + '</div>';
  }
}

function _regimeSetField(label, id, value, type, min, max) {
  return '<div class="field">'
    + '<label style="font-size:11px;">' + label + '</label>'
    + '<input id="' + id + '" type="' + type + '" value="' + value + '"'
    + (min ? ' min="' + min + '"' : '') + (max ? ' max="' + max + '"' : '')
    + ' style="width:100%;">'
    + '</div>';
}

function toggleRegimeSetEdit(setId) {
  var panel = document.getElementById('rset-edit-' + setId);
  if (panel) panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
}

async function saveRegimeSet(setId) {
  var msgEl = document.getElementById('rset-save-msg-' + setId);
  if (msgEl) msgEl.textContent = '저장 중...';
  
  var maxPos = document.getElementById('rset-max_positions-' + setId);
  var stopRate = document.getElementById('rset-stop_loss_rate-' + setId);
  var tpRate = document.getElementById('rset-take_profit_rate-' + setId);
  var trailActivate = document.getElementById('rset-trailing_activate_profit-' + setId);
  var trailStop = document.getElementById('rset-trailing_stop_rate-' + setId);
  var newEntry = document.getElementById('rset-new_entry_allowed-' + setId);
  
  var settings = {};
  if (maxPos) settings.max_positions = parseInt(maxPos.value);
  if (stopRate) settings.stop_loss_rate = parseFloat(stopRate.value) / 100;
  if (tpRate) settings.take_profit_rate = parseFloat(tpRate.value) / 100;
  if (trailActivate) settings.trailing_activate_profit = parseFloat(trailActivate.value) / 100;
  if (trailStop) settings.trailing_stop_rate = parseFloat(trailStop.value) / 100;
  if (newEntry) settings.new_entry_allowed = newEntry.checked;
  
  try {
    var r = await fetch('/api/v1/regime/sets/' + encodeURIComponent(setId), {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({settings: settings})
    });
    var d = await r.json();
    if (d.ok) {
      if (msgEl) { msgEl.style.color = 'var(--green)'; msgEl.textContent = '✓ 저장됨'; }
      setTimeout(function() { loadRegimeSets(); }, 1000);
    } else {
      if (msgEl) { msgEl.style.color = 'var(--red)'; msgEl.textContent = '저장 실패'; }
    }
  } catch(e) {
    if (msgEl) { msgEl.style.color = 'var(--red)'; msgEl.textContent = '오류: ' + e.message; }
  }
}
```

Settings 화면 진입 시(`initSettingsUI` 또는 `showScreen("settings")`) `loadRegimeSets()` 자동 호출.  
`console-navigation.js` 의 `if (name === "settings")` 블록에 `loadRegimeSets()` 추가.

---

## 3. Daily Results (`screen-daily-results`) — 행 클릭 확장 패널

### 3-A. `console-daily-results.js` 수정

`_renderDailyResultsTable` 함수에서 `<tbody>` 각 행의 `onclick` 변경:

기존:
```javascript
return '<tr style="cursor:pointer;" onclick="dailyResultsGoToReview(\'' + escapeHtml(row.trade_date) + '\')">'
```

변경:
```javascript
return '<tr style="cursor:pointer;" onclick="toggleDailyResultDetail(\'' + escapeHtml(row.trade_date) + '\')">'
  + ... (기존 td들) ...
  + '</tr>'
  + '<tr id="dr-detail-' + escapeHtml(row.trade_date) + '" style="display:none;">'
  + '<td colspan="9" style="padding:0; background:var(--bg2);">'
  + '<div id="dr-detail-content-' + escapeHtml(row.trade_date) + '" style="padding:12px 16px;">'
  + '<div class="muted" style="font-size:12px;">로딩 중...</div>'
  + '</div>'
  + '</td>'
  + '</tr>';
```

아래 함수 추가:

```javascript
var _drDetailCache = {};

async function toggleDailyResultDetail(tradeDate) {
  var detailRow = document.getElementById('dr-detail-' + tradeDate);
  if (!detailRow) return;
  
  if (detailRow.style.display !== 'none') {
    detailRow.style.display = 'none';
    return;
  }
  detailRow.style.display = 'table-row';
  
  if (_drDetailCache[tradeDate]) {
    document.getElementById('dr-detail-content-' + tradeDate).innerHTML = _drDetailCache[tradeDate];
    return;
  }
  
  try {
    var r = await fetch('/api/v1/regime/day-detail?trade_date=' + encodeURIComponent(tradeDate));
    var d = await r.json();
    var html = _renderDayDetail(d);
    _drDetailCache[tradeDate] = html;
    document.getElementById('dr-detail-content-' + tradeDate).innerHTML = html;
  } catch(e) {
    document.getElementById('dr-detail-content-' + tradeDate).innerHTML = '<div class="muted">조회 실패</div>';
  }
}

function _renderDayDetail(d) {
  var parts = [];
  
  // 레짐 SET 정보
  var app = d.regime_application;
  if (app) {
    var REGIME_COLORS = {risk_on:'#3fb950', neutral:'#8b9bb4', risk_off:'#f85149', volatile:'#d29922'};
    var rc = REGIME_COLORS[app.regime_label] || '#8b9bb4';
    parts.push(
      '<div style="display:flex; gap:12px; flex-wrap:wrap; align-items:center; margin-bottom:10px;">'
      + '<span style="font-size:11px; color:var(--muted);">레짐 SET</span>'
      + '<span style="font-weight:700; font-size:13px;">' + escapeHtml(app.set_name || '-') + '</span>'
      + (app.is_prebuilt ? '<span style="font-size:10px; background:#d29922; color:#000; border-radius:3px; padding:1px 5px;">예측 SET</span>' : '')
      + '<span style="color:' + rc + '; font-size:12px;">' + escapeHtml(app.regime_label || '-') + '</span>'
      + '<span style="font-size:11px; color:var(--muted);">매칭 ' + Math.round((app.match_score || 0) * 100) + '%</span>'
      + '</div>'
      + '<div style="font-size:12px; color:var(--muted); margin-bottom:10px;">' + escapeHtml(app.match_reason || '') + '</div>'
    );
  } else {
    parts.push('<div style="font-size:12px; color:var(--muted); margin-bottom:10px;">레짐 SET 기록 없음 (이전 거래일)</div>');
  }
  
  // Risk Profile별 성과
  var profiles = d.profile_breakdown || [];
  if (profiles.length > 0) {
    var PROFILE_COLORS = {LOW_VOL:'#6cb6ff', MID_VOL:'#3fb950', HIGH_VOL:'#d29922', THEME_SPIKE:'#f85149'};
    parts.push(
      '<div style="display:flex; gap:8px; flex-wrap:wrap;">'
      + profiles.map(function(p) {
          var pc = PROFILE_COLORS[p.profile] || '#8b9bb4';
          var pnlSign = (p.total_pnl || 0) >= 0 ? '+' : '';
          var pnlCls = (p.total_pnl || 0) > 0 ? 'color:var(--green)' : (p.total_pnl || 0) < 0 ? 'color:var(--red)' : 'color:var(--muted)';
          return '<div style="background:var(--panel-2); border-radius:6px; padding:8px 12px; min-width:120px;">'
            + '<div style="font-size:11px; font-weight:700; color:' + pc + '; margin-bottom:4px;">' + escapeHtml(p.profile) + '</div>'
            + '<div style="font-size:13px; font-weight:700;">' + (p.win_rate_pct || 0) + '% <span style="font-size:11px; color:var(--muted);">승률</span></div>'
            + '<div style="font-size:11px; color:var(--muted);">' + (p.trades || 0) + '건 (' + (p.win_count || 0) + '승)</div>'
            + '<div style="font-size:11px; ' + pnlCls + ';">' + pnlSign + Math.round(p.total_pnl || 0).toLocaleString() + '원</div>'
            + '</div>';
        }).join('')
      + '</div>'
    );
  } else {
    parts.push('<div style="font-size:12px; color:var(--muted);">Risk Profile별 성과 데이터 없음</div>');
  }
  
  return '<div style="padding:4px 0;">' + parts.join('') + '</div>';
}
```

---

## 4. Trade Review (`screen-review`) — 레짐 SET 평가 블록 추가

`console-review.js` (`backend/static/js/screens/console-review.js`) 에서  
`loadReviewAuditScreen(date)` 또는 보고서 렌더링 함수 안에서  
**헤더 카드 바로 다음**에 레짐 SET 평가 블록을 삽입.

HTML에서 `#ra-report` 안의 헤더 카드 (`ra-report-title` 카드) 바로 다음에 추가:

```html
<!-- BLOCK -1: 레짐 SET 평가 -->
<div class="card" id="ra-regime-eval" style="margin-bottom:16px; display:none;">
  <div class="card-title">레짐 SET 평가</div>
  <div id="ra-regime-eval-content" style="font-size:13px;"></div>
</div>
```

`console-review.js` 에서 날짜가 로드될 때 `/api/v1/regime/day-detail?trade_date=` 를 추가로 호출하여 렌더:

```javascript
async function loadRegimeEvalForReview(tradeDate) {
  var card = document.getElementById('ra-regime-eval');
  var content = document.getElementById('ra-regime-eval-content');
  if (!card || !content) return;
  
  try {
    var r = await fetch('/api/v1/regime/day-detail?trade_date=' + encodeURIComponent(tradeDate));
    var d = await r.json();
    if (!d.ok) { card.style.display = 'none'; return; }
    
    card.style.display = 'block';
    var app = d.regime_application;
    var mc = d.morning_context;
    var profiles = d.profile_breakdown || [];
    var REGIME_COLORS = {risk_on:'#3fb950', neutral:'#8b9bb4', risk_off:'#f85149', volatile:'#d29922'};
    var REGIME_LABELS = {risk_on:'Risk On', neutral:'중립', risk_off:'Risk Off', volatile:'변동성'};
    
    var html = '';
    
    // 적용된 SET
    if (app) {
      var rc = REGIME_COLORS[app.regime_label] || '#8b9bb4';
      html += '<div style="display:flex; gap:16px; flex-wrap:wrap; margin-bottom:12px; padding-bottom:12px; border-bottom:1px solid var(--line);">'
        + '<div><span style="font-size:11px; color:var(--muted);">적용 SET</span>'
        + '<div style="font-weight:700;">' + escapeHtml(app.set_name || '-') + '</div>'
        + (app.is_prebuilt ? '<span style="font-size:10px; background:#d29922; color:#000; border-radius:3px; padding:1px 5px;">예측 SET</span>' : '')
        + '</div>'
        + '<div><span style="font-size:11px; color:var(--muted);">레짐</span>'
        + '<div style="color:' + rc + '; font-weight:700;">' + escapeHtml(REGIME_LABELS[app.regime_label] || app.regime_label || '-') + '</div>'
        + '</div>';
      if (mc) {
        html += '<div><span style="font-size:11px; color:var(--muted);">VIX</span>'
          + '<div>' + (mc.vix != null ? mc.vix.toFixed(1) : '-') + '</div></div>'
          + '<div><span style="font-size:11px; color:var(--muted);">KOSPI</span>'
          + '<div>' + (mc.kospi_change_pct != null ? (mc.kospi_change_pct >= 0 ? '+' : '') + mc.kospi_change_pct.toFixed(2) + '%' : '-') + '</div></div>';
      }
      html += '</div>';
      html += '<div style="font-size:12px; color:var(--muted); margin-bottom:12px;">' + escapeHtml(app.match_reason || '') + '</div>';
    } else {
      html += '<div style="font-size:12px; color:var(--muted); margin-bottom:12px;">레짐 SET 기록 없음 (이 날짜는 SET 적용 전 거래일입니다)</div>';
    }
    
    // Risk Profile별 성과
    if (profiles.length > 0) {
      var PROFILE_COLORS = {LOW_VOL:'#6cb6ff', MID_VOL:'#3fb950', HIGH_VOL:'#d29922', THEME_SPIKE:'#f85149'};
      html += '<div style="font-size:11px; color:var(--muted); margin-bottom:6px; font-weight:600;">Risk Profile별 성과</div>'
        + '<div style="display:flex; gap:8px; flex-wrap:wrap;">'
        + profiles.map(function(p) {
            var pc = PROFILE_COLORS[p.profile] || '#8b9bb4';
            var pnlCls = (p.total_pnl || 0) > 0 ? 'color:var(--green)' : (p.total_pnl || 0) < 0 ? 'color:var(--red)' : 'color:var(--muted)';
            return '<div style="background:var(--panel-2); border-radius:6px; padding:8px 12px; min-width:120px;">'
              + '<div style="font-size:11px; font-weight:700; color:' + pc + ';">' + escapeHtml(p.profile) + '</div>'
              + '<div style="font-weight:700;">' + (p.win_rate_pct || 0) + '%</div>'
              + '<div style="font-size:11px; color:var(--muted);">' + p.trades + '건</div>'
              + '<div style="font-size:11px; ' + pnlCls + ';">' + ((p.total_pnl >= 0 ? '+' : '') + Math.round(p.total_pnl || 0).toLocaleString()) + '원</div>'
              + '</div>';
          }).join('')
        + '</div>';
    }
    
    content.innerHTML = html;
  } catch(e) {
    card.style.display = 'none';
  }
}
```

Review 화면에서 날짜 로드 시 `loadRegimeEvalForReview(date)` 를 함께 호출.

---

## 5. 캐시 버스팅 (console.html 스크립트 버전 업)

```
console-daily-plan.js?v=5
console-navigation.js?v=5
console-settings.js (버전 추가 또는 증가)
console-daily-results.js (버전 추가 또는 증가)
console-review.js (버전 추가 또는 증가)
```

---

## 완료 후 OUTBOX 작성

`docs/agent-comm/OUTBOX_GEMINI_screen_reorg_frontend.md` 에 수정 파일 목록 + 주요 변경사항 정리
