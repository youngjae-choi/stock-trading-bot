# OUTBOX_EXECUTOR_engine_test_url_fix — console.html URL 오류 수정 결과

## 작업 일시
- 2026-05-02 00:05:51 UTC

## 구현 결과
- `backend/static/console.html` 수정
  - `engineTestRun(step)` 호출 URL을 단계별 실제 API 엔드포인트 매핑으로 변경
    - `s1`: `/api/v1/engine/token-refresh`
    - `s2`: `/api/v1/market-tone/analyze`
    - `s3`: `/api/v1/universe-filter/run`
    - `s4`: `/api/v1/screening/run`
    - `s5`: `/api/v1/rulepack-gen/run`
  - 알 수 없는 `step` 값 입력 시 API 호출 없이 오류 상태를 표시하도록 방어 처리 추가
  - `engineTestLoadLogs(filter)` 로그 URL을 `/api/v1/engine/logs`로 변경
  - `/api/v1/engine/logs`의 `payload.lines` 배열 응답도 화면에 표시되도록 기존 `payload.logs` 처리와 함께 하위 호환 보완

## 변경 파일
- `backend/static/console.html`
- `docs/agent-comm/OUTBOX_EXECUTOR_engine_test_url_fix.md`

## 검증 결과
```bash
python3 -c "from html.parser import HTMLParser; p=HTMLParser(); p.feed(open('backend/static/console.html').read()); print('HTML OK')"
```
결과: 통과 (`HTML OK`)

```bash
grep -n "engine/logs\|engine/token-refresh\|market-tone/analyze" backend/static/console.html | head -10
```
결과:
```text
2458:        s1: "/api/v1/engine/token-refresh",
2459:        s2: "/api/v1/market-tone/analyze",
2507:      var url = "/api/v1/engine/logs";
```

```bash
rg -n "/api/v1/testing/run-|/api/v1/testing/logs|payload\.lines|payload\.logs" backend/static/console.html
```
결과:
```text
1974:    sampleLogs = (payload.logs || []).map(function (entry) {
2512:        var logs = data.payload.logs || (Array.isArray(data.payload.lines) ? data.payload.lines.join("\n") : "");
```
- 기존 오류 URL `/api/v1/testing/run-*`, `/api/v1/testing/logs`는 남아 있지 않음.
- `payload.logs`는 다른 화면의 기존 처리와 엔진 로그 하위 호환 처리로만 남아 있음.

## 확인 필요
- 실제 브라우저 버튼 클릭 및 로그인 세션 기반 API 호출 검증은 수행하지 않았다.
- Codex는 프로젝트 규칙상 git commit을 수행하지 않았다.
