# INBOX_ORACLE - 2026-05-07 19:20 KST - console.html 분리 사전 감사

## 요청자

Sisyphus

## 담당 페르소나

Oracle

## 배경

현재 프론트는 `backend/static/console.html` 하나에 약 7,000줄 이상의 HTML/CSS/JS가 모두 들어간 단일 파일 구조다.

PM 요청:

- 장중이 아니므로 전체 구조를 상식적으로 쪼개라.
- 유지보수와 토큰 소모를 줄이는 방향으로 바꿔라.

## 목표

Executor가 안전하게 파일 분리를 수행할 수 있도록, 현재 `console.html`의 구조/의존성을 읽기 전용으로 분석한다.

## 금지 사항

- 파일 수정 금지.
- git commit 금지.
- 서버 재시작 금지.
- S1~S11 실행 금지.
- 주문/청산/decision activate/API POST 호출 금지.
- 외부 LLM/KIS 호출 금지.

## 조사 항목

1. `console.html`의 큰 구역을 라인 기준으로 분해한다.
   - CSS
   - login/header/sidebar/layout
   - screen sections
   - global state/constants
   - common API helpers
   - navigation
   - screen별 JS
   - boot/init

2. 안전한 1차 분리 범위를 제안한다.
   - 기능 변경 없이 파일만 분리할 수 있는 영역
   - 회귀 위험이 큰 영역
   - 먼저 빼야 할 공통 파일

3. 권장 파일 구조를 제안한다.
   - `backend/static/css/console.css`
   - `backend/static/js/api.js`
   - `backend/static/js/navigation.js`
   - `backend/static/js/screens/*.js`
   - 필요 시 `backend/static/js/state.js`, `utils.js`

4. 전역 함수 의존성 확인.
   - HTML inline `onclick`에서 호출하는 함수 목록
   - 전역 변수 목록
   - 파일 분리 후 `window.*`로 노출해야 하는 함수 목록

5. 테스트 계획 제안.
   - Playwright smoke로 확인해야 할 화면
   - no-op refactor임을 확인할 기준

## 결과 보고 파일

검토 완료 후 아래 파일을 작성하라.

`docs/agent-comm/OUTBOX_ORACLE_20260507_1920_console_split_audit.md`

포함 항목:

- Findings/주의점
- 권장 분리 순서
- 추천 파일 구조
- 전역 의존성 목록
- Executor 작업 지시 초안
- 테스트 계획
