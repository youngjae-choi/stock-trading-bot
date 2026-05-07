# OUTBOX_ORACLE - 2026-05-07 19:50 KST - console.html Stage 1 분리 리뷰

## Findings

- P1: 없음.
- P2: 없음.

## 검토 결과

- `backend/static/console.html`의 기존 inline `<script>` 본문과 `backend/static/js/console.js`는 SHA/길이 기준으로 일치한다.
- 기존 HTML에서 style/script만 link/script src로 치환한 결과와 현재 `console.html`은 SHA/길이 기준으로 일치한다.
- 기존 inline `<style>` 본문과 `backend/static/css/console.css`는 `style` 태그 주변 선행/후행 공백 제거만 차이가 있고, `trim()` 기준 내용은 일치한다.
- screen section id 18개와 nav `data-screen` 15개는 분리 전/후 동일하다.
- `console.html`은 `/static/css/console.css`, `/static/js/console.js`를 참조하며, FastAPI는 `backend/main.py`에서 `backend/static`을 `/static`으로 mount하고 있어 경로가 맞다.
- 새 JS는 `type="module"` 없이 classic script로 로드된다. top-level `function`/`var` 기반 전역 접근 방식이 유지되어 inline handler와 동적 HTML handler 의존성이 보존된다.
- `tests/e2e/status-truth.spec.cjs`의 테스트 서버는 `/console`과 `/static/*` GET만 제공한다. API 응답은 `window.fetch` mock으로 처리되며, S1~S11 실행/주문/청산/decision activate/API POST 호출은 수행하지 않았다.

## 테스트 결과

- PASS: `node --check backend/static/js/console.js`
- PASS: `node --check tests/e2e/status-truth.spec.cjs`
- PASS: `.venv/bin/python -m compileall -q backend`
- PASS: `git diff --check`
- PASS: `npx playwright test --config=playwright.config.cjs tests/e2e/status-truth.spec.cjs --workers=1`
  - 8 passed
  - extracted asset link/script 존재 확인
  - `.screen` 18개 확인
  - 주요 전역 함수 확인
  - `/static` asset load failure 없음
  - `ReferenceError`/`TypeError` 없음

## 최종 판단

- 배포 가능.
- 단, 현재 `backend/static/css/`와 `backend/static/js/`는 untracked 상태이므로 최종 커밋/배포 묶음에 반드시 포함해야 한다. 누락되면 `/static/css/console.css`, `/static/js/console.js` asset load failure로 console UI가 깨진다.

## Stage 2 권고

- Stage 2 진행 가능.
- JS를 추가 분리할 때는 classic script 로드 순서와 전역 함수 노출 계약을 먼저 고정해야 한다.
- `showScreen()`에서 screen별 loader를 호출하는 흐름을 기준으로 의존성 그래프를 만든 뒤 작은 단위로 분리하는 것을 권고한다.
- `_settingsProfileData`처럼 동적 `onchange` 문자열에서 참조하는 전역 상태는 Stage 2에서 명시적으로 `window` 계약 또는 이벤트 바인딩 방식으로 정리하는 것이 안전하다.
- `generateDailyPlan()`의 암묵적 `event` 의존성은 Stage 2 이후 별도 안정화 항목으로 추적하는 것을 권고한다.

## 남은 위험

- 이번 Stage 1은 no-op 추출에 가깝지만, 기존 console의 대형 전역 상태와 inline handler 구조 자체의 위험은 그대로 남아 있다.
- Playwright 검증은 mock/static server 기반이다. 실제 운영 서버에서의 asset serve는 FastAPI mount 경로로 논리 확인했으며, 서버 재시작 금지 조건 때문에 실제 서버 재기동 검증은 수행하지 않았다.
- 기존 `tests/e2e/console-smoke.spec.cjs`에는 위험 API POST를 호출할 수 있는 시나리오가 있어 이번 리뷰 범위에서는 실행하지 않았다.
