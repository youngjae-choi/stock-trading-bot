# INBOX_EXECUTOR - 2026-05-07 09:02 KST - 서버 재시작 및 반영 확인

## 요청자

Sisyphus

## 담당 페르소나

Executor

## 배경

최근 다음 커밋들이 반영되었지만, 운영 uvicorn 프로세스는 2026-05-05부터 실행 중이라 최신 코드가 메모리에 반영되지 않았다.

- `853c824 Fix pipeline status truth display`
- `4a5812f Repair funnel diagnostics and log visibility`

PM 요청: 서버를 재시작하고 수정사항이 실제 화면/API에 반영되는지 테스트한다.

현재 시각은 2026-05-07 09:02 KST 전후이며 장중이다. 따라서 재시작 후 절대 매매/주문/단계 실행을 유발하지 말고 read-only smoke만 수행한다.

## 금지 사항

- git commit 금지.
- S1~S11 단계 실행 금지.
- `/api/v1/decision/activate` 호출 금지.
- 주문/매수/매도/청산/decision activate API 호출 금지.
- 실계좌/KIS 주문성 API 호출 금지.
- 외부 LLM/KIS 호출 금지.
- DB 값을 임의 변경하지 말 것.

## 작업 절차

1. 현재 실행 중인 uvicorn 프로세스와 명령을 확인한다.
2. 현재 git 작업트리가 깨끗한지 확인한다.
3. 서버 재시작 전 현재 상태를 read-only로 기록한다.
   - KST 시각
   - uvicorn PID/시작시각
   - `/api/v1/decision/status` GET 결과
   - `logs/server.log` 상태
4. 기존 uvicorn 프로세스를 정상 종료한다.
5. 동일 명령 또는 프로젝트 표준 실행 방식으로 uvicorn을 재시작한다.
   - 기존 프로세스 명령이 `/home/young/repos/stock-trading-bot/.venv/bin/python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --log-level info`이면 동일하게 사용한다.
   - 백그라운드 실행하되 세션이 끊겨도 유지되도록 한다.
6. 재시작 후 read-only smoke를 수행한다.
   - `/api/v1/decision/status` GET: `active`가 의도치 않게 true가 아닌지 확인
   - `/api/v1/engine/logs` GET: `log_path`, `exists`, `total`, `message` 확인
   - Funnel summary GET: mock 문구 제거/empty_reason 관련 필드 확인
   - S2/S3/S4/S5 today GET envelope 확인: `status`, `has_result`, `result`, `trade_date`
   - 실제 S1~S11 실행 POST는 절대 호출하지 않는다.
7. 가능하면 Playwright 또는 curl 기반으로 System Diagnostics/Funnel 관련 API만 확인한다. 로그인/MFA가 막히면 API smoke만 보고한다.
8. 결과 보고 파일을 작성한다.

## 결과 보고 파일

작업 완료 후 아래 파일을 작성하라.

`docs/agent-comm/OUTBOX_EXECUTOR_20260507_0902_server_restart_smoke.md`

포함 항목:

- 재시작 전/후 PID와 시각
- 실행한 명령
- read-only smoke 결과
- Decision Engine 활성 여부
- 로그 패널 API 반영 여부
- Funnel/status envelope 반영 여부
- 실패/주의 사항
