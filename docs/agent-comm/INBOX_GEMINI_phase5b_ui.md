# INBOX_GEMINI_phase5b_ui

## 역할
너는 Frontend 담당이다. `backend/static/console.html`만 수정한다.
완료 후 `docs/agent-comm/OUTBOX_GEMINI_phase5b_ui.md`에 결과를 작성하라.

---

## 작업 1 — 사이드바에 "판단 검증" 섹션 메뉴 추가

`Approval Queue` 버튼 다음에 아래 4개 버튼을 추가한다.

```html
<div class="nav-section-label">판단 검증</div>
<button data-screen="shadow-trading">Shadow Trading <small>shadow</small></button>
<button data-screen="missed-opportunity">Missed Opportunity <small>missed</small></button>
<button data-screen="false-positive">False Positive <small>fp</small></button>
<button data-screen="confidence-cal">Confidence Cal. <small>conf-cal</small></button>
```

모바일 select에도 추가:
```html
<option value="shadow-trading">Shadow Trading</option>
<option value="missed-opportunity">Missed Opportunity</option>
<option value="false-positive">False Positive</option>
<option value="confidence-cal">Confidence Cal.</option>
```

---

## 작업 2 — Shadow Trading 화면

`id="screen-approval"` 섹션 바로 뒤에 추가.

```html
<section class="screen" id="screen-shadow-trading">
  <div class="page-head">
    <div>
      <h1 class="page-title">Shadow Trading</h1>
      <p class="page-desc">미진입 종목을 가상으로 추적해 놓친 수익 기회를 분석합니다.</p>
    </div>
    <button class="btn" onclick="loadShadowTrading()">새로고침</button>
  </div>

  <!-- 요약 카드 -->
  <div class="grid cols-3" style="margin-bottom:16px">
    <div class="card compact"><div class="card-title">총 Shadow Trades</div><div class="metric" id="st-total">-</div></div>
    <div class="card compact"><div class="card-title">평균 가상 손익</div><div class="metric" id="st-avg-pnl">-</div></div>
    <div class="card compact"><div class="card-title">양성 비율</div><div class="metric" id="st-positive-rate">-</div></div>
  </div>

  <!-- 목록 -->
  <div class="card">
    <div class="card-title">오늘 Shadow Trade 목록</div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>종목</th><th>미진입 단계</th><th>진입가</th><th>청산가</th><th>가상 손익(%)</th><th>상태</th></tr>
        </thead>
        <tbody id="st-list-tbody">
          <tr><td colspan="6" class="muted" style="text-align:center">새로고침을 눌러 불러오기</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</section>
```

---

## 작업 3 — Missed Opportunity 화면

`id="screen-shadow-trading"` 바로 뒤에 추가.

```html
<section class="screen" id="screen-missed-opportunity">
  <div class="page-head">
    <div>
      <h1 class="page-title">Missed Opportunity</h1>
      <p class="page-desc">필터에서 탈락한 종목의 이후 수익을 추적합니다.</p>
    </div>
    <button class="btn" onclick="loadMissedOpportunity()">새로고침</button>
  </div>

  <div class="grid cols-2" style="margin-bottom:16px">
    <div class="card">
      <div class="card-title">오늘 Missed Opportunity 목록</div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>종목</th><th>탈락 단계</th><th>이유</th><th>탈락 시 가격</th><th>10분 후</th><th>30분 후</th><th>EOD</th></tr>
          </thead>
          <tbody id="mo-all-tbody">
            <tr><td colspan="7" class="muted" style="text-align:center">새로고침을 눌러 불러오기</td></tr>
          </tbody>
        </table>
      </div>
    </div>
    <div class="card">
      <div class="card-title">개선 후보</div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>종목</th><th>탈락 단계</th><th>EOD 수익률</th></tr>
          </thead>
          <tbody id="mo-candidate-tbody">
            <tr><td colspan="3" class="muted" style="text-align:center">새로고침을 눌러 불러오기</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</section>
```

---

## 작업 4 — False Positive 화면

`id="screen-missed-opportunity"` 바로 뒤에 추가.

```html
<section class="screen" id="screen-false-positive">
  <div class="page-head">
    <div>
      <h1 class="page-title">False Positive</h1>
      <p class="page-desc">진입 후 손실이 난 종목의 원인을 분석합니다.</p>
    </div>
    <button class="btn" onclick="loadFalsePositive()">새로고침</button>
  </div>

  <div class="card">
    <div class="card-title">오늘 False Positive 목록</div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>종목</th><th>유형</th><th>원점수</th><th>Confidence</th><th>진입 이유</th><th>손실 이유</th></tr>
        </thead>
        <tbody id="fp-list-tbody">
          <tr><td colspan="6" class="muted" style="text-align:center">새로고침을 눌러 불러오기</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</section>
```

---

## 작업 5 — Confidence Calibration 화면

`id="screen-false-positive"` 바로 뒤에 추가.

```html
<section class="screen" id="screen-confidence-cal">
  <div class="page-head">
    <div>
      <h1 class="page-title">Confidence Calibration</h1>
      <p class="page-desc">Confidence 구간별 예측 정확도를 분석합니다.</p>
    </div>
    <div>
      <button class="btn secondary" onclick="runConfidenceCalibration()">캘리브레이션 실행</button>
      <button class="btn" onclick="loadConfidenceCalibration()">새로고침</button>
    </div>
  </div>

  <div class="card">
    <div class="card-title">오늘 Confidence Calibration 결과</div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>구간</th><th>거래 수</th><th>승률 (실제)</th><th>승률 (예상)</th><th>평균 손익</th></tr>
        </thead>
        <tbody id="cc-list-tbody">
          <tr><td colspan="5" class="muted" style="text-align:center">새로고침을 눌러 불러오기</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</section>
```

---

## 작업 6 — JS 함수 추가

기존 `ackAlert`, `approveRequest` 등 함수 아래에 추가한다.

```javascript
// Shadow Trading
async function loadShadowTrading() {
  try {
    const [sumRes, listRes] = await Promise.all([
      fetch('/api/v1/shadow-trading/summary'),
      fetch('/api/v1/shadow-trading/today'),
    ]);
    if (sumRes.ok) {
      const sum = await sumRes.json();
      const s = sum.payload || {};
      const setEl = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v ?? '-'; };
      setEl('st-total', s.total_count ?? s.total ?? '-');
      setEl('st-avg-pnl', s.avg_pnl != null ? s.avg_pnl.toFixed(2) + '%' : '-');
      setEl('st-positive-rate', s.positive_rate != null ? (s.positive_rate * 100).toFixed(1) + '%' : '-');
    }
    if (listRes.ok) {
      const list = await listRes.json();
      const items = list.payload || [];
      const tbody = document.getElementById('st-list-tbody');
      if (!tbody) return;
      if (!items.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="muted" style="text-align:center">데이터 없음</td></tr>';
        return;
      }
      tbody.innerHTML = items.map(t => `<tr>
        <td>${t.symbol_name || t.symbol}</td>
        <td>${t.missed_stage}</td>
        <td>${t.entry_price?.toLocaleString() ?? '-'}</td>
        <td>${t.exit_price?.toLocaleString() ?? '-'}</td>
        <td style="color:${(t.shadow_pnl||0)>=0?'#3fb950':'#f85149'}">${t.shadow_pnl != null ? t.shadow_pnl.toFixed(2)+'%' : '-'}</td>
        <td><span class="status ${t.status==='active'?'warn':'ok'}">${t.status}</span></td>
      </tr>`).join('');
    }
  } catch (e) { console.warn('loadShadowTrading error', e); }
}

// Missed Opportunity
async function loadMissedOpportunity() {
  try {
    const [allRes, candRes] = await Promise.all([
      fetch('/api/v1/missed-opportunity/today'),
      fetch('/api/v1/missed-opportunity/candidates'),
    ]);
    if (allRes.ok) {
      const data = await allRes.json();
      const items = data.payload || [];
      const tbody = document.getElementById('mo-all-tbody');
      if (tbody) {
        if (!items.length) {
          tbody.innerHTML = '<tr><td colspan="7" class="muted" style="text-align:center">데이터 없음</td></tr>';
        } else {
          tbody.innerHTML = items.map(m => `<tr>
            <td>${m.symbol_name || m.symbol}</td>
            <td>${m.missed_stage}</td>
            <td class="muted" style="font-size:0.85em">${m.missed_reason}</td>
            <td>${m.price_at_missed?.toLocaleString() ?? '-'}</td>
            <td style="color:${(m.max_return_after_10m||0)>=0?'#3fb950':'#f85149'}">${m.max_return_after_10m != null ? m.max_return_after_10m.toFixed(2)+'%' : '-'}</td>
            <td style="color:${(m.max_return_after_30m||0)>=0?'#3fb950':'#f85149'}">${m.max_return_after_30m != null ? m.max_return_after_30m.toFixed(2)+'%' : '-'}</td>
            <td style="color:${(m.max_return_until_eod||0)>=0?'#3fb950':'#f85149'}">${m.max_return_until_eod != null ? m.max_return_until_eod.toFixed(2)+'%' : '-'}</td>
          </tr>`).join('');
        }
      }
    }
    if (candRes.ok) {
      const data = await candRes.json();
      const items = data.payload || [];
      const tbody = document.getElementById('mo-candidate-tbody');
      if (tbody) {
        if (!items.length) {
          tbody.innerHTML = '<tr><td colspan="3" class="muted" style="text-align:center">후보 없음</td></tr>';
        } else {
          tbody.innerHTML = items.map(m => `<tr>
            <td>${m.symbol_name || m.symbol}</td>
            <td>${m.missed_stage}</td>
            <td style="color:${(m.max_return_until_eod||0)>=0?'#3fb950':'#f85149'}">${m.max_return_until_eod != null ? m.max_return_until_eod.toFixed(2)+'%' : '-'}</td>
          </tr>`).join('');
        }
      }
    }
  } catch (e) { console.warn('loadMissedOpportunity error', e); }
}

// False Positive
async function loadFalsePositive() {
  try {
    const res = await fetch('/api/v1/false-positive/today');
    if (!res.ok) return;
    const data = await res.json();
    const items = data.payload || [];
    const tbody = document.getElementById('fp-list-tbody');
    if (!tbody) return;
    if (!items.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="muted" style="text-align:center">데이터 없음</td></tr>';
      return;
    }
    tbody.innerHTML = items.map(f => `<tr>
      <td>${f.symbol_name || f.symbol}</td>
      <td>${f.false_positive_type}</td>
      <td>${f.original_score != null ? f.original_score.toFixed(2) : '-'}</td>
      <td>${f.original_confidence != null ? (f.original_confidence*100).toFixed(1)+'%' : '-'}</td>
      <td class="muted" style="font-size:0.85em">${f.entry_reason || '-'}</td>
      <td class="muted" style="font-size:0.85em">${f.loss_reason || '-'}</td>
    </tr>`).join('');
  } catch (e) { console.warn('loadFalsePositive error', e); }
}

// Confidence Calibration
async function loadConfidenceCalibration() {
  try {
    const res = await fetch('/api/v1/confidence-calibration/today');
    if (!res.ok) return;
    const data = await res.json();
    const items = data.payload || [];
    const tbody = document.getElementById('cc-list-tbody');
    if (!tbody) return;
    if (!items.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="muted" style="text-align:center">데이터 없음 (실행 버튼 클릭)</td></tr>';
      return;
    }
    tbody.innerHTML = items.map(c => `<tr>
      <td>${c.bin_label}</td>
      <td>${c.trade_count}</td>
      <td style="color:${(c.actual_win_rate||0)>=(c.expected_win_rate||0)?'#3fb950':'#f85149'}">${c.actual_win_rate != null ? (c.actual_win_rate*100).toFixed(1)+'%' : '-'}</td>
      <td>${c.expected_win_rate != null ? (c.expected_win_rate*100).toFixed(1)+'%' : '-'}</td>
      <td style="color:${(c.avg_pnl||0)>=0?'#3fb950':'#f85149'}">${c.avg_pnl != null ? c.avg_pnl.toFixed(2)+'%' : '-'}</td>
    </tr>`).join('');
  } catch (e) { console.warn('loadConfidenceCalibration error', e); }
}

async function runConfidenceCalibration() {
  try {
    const res = await fetch('/api/v1/confidence-calibration/run', { method: 'POST' });
    if (res.ok) { showToast('캘리브레이션 완료'); await loadConfidenceCalibration(); }
    else showToast('실행 실패', 'error');
  } catch (e) { showToast('오류: ' + e.message, 'error'); }
}
```

### 화면 전환 연결
`showScreen` 또는 `data-screen` 핸들러에서:
- `shadow-trading` → `loadShadowTrading()` 호출
- `missed-opportunity` → `loadMissedOpportunity()` 호출
- `false-positive` → `loadFalsePositive()` 호출
- `confidence-cal` → `loadConfidenceCalibration()` 호출

---

## 검증

```bash
grep -c "screen-shadow-trading\|Shadow Trading\|loadShadowTrading" backend/static/console.html
# → 3 이상

grep -c "screen-missed-opportunity\|Missed Opportunity\|loadMissedOpportunity" backend/static/console.html
# → 3 이상

grep -c "screen-false-positive\|False Positive\|loadFalsePositive" backend/static/console.html
# → 3 이상

grep -c "screen-confidence-cal\|Confidence Cal\|loadConfidenceCalibration" backend/static/console.html
# → 3 이상
```

---

## 완료 체크리스트

- [ ] 작업 1 — 사이드바 메뉴 4개 추가
- [ ] 작업 2 — Shadow Trading 화면
- [ ] 작업 3 — Missed Opportunity 화면
- [ ] 작업 4 — False Positive 화면
- [ ] 작업 5 — Confidence Calibration 화면
- [ ] 작업 6 — JS 함수 추가 및 화면 전환 연결
- [ ] 검증 통과

결과는 `docs/agent-comm/OUTBOX_GEMINI_phase5b_ui.md`에 작성하라.
