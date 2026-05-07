# INBOX_ORACLE - 2026-05-07 19:50 KST - console.html Stage 1 분리 리뷰

## 요청자

Sisyphus

## 담당 페르소나

Oracle

## 배경

Executor가 Stage 1 분리를 완료했다.

- 지시: `docs/agent-comm/INBOX_EXECUTOR_20260507_1930_console_split_stage1.md`
- 결과: `docs/agent-comm/OUTBOX_EXECUTOR_20260507_1930_console_split_stage1.md`

변경 요약:

- `backend/static/console.html`: 7065줄 → 1672줄
- `backend/static/css/console.css`: 기존 style 추출
- `backend/static/js/console.js`: 기존 script 추출, classic script
- `tests/e2e/status-truth.spec.cjs`: file URL 대신 테스트 static server 사용

## 리뷰 목표

1. CSS/JS 추출이 기능 변경 없는 no-op인지 확인.
2. `/static/css/console.css`, `/static/js/console.js` 경로가 FastAPI static mount와 맞는지 확인.
3. classic script라 inline handler가 계속 동작할 수 있는지 확인.
4. HTML section id/nav/screen 구조가 유지됐는지 확인.
5. `status-truth.spec.cjs` 테스트 조정이 안전한지 확인.
6. ReferenceError/TypeError/asset load failure가 없는지 확인.
7. 다음 Stage 2로 넘어갈 수 있는지 판단.

## 금지 사항

- 파일 수정 금지.
- git commit 금지.
- 서버 재시작 금지.
- S1~S11 실행 금지.
- 주문/청산/decision activate/API POST 호출 금지.
- 외부 LLM/KIS 호출 금지.

## 필수 검증

- `node --check backend/static/js/console.js`
- `node --check tests/e2e/status-truth.spec.cjs`
- `.venv/bin/python -m compileall -q backend`
- `git diff --check`
- `npx playwright test --config=playwright.config.cjs tests/e2e/status-truth.spec.cjs --workers=1`
- 가능하면 static server/mock 기반으로 주요 nav heading과 asset load 확인

## 결과 보고 파일

검토 완료 후 아래 파일을 작성하라.

`docs/agent-comm/OUTBOX_ORACLE_20260507_1950_console_split_stage1_review.md`

포함 항목:

- Findings 우선
- 테스트 결과
- 최종 판단: 배포 가능 / 조건부 가능 / 불가
- Stage 2 권고
- 남은 위험
