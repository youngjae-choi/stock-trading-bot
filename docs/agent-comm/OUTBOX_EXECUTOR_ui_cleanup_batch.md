# OUTBOX_EXECUTOR_ui_cleanup_batch

## 처리 상태

완료.

## 변경 파일

- `backend/static/console.html`

## 구현 내용

### Task 1 — Today Control 화면 정리

- 상단 `top-status` 상태 pill 블록을 제거했습니다.
- Today Control의 `System Health` 카드를 제거했습니다.
- `Today's Timeline`과 `Recent Operation Logs`를 `오늘 운영 현황` 단일 카드로 병합했습니다.
- 기존 JS의 `engineDot`, `engineText`, `restDot`, `restStatusText`, `socketDot`, `socketStatusText`, `phaseText` 참조는 null-safe 상태로 유지했습니다.

### Task 2 — Statistics → 거래내역

- 화면명을 `거래내역`으로 변경했습니다.
- 메뉴와 모바일 select에서 `statistics`를 3번째로 이동했습니다.
- 기간 필터에 `오늘`, `이번주`를 추가하고 기본값을 `today`로 변경했습니다.
- `filterStItems()`에 `today`, `week` 필터 로직을 추가했습니다.
- 오늘 체결 내역과 거래중 미체결 주문 테이블을 추가했습니다.
- `loadTodayTrades()`를 추가하고 `statistics` 화면 진입 시 호출되도록 연결했습니다.

### Task 3 — API Logs 화면 정리

- API Logs 상단 compact 카드 3개를 제거했습니다.
- 제거된 카드 관련 JS 참조는 기존 null-safe 조건문으로 유지했습니다.
- 호출시간 표시를 `YY-MM-DD HH:MM:SS` 형식으로 변경했습니다.

### Task 4 — Settings 리스크/청산 통합

- `Risk Settings` 카드와 `포지션 청산 조건 Override` 카드를 `리스크 & 청산 설정` 카드로 통합했습니다.
- `exitOverrideSettingsTableBody`는 통합 카드 내부로 이동했습니다.
- Notification 카드는 기존 `.split` 구조 안에 유지했습니다.

### Task 5 — Data & API System Health 이동

- `System Health` 카드를 Data & API 화면의 compact 카드 그리드 아래로 추가했습니다.
- 기존 health id(`kisTokenStatus`, `rulepackStatus`, `websocketStatus`, `riskStatus`)를 유지해 기존 JS 갱신 경로와 연결되도록 했습니다.

## 검증 결과

- INBOX 완료 기준 Python 체크: PASS
- `node` script block parse 검사: PASS (`PASS parsed 1 script block(s)`)
- `rg` 확인:
  - `<div class="top-status">` 제거 확인
  - `오늘 운영 현황`, `거래내역`, `sf-today`, `sf-week`, `loadTodayTrades`, `rawTime.slice(2, 10)`, `리스크 & 청산 설정`, Data & API `System Health` 확인
  - `최근 집계`, `포지션 청산 조건 Override` 별도 카드 문자열 제거 확인

## 잔여 리스크

- 브라우저 수동 확인은 수행하지 않았습니다.
- 작업 시작 전 `backend/static/console.html`을 포함한 다수 파일이 이미 수정된 상태였습니다. 이번 작업은 요청된 `backend/static/console.html`과 OUTBOX 작성만 수행했습니다.
