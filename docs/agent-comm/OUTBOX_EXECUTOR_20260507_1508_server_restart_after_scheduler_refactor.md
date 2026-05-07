# OUTBOX_EXECUTOR - 2026-05-07 15:10 KST - Scheduler Refactor 반영 서버 재시작

## 요약

- 요청 커밋 확인: `0541bf2 Refactor scheduler into process triggers`
- uvicorn 재시작 완료.
- 실행성 POST, S1~S11 수동 실행, `/api/v1/decision/activate`, 직접 주문/청산 API 호출 없음.
- 직접 수행한 smoke는 read-only GET 및 로컬 build-only 확인으로 제한.
- git commit 수행하지 않음.

## 재시작 전 상태

- PID: `171631`
- 시작시각: `Thu May 7 00:04:06 2026`
- 실행 명령:
  ```bash
  /home/young/repos/stock-trading-bot/.venv/bin/python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --log-level info
  ```
- git 상태:
  - branch: `main`
  - untracked: `docs/agent-comm/INBOX_EXECUTOR_20260507_1508_server_restart_after_scheduler_refactor.md`

## 재시작 후 상태

- 재시작 명령:
  ```bash
  nohup /home/young/repos/stock-trading-bot/.venv/bin/python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --log-level info > logs/uvicorn.out 2>&1 &
  ```
- 재시작 직후 shell background PID: `178828`
- 최종 상주 uvicorn PID: `178839`
- 최종 상주 PID 시작시각: `Thu May 7 06:09:37 2026`
- 최종 상주 PID 명령:
  ```bash
  /home/young/repos/stock-trading-bot/.venv/bin/python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --log-level info
  ```

## Read-only Smoke 결과

### `GET /health`

- 결과: `200 OK`
- 확인 내용:
  - `status=healthy`
  - `version=0.3.0`
  - `kis_configured=true`
  - `database.ok=true`

### `GET /api/v1/decision/status`

- 결과: `200 OK`
- payload:
  ```json
  {"active": false, "ws_connected": false, "candidates": 0, "signals_sent": 0}
  ```
- Decision Engine active 여부: `false`

### `GET /api/v1/scheduler/status`

- 직접 curl 결과: `401 Unauthorized` (`LOGIN_REQUIRED`)
- 인증 필요로 직접 smoke payload는 확보하지 않음.
- 서버 로그에는 인증된 콘솔/브라우저 GET으로 보이는 조회가 별도 기록됨:
  - `SUCCESS: GET /api/v1/scheduler/status — running=True, jobs=6`

## Scheduler Refactor 반영 여부

로컬 Python build-only 확인을 수행했다. scheduler job을 실행하지 않고 import 후 job 등록 형태만 확인했다.

```text
running=False
jobs=6
job_trade_preparation_pipeline|거래준비 프로세스 S1~S5-A|cron[hour='7', minute='45']
job_decision_engine_start|Decision Engine 활성화|cron[hour='8', minute='59']
job_postprocess_pipeline|후처리 프로세스 S9~S10|cron[hour='15', minute='20']
job_data_backup|데이터 백업|cron[hour='18', minute='0']
job_learning_memory|S11 Learning Memory Builder|cron[hour='22', minute='0']
job_us_market_watch|야간 미국장 관찰|cron[hour='22', minute='0']
```

판정: 기존 S1~S11 개별 job 다수 등록 형태가 아니라 process trigger 중심의 6개 job 형태로 확인되어 refactor 반영됨.

## 로그 확인

`logs/server.log`에서 재시작 흐름 확인:

- `SUCCESS: Scheduler stopped`
- `SUCCESS: Backend API Server Shutdown`
- `START: Backend API Server`
- `SUCCESS: Scheduler started (6 jobs registered)`
- `SUCCESS: [startup] 오늘 포지션 자동 복원 완료 trade_date=2026-05-07`
- smoke 호출 로그:
  - `SUCCESS: /health`
  - `SUCCESS: GET /api/v1/decision/status active=False`

## 실패/주의 사항

- `/api/v1/scheduler/status`는 직접 curl에서 인증 필요로 `401 Unauthorized`가 반환되어, 직접 smoke는 로컬 build-only와 서버 로그 확인으로 대체했다.
- 재시작 후 `logs/server.log`에 콘솔/브라우저 주기 조회로 보이는 read-only GET들이 추가로 기록되었다. 여기에는 `/api/v1/orders/today`, `/api/v1/orders/positions` GET도 포함된다. 직접 실행한 호출은 `/health`, `/api/v1/decision/status`, `/api/v1/scheduler/status` GET 및 로컬 build-only 확인뿐이다.
- 재시작 이후 확인한 로그 tail 범위에서 실행성 POST, 매수/매도/청산 요청, 외부 LLM 호출, 신규 KIS REST/WS 호출은 확인되지 않았다.
- scheduler에는 `job_postprocess_pipeline`이 `15:20 KST`로 등록되어 있다. 장마감 전 자동 실행 정책은 운영 판단 필요.
