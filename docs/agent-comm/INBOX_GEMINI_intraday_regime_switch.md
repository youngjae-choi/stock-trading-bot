# INBOX: Gemini — 장중 레짐 전환 UI 구현

**우선순위:** HIGH  
**담당:** Gemini (Frontend Agent)  
**작성:** Sisyphus 2026-05-23

---

## 목표

장중 레짐 SET 전환 기능에 맞춰 2곳 UI 수정:
1. **Today Control** — 오늘 SET 전환 이력 타임라인 표시
2. **Daily Plan** — 오늘의 Regime Set 카드에 전환 이력 + 현재 SET 표시 강화

---

## 1. Today Control (`screen-today`) — 레짐 전환 타임라인

### 위치
Today Control 화면에서 기존 "오늘의 Plan 상태" 카드 (`#tc-plan-status` 근처) 아래,  
또는 Morning Brief 카드 바로 아래에 삽입.

### HTML 추가 (console.html `#screen-today` 내부)

```html
<!-- 레짐 전환 타임라인 -->
<div id="tc-regime-timeline-card" class="card" style="margin-bottom:16px; display:none;">
  <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:10px;">
    <div class="card-title" style="margin-bottom:0;">레짐 SET 타임라인 <span>오늘</span></div>
    <span id="tc-regime-current-badge" style="font-size:11px; background:var(--accent); color:#fff; border-radius:4px; padding:2px 8px;"></span>
  </div>
  <div id="tc-regime-timeline" style="font-size:12px;">
    <!-- JS가 채움 -->
  </div>
</div>
```

### JS: `loadTodayPlanStatus()` 또는 `loadMorningBrief()` 이후에 호출

`backend/static/js/screens/console-daily-plan.js` 또는 신규 함수로 추가:

```javascript
async function loadTodayRegimeTimeline() {
  var card = document.getElementById('tc-regime-timeline-card');
  var timelineEl = document.getElementById('tc-regime-timeline');
  var badgeEl = document.getElementById('tc-regime-current-badge');
  if (!card || !timelineEl) return;

  try {
    var r = await fetch('/api/v1/regime/today');
    var d = await r.json();
    if (!d.ok) { card.style.display = 'none'; return; }

    var transitions = d.transitions || [];
    var current = d.application;

    if (!current && transitions.length === 0) {
      card.style.display = 'none';
      return;
    }

    card.style.display = 'block';

    // 현재 SET 배지
    if (badgeEl && current) {
      badgeEl.textContent = current.set_name || '-';
    }

    // 타임라인
    var REGIME_COLORS = {risk_on:'#3fb950', neutral:'#8b9bb4', risk_off:'#f85149', volatile:'#d29922'};
    var TRIGGER_LABELS = {morning: '🌅 아침', intraday: '⚡ 장중'};

    if (transitions.length === 0) {
      timelineEl.innerHTML = '<div style="color:var(--muted);">전환 이력 없음 — 아침 SET 유지 중</div>';
    } else {
      timelineEl.innerHTML = transitions.map(function(t, i) {
        var rc = REGIME_COLORS[t.regime_label] || '#8b9bb4';
        var triggerLabel = TRIGGER_LABELS[t.trigger] || t.trigger;
        var timeStr = (t.applied_at || t.created_at || '').slice(11, 16);  // HH:MM
        var isCurrent = t.current_flag === 1 || t.current_flag === true;
        var kp = t.kospi_change_pct;
        var kpStr = kp != null ? ' KOSPI ' + (kp >= 0 ? '+' : '') + kp.toFixed(2) + '%' : '';
        var vixStr = t.vix_value != null ? ' VIX ' + t.vix_value.toFixed(1) : '';

        return '<div style="display:flex; gap:10px; align-items:flex-start; padding:6px 0;'
          + (i < transitions.length - 1 ? ' border-bottom:1px solid var(--line);' : '') + '">'
          + '<div style="width:40px; flex-shrink:0; font-size:11px; color:var(--muted); padding-top:1px;">' + timeStr + '</div>'
          + '<div style="width:8px; height:8px; border-radius:50%; background:' + rc + '; flex-shrink:0; margin-top:4px;"></div>'
          + '<div style="flex:1;">'
            + '<span style="font-weight:' + (isCurrent ? '700' : '400') + '; color:' + (isCurrent ? 'var(--fg)' : 'var(--muted)') + ';">'
              + escapeHtml(t.set_name || t.set_id || '-')
            + '</span>'
            + ' <span style="font-size:10px; color:' + rc + ';">' + escapeHtml(t.regime_label || '') + '</span>'
            + (isCurrent ? ' <span style="font-size:10px; background:var(--accent); color:#fff; border-radius:3px; padding:1px 4px;">현재</span>' : '')
            + '<div style="font-size:11px; color:var(--muted);">'
              + triggerLabel + kpStr + vixStr
            + '</div>'
          + '</div>'
          + '</div>';
      }).join('');
    }
  } catch(e) {
    card.style.display = 'none';
    console.warn('regime timeline load failed:', e);
  }
}
```

### `console-navigation.js` 수정

`if (name === "today")` 블록에 `loadTodayRegimeTimeline()` 추가:

```javascript
if (name === "today") {
  _safeLoadConsoleData();
  loadTodayOrders();
  loadTodayPlanStatus();
  loadMorningBrief();
  loadTodayRegimeTimeline();   // ← 추가
  _todayTimer = setInterval(function() {
    _safeLoadConsoleData();
    loadTodayRegimeTimeline();  // ← 30초마다 갱신
  }, 30000);
}
```

---

## 2. Daily Plan (`screen-rulepack`) — 오늘의 Regime SET 카드 강화

### 추론 체인 아래에 전환 이력 미니 타임라인 추가

`console-daily-plan.js`의 레짐 SET 로드 블록 끝에 추가:

```javascript
// 전환 이력이 2개 이상이면 미니 타임라인 표시
var transitions = setData.transitions || [];
if (transitions.length > 1) {
  var chainEl = document.getElementById('dp-set-chain');
  if (chainEl) {
    var REGIME_COLORS = {risk_on:'#3fb950', neutral:'#8b9bb4', risk_off:'#f85149', volatile:'#d29922'};
    var miniTimeline = '<div style="margin-top:10px; padding-top:10px; border-top:1px solid var(--line);">'
      + '<div style="font-size:10px; color:var(--muted); margin-bottom:6px;">오늘 전환 이력 (' + transitions.length + '회)</div>'
      + '<div style="display:flex; gap:6px; flex-wrap:wrap;">'
      + transitions.map(function(t) {
          var rc = REGIME_COLORS[t.regime_label] || '#8b9bb4';
          var timeStr = (t.applied_at || t.created_at || '').slice(11, 16);
          var isCurrent = t.current_flag === 1 || t.current_flag === true;
          return '<div style="font-size:11px; padding:3px 8px; border-radius:12px; '
            + 'border:1px solid ' + rc + '; color:' + rc + '; '
            + (isCurrent ? 'background:' + rc + '; color:#fff;' : '') + '">'
            + timeStr + ' ' + escapeHtml(t.set_name || '-')
            + '</div>';
        }).join('<span style="color:var(--muted); font-size:12px; align-self:center;">→</span>')
      + '</div></div>';
    chainEl.insertAdjacentHTML('beforeend', miniTimeline);
  }
}
```

---

## 3. 캐시 버스팅

```
console-navigation.js?v=6
console-daily-plan.js?v=6
```

---

## 완료 후 OUTBOX

`docs/agent-comm/OUTBOX_GEMINI_intraday_regime_switch.md`에 수정 파일 + 변경사항 정리
