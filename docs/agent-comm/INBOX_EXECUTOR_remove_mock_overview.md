# INBOX_EXECUTOR_remove_mock_overview — /api/v1/bot/overview mock 제거

## 작업 목적

`/api/v1/bot/overview`가 현재 하드코딩 mock 데이터를 반환한다.
`console_state.py`의 `get_console_overview()`를 실 DB 조회 기반으로 교체한다.
`bot.py`의 해당 엔드포인트도 `mock=False`로 변경한다.

---

## 변경 파일

1. `backend/services/console_state.py` — `get_console_overview()` 실 데이터로 교체
2. `backend/api/routes/bot.py` — `/api/v1/bot/overview` mock 플래그 제거

---

## Task 1 — `console_state.py`의 `get_console_overview()` 교체

현재 `get_console_overview()` 함수를 찾아서 아래 구현으로 완전히 교체한다.
`_CONSOLE_STATE["overview"]` 딕셔너리 자체는 더 이상 반환하지 않는다.
emergency_halt / mock_mode 상태는 `_CONSOLE_STATE`에서 계속 읽는다.

```python
def get_console_overview() -> dict[str, Any]:
    """Return real-time console overview built from live DB and runtime state."""
    logger.info("START: console_state.get_console_overview")
    from zoneinfo import ZoneInfo

    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    today = now_kst.strftime("%Y-%m-%d")

    # ── 1. KIS 토큰 상태 ──────────────────────────────────────────────
    try:
        from .kis.common.client import kis_client
        kis_ok = kis_client._token_is_valid() if kis_client is not None else False
    except Exception:
        kis_ok = False

    # ── 2. WebSocket 상태 ─────────────────────────────────────────────
    try:
        from .kis.realtime_ws import realtime_ws_manager
        ws_connected = realtime_ws_manager.is_connected
        ws_symbols = getattr(realtime_ws_manager, "_symbols", [])
    except Exception:
        ws_connected = False
        ws_symbols = []

    # ── 3. RulePack 상태 ──────────────────────────────────────────────
    try:
        from .engine.rulepack_store import get_active_rulepack_for_date
        rulepack = get_active_rulepack_for_date(today)
        rulepack_ready = rulepack is not None
        rulepack_id = rulepack.get("rulepack_id", "") if rulepack else ""
    except Exception:
        rulepack_ready = False
        rulepack_id = ""

    # ── 4. Decision Engine 상태 ───────────────────────────────────────
    try:
        from .engine.decision_engine import decision_engine
        engine_active = decision_engine._active
    except Exception:
        engine_active = False

    # ── 5. 포지션 수 ──────────────────────────────────────────────────
    try:
        from .engine.position_manager import position_manager
        positions = position_manager.get_positions()
        open_positions = len(positions)
    except Exception:
        open_positions = 0

    # ── 6. 오늘 신호/주문 요약 ────────────────────────────────────────
    signals_pending = 0
    signals_executed = 0
    try:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM trading_signals WHERE trade_date=? GROUP BY status",
                (today,),
            ).fetchall()
        for row in rows:
            if row["status"] == "pending":
                signals_pending = row["cnt"]
            elif row["status"] == "executed":
                signals_executed = row["cnt"]
    except Exception:
        pass

    # ── 7. 오늘 당일 손익 계산 ───────────────────────────────────────
    pnl_pct = 0.0
    try:
        with get_connection() as conn:
            row = conn.execute(
                """SELECT realized_pnl_pct FROM daily_trade_summary
                   WHERE trade_date=? ORDER BY created_at DESC LIMIT 1""",
                (today,),
            ).fetchone()
        if row:
            pnl_pct = float(row["realized_pnl_pct"] or 0.0)
    except Exception:
        pass

    # ── 8. Funnel 집계 ────────────────────────────────────────────────
    market_total = 0
    layer1_count = 0
    layer2_count = 0
    try:
        with get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM symbols WHERE is_active=1").fetchone()
            market_total = row["cnt"] if row else 0
    except Exception:
        market_total = 0

    try:
        with get_connection() as conn:
            row = conn.execute(
                """SELECT result_json FROM universe_filter_results
                   WHERE trade_date=? ORDER BY created_at DESC LIMIT 1""",
                (today,),
            ).fetchone()
        if row:
            import json as _json
            data = _json.loads(row["result_json"] or "{}")
            layer1_count = len(data.get("items", []))
    except Exception:
        pass

    try:
        with get_connection() as conn:
            row = conn.execute(
                """SELECT output_count FROM hybrid_screening_results
                   WHERE trade_date=? ORDER BY created_at DESC LIMIT 1""",
                (today,),
            ).fetchone()
        if row:
            layer2_count = row["output_count"] or 0
    except Exception:
        pass

    # ── 9. 타임라인 — 각 Step 완료 여부 확인 ────────────────────────
    def _step_done(table: str, date_col: str = "trade_date") -> bool:
        try:
            with get_connection() as conn:
                row = conn.execute(
                    f"SELECT 1 FROM {table} WHERE {date_col}=? LIMIT 1", (today,)
                ).fetchone()
            return row is not None
        except Exception:
            return False

    s2_done = _step_done("market_tone_results")
    s3_done = _step_done("universe_filter_results")
    s4_done = _step_done("hybrid_screening_results")
    s5_done = rulepack_ready

    # 장 단계 계산
    now_time = now_kst.strftime("%H:%M")

    def _tl_status(step_time: str, done: bool) -> str:
        if done:
            return "완료"
        if now_time >= step_time:
            return "실행중"
        return "대기"

    timeline = [
        {"time": "07:45", "name": "KIS 토큰 갱신",    "status": "완료" if kis_ok else ("완료" if now_time > "07:50" else "대기")},
        {"time": "08:00", "name": "AI 시장 톤 분석",  "status": _tl_status("08:00", s2_done)},
        {"time": "08:15", "name": "유니버스 필터",     "status": _tl_status("08:15", s3_done)},
        {"time": "08:30", "name": "AI 스크리닝",       "status": _tl_status("08:30", s4_done)},
        {"time": "08:45", "name": "RulePack 생성",     "status": _tl_status("08:45", s5_done)},
        {"time": "09:00", "name": "실시간 매매 시작",  "status": "완료" if engine_active else ("실행중" if now_time >= "09:00" else "대기")},
        {"time": "11:30", "name": "중간 리포트",        "status": _tl_status("11:30", False)},
        {"time": "15:20", "name": "당일매매 청산",      "status": _tl_status("15:20", False)},
        {"time": "16:00", "name": "AI 복기 리포트",    "status": _tl_status("16:00", False)},
        {"time": "16:30", "name": "일일 리포트",        "status": _tl_status("16:30", False)},
        {"time": "18:00", "name": "데이터 백업",        "status": _tl_status("18:00", False)},
    ]

    # 다음 실행 예정 Job
    schedule_order = [
        ("07:45", "KIS 토큰 갱신"), ("08:00", "AI 시장 톤 분석"),
        ("08:15", "유니버스 필터"), ("08:30", "AI 스크리닝"),
        ("08:45", "RulePack 생성"), ("09:00", "실시간 매매 시작"),
        ("11:30", "중간 리포트"),   ("15:20", "당일매매 청산"),
        ("16:00", "AI 복기 리포트"), ("16:30", "일일 리포트"),
        ("18:00", "데이터 백업"),   ("22:00", "미국장 야간 관찰"),
    ]
    next_job = {"time": "-", "name": "-"}
    for t, name in schedule_order:
        if now_time < t:
            next_job = {"time": t, "name": name}
            break

    # ── 10. 운영 로그 (최근 DB 이벤트) ──────────────────────────────
    logs = []
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT time(created_at, '+9 hours') as kst_time, 'AI 시장 톤 분석 완료 tone='||tone as text
                   FROM market_tone_results WHERE trade_date=? ORDER BY created_at DESC LIMIT 1""",
                (today,),
            ).fetchall()
        for row in rows:
            logs.append({"time": (row["kst_time"] or "")[:5], "text": row["text"]})
    except Exception:
        pass
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT time(created_at, '+9 hours') as kst_time, raw_input_count, output_count
                   FROM hybrid_screening_results WHERE trade_date=? ORDER BY created_at DESC LIMIT 1""",
                (today,),
            ).fetchall()
        for row in rows:
            logs.append({"time": (row["kst_time"] or "")[:5],
                         "text": f"AI 스크리닝 완료 — 입력 {row['raw_input_count']}종목 → 후보 {row['output_count']}종목"})
    except Exception:
        pass
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT time(created_at, '+9 hours') as kst_time, symbol, name, status
                   FROM trading_signals WHERE trade_date=? ORDER BY created_at DESC LIMIT 5""",
                (today,),
            ).fetchall()
        for row in rows:
            logs.append({"time": (row["kst_time"] or "")[:5],
                         "text": f"매수 신호 — {row['name']}({row['symbol']}) status={row['status']}"})
    except Exception:
        pass

    if not logs:
        logs.append({"time": now_time, "text": "오늘 운영 이벤트 없음"})

    logs = sorted(logs, key=lambda x: x["time"], reverse=True)[:10]

    # ── 11. 리스크 한도 조회 ─────────────────────────────────────────
    max_positions = 5
    daily_loss_limit_pct = -2.0
    try:
        if rulepack:
            mr = rulepack.get("machine_rules") or {}
            if isinstance(mr, str):
                import json as _json2
                mr = _json2.loads(mr)
            rl = mr.get("risk_limits", {})
            max_positions = int(rl.get("max_positions", 5))
            daily_loss_limit_pct = float(rl.get("daily_loss_limit_rate", -0.02)) * 100
    except Exception:
        pass

    # ── 최종 조합 ─────────────────────────────────────────────────────
    emergency_halt = _CONSOLE_STATE["emergency_halt"]
    payload = {
        "trade_date": today,
        "pnl_percent": pnl_pct,
        "daily_loss_limit_percent": daily_loss_limit_pct,
        "open_positions": open_positions,
        "max_positions": max_positions,
        "rulepack_ready": rulepack_ready,
        "rulepack_id": rulepack_id,
        "engine_active": engine_active,
        "signals_pending": signals_pending,
        "signals_executed": signals_executed,
        "timeline": timeline,
        "next_job": next_job,
        "health": {
            "kis_rest": {
                "status": "ok" if kis_ok else "warn",
                "detail": "토큰 유효" if kis_ok else "토큰 없음 또는 만료",
            },
            "websocket": {
                "status": "ok" if ws_connected else "warn",
                "detail": f"연결됨 — {len(ws_symbols)}개 구독중" if ws_connected else "미연결 (S4 완료 후 자동 시작)",
            },
            "rulepack": {
                "status": "ok" if rulepack_ready else "warn",
                "detail": f"활성 RulePack: {rulepack_id}" if rulepack_ready else "오늘 활성 RulePack 없음",
            },
            "risk_guard": {
                "status": "halted" if emergency_halt else "ok",
                "detail": "긴급정지 적용됨" if emergency_halt else "신규 진입 허용",
            },
        },
        "funnel": {
            "market_total": market_total,
            "layer1": layer1_count,
            "layer2": layer2_count,
            "entry_waiting": signals_pending,
            "holding": open_positions,
        },
        "logs": logs,
        "emergency_halt": emergency_halt,
        "mock_mode": False,
        "updated_at": _utc_now_iso(),
        "note": "실 DB 및 런타임 상태 기반 응답",
    }
    logger.info(
        "SUCCESS: console_state.get_console_overview trade_date=%s kis=%s ws=%s rulepack=%s",
        today, kis_ok, ws_connected, rulepack_ready,
    )
    return payload
```

파일 상단에 아래 import가 없으면 추가한다:
```python
from .db import get_connection
```

---

## Task 2 — `bot.py` overview 엔드포인트 mock 플래그 제거

`bot.py`에서 `/api/v1/bot/overview` 핸들러를 찾아 `mock=True`를 `mock=False`로 바꾸고
`source="mock"` → `source="backend"`, `message` 텍스트도 실 데이터임을 반영해 수정한다.

```python
return _build_logged_success_response(
    endpoint=endpoint,
    method="GET",
    payload=payload,
    source="backend",
    message="Console overview served from live DB and runtime state.",
    feature_name="운영 개요 조회",
    purpose="운영 화면에서 엔진 상태와 리스크 상태를 한 번에 확인",
    result_summary="성공 실 DB 기반 운영 개요 반환",
    mock=False,
)
```

---

## 주의사항

1. `universe_filter_results` 테이블 구조를 먼저 확인한다.
   - `result_json` 컬럼이 없을 수 있다 — `SELECT * FROM universe_filter_results LIMIT 1` 로 확인
   - 없으면 layer1_count 쿼리를 해당 실제 컬럼명으로 수정한다

2. `daily_trade_summary` 테이블이 없을 수 있다 (S10 미실행 시) — try/except로 처리 (이미 코드에 포함됨)

3. `get_connection()` import가 `console_state.py` 상단에 없으면 추가한다.
   - 현재 `console_state.py`에 `from .db import get_connection`이 없을 가능성이 있으니 파일 상단을 확인한다.

4. `kis_client` singleton 변수명은 `backend/services/kis/common/client.py`를 읽어서 확인한다.

---

## 완료 기준

```bash
python -m py_compile backend/services/console_state.py && echo "console_state OK"
python -m py_compile backend/api/routes/bot.py && echo "bot OK"

python3 -c "
from backend.services.console_state import get_console_overview
result = get_console_overview()
print('trade_date:', result.get('trade_date'))
print('mock_mode:', result.get('mock_mode'))
print('health keys:', list(result.get('health', {}).keys()))
print('funnel:', result.get('funnel'))
print('OK' if result.get('mock_mode') == False else 'STILL MOCK')
"
```

기대 출력:
- `mock_mode: False`
- `health keys: ['kis_rest', 'websocket', 'rulepack', 'risk_guard']`
- `funnel: {'market_total': ..., 'layer1': ..., 'layer2': ..., ...}`

OUTBOX 결과는 `docs/agent-comm/OUTBOX_EXECUTOR_remove_mock_overview.md` 에 작성하라.
