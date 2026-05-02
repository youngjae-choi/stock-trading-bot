# INBOX_GEMINI_engine_test_frontend — KIS System Test 화면 구현

## 작업 목표
`backend/static/console.html` 에 **KIS System Test** 메뉴와 화면을 추가한다.
S1~S5 각 단계를 버튼 하나로 수동 실행하고, 결과와 서버 로그를 화면에 출력한다.

---

## 추가할 메뉴 항목

### 사이드바 nav (line 899 `settings` 버튼 바로 위에 삽입)
```html
<button data-screen="engine-test">KIS System Test <small>test</small></button>
```

### 모바일 select (line 869 `settings` option 바로 위)
```html
<option value="engine-test">KIS System Test</option>
```

---

## 추가할 화면 섹션

`id="screen-settings"` 섹션 바로 앞에 새 섹션 삽입:

```html
<section class="screen" id="screen-engine-test">
  <div class="page-head">
    <div>
      <h1 class="page-title">KIS System Test</h1>
      <p class="page-sub">S1~S5 각 단계를 수동으로 실행하고 결과를 확인합니다. 실제 KIS API와 DB에 반영됩니다.</p>
    </div>
    <div class="page-actions">
      <button class="btn" onclick="engineTestClearAll()">전체 결과 지우기</button>
      <button class="btn" onclick="engineTestLoadLogs('')">전체 로그 보기</button>
    </div>
  </div>

  <!-- 단계별 카드 그리드 -->
  <div style="display:grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap:16px; margin-bottom:24px;">

    <!-- S1 -->
    <div class="card" id="et-card-s1">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
        <div>
          <strong>S1 — KIS 토큰 갱신</strong>
          <div style="font-size:12px; color:var(--muted); margin-top:2px;">07:45 KST · token-refresh</div>
        </div>
        <span class="badge" id="et-badge-s1">대기</span>
      </div>
      <button class="btn" style="width:100%; margin-bottom:10px;" onclick="engineTestRun('s1')">▶ 실행</button>
      <pre class="et-result" id="et-result-s1" style="display:none;"></pre>
    </div>

    <!-- S2 -->
    <div class="card" id="et-card-s2">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
        <div>
          <strong>S2 — 시장 톤 분석</strong>
          <div style="font-size:12px; color:var(--muted); margin-top:2px;">08:00 KST · LLM → market_tone_results</div>
        </div>
        <span class="badge" id="et-badge-s2">대기</span>
      </div>
      <button class="btn" style="width:100%; margin-bottom:10px;" onclick="engineTestRun('s2')">▶ 실행</button>
      <pre class="et-result" id="et-result-s2" style="display:none;"></pre>
    </div>

    <!-- S3 -->
    <div class="card" id="et-card-s3">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
        <div>
          <strong>S3 — 유니버스 필터</strong>
          <div style="font-size:12px; color:var(--muted); margin-top:2px;">08:15 KST · KIS → universe_filter_results</div>
        </div>
        <span class="badge" id="et-badge-s3">대기</span>
      </div>
      <button class="btn" style="width:100%; margin-bottom:10px;" onclick="engineTestRun('s3')">▶ 실행</button>
      <pre class="et-result" id="et-result-s3" style="display:none;"></pre>
    </div>

    <!-- S4 -->
    <div class="card" id="et-card-s4">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
        <div>
          <strong>S4 — 하이브리드 스크리닝</strong>
          <div style="font-size:12px; color:var(--muted); margin-top:2px;">08:30 KST · LLM 정성 평가 → hybrid_screening_results</div>
        </div>
        <span class="badge" id="et-badge-s4">대기</span>
      </div>
      <button class="btn" style="width:100%; margin-bottom:10px;" onclick="engineTestRun('s4')">▶ 실행</button>
      <pre class="et-result" id="et-result-s4" style="display:none;"></pre>
    </div>

    <!-- S5 -->
    <div class="card" id="et-card-s5">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
        <div>
          <strong>S5 — RulePack 자동 생성</strong>
          <div style="font-size:12px; color:var(--muted); margin-top:2px;">08:45 KST · LLM → rulepacks (자동 활성화)</div>
        </div>
        <span class="badge" id="et-badge-s5">대기</span>
      </div>
      <button class="btn" style="width:100%; margin-bottom:10px;" onclick="engineTestRun('s5')">▶ 실행</button>
      <pre class="et-result" id="et-result-s5" style="display:none;"></pre>
    </div>

  </div>

  <!-- 서버 로그 패널 -->
  <div class="card">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
      <strong>서버 로그</strong>
      <div style="display:flex; gap:8px; align-items:center;">
        <input type="text" id="etLogFilter" placeholder="필터 키워드 (예: UniverseFilter)" 
               style="padding:4px 8px; border-radius:4px; border:1px solid var(--border); background:var(--input-bg); color:var(--text); font-size:12px; width:220px;">
        <button class="btn" onclick="engineTestLoadLogs(document.getElementById('etLogFilter').value)">불러오기</button>
        <button class="btn" onclick="engineTestClearLog()">지우기</button>
      </div>
    </div>
    <pre id="et-server-log" style="font-size:11px; max-height:400px; overflow-y:auto; white-space:pre-wrap; word-break:break-all; background:var(--code-bg, #111); padding:12px; border-radius:4px; color:var(--code-text, #ccc);">로그를 불러오려면 위 [불러오기] 버튼을 클릭하세요.</pre>
  </div>

</section>
```

---

## 추가할 CSS (기존 `<style>` 블록 끝에 추가)

```css
/* Engine Test */
.et-result {
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-all;
  background: var(--code-bg, #111);
  color: var(--code-text, #ccc);
  padding: 10px;
  border-radius: 4px;
  max-height: 220px;
  overflow-y: auto;
  margin: 0;
}
#et-server-log {
  font-family: monospace;
}
```

---

## 추가할 JavaScript (기존 `<script>` 블록 끝에 추가)

```javascript
// ─── Engine Test ───────────────────────────────────────
var ET_STEPS = {
  s1: { url: '/api/v1/engine/token-refresh',   method: 'POST', logKw: '토큰' },
  s2: { url: '/api/v1/market-tone/analyze',    method: 'POST', logKw: 'MarketTone' },
  s3: { url: '/api/v1/universe-filter/run',    method: 'POST', logKw: 'UniverseFilter' },
  s4: { url: '/api/v1/screening/run',          method: 'POST', logKw: 'HybridScreening' },
  s5: { url: '/api/v1/rulepack-gen/run',       method: 'POST', logKw: 'RulePackGen' },
};

function etSetBadge(step, text, color) {
  var b = document.getElementById('et-badge-' + step);
  if (!b) return;
  b.textContent = text;
  b.style.background = color === 'ok' ? 'var(--green, #22c55e)' :
                       color === 'err' ? 'var(--red, #ef4444)' :
                       color === 'run' ? 'var(--blue, #3b82f6)' : 'var(--muted-bg, #444)';
  b.style.color = '#fff';
  b.style.padding = '2px 8px';
  b.style.borderRadius = '4px';
  b.style.fontSize = '11px';
}

function etShowResult(step, text) {
  var el = document.getElementById('et-result-' + step);
  if (!el) return;
  el.textContent = text;
  el.style.display = 'block';
}

async function engineTestRun(step) {
  var cfg = ET_STEPS[step];
  if (!cfg) return;
  etSetBadge(step, '실행 중…', 'run');
  etShowResult(step, '요청 중...');

  try {
    var resp = await fetch(cfg.url, {
      method: cfg.method,
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
    });
    var data = await resp.json();
    var pretty = JSON.stringify(data, null, 2);
    etShowResult(step, pretty);
    if (data.ok) {
      etSetBadge(step, '성공', 'ok');
    } else {
      etSetBadge(step, '실패', 'err');
    }
    // 자동으로 해당 단계 로그 갱신
    engineTestLoadLogs(cfg.logKw);
  } catch (e) {
    etShowResult(step, '네트워크 오류: ' + e.message);
    etSetBadge(step, '오류', 'err');
  }
}

async function engineTestLoadLogs(filterKw) {
  var logEl = document.getElementById('et-server-log');
  if (!logEl) return;
  logEl.textContent = '로그 불러오는 중...';
  try {
    var qs = '?lines=100' + (filterKw ? '&filter=' + encodeURIComponent(filterKw) : '');
    var resp = await fetch('/api/v1/engine/logs' + qs, { credentials: 'include' });
    var data = await resp.json();
    if (data.ok && data.payload && data.payload.lines) {
      var lines = data.payload.lines;
      logEl.textContent = lines.length > 0 ? lines.join('\n') : '(해당 조건의 로그 없음)';
      // 자동 스크롤 하단
      logEl.scrollTop = logEl.scrollHeight;
    } else {
      logEl.textContent = '로그 조회 실패: ' + JSON.stringify(data);
    }
  } catch (e) {
    logEl.textContent = '네트워크 오류: ' + e.message;
  }
}

function engineTestClearLog() {
  var el = document.getElementById('et-server-log');
  if (el) el.textContent = '(지워졌습니다. 불러오기 버튼으로 다시 조회하세요.)';
}

function engineTestClearAll() {
  ['s1','s2','s3','s4','s5'].forEach(function(step) {
    etSetBadge(step, '대기', 'none');
    var el = document.getElementById('et-result-' + step);
    if (el) { el.textContent = ''; el.style.display = 'none'; }
  });
  engineTestClearLog();
}
// ───────────────────────────────────────────────────────
```

---

## 수정 요령 (삽입 위치 정확히 찾는 방법)

### 사이드바 버튼 삽입
`<button data-screen="settings">Settings <small>admin</small></button>` 바로 앞에 engine-test 버튼 삽입.

### 모바일 option 삽입
`<option value="settings">Settings</option>` 바로 앞에 engine-test option 삽입.

### 화면 섹션 삽입
`<section class="screen" id="screen-settings">` 바로 앞에 engine-test 섹션 전체 삽입.

### CSS 삽입
기존 `</style>` 바로 앞에 CSS 추가.

### JS 삽입
기존 `</script>` 바로 앞에 JS 추가.

---

## 완료 기준

1. `backend/static/console.html` 수정 완료
2. HTML 유효성: `python3 -c "from html.parser import HTMLParser; p=HTMLParser(); p.feed(open('backend/static/console.html').read()); print('HTML OK')"` 통과
3. OUTBOX(`docs/agent-comm/OUTBOX_GEMINI_engine_test_frontend.md`)에 결과 작성
