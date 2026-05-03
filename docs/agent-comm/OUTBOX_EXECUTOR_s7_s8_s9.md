# OUTBOX_EXECUTOR_s7_s8_s9 — 작업 결과

## 요약

S7 주문 실행, S8 포지션 실시간 감시, S9 당일 청산을 백엔드에 통합했다.

- `trading_orders` 테이블 자동 생성
- `pending` 매수 신호 발생 시 KIS 현금 매수 주문 발행
- 주문 성공/실패를 `trading_orders`에 기록
- 주문 성공 시 `trading_signals.status = executed` 업데이트
- PositionManager 인메모리 포지션 등록 및 WS tick 기반 손절/익절/트레일링/시간손절 감시
- 15:20 KST 당일 전량 시장가 청산 job 등록
- 주문/포지션 조회 및 수동 매도/전체 청산 API 추가

## 변경 파일

- `backend/services/engine/order_executor.py` 신규
  - `OrderExecutor` 싱글턴 추가
  - `execute_signal()` 매수 주문 실행
  - `execute_sell()` 매도 주문 실행
  - `trading_orders` 테이블/인덱스 자동 생성
  - RulePack `risk_limits.max_positions`, `position_size_pct` 적용
  - 기존 RulePack 호환을 위해 `max_position_size_rate`도 fallback 처리
  - KIS 실패 시 `status='failed'` 주문 row 저장
- `backend/services/engine/position_manager.py` 신규
  - PositionManager 싱글턴 추가
  - `add_position()`, `remove_position()`, `get_positions()` 구현
  - WS tick 콜백에서 손절/익절/트레일링/시간손절 조건 평가
  - 기존 RulePack 호환을 위해 `stop_loss_rate`, `take_profit_rate`도 fallback 처리
- `backend/services/engine/eod_liquidation.py` 신규
  - `run_eod_liquidation()` 구현
  - 현재 PositionManager 포지션 전량 시장가 매도
- `backend/api/routes/orders.py` 신규
  - `GET /api/v1/orders/today`
  - `GET /api/v1/orders/positions`
  - `POST /api/v1/orders/sell`
  - `POST /api/v1/orders/liquidate-all`
- `backend/services/engine/decision_engine.py` 수정
  - S6 BUY signal 저장 후 S7 `order_executor.execute_signal()` 비동기 실행
  - activate/deactivate 시 PositionManager 콜백 등록/해제
- `backend/services/scheduler.py` 수정
  - `job_eod_liquidation()` 추가
  - 기존 15:20 S9 job을 당일 청산 job으로 교체
  - 청산 후 Decision Engine 비활성화도 수행
- `backend/main.py` 수정
  - orders router 등록

## 검증 결과

### 통과

지시된 완료 기준:

```bash
python -m py_compile backend/services/engine/order_executor.py && echo "order_executor OK"
python -m py_compile backend/services/engine/position_manager.py && echo "position_manager OK"
python -m py_compile backend/services/engine/eod_liquidation.py && echo "eod_liquidation OK"
python -m py_compile backend/api/routes/orders.py && echo "orders_route OK"
python -m py_compile backend/services/engine/decision_engine.py && echo "decision_engine OK"
python -m py_compile backend/services/scheduler.py && echo "scheduler OK"
python -m py_compile backend/main.py && echo "main OK"
python -c "
from backend.services.engine.order_executor import order_executor
from backend.services.engine.position_manager import position_manager
from backend.services.engine.eod_liquidation import run_eod_liquidation
print('all imports OK')
"
```

결과:

```text
order_executor OK
position_manager OK
eod_liquidation OK
orders_route OK
decision_engine OK
scheduler OK
main OK
all imports OK
```

추가 검증:

```bash
python -m compileall -q backend
```

결과: 통과

라우트 등록 확인:

```text
/api/v1/orders/today OK
/api/v1/orders/positions OK
/api/v1/orders/sell OK
/api/v1/orders/liquidate-all OK
```

DB/서비스 직접 검증:

```text
get_today_orders('2099-01-01') -> list
orders_today True 0
positions True 0
```

스케줄러 job 확인:

```text
job_eod_liquidation -> 당일 청산
job_decision_engine_stop -> MISSING
```

### 실패 / 환경 제한

`npm run test:e2e` 및 `npm run _playwright_test_internal` 실행 결과, 현재 Codex 샌드박스의 로컬 네트워크/브라우저 제한으로 실패했다.

주요 오류:

```text
apiRequestContext.get: connect EPERM 127.0.0.1:8000
browserType.launch: ... sandbox_host_linux.cc ... Operation not permitted
```

FastAPI `TestClient`로 lifespan 포함 API 검증도 시도했으나, 현재 앱의 scheduler lifespan과 샌드박스 실행 환경이 맞물려 응답이 반환되지 않았다. 대신 라우트 함수 직접 호출과 라우트 등록 확인으로 새 주문 API의 기본 경로를 검증했다.

## 주의 사항

- Codex는 프로젝트 규칙상 git commit을 실행하지 않았다.
- 작업 시작 전 이미 존재하던 수정/미추적 파일은 되돌리지 않았다.
- KIS 실제 주문 API는 실계좌/모의계좌 설정과 네트워크가 필요한 영역이라 실제 주문 송신 성공까지는 이 샌드박스에서 검증하지 못했다.
- `execute_signal()`은 S6 `_emit_signal()`에서 발생한 신호를 즉시 주문으로 전환한다. 별도 배치 방식의 기존 pending 신호 일괄 처리 API는 이번 지시 범위에 없어서 추가하지 않았다.

## 다음 추천 작업

1. 실제 개발 서버에서 KIS 모의투자 계정으로 소량/테스트 종목 주문 송신 검증
2. PM 브라우저 확인용으로 주문/포지션 UI와 `/api/v1/orders/*` 응답 연동 확인
3. Oracle 리뷰에서 주문 실패 row의 `reason` 저장 범위와 포지션 제거 시점(주문 제출 vs 체결 확인) 정책 확정
