# OUTBOX_EXECUTOR - 2026-05-07 08:45 KST - 서버 로그 FileHandler 중복 방지

## 변경 파일 목록

- `backend/main.py`
- `docs/agent-comm/OUTBOX_EXECUTOR_20260507_0845_log_handler_dedupe.md`

## 구현 요약

- `_configure_server_file_logging()`을 root logger 중심으로 단순화했다.
- `logs/server.log` FileHandler는 root logger에만 1개 추가되도록 유지했다.
- `uvicorn`, `uvicorn.error`, `uvicorn.access` logger에는 동일한 `logs/server.log` FileHandler를 직접 추가하지 않도록 변경했다.
- `_logger_has_file_handler()` 중복 검사 함수는 유지해 재호출 시 같은 logger에 동일 파일 핸들러가 중복 추가되지 않도록 했다.

## 테스트 결과

- PASS: `.venv/bin/python -m compileall -q backend`
- PASS: `git diff --check`
- PASS: Python snippet으로 `_configure_server_file_logging()` 5회 재호출 검증
  - `root_server_log_handlers=1`
  - `uvicorn_server_log_handlers=0`

## 남은 위험

- 실제 운영 uvicorn logging config가 root 전파를 별도로 차단하는 경우 access/error 로그 파일 기록 정책은 실행 환경에서 추가 확인이 필요하다.
- 금지 범위에 따라 S1~S11 단계, 주문/매수/매도/청산/decision activate API, 외부 LLM/KIS 호출은 실행하지 않았다.
- git commit은 수행하지 않았다.
