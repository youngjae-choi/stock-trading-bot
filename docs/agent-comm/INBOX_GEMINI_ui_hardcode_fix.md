# INBOX_GEMINI_ui_hardcode_fix

## 역할
너는 Frontend Gemini다. 아래 작업을 수행하라.
완료 후 `docs/agent-comm/OUTBOX_GEMINI_ui_hardcode_fix.md`에 결과를 작성하라.

대상 파일: `backend/static/console.html` (단일 파일만 수정)

---

## 배경

`console.html`에 다음 3종류의 버그가 있다:

1. **잘못된 API 경로**: `/api/v1/settings/list` → 실제 존재하지 않는 경로 (404)
2. **잘못된 응답 필드**: `payload.settings` → 실제 API는 `payload.items`를 반환
3. **OPS_STEPS defaultTime 오류**: 실제 스케줄러 시간과 불일치
4. **저장 API 오류**: `/api/v1/settings/set` + `value_json` → 실제 API는 `/api/v1/settings` + `value`
5. **Funnel Progress 하드코딩**: Today Control과 Funnel Monitor의 숫자가 정적 HTML에 하드코딩

---

## 수정 1 — renderTodayFeed() 내 설정 API 경로 수정

**위치**: `renderTodayFeed()` 함수 내부 (라인 약 2809)

**현재 코드:**
```javascript
var settingsData = await fetchJson('/api/v1/settings/list').catch(() => null);
var settingsMap = {};
if (settingsData && settingsData.payload && settingsData.payload.settings) {
  settingsData.payload.settings.forEach(s => {
    try { settingsMap[s.key] = JSON.parse(s.value_json); } catch(e) { settingsMap[s.key] = s.value_json; }
  });
}
```

**수정 후:**
```javascript
var settingsData = await fetchJson('/api/v1/settings').catch(() => null);
var settingsMap = {};
if (settingsData && settingsData.payload && settingsData.payload.items) {
  settingsData.payload.items.forEach(s => {
    try { settingsMap[s.key] = JSON.parse(s.value_json); } catch(e) { settingsMap[s.key] = s.value_json; }
  });
}
```

변경 사항:
- `/api/v1/settings/list` → `/api/v1/settings`
- `payload.settings` → `payload.items`

---

## 수정 2 — OPS_STEPS defaultTime 수정

**위치**: `OPS_STEPS` 배열 정의부 (라인 약 2777)

**현재 코드:**
```javascript
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

**수정 후:**
```javascript
var OPS_STEPS = [
  { id: 's1', label: 'S1 KIS 토큰',     defaultTime: '07:45', settingKey: 's1' },
  { id: 's2', label: 'S2 시장톤',        defaultTime: '08:00', settingKey: 's2' },
  { id: 's3', label: 'S3 유니버스',      defaultTime: '08:15', settingKey: 's3' },
  { id: 's4', label: 'S4 스크리닝',      defaultTime: '08:30', settingKey: 's4' },
  { id: 's5', label: 'S5 Daily Plan',   defaultTime: '08:45', settingKey: 's5' },
  { id: 's6', label: 'S6 엔진',          defaultTime: '실시간', settingKey: null },
  { id: 's7', label: 'S7 주문',          defaultTime: '실시간', settingKey: null },
  { id: 's8', label: 'S8 포지션',        defaultTime: '실시간', settingKey: null },
  { id: 's9', label: 'S9 청산',          defaultTime: '15:20', settingKey: 's9' },
  { id: 's10', label: 'S10 요약',        defaultTime: '18:00', settingKey: 's10' },
  { id: 's11', label: 'S11 메모리',      defaultTime: '22:00', settingKey: 's11' },
];
```

변경 사항:
- s3: `09:05` → `08:15`
- s4: `09:20` → `08:30`
- s5: `09:35` → `08:45`
- s6: `09:45` + `settingKey: 's6'` → `실시간` + `settingKey: null` (Decision Engine은 스케줄 없음)

---

## 수정 3 — loadBuyConditions() 내 설정 API 경로 수정

**위치**: `loadBuyConditions()` 함수 내부 (라인 약 3779)

**현재 코드:**
```javascript
var [settingsData, screeningData] = await Promise.all([
  fetchJson('/api/v1/settings/list'),
  fetchJson('/api/v1/screening/today').catch(() => null)
]);

var settings = {};
(settingsData.payload?.settings || []).forEach(function(s) {
  try { settings[s.key] = JSON.parse(s.value_json); } catch(e) { settings[s.key] = s.value_json; }
});
```

**수정 후:**
```javascript
var [settingsData, screeningData] = await Promise.all([
  fetchJson('/api/v1/settings').catch(() => null),
  fetchJson('/api/v1/screening/today').catch(() => null)
]);

var settings = {};
(settingsData?.payload?.items || []).forEach(function(s) {
  try { settings[s.key] = JSON.parse(s.value_json); } catch(e) { settings[s.key] = s.value_json; }
});
```

변경 사항:
- `/api/v1/settings/list` → `/api/v1/settings`
- `.catch(() => null)` 추가 (오류 무시)
- `settingsData.payload?.settings` → `settingsData?.payload?.items`

---

## 수정 4 — saveGuardrail() 저장 API 경로 및 body 수정

**위치**: `saveGuardrail()` 함수 내부 (라인 약 3833)

**현재 코드:**
```javascript
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

**수정 후:**
```javascript
async function saveGuardrail(key, value) {
  try {
    await fetchJson('/api/v1/settings', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({key: key, value: parseFloat(value), value_type: 'number'})
    });
  } catch(e) {
    alert('저장 실패: ' + e.message);
  }
}
```

변경 사항:
- `/api/v1/settings/set` → `/api/v1/settings`
- `value_json: String(value)` → `value: parseFloat(value)`

---

## 수정 5 — Today Control Funnel Progress 동적 로드 추가

**위치**: Today Control 화면에서 funnel 진행상황을 표시하는 정적 HTML과
`renderFunnel()` 함수 호출부.

### 5-A: 정적 HTML 초기값 교체

**현재 코드** (라인 약 972):
```html
<div class="funnel" id="funnelProgress">
  <div class="funnel-step"><strong>2,500</strong><span>전체 종목</span></div>
  <div class="funnel-step"><strong>200</strong><span>Layer 1 Universe</span></div>
  <div class="funnel-step"><strong>15</strong><span>Layer 2 후보</span></div>
  <div class="funnel-step"><strong>4</strong><span>매수조건 대기</span></div>
  <div class="funnel-step"><strong>1</strong><span>보유중</span></div>
```

**수정 후:**
```html
<div class="funnel" id="funnelProgress">
  <div class="funnel-step"><strong id="fp-total">-</strong><span>전체 종목</span></div>
  <div class="funnel-step"><strong id="fp-layer1">-</strong><span>Layer 1 Universe</span></div>
  <div class="funnel-step"><strong id="fp-layer2">-</strong><span>Layer 2 후보</span></div>
  <div class="funnel-step"><strong id="fp-signals">-</strong><span>매수조건 대기</span></div>
  <div class="funnel-step"><strong id="fp-positions">-</strong><span>보유중</span></div>
```

### 5-B: renderFunnel() 함수 수정

`renderFunnel(funnel)` 함수를 찾아 아래로 교체한다.

**현재 코드** (라인 약 2954):
```javascript
function renderFunnel(funnel) {
  if (!funnelProgress || !funnel) {
    return;
  }
  funnelProgress.innerHTML = ''
    + '<div class="funnel-step"><strong>' + funnel.market_total + '</strong><span>전체 종목</span></div>'
    + '<div class="funnel-step"><strong>' + funnel.layer1 + '</strong><span>Layer 1 Universe</span></div>'
    + '<div class="funnel-step"><strong>' + funnel.layer2 + '</strong><span>Layer 2 후보</span></div>'
    + '<div class="funnel-step"><strong>' + funnel.entry_waiting + '</strong><span>매수조건 대기</span></div>'
    + '<div class="funnel-step"><strong>' + funnel.holding + '</strong><span>보유중</span></div>';
```

**수정 후:**
```javascript
function renderFunnel(funnel) {
  if (!funnelProgress || !funnel) {
    return;
  }
  // renderFunnel은 overview payload.funnel 포맷(market_total/layer1/layer2)을 지원
  // 새로운 /api/v1/funnel/summary 포맷도 지원 (total_universe/layer1_count/layer2_count)
  var total = funnel.total_universe || funnel.market_total || '-';
  var l1 = funnel.layer1_count || funnel.layer1 || '-';
  var l2 = funnel.layer2_count || funnel.layer2 || '-';
  var sig = funnel.signals_count != null ? funnel.signals_count : (funnel.entry_waiting || '-');
  var pos = funnel.positions_count != null ? funnel.positions_count : (funnel.holding || '-');

  var setEl = function(id, val) { var el = document.getElementById(id); if (el) el.textContent = val; };
  setEl('fp-total', typeof total === 'number' ? total.toLocaleString() : total);
  setEl('fp-layer1', typeof l1 === 'number' ? l1.toLocaleString() : l1);
  setEl('fp-layer2', typeof l2 === 'number' ? l2.toLocaleString() : l2);
  setEl('fp-signals', sig);
  setEl('fp-positions', pos);
}
```

### 5-C: renderTodayFeed() 내 funnel summary API 호출 추가

`renderTodayFeed()` 내에서 기존 status API 호출 목록(`statusResults`)에 funnel summary 추가:

**현재 코드** (statusResults 배열):
```javascript
var statusResults = await Promise.allSettled([
  fetchJson('/api/v1/scheduler/status'),
  fetchJson('/api/v1/market-tone/today'),
  fetchJson('/api/v1/universe-filter/today'),
  fetchJson('/api/v1/screening/today'),
  fetchJson('/api/v1/daily-plan/today'),
  fetchJson('/api/v1/decision/status'),
  fetchJson('/api/v1/orders/today'),
  fetchJson('/api/v1/orders/positions'),
]);
```

**수정 후:**
```javascript
var statusResults = await Promise.allSettled([
  fetchJson('/api/v1/scheduler/status'),
  fetchJson('/api/v1/market-tone/today'),
  fetchJson('/api/v1/universe-filter/today'),
  fetchJson('/api/v1/screening/today'),
  fetchJson('/api/v1/daily-plan/today'),
  fetchJson('/api/v1/decision/status'),
  fetchJson('/api/v1/orders/today'),
  fetchJson('/api/v1/orders/positions'),
  fetchJson('/api/v1/funnel/summary'),  // index 8
]);
```

그리고 statusResults 직후에 아래 코드를 추가 (funnel summary 렌더링):
```javascript
// Funnel summary 렌더링
if (statusResults[8].status === 'fulfilled' && statusResults[8].value.ok) {
  renderFunnel(statusResults[8].value.payload);
}
```

---

## 수정 6 — Funnel Monitor loadFunnelData() 개선

**위치**: `loadFunnelData()` 함수 내 overview 호출 부분 (라인 약 4565)

**현재 코드:**
```javascript
try {
  var overviewData = await fetchJson("/api/v1/bot/overview");
  var funnel = overviewData.payload && overviewData.payload.funnel;
  if (funnel) {
    var totalEl = document.getElementById("funnel-total");
    var l1El = document.getElementById("funnel-layer1");
    if (totalEl) totalEl.textContent = (funnel.market_total || "-").toLocaleString();
    if (l1El) l1El.textContent = (funnel.layer1 || "-").toLocaleString();
  }
} catch (e) { /* ignore overview fail */ }
```

**수정 후:**
```javascript
try {
  var funnelSummary = await fetchJson("/api/v1/funnel/summary");
  if (funnelSummary.ok && funnelSummary.payload) {
    var fp = funnelSummary.payload;
    var totalEl = document.getElementById("funnel-total");
    var l1El = document.getElementById("funnel-layer1");
    var l2El2 = document.getElementById("funnel-layer2");
    var candEl2 = document.getElementById("funnel-candidates");
    if (totalEl) totalEl.textContent = (fp.total_universe || 2500).toLocaleString();
    if (l1El) l1El.textContent = fp.layer1_count != null ? fp.layer1_count.toLocaleString() : "-";
    if (l2El2 && fp.layer2_count != null) l2El2.textContent = fp.layer2_count.toLocaleString();
    if (candEl2 && fp.signals_count != null) candEl2.textContent = fp.signals_count;
    // Risk Profile별 배정 수
    var pc = fp.profile_counts || {};
    var setPC = function(id, key) { var el = document.getElementById(id); if (el) el.textContent = pc[key] || 0; };
    setPC('fn-low-count', 'LOW_VOL');
    setPC('fn-mid-count', 'MID_VOL');
    setPC('fn-high-count', 'HIGH_VOL');
    setPC('fn-spike-count', 'THEME_SPIKE');
  }
} catch (e) { /* ignore funnel summary fail */ }
```

주의: 기존 screening/today 호출 및 daily-plan/today 호출 블록은 제거하지 말 것 (후보 목록 테이블에서 여전히 사용).

---

## 검증

수정 완료 후 Python HTMLParser로 syntax 확인:
```bash
python3 -c "
from html.parser import HTMLParser
class P(HTMLParser):
    pass
with open('backend/static/console.html', encoding='utf-8') as f:
    P().feed(f.read())
print('HTML parse OK')
"
```

수정된 항목 grep 확인:
```bash
echo "=== settings/list (0개여야 함) ==="
grep -c "settings/list" backend/static/console.html || echo "0"

echo "=== settings/set (0개여야 함) ==="
grep -c "settings/set" backend/static/console.html || echo "0"

echo "=== 올바른 API 경로 확인 ==="
grep -c "fetchJson('/api/v1/settings')" backend/static/console.html

echo "=== OPS_STEPS 시간 확인 ==="
grep "defaultTime.*08:15\|defaultTime.*08:30\|defaultTime.*08:45" backend/static/console.html

echo "=== funnel/summary 호출 확인 ==="
grep -c "funnel/summary" backend/static/console.html
```

---

## 완료 체크리스트

- [ ] renderTodayFeed(): `/api/v1/settings/list` → `/api/v1/settings`, `payload.settings` → `payload.items`
- [ ] OPS_STEPS s3/s4/s5 defaultTime 수정 (08:15/08:30/08:45), s6 → `실시간`
- [ ] loadBuyConditions(): `/api/v1/settings/list` → `/api/v1/settings`, `payload.settings` → `payload.items`
- [ ] saveGuardrail(): `/api/v1/settings/set` → `/api/v1/settings`, `value_json` → `value`
- [ ] funnelProgress HTML: 하드코딩 숫자 → id 부여 (`fp-total`, `fp-layer1` 등)
- [ ] renderFunnel(): 두 포맷(overview/funnel summary) 모두 처리
- [ ] renderTodayFeed(): `/api/v1/funnel/summary` 호출 추가 + renderFunnel() 호출
- [ ] loadFunnelData(): overview 대신 `/api/v1/funnel/summary` 사용
- [ ] HTML parse OK
- [ ] grep 검증 통과

결과는 `docs/agent-comm/OUTBOX_GEMINI_ui_hardcode_fix.md`에 작성하라.
