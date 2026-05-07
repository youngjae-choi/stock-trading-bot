# OUTBOX_EXECUTOR - 2026-05-07 19:30 KST - console.html Stage 1 분리

## 변경 파일 목록

- `backend/static/console.html`
- `backend/static/css/console.css`
- `backend/static/js/console.js`
- `tests/e2e/status-truth.spec.cjs`
- `docs/agent-comm/OUTBOX_EXECUTOR_20260507_1930_console_split_stage1.md`

## 분리 전/후 파일 라인 수

| 파일 | 분리 전 | 분리 후 |
|---|---:|---:|
| `backend/static/console.html` | 7065 | 1672 |
| `backend/static/css/console.css` | 0 | 811 |
| `backend/static/js/console.js` | 0 | 4580 |

## 구현 요약

- `console.html`의 기존 `<style>...</style>` 내용을 `backend/static/css/console.css`로 이동했다.
- `console.html` head에 `<link rel="stylesheet" href="/static/css/console.css">`를 추가했다.
- `console.html` 하단의 기존 classic `<script>...</script>` 내용을 `backend/static/js/console.js`로 이동했다.
- `console.html` body 끝에 `<script src="/static/js/console.js"></script>`를 추가했다.
- `type="module"`은 사용하지 않았고, inline handler와 top-level 전역 함수 노출 방식은 classic script 그대로 유지했다.
- HTML section 구조와 inline `style=""`, inline `onclick/onchange`, 함수 본문, API endpoint는 변경하지 않았다.
- `tests/e2e/status-truth.spec.cjs`는 `file://` 로드 대신 테스트 내부 static server로 `/console`과 `/static/...`만 제공하도록 조정했다.
- status-truth 테스트의 API 호출은 기존처럼 `window.fetch` mock을 사용한다. S1~S11 실행, 주문, 청산, decision activate, settings save 계열 POST는 클릭하거나 호출하지 않았다.
- status-truth smoke를 추가해 CSS/JS 링크 존재, 18개 screen 유지, 주요 전역 함수 유지, `/static` 로드 실패 없음, `ReferenceError`/`TypeError` 없음까지 확인했다.

## 테스트 결과

- PASS: `node --check backend/static/js/console.js`
- PASS: `node --check tests/e2e/status-truth.spec.cjs`
- PASS: `.venv/bin/python -m compileall -q backend`
- PASS: `git diff --check`
- PASS: `npx playwright test --config=playwright.config.cjs tests/e2e/status-truth.spec.cjs --workers=1`
  - 8 passed

## 남은 위험

- 이번 작업은 no-op 구조 분리만 수행했으므로 기존 console의 대형 전역 상태, inline handler, 동적 HTML 문자열 handler 의존성은 그대로 남아 있다.
- `console.html`은 줄 수가 줄었지만 HTML 자체도 아직 큰 편이다. screen별 JS 분리는 Oracle 권고대로 별도 Stage에서 classic script 순서를 고정한 뒤 진행하는 편이 안전하다.
- 기존 `tests/e2e/console-smoke.spec.cjs`에는 halt API POST를 호출하는 테스트가 남아 있으므로 이번 분리 검증에는 사용하지 않았다.
- `git diff --check`는 통과했지만 새 파일은 현재 untracked 상태이므로 최종 커밋 전 포함 여부 확인이 필요하다. Executor는 지시에 따라 git commit을 수행하지 않았다.

## Oracle 리뷰 포인트

- `/static/css/console.css`, `/static/js/console.js` 경로가 FastAPI static mount와 맞는지 재확인.
- classic script 유지로 inline handler의 `window.*` 접근이 보존되는지 재확인.
- `status-truth.spec.cjs`의 테스트 내부 static server 방식이 서버 재시작 금지 조건과 POST 금지 조건을 만족하는지 확인.
- Stage 2 이후 screen별 JS 분리 시 `showScreen()` loader 의존성, `_settingsProfileData` 동적 onchange 접근, `generateDailyPlan()`의 암묵적 `event` 의존성을 별도 리스크로 추적.
