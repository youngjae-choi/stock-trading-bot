# OUTBOX_EXECUTOR_s4_ws_start — S4 완료 후 KIS WebSocket 자동 구독

## 작업 상태

완료.

## 구현 요약

- `backend/services/engine/hybrid_screening.py`
  - S3 유니버스 결과가 없어서 S4가 early return하는 경우 기존 KIS WebSocket 구독을 중지하도록 추가.
  - S4 결과 DB 저장 및 성공 로그 이후, 후보 `ticker` 목록을 추출해 `realtime_ws_manager.start(symbols=tickers)`를 호출하도록 추가.
  - WebSocket 시작/중지 실패 시 스크리닝 결과 반환은 막지 않고 WARN 로그로 원인을 남기도록 처리.

- `backend/services/console_state.py`
  - `get_data_health()`의 `kis_ws` metric을 `realtime_ws_manager.is_connected`와 `_symbols` 기준으로 동적 표시하도록 변경.
  - 미연결 상태는 `warn`, 연결 상태는 `ok`로 표시.
  - KIS WebSocket 안내 note를 S4 완료 후 자동 구독 기준으로 갱신.

## 검증 결과

```bash
python -m py_compile backend/services/engine/hybrid_screening.py && echo "hybrid_screening OK"
```

결과: `hybrid_screening OK`

```bash
python -m py_compile backend/services/console_state.py && echo "console_state OK"
```

결과: `console_state OK`

```bash
python3 -c "
content = open('backend/services/engine/hybrid_screening.py').read()
checks = [
    ('WebSocket start after S4', 'realtime_ws_manager.start'),
    ('WebSocket stop on S3 miss', 'realtime_ws_manager.stop'),
    ('ticker extraction', 'c[\"ticker\"]'),
]
for name, pattern in checks:
    print(f'{name}: {\"OK\" if pattern in content else \"MISSING\"}')
"
```

결과:

```text
WebSocket start after S4: OK
WebSocket stop on S3 miss: OK
ticker extraction: OK
```

```bash
python3 -c "
content = open('backend/services/console_state.py').read()
checks = [
    ('ws_connected check', 'is_connected'),
    ('ws_detail dynamic', 'ws_detail'),
]
for name, pattern in checks:
    print(f'{name}: {\"OK\" if pattern in content else \"MISSING\"}')
"
```

결과:

```text
ws_connected check: OK
ws_detail dynamic: OK
```

## 잔여 리스크 / 확인 필요

- 실제 KIS WebSocket 연결은 KIS 승인키/네트워크/장중 환경이 필요하므로 로컬 컴파일 및 정적 검증까지만 수행했다.
- 작업 시작 전 이미 작업트리에 다수의 변경 파일이 있었고, `backend/services/console_state.py`에도 기존 변경이 포함되어 있었다. 이번 작업은 `get_data_health()`의 `kis_ws` 상태 반영 부분에 한정했다.

