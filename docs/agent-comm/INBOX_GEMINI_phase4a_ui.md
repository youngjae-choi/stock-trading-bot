# INBOX_GEMINI_phase4a_ui

## 역할
너는 Frontend 담당이다. `backend/static/console.html`만 수정한다.
완료 후 `docs/agent-comm/OUTBOX_GEMINI_phase4a_ui.md`에 결과를 작성하라.

---

## 작업 1 — Funnel Monitor 상단 카드에 메모리 카운트 추가

### 현재 상태
`id="screen-funnel"` 내부에 `.grid.cols-4` 카드 영역이 있다.
현재 카드: 전체 종목 / Layer 1 통과 / Layer 2 통과 / 현재 매수대기 / Profile 배정 현황

### 변경
기존 `.grid.cols-4` 바로 아래에 메모리/지식 현황 행을 추가한다.

```html
<div class="grid cols-3" style="margin-top:8px">
  <div class="card compact">
    <div class="card-title">S3 적용 메모리</div>
    <div class="metric" id="funnel-mem-s3">-</div>
    <div class="muted">S3_UNIVERSE_FILTER</div>
  </div>
  <div class="card compact">
    <div class="card-title">S4 적용 메모리</div>
    <div class="metric" id="funnel-mem-s4">-</div>
    <div class="muted">S4_HYBRID_SCREENING</div>
  </div>
  <div class="card compact">
    <div class="card-title">S5 적용 메모리</div>
    <div class="metric" id="funnel-mem-s5">-</div>
    <div class="muted">S5_DAILY_PLAN</div>
  </div>
</div>
```

---

## 작업 2 — 후보 선정 결과 테이블에 memory_refs 컬럼 추가

### 현재 상태
`id="funnel-candidates-tbody"` 상위 테이블 헤더:
```html
<tr>
  <th>종목코드</th><th>종목명</th><th>기술</th><th>기초</th><th>테마</th>
  <th>총점</th><th>AI 신뢰도</th><th>상태</th><th>선정 사유</th>
  <th>배정 Profile</th><th>배정 사유</th>
</tr>
```

### 변경
`<th>배정 사유</th>` 뒤에 추가:
```html
<th>Memory refs</th>
```

---

## 작업 3 — loadFunnelData() JS에 메모리 카운트 로드 추가

`loadFunnelData()` 함수가 `backend/static/console.html` 내부에 존재한다.
이 함수 내부(또는 함수 끝)에 Context Preview API 호출 코드를 추가한다.

```javascript
// S3/S4/S5 메모리 카운트 로드
async function loadFunnelMemoryCounts() {
  const scopes = [
    { id: 'funnel-mem-s3', path: '/api/v1/pipeline/S3/context-preview' },
    { id: 'funnel-mem-s4', path: '/api/v1/pipeline/S4/context-preview' },
    { id: 'funnel-mem-s5', path: '/api/v1/pipeline/S5/context-preview' },
  ];
  for (const { id, path } of scopes) {
    try {
      const res = await fetch(path);
      if (res.ok) {
        const data = await res.json();
        const el = document.getElementById(id);
        if (el) el.textContent = data.payload?.count ?? 0;
      }
    } catch (_) {}
  }
}
```

`loadFunnelData()` 함수 안에서 `loadFunnelMemoryCounts()` 호출을 추가한다.

---

## 작업 4 — 후보 테이블 렌더링 JS에 memory_refs 컬럼 추가

`funnel-candidates-tbody`를 채우는 JS 코드를 찾아서
각 행의 마지막에 memory_refs 셀을 추가한다.

기존 행 렌더링 패턴이 어디에 있는지 grep으로 확인한 뒤 수정할 것.

추가 셀 예시:
```javascript
const memRefs = (item.memory_refs || []).join(', ') || '—';
// ... 기존 td들 뒤에 추가:
`<td style="font-size:0.8em;color:var(--accent)">${memRefs}</td>`
```

---

## 검증

```bash
grep -c "funnel-mem-s3\|funnel-mem-s4\|funnel-mem-s5" backend/static/console.html
# → 3 이상

grep -c "Memory refs\|loadFunnelMemoryCounts" backend/static/console.html
# → 2 이상
```

---

## 완료 체크리스트

- [x] 작업 1 — 메모리 카운트 카드 3개 추가
- [x] 작업 2 — 테이블 헤더 Memory refs 컬럼 추가
- [x] 작업 3 — loadFunnelMemoryCounts() 함수 추가 + 호출
- [x] 작업 4 — 후보 테이블 렌더링에 memory_refs 셀 추가
- [x] 검증 통과

결과는 `docs/agent-comm/OUTBOX_GEMINI_phase4a_ui.md`에 작성하라.
