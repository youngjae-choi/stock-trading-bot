# INBOX: Settings 화면 항목별 최종 업데이트 시각 표시

**날짜:** 2026-05-22  
**우선순위:** MEDIUM  
**대상:** Gemini (Frontend)

---

## 요구사항
Settings 화면의 각 설정 항목 옆에 "언제, 누가 바꿨는지"를 표시한다.

`/api/v1/settings` API 응답은 이미 각 item에 `updated_at`과 `updated_by` 필드를 포함하고 있다.
예시:
```json
{
  "key": "engine.min_confidence_floor",
  "value": 0.65,
  "value_type": "number",
  "description": "...",
  "updated_at": "2026-05-22T10:35:00+09:00",
  "updated_by": "telegram_approval"
}
```

현재 `loadSettingsMap()` (`backend/static/js/screens/console-diagnostics.js` line 1~11)은 `key → value`만 매핑한다.

---

## 수정 파일: `backend/static/js/screens/console-diagnostics.js`

### loadSettingsMap 확장

기존 `loadSettingsMap()` 아래에 `loadSettingsMapFull()` 함수 추가:
```javascript
async function loadSettingsMapFull() {
  try {
    var res = await fetchJson("/api/v1/settings");
    var settingsItems = res.payload.items || [];
    var map = {};
    settingsItems.forEach(function(s) {
      map[s.key] = {
        value: s.value,
        updated_at: s.updated_at || null,
        updated_by: s.updated_by || null,
      };
    });
    return map;
  } catch (e) {
    return {};
  }
}
```

### 업데이트 시각 포맷 헬퍼 함수 추가

```javascript
function _fmtSettingTs(isoStr, updatedBy) {
  if (!isoStr) return '';
  try {
    var d = new Date(isoStr);
    var dt = d.toLocaleString('ko-KR', {
      timeZone: 'Asia/Seoul',
      month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hour12: false
    }).replace(/\. /g, '-').replace('. ', ' ');
    var by = updatedBy ? (' · ' + escapeHtml(updatedBy)) : '';
    return '<span class="muted" style="font-size:10px;">' + dt + by + '</span>';
  } catch(e) { return ''; }
}
```

---

## 수정 파일: `backend/static/js/screens/console-settings.js`

### 1. loadRiskSettings 수정

`loadSettingsMap()` → `loadSettingsMapFull()` 로 교체.
각 `<input>` 또는 `<select>` 뒤에 `_fmtSettingTs(fullMap[key].updated_at, fullMap[key].updated_by)` 출력.

예시 (risk.daily_loss_limit_percent):
```javascript
var settingsFull = await loadSettingsMapFull();
var dailyLoss = document.getElementById("risk-daily-loss");
if (dailyLoss) {
  dailyLoss.value = (settingsFull["risk.daily_loss_limit_percent"]?.value) ?? "-2.0";
  var tsEl = document.getElementById("ts-risk-daily-loss");
  if (tsEl) tsEl.innerHTML = _fmtSettingTs(
    settingsFull["risk.daily_loss_limit_percent"]?.updated_at,
    settingsFull["risk.daily_loss_limit_percent"]?.updated_by
  );
}
```

그러려면 HTML도 각 input 옆에 `<span id="ts-risk-XXX"></span>` 추가해야 하므로,
대신 **JS에서 동적으로** 타임스탬프 span을 input 옆에 삽입하는 방식으로 처리:

```javascript
// 각 input 아래에 타임스탬프 span 동적 삽입 유틸
function _insertSettingTs(inputId, settingKey, fullMap) {
  var el = document.getElementById(inputId);
  if (!el) return;
  var existing = document.getElementById('ts-' + inputId);
  if (existing) existing.remove();
  var item = fullMap[settingKey];
  if (!item || !item.updated_at) return;
  var span = document.createElement('span');
  span.id = 'ts-' + inputId;
  span.style.cssText = 'display:block; font-size:10px; color:var(--muted); margin-top:2px;';
  span.innerHTML = _fmtSettingTs(item.updated_at, item.updated_by);
  el.parentNode.insertBefore(span, el.nextSibling);
}
```

`loadRiskSettings()` 마지막에 아래 추가:
```javascript
var fm = await loadSettingsMapFull();
_insertSettingTs('risk-daily-loss', 'risk.daily_loss_limit_percent', fm);
_insertSettingTs('risk-max-positions', 'risk.max_positions', fm);
_insertSettingTs('risk-position-size', 'risk.max_position_rate_per_stock', fm);
_insertSettingTs('risk-mode', 'engine.mode', fm);
_insertSettingTs('setting-cutoff-time', 'risk.new_entry_cutoff_time', fm);
_insertSettingTs('setting-force-exit-time', 'risk.force_exit_time', fm);
```

### 2. loadSchedulerSettings 수정

테이블 행 렌더링 시 현재:
```javascript
return ''
  + '<tr>'
  + '  <td>' + k.label + '</td>'
  + '  <td class="muted">' + escapeHtml(k.description || k.key) + '</td>'
  + '  <td>' + escapeHtml(current) + '</td>'
  + ...
```

`/api/v1/settings` 전체 응답에서 `updated_at`/`updated_by`도 가져와 테이블 행에 추가:

```javascript
var res = await fetchJson("/api/v1/settings");
var settings = res.payload.items || [];
var settingsMap = {};
var settingsMetaMap = {};
settings.forEach(function(s) {
  settingsMap[s.key] = s.value;
  settingsMetaMap[s.key] = { updated_at: s.updated_at, updated_by: s.updated_by };
});
```

행 생성 시 현재 열 뒤에 `updated_at` 열 추가:
```javascript
var meta = settingsMetaMap[k.key] || {};
var tsHtml = _fmtSettingTs(meta.updated_at, meta.updated_by) || '<span class="muted">-</span>';
return ''
  + '<tr>'
  + '  <td>' + k.label + '</td>'
  + '  <td class="muted">' + escapeHtml(k.description || k.key) + '</td>'
  + '  <td>' + escapeHtml(current) + '</td>'
  + '  <td>' + tsHtml + '</td>'   // ← 추가된 열
  + '  <td>' + inputHtml + '</td>'
  + '  <td>' + buttonHtml + '</td>'
  + '</tr>';
```

### 3. loadExitOverrideSettings 수정

동일하게 `settingsMetaMap` 추가 후 행에 타임스탬프 열 추가.
(각 `<tr>` 마지막에 `<td>' + tsHtml + '</td>` 추가)

### 4. loadBuyConditions 수정

`settings[s.key] = s.value` → `settingsMeta[s.key] = { value: s.value, updated_at: s.updated_at, updated_by: s.updated_by }`  
행 생성 시 guardVal 아래에 타임스탬프 표시:

```javascript
var guardMeta = settingsMeta[row.guardKey] || {};
var tsHtml = _fmtSettingTs(guardMeta.updated_at, guardMeta.updated_by);
// input 아래 작은 텍스트로 출력
'<td style="padding:8px 4px;">'
  + '<input type="number" ...>'
  + (tsHtml ? '<div style="font-size:10px;margin-top:2px;">' + tsHtml + '</div>' : '')
  + '</td>'
```

---

## 완료 기준

1. Settings 화면 → 위험 관리 섹션: 각 input 아래 "MM-DD HH:MM · updated_by" 텍스트 표시
2. Settings 화면 → 스케줄러 섹션: 테이블에 "최종 수정" 열 추가
3. Settings 화면 → 청산 규칙 섹션: 동일
4. Settings 화면 → 매수 조건 섹션: guardrail input 아래 타임스탬프 표시
5. `updated_at`이 없는 설정은 해당 위치에 아무것도 표시하지 않는다 (에러 없이 조용히 처리)
6. 서버 재시작 없이 브라우저 새로고침으로 확인 가능

결과를 `docs/agent-comm/OUTBOX_GEMINI_20260522_settings_updated_at.md`에 기록하라.
