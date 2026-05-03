# INBOX_EXECUTOR_ui_refinement_fix — UI 수정 잔여 작업

## 대상 파일
`backend/static/console.html` 하나만 수정.

이전 Executor가 Task 1-C, 3, 4-A/B, 5를 미처리했다. 아래 항목만 처리한다.

---

## Task 1-C — 상단 2개 카드 완전 제거

`id="trades-executed-tbody"` 와 `id="trades-pending-tbody"` 가 포함된 카드 블록을 파일에서 찾아 완전히 제거한다.

이 두 tbody는 각각 "오늘 체결 내역" 카드와 "거래중 (미체결)" 카드에 속해 있다.
두 카드를 감싸는 flex 컨테이너 div까지 통째로 삭제한다.

완료 기준: 파일에 `trades-executed-tbody`, `trades-pending-tbody` 문자열이 없어야 한다.

---

## Task 3 — API Logs 당일 필터

`loadApiLogs` 함수를 찾아서 아래와 같이 교체한다:

```javascript
async function loadApiLogs() {
  var today = new Date();
  var dateStr = today.getFullYear() + '-'
    + String(today.getMonth()+1).padStart(2,'0') + '-'
    + String(today.getDate()).padStart(2,'0');
  var result = await fetchJson('/api/v1/bot/api-logs?date=' + dateStr);
  // 백엔드가 date 파라미터 미지원 시 클라이언트에서 필터
  if (result && result.payload && Array.isArray(result.payload)) {
    result.payload = result.payload.filter(function(e) {
      var ts = e.called_at || e.timestamp || '';
      return ts.startsWith(dateStr);
    });
  }
  renderApiLogs(result && result.payload);
}
```

완료 기준: 파일에 `dateStr` 문자열이 있어야 한다.

---

## Task 4-A — Notification 카드 완전 제거

`screen-settings` 내에서 아래 패턴의 카드를 찾아 제거:
- `card-title` 텍스트가 "Notification"인 카드
- 그 안에 `<h4>Telegram</h4>` 섹션과 `<h4>권한 정책</h4>` 섹션이 있다

카드 전체 (열리는 `<div class="card">` ~ 닫히는 `</div>` 까지) 삭제.

완료 기준: 파일에 `권한 정책` 문자열이 없어야 한다.

---

## Task 4-B — 리스크 & 청산 설정 카드 내용 교체

`screen-settings` 내에서 "리스크 & 청산 설정" 카드를 찾아 내용 전체를 아래로 교체:

```html
<div class="card">
  <div class="card-title">리스크 & 청산 설정 <span>system_settings</span></div>
  <p class="muted" style="margin-bottom:12px; font-size:12px;">이 설정값을 기준으로 RulePack의 위험 한도가 자동 적용됩니다.</p>

  <!-- 포트폴리오 위험 한도 -->
  <div style="font-size:11px; color:var(--muted); font-weight:600; margin-bottom:8px; letter-spacing:0.05em;">포트폴리오 위험 한도 (전체 계좌 기준)</div>
  <div class="form-grid" id="riskSettingsForm">
    <div class="field">
      <label>일일 손실 한도</label>
      <input id="risk-daily-loss" value="-2.0%" readonly>
      <small class="muted">당일 계좌 전체 손익이 이 이하로 떨어지면 신규 매수를 중단</small>
    </div>
    <div class="field">
      <label>주간 손실 한도</label>
      <input id="risk-weekly-loss" value="-5.0%" readonly>
    </div>
    <div class="field">
      <label>월간 손실 한도</label>
      <input id="risk-monthly-loss" value="-8.0%" readonly>
    </div>
    <div class="field">
      <label>최대 보유 종목</label>
      <input id="risk-max-positions" value="5" readonly>
    </div>
    <div class="field">
      <label>종목당 최대 비중</label>
      <input id="risk-position-size" value="10%" readonly>
    </div>
    <div class="field">
      <label>기본 운용 모드</label>
      <select id="risk-mode">
        <option>AUTO</option>
        <option>MONITOR</option>
        <option>HALT</option>
      </select>
    </div>
  </div>

  <hr style="border:none; border-top:1px solid var(--border,var(--line)); margin:16px 0;">

  <!-- 포지션별 청산 기준 -->
  <div style="font-size:11px; color:var(--muted); font-weight:600; margin-bottom:4px; letter-spacing:0.05em;">포지션별 청산 기준 (개별 종목 기준)</div>
  <p class="muted" style="font-size:11px; margin-bottom:10px;">포트폴리오 한도(위)와 별개로, 개별 종목 진입가 대비 손절/익절 기준을 설정합니다. 비워두면 RulePack 값을 사용합니다.</p>
  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>항목</th><th>현재값</th><th>새 값</th><th>저장</th><th>예시</th></tr>
      </thead>
      <tbody id="exitOverrideSettingsTableBody">
        <tr><td colspan="5" class="muted">설정을 불러오는 중입니다...</td></tr>
      </tbody>
    </table>
  </div>
</div>
```

완료 기준: 파일에 `포트폴리오 위험 한도`, `포지션별 청산 기준` 문자열이 있어야 한다.

---

## Task 5 — Data & API: Telegram 상태 카드 추가

`screen-data` 섹션 내 LLM Provider 상태 카드 바로 아래에 아래 HTML 블록을 삽입:

```html
<div class="section-gap"></div>
<div class="card">
  <div class="card-title">알림 연동 상태</div>
  <div class="natural-card" style="display:flex; gap:16px; align-items:center;">
    <div>
      <h4 style="margin:0 0 4px;">Telegram Bot</h4>
      <p style="margin:0;"><span class="status ok" id="telegram-status">확인중</span></p>
    </div>
    <div style="color:var(--muted); font-size:12px;" id="telegram-detail">
      RulePack 생성, 주문 발생, 차단, 긴급정지, 일일 리포트 발송
    </div>
  </div>
</div>
```

그리고 `loadDataHealth()` 함수 내부 끝 부분 또는 함수 안에 아래를 추가:

```javascript
var telegramEl = document.getElementById('telegram-status');
if (telegramEl) {
  telegramEl.textContent = '활성';
  telegramEl.className = 'status ok';
}
```

완료 기준: 파일에 `telegram-status` 문자열이 있어야 한다.

---

## 검증

작업 완료 후 반드시 아래 검증을 수행하고 결과를 OUTBOX에 기록:

```bash
python3 - <<'PY'
c = open('backend/static/console.html').read()
checks = [
  ('오늘 체결 내역 카드 제거', 'trades-executed-tbody' not in c),
  ('거래중 미체결 카드 제거', 'trades-pending-tbody' not in c),
  ('API Logs 당일 필터', 'dateStr' in c),
  ('Notification 카드 제거', '권한 정책' not in c),
  ('포트폴리오 위험 한도 라벨', '포트폴리오 위험 한도' in c),
  ('포지션별 청산 기준 라벨', '포지션별 청산 기준' in c),
  ('Telegram Data&API 이동', 'telegram-status' in c),
]
for name, check in checks:
  print(f'{"✅" if check else "❌"} {name}')
PY
```

그리고 JS 문법 검증:
```bash
node -e "const fs=require('fs'); const html=fs.readFileSync('backend/static/console.html','utf8'); const m=html.match(/<script>([\s\S]*)<\/script>/); new Function(m[1]); console.log('script syntax ok');"
```

## OUTBOX
`docs/agent-comm/OUTBOX_EXECUTOR_ui_refinement_fix.md`
