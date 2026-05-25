# INBOX: Gemini — Trade Review LLM 복기 UI + 기타 UX 개선

**우선순위:** HIGH  
**담당:** Gemini (Frontend Agent)  
**작성:** Sisyphus 2026-05-23

---

## 목표

1. Trade Review 화면 — LLM 복기 결과 표시 (레짐 평가 카드 + 서술 + 적용된 Settings)
2. Trade Review — 액션플랜 + 시스템반영 카드 병합
3. Today Control — 비거래일이면 마지막 거래일 데이터 표시
4. 브라우저 ← / X 버튼 동작 구현
5. 캐시 버스팅

---

## 1. Trade Review — LLM 복기 카드 재구성

### 1-A. `console.html` BLOCK -1 (레짐 평가) 교체

현재:
```html
<!-- BLOCK -1: 레짐 SET 평가 -->
<div class="card" id="ra-regime-eval" style="margin-bottom:16px; display:none;">
  <div class="card-title">레짐 SET 평가</div>
  <div id="ra-regime-eval-content" style="font-size:13px;"></div>
```

교체 후:
```html
<!-- BLOCK -1: LLM 복기 종합 -->
<div class="card" id="ra-llm-review-card" style="margin-bottom:16px; display:none;">
  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
    <div class="card-title" style="margin-bottom:0;">LLM 복기 분석</div>
    <div id="ra-llm-applied-at" style="font-size:11px; color:var(--muted);"></div>
  </div>
  <!-- 레짐 평가 배지 -->
  <div id="ra-regime-eval-badge" style="margin-bottom:12px;"></div>
  <!-- LLM 서술 -->
  <div id="ra-llm-narrative" style="font-size:13px; line-height:1.7; color:var(--text); background:var(--panel-2); padding:14px; border-radius:8px; margin-bottom:12px;"></div>
  <!-- 패턴 -->
  <div id="ra-llm-patterns" style="font-size:12px;"></div>
</div>
<!-- 레짐 평가 카드 (기존 id 유지 — JS 호환) -->
<div class="card" id="ra-regime-eval" style="display:none; margin-bottom:16px;">
  <div id="ra-regime-eval-content"></div>
</div>
```

### 1-B. BLOCK 5+6 카드 병합

기존 BLOCK 5 (다음 거래일 액션 플랜) + BLOCK 6 (시스템 반영 내역) 두 카드를 하나로 합친다:

```html
<!-- BLOCK 5+6: 다음 거래일 액션 플랜 + 시스템 반영 -->
<div class="card">
  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
    <div class="card-title" style="margin-bottom:0;">다음 거래일 액션 플랜</div>
    <span id="ra-settings-applied-badge" style="font-size:11px; color:var(--muted);"></span>
  </div>
  <div id="ra-nl-tomorrow" class="ra-nl"></div>
  <div id="ra-settings-applied-section" style="display:none; margin-top:12px; padding-top:12px; border-top:1px solid var(--line);">
    <div style="font-size:11px; color:var(--muted); margin-bottom:8px;">Settings 자동 반영 내역</div>
    <div id="ra-nl-settings-applied" class="ra-nl" style="font-size:12px;"></div>
  </div>
</div>
```

BLOCK 6 원래 카드 제거, `ra-apply-btn` 제거 (LLM이 자동 반영하므로 불필요).

---

## 2. `console-review.js` 수정

### 2-A. `renderReviewReport()` 에 LLM 복기 렌더링 추가

`renderReviewReport(r)` 함수 맨 위에 아래를 추가:

```javascript
// LLM 복기 카드
var llmCard = document.getElementById('ra-llm-review-card');
var llmReview = r.llm_review || {};
var regimeEval = llmReview.regime_evaluation || {};

if (llmCard) {
  var narrative = llmReview.narrative || '';
  var appliedAt = llmReview.applied_at || '';
  var appliedSettings = llmReview.applied_settings || [];
  var evaluation = regimeEval.evaluation || '';
  var patterns = llmReview.patterns || {};

  if (narrative || evaluation) {
    llmCard.style.display = 'block';

    // 적용 시각
    var atEl = document.getElementById('ra-llm-applied-at');
    if (atEl && appliedAt) {
      atEl.textContent = '반영: ' + appliedAt.slice(11, 16) + ' KST';
    }

    // 레짐 평가 배지
    var badgeEl = document.getElementById('ra-regime-eval-badge');
    if (badgeEl && evaluation) {
      var evalColors = { good: '#3fb950', neutral: '#8b9bb4', bad: '#f85149' };
      var evalLabels = { good: '✅ 레짐 선택 적절', neutral: '📊 레짐 선택 보통', bad: '⚠️ 레짐 선택 부적절' };
      var col = evalColors[evaluation] || '#8b9bb4';
      var label = evalLabels[evaluation] || evaluation;
      var reason = regimeEval.reason || '';
      var hint = regimeEval.next_regime_hint || '';
      badgeEl.innerHTML =
        '<div style="display:flex; gap:10px; align-items:flex-start; flex-wrap:wrap;">'
        + '<span style="padding:4px 12px; border-radius:20px; background:' + col + '22; color:' + col + '; font-weight:700; font-size:13px;">' + escapeHtml(label) + '</span>'
        + (hint && hint !== 'same' ? '<span style="font-size:12px; color:var(--muted); align-self:center;">내일 힌트: <strong style="color:var(--fg);">' + escapeHtml(hint) + '</strong></span>' : '')
        + '</div>'
        + (reason ? '<div style="font-size:12px; color:var(--muted); margin-top:6px;">' + escapeHtml(reason) + '</div>' : '');
    }

    // 서술
    var narrativeEl = document.getElementById('ra-llm-narrative');
    if (narrativeEl) {
      // 마크다운 줄바꿈만 처리 (보안 — innerHTML이지만 escapeHtml 적용)
      narrativeEl.innerHTML = narrative.split('\n').map(function(line) {
        return '<div>' + escapeHtml(line) + '</div>';
      }).join('');
    }

    // 패턴
    var patternsEl = document.getElementById('ra-llm-patterns');
    if (patternsEl) {
      var winning = patterns.winning || [];
      var losing = patterns.losing || [];
      var html = '';
      if (winning.length) {
        html += '<div style="margin-bottom:8px;"><span style="color:#3fb950; font-size:11px; font-weight:600;">▲ 승리 패턴</span>'
          + winning.map(function(p) { return '<div style="margin-left:10px; font-size:12px; color:var(--muted);">• ' + escapeHtml(p) + '</div>'; }).join('') + '</div>';
      }
      if (losing.length) {
        html += '<div><span style="color:#f85149; font-size:11px; font-weight:600;">▼ 손실 패턴</span>'
          + losing.map(function(p) { return '<div style="margin-left:10px; font-size:12px; color:var(--muted);">• ' + escapeHtml(p) + '</div>'; }).join('') + '</div>';
      }
      patternsEl.innerHTML = html;
    }
  } else {
    llmCard.style.display = 'none';
  }
}
```

### 2-B. `_nlSettingsApplied()` 수정 — LLM 자동 반영 항목 표시

```javascript
function _nlSettingsApplied(r) {
  var llmReview = r.llm_review || {};
  var appliedSettings = llmReview.applied_settings || [];
  var appliedAt = llmReview.applied_at || '';
  var badgeEl = document.getElementById('ra-settings-applied-badge');
  var section = document.getElementById('ra-settings-applied-section');

  if (appliedSettings.length) {
    if (badgeEl) badgeEl.textContent = '자동 반영 ' + appliedSettings.length + '건' + (appliedAt ? ' · ' + appliedAt.slice(11,16) : '');
    if (section) section.style.display = 'block';
    return '<div>' + appliedSettings.map(function(s) {
      return '<div style="font-size:12px; padding:4px 0; border-bottom:1px solid var(--line);">'
        + '• ' + escapeHtml(s) + '</div>';
    }).join('') + '</div>';
  }

  // fallback: 기존 settings_changes (없으면 LLM 반영 없음 메시지)
  var changes = r.settings_changes || [];
  if (section) section.style.display = changes.length ? 'block' : 'none';
  if (!changes.length) return '<p class="muted">자동 반영된 설정 없음.</p>';
  // 기존 렌더 로직 유지
  return changes.map(function(c) {
    return '<div style="font-size:12px; padding:4px 0;">'
      + '• ' + escapeHtml(c.key || '') + ': ' + escapeHtml(String(c.old_value || '')) + ' → ' + escapeHtml(String(c.new_value || '')) + '</div>';
  }).join('');
}
```

### 2-C. `ra-apply-btn` 관련 코드 제거

`_nlTomorrow()` 내 `ra-apply-btn` display 토글 코드 제거 (버튼이 HTML에서 없어지므로).  
`applyNextDayOverrides` 액션 핸들러도 제거.

---

## 3. Today Control — 비거래일 처리

`console-navigation.js` 또는 `console-main.js`에서 `"today"` 화면 진입 시:

```javascript
// Today Control 진입 시 거래일 확인
async function _checkTodayTradingDay() {
  try {
    var r = await fetch('/api/v1/daily-plan/today');
    var d = await r.json();
    // daily-plan의 trade_date가 오늘과 다르면 비거래일 배너 표시
    var today = new Date().toLocaleDateString('sv-SE', {timeZone:'Asia/Seoul'});
    var planDate = d.trade_date || d.date || today;
    var banner = document.getElementById('tc-non-trading-banner');
    if (!banner) return;
    if (planDate !== today) {
      banner.style.display = 'block';
      var dateEl = document.getElementById('tc-non-trading-date');
      if (dateEl) dateEl.textContent = planDate;
    } else {
      banner.style.display = 'none';
    }
  } catch(e) {}
}
```

`console.html` `#screen-today` 맨 위에 배너 HTML 추가:

```html
<div id="tc-non-trading-banner" style="display:none; background:var(--panel-2); border:1px solid var(--line); border-radius:8px; padding:10px 16px; margin-bottom:12px; font-size:13px; color:var(--muted);">
  오늘은 비거래일입니다 — <strong id="tc-non-trading-date">-</strong> 기준 데이터를 표시합니다.
</div>
```

`console-navigation.js`의 `if (name === "today")` 블록에 `_checkTodayTradingDay()` 추가.

---

## 4. 브라우저 ← / X 버튼 동작

`console-navigation.js` 또는 `console-main.js`에 추가:

```javascript
// ── 화면 히스토리 스택 ──────────────────────────────────────
var _screenHistory = [];

function _pushScreenHistory(screenName) {
  // 직전과 같은 화면 중복 push 방지
  if (_screenHistory[_screenHistory.length - 1] !== screenName) {
    _screenHistory.push(screenName);
  }
}

// showScreen 호출 시마다 히스토리 push
// 기존 showScreen() 함수 안에 _pushScreenHistory(name) 추가

// ── 브라우저 뒤로가기 (popstate) ────────────────────────────
window.addEventListener('popstate', function(e) {
  if (_screenHistory.length > 1) {
    _screenHistory.pop(); // 현재 제거
    var prev = _screenHistory[_screenHistory.length - 1];
    if (prev) {
      showScreen(prev, { skipHistory: true }); // 히스토리 중복 push 방지 플래그
      return;
    }
  }
  // 첫 화면이면 X 동작과 동일 → confirm
  _confirmClose();
});

// history.pushState를 화면 전환 시 호출해 popstate가 동작하도록
// showScreen() 안에: history.pushState({screen: name}, '', '#' + name);

// ── X 버튼 (beforeunload 대신 커스텀) ───────────────────────
// beforeunload는 모바일에서 동작 안 하므로 커스텀 confirm 사용
// 단, PWA/앱이 아닌 일반 브라우저 탭 닫기는 막을 수 없으므로
// 헤더의 X 버튼(있다면) 또는 beforeunload 이벤트에서 처리

function _confirmClose() {
  if (confirm('KAIROS를 종료하시겠습니까?')) {
    window.close();
    // window.close()가 막힌 환경(대부분)이면 빈 페이지로
    setTimeout(function() { window.location.href = '/logout'; }, 200);
  }
}

// beforeunload로 브라우저 탭 닫기 감지
window.addEventListener('beforeunload', function(e) {
  e.preventDefault();
  e.returnValue = ''; // 크롬 기본 confirm 표시
});
```

**주의**: `showScreen(name, opts)` 함수 시그니처에 `opts` 파라미터 추가. `opts.skipHistory`가 true면 `_pushScreenHistory` 및 `history.pushState` 스킵.

---

## 5. 캐시 버스팅

`console.html`의 스크립트 태그:
```
console-review.js?v=7
console-navigation.js?v=7
console-main.js?v=7 (있다면)
```

---

## 완료 후 OUTBOX

`docs/agent-comm/OUTBOX_GEMINI_review_llm_ui_ux.md`에 수정 파일 + 변경사항 정리
