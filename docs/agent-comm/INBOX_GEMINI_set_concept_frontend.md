# INBOX: Gemini — 매매 계획 통합 화면 구현 (Set 개념 포함)

**우선순위:** HIGH  
**담당:** Gemini (Frontend Agent)  
**작성:** Sisyphus 2026-05-23

---

## 목표

1. "Daily Plan" 화면과 "레짐 분석" 화면을 **하나의 "매매 계획" 화면**으로 통합
2. 화면 최상단에 **오늘의 Regime Set 카드** 추가 — 어떤 Set이 적용됐는지 + 이유 표시
3. 예측 Set(미리 만든 시나리오 Set) 구분 표시
4. 사이드바에서 "레짐 분석" 버튼 제거, "Daily Plan" → "매매 계획"으로 레이블 변경

---

## 변경 파일

1. `backend/static/console.html` — 화면 통합 + 라벨 변경
2. `backend/static/js/screens/console-daily-plan.js` — Set 카드 로직 추가
3. `backend/static/js/screens/console-regime-analytics.js` — loadRegimeAnalyticsScreen을 rulepack 화면 내부에서 호출
4. `backend/static/js/console-navigation.js` — showScreen() 수정

---

## 1. `console.html` 수정

### 1-A. 사이드바 내비게이션 버튼 변경

기존:
```html
<button type="button" data-screen="regime-analytics">레짐 분석 <small>analytics</small></button>
<button type="button" data-screen="rulepack">Daily Plan <small>rules</small></button>
```

변경 후:
```html
<button type="button" data-screen="rulepack">매매 계획 <small>plan & regime</small></button>
```
→ "레짐 분석" 버튼 완전 제거

### 1-B. 모바일 메뉴 `<select>` 옵션

기존:
```html
<option value="rulepack">Daily Plan</option>
```
변경:
```html
<option value="rulepack">매매 계획</option>
```
regime-analytics 옵션이 있으면 제거.

### 1-C. `#screen-rulepack` 내부 — Set 카드 추가

`<section class="screen" id="screen-rulepack">` 의 `<div class="page-head">` 바로 뒤,
기존 summary 카드(`.grid.cols-4`) 위에 아래 블록을 삽입:

```html
<!-- ── 오늘의 Regime Set ── -->
<div id="dp-regime-set-card" class="card" style="margin-bottom:16px; border-left:3px solid var(--accent);">
  <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:8px;">
    <div>
      <span class="card-title" style="font-size:13px;">오늘의 Regime Set</span>
      <span id="dp-set-prebuilt-badge" style="display:none; margin-left:8px; font-size:10px; background:#d29922; color:#000; border-radius:3px; padding:2px 6px;">예측 Set</span>
    </div>
    <span id="dp-set-score" style="font-size:11px; color:var(--muted);"></span>
  </div>
  <div style="display:flex; gap:16px; flex-wrap:wrap; align-items:flex-start;">
    <div>
      <div id="dp-set-name" style="font-size:18px; font-weight:700; color:var(--fg);">-</div>
      <div id="dp-set-regime" style="font-size:12px; color:var(--muted); margin-top:2px;"></div>
    </div>
    <div style="flex:1; min-width:200px;">
      <div id="dp-set-reason" style="font-size:12px; color:var(--muted); line-height:1.6;"></div>
    </div>
    <div id="dp-set-settings" style="font-size:11px; color:var(--fg); background:var(--bg2); border-radius:6px; padding:8px 12px; white-space:pre;"></div>
  </div>
</div>

<!-- ── 레짐 분석 (통합) ── -->
<div id="dp-regime-analytics-section" style="margin-bottom:16px;">
  <!-- console-regime-analytics.js 가 여기 렌더링 -->
</div>
```

### 1-D. `#screen-regime-analytics` 섹션 처리

기존:
```html
<section class="screen" id="screen-regime-analytics">
  <!-- console-regime-analytics.js 가 렌더링 -->
</section>
```

변경: 이 `<section>` 태그는 **그대로 유지** (삭제하지 않음).  
단, 내용은 비워두고 `style="display:none;"` 추가 — 직접 접근 불가하게만 막음.  
→ 실제 렌더링은 rulepack 화면 내 `#dp-regime-analytics-section` 에서 처리.

### 1-E. 하단 탭바 수정

기존에 `data-screen="rulepack"` 탭이 있다면 레이블만 "매매 계획"으로 변경.

### 1-F. 제목 변경

`#screen-rulepack` 안의 `<h1 class="page-title">Daily Plan</h1>`  
→ `<h1 class="page-title">매매 계획</h1>`

`<p class="page-desc">` 내용 변경:  
→ `"오늘 적용된 Regime Set, Daily Plan, Risk Profile, 레짐별 성과 분석을 통합해서 확인합니다."`

---

## 2. `console-daily-plan.js` — Set 카드 로직 추가

`loadDailyPlanScreen()` 함수 안 마지막에 아래 비동기 블록 추가:

```javascript
// ── 오늘의 Regime Set 카드 ──
try {
  var today = new Date().toISOString().slice(0, 10).replace(/-/g, '-');
  var setResp = await fetch('/api/v1/regime/today');
  var setData = await setResp.json();
  if (setData.ok && setData.application) {
    var app = setData.application;
    var setCard = document.getElementById('dp-regime-set-card');
    if (setCard) {
      var nameEl = document.getElementById('dp-set-name');
      if (nameEl) nameEl.textContent = app.set_name || '-';
      
      var regimeEl = document.getElementById('dp-set-regime');
      if (regimeEl) {
        var regimeLabels = {risk_on:'Risk On', neutral:'중립', risk_off:'Risk Off', volatile:'변동성'};
        var parts = [];
        if (app.regime_label) parts.push(regimeLabels[app.regime_label] || app.regime_label);
        if (app.vix_value != null) parts.push('VIX ' + app.vix_value.toFixed(1));
        if (app.kospi_change_pct != null) {
          var kp = app.kospi_change_pct;
          parts.push('KOSPI ' + (kp >= 0 ? '+' : '') + kp.toFixed(2) + '%');
        }
        regimeEl.textContent = parts.join(' · ');
      }
      
      var reasonEl = document.getElementById('dp-set-reason');
      if (reasonEl) reasonEl.textContent = app.match_reason || '';
      
      var scoreEl = document.getElementById('dp-set-score');
      if (scoreEl) scoreEl.textContent = app.match_score != null
        ? '매칭 점수: ' + (app.match_score * 100).toFixed(0) + '%' : '';
      
      var badge = document.getElementById('dp-set-prebuilt-badge');
      if (badge) badge.style.display = app.is_prebuilt ? 'inline' : 'none';
      
      // 적용된 설정값 표시
      var settingsEl = document.getElementById('dp-set-settings');
      if (settingsEl && app.applied_settings) {
        var s = app.applied_settings;
        var lines = [];
        if (s.max_positions != null) lines.push('최대포지션: ' + s.max_positions + '개');
        if (s.stop_loss_rate != null) lines.push('손절: ' + (s.stop_loss_rate * 100).toFixed(1) + '%');
        if (s.take_profit_rate != null) lines.push('익절: +' + (s.take_profit_rate * 100).toFixed(1) + '%');
        if (s.new_entry_allowed != null) lines.push('신규매수: ' + (s.new_entry_allowed ? '허용' : '차단'));
        settingsEl.textContent = lines.join('\n');
      }
    }
  }
} catch(e) {
  console.warn('regime set card load failed:', e);
}
```

---

## 3. `console-regime-analytics.js` — 렌더링 타깃 변경

`loadRegimeAnalyticsScreen()` 함수 안에서 화면에 HTML을 렌더링할 때,  
`document.getElementById('screen-regime-analytics')` 대신  
`document.getElementById('dp-regime-analytics-section')` 을 타깃으로 사용한다.

단, `document.getElementById('screen-regime-analytics')` 를 직접 사용하는 부분을  
아래처럼 변경:

```javascript
// 기존
var container = document.getElementById('screen-regime-analytics');
// 변경 후
var container = document.getElementById('dp-regime-analytics-section') 
                || document.getElementById('screen-regime-analytics');
```

→ `dp-regime-analytics-section` 이 있으면 거기 렌더링, 없으면 기존 방식 fallback.

---

## 4. `console-navigation.js` — showScreen() 수정

기존:
```javascript
if (name === "rulepack") {
  loadDailyPlanScreen();
}

if (name === "regime-analytics") {
  loadRegimeAnalyticsScreen();
}
```

변경:
```javascript
if (name === "rulepack") {
  loadDailyPlanScreen();
  loadRegimeAnalyticsScreen();  // 통합 화면에서 함께 로드
}

// "regime-analytics" 블록은 그대로 두되 loadRegimeAnalyticsScreen()만 호출
// (사이드바에서 직접 접근하는 경로는 없어지지만 코드는 유지)
```

---

## 5. CSS 추가 (console.css 또는 inline)

`#dp-set-settings` 가 보기 좋게 표시되도록 monospace 폰트 적용:

```css
#dp-set-settings {
  font-family: var(--font-mono, 'Roboto Mono', monospace);
  font-size: 11px;
}
```

---

## 완료 후 OUTBOX 작성

`docs/agent-comm/OUTBOX_GEMINI_set_concept_frontend.md` 에 결과 작성:
- 수정된 파일 목록
- 통합 화면 DOM 구조 요약
- Set 카드 렌더링 확인

---

## 주의사항

- `#screen-regime-analytics` 섹션 자체는 삭제하지 않는다 (style="display:none" 처리만)
- 캐시 버스팅을 위해 스크립트 태그 버전을 올린다:
  - `console-daily-plan.js?v=4`
  - `console-regime-analytics.js?v=2`
  - `console-navigation.js?v=4`
- 기존 `loadMorningBrief()` 는 navigation.js의 today 블록에만 있으므로 건드리지 않음
