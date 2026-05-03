# INBOX_EXECUTOR_s4_ws_start — S4 완료 후 KIS WebSocket 자동 구독

## 작업 목적

S4 Hybrid Screening 완료 시 선정된 후보 종목을 KIS WebSocket으로 자동 구독 시작한다.

---

## 변경 파일

1. `backend/services/engine/hybrid_screening.py` — S4 완료 후 WebSocket 시작
2. `backend/services/console_state.py` — `get_data_health()`의 `kis_ws` 실 상태 반영

---

## Task 1 — `hybrid_screening.py` 수정

### 1-A. `run_hybrid_screening()` 함수 수정

`run_hybrid_screening()` 함수 내 DB 저장 직후, `return result` 직전에 아래 코드를 추가한다.

```python
    # S4 완료 → KIS WebSocket 구독 시작
    try:
        from ..kis.realtime_ws import realtime_ws_manager
        tickers = [c["ticker"] for c in candidates if c.get("ticker")]
        if tickers:
            await realtime_ws_manager.start(symbols=tickers)
            logger.info(
                "SUCCESS: HybridScreening KIS WebSocket 구독 시작 symbols=%s count=%d",
                tickers, len(tickers),
            )
        else:
            logger.warning("WARN: HybridScreening 후보 종목 없음 — KIS WebSocket 구독 생략")
    except Exception as ws_exc:
        logger.warning("WARN: HybridScreening KIS WebSocket 시작 실패 — %s", ws_exc)
```

위 코드는 반드시 `result = { ... }` 딕셔너리 구성 이후, `logger.info("SUCCESS: HybridScreeningService ...")` 이후에 삽입한다.

### 1-B. S3 결과 없을 때 (early return) WebSocket 중지

S3 결과 없어 early return하는 블록 직전에 아래 추가:

```python
        # S3 결과 없으면 기존 WebSocket 구독도 중지
        try:
            from ..kis.realtime_ws import realtime_ws_manager
            await realtime_ws_manager.stop()
            logger.info("INFO: HybridScreening S3 결과 없음 — KIS WebSocket 구독 중지")
        except Exception:
            pass
```

---

## Task 2 — `console_state.py` 수정

`get_data_health()` 함수에서 `kis_ws` metric을 실제 `realtime_ws_manager.is_connected` 값으로 반영한다.

현재 `get_data_health()` 내 kis_ws 부분:
```python
"kis_ws": {"status": "info", "detail": "KIS WebSocket 미구현 (향후 S-step 예정)"},
```

아래로 교체:
```python
# KIS WebSocket 실제 연결 상태 확인
try:
    from .kis.realtime_ws import realtime_ws_manager
    ws_connected = realtime_ws_manager.is_connected
    ws_symbols = getattr(realtime_ws_manager, '_symbols', [])
    if ws_connected:
        ws_status = "ok"
        ws_detail = f"연결됨 — {len(ws_symbols)}개 종목 구독중"
    else:
        ws_status = "warn"
        ws_detail = "미연결 (S4 스크리닝 완료 후 자동 시작)"
except Exception:
    ws_connected = False
    ws_status = "warn"
    ws_detail = "상태 확인 불가"
```

그리고 `kis_ws` dict를 다음으로 교체:
```python
"kis_ws": {"status": ws_status, "detail": ws_detail},
```

---

## 완료 기준

```bash
python -m py_compile backend/services/engine/hybrid_screening.py && echo "hybrid_screening OK"
python -m py_compile backend/services/console_state.py && echo "console_state OK"

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

OUTBOX 결과는 `docs/agent-comm/OUTBOX_EXECUTOR_s4_ws_start.md` 에 작성하라.
