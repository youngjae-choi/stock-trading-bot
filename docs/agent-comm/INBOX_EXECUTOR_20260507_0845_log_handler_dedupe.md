# INBOX_EXECUTOR - 2026-05-07 08:45 KST - 서버 로그 FileHandler 중복 방지

## 요청자

Sisyphus

## 담당 페르소나

Executor

## 선행 리뷰

반드시 먼저 읽을 것:

- `docs/agent-comm/OUTBOX_ORACLE_20260507_0840_funnel_diag_repair_review.md`

## 배경

Funnel/Diagnostics 복구 작업은 Oracle 기준 조건부 가능이다. 단, `backend/main.py`의 `_configure_server_file_logging()`이 root, `uvicorn`, `uvicorn.error`, `uvicorn.access`에 모두 같은 `logs/server.log` FileHandler를 붙여 logger 전파 구조에 따라 중복 기록 가능성이 있다.

## 금지 사항

- git commit 금지.
- 사용자 변경사항 되돌리기 금지.
- S1~S11 단계 실행 금지.
- 주문/매수/매도/청산/decision activate API 호출 금지.
- 실계좌/KIS 주문성 API 호출 금지.
- 외부 LLM/KIS 호출 금지.

## 구현 목표

Diagnostics 로그 패널이 읽는 `logs/server.log`에는 backend app logger가 안정적으로 기록되어야 한다. 동시에 uvicorn 계열 logger의 중복 기록 가능성을 줄여야 한다.

## 구현 요구

- `backend/main.py`의 `_configure_server_file_logging()`을 단순화한다.
- root logger에 `logs/server.log` FileHandler 1개를 붙이는 것을 기본으로 한다.
- uvicorn 계열 logger에 같은 FileHandler를 여러 번 붙이지 않는다.
- uvicorn access/error 로그를 꼭 직접 붙여야 한다면 한 군데만 붙이고 `propagate` 정책을 명시하라. 불확실하면 root handler만 유지하라.
- `_logger_has_file_handler()`는 유지해도 되고 더 단순화해도 된다.
- 함수 주석은 유지한다.

## 완료 기준

- backend app logger가 `logs/server.log`에 기록될 수 있다.
- 같은 logger에 동일 FileHandler가 중복 추가되지 않는다.
- uvicorn logger 계층에 동일 FileHandler가 다중 부착되지 않는다.
- compile/diff check 통과.

## 필수 검증

- `.venv/bin/python -m compileall -q backend`
- `git diff --check`
- 가능하면 외부 호출 없이 Python snippet으로 `_configure_server_file_logging()`을 여러 번 호출해도 root의 `logs/server.log` FileHandler가 1개만 유지되는지 확인.

## 결과 보고 파일

작업 완료 후 아래 파일을 작성하라.

`docs/agent-comm/OUTBOX_EXECUTOR_20260507_0845_log_handler_dedupe.md`

포함 항목:

- 변경 파일 목록
- 구현 요약
- 테스트 결과
- 남은 위험
