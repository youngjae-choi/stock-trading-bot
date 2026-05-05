# INBOX_GEMINI_phase3_ui

## 역할
너는 Frontend 담당이다. `backend/static/console.html` 파일만 수정한다.
작업 완료 후 `docs/agent-comm/OUTBOX_GEMINI_phase3_ui.md`에 결과를 작성하라.

---

## 작업 1 — Review & Audit 화면 문구 변경

`backend/static/console.html`에서 아래 문구를 찾아 교체한다.

**찾을 문구:**
```
복기의 목적은 리포트가 아니라 학습입니다. 좋은 전략, 나쁜 전략, 좋은 타이밍을 구조화해서 다음 RulePack에 반영합니다.
```

**교체할 문구:**
```
복기의 목적은 리포트가 아니라 학습입니다. 당일 매매 결과와 미진입 사유를 구조화하여 Learning Memory로 저장하고, 다음 거래일 S3~S5와 Daily Trading Plan 생성에 반영합니다.
```

---

## 작업 2 — Review & Audit 화면에 6개 영역 추가

Review & Audit 화면의 기존 콘텐츠 영역(일별 거래 이력, 총 손익 카드 등) 아래에 아래 6개 섹션을 추가한다.
기존 UI는 건드리지 않는다. 추가만 한다.

### 2-1. Rule Context 섹션

```html
<section class="card" id="ra-rule-context">
  <h3>Rule Context</h3>
  <div class="info-grid">
    <span class="label">Base RulePack Ver</span><span id="ra-rulepack-ver" class="value">—</span>
    <span class="label">Risk Profile Pack Ver</span><span id="ra-profile-pack-ver" class="value">—</span>
    <span class="label">Daily Plan ID</span><span id="ra-daily-plan-id" class="value">—</span>
  </div>
</section>
```

### 2-2. Risk Profile Performance 섹션

```html
<section class="card" id="ra-profile-performance">
  <h3>Risk Profile Performance</h3>
  <table class="data-table" id="ra-profile-table">
    <thead>
      <tr>
        <th>Profile</th><th>거래수</th><th>승률</th><th>평균손익</th>
      </tr>
    </thead>
    <tbody id="ra-profile-tbody">
      <tr><td colspan="4" class="muted">데이터 없음</td></tr>
    </tbody>
  </table>
</section>
```

### 2-3. Exit Reason Analysis 섹션

```html
<section class="card" id="ra-exit-reason">
  <h3>Exit Reason Analysis</h3>
  <table class="data-table" id="ra-exit-table">
    <thead>
      <tr>
        <th>청산 사유</th><th>건수</th><th>평균손익</th>
      </tr>
    </thead>
    <tbody id="ra-exit-tbody">
      <tr><td colspan="3" class="muted">데이터 없음</td></tr>
    </tbody>
  </table>
</section>
```

### 2-4. Trailing Stop Quality 섹션

```html
<section class="card" id="ra-trailing-quality">
  <h3>Trailing Stop Quality</h3>
  <div class="info-grid">
    <span class="label">평균 수익 회수율</span><span id="ra-trailing-recovery" class="value">—</span>
    <span class="label">조기 청산 비율</span><span id="ra-trailing-early" class="value">—</span>
    <span class="label">Trailing Stop 청산 건수</span><span id="ra-trailing-count" class="value">—</span>
  </div>
</section>
```

### 2-5. No Trade Reason 섹션

```html
<section class="card" id="ra-no-trade">
  <h3>No Trade Reason</h3>
  <div id="ra-no-trade-list" class="tag-list">
    <span class="muted">데이터 없음</span>
  </div>
</section>
```

### 2-6. Learning Memory 섹션

```html
<section class="card" id="ra-learning-memory">
  <h3>Learning Memory</h3>
  <div class="stat-row">
    <div class="stat-item">
      <span class="stat-label">오늘 생성</span>
      <span class="stat-value" id="ra-mem-total">0</span>
    </div>
    <div class="stat-item">
      <span class="stat-label">자동 반영 가능</span>
      <span class="stat-value success" id="ra-mem-auto">0</span>
    </div>
    <div class="stat-item">
      <span class="stat-label">승인 필요</span>
      <span class="stat-value warn" id="ra-mem-approval">0</span>
    </div>
  </div>
  <div class="scope-tags">
    <span class="label">반영 예정</span>
    <span class="tag" id="ra-mem-s3">S3: 0건</span>
    <span class="tag" id="ra-mem-s4">S4: 0건</span>
    <span class="tag" id="ra-mem-s5">S5: 0건</span>
  </div>
  <div id="ra-mem-list" style="margin-top:12px"></div>
  <div style="margin-top:12px">
    <button class="btn secondary" id="ra-build-memory-btn" onclick="buildLearningMemory()">S11 Learning Memory 생성</button>
  </div>
</section>
```

---

## 작업 3 — Review & Audit 화면 JavaScript 추가

`console.html`의 기존 JS 섹션에 아래 함수들을 추가한다 (기존 함수는 건드리지 않는다).

```javascript
// Review & Audit — 데이터 로드
async function loadReviewAuditData() {
  try {
    const today = new Date().toISOString().slice(0, 10);
    // S10 리뷰 결과
    const reviewRes = await fetch('/api/v1/review-audit/today');
    if (reviewRes.ok) {
      const reviewData = await reviewRes.json();
      const p = reviewData.payload || {};
      if (p.profile_summary) renderProfilePerformance(p.profile_summary);
      if (p.exit_summary) renderExitReason(p.exit_summary);
      if (p.trailing_quality) renderTrailingQuality(p.trailing_quality);
    }
    // S11 메모리 결과
    const memRes = await fetch('/api/v1/learning-memory/today');
    if (memRes.ok) {
      const memData = await memRes.json();
      const memories = memData.payload || [];
      renderLearningMemory(memories);
    }
  } catch (e) {
    console.warn('loadReviewAuditData error', e);
  }
}

function renderProfilePerformance(summary) {
  const tbody = document.getElementById('ra-profile-tbody');
  if (!tbody) return;
  const entries = Object.entries(summary);
  if (!entries.length) return;
  tbody.innerHTML = entries.map(([profile, data]) => {
    const wr = data.win_count && data.trade_count
      ? ((data.win_count / data.trade_count) * 100).toFixed(0) + '%'
      : '—';
    const pnl = data.avg_pnl != null ? (data.avg_pnl * 100).toFixed(2) + '%' : '—';
    return `<tr><td>${profile}</td><td>${data.trade_count || 0}</td><td>${wr}</td><td>${pnl}</td></tr>`;
  }).join('');
}

function renderExitReason(summary) {
  const tbody = document.getElementById('ra-exit-tbody');
  if (!tbody) return;
  const entries = Object.entries(summary);
  if (!entries.length) return;
  tbody.innerHTML = entries.map(([reason, data]) => {
    const pnl = data.avg_pnl != null ? (data.avg_pnl * 100).toFixed(2) + '%' : '—';
    return `<tr><td>${reason}</td><td>${data.count || 0}</td><td>${pnl}</td></tr>`;
  }).join('');
}

function renderTrailingQuality(tq) {
  const r = document.getElementById('ra-trailing-recovery');
  const e = document.getElementById('ra-trailing-early');
  const c = document.getElementById('ra-trailing-count');
  if (r) r.textContent = tq.avg_recovery_rate != null ? (tq.avg_recovery_rate * 100).toFixed(1) + '%' : '—';
  if (e) e.textContent = tq.early_exit_rate != null ? (tq.early_exit_rate * 100).toFixed(1) + '%' : '—';
  if (c) c.textContent = tq.total_trailing_exits ?? '—';
}

function renderLearningMemory(memories) {
  const total = memories.length;
  const auto = memories.filter(m => m.auto_apply_allowed).length;
  const approval = memories.filter(m => m.requires_approval).length;
  const s3 = memories.filter(m => m.scope === 'S3_UNIVERSE_FILTER').length;
  const s4 = memories.filter(m => m.scope === 'S4_HYBRID_SCREENING').length;
  const s5 = memories.filter(m => m.scope === 'S5_DAILY_PLAN').length;

  const setEl = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
  setEl('ra-mem-total', total);
  setEl('ra-mem-auto', auto);
  setEl('ra-mem-approval', approval);
  setEl('ra-mem-s3', `S3: ${s3}건`);
  setEl('ra-mem-s4', `S4: ${s4}건`);
  setEl('ra-mem-s5', `S5: ${s5}건`);

  const list = document.getElementById('ra-mem-list');
  if (!list) return;
  if (!total) { list.innerHTML = '<p class="muted">생성된 메모리 없음</p>'; return; }
  list.innerHTML = memories.map(m => `
    <div class="memory-item" style="border-left:3px solid var(--accent);padding:8px 12px;margin-bottom:8px">
      <div><strong>[${m.scope}]</strong> ${m.summary}</div>
      <div class="muted" style="font-size:0.85em">
        auto: ${m.auto_apply_allowed ? 'Yes' : 'No'} |
        approval: ${m.requires_approval ? 'Yes' : 'No'} |
        status: ${m.status}
      </div>
    </div>
  `).join('');
}

async function buildLearningMemory() {
  const btn = document.getElementById('ra-build-memory-btn');
  if (btn) { btn.disabled = true; btn.textContent = '생성 중...'; }
  try {
    const res = await fetch('/api/v1/learning-memory/build', { method: 'POST' });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast('Learning Memory 생성 완료');
      await loadReviewAuditData();
    } else {
      showToast('생성 실패: ' + (data.detail || data.payload?.reason || 'unknown'), 'error');
    }
  } catch (e) {
    showToast('오류: ' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'S11 Learning Memory 생성'; }
  }
}
```

Review & Audit 화면이 열릴 때 `loadReviewAuditData()`를 호출하도록 한다.
화면 전환 함수나 `showScreen('review-audit')` 류 함수 또는 탭/버튼 클릭 핸들러에서 해당 화면 활성화 시 호출 추가.

---

## 작업 4 — KIS System Test 화면에 S11 카드 추가

기존 S5-V 카드 다음에 S11 카드를 추가한다.

```html
<div class="test-card" id="test-s11">
  <div class="test-card-header">
    <span class="status info">S11</span>
    <strong>S11 — Learning Memory Builder</strong>
  </div>
  <p class="muted">Review & Audit 결과를 Learning Memory로 구조화하여 다음 거래일 S3~S5에 반영합니다.</p>
  <button class="btn secondary" onclick="runTestS11()">Learning Memory 생성 실행</button>
  <div id="test-s11-result" class="test-result" style="display:none"></div>
</div>
```

JS 함수 추가:
```javascript
async function runTestS11() {
  const result = document.getElementById('test-s11-result');
  if (result) { result.style.display = 'block'; result.textContent = '실행 중...'; }
  try {
    const res = await fetch('/api/v1/learning-memory/build', { method: 'POST' });
    const data = await res.json();
    if (result) result.textContent = JSON.stringify(data.payload || data, null, 2);
  } catch (e) {
    if (result) result.textContent = '오류: ' + e.message;
  }
}
```

---

## 검증 요구사항

1. `node --check backend/static/console.html` 통과 (JS 문법 오류 없음)
   - HTML 파일이라 직접 node --check는 안 되므로 JS 부분만 임시 파일로 추출해서 확인:
   ```bash
   node -e "require('fs').readFileSync('backend/static/console.html','utf8')" 2>&1 | head -5
   ```
   → 오류 없으면 OK
2. Review & Audit 화면에 6개 섹션 ID 존재 확인:
   ```bash
   grep -c "ra-rule-context\|ra-profile-performance\|ra-exit-reason\|ra-trailing-quality\|ra-no-trade\|ra-learning-memory" backend/static/console.html
   ```
   → 6 이상이면 OK
3. S11 카드 확인:
   ```bash
   grep -c "test-s11\|Learning Memory Builder" backend/static/console.html
   ```
   → 2 이상이면 OK

---

## 완료 기준

- [x] 작업 1 — 문구 변경
- [x] 작업 2 — 6개 섹션 추가
- [x] 작업 3 — JS 함수 추가
- [x] 작업 4 — S11 카드 추가
- [x] 검증 통과

결과는 `docs/agent-comm/OUTBOX_GEMINI_phase3_ui.md`에 작성하라.
