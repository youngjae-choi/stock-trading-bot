# INBOX_EXECUTOR - 2026-05-07 19:30 KST - console.html Stage 1 분리

## 요청자

Sisyphus

## 담당 페르소나

Executor

## 선행 감사

반드시 먼저 읽을 것:

- `docs/agent-comm/OUTBOX_ORACLE_20260507_1920_console_split_audit.md`

## 배경

현재 `backend/static/console.html`은 약 7,000줄 단일 파일이며 HTML/CSS/JS가 모두 섞여 있다. PM 요청은 유지보수성과 토큰 소모를 줄이기 위해 상식적으로 파일을 쪼개는 것이다.

Oracle 권고:

- 1차 분리는 CSS 추출 + 전체 JS 단일 파일 추출까지만 한다.
- 바로 ES module/screen module로 쪼개면 inline handler와 전역 함수 의존성이 깨질 위험이 크다.

## 금지 사항

- git commit 금지.
- 사용자 변경사항 되돌리지 말 것.
- 서버 재시작 금지.
- S1~S11 실행 금지.
- 주문/청산/decision activate/API POST 호출 금지.
- 외부 LLM/KIS 호출 금지.
- 기능 변경 금지. 이번 작업은 no-op 구조 분리다.

## 구현 범위

### 1. CSS 추출

- `backend/static/css/console.css` 생성.
- `console.html`의 `<style>...</style>` 내용을 그대로 이동.
- `console.html`에는 `<link rel="stylesheet" href="/static/css/console.css">`를 둔다.
- inline `style=""`은 건드리지 않는다.

### 2. JS 전체 단일 파일 추출

- `backend/static/js/console.js` 생성.
- `console.html`의 하단 `<script>...</script>` 내용을 그대로 이동.
- `console.html`에는 body 끝에 `<script src="/static/js/console.js"></script>`를 둔다.
- `type="module"` 사용 금지. classic script로 유지한다.
- 함수 본문 수정/이벤트 방식 변경/API endpoint 변경 금지.

### 3. 테스트 조정

- 기존 `tests/e2e/status-truth.spec.cjs`가 `file://`로 HTML을 열면 `/static/js/...`를 못 읽을 수 있다.
- 해당 테스트를 `/console` 또는 로컬 static route mock 방식으로 조정하라.
- 테스트 중 S1~S11 실행 버튼, 청산/매도/decision activate/settings save 같은 POST는 클릭하지 말 것.

### 4. 검증

필수:

- HTML에 CSS/JS 링크가 존재하는지 확인.
- `node --check backend/static/js/console.js`
- `.venv/bin/python -m compileall -q backend`
- `git diff --check`
- Playwright non-mutating smoke:
  - `/console` 로드 또는 안전한 static server/mock
  - 주요 화면 heading/nav 존재
  - `Failed to load resource /static/...` 없음
  - `ReferenceError`/`TypeError` 없음
  - status-truth spec 통과 또는 조정 후 통과

## 완료 기준

- `console.html` 줄 수가 크게 감소한다.
- CSS와 JS가 별도 파일로 분리된다.
- 기존 화면 구조와 전역 함수 동작은 유지된다.
- targeted Playwright가 통과한다.
- 결과 OUTBOX 작성.

## 결과 보고 파일

작업 완료 후 아래 파일을 작성하라.

`docs/agent-comm/OUTBOX_EXECUTOR_20260507_1930_console_split_stage1.md`

포함 항목:

- 변경 파일 목록
- 분리 전/후 파일 라인 수
- 구현 요약
- 테스트 결과
- 남은 위험
- Oracle 리뷰 포인트
