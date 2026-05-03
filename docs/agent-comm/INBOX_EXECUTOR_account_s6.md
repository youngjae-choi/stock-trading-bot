# INBOX_EXECUTOR_account_s6 — 계좌 API + S6 Decision Engine + WS 콜백 구조

## 개요

3가지를 한 번에 구현한다:
1. 계좌 잔고 API (`/api/v1/account/balance`)
2. KIS WebSocket에 tick 콜백 dispatch 구조 추가
3. S6 Decision Engine — tick 수신 → RulePack 조건 평가 → 신호 DB 저장

---

## 참조 파일 (읽기 전용)

- `backend/services/kis/domestic/service.py` — `get_balance()`, `check_trading_day()` 패턴
- `backend/services/kis/realtime_ws.py` — 전체 구조 파악 필수
- `backend/services/engine/rulepack_store.py` — `get_active_rulepack()` 함수 확인
- `backend/services/engine/hybrid_screening.py` — `get_today_screening()` 함수 확인
- `backend/services/db.py` — `get_connection()` 패턴
- `backend/config.py` — `settings.KIS_CANO`, `settings.KIS_ACNT_PRDT_CD`
- `backend/main.py` — router 등록 패턴

---

## 1. 계좌 API — `backend/api/routes/account.py` 신규

```python
router = APIRouter(prefix="/api/v1/account", tags=["account"])

@router.get("/balance")
async def get_account_balance():
    """계좌 잔고 조회 — 예수금, 보유종목, 평가손익"""
```

`get_balance()` 호출 후 응답에서 아래 필드 추출해 반환:
- `output1`: 보유 종목 목록 (각 항목: `pdno`=종목코드, `prdt_name`=종목명, `hldg_qty`=보유수량, `pchs_avg_pric`=매입평균가, `prpr`=현재가, `evlu_pfls_rt`=평가손익률)
- `output2[0]`: 계좌 요약 (`dnca_tot_amt`=예수금, `tot_evlu_amt`=총평가금액, `pchs_amt_smtl_amt`=매입금액합계, `evlu_pfls_smtl_amt`=평가손익합계)

응답 형식:
```json
{
  "ok": true,
  "payload": {
    "account_no": "KIS_CANO + KIS_ACNT_PRDT_CD",
    "deposit": 1234567,
    "total_eval": 5678900,
    "positions": [
      {"symbol": "005930", "name": "삼성전자", "qty": 10, "avg_price": 72500, "current_price": 73000, "pnl_pct": 0.69}
    ]
  }
}
```

---

## 2. KIS WebSocket 콜백 구조 — `backend/services/kis/realtime_ws.py` 수정

`RealtimeWSManager`에 tick 콜백 리스트 추가:

```python
from typing import Callable, Awaitable

class RealtimeWSManager:
    def __init__(self):
        # 기존 필드 유지
        self._tick_callbacks: list[Callable[[dict], Awaitable[None]]] = []

    def register_tick_callback(self, cb: Callable[[dict], Awaitable[None]]) -> None:
        """tick 수신 시 호출될 async 콜백을 등록한다."""
        if cb not in self._tick_callbacks:
            self._tick_callbacks.append(cb)

    def unregister_tick_callback(self, cb: Callable[[dict], Awaitable[None]]) -> None:
        self._tick_callbacks = [c for c in self._tick_callbacks if c != cb]
```

`_ingest_message()` 끝에 tick 발생 시 콜백 호출:
```python
# "|" 파이프 구분 메시지 파싱 완료 후 (fields가 존재할 때만)
if entry.get("symbol") and self._tick_callbacks:
    tick = {
        "symbol": entry.get("symbol"),
        "price": entry.get("price"),
        "volume": entry.get("trade_volume"),
        "time": entry.get("trade_time"),
        "fields": entry.get("fields", []),
    }
    for cb in self._tick_callbacks:
        try:
            await cb(tick)
        except Exception as exc:
            logger.error("FAIL: tick callback error — %s", exc)
```

---

## 3. S6 Decision Engine — `backend/services/engine/decision_engine.py` 신규

### DB 스키마 — `trading_signals` 테이블

```sql
CREATE TABLE IF NOT EXISTS trading_signals (
    id          TEXT PRIMARY KEY,
    trade_date  TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    name        TEXT NOT NULL DEFAULT '',
    signal_type TEXT NOT NULL DEFAULT 'BUY',   -- BUY | SKIP
    trigger_price REAL NOT NULL DEFAULT 0.0,
    confidence  REAL NOT NULL DEFAULT 0.0,
    rule_matched TEXT NOT NULL DEFAULT '{}',   -- JSON: 충족된 조건 목록
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending | executed | cancelled
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trading_signals_trade_date ON trading_signals(trade_date);
```

### 핵심 로직

```python
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from ..db import get_connection
from .rulepack_store import get_active_rulepack
from .hybrid_screening import get_today_screening
from ..kis.realtime_ws import realtime_ws_manager

logger = logging.getLogger("DecisionEngine")

class DecisionEngine:
    """S6: 실시간 tick을 받아 RulePack 조건을 평가하고 매수 신호를 생성한다."""

    def __init__(self):
        self._active = False
        self._rulepack = None        # 오늘 RulePack (machine_rules)
        self._candidates = {}        # {symbol: candidate_dict} — S4 결과
        self._signal_sent = set()    # 이미 신호 발행한 종목 (중복 방지)

    async def activate(self) -> dict:
        """장 시작(09:00)에 호출 — RulePack + S4 후보 로드, WS 콜백 등록"""
        today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")

        # RulePack 로드
        rulepack = get_active_rulepack(today)
        if not rulepack:
            logger.warning("WARN: [S6] 오늘 활성 RulePack 없음 — Decision Engine 비활성")
            return {"ok": False, "reason": "no_active_rulepack"}

        # S4 후보 로드
        screening = get_today_screening(today)
        if not screening or not screening.get("candidates"):
            logger.warning("WARN: [S6] 오늘 S4 스크리닝 결과 없음 — Decision Engine 비활성")
            return {"ok": False, "reason": "no_screening_results"}

        self._rulepack = rulepack.get("machine_rules", {})
        self._candidates = {c["symbol"]: c for c in screening["candidates"]}
        self._signal_sent = set()
        self._active = True

        # WS 콜백 등록
        realtime_ws_manager.register_tick_callback(self._on_tick)

        # WS 구독 시작 (S4 후보 종목)
        symbols = list(self._candidates.keys())
        await realtime_ws_manager.start(symbols=symbols)

        logger.info("SUCCESS: [S6] Decision Engine 활성화 candidates=%d symbols=%s", len(symbols), symbols)
        return {"ok": True, "candidates": len(symbols), "symbols": symbols}

    async def deactivate(self) -> None:
        """장 종료 시 호출"""
        self._active = False
        realtime_ws_manager.unregister_tick_callback(self._on_tick)
        await realtime_ws_manager.stop()
        logger.info("INFO: [S6] Decision Engine 비활성화")

    async def _on_tick(self, tick: dict) -> None:
        """tick 수신 콜백 — RulePack 조건 평가"""
        if not self._active:
            return

        symbol = tick.get("symbol", "")
        if symbol not in self._candidates or symbol in self._signal_sent:
            return

        try:
            price = float(tick.get("price") or 0)
        except (ValueError, TypeError):
            return

        candidate = self._candidates[symbol]
        rules = self._rulepack.get("layer3_entry", {})

        # 조건 평가 (현재는 가격 기반 기본 체크 — 향후 VWAP/RSI 확장)
        matched = {}

        # volume_ratio_min 체크
        min_vol_ratio = rules.get("volume_ratio_min", 1.0)
        matched["volume_ratio"] = True  # WS tick에 volume 정보 있으면 실제 계산

        # ai_confidence_min 체크
        ai_conf_min = rules.get("ai_confidence_min", 0.0)
        ai_conf = float(candidate.get("confidence", 0.0))
        matched["ai_confidence"] = ai_conf >= ai_conf_min

        # 모든 조건 충족 시 BUY 신호
        if all(matched.values()):
            await self._emit_signal(symbol, candidate, price, matched)

    async def _emit_signal(self, symbol: str, candidate: dict, price: float, matched: dict) -> None:
        """BUY 신호 DB 저장"""
        self._signal_sent.add(symbol)
        today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
        signal_id = str(uuid.uuid4())

        with get_connection() as conn:
            conn.execute(
                """INSERT INTO trading_signals
                   (id, trade_date, symbol, name, signal_type, trigger_price, confidence, rule_matched, status, created_at)
                   VALUES (?, ?, ?, ?, 'BUY', ?, ?, ?, 'pending', ?)""",
                (
                    signal_id, today, symbol,
                    candidate.get("name", ""),
                    price,
                    float(candidate.get("confidence", 0.0)),
                    __import__("json").dumps(matched),
                    datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
                ),
            )

        logger.info("SIGNAL: [S6] BUY signal symbol=%s price=%.0f confidence=%.2f",
                    symbol, price, candidate.get("confidence", 0.0))


# 싱글턴
decision_engine = DecisionEngine()


def get_today_signals(trade_date: str) -> list[dict]:
    """오늘 생성된 매수 신호 목록 조회"""
    _ensure_signals_table()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM trading_signals WHERE trade_date = ? ORDER BY created_at DESC",
            (trade_date,),
        ).fetchall()
    return [dict(r) for r in rows]


def _ensure_signals_table() -> None:
    with get_connection() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS trading_signals (
            id TEXT PRIMARY KEY,
            trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            signal_type TEXT NOT NULL DEFAULT 'BUY',
            trigger_price REAL NOT NULL DEFAULT 0.0,
            confidence REAL NOT NULL DEFAULT 0.0,
            rule_matched TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        )""")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trading_signals_trade_date ON trading_signals(trade_date)"
        )
```

---

## 4. Decision API — `backend/api/routes/decision.py` 신규

```python
router = APIRouter(prefix="/api/v1/decision", tags=["decision"])

@router.get("/signals/today")
async def get_today_signals_api():
    """오늘 생성된 매수 신호 조회"""

@router.get("/status")
async def get_decision_status():
    """Decision Engine 활성화 상태 + WS 연결 상태"""
    from ...services.kis.realtime_ws import realtime_ws_manager
    from ...services.engine.decision_engine import decision_engine
    return {
        "ok": True,
        "payload": {
            "active": decision_engine._active,
            "ws_connected": realtime_ws_manager.is_connected,
            "candidates": len(decision_engine._candidates),
            "signals_sent": len(decision_engine._signal_sent),
        }
    }

@router.post("/activate")
async def activate_decision_engine():
    """수동 활성화 (테스트용)"""
    from ...services.engine.decision_engine import decision_engine
    result = await decision_engine.activate()
    return {"ok": True, "payload": result}

@router.post("/deactivate")
async def deactivate_decision_engine():
    from ...services.engine.decision_engine import decision_engine
    await decision_engine.deactivate()
    return {"ok": True}
```

---

## 5. `backend/services/scheduler.py` 수정 — S6 job 추가

```python
async def job_decision_engine_start() -> None:
    """Job 6 (09:00 KST): S6 Decision Engine 활성화 + WS 연결"""
    logger.info("START: [Job6] Decision Engine 활성화 (09:00 KST)")
    try:
        from .engine.decision_engine import decision_engine
        result = await decision_engine.activate()
        logger.info("SUCCESS: [Job6] Decision Engine active=%s candidates=%s",
                    result.get("ok"), result.get("candidates"))
    except Exception as exc:
        logger.error("FAIL: [Job6] Decision Engine 활성화 실패 — reason=%s", exc)


async def job_decision_engine_stop() -> None:
    """Job 9 (15:20 KST): S6 비활성화 + WS 종료"""
    logger.info("START: [Job9] Decision Engine 비활성화 (15:20 KST)")
    try:
        from .engine.decision_engine import decision_engine
        await decision_engine.deactivate()
        logger.info("SUCCESS: [Job9] Decision Engine 비활성화 완료")
    except Exception as exc:
        logger.error("FAIL: [Job9] 비활성화 실패 — reason=%s", exc)
```

스케줄러 job 등록 (기존 schedule_*_time DB 패턴 동일하게):
- `schedule_s6_time` 기본값 `"09:00"` — `job_decision_engine_start`
- `schedule_s9_time` 기본값 `"15:20"` — `job_decision_engine_stop`

---

## 6. `backend/main.py` 수정

```python
from .api.routes.account import router as account_router
from .api.routes.decision import router as decision_router

app.include_router(account_router)
app.include_router(decision_router)
```

---

## 완료 기준

```bash
python -m py_compile backend/api/routes/account.py && echo "account OK"
python -m py_compile backend/services/kis/realtime_ws.py && echo "ws OK"
python -m py_compile backend/services/engine/decision_engine.py && echo "decision OK"
python -m py_compile backend/api/routes/decision.py && echo "decision_route OK"
python -m py_compile backend/services/scheduler.py && echo "scheduler OK"
python -m py_compile backend/main.py && echo "main OK"
python -c "from backend.services.engine.decision_engine import decision_engine, get_today_signals; print('import OK')"
```

OUTBOX(`docs/agent-comm/OUTBOX_EXECUTOR_account_s6.md`)에 결과 작성.
