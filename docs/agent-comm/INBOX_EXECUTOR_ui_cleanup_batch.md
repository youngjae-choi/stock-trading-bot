# INBOX_EXECUTOR_ui_cleanup_batch

## 작업 목적

`backend/static/console.html` 에서 **"RulePack 생성"** 구시대 문구를 모두 제거하고 **Daily Trading Plan 자동 생성** 중심으로 문구/버튼/상태값을 정리한다.

백엔드는 이미 Daily Plan 구조로 구현 완료 상태이므로 **HTML/JS만 수정**한다.

---

## 변경 1 — 문구 교체 (단순 텍스트)

아래 텍스트를 정확히 찾아 교체한다:

| grep 키워드 | 기존 문구 | 변경 문구 |
|---|---|---|
| `brand-sub` div | `AI RulePack 기반 자동매매 운영 관제` | `AI 기반 단타 자동매매 운영 관제` |
| `modeDetail` div 초기값 | `RulePack 적용 완료` | `Daily Plan 활성` |
| `modeDetail.textContent` JS 할당 | `"RulePack 적용 완료"` | `"Daily Plan 활성"` |
| scheduleItems 배열 | `{ time: "08:45", name: "RulePack 생성" }` | `{ time: "08:45", name: "S5 Daily Plan 자동 생성" }` |
| kisTokenDetail 초기값 | `RulePack 적용 상태` | `Auto Engine 상태` |
| Data&API RulePack h4 태그 | `<h4>RulePack</h4>` (id=rulepackStatus 위) | `<h4>Rule Composition</h4>` |
| rulepackDetail 초기값 | `오늘 활성 RulePack` | `오늘 활성 Rule Composition` |
| Settings 스케줄러 label | `"S5 RulePack"` | `"S5 Daily Plan"` |
| Review&Audit page-desc | `좋은 전략, 나쁜 전략, 좋은 타이밍을 구조화해서 다음 RulePack에 반영합니다.` | `당일 매매 결과와 미진입 사유를 구조화하여 Learning Memory로 저장하고, 다음 거래일 S3~S5와 Daily Trading Plan 생성에 반영합니다.` |
| review-latest-rulepack 위 h4 | `<h4>RulePack</h4>` (review 화면) | `<h4>Daily Plan</h4>` |
| S5 테스트 카드 설명 div | `08:45 KST · LLM → daily_trading_plan (종목별 Profile 배정)` | `08:45 KST · Scheduler → daily_trading_plans (generated → validated → active 자동 파이프라인)` |
| Settings 포지션별 청산 안내 | `비워두면 RulePack 값을 사용합니다.` | `비워두면 Risk Profile 값을 사용합니다.` |
| Settings 리스크 안내 | `RulePack의 위험 한도가 자동 적용됩니다.` | `Risk Profile Pack의 위험 한도가 자동 적용됩니다.` |

---

## 변경 2 — Daily Plan & RulePack 화면 버튼 교체

현재 (line ~1111):
```html
<div style="display:flex; gap:8px;">
  <button class="btn" onclick="generateDailyPlan()">Daily Plan 생성</button>
  <button class="btn" onclick="loadDailyPlanScreen()">새로고침</button>
</div>
```

변경 후:
```html
<div style="display:flex; gap:8px; align-items:center;">
  <button class="btn" onclick="loadDailyPlanScreen()">새로고침</button>
  <button class="btn" onclick="showDpContext()">Context 보기</button>
  <div style="position:relative; display:inline-block;">
    <button class="btn" onclick="toggleDpAdvanced(this)">고급 작업 ▾</button>
    <div id="dp-advanced-menu" style="display:none; position:absolute; right:0; top:100%; background:var(--bg2); border:1px solid var(--border); border-radius:6px; min-width:180px; z-index:100; padding:4px 0;">
      <button style="width:100%; text-align:left; padding:8px 12px; background:none; border:none; color:var(--fg); font-size:12px; cursor:pointer;" onclick="runDailyPlanDryRun()">Daily Plan Dry Run</button>
      <button style="width:100%; text-align:left; padding:8px 12px; background:none; border:none; color:var(--fg); font-size:12px; cursor:pointer;" onclick="manualRerunS5()">S5 수동 재실행</button>
      <button style="width:100%; text-align:left; padding:8px 12px; background:none; border:none; color:var(--fg); font-size:12px; cursor:pointer;" onclick="revalidateDailyPlan()">Daily Plan 재검증</button>
      <hr style="margin:4px 0; border-color:var(--border);">
      <button style="width:100%; text-align:left; padding:8px 12px; background:none; border:none; color:#f85149; font-size:12px; cursor:pointer;" onclick="deactivateDailyPlan()">Daily Plan 비활성화</button>
      <button style="width:100%; text-align:left; padding:8px 12px; background:none; border:none; color:#f85149; font-size:12px; cursor:pointer;" onclick="rollbackDailyPlan()">이전 Plan으로 롤백</button>
    </div>
  </div>
</div>
```

JS에 아래 함수를 추가한다 (기존 `generateDailyPlan()` 함수 근처에 추가):
```javascript
function toggleDpAdvanced(btn) {
  var menu = document.getElementById('dp-advanced-menu');
  if (!menu) return;
  menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
}
document.addEventListener('click', function(e) {
  var menu = document.getElementById('dp-advanced-menu');
  if (menu && !e.target.closest('[onclick^="toggleDpAdvanced"]') && !e.target.closest('#dp-advanced-menu')) {
    menu.style.display = 'none';
  }
});
function showDpContext() { alert('Context 보기 기능은 Phase 2에서 구현됩니다.'); }
function runDailyPlanDryRun() { alert('Dry Run 기능은 Phase 2에서 구현됩니다.'); }
function manualRerunS5() { alert('S5 수동 재실행 기능은 Phase 2에서 구현됩니다.'); }
function revalidateDailyPlan() { alert('Daily Plan 재검증 기능은 Phase 2에서 구현됩니다.'); }
function deactivateDailyPlan() { alert('Daily Plan 비활성화 기능은 Phase 2에서 구현됩니다.'); }
function rollbackDailyPlan() { alert('이전 Plan으로 롤백 기능은 Phase 2에서 구현됩니다.'); }
```

---

## 변경 3 — Daily Plan 상태 색상 뱃지

`loadDailyPlanScreen()` 함수 안에서 `payload.status`를 읽어 상태 뱃지를 표시한다.

`dp-plan-status` div에 현재는 텍스트만 표시하는데, 아래처럼 span 뱃지로 변경:

```javascript
var statusColors = { active:'ok', validated:'info', generated:'info', validation_failed:'err', inactive:'warn', expired:'warn', superseded:'warn', rollbacked:'warn', dry_run:'info', draft:'warn', none:'warn' };
var statusLabel = { active:'active', validated:'validated', generated:'generated', validation_failed:'검증실패', inactive:'inactive', expired:'만료', superseded:'superseded', rollbacked:'롤백됨', dry_run:'dry_run', draft:'draft', none:'없음' };
var st = (payload && payload.status) ? payload.status : 'none';
var planStatusEl = document.getElementById('dp-plan-status');
if (planStatusEl) planStatusEl.innerHTML = 'Plan 상태: <span class="status ' + (statusColors[st]||'warn') + '">' + (statusLabel[st]||st) + '</span>';
```

또한 `dp-created-at` div에 생성자/방식을 표시:
```javascript
var createdBy = (payload && payload.created_by) ? payload.created_by : 'scheduler';
var creationMode = (payload && payload.creation_mode) ? payload.creation_mode : 'auto';
var createdAtEl = document.getElementById('dp-created-at');
if (createdAtEl) createdAtEl.textContent = '생성: ' + creationMode + ' · ' + createdBy;
```

---

## 변경 4 — KIS System Test S5-V 카드 추가

S5 카드 다음에 S5-V 카드를 삽입한다. S5 카드의 닫는 `</div>` 바로 다음에:

```html
<!-- S5-V -->
<div class="card" style="margin-bottom:12px;">
  <div style="display:flex; align-items:center; gap:8px; margin-bottom:8px;">
    <span class="status info">S5-V</span>
    <div>
      <strong>S5-V — Daily Plan Validation</strong>
      <div style="font-size:12px; color:var(--muted); margin-top:2px;">08:50 KST · Schema/Risk Guard/Daily Override 검증 → validated 또는 validation_failed</div>
    </div>
  </div>
  <button class="btn" style="width:100%; margin-bottom:10px;" onclick="testDailyPlanValidate()">Daily Plan 검증 실행</button>
  <pre id="s5v-test-result" style="font-size:11px; max-height:150px; overflow:auto; display:none;"></pre>
</div>
```

S5 테스트 버튼 문구도 변경:
- 기존: `Daily Plan 생성 실행`
- 변경: `S5 Daily Plan 생성 테스트`

---

## 변경 5 — Settings 스케줄러 항목 확장

`schedulerKeys` 배열에서:
```javascript
{ key: "schedule_s5_time", label: "S5 RulePack", default: "08:45" },
```
를 아래로 교체:
```javascript
{ key: "schedule_s5_time",  label: "S5 Daily Plan 자동 생성", default: "08:45" },
{ key: "schedule_s5v_time", label: "S5-V Daily Plan 자동 검증", default: "08:50" },
{ key: "schedule_s5a_time", label: "S5-A Daily Plan 활성화 확인", default: "08:55" },
{ key: "schedule_s10_time", label: "S10 Review & Audit", default: "16:00" },
{ key: "schedule_s11_time", label: "S11 Learning Memory Builder", default: "16:30" },
```

기존 `schedule_close_time`, `schedule_backup_time`, `schedule_usmarket_time`은 유지.

---

## 변경 6 — S5 API endpoint 수정

JS에서:
```javascript
s5: "/api/v1/rulepack-gen/run",
```
를:
```javascript
s5: "/api/v1/daily-plan/generate",
```
로 변경.

---

## 변경 7 — bootstrap에서 /api/v1/bot/rulepack/today 호출 제거

line ~2825 부근에:
```javascript
fetchJson("/api/v1/bot/rulepack/today"),
```
가 있고, 이 결과를 `rulepackResult`로 받아 `renderRulepack()`을 호출하는 블록이 있다.

이 fetchJson 호출과 결과 처리 블록(rulepackResult 관련)을 제거한다.
`renderRulepack()` 함수 자체는 남겨둔다 (다른 곳에서 참조될 수 있음).

제거 전 `rulepackBadge`, `rulepackSummary`, `rulepackChanges`, `rulepackJson` 요소가 화면 HTML에 실제 존재하는지 확인 후:
- 존재하면 이 요소들과 `renderRulepack()` 함수도 함께 제거 (더 이상 사용 안 함)
- 존재하지 않으면 bootstrap 호출 블록만 제거

---

## 검증 기준

1. `grep -n "RulePack 생성\|rulepack-gen" backend/static/console.html` → 0건
2. `grep -n "schedule_s5_time" backend/static/console.html` → `"S5 Daily Plan 자동 생성"` 포함 확인
3. JS 문법 오류 없어야 함: `node -e "var s=''; require('fs').createReadStream('backend/static/console.html').on('data',c=>s+=c).on('end',()=>{ var m=s.match(/<script[\s\S]*?<\/script>/g)||[]; m.forEach(b=>{ try{new Function(b.replace(/<\/?script[^>]*>/g,''))}catch(e){console.error(e.message)} }); console.log('done');})"` (에러 없으면 OK)

---

## 완료 후

`docs/agent-comm/OUTBOX_EXECUTOR_ui_cleanup_batch.md` 에 결과 작성.

형식:
```
# OUTBOX_EXECUTOR_ui_cleanup_batch
## 결과 요약
## 완료 체크리스트
- [x] 변경 1 — 문구 교체
- [x] 변경 2 — 버튼 교체
- [x] 변경 3 — Daily Plan 상태 뱃지
- [x] 변경 4 — KIS Test S5-V 카드
- [x] 변경 5 — Settings 스케줄러 확장
- [x] 변경 6 — S5 API endpoint
- [x] 변경 7 — bootstrap 호출 정리
## 특이사항
```
