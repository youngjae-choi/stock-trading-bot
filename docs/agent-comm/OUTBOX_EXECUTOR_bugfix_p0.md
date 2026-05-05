# OUTBOX_EXECUTOR_bugfix_p0

## 처리 일시
- 2026-05-05

## 처리 요약
- P0 버그 1: `trading_signals.profile_assigned` 마이그레이션 경로 확인 완료
- P0 버그 2: KIS 초당 한도 초과 완화를 위해 BUY signal 실행 직렬화, 잔고 캐시, 주문 후 최소 대기 적용 완료

## 변경 파일
- `backend/services/engine/order_executor.py`
- `docs/agent-comm/OUTBOX_EXECUTOR_bugfix_p0.md`

## 상세 결과

### 버그 1 — trading_signals profile_assigned 컬럼 누락
- 현재 `backend/services/db.py`에는 이미 `trading_signals` 전용 마이그레이션 함수가 존재한다.
- `initialize_database()`에서 `PRAGMA table_info(trading_signals)`로 컬럼 존재 여부를 확인한 뒤 `_trading_signal_migration_statements()`를 실행한다.
- `_trading_signal_migration_statements()`에 아래 항목이 이미 존재함을 확인했다.

```python
("profile_assigned", "ALTER TABLE trading_signals ADD COLUMN profile_assigned TEXT NOT NULL DEFAULT 'MID_VOL'")
```

- 중복 ALTER를 추가하면 기존 구조와 충돌 위험이 있어 `db.py`는 추가 수정하지 않았다.

### 버그 2 — KIS 초당 한도 초과 EGW00201
- `OrderExecutor.__init__()`에 `asyncio.Semaphore(1)`을 추가해 `execute_signal()` 동시 실행을 1개로 제한했다.
- 기존 `execute_signal()` 본문은 `_execute_signal_inner()`로 분리했다.
- `get_balance()` 직접 호출을 `_get_cached_balance()`로 교체했다.
- 잔고 캐시는 30초 TTL을 적용했다.
- `order_cash()` 호출 후 성공/실패 모두 `await asyncio.sleep(0.2)`가 실행되도록 `finally`에 최소 대기 시간을 추가했다.
- 잔고 캐시 갱신/재사용 로그를 추가했다.

## 완료 체크리스트
- [x] db.py migration에 profile_assigned 존재 확인
- [x] order_executor.py Semaphore 추가
- [x] order_executor.py 잔고 캐시 30초 TTL 적용
- [x] execute_signal -> _execute_signal_inner 리팩토링
- [x] 주문 후 0.2초 sleep 추가
- [x] py_compile 통과

## 검증 결과

```bash
python3 -m py_compile backend/services/db.py backend/services/engine/order_executor.py && echo OK
```

결과:

```text
OK
```

## 확인 필요
- 서버 재시작 후 Decision Engine 활성화 상태의 실시간 로그는 이 작업에서 실행하지 못했다.
- PM 또는 Sisyphus가 서버를 재시작한 뒤 아래 로그가 더 이상 발생하지 않는지 확인 필요.

```text
FAIL: tick callback error — table trading_signals has no column named profile_assigned
```
