# INBOX_EXECUTOR_engine_test_s6 — KIS System Test 페이지에 S6 카드 추가

## 수정 대상
`backend/static/console.html`

## 작업

`screen-engine-test` 섹션의 단계별 카드 그리드에 S6 카드를 추가한다.
기존 S5 카드 바로 뒤에 삽입.

### 추가할 HTML (S5 카드 닫는 `</div>` 바로 뒤)

```html
            <!-- S6 -->
            <div class="card" id="et-card-s6">
              <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                <div>
                  <strong>S6 — Decision Engine 활성화</strong>
                  <div style="font-size:12px; color:var(--muted); margin-top:2px;">09:00 KST · WS 연결 + RulePack 조건 감시</div>
                </div>
                <span class="badge" id="et-badge-s6">대기</span>
              </div>
              <button class="btn" style="width:100%; margin-bottom:10px;" onclick="engineTestRun('s6')">▶ 활성화</button>
              <pre class="et-result" id="et-result-s6" style="display:none;"></pre>
            </div>
```

### `engineTestRun()` 함수의 STEP_URLS에 s6 추가

현재 코드에서 `STEP_URLS` 오브젝트를 찾아:
```javascript
var STEP_URLS = {
  s1: "/api/v1/engine/token-refresh",
  s2: "/api/v1/market-tone/analyze",
  s3: "/api/v1/universe-filter/run",
  s4: "/api/v1/screening/run",
  s5: "/api/v1/rulepack-gen/run"
};
```

아래로 교체:
```javascript
var STEP_URLS = {
  s1: "/api/v1/engine/token-refresh",
  s2: "/api/v1/market-tone/analyze",
  s3: "/api/v1/universe-filter/run",
  s4: "/api/v1/screening/run",
  s5: "/api/v1/rulepack-gen/run",
  s6: "/api/v1/decision/activate"
};
```

## 완료 기준
```bash
python3 -c "from html.parser import HTMLParser; p=HTMLParser(); p.feed(open('backend/static/console.html').read()); print('HTML OK')"
grep -n "et-card-s6\|decision/activate" backend/static/console.html
```

OUTBOX(`docs/agent-comm/OUTBOX_EXECUTOR_engine_test_s6.md`)에 결과 작성.
