# OUTBOX_EXECUTOR_position_restore

## 작업 결과

S9 당일 청산이 서버 재시작 후에도 청산 대상을 찾을 수 있도록 포지션 복원과 EOD fallback을 보강했다.

## 변경 파일

- `backend/services/engine/decision_engine.py`
  - `_restore_positions_from_db(trade_date, candidate_symbols)`가 `candidate_symbols=[]`인 경우에도 오늘 `trading_orders`의 buy/submitted/filled 주문과 오늘 최신 `position_stop_states`를 기준으로 복원하도록 수정.
  - 후보 종목이 있으면 기존처럼 후보 종목으로 제한하고, 없으면 오늘 매수 주문 전체를 대상으로 복원.
  - 복원 완료 로그에 `trade_date`를 포함.

- `backend/services/engine/eod_liquidation.py`
  - `_today_kst()` 추가.
  - `_get_open_positions_from_db(trade_date)` 추가.
  - `run_eod_liquidation()`이 인메모리 포지션이 0건이면 DB에서 오늘 매수 후 아직 매도 주문이 없는 종목을 조회해 시장가 청산하도록 수정.
  - 청산 대상 0건, DB 조회 실패, invalid position 케이스 로그 추가.

- `backend/main.py`
  - `scheduler_instance.start()` 이후 startup 포지션 자동 복원 로직 추가.
  - S6 activate 없이도 서버 시작 시 오늘 포지션을 인메모리에 복원하도록 처리.

- `backend/services/engine/position_manager.py`
  - 현재 `add_position()` / `get_positions()` / `remove_position()` 인터페이스로 요구사항 처리가 가능해 코드 변경 없음.

## 검증 결과

### py_compile

명령:

```bash
python3 -m py_compile backend/services/engine/decision_engine.py backend/services/engine/eod_liquidation.py backend/main.py && echo "py_compile OK"
```

결과:

```text
py_compile OK
```

### DB open position 사전 확인

명령:

```bash
python3 - <<'PY'
import os
os.environ.setdefault("APP_ENV", "development")
from backend.services.db import initialize_database
from backend.services.engine.eod_liquidation import _get_open_positions_from_db
initialize_database()
today = "2026-05-05"
positions = _get_open_positions_from_db(today)
print(f"DB open positions: {len(positions)}")
for position in positions:
    print(position)
PY
```

결과:

```text
DB open positions: 0
```

### 요청 검증 스크립트

명령:

```bash
python3 - <<'PY'
import os
os.environ.setdefault("APP_ENV", "development")
import asyncio
from backend.services.engine.eod_liquidation import run_eod_liquidation, _get_open_positions_from_db
from backend.services.db import initialize_database
initialize_database()
today = "2026-05-05"
positions = _get_open_positions_from_db(today)
print(f"DB open positions: {len(positions)}")
result = asyncio.run(run_eod_liquidation())
print(f"EOD result: liquidated={result['liquidated']}")
print("PASS")
PY
```

결과:

```text
DB open positions: 0
EOD result: liquidated=0
PASS
```

### 복원 smoke test

명령:

```bash
python3 - <<'PY'
import os
os.environ.setdefault("APP_ENV", "development")
from backend.services.db import initialize_database
from backend.services.engine.decision_engine import _restore_positions_from_db
initialize_database()
_restore_positions_from_db("2026-05-05", [])
print("restore smoke PASS")
PY
```

결과:

```text
restore smoke PASS
```

## 완료 체크리스트

- [x] `_restore_positions_from_db()` — candidate_symbols 없어도 복원
- [x] `run_eod_liquidation()` — 인메모리 없으면 DB 직접 조회 청산
- [x] `main.py` startup 포지션 자동 복원
- [x] py_compile OK
- [x] 검증 스크립트 통과

## 잔여 리스크 / 확인 필요

- 현재 개발 DB 기준 `2026-05-05` 미청산 포지션이 0건이라 실제 `execute_sell()` 성공 경로는 호출되지 않았다.
- `position_manager.add_position()` 기반 복원은 기존 구현과 동일하게 entry/qty/rule 기준으로 포지션을 재등록한다. `position_stop_states`의 trailing 세부 상태를 그대로 인메모리에 재현하는 전용 restore API는 이번 범위에 포함하지 않았다.
