# OUTBOX_EXECUTOR_account_s6 — 계좌 API + S6 Decision Engine + WS 콜백 구조

## 작업 결과

완료.

## 변경 파일

- `backend/api/routes/account.py` 신규
  - `GET /api/v1/account/balance` 추가
  - KIS `get_balance()` 응답의 `output1`, `output2[0]`를 표준 payload로 변환
  - KIS 설정 누락 시 `KIS_CONFIG_MISSING` 응답 반환

- `backend/services/kis/realtime_ws.py` 수정
  - `register_tick_callback()`, `unregister_tick_callback()` 추가
  - 파이프 구분 실시간 tick 파싱 후 async callback dispatch 추가
  - callback 예외는 로그만 남기고 WS loop는 유지

- `backend/services/engine/decision_engine.py` 신규
  - `DecisionEngine` 싱글턴 추가
  - 활성 RulePack + S4 screening candidates 로드
  - 실시간 tick 수신 시 기본 RulePack 조건 평가
  - BUY signal 중복 방지 및 `trading_signals` 테이블 저장
  - `get_today_signals(trade_date)` 조회 함수 추가

- `backend/api/routes/decision.py` 신규
  - `GET /api/v1/decision/signals/today`
  - `GET /api/v1/decision/status`
  - `POST /api/v1/decision/activate`
  - `POST /api/v1/decision/deactivate`

- `backend/services/scheduler.py` 수정
  - `job_decision_engine_start()` 추가
  - `job_decision_engine_stop()` 추가
  - `schedule_s6_time` 기본값 `09:00`
  - `schedule_s9_time` 기본값 `15:20`
  - scheduler job 등록 연결

- `backend/main.py` 수정
  - account router 등록
  - decision router 등록

## 구현 메모

- 인박스에는 `get_active_rulepack()` 참조가 있었지만 실제 코드에는 해당 함수가 없어서 기존 활성 코드인 `get_active_rulepack_for_date()`를 사용했다.
- S4 후보는 현재 `ticker`, `suitability_score` 기반으로 저장될 수 있어 `symbol`/`ticker`, `confidence`/`suitability_score`를 모두 허용했다.
- `trading_signals` 테이블은 Decision Engine 조회/저장 시 `CREATE TABLE IF NOT EXISTS`로 보장한다.
- WS tick에 5일 평균 거래량 기준값이 없어 `volume_ratio`는 tick volume 수신 여부 또는 최소 기준 1.0 이하일 때 충족으로 처리했다.

## 검증 결과

통과:

```bash
python -m py_compile backend/api/routes/account.py && echo "account OK"
python -m py_compile backend/services/kis/realtime_ws.py && echo "ws OK"
python -m py_compile backend/services/engine/decision_engine.py && echo "decision OK"
python -m py_compile backend/api/routes/decision.py && echo "decision_route OK"
python -m py_compile backend/services/scheduler.py && echo "scheduler OK"
python -m py_compile backend/main.py && echo "main OK"
python -c "from backend.services.engine.decision_engine import decision_engine, get_today_signals; print('import OK')"
```

추가 확인:

- 계좌 payload 변환 함수 smoke: `1234567 005930 10`
- WS callback dispatch smoke: `005930 73000 100`
- Decision API 함수 smoke: status `{active: False, ws_connected: False, candidates: 0, signals_sent: 0}`, today signals count `0`

## 확인 필요

- 실제 `GET /api/v1/account/balance` 라이브 호출은 KIS 외부 API 접근과 실계정/모의계정 설정이 필요해 현재 제한된 로컬 환경에서는 최종 응답 확인이 필요하다.
- `POST /api/v1/decision/activate` 라이브 동작은 당일 active RulePack, S4 screening 결과, KIS WebSocket approval key가 모두 준비된 상태에서 확인 필요.
- 기존 설정 UI는 별도 작업에서 `schedule_close_time` 등을 쓰는 흔적이 있어, UI가 `schedule_s6_time`/`schedule_s9_time`을 표시하도록 맞추는 후속 정합성 점검이 필요하다.
