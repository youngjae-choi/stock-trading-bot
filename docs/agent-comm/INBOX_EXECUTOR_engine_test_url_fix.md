# INBOX_EXECUTOR_engine_test_url_fix — console.html URL 오류 수정

## 수정 대상
`backend/static/console.html`

## 오류 1: engineTestRun 함수 URL

현재 (약 2457라인):
```javascript
var res = await fetch("/api/v1/testing/run-" + step, { method: "POST" });
```

이것을 아래로 교체 (단계별 실제 API 엔드포인트 매핑):
```javascript
var STEP_URLS = {
  s1: "/api/v1/engine/token-refresh",
  s2: "/api/v1/market-tone/analyze",
  s3: "/api/v1/universe-filter/run",
  s4: "/api/v1/screening/run",
  s5: "/api/v1/rulepack-gen/run"
};
var stepUrl = STEP_URLS[step];
if (!stepUrl) {
  if (badge) { badge.textContent = "오류"; badge.className = "badge status danger"; }
  if (resultEl) { resultEl.textContent = "알 수 없는 step: " + step; }
  return;
}
var res = await fetch(stepUrl, { method: "POST" });
```

## 오류 2: engineTestLoadLogs 함수 URL

현재 (약 2489라인):
```javascript
var url = "/api/v1/testing/logs";
```

이것을 아래로 교체:
```javascript
var url = "/api/v1/engine/logs";
```

## 완료 기준
```bash
python3 -c "from html.parser import HTMLParser; p=HTMLParser(); p.feed(open('backend/static/console.html').read()); print('HTML OK')"
grep -n "engine/logs\|engine/token-refresh\|market-tone/analyze" backend/static/console.html | head -10
```

OUTBOX(`docs/agent-comm/OUTBOX_EXECUTOR_engine_test_url_fix.md`)에 결과 작성.
