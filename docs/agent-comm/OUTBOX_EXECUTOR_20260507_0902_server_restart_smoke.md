# OUTBOX_EXECUTOR - 2026-05-07 09:02 KST - 서버 재시작 및 read-only smoke 결과

## 요약

- 서버 재시작 완료.
- git commit은 수행하지 않음.
- S1~S11 실행 POST, `/api/v1/decision/activate`, 주문성 API, 외부 LLM/KIS 호출은 수행하지 않음.
- 재시작 후 Decision Engine은 `active=false`로 확인됨.

## 재시작 전 상태

- 확인 시각: 2026-05-07 09:03:12 KST
- uvicorn PID: `133053`
- uvicorn 시작시각: 2026-05-05 19:33:24 UTC
- 실행 명령:
  ```bash
  /home/young/repos/stock-trading-bot/.venv/bin/python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --log-level info
  ```
- git status:
  ```text
  ?? docs/agent-comm/INBOX_EXECUTOR_20260507_0902_server_restart_smoke.md
  ```
- `logs/server.log`: 존재하지만 0 bytes
- `GET /api/v1/decision/status`:
  ```json
  {"ok":true,"payload":{"active":false,"ws_connected":true,"candidates":0,"signals_sent":0}}
  ```
- 인증 필요 API 사전 확인:
  - `GET /api/v1/engine/logs` -> `401 LOGIN_REQUIRED`
  - `GET /api/v1/funnel/summary` -> `401 LOGIN_REQUIRED`
  - `GET /api/v1/market-tone/today` -> `401 LOGIN_REQUIRED`

## 실행한 명령

기존 프로세스 정상 종료:

```bash
kill -TERM 133053
```

동일 uvicorn 명령으로 백그라운드 재시작:

```bash
nohup /home/young/repos/stock-trading-bot/.venv/bin/python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --log-level info > logs/uvicorn.out 2>&1 &
```

## 재시작 후 상태

- 확인 시각: 2026-05-07 09:04:27 KST
- 실제 uvicorn PID: `171631`
- uvicorn 시작시각: 2026-05-07 00:04:06 UTC / 2026-05-07 09:04:06 KST
- PPID: `1` (세션 종료 후에도 유지되는 백그라운드 프로세스)
- 실행 명령:
  ```bash
  /home/young/repos/stock-trading-bot/.venv/bin/python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --log-level info
  ```
- `GET /health`: `200 OK`, `status=healthy`, `version=0.3.0`, DB `ok=true`
- `logs/server.log`: 5205 bytes 이상으로 기록 시작 확인
- 서버 로그에서 확인한 startup:
  - `START: Backend API Server`
  - `SUCCESS: Scheduler started (11 jobs registered)`
  - `SUCCESS: [startup] 오늘 포지션 자동 복원 완료 trade_date=2026-05-07`

## Read-only smoke 결과

### Decision Engine 활성 여부

- 직접 호출: `GET /api/v1/decision/status`
- 결과: `200 OK`
  ```json
  {"ok":true,"payload":{"active":false,"ws_connected":false,"candidates":0,"signals_sent":0}}
  ```
- 판단: 의도치 않은 활성화 없음.

### 로그 패널 API 반영 여부

- 직접 호출: `GET /api/v1/engine/logs?lines=20`
- 결과: `401 LOGIN_REQUIRED`
- 판단:
  - 해당 API는 `require_console_user` 보호 대상이라, 로그인 POST 없이 read-only GET만 수행한 이번 세션에서는 직접 payload 확인 불가.
  - 단, 재시작 후 `logs/server.log` FileHandler는 실제로 연결되어 startup 및 GET 로그가 기록됨.
  - 인증 세션에서 접근하면 `log_path`, `exists`, `total`, `message` payload 확인 가능할 것으로 보이나, 이번 작업 범위에서는 인증 POST/MFA를 수행하지 않음.

### Funnel/status envelope 반영 여부

- 직접 호출:
  - `GET /api/v1/funnel/summary` -> `401 LOGIN_REQUIRED`
  - `GET /api/v1/market-tone/today` -> `401 LOGIN_REQUIRED`
  - `GET /api/v1/universe-filter/today` -> `401 LOGIN_REQUIRED`
  - `GET /api/v1/screening/today` -> `401 LOGIN_REQUIRED`
- 직접 호출 가능했던 S5:
  - `GET /api/v1/daily-plan/today` -> `200 OK`
  - envelope 핵심 필드: `ok=true`, `status=success`, `has_result=true`, `trade_date=2026-05-07`, `result` 존재
- 재시작 직후 `logs/server.log`에 남은 인증 콘솔 세션의 read-only GET 성공 기록:
  - `GET /api/v1/market-tone/today` -> `found=True`
  - `GET /api/v1/universe-filter/today` -> `found=True`
  - `GET /api/v1/screening/today` -> `found=True`
  - `GET /api/v1/funnel/summary` -> `has_s3=True`, `has_s4=True`, `has_s5=True`, `empty_reason=''`
- Funnel summary 로그 payload 핵심:
  - `trade_date=2026-05-07`
  - `total_universe=2500`
  - `layer1_raw=43`
  - `layer1_count=43`
  - `layer2_count=29`
  - `signals_count=0`
  - `positions_count=0`
  - `profile_counts={'LOW_VOL': 1, 'MID_VOL': 6, 'HIGH_VOL': 9, 'THEME_SPIKE': 0}`
  - `empty_reason=''`

## 실패/주의 사항

- 인증 보호 API는 세션 쿠키 없이 `401 LOGIN_REQUIRED`가 정상적으로 반환됨.
- 이번 지시가 read-only GET smoke로 제한되어 있어 로그인/MFA POST는 수행하지 않았고, 그 결과 보호 API의 JSON payload 직접 확인은 제한됨.
- `nohup` 실행 직후 shell이 출력한 background PID는 `171636`이었으나, 실제 uvicorn 프로세스는 `171631`로 확인됨.
- `logs/uvicorn.out`은 비어 있고, 애플리케이션 로그는 `logs/server.log`에 기록됨.
- git 작업트리는 작업 전부터 INBOX 파일이 미추적 상태였고, 본 작업 후 OUTBOX 파일이 추가됨. git commit은 수행하지 않음.
