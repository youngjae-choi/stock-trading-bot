# INBOX_EXECUTOR_shadow_missed_merge

## 역할
너는 Executor(Codex)다. Shadow Trading과 Missed Opportunity 두 페이지를 하나의 "미진입 종목 추적" 페이지로 통합한다.
완료 후 `docs/agent-comm/OUTBOX_EXECUTOR_shadow_missed_merge.md`에 결과를 작성하라.

수정 대상: `backend/static/console.html` 단일 파일

---

## 배경

두 페이지가 추적하는 내용은 "매수하지 않은 종목이 이후 어떻게 됐는가"로 동일하다.
차이는 `missed_stage` 컬럼만으로 표현 가능하다:

| missed_stage | 의미 |
|---|---|
| S3_FILTER / S3_UNIVERSE_FILTER | 유니버스 필터 탈락 |
| S4_SCREENING / S4_HYBRID_SCREENING | Opus 스크리닝 탈락 |
| S5_NOT_ASSIGNED | Daily Plan 미배정 |
| S6_NO_SIGNAL | 조건 미달 — 신호 미발생 (Shadow Trading) |

API:
- Shadow: `GET /api/v1/shadow-trading/today` → `[{symbol, missed_stage:"S6_NO_SIGNAL", entry_price, max_return_10m, max_return_30m, max_return_eod, ...}]`
- Missed: `GET /api/v1/missed-opportunity/today` → `[{symbol, missed_stage:"S3_FILTER"|..., missed_reason, price_at_missed, max_return_after_10m, max_return_after_30m, max_return_until_eod, improvement_candidate, ...}]`

---

## 작업 1 — 메뉴에서 Missed Opportunity 제거, Shadow Trading → "미진입 추적"으로 통합

### 사이드바 버튼 (라인 약 870)

**현재:**
```html
<button data-screen="shadow-trading">Shadow Trading <small>shadow</small></button>
<button data-screen="missed-opportunity">Missed Opportunity <small>missed</small></button>
```

**수정 후:**
```html
<button data-screen="shadow-trading">미진입 추적 <small>missed</small></button>
```
(missed-opportunity 버튼 제거)

### 모바일 select option (라인 약 839)

**현재:**
```html
<option value="shadow-trading">Shadow Trading</option>
<option value="missed-opportunity">Missed Opportunity</option>
```

**수정 후:**
```html
<option value="shadow-trading">미진입 추적</option>
```
(missed-opportunity option 제거)

---

## 작업 2 — Shadow Trading 화면을 통합 "미진입 추적" 화면으로 교체

`id="screen-shadow-trading"` 섹션을 찾아 아래로 완전 교체한다.

```html
<section class="screen" id="screen-shadow-trading">
  <div class="page-head">
    <div>
      <h1 class="page-title">미진입 추적</h1>
      <p class="page-desc">오늘 매수하지 않은 종목이 이후 어떻게 움직였는지 추적합니다.</p>
    </div>
    <button class="btn" onclick="loadMissedTracking()">새로고침</button>
  </div>

  <!-- 요약 카드 -->
  <div class="grid cols-4" style="margin-bottom:16px;" id="missed-summary-cards">
    <div class="card compact"><div class="card-title">필터 탈락</div><div class="metric" id="ms-filter-count">-</div><div class="muted">S3/S4 제외</div></div>
    <div class="card compact"><div class="card-title">미배정</div><div class="metric" id="ms-plan-count">-</div><div class="muted">S5 Daily Plan</div></div>
    <div class="card compact"><div class="card-title">신호 미발생</div><div class="metric" id="ms-signal-count">-</div><div class="muted">S6 조건 미달</div></div>
    <div class="card compact"><div class="card-title">개선 후보</div><div class="metric" id="ms-candidate-count" style="color:var(--warn);">-</div><div class="muted">성과 좋았던 미진입</div></div>
  </div>

  <!-- 종목 목록 -->
  <div class="card">
    <div class="card-title" style="display:flex; justify-content:space-between; align-items:center;">
      <span>미진입 종목 목록</span>
      <div style="display:flex; gap:6px;">
        <button class="btn" id="ms-filter-all" onclick="filterMissedTracking('all')">전체</button>
        <button class="btn" id="ms-filter-s3s4" onclick="filterMissedTracking('filter')">필터탈락</button>
        <button class="btn" id="ms-filter-s5" onclick="filterMissedTracking('plan')">미배정</button>
        <button class="btn" id="ms-filter-s6" onclick="filterMissedTracking('signal')">신호미발생</button>
        <button class="btn" id="ms-filter-candidate" onclick="filterMissedTracking('candidate')">개선후보</button>
      </div>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>종목코드</th>
            <th>종목명</th>
            <th>탈락 단계</th>
            <th>탈락 사유</th>
            <th>진입가</th>
            <th>10분 후</th>
            <th>30분 후</th>
            <th>장마감</th>
            <th>개선후보</th>
          </tr>
        </thead>
        <tbody id="missed-tracking-tbody">
          <tr><td colspan="9" class="muted" style="text-align:center;">로딩중...</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</section>
```

---

## 작업 3 — Missed Opportunity 화면 HTML 제거

`id="screen-missed-opportunity"` 섹션 전체를 삭제한다.
(기존 JS 함수 `loadMissedOpportunity()`는 유지해도 무방, 혹은 아래 신규 함수로 대체)

---

## 작업 4 — JS 통합 함수 추가

기존 `loadShadowTrading()`, `loadMissedOpportunity()` 함수 아래에 추가:

```javascript
var _missedTrackingAll = [];
var _missedFilter = 'all';

async function loadMissedTracking() {
  var tbody = document.getElementById('missed-tracking-tbody');
  if (tbody) tbody.innerHTML = '<tr><td colspan="9" class="muted" style="text-align:center;">로딩중...</td></tr>';

  try {
    var [shadowRes, missedRes] = await Promise.all([
      fetch('/api/v1/shadow-trading/today').then(r => r.json()).catch(() => ({payload: []})),
      fetch('/api/v1/missed-opportunity/today').then(r => r.json()).catch(() => ({payload: []})),
    ]);

    // Shadow Trading rows (S6_NO_SIGNAL)
    var shadowRows = (shadowRes.payload || []).map(function(r) {
      return {
        symbol: r.symbol || '',
        symbol_name: r.symbol_name || '',
        missed_stage: r.missed_stage || 'S6_NO_SIGNAL',
        missed_reason: r.missed_reason || '신호 조건 미달',
        entry_price: r.entry_price || 0,
        ret_10m: r.max_return_10m,
        ret_30m: r.max_return_30m,
        ret_eod: r.max_return_eod,
        improvement_candidate: 0,
      };
    });

    // Missed Opportunity rows (S3/S4/S5)
    var missedRows = (missedRes.payload || []).map(function(r) {
      return {
        symbol: r.symbol || '',
        symbol_name: r.symbol_name || '',
        missed_stage: r.missed_stage || 'S3_FILTER',
        missed_reason: r.missed_reason || '-',
        entry_price: r.price_at_missed || 0,
        ret_10m: r.max_return_after_10m,
        ret_30m: r.max_return_after_30m,
        ret_eod: r.max_return_until_eod,
        improvement_candidate: r.improvement_candidate || 0,
      };
    });

    _missedTrackingAll = shadowRows.concat(missedRows);

    // 요약 카드
    var filterCount = _missedTrackingAll.filter(function(r) {
      return r.missed_stage.indexOf('S3') !== -1 || r.missed_stage.indexOf('S4') !== -1;
    }).length;
    var planCount = _missedTrackingAll.filter(function(r) { return r.missed_stage.indexOf('S5') !== -1; }).length;
    var signalCount = _missedTrackingAll.filter(function(r) { return r.missed_stage.indexOf('S6') !== -1; }).length;
    var candidateCount = _missedTrackingAll.filter(function(r) { return r.improvement_candidate; }).length;

    var setEl = function(id, val) { var el = document.getElementById(id); if (el) el.textContent = val; };
    setEl('ms-filter-count', filterCount);
    setEl('ms-plan-count', planCount);
    setEl('ms-signal-count', signalCount);
    setEl('ms-candidate-count', candidateCount);

    renderMissedTracking();
  } catch (e) {
    if (tbody) tbody.innerHTML = '<tr><td colspan="9" class="muted" style="text-align:center;">로드 실패: ' + escapeHtml(e.message) + '</td></tr>';
  }
}

function filterMissedTracking(filter) {
  _missedFilter = filter;
  renderMissedTracking();
}

function renderMissedTracking() {
  var tbody = document.getElementById('missed-tracking-tbody');
  if (!tbody) return;

  var rows = _missedTrackingAll;
  if (_missedFilter === 'filter') {
    rows = rows.filter(function(r) { return r.missed_stage.indexOf('S3') !== -1 || r.missed_stage.indexOf('S4') !== -1; });
  } else if (_missedFilter === 'plan') {
    rows = rows.filter(function(r) { return r.missed_stage.indexOf('S5') !== -1; });
  } else if (_missedFilter === 'signal') {
    rows = rows.filter(function(r) { return r.missed_stage.indexOf('S6') !== -1; });
  } else if (_missedFilter === 'candidate') {
    rows = rows.filter(function(r) { return r.improvement_candidate; });
  }

  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="9" class="muted" style="text-align:center;">해당 항목 없음</td></tr>';
    return;
  }

  var stageLabel = {
    'S3_FILTER': 'S3 필터탈락', 'S3_UNIVERSE_FILTER': 'S3 필터탈락',
    'S4_SCREENING': 'S4 스크리닝탈락', 'S4_HYBRID_SCREENING': 'S4 스크리닝탈락',
    'S5_NOT_ASSIGNED': 'S5 미배정',
    'S6_NO_SIGNAL': 'S6 신호미발생',
  };

  var fmtPct = function(v) {
    if (v == null) return '-';
    var n = parseFloat(v);
    if (isNaN(n)) return '-';
    var color = n > 0 ? 'var(--green)' : n < 0 ? 'var(--red, #f85149)' : 'var(--muted)';
    return '<span style="color:' + color + ';">' + (n >= 0 ? '+' : '') + n.toFixed(2) + '%</span>';
  };

  tbody.innerHTML = rows.map(function(r) {
    var stage = stageLabel[r.missed_stage] || r.missed_stage;
    var price = r.entry_price ? Number(r.entry_price).toLocaleString() + '원' : '-';
    var candiBadge = r.improvement_candidate
      ? '<span style="color:var(--warn); font-size:11px;">★ 개선후보</span>'
      : '-';
    return '<tr>'
      + '<td>' + escapeHtml(r.symbol) + '</td>'
      + '<td>' + escapeHtml(r.symbol_name) + '</td>'
      + '<td><span style="font-size:11px; color:var(--muted);">' + escapeHtml(stage) + '</span></td>'
      + '<td style="font-size:11px; color:var(--muted);">' + escapeHtml(r.missed_reason || '-') + '</td>'
      + '<td>' + price + '</td>'
      + '<td>' + fmtPct(r.ret_10m) + '</td>'
      + '<td>' + fmtPct(r.ret_30m) + '</td>'
      + '<td>' + fmtPct(r.ret_eod) + '</td>'
      + '<td>' + candiBadge + '</td>'
      + '</tr>';
  }).join('');
}
```

---

## 작업 5 — showScreen 진입 핸들러 수정

`showScreen()` 내 `shadow-trading` 분기를 수정:

```javascript
if (name === "shadow-trading") {
  loadMissedTracking();
}
```

`missed-opportunity` 분기는 제거한다.

---

## 검증

```bash
python3 -c "
from html.parser import HTMLParser
with open('backend/static/console.html', encoding='utf-8') as f:
    HTMLParser().feed(f.read())
print('HTML parse OK')
"

# missed-opportunity 버튼/option 제거 확인
grep -c "missed-opportunity" backend/static/console.html || echo "0"

# 통합 함수 추가 확인
grep -c "loadMissedTracking\|renderMissedTracking" backend/static/console.html
```

---

## 완료 체크리스트

- [ ] 사이드바: missed-opportunity 버튼 제거, shadow-trading → "미진입 추적"
- [ ] 모바일: missed-opportunity option 제거
- [ ] `screen-shadow-trading` 통합 화면으로 교체
- [ ] `screen-missed-opportunity` 섹션 삭제
- [ ] `loadMissedTracking()`, `renderMissedTracking()`, `filterMissedTracking()` 추가
- [ ] showScreen 핸들러 수정
- [ ] HTML parse OK

결과는 `docs/agent-comm/OUTBOX_EXECUTOR_shadow_missed_merge.md`에 작성하라.
