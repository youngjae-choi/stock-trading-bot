# INBOX_GEMINI_ui_overhaul_v2

## 역할
너는 Gemini (Frontend 전담)다.
`backend/static/console.html` 하나만 수정한다.
완료 후 `docs/agent-comm/OUTBOX_GEMINI_ui_overhaul_v2.md`에 결과를 작성하라.

---

## 작업 1 — F5 새로고침 시 현재 화면 유지

### 현재 문제
F5로 새로고침하면 항상 Today Control 화면으로 이동.

### 수정 방법
`showScreen(screenId)` 함수 내부에서 `sessionStorage.setItem('currentScreen', screenId)` 호출.
페이지 로드 시 `sessionStorage.getItem('currentScreen')`이 있으면 해당 화면으로 진입.

```js
// 페이지 로드 시 (DOMContentLoaded 또는 초기화 함수에서)
var savedScreen = sessionStorage.getItem('currentScreen');
if (savedScreen && document.getElementById('screen-' + savedScreen)) {
  showScreen(savedScreen);
} else {
  showScreen('main'); // 기본값
}

// showScreen() 함수 내 추가
sessionStorage.setItem('currentScreen', screenId);
```

---

## 작업 2 — 오늘 운영현황 가로 타임라인 + 동적 시간 + 자세히보기

### 현재 문제
- 운영현황이 세로 피드 형태 → 공간 낭비
- 단계 시간이 하드코딩
- "자세히보기" 없음

### 수정 방법

`#today-ops-feed` div를 가로 타임라인으로 교체.

#### 2a — API 호출로 동적 시간 로드
`GET /api/v1/settings/list` 응답에서 `schedule_s1_time`, `schedule_s2_time` 등 키를 읽어 각 단계 시간에 반영.
API 응답 구조:
```json
{"ok": true, "payload": {"settings": [{"key": "schedule_s1_time", "value_json": "\"07:45\""}]}}
```

#### 2b — 가로 타임라인 렌더링

`loadConsoleData()` 또는 별도 `loadOpsTimeline()` 함수에서 아래 단계를 순서대로 렌더링:

단계 목록 (하드코딩 기본값, settings로 덮어씀):
```js
var OPS_STEPS = [
  { id: 's1', label: 'S1 KIS 토큰',     defaultTime: '07:45', settingKey: 's1' },
  { id: 's2', label: 'S2 시장톤',        defaultTime: '08:00', settingKey: 's2' },
  { id: 's3', label: 'S3 유니버스',      defaultTime: '09:05', settingKey: 's3' },
  { id: 's4', label: 'S4 스크리닝',      defaultTime: '09:20', settingKey: 's4' },
  { id: 's5', label: 'S5 Daily Plan',   defaultTime: '09:35', settingKey: 's5' },
  { id: 's6', label: 'S6 엔진',          defaultTime: '09:45', settingKey: 's6' },
  { id: 's7', label: 'S7 주문',          defaultTime: '실시간', settingKey: null },
  { id: 's8', label: 'S8 포지션',        defaultTime: '실시간', settingKey: null },
  { id: 's9', label: 'S9 청산',          defaultTime: '15:20', settingKey: 's9' },
  { id: 's10', label: 'S10 요약',        defaultTime: '18:00', settingKey: 's10' },
  { id: 's11', label: 'S11 메모리',      defaultTime: '22:00', settingKey: 's11' },
];
```

타임라인 HTML 구조 (가로 스크롤 가능):
```html
<div style="display:flex; gap:8px; overflow-x:auto; padding-bottom:8px;">
  <!-- 각 단계 -->
  <div style="flex:0 0 90px; text-align:center;">
    <div style="font-size:10px; color:var(--muted); margin-bottom:4px;">07:45</div>
    <div style="padding:6px 4px; border-radius:6px; font-size:11px; font-weight:600;
                background: (완료=var(--green-subtle) / 대기=var(--panel-2) / 실행중=var(--blue-subtle))
                border: 1px solid (완료=var(--green) / 대기=var(--border) / 실행중=var(--blue))">
      S1<br>KIS 토큰
    </div>
    <div style="font-size:10px; margin-top:4px; color:var(--muted)">완료</div>
  </div>
  <!-- 구분선 -->
  <div style="flex:0 0 16px; display:flex; align-items:center; color:var(--muted);">→</div>
  ...
</div>
```

상태값은 각 단계의 오늘 결과 API로 판단:
- S1: `GET /api/v1/scheduler/status` → last_run 확인
- S2: `GET /api/v1/market-tone/today` → ok 여부
- S3: `GET /api/v1/universe-filter/today` → ok 여부
- S4: `GET /api/v1/screening/today` → ok 여부
- S5: `GET /api/v1/daily-plan/today` → ok 여부
- S6: `GET /api/v1/decision/status` → active 여부
- S7: `GET /api/v1/orders/today` → count > 0
- S8: `GET /api/v1/orders/positions` → count
- S9/S10/S11: 시간 기준으로 "대기" 표시

상태 3종: `completed`(완료/초록), `running`(실행중/파랑), `pending`(대기/회색)

#### 2c — 자세히보기 버튼
타임라인 아래에:
```html
<div style="text-align:right; margin-top:8px;">
  <button class="btn" style="font-size:11px;" onclick="showScreen('engine-test')">
    자세히보기 (KIS System Test) →
  </button>
</div>
```

---

## 작업 3 — KIS System Test 화면 개선

### 3a — 페이지 진입 시 오늘 실행 결과 자동 로드

`showScreen('engine-test')` 또는 화면 진입 시 `engineTestLoadTodayResults()` 함수 호출.

```js
async function engineTestLoadTodayResults() {
  // S1: 스케줄러 마지막 실행 확인 → et-badge-s1 업데이트
  // S2: GET /api/v1/market-tone/today → 결과 et-result-s2에 표시
  // S3: GET /api/v1/universe-filter/today
  // S4: GET /api/v1/screening/today
  // S5: GET /api/v1/daily-plan/today
  // S6: GET /api/v1/decision/status
  // S7: GET /api/v1/orders/today
  // S8: GET /api/v1/orders/positions
  // S10: GET /api/v1/trades/summary/today (있으면)
  
  // 각 단계별로:
  // 1. API 호출
  // 2. ok이고 데이터 있으면 → badge를 "완료"(초록)로 변경
  // 3. et-result-{id} pre에 JSON 결과 표시 (display:block)
  // 4. 에러/데이터없음 → badge "대기"(회색) 유지
}
```

배지 업데이트 헬퍼:
```js
function etSetBadge(stepId, status, text) {
  var badge = document.getElementById('et-badge-' + stepId);
  if (!badge) return;
  badge.textContent = text;
  badge.className = 'badge ' + (status === 'ok' ? 'ok' : status === 'running' ? 'running' : '');
}

function etSetResult(stepId, data) {
  var pre = document.getElementById('et-result-' + stepId);
  if (!pre) return;
  pre.textContent = JSON.stringify(data, null, 2);
  pre.style.display = 'block';
}
```

CSS 추가 (`:root` 및 `.badge` 관련):
```css
.badge.ok { background: var(--green-subtle, rgba(63,185,80,0.15)); color: var(--green, #3fb950); border: 1px solid var(--green, #3fb950); }
.badge.running { background: var(--blue-subtle, rgba(88,166,255,0.15)); color: var(--blue, #58a6ff); border: 1px solid; animation: pulse 1.5s infinite; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.5} }
```

### 3b — S5 카드 통일 (S1~S4 패턴으로)

현재 S5 카드에 버튼이 4개 (S5 생성, Risk Profile Pack, Daily Plan 검증, Rule Composition).
이를 S1~S4 패턴으로 변경:

**S5 카드 (Daily Plan 생성):**
```html
<div class="card" id="et-card-s5">
  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
    <div>
      <strong>S5 — Daily Trading Plan 생성</strong>
      <div style="font-size:12px; color:var(--muted); margin-top:2px;">
        09:35 KST · Scheduler → daily_trading_plans
      </div>
    </div>
    <span class="badge" id="et-badge-s5">대기</span>
  </div>
  <button class="btn" style="width:100%; margin-bottom:10px;" onclick="engineTestRun('s5')">▶ 실행</button>
  <pre class="et-result" id="et-result-s5" style="display:none;"></pre>
</div>
```

**S5-V 카드 (Daily Plan 검증):** 같은 패턴
```html
<div class="card" id="et-card-s5v">
  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
    <div>
      <strong>S5-V — Daily Plan Validation</strong>
      <div style="font-size:12px; color:var(--muted); margin-top:2px;">
        09:40 KST · Schema/Risk Guard 검증
      </div>
    </div>
    <span class="badge" id="et-badge-s5v">대기</span>
  </div>
  <button class="btn" style="width:100%; margin-bottom:10px;" onclick="engineTestRun('s5v')">▶ 실행</button>
  <pre class="et-result" id="et-result-s5v" style="display:none;"></pre>
</div>
```

**S11 카드도 같은 패턴으로 통일:**
```html
<div class="card" id="et-card-s11">
  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
    <div>
      <strong>S11 — Learning Memory Builder</strong>
      <div style="font-size:12px; color:var(--muted); margin-top:2px;">
        22:00 KST · Review & Audit → Learning Memory
      </div>
    </div>
    <span class="badge" id="et-badge-s11">대기</span>
  </div>
  <button class="btn" style="width:100%; margin-bottom:10px;" onclick="engineTestRun('s11')">▶ 실행</button>
  <pre class="et-result" id="et-result-s11" style="display:none;"></pre>
</div>
```

`engineTestRun()` 함수에서 's5', 's5v', 's11' 케이스 추가 (기존 패턴 참고).

---

## 작업 4 — Settings 화면에 "매수 조건 가드레일" 섹션 추가

Settings 화면(`screen-settings`)에 새 카드 섹션 추가.

```html
<div class="card" style="margin-top:16px;">
  <div class="card-title">매수 조건 가드레일 <span style="font-size:11px; color:var(--muted)">AI가 매일 설정 / 이 값이 절대 하한선/상한선</span></div>
  <table style="width:100%; border-collapse:collapse; font-size:13px;">
    <thead>
      <tr style="border-bottom:1px solid var(--border);">
        <th style="text-align:left; padding:6px 0;">항목</th>
        <th style="text-align:left; padding:6px 0;">현재 AI 설정</th>
        <th style="text-align:left; padding:6px 0;">가드레일 (수동)</th>
        <th style="text-align:left; padding:6px 0;">설명</th>
      </tr>
    </thead>
    <tbody id="buy-condition-tbody">
      <tr><td colspan="4" class="muted" style="text-align:center;">로딩중...</td></tr>
    </tbody>
  </table>
</div>
```

`loadSettings()` 또는 settings 화면 진입 시 `loadBuyConditions()` 호출:

```js
async function loadBuyConditions() {
  try {
    // 가드레일: engine.min_confidence_floor, engine.min_price_change_pct, engine.max_price_change_pct
    // 오늘 AI 설정: GET /api/v1/screening/today → entry_rules
    var [settingsData, screeningData] = await Promise.all([
      fetchJson('/api/v1/settings/list'),
      fetchJson('/api/v1/screening/today').catch(() => null)
    ]);
    
    var settings = {};
    (settingsData.payload?.settings || []).forEach(function(s) {
      try { settings[s.key] = JSON.parse(s.value_json); } catch(e) { settings[s.key] = s.value_json; }
    });
    
    var aiEntryRules = screeningData?.payload?.entry_rules || {};
    
    var rows = [
      {
        label: 'AI confidence 임계값',
        aiValue: aiEntryRules.min_ai_confidence ?? '-',
        guardKey: 'engine.min_confidence_floor',
        desc: 'AI가 설정한 오늘의 최소 신뢰도 / 가드레일은 절대 하한선'
      },
      {
        label: '최소 등락률 %',
        aiValue: aiEntryRules.min_price_change_pct ?? '-',
        guardKey: 'engine.min_price_change_pct',
        desc: '이 등락률 미만 종목은 매수 신호 발생 안 함'
      },
      {
        label: '최대 등락률 %',
        aiValue: aiEntryRules.max_price_change_pct ?? '-',
        guardKey: 'engine.max_price_change_pct',
        desc: '이 등락률 초과 종목은 과열로 판단해 제외'
      },
    ];
    
    var html = rows.map(function(row) {
      var guardVal = settings[row.guardKey] ?? '-';
      return '<tr style="border-bottom:1px solid var(--border);">'
        + '<td style="padding:8px 0;">' + escapeHtml(row.label) + '</td>'
        + '<td style="padding:8px 4px; font-weight:600; color:var(--blue);">' + row.aiValue + '</td>'
        + '<td style="padding:8px 4px;">'
        + '<input type="number" step="0.01" value="' + guardVal + '" '
        + 'onchange="saveGuardrail(\'' + row.guardKey + '\', this.value)" '
        + 'style="width:70px; padding:4px; border-radius:4px; background:var(--panel-2); color:var(--text); border:1px solid var(--border);">'
        + '</td>'
        + '<td style="padding:8px 4px; font-size:11px; color:var(--muted);">' + escapeHtml(row.desc) + '</td>'
        + '</tr>';
    }).join('');
    document.getElementById('buy-condition-tbody').innerHTML = html;
  } catch(e) {
    document.getElementById('buy-condition-tbody').innerHTML =
      '<tr><td colspan="4" class="muted">로드 실패: ' + escapeHtml(e.message) + '</td></tr>';
  }
}

async function saveGuardrail(key, value) {
  try {
    await fetchJson('/api/v1/settings/set', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({key: key, value_json: String(value), value_type: 'number'})
    });
  } catch(e) {
    alert('저장 실패: ' + e.message);
  }
}
```

---

## API 경로 참고

이미 존재하는 API:
- `GET /api/v1/market-tone/today`
- `GET /api/v1/universe-filter/today` (또는 `/run`)
- `GET /api/v1/screening/today`
- `GET /api/v1/daily-plan/today`
- `GET /api/v1/decision/status`
- `GET /api/v1/orders/today`
- `GET /api/v1/orders/positions`
- `GET /api/v1/settings/list`
- `POST /api/v1/settings/set`
- `GET /api/v1/scheduler/status`

---

## 검증

```bash
python3 -c "
from html.parser import HTMLParser
p = HTMLParser()
p.feed(open('backend/static/console.html').read())
print('HTML parse OK')
"

grep -c "sessionStorage\|currentScreen\|OPS_STEPS\|engineTestLoadTodayResults\|et-badge-s5v\|buy-condition-tbody\|saveGuardrail" backend/static/console.html
```

7개 항목 모두 1 이상이면 통과.

---

## 완료 체크리스트

- [ ] F5 새로고침 시 현재 화면 유지 (sessionStorage)
- [ ] 오늘운영현황 가로 타임라인 레이아웃
- [ ] 타임라인 단계 시간 settings API로 동적 표시
- [ ] 자세히보기 → engine-test 이동 버튼
- [ ] KIS System Test 진입 시 오늘 결과 자동 로드
- [ ] S5 카드 → S1~S4 패턴 통일 (버튼 1개)
- [ ] S5-V 카드 → 같은 패턴 통일
- [ ] S11 카드 → 같은 패턴 통일
- [ ] badge.ok / badge.running CSS 추가
- [ ] Settings에 매수 조건 가드레일 섹션
- [ ] HTML parse OK
- [ ] grep 검증 통과

결과는 `docs/agent-comm/OUTBOX_GEMINI_ui_overhaul_v2.md`에 작성하라.
