# INBOX_EXECUTOR_bugfix_p0

## 역할
너는 Executor다. 아래 P0 버그 2개를 순서대로 수정하라.
완료 후 `docs/agent-comm/OUTBOX_EXECUTOR_bugfix_p0.md`에 결과를 작성하라.

---

## 버그 1 — trading_signals profile_assigned 컬럼 누락

### 증상
서버 기동 후 Decision Engine 첫 tick 수신 시:
```
FAIL: tick callback error — table trading_signals has no column named profile_assigned
```

### 원인
`backend/services/db.py`의 `_migration_statements()`에 `profile_assigned` 컬럼 추가 migration이 없음.

### 수정 방법
`backend/services/db.py`의 `_migration_statements()` 함수에 아래를 추가한다:

```python
# trading_signals — profile_assigned 컬럼
("trading_signals", "profile_assigned",
 "ALTER TABLE trading_signals ADD COLUMN profile_assigned TEXT NOT NULL DEFAULT 'MID_VOL'"),
```

패턴은 기존 migration과 동일하다:
```python
# 기존 예시
("trading_signals", "realized_pnl",
 "ALTER TABLE trading_signals ADD COLUMN realized_pnl REAL"),
```

---

## 버그 2 — KIS 초당 한도 초과 (EGW00201)

### 증상
신호 11개가 동시 발생 → `execute_signal` 11개 비동기 task가 동시 실행
→ 각자 `get_balance()` 호출 → 초당 15회 한도 초과:
```
KIS API Error: EGW00201 초당 거래건수를 초과하였습니다.
```

### 원인
`backend/services/engine/order_executor.py`의 `execute_signal`에서
매 신호마다 `get_balance()`를 개별 호출.

### 수정 방법

`backend/services/engine/order_executor.py`에 아래 두 가지를 적용한다.

#### 1) 클래스 레벨 Semaphore + 잔고 캐시 추가

`OrderExecutor.__init__`에 추가:
```python
import asyncio
import time

self._semaphore = asyncio.Semaphore(1)   # 동시 실행 1개로 제한
self._balance_cache: dict = {}
self._balance_cache_at: float = 0.0
self._BALANCE_TTL = 30.0  # 30초간 캐시
```

#### 2) `execute_signal` 메서드 수정

```python
async def execute_signal(self, signal: dict[str, Any]) -> dict[str, Any]:
    async with self._semaphore:           # ← 추가: 순차 실행 보장
        return await self._execute_signal_inner(signal)
```

기존 `execute_signal` 내용을 `_execute_signal_inner`로 이름 변경하고,
`get_balance()` 호출 부분을 아래로 교체:

```python
# 잔고 캐시 활용
now = time.monotonic()
if now - self._balance_cache_at > self._BALANCE_TTL or not self._balance_cache:
    self._balance_cache = await get_balance()
    self._balance_cache_at = now
balance = self._balance_cache
```

#### 3) 주문 간 최소 간격

`_execute_signal_inner` 내부에서 `order_cash()` 호출 이후 (성공/실패 모두):
```python
await asyncio.sleep(0.2)   # KIS rate limit 여유
```

---

## 검증

```bash
python3 -m py_compile backend/services/db.py backend/services/engine/order_executor.py
echo "OK"
```

그리고 서버 재시작 후 Decision Engine 활성화 시 아래 로그가 없어야 한다:
```
FAIL: tick callback error — table trading_signals has no column named profile_assigned
```

---

## 완료 체크리스트

- [ ] db.py migration에 profile_assigned 추가
- [ ] order_executor.py Semaphore 추가
- [ ] order_executor.py 잔고 캐시 30초 TTL 적용
- [ ] execute_signal → _execute_signal_inner 리팩토링
- [ ] 주문 후 0.2초 sleep 추가
- [ ] py_compile 통과

결과는 `docs/agent-comm/OUTBOX_EXECUTOR_bugfix_p0.md`에 작성하라.
