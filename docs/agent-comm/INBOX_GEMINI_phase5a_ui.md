# INBOX_GEMINI_phase5a_ui

## 역할
너는 Frontend 담당이다. `backend/static/console.html`만 수정한다.
완료 후 `docs/agent-comm/OUTBOX_GEMINI_phase5a_ui.md`에 결과를 작성하라.

---

## 작업 1 — Data & API 화면에 Data Quality Guard 카드 추가

`id="screen-data"` 내부의 System Health 카드(`<div class="card" style="margin-bottom:16px;">`) 바로 위에 추가한다.

```html
<div class="card" style="margin-bottom:16px;">
  <div class="card-title">Data Quality Guard</div>
  <div class="grid cols-2">
    <div class="natural-card">
      <h4>전체 상태</h4>
      <p><span class="status ok" id="dq-overall-status">NORMAL</span></p>
      <p class="muted" id="dq-overall-detail">데이터 이상 없음</p>
    </div>
    <div class="natural-card">
      <h4>오늘 이벤트</h4>
      <p><span class="metric" id="dq-event-count" style="font-size:1.5rem">0</span></p>
      <p class="muted" id="dq-event-detail">이상 이벤트 수</p>
    </div>
  </div>
  <div style="margin-top:8px; font-size:12px; color:var(--muted);" id="dq-event-breakdown">
    이벤트 유형별 현황 로딩 중...
  </div>
</div>
```

---

## 작업 2 — Alert Center 사이드바 메뉴 및 화면 추가

### 2-1. 사이드바
`Expert Knowledge` 버튼 다음에 추가:
```html
<button data-screen="alerts">Alert Center <small>alerts</small></button>
```
모바일 select에도 추가:
```html
<option value="alerts">Alert Center</option>
```

### 2-2. Alert Center 화면 (`id="screen-expert-knowledge"` 섹션 바로 뒤에 추가)

```html
<section class="screen" id="screen-alerts">
  <div class="page-head">
    <div>
      <h1 class="page-title">Alert Center</h1>
      <p class="page-desc">시스템 이상 알림을 확인하고 처리합니다.</p>
    </div>
    <button class="btn" onclick="loadAlerts()">새로고침</button>
  </div>

  <!-- 요약 카드 -->
  <div class="grid cols-4" style="margin-bottom:16px">
    <div class="card compact"><div class="card-title">전체 알림</div><div class="metric" id="al-total">-</div></div>
    <div class="card compact"><div class="card-title">Critical</div><div class="metric" style="color:#f85149" id="al-critical">-</div></div>
    <div class="card compact"><div class="card-title">Warning</div><div class="metric" style="color:#d29922" id="al-warning">-</div></div>
    <div class="card compact"><div class="card-title">미확인</div><div class="metric" style="color:#6cb6ff" id="al-unacked">-</div></div>
  </div>

  <!-- 알림 목록 -->
  <div class="card">
    <div class="card-title">알림 목록 <span>오늘</span></div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>심각도</th><th>유형</th><th>제목</th><th>상세</th><th>시간</th><th>상태</th><th>액션</th></tr>
        </thead>
        <tbody id="al-list-tbody">
          <tr><td colspan="7" class="muted" style="text-align:center">새로고침을 눌러 불러오기</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</section>
```

---

## 작업 3 — Human Approval Queue 사이드바 메뉴 및 화면 추가

### 3-1. 사이드바
`Alert Center` 버튼 다음에 추가:
```html
<button data-screen="approval">Approval Queue <small>approval</small></button>
```
모바일 select에도 추가:
```html
<option value="approval">Approval Queue</option>
```

### 3-2. Approval Queue 화면 (`id="screen-alerts"` 뒤에 추가)

```html
<section class="screen" id="screen-approval">
  <div class="page-head">
    <div>
      <h1 class="page-title">Approval Queue</h1>
      <p class="page-desc">위험 변경사항에 대한 승인 요청을 관리합니다.</p>
    </div>
    <button class="btn" onclick="loadApprovalQueue()">새로고침</button>
  </div>

  <div class="card">
    <div class="card-title">승인 대기 목록</div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>유형</th><th>제목</th><th>설명</th><th>상태</th><th>등록일</th><th>액션</th></tr>
        </thead>
        <tbody id="aq-list-tbody">
          <tr><td colspan="6" class="muted" style="text-align:center">새로고침을 눌러 불러오기</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</section>
```

---

## 작업 4 — JS 함수 추가

```javascript
// Data Quality Guard 로드
async function loadDQStatus() {
  try {
    const res = await fetch('/api/v1/data-quality/status');
    if (!res.ok) return;
    const data = await res.json();
    const p = data.payload || {};
    const el = document.getElementById('dq-overall-status');
    if (el) {
      el.textContent = p.overall_status || 'NORMAL';
      el.className = 'status ' + ({
        NORMAL: 'ok', WARNING: 'warn', DEGRADED: 'warn',
        BLOCK_NEW_ENTRY: 'fail', EMERGENCY: 'fail'
      }[p.overall_status] || 'info');
    }
    const detail = document.getElementById('dq-overall-detail');
    if (detail) detail.textContent = p.overall_status === 'NORMAL' ? '데이터 이상 없음' : '이상 감지됨';
    const count = document.getElementById('dq-event-count');
    const events = p.events || [];
    if (count) count.textContent = events.length;
    const breakdown = document.getElementById('dq-event-breakdown');
    if (breakdown) {
      const counts = {};
      events.forEach(e => { counts[e.event_type] = (counts[e.event_type] || 0) + 1; });
      breakdown.textContent = Object.entries(counts).map(([k, v]) => `${k}: ${v}`).join(' | ') || '이벤트 없음';
    }
  } catch (e) { console.warn('loadDQStatus error', e); }
}

// Alert Center 로드
async function loadAlerts() {
  try {
    const [listRes, summaryRes] = await Promise.all([
      fetch('/api/v1/alerts/'),
      fetch('/api/v1/alerts/summary'),
    ]);
    if (summaryRes.ok) {
      const sum = await summaryRes.json();
      const s = sum.payload || {};
      const setEl = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v ?? '-'; };
      setEl('al-total', s.total);
      setEl('al-critical', s.by_severity?.CRITICAL ?? 0);
      setEl('al-warning', s.by_severity?.WARNING ?? 0);
      setEl('al-unacked', s.unacknowledged);
    }
    if (listRes.ok) {
      const list = await listRes.json();
      const items = list.payload || [];
      const tbody = document.getElementById('al-list-tbody');
      if (!tbody) return;
      if (!items.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="muted" style="text-align:center">알림 없음</td></tr>';
        return;
      }
      tbody.innerHTML = items.map(a => {
        const cls = a.severity === 'CRITICAL' ? 'fail' : a.severity === 'WARNING' ? 'warn' : 'info';
        const ackBtn = !a.acknowledged
          ? `<button class="btn small secondary" onclick="ackAlert('${a.id}')">확인</button>`
          : '<span class="muted">확인됨</span>';
        return `<tr>
          <td><span class="status ${cls}">${a.severity}</span></td>
          <td>${a.alert_type}</td>
          <td>${a.title}</td>
          <td class="muted" style="font-size:0.85em">${a.detail || '-'}</td>
          <td>${(a.created_at || '').slice(11, 19)}</td>
          <td>${a.acknowledged ? '확인됨' : '미확인'}</td>
          <td>${ackBtn}</td>
        </tr>`;
      }).join('');
    }
  } catch (e) { console.warn('loadAlerts error', e); }
}

async function ackAlert(alertId) {
  try {
    const res = await fetch(`/api/v1/alerts/${alertId}/acknowledge`, { method: 'POST' });
    if (res.ok) { showToast('알림 확인 처리됨'); await loadAlerts(); }
  } catch (e) { showToast('오류: ' + e.message, 'error'); }
}

// Approval Queue 로드
async function loadApprovalQueue() {
  try {
    const res = await fetch('/api/v1/approval/');
    if (!res.ok) return;
    const data = await res.json();
    const items = data.payload || [];
    const tbody = document.getElementById('aq-list-tbody');
    if (!tbody) return;
    if (!items.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="muted" style="text-align:center">승인 요청 없음</td></tr>';
      return;
    }
    tbody.innerHTML = items.map(r => {
      const cls = r.status === 'pending' ? 'warn' : r.status === 'approved' ? 'ok' : 'fail';
      const btns = r.status === 'pending'
        ? `<button class="btn small secondary" onclick="approveRequest('${r.id}')">승인</button>
           <button class="btn small" onclick="rejectRequest('${r.id}')">거부</button>
           <button class="btn small" onclick="deferRequest('${r.id}')">보류</button>`
        : `<span class="muted">${r.status}</span>`;
      return `<tr>
        <td>${r.change_type}</td>
        <td>${r.title}</td>
        <td class="muted" style="font-size:0.85em">${r.description || '-'}</td>
        <td><span class="status ${cls}">${r.status}</span></td>
        <td>${(r.created_at || '').slice(0, 10)}</td>
        <td>${btns}</td>
      </tr>`;
    }).join('');
  } catch (e) { console.warn('loadApprovalQueue error', e); }
}

async function approveRequest(id) {
  const res = await fetch(`/api/v1/approval/${id}/approve`, { method: 'POST' });
  if (res.ok) { showToast('승인 완료'); await loadApprovalQueue(); }
}
async function rejectRequest(id) {
  const res = await fetch(`/api/v1/approval/${id}/reject`, { method: 'POST' });
  if (res.ok) { showToast('거부 완료'); await loadApprovalQueue(); }
}
async function deferRequest(id) {
  const res = await fetch(`/api/v1/approval/${id}/defer`, { method: 'POST' });
  if (res.ok) { showToast('보류 처리됨'); await loadApprovalQueue(); }
}
```

### 화면 전환 연결
`showScreen` 또는 `data-screen` 핸들러에서:
- `alerts` → `loadAlerts()` 호출
- `approval` → `loadApprovalQueue()` 호출
- `data` 화면 활성화 시 기존 로직 외에 `loadDQStatus()` 추가 호출

---

## 검증

```bash
grep -c "screen-alerts\|Alert Center\|loadAlerts" backend/static/console.html
# → 3 이상

grep -c "screen-approval\|Approval Queue\|loadApprovalQueue" backend/static/console.html
# → 3 이상

grep -c "dq-overall-status\|loadDQStatus" backend/static/console.html
# → 2 이상
```

---

## 완료 체크리스트

- [x] 작업 1 — Data Quality Guard 카드 추가 (Data & API 화면)
- [x] 작업 2 — Alert Center 화면 + 사이드바
- [x] 작업 3 — Approval Queue 화면 + 사이드바
- [x] 작업 4 — JS 함수 추가 및 화면 전환 연결
- [x] 검증 통과

결과는 `docs/agent-comm/OUTBOX_GEMINI_phase5a_ui.md`에 작성하라.
