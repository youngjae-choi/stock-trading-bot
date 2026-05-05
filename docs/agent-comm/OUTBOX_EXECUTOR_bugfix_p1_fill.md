# OUTBOX_EXECUTOR_bugfix_p1_fill

## 처리 결과

P1 Fill Confirmation 미구현 수정 작업을 완료했다.

## 변경 파일

- `backend/services/kis/domestic/service.py`
  - `get_daily_order_inquiry(date_str, side)` 추가
  - KIS `inquire-daily-ccld` 경로로 당일 주문 체결 내역 조회
  - `side=buy|sell|all`을 KIS `SLL_BUY_DVSN_CD`로 변환
  - 체결 주문만 조회하도록 `CCLD_DVSN=01` 적용

- `backend/services/engine/fill_poller.py`
  - 신규 `FillPoller` 백그라운드 서비스 추가
  - 60초마다 submitted 주문의 KIS 체결 여부 조회
  - 전량 체결 시 `trading_orders.status = filled` 갱신
  - `fills` 테이블에 체결 기록 삽입
  - 새 DB/독립 실행에서도 필요한 주문/체결 테이블을 보장
  - `fills.order_id -> orders.id` FK 충돌 방지를 위해 체결 전 최소 archive `orders` 행을 보장

- `backend/services/engine/decision_engine.py`
  - `activate()`에서 `fill_poller.start(today)` 연동
  - `deactivate()`에서 `fill_poller.stop()` 연동
  - 서버 재시작 후 인메모리 포지션이 비어 있으면 `position_stop_states` + `trading_orders`에서 포지션 복원

- `backend/api/routes/orders.py`
  - `GET /api/v1/orders/positions` 응답에 UI alias 추가
  - `stop_loss_price`, `take_profit_price`, `pnl_pct`, `current_price` 포함

## 공식 문서/근거 확인

- 한국투자증권 공식 GitHub 샘플 `examples_llm/domestic_stock/inquire_daily_ccld/inquire_daily_ccld.py` 확인
- 해당 샘플 기준 체결구분 파라미터는 `CCLD_DVSN`이므로 지시서의 `CCL_DVSN` 대신 `CCLD_DVSN`으로 적용

## 검증 결과

### py_compile

```bash
python3 -m py_compile \
  backend/services/kis/domestic/service.py \
  backend/services/engine/fill_poller.py \
  backend/services/engine/decision_engine.py \
  backend/api/routes/orders.py
```

결과:

```text
py_compile OK
```

### 지시서 검증 스크립트

```text
FillPoller created: <backend.services.engine.fill_poller.FillPoller object at ...>
poll_once result: {'filled': 0, 'unchanged': 0}
PASS
```

### 로컬 체결 반영 로직 검증

임시 DB(`/tmp/fill_poller_test.sqlite3`)에서 submitted 주문 1건과 KIS mock 체결 응답을 구성해 `poll_once()` 실행.

결과:

```text
{'filled': 1, 'unchanged': 0}
status: filled fills: 1
```

### 포지션 응답 핸들러 검증

`get_positions_api()` 직접 호출 결과:

```text
{'ok': True, 'payload': {'positions': [], 'count': 0}}
```

## 확인 필요 / 리스크

- 실제 KIS 계좌 연결 체결 조회는 로컬 환경에서 API 키/실주문 체결 데이터가 없어 수행하지 못했다.
- `FillPoller`는 8시간 이상 지난 submitted 주문은 조회 대상에서 제외한다.
- `position_manager.add_position()` 기반 복원은 entry/qty/rule 기준으로 포지션을 재등록한다. 기존 `position_stop_states`의 trailing 세부 상태를 완전 재현하는 전용 restore API는 아직 없다.

## 완료 체크리스트

- [x] `backend/services/kis/domestic/service.py`에 `get_daily_order_inquiry()` 추가
- [x] `backend/services/engine/fill_poller.py` 신규 생성
- [x] `decision_engine.py activate()`에 `fill_poller.start()` + `_restore_positions_from_db()` 추가
- [x] `decision_engine.py deactivate()`에 `fill_poller.stop()` 추가
- [x] `orders.py GET /positions`에 필드 정규화 추가
- [x] py_compile 전체 통과
- [x] 검증 스크립트 통과
