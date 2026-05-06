# INBOX_EXECUTOR - 2026-05-07 08:10 KST - 상태 표시 진실성 수정

## 요청자

Sisyphus

## 담당 페르소나

Executor

## 배경

PM이 2026-05-07 08:00 KST 전후 콘솔에서 이상 동작을 발견했다.

- Today 화면과 System Diagnostics가 S2~S5를 완료/성공처럼 표시했다.
- 그러나 Diagnostics 결과 JSON은 `market_tone: null`, `universe: null`, `screening: null`, S5 `payload: null`이었다.
- PM이 S2를 수동으로 실행하자 정상 payload가 반환되었다.
- Oracle 읽기 전용 감사 결과, 실제로 S3~S5가 시간 무시 실행된 것이 아니라 UI가 `ok: true`만 보고 완료로 표시한 것이 원인으로 확인되었다.

## 핵심 판단

이 작업의 목표는 자동매매 로직을 새로 실행하는 것이 아니라, 콘솔이 실제 상태를 거짓으로 표시하지 않게 만드는 것이다.

`ok: true`는 API 조회 성공일 뿐 단계 완료가 아니다. 단계 완료는 실제 결과 payload, trade date, audit/status를 기준으로 판단해야 한다.

## 금지 사항

- git commit 금지.
- 사용자 변경사항 되돌리기 금지.
- S1~S11 단계 실행 금지.
- 주문/매수/매도/청산/decision activate API 호출 금지.
- 실계좌/KIS 주문성 API 호출 금지.
- 외부 LLM/KIS 호출을 유발하는 테스트 금지.

## 구현 범위

### 1. Today 화면 상태판정 수정

대상: `backend/static/console.html`

- S2~S5 완료 여부를 `ok`만으로 판단하지 말 것.
- S2는 오늘 날짜의 `market_tone` 결과가 실제로 있을 때만 완료.
- S3는 오늘 날짜의 `universe` 또는 필터 결과가 실제로 있을 때만 완료.
- S4는 오늘 날짜의 `screening` 또는 스크리닝 결과가 실제로 있을 때만 완료.
- S5는 `payload`가 null이 아니고 오늘 날짜 plan id/status가 있을 때만 완료.
- 결과가 없으면 `대기`, `미생성`, 또는 `비거래일 스킵`으로 표시할 것.

### 2. System Diagnostics 상태판정 수정

대상: `backend/static/console.html`

- GET 조회 응답이 `ok: true`여도 payload 내부 결과가 null이면 완료/성공 배지를 붙이지 말 것.
- POST 실행 결과와 GET 조회 결과를 구분해서 표시할 것.
- null payload는 검은 JSON 박스에 그대로 보여주되, 상태는 `대기` 또는 `미생성`이어야 한다.
- `schedule_skip_today=true`이면 S2~S6에 `비거래일 스킵` 또는 `스킵` 상태를 명확히 표시할 것.

### 3. API 응답 envelope 보강

대상 후보:

- `backend/api/routes/market_tone.py`
- `backend/api/routes/universe.py`
- `backend/api/routes/screening.py`
- `backend/api/routes/daily_plan.py`

요구:

- 기존 응답 하위 호환성은 유지한다.
- GET 응답에 가능한 한 공통 필드를 추가한다.
  - `status`: `pending | success | skipped | failed`
  - `has_result`: boolean
  - `result`: 실제 결과 또는 null
  - `trade_date`
- 기존 `payload` 구조를 깨지 말고, 프론트가 새 필드를 우선 사용하게 한다.

### 4. skip 상태 반영

대상 후보:

- `backend/api/routes/scheduler.py`
- `backend/services/scheduler.py`
- `backend/static/console.html`

요구:

- `schedule_skip_today=true`일 때 Today/System Diagnostics에서 완료가 아니라 skip으로 보이게 한다.
- skipped와 completed를 명확히 분리한다.

### 5. 실행 중 코드 버전/서버 시작 시각 표시 검토

가능하면 System Status 또는 Diagnostics API에 다음 정보를 read-only로 추가한다.

- 현재 git commit 또는 unknown
- 서버 프로세스 시작 시각
- 앱이 바라보는 코드 버전

단, 범위가 커지면 이 항목은 후속 작업으로 남겨도 된다.

## 완료 기준

- null payload가 더 이상 완료/성공으로 표시되지 않는다.
- 2026-05-07 08:00 상황처럼 S3~S5 산출물이 없으면 Today와 Diagnostics 모두 대기/미생성/스킵으로 표시된다.
- S2 수동 실행 후에는 S2만 성공/완료로 표시되고, S3~S5는 실제 결과가 생기기 전까지 완료가 아니다.
- `schedule_skip_today=true`이면 S2~S6은 완료가 아니라 skip으로 표현된다.
- compile/diff check가 통과한다.
- 외부 API 호출 없는 로컬 smoke 또는 Playwright mock 검증을 수행한다.

## 필수 검증

- `.venv/bin/python -m compileall -q backend`
- `git diff --check`
- 가능하면 Playwright route mock 또는 로컬 정적 화면 검증:
  - S2 GET: `{ ok: true, payload: { market_tone: null, trade_date: today }, has_result: false }` -> 상태 대기/미생성
  - S3 GET null -> 완료 아님
  - S4 GET null -> 완료 아님
  - S5 GET `{ ok: true, payload: null }` -> 완료 아님
  - S2 POST success result -> S2만 성공

## 결과 보고 파일

작업 완료 후 아래 파일을 작성하라.

`docs/agent-comm/OUTBOX_EXECUTOR_20260507_0810_status_truth_fix.md`

포함 항목:

- 변경 파일 목록
- 구현 요약
- 테스트 결과
- Playwright/mock 확인 결과
- 남은 위험
- Oracle에게 넘길 리뷰 포인트
