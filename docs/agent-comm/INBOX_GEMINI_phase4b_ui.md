# INBOX_GEMINI_phase4b_ui

## 역할
너는 Frontend 담당이다. `backend/static/console.html`만 수정한다.
완료 후 `docs/agent-comm/OUTBOX_GEMINI_phase4b_ui.md`에 결과를 작성하라.

---

## 목표
Expert Knowledge Base UI를 추가한다.
새 화면("Expert Knowledge")을 사이드바 메뉴에 추가하고,
지식 항목 목록/등록/승인 기능을 구현한다.

---

## 작업 1 — 사이드바에 Expert Knowledge 메뉴 추가

### 현재 사이드바 버튼 패턴 (참고용)
```html
<button class="active" data-screen="today">Today Control <small>main</small></button>
<button data-screen="funnel">Funnel Monitor <small>screening</small></button>
```

### 추가할 버튼
`Funnel Monitor` 버튼 다음에 추가:
```html
<button data-screen="expert-knowledge">Expert Knowledge <small>knowledge</small></button>
```

select 드롭다운(모바일용)에도 추가:
```html
<option value="expert-knowledge">Expert Knowledge</option>
```

---

## 작업 2 — Expert Knowledge 화면 신규 추가

`id="screen-funnel"` 섹션 바로 뒤에 아래 섹션을 삽입한다.

```html
<section class="screen" id="screen-expert-knowledge">
  <div class="page-head">
    <div>
      <h1 class="page-title">Expert Knowledge</h1>
      <p class="page-desc">운영자가 등록한 정성적 전략 지식을 관리합니다. 승인된 항목만 S3/S4/S5에 자동 주입됩니다.</p>
    </div>
    <button class="btn" onclick="loadExpertKnowledge()">새로고침</button>
  </div>

  <!-- 등록 폼 -->
  <div class="card" id="ek-form-card">
    <div class="card-title">새 지식 등록</div>
    <div class="form-grid">
      <div class="form-row">
        <label>제목</label>
        <input type="text" id="ek-title" placeholder="예: THEME_SPIKE 오전 집중 효과" style="width:100%">
      </div>
      <div class="form-row">
        <label>내용</label>
        <textarea id="ek-content" rows="3" placeholder="구체적인 전략 지식을 입력하세요" style="width:100%"></textarea>
      </div>
      <div class="form-row cols-3">
        <div>
          <label>적용 범위</label>
          <select id="ek-scope">
            <option value="ALL">ALL (전체)</option>
            <option value="S3_UNIVERSE_FILTER">S3 Universe Filter</option>
            <option value="S4_HYBRID_SCREENING">S4 Hybrid Screening</option>
            <option value="S5_DAILY_PLAN">S5 Daily Plan</option>
          </select>
        </div>
        <div>
          <label>카테고리</label>
          <select id="ek-category">
            <option value="general">general</option>
            <option value="timing">timing</option>
            <option value="sector">sector</option>
            <option value="profile">profile</option>
            <option value="risk">risk</option>
          </select>
        </div>
        <div>
          <label>우선순위 (1=높음)</label>
          <input type="number" id="ek-priority" value="5" min="1" max="10">
        </div>
      </div>
      <div class="form-row">
        <button class="btn primary" onclick="submitKnowledge()">등록</button>
      </div>
    </div>
  </div>

  <!-- 목록 -->
  <div class="section-gap"></div>
  <div class="card">
    <div class="card-title">지식 목록</div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>제목</th><th>범위</th><th>카테고리</th><th>우선순위</th><th>상태</th><th>등록일</th><th>액션</th>
          </tr>
        </thead>
        <tbody id="ek-list-tbody">
          <tr><td colspan="7" class="muted" style="text-align:center">새로고침을 눌러 불러오기</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</section>
```

---

## 작업 3 — JS 함수 추가

아래 JS 함수들을 기존 `<script>` 섹션에 추가한다.

```javascript
// Expert Knowledge 목록 로드
async function loadExpertKnowledge() {
  try {
    const res = await fetch('/api/v1/expert-knowledge/');
    if (!res.ok) return;
    const data = await res.json();
    const items = data.payload || [];
    renderKnowledgeList(items);
  } catch (e) {
    console.warn('loadExpertKnowledge error', e);
  }
}

function renderKnowledgeList(items) {
  const tbody = document.getElementById('ek-list-tbody');
  if (!tbody) return;
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="muted" style="text-align:center">등록된 지식 없음</td></tr>';
    return;
  }
  tbody.innerHTML = items.map(item => {
    const statusClass = item.status === 'approved' ? 'ok' : item.status === 'rejected' ? 'fail' : 'info';
    const actionBtns = item.status === 'pending'
      ? `<button class="btn small secondary" onclick="approveKnowledge('${item.id}')">승인</button>
         <button class="btn small" onclick="rejectKnowledge('${item.id}')">거부</button>`
      : `<span class="muted">${item.status}</span>`;
    return `<tr>
      <td>${item.title}</td>
      <td><span class="tag">${item.scope}</span></td>
      <td>${item.category}</td>
      <td>${item.priority}</td>
      <td><span class="status ${statusClass}">${item.status}</span></td>
      <td>${(item.created_at || '').slice(0, 10)}</td>
      <td>${actionBtns}</td>
    </tr>`;
  }).join('');
}

async function submitKnowledge() {
  const title = document.getElementById('ek-title')?.value?.trim();
  const content = document.getElementById('ek-content')?.value?.trim();
  const scope = document.getElementById('ek-scope')?.value;
  const category = document.getElementById('ek-category')?.value;
  const priority = parseInt(document.getElementById('ek-priority')?.value || '5');

  if (!title || !content) {
    showToast('제목과 내용을 입력하세요', 'error');
    return;
  }

  try {
    const res = await fetch('/api/v1/expert-knowledge/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, content, scope, category, priority, auto_inject: false }),
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast('지식 등록 완료');
      document.getElementById('ek-title').value = '';
      document.getElementById('ek-content').value = '';
      await loadExpertKnowledge();
    } else {
      showToast('등록 실패: ' + (data.detail || 'unknown'), 'error');
    }
  } catch (e) {
    showToast('오류: ' + e.message, 'error');
  }
}

async function approveKnowledge(itemId) {
  try {
    const res = await fetch(`/api/v1/expert-knowledge/${itemId}/approve`, { method: 'POST' });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast('승인 완료');
      await loadExpertKnowledge();
    } else {
      showToast('승인 실패', 'error');
    }
  } catch (e) {
    showToast('오류: ' + e.message, 'error');
  }
}

async function rejectKnowledge(itemId) {
  try {
    const res = await fetch(`/api/v1/expert-knowledge/${itemId}/reject`, { method: 'POST' });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast('거부 완료');
      await loadExpertKnowledge();
    } else {
      showToast('거부 실패', 'error');
    }
  } catch (e) {
    showToast('오류: ' + e.message, 'error');
  }
}
```

화면 전환 시 `screen-expert-knowledge`가 활성화될 때 `loadExpertKnowledge()`가 호출되도록 한다.
기존 화면 전환 로직(`showScreen` 또는 `data-screen` 핸들러)에서 `expert-knowledge` case를 추가한다.

---

## 검증

```bash
grep -c "screen-expert-knowledge\|Expert Knowledge\|loadExpertKnowledge" backend/static/console.html
# → 3 이상

grep -c "ek-list-tbody\|submitKnowledge\|approveKnowledge" backend/static/console.html
# → 3 이상
```

---

## 완료 체크리스트

- [x] 작업 1 — 사이드바 메뉴 추가
- [x] 작업 2 — Expert Knowledge 화면 추가
- [x] 작업 3 — JS 함수 추가 및 화면 전환 연결
- [x] 검증 통과

결과는 `docs/agent-comm/OUTBOX_GEMINI_phase4b_ui.md`에 작성하라.
