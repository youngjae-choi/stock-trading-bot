# [GEMINI] 레짐별 성과 분석 — 프론트엔드 구현

## 목표
"시장 상황(레짐)별 최적 설정값 탐색" 화면 구현.
백엔드 API 3개를 시각화하는 새 콘솔 화면 `regime-analytics` 추가.

---

## 작업 1 — console.html: nav + screen div 추가

파일: `backend/static/console.html`

### 1-A. 사이드바 nav 버튼 추가

기존 `data-screen="statistics"` 버튼 바로 아래에 추가:

```html
<button class="nav-btn" data-screen="regime-analytics" onclick="showScreen('regime-analytics')">
  레짐 분석
</button>
```

### 1-B. screen div 추가

다른 `<div id="screen-XXX" class="screen" ...>` 패턴과 동일하게 추가:

```html
<div id="screen-regime-analytics" class="screen" style="display:none;">
  <!-- console-regime-analytics.js 가 렌더링 -->
</div>
```

### 1-C. script 태그 추가

다른 screen JS들과 같은 위치(screens 그룹)에:

```html
<script src="/static/js/screens/console-regime-analytics.js?v=1"></script>
```

---

## 작업 2 — console-regime-analytics.js 신규 생성

파일: `backend/static/js/screens/console-regime-analytics.js`

이 화면은 3개 섹션으로 구성:
1. **레짐별 성과 카드** — risk_on/neutral/risk_off/volatile 각 카드
2. **날짜별 히스토리 테이블** — parameter-history API 결과
3. **최적 설정 추천** — regime-recommendation API 결과

```javascript
/* ── Regime Analytics Screen ── */

async function loadRegimeAnalyticsScreen() {
  var container = document.getElementById('screen-regime-analytics');
  if (!container) return;

  // 기간 선택 상태 (전역 유지)
  if (!window._regimeAnalyticsDays) window._regimeAnalyticsDays = 90;

  container.innerHTML = buildRegimeAnalyticsLayout();
  await Promise.all([
    loadRegimePerformance(),
    loadRegimeRecommendation(),
    loadParameterHistory(),
  ]);
}

function buildRegimeAnalyticsLayout() {
  return `
    <div style="padding:20px; max-width:1200px; margin:0 auto;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
        <h2 style="margin:0; font-size:18px; font-weight:700; color:var(--fg);">레짐별 성과 분석</h2>
        <div style="display:flex; gap:8px; align-items:center;">
          <span style="font-size:12px; color:var(--muted);">기간:</span>
          <button class="btn btn-sm" onclick="setRegimeAnalyticsDays(30)" id="ra-btn-30">30일</button>
          <button class="btn btn-sm" onclick="setRegimeAnalyticsDays(90)" id="ra-btn-90">90일</button>
          <button class="btn btn-sm" onclick="setRegimeAnalyticsDays(180)" id="ra-btn-180">180일</button>
          <button class="btn btn-sm" onclick="loadRegimeAnalyticsScreen()">↻</button>
        </div>
      </div>

      <!-- 레짐별 성과 카드 -->
      <div style="margin-bottom:24px;">
        <div style="font-size:13px; font-weight:600; color:var(--muted); margin-bottom:12px; text-transform:uppercase; letter-spacing:1px;">레짐별 거래 성과</div>
        <div id="ra-regime-cards" style="display:grid; grid-template-columns:repeat(4,1fr); gap:12px;">
          <div class="card" style="padding:16px; text-align:center; color:var(--muted);">로딩 중...</div>
        </div>
      </div>

      <!-- 설정 추천 -->
      <div style="margin-bottom:24px;">
        <div style="font-size:13px; font-weight:600; color:var(--muted); margin-bottom:12px; text-transform:uppercase; letter-spacing:1px;">레짐별 최적 설정 추천</div>
        <div id="ra-recommendations" style="display:grid; grid-template-columns:repeat(4,1fr); gap:12px;">
          <div class="card" style="padding:16px; text-align:center; color:var(--muted);">로딩 중...</div>
        </div>
      </div>

      <!-- 날짜별 히스토리 테이블 -->
      <div>
        <div style="font-size:13px; font-weight:600; color:var(--muted); margin-bottom:12px; text-transform:uppercase; letter-spacing:1px;">날짜별 히스토리</div>
        <div class="card" style="padding:0; overflow:hidden;">
          <div id="ra-history-table" style="overflow-x:auto;">
            <div style="padding:20px; text-align:center; color:var(--muted);">로딩 중...</div>
          </div>
        </div>
      </div>
    </div>
  `;
}

function setRegimeAnalyticsDays(days) {
  window._regimeAnalyticsDays = days;
  loadRegimeAnalyticsScreen();
}

// 레짐 색상 & 라벨
var REGIME_META = {
  risk_on:  { label: 'Risk On',  color: '#3fb950', bg: 'rgba(63,185,80,0.12)' },
  neutral:  { label: 'Neutral',  color: '#8b9bb4', bg: 'rgba(139,155,180,0.12)' },
  risk_off: { label: 'Risk Off', color: '#f85149', bg: 'rgba(248,81,73,0.12)' },
  volatile: { label: 'Volatile', color: '#d29922', bg: 'rgba(210,153,34,0.12)' },
};

async function loadRegimePerformance() {
  var days = window._regimeAnalyticsDays || 90;
  var el = document.getElementById('ra-regime-cards');
  if (!el) return;
  try {
    var r = await fetch('/api/v1/analytics/regime-performance?days=' + days);
    var d = await r.json();
    if (!d.ok) { el.innerHTML = '<div style="color:var(--err)">로드 실패</div>'; return; }

    var regimes = ['risk_on', 'neutral', 'risk_off', 'volatile'];
    el.innerHTML = regimes.map(function(regime) {
      var meta = REGIME_META[regime] || { label: regime, color: '#aaa', bg: 'rgba(170,170,170,0.1)' };
      var data = (d.regimes || {})[regime] || {};
      var hasTrades = data.total_trades > 0;
      return '<div class="card" style="padding:16px; border-left:3px solid ' + meta.color + '; background:' + meta.bg + ';">'
        + '<div style="font-size:13px; font-weight:700; color:' + meta.color + '; margin-bottom:10px;">' + meta.label + '</div>'
        + '<div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; font-size:12px;">'
        + '<div><span style="color:var(--muted)">거래일</span><br><strong>' + (data.days || 0) + '일</strong></div>'
        + '<div><span style="color:var(--muted)">총 거래</span><br><strong>' + (data.total_trades || 0) + '건</strong></div>'
        + '<div><span style="color:var(--muted)">승률</span><br><strong style="color:' + (hasTrades && data.win_rate_pct >= 50 ? '#3fb950' : '#f85149') + '">' + (hasTrades ? data.win_rate_pct + '%' : '-') + '</strong></div>'
        + '<div><span style="color:var(--muted)">평균 P&L</span><br><strong style="color:' + ((data.avg_pnl_krw || 0) >= 0 ? '#3fb950' : '#f85149') + '">' + (hasTrades ? formatKrw(data.avg_pnl_krw) : '-') + '</strong></div>'
        + '<div style="grid-column:1/-1;"><span style="color:var(--muted)">누적 P&L</span> <strong style="color:' + ((data.total_pnl_krw || 0) >= 0 ? '#3fb950' : '#f85149') + '">' + (hasTrades ? formatKrw(data.total_pnl_krw) : '데이터 없음') + '</strong></div>'
        + '</div>'
        + '</div>';
    }).join('');
  } catch(e) {
    if (el) el.innerHTML = '<div style="color:var(--err)">오류: ' + e.message + '</div>';
  }
}

async function loadRegimeRecommendation() {
  var days = window._regimeAnalyticsDays || 90;
  var el = document.getElementById('ra-recommendations');
  if (!el) return;
  try {
    var r = await fetch('/api/v1/analytics/regime-recommendation?days=' + days);
    var d = await r.json();
    if (!d.ok) { el.innerHTML = '<div style="color:var(--err)">로드 실패</div>'; return; }

    var CONF_COLOR = { high: '#3fb950', medium: '#d29922', low: '#8b9bb4', no_data: '#555' };
    var CONF_LABEL = { high: '신뢰도 높음', medium: '신뢰도 보통', low: '신뢰도 낮음', no_data: '데이터 없음' };
    var regimes = ['risk_on', 'neutral', 'risk_off', 'volatile'];

    el.innerHTML = regimes.map(function(regime) {
      var meta = REGIME_META[regime] || { label: regime, color: '#aaa', bg: '' };
      var rec = (d.recommendations || {})[regime] || {};
      var s = rec.settings || {};
      var conf = rec.confidence || 'no_data';
      return '<div class="card" style="padding:16px;">'
        + '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">'
        + '<span style="font-size:13px; font-weight:700; color:' + meta.color + '">' + meta.label + '</span>'
        + '<span style="font-size:10px; color:' + (CONF_COLOR[conf]||'#aaa') + '; background:rgba(0,0,0,0.2); padding:2px 6px; border-radius:8px;">' + (CONF_LABEL[conf]||conf) + '</span>'
        + '</div>'
        + '<div style="font-size:11px; display:grid; gap:4px;">'
        + '<div style="display:flex; justify-content:space-between;"><span style="color:var(--muted)">최대 포지션</span><strong>' + (s.max_positions != null ? s.max_positions + '개' : '-') + '</strong></div>'
        + '<div style="display:flex; justify-content:space-between;"><span style="color:var(--muted)">손절선</span><strong style="color:#f85149">' + (s.stop_loss_rate != null ? (s.stop_loss_rate * 100).toFixed(1) + '%' : '-') + '</strong></div>'
        + '<div style="display:flex; justify-content:space-between;"><span style="color:var(--muted)">목표 익절</span><strong style="color:#3fb950">' + (s.take_profit_rate != null ? '+' + (s.take_profit_rate * 100).toFixed(1) + '%' : '-') + '</strong></div>'
        + '<div style="display:flex; justify-content:space-between;"><span style="color:var(--muted)">종목당 비중</span><strong>' + (s.max_position_size_rate != null ? (s.max_position_size_rate * 100).toFixed(0) + '%' : '-') + '</strong></div>'
        + '</div>'
        + '<div style="margin-top:8px; font-size:10px; color:var(--muted); line-height:1.4;">' + escapeHtml(rec.rationale || '') + '</div>'
        + '</div>';
    }).join('');
  } catch(e) {
    if (el) el.innerHTML = '<div style="color:var(--err)">오류: ' + e.message + '</div>';
  }
}

async function loadParameterHistory() {
  var days = window._regimeAnalyticsDays || 90;
  var el = document.getElementById('ra-history-table');
  if (!el) return;
  try {
    var r = await fetch('/api/v1/analytics/parameter-history?days=' + days);
    var d = await r.json();
    if (!d.ok) { el.innerHTML = '<div style="padding:20px; color:var(--err)">로드 실패</div>'; return; }

    var rows = d.rows || [];
    if (!rows.length) {
      el.innerHTML = '<div style="padding:20px; text-align:center; color:var(--muted);">데이터 없음 — 거래일이 쌓이면 표시됩니다</div>';
      return;
    }

    var thead = '<tr>'
      + '<th>날짜</th><th>레짐</th><th>리스크</th>'
      + '<th>손절선</th><th>목표익절</th><th>최대포지션</th>'
      + '<th>거래건수</th><th>승률</th><th>P&L</th>'
      + '</tr>';

    var tbody = rows.slice().reverse().map(function(row) {
      var meta = REGIME_META[row.regime] || { label: row.regime, color: '#aaa' };
      var hasTrades = row.total_trades > 0;
      var pnl = row.total_pnl || 0;
      return '<tr>'
        + '<td>' + (row.date || '') + '</td>'
        + '<td><span style="color:' + meta.color + '; font-weight:600;">' + meta.label + '</span></td>'
        + '<td style="font-size:11px; color:var(--muted);">' + (row.risk_level || '-') + '</td>'
        + '<td style="color:#f85149;">' + (row.stop_loss_rate != null ? (row.stop_loss_rate * 100).toFixed(1) + '%' : '-') + '</td>'
        + '<td style="color:#3fb950;">' + (row.take_profit_rate != null ? '+' + (row.take_profit_rate * 100).toFixed(1) + '%' : '-') + '</td>'
        + '<td>' + (row.max_positions != null ? row.max_positions : '-') + '</td>'
        + '<td>' + row.total_trades + '건</td>'
        + '<td style="color:' + (hasTrades && row.win_rate_pct >= 50 ? '#3fb950' : '#f85149') + ';">' + (hasTrades && row.win_rate_pct != null ? row.win_rate_pct + '%' : '-') + '</td>'
        + '<td style="color:' + (pnl >= 0 ? '#3fb950' : '#f85149') + ';">' + (hasTrades ? formatKrw(pnl) : '-') + '</td>'
        + '</tr>';
    }).join('');

    el.innerHTML = '<table class="data-table"><thead>' + thead + '</thead><tbody>' + tbody + '</tbody></table>';
  } catch(e) {
    if (el) el.innerHTML = '<div style="padding:20px; color:var(--err)">오류: ' + e.message + '</div>';
  }
}

function formatKrw(val) {
  if (val == null) return '-';
  var n = Math.round(val);
  var sign = n >= 0 ? '+' : '';
  return sign + n.toLocaleString('ko-KR') + '원';
}
```

---

## 작업 3 — console.css: 반응형 보완

파일: `backend/static/css/console.css`

`@media (max-width: 860px)` 블록 내에 추가:

```css
/* 레짐 분석 카드 — 모바일에서 2열 */
#screen-regime-analytics #ra-regime-cards,
#screen-regime-analytics #ra-recommendations {
  grid-template-columns: repeat(2, 1fr) !important;
}
```

---

## 검증 기준

1. 콘솔 사이드바에 "레짐 분석" 메뉴 표시
2. 클릭 시 화면 전환 정상 (`screen-regime-analytics` 보임)
3. `/api/v1/analytics/regime-performance` 호출 후 4개 레짐 카드 렌더링
4. `/api/v1/analytics/regime-recommendation` 호출 후 추천 카드 렌더링
5. 히스토리 테이블 렌더링 (데이터 없으면 "데이터 없음" 메시지)
6. 30일/90일/180일 버튼 전환 동작

---

## 주의사항

- `escapeHtml`, `showScreen` 함수는 console-utils.js 에 이미 있음 — 중복 정의 금지
- `fetchWithAuth` 대신 `fetch` 사용 (analytics는 인증 불필요)
- 기존 CSS 클래스 (`card`, `btn`, `btn-sm`, `data-table`, `status`) 최대한 재사용

작업 완료 후 `docs/agent-comm/OUTBOX_GEMINI_20260523_regime_analytics_frontend.md` 에 결과 보고.
