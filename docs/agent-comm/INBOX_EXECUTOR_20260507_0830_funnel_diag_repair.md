# INBOX_EXECUTOR - 2026-05-07 08:30 KST - Funnel Monitor 및 Diagnostics 신뢰성 복구

## 요청자

Sisyphus

## 담당 페르소나

Executor

## 선행 감사

반드시 먼저 읽을 것:

- `docs/agent-comm/OUTBOX_ORACLE_20260507_0826_funnel_diag_regression_audit.md`

## 배경

PM이 다음 문제를 제기했다.

1. Funnel Monitor 화면이 매일 바뀌어야 하는데 고정값처럼 보인다.
2. `전체 종목 2,500`, Layer 1 탈락 사유, Funnel Quality 문구가 실제 데이터인지 의심된다.
3. System Diagnostics에서 단계를 실행하면 하단 서버 로그에 연결되어 보여야 하는데 `로그가 없습니다.`로 나온다.
4. 자동 실행이 수동 실행처럼 확인 가능해야 하는데, 현재 audit/source/실행시각이 카드에 연결되어 보이지 않는다.

Oracle 감사 결론:

- Funnel 상단 일부 0 값은 2026-05-07 DB 상태와 일치한다.
- 그러나 `전체 종목 2,500`, Layer 1 탈락 사유, Funnel Quality 문구는 하드코딩/mock이다.
- Diagnostics 로그 패널은 `/api/v1/engine/logs`가 `logs/server.log`만 읽는데 실제 서버 로그가 그 파일에 기록되지 않아 빈 로그를 표시한다.
- 최근 상태 표시 수정이 로그 fetch를 직접 깨뜨린 증거는 없지만, 현재 운영 로그 경로와 UI 로그 경로가 불일치한다.
- 자동/수동 실행 audit는 DB에 있으나 Diagnostics 카드에 실행 시각/source/status가 표시되지 않는다.

## 금지 사항

- git commit 금지.
- 사용자 변경사항 되돌리기 금지.
- S1~S11 단계 실행 금지.
- 주문/매수/매도/청산/decision activate API 호출 금지.
- 실계좌/KIS 주문성 API 호출 금지.
- 외부 LLM/KIS 호출 금지.

## 구현 목표

화면이 모르는 값을 아는 척하지 않게 하고, 실제 DB/audit/log에 근거한 상태만 표시한다.

### 1. Funnel Monitor mock/hardcode 제거 또는 명확화

대상 후보:

- `backend/api/routes/funnel.py`
- `backend/static/console.html`

요구:

- `전체 종목 2,500`이 실제 DB 집계가 아니면 라벨을 `KRX 기준값` 또는 `기준 universe`처럼 명확히 표시하고 `source`를 내려라.
- 가능하면 API에 다음 필드를 추가한다.
  - `total_universe_source`
  - `layer1_raw`
  - `layer1_rejected`
  - `has_s3`
  - `has_s4`
  - `has_s5`
  - `empty_reason`
  - `last_updated_at`
- Layer 1 탈락 사유 정적 숫자는 제거한다.
  - 실제 breakdown 데이터가 없으면 `탈락 사유 상세 집계 없음` 또는 `S3 breakdown 미수집`으로 표시한다.
- Funnel Quality 정적 문구는 제거한다.
  - 실제 최근 N거래일 집계를 구현할 수 있으면 DB 기반으로 표시한다.
  - 어렵다면 `품질 집계 미구현` 또는 `후보 없음: S3 통과 0`처럼 실제 상태 설명으로 바꾼다.
- 2026-05-07처럼 `raw_count=30`, `filtered_count=0`, S4/S5 없음인 경우 화면에 “S3는 실행됐으나 통과 종목 0개라 S4/S5 미생성”이 드러나야 한다.

### 2. 후보/assignment 키 정규화

대상: `backend/static/console.html`

요구:

- 후보 코드 매핑은 `symbol || ticker || code`를 모두 지원한다.
- S5 assignment 매칭도 `symbol || ticker || code`를 모두 지원한다.
- S4/S5 결과가 있는 날 후보 테이블의 종목코드/profile이 비어 보이지 않게 한다.

### 3. Diagnostics 서버 로그 패널 복구

대상 후보:

- `backend/api/routes/engine_test.py`
- `backend/main.py`
- `run.sh`
- `backend/static/console.html`

요구:

- `/api/v1/engine/logs`가 읽는 로그 파일과 실제 backend 로그 출력 대상이 일치해야 한다.
- Python logging에 `logs/server.log` FileHandler를 추가하거나, 기존 logging 설정 패턴에 맞는 안전한 방식을 적용한다.
- uvicorn access log까지 완벽히 담기 어렵다면 최소한 backend app logger는 `logs/server.log`에 기록되게 한다.
- API 응답에 다음을 포함한다.
  - `log_path`
  - `exists`
  - `total`
  - `lines`
  - `message`
- UI는 빈 로그일 때 단순히 `로그가 없습니다.`가 아니라 원인을 표시한다.
  - 예: `서버 로그 파일은 비어 있습니다: logs/server.log`
  - 파일 없음이면 `로그 파일을 찾을 수 없습니다`.

### 4. Diagnostics 카드와 pipeline_run_audit 연결

대상 후보:

- `backend/api/routes/engine_test.py`
- `backend/services/engine/pipeline_audit.py`
- `backend/static/console.html`

요구:

- 오늘 최신 `pipeline_run_audit`를 read-only API로 제공하거나 기존 Diagnostics status에 병합한다.
- 카드에 최소한 다음을 표시한다.
  - 마지막 실행 시각 KST
  - source: `auto_scheduler` / `console_manual` / `api_manual`
  - status: `success` / `skipped` / `failed` / `started`
  - message 또는 summary
- PM 친화 문구:
  - `자동 실행 결과를 카드에 표시 중`
  - `수동 확인 실행 결과`
  - `비거래일 스킵`
- 내부 audit 필드는 보존하고 UI 표시만 친절하게 만든다.

### 5. 회귀 테스트

가능하면 외부 호출 없는 Playwright/mock 테스트를 추가하거나 기존 `status-truth.spec.cjs`를 확장한다.

검증 케이스:

- Funnel Monitor에서 하드코딩 Layer 1 탈락 사유 숫자가 더 이상 표시되지 않는다.
- S3 raw 30 / filtered 0 / S4 없음 / S5 없음이면 empty reason이 표시된다.
- 후보 매핑에서 `ticker`와 `code`가 모두 화면 symbol로 표시된다.
- engine logs API가 빈 파일이면 `log_path`, `exists`, `total=0`, 명확한 message를 반환한다.
- Diagnostics 카드가 audit source/time/status를 표시한다.

## 필수 검증

- `.venv/bin/python -m compileall -q backend`
- `git diff --check`
- 외부 호출 없는 targeted Playwright/mock 테스트

## 결과 보고 파일

작업 완료 후 아래 파일을 작성하라.

`docs/agent-comm/OUTBOX_EXECUTOR_20260507_0830_funnel_diag_repair.md`

포함 항목:

- 변경 파일 목록
- 구현 요약
- 테스트 결과
- 남은 위험
- Oracle에게 넘길 리뷰 포인트
