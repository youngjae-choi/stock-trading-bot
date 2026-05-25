# INBOX — Gemini Frontend: Daily Plan 화면 아침 브리핑 카드

**날짜**: 2026-05-23  
**우선순위**: High  
**작업 범위**: 프론트엔드 전용

---

## 배경

백엔드에서 아침 시장 컨텍스트(morning_context)를 새로 수집·저장하게 됐다.  
API 엔드포인트: `GET /api/v1/morning-context/today`  
이 데이터를 Daily Plan 화면 상단에 카드로 표시한다.

---

## 작업 1 — `backend/static/console.html` 수정

`id="screen-rulepack"` 섹션 안에서,  
현재 "오늘 요약 카드 4개" (`<div class="grid cols-4">`) **바로 위에** 아침 브리핑 카드를 삽입한다.

삽입 위치 (line ~396):
```html
<!-- 아침 브리핑 카드 (신규 삽입) -->
<div class="card morning-brief-card" id="morningBriefCard" style="display:none;">
  <div class="morning-brief-header">
    <div class="morning-brief-title">
      <span class="morning-brief-icon">🌏</span>
      아침 시장 브리핑
      <span class="morning-brief-date" id="mbDate"></span>
    </div>
    <div class="morning-brief-badges">
      <span class="mb-badge regime" id="mbRegime">-</span>
      <span class="mb-badge risk" id="mbRisk">-</span>
    </div>
  </div>
  <div class="morning-brief-body">
    <!-- 왼쪽: 수치 그리드 -->
    <div class="mb-market-grid" id="mbMarketGrid">
      <!-- JS로 채움 -->
    </div>
    <!-- 오른쪽: LLM 판단 -->
    <div class="mb-analysis">
      <div class="mb-analysis-row">
        <span class="mb-label">주도 성격</span>
        <span class="mb-value" id="mbStockChar">-</span>
      </div>
      <div class="mb-analysis-row">
        <span class="mb-label">RulePack 힌트</span>
        <span class="mb-value" id="mbRulepackHint">-</span>
      </div>
      <div class="mb-analysis-row">
        <span class="mb-label">핵심 요인</span>
        <span class="mb-value muted" id="mbKeyFactors">-</span>
      </div>
    </div>
  </div>
</div>

<!-- 오늘 요약 카드 4개 (기존 유지) -->
<div class="grid cols-4">
```

---

## 작업 2 — `backend/static/css/console.css` 스타일 추가

파일 끝에 다음 스타일을 추가한다:

```css
/* ── Morning Brief Card ── */
.morning-brief-card {
  margin-bottom: 12px;
  border-left: 3px solid var(--accent, #E8520A);
}
.morning-brief-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  flex-wrap: wrap;
  gap: 8px;
}
.morning-brief-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--fg);
  display: flex;
  align-items: center;
  gap: 6px;
}
.morning-brief-icon { font-size: 16px; }
.morning-brief-date {
  font-size: 11px;
  color: var(--muted);
  font-weight: 400;
}
.morning-brief-badges { display: flex; gap: 6px; }

/* 레짐 배지 */
.mb-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.mb-badge.regime[data-val="risk_on"]  { background: #1a4731; color: #3fb950; }
.mb-badge.regime[data-val="risk_off"] { background: #4a1f1f; color: #f85149; }
.mb-badge.regime[data-val="volatile"] { background: #4a3b1f; color: #e3b341; }
.mb-badge.regime[data-val="neutral"]  { background: var(--bg3); color: var(--muted); }
.mb-badge.risk[data-val="low"]     { background: #1a4731; color: #3fb950; }
.mb-badge.risk[data-val="normal"]  { background: var(--bg3); color: var(--muted); }
.mb-badge.risk[data-val="high"]    { background: #4a3b1f; color: #e3b341; }
.mb-badge.risk[data-val="extreme"] { background: #4a1f1f; color: #f85149; }

.morning-brief-body {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
@media (max-width: 860px) {
  .morning-brief-body { grid-template-columns: 1fr; }
}

/* 시장 수치 그리드 */
.mb-market-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 6px 12px;
}
.mb-market-item {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-size: 12px;
}
.mb-market-label {
  color: var(--muted);
  font-size: 11px;
  white-space: nowrap;
  min-width: 70px;
}
.mb-market-value { font-weight: 600; font-size: 12px; }
.mb-market-value.up   { color: #f85149; }  /* 한국 기준: 상승=빨강 */
.mb-market-value.down { color: #3fb950; }  /* 하락=초록 */
.mb-market-value.flat { color: var(--muted); }

/* 분석 섹션 */
.mb-analysis { display: flex; flex-direction: column; gap: 8px; }
.mb-analysis-row { display: flex; flex-direction: column; gap: 2px; }
.mb-label {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--muted);
}
.mb-value { font-size: 12px; color: var(--fg); line-height: 1.5; }
.mb-value.muted { color: var(--muted); font-size: 11px; }
```

---

## 작업 3 — `backend/static/js/screens/console-rulepack.js` (또는 Daily Plan JS 파일) 수정

Daily Plan 화면을 담당하는 JS 파일을 찾아서 `loadDailyPlanScreen()` 함수 내에 아침 브리핑 로드를 추가한다.

파일명이 불확실하면 `loadDailyPlanScreen` 함수를 grep으로 찾는다.

### 추가할 함수 `loadMorningBrief()`:

```javascript
function loadMorningBrief() {
  var card = document.getElementById('morningBriefCard');
  if (!card) return;

  fetchWithAuth('/api/v1/morning-context/today')
    .then(function(res) { return res.json(); })
    .then(function(json) {
      if (!json.ok || !json.data) {
        card.style.display = 'none';
        return;
      }
      var d = json.data;
      card.style.display = 'block';

      // 날짜
      var dateEl = document.getElementById('mbDate');
      if (dateEl) dateEl.textContent = d.trade_date || '';

      // 레짐 배지
      var regimeEl = document.getElementById('mbRegime');
      if (regimeEl) {
        var regimeLabels = {
          'risk_on': 'Risk On', 'risk_off': 'Risk Off',
          'neutral': 'Neutral', 'volatile': 'Volatile'
        };
        regimeEl.textContent = regimeLabels[d.regime] || d.regime || '-';
        regimeEl.setAttribute('data-val', d.regime || 'neutral');
      }

      // 리스크 배지
      var riskEl = document.getElementById('mbRisk');
      if (riskEl) {
        var riskLabels = {
          'low': 'Low Risk', 'normal': 'Normal',
          'high': 'High Risk', 'extreme': 'Extreme'
        };
        riskEl.textContent = riskLabels[d.risk_level] || d.risk_level || '-';
        riskEl.setAttribute('data-val', d.risk_level || 'normal');
      }

      // 시장 수치 그리드
      var grid = document.getElementById('mbMarketGrid');
      if (grid && d.market_data) {
        var marketLabels = {
          'nasdaq': 'NASDAQ', 'sp500': 'S&P500',
          'vix': 'VIX', 'usdkrw': 'USD/KRW',
          'nikkei': '닛케이', 'hangseng': '항셍',
          'kospi': 'KOSPI', 'oil_wti': 'WTI'
        };
        var html = '';
        var keys = ['nasdaq', 'sp500', 'vix', 'usdkrw', 'nikkei', 'hangseng', 'kospi', 'oil_wti'];
        keys.forEach(function(k) {
          var item = d.market_data[k];
          if (!item) return;
          var pct = item.change_pct;
          var dir = pct > 0 ? 'up' : (pct < 0 ? 'down' : 'flat');
          var arrow = pct > 0 ? '▲' : (pct < 0 ? '▼' : '━');
          // VIX: 반대 색상 (높을수록 위험)
          if (k === 'vix') { dir = pct > 0 ? 'down' : (pct < 0 ? 'up' : 'flat'); }
          html += '<div class="mb-market-item">' +
            '<span class="mb-market-label">' + (marketLabels[k] || k) + '</span>' +
            '<span class="mb-market-value ' + dir + '">' +
              arrow + (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%' +
            '</span>' +
          '</div>';
        });
        grid.innerHTML = html;
      }

      // 분석 텍스트
      var charEl = document.getElementById('mbStockChar');
      if (charEl) charEl.textContent = d.stock_character || '-';

      var hintEl = document.getElementById('mbRulepackHint');
      if (hintEl) hintEl.textContent = d.rulepack_hint || '-';

      var factorsEl = document.getElementById('mbKeyFactors');
      if (factorsEl) {
        var factors = Array.isArray(d.key_factors) ? d.key_factors : [];
        factorsEl.textContent = factors.length ? factors.join(' · ') : '-';
      }
    })
    .catch(function(err) {
      console.warn('morning context load failed', err);
      if (card) card.style.display = 'none';
    });
}
```

### `loadDailyPlanScreen()` 함수 안에 호출 추가:

```javascript
function loadDailyPlanScreen() {
  loadMorningBrief();   // ← 이 줄 추가 (기존 코드 앞에)
  // ... 기존 로직 ...
}
```

---

## 주의사항

1. `fetchWithAuth` 함수가 있으면 사용, 없으면 `fetch`에 credentials/auth 헤더를 붙이는 기존 패턴을 따른다.
2. Daily Plan JS 파일명이 `console-rulepack.js`가 아닐 수 있다. `loadDailyPlanScreen`을 grep해서 정확한 파일을 찾는다.
3. CSS 변수 (`var(--accent)`, `var(--muted)`, `var(--bg2)`, `var(--bg3)`, `var(--fg)`)는 기존 테마 시스템을 그대로 따른다.
4. 카드가 데이터 없을 때는 `display:none`으로 숨긴다 (morning_context가 아직 수집 안 된 경우 대비).
5. 기존 파일 수정 시 기존 로직을 절대 깨뜨리지 않는다.

---

## 완료 기준

1. Daily Plan 화면 로드 시 아침 브리핑 카드가 표시된다.
2. regime 배지 색상이 올바르게 적용된다 (risk_on=초록, risk_off=빨강, volatile=노랑).
3. 시장 수치 8개 항목이 등락 방향에 따라 색상 적용된다.
4. 모바일(390px)에서 세로 레이아웃으로 자연스럽게 표시된다.
5. API 데이터 없을 때 카드가 숨겨진다.

## 작업 완료 후

결과를 `docs/agent-comm/OUTBOX_GEMINI_20260523_morning_briefing.md`에 작성하라.
