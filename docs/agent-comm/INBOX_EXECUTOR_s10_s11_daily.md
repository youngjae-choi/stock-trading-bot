# INBOX_EXECUTOR_s10_s11_daily — S10 데이터 백업 + S11 미국장 관찰 + 일별 거래 기록

## 개요

3가지를 구현한다:
1. **S10** (18:00 KST): 당일 거래 결과를 `daily_trade_summary` 테이블에 저장 + SQLite DB 파일 백업
2. **S11** (22:00 KST): 미국 장중 지표 수집 → `overnight_market_snapshots` 테이블 저장 (다음날 S2 활용)
3. **일별 거래 기록 API**: `GET /api/v1/trades/history` — 날짜별 거래 요약 조회

---

## 참조 파일 (읽기 전용)

- `backend/services/engine/market_data_fetcher.py` — `fetch_overnight_market_summary()`, `_SYMBOLS` 구조
- `backend/services/engine/order_executor.py` — `get_today_orders()`, `trading_orders` 테이블 구조
- `backend/services/engine/position_manager.py` — `get_positions()` 구조
- `backend/services/db.py` — `get_connection()`, DB 파일 경로 패턴
- `backend/config.py` — `settings.APP_DB_PATH`
- `backend/services/scheduler.py` — `job_data_backup()`, `job_us_market_watch()` placeholder 교체
- `backend/main.py` — router 등록 패턴

---

## 1. DB 스키마

### `daily_trade_summary` 테이블

```sql
CREATE TABLE IF NOT EXISTS daily_trade_summary (
    id              TEXT PRIMARY KEY,
    trade_date      TEXT NOT NULL UNIQUE,     -- YYYY-MM-DD
    total_orders    INTEGER NOT NULL DEFAULT 0,
    buy_orders      INTEGER NOT NULL DEFAULT 0,
    sell_orders     INTEGER NOT NULL DEFAULT 0,
    failed_orders   INTEGER NOT NULL DEFAULT 0,
    realized_pnl    REAL NOT NULL DEFAULT 0.0,  -- 실현 손익 합계 (원)
    realized_pnl_pct REAL NOT NULL DEFAULT 0.0, -- 평균 손익률 (%)
    symbols_traded  TEXT NOT NULL DEFAULT '[]', -- JSON: 거래 종목 코드 목록
    market_tone     TEXT NOT NULL DEFAULT '',   -- 당일 S2 톤
    rulepack_id     TEXT NOT NULL DEFAULT '',   -- 당일 활성 RulePack ID
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
```

### `overnight_market_snapshots` 테이블

```sql
CREATE TABLE IF NOT EXISTS overnight_market_snapshots (
    id              TEXT PRIMARY KEY,
    snapshot_date   TEXT NOT NULL,            -- YYYY-MM-DD (수집 날짜, 다음날 S2가 조회)
    snapshot_time   TEXT NOT NULL,            -- HH:MM KST
    sp500_chg_pct   REAL,
    nasdaq_chg_pct  REAL,
    dow_chg_pct     REAL,
    ftse100_chg_pct REAL,
    dax_chg_pct     REAL,
    oil_wti_chg_pct REAL,
    usdkrw_rate     REAL,
    us_10y_yield    REAL,
    raw_data        TEXT NOT NULL DEFAULT '{}', -- JSON: 전체 raw 데이터
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_overnight_market_snapshot_date ON overnight_market_snapshots(snapshot_date);
```

---

## 2. S10 — `backend/services/engine/daily_summary.py` 신규

```python
"""S10: 당일 거래 결과 요약 저장 + DB 파일 백업."""

import shutil, uuid, json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..db import get_connection
from ..settings_store import get_setting
from .order_executor import get_today_orders
from .rulepack_store import get_active_rulepack_for_date
from ...config import settings

logger = logging.getLogger("DailySummary")


def _ensure_tables() -> None:
    with get_connection() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS daily_trade_summary (
            id TEXT PRIMARY KEY,
            trade_date TEXT NOT NULL UNIQUE,
            total_orders INTEGER NOT NULL DEFAULT 0,
            buy_orders INTEGER NOT NULL DEFAULT 0,
            sell_orders INTEGER NOT NULL DEFAULT 0,
            failed_orders INTEGER NOT NULL DEFAULT 0,
            realized_pnl REAL NOT NULL DEFAULT 0.0,
            realized_pnl_pct REAL NOT NULL DEFAULT 0.0,
            symbols_traded TEXT NOT NULL DEFAULT '[]',
            market_tone TEXT NOT NULL DEFAULT '',
            rulepack_id TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")


async def run_daily_summary(trade_date: str | None = None) -> dict:
    """당일 거래 결과를 집계해 daily_trade_summary에 저장하고 DB를 백업한다."""
    _ensure_tables()
    if trade_date is None:
        trade_date = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    
    now_iso = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()

    # 당일 주문 집계
    orders = get_today_orders(trade_date)
    buy_orders = [o for o in orders if o.get("side") == "buy"]
    sell_orders = [o for o in orders if o.get("side") == "sell"]
    failed_orders = [o for o in orders if o.get("status") == "failed"]

    # 실현 손익 계산 (매도 주문 기준: sell_price * qty - avg_buy_price * qty)
    # 간단 구현: 매수 평균가 vs 매도가 기준
    realized_pnl = 0.0
    realized_pnl_pcts = []
    for sell in sell_orders:
        sym = sell.get("symbol")
        sell_price = float(sell.get("price") or 0)
        qty = int(sell.get("qty") or 0)
        # 같은 날 같은 종목 매수 평균가 조회
        buys = [o for o in buy_orders if o.get("symbol") == sym]
        if buys and sell_price > 0 and qty > 0:
            avg_buy = sum(float(b.get("price", 0)) for b in buys) / len(buys)
            pnl = (sell_price - avg_buy) * qty
            pnl_pct = (sell_price - avg_buy) / avg_buy * 100 if avg_buy > 0 else 0
            realized_pnl += pnl
            realized_pnl_pcts.append(pnl_pct)

    avg_pnl_pct = sum(realized_pnl_pcts) / len(realized_pnl_pcts) if realized_pnl_pcts else 0.0
    symbols_traded = list({o.get("symbol") for o in orders if o.get("symbol")})

    # 시장 톤, RulePack ID 조회
    market_tone = ""
    rulepack_id = ""
    try:
        with get_connection() as conn:
            tone_row = conn.execute(
                "SELECT tone FROM market_tone_results WHERE trade_date = ? LIMIT 1",
                (trade_date,)
            ).fetchone()
            if tone_row:
                market_tone = tone_row["tone"]
    except Exception:
        pass

    rulepack = get_active_rulepack_for_date(trade_date)
    if rulepack:
        rulepack_id = rulepack.get("rulepack_id", "")

    # DB 저장 (UPSERT)
    summary_id = str(uuid.uuid4())
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM daily_trade_summary WHERE trade_date = ?", (trade_date,)
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE daily_trade_summary SET
                   total_orders=?, buy_orders=?, sell_orders=?, failed_orders=?,
                   realized_pnl=?, realized_pnl_pct=?, symbols_traded=?,
                   market_tone=?, rulepack_id=?, updated_at=?
                   WHERE trade_date=?""",
                (len(orders), len(buy_orders), len(sell_orders), len(failed_orders),
                 realized_pnl, avg_pnl_pct, json.dumps(symbols_traded),
                 market_tone, rulepack_id, now_iso, trade_date)
            )
        else:
            conn.execute(
                """INSERT INTO daily_trade_summary
                   (id, trade_date, total_orders, buy_orders, sell_orders, failed_orders,
                    realized_pnl, realized_pnl_pct, symbols_traded, market_tone, rulepack_id,
                    created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (summary_id, trade_date, len(orders), len(buy_orders), len(sell_orders),
                 len(failed_orders), realized_pnl, avg_pnl_pct, json.dumps(symbols_traded),
                 market_tone, rulepack_id, now_iso, now_iso)
            )

    logger.info("SUCCESS: DailySummary saved trade_date=%s orders=%d pnl=%.0f",
                trade_date, len(orders), realized_pnl)

    # DB 파일 백업
    backup_result = _backup_db(trade_date)

    return {
        "trade_date": trade_date,
        "total_orders": len(orders),
        "buy_orders": len(buy_orders),
        "sell_orders": len(sell_orders),
        "realized_pnl": realized_pnl,
        "realized_pnl_pct": avg_pnl_pct,
        "symbols_traded": symbols_traded,
        "backup": backup_result,
    }


def _backup_db(trade_date: str) -> dict:
    """SQLite DB 파일을 data/backups/ 디렉토리에 날짜별로 복사한다."""
    try:
        db_path = Path(settings.APP_DB_PATH)
        backup_dir = db_path.parent / "backups"
        backup_dir.mkdir(exist_ok=True)
        backup_path = backup_dir / f"stock_trading_bot_{trade_date}.sqlite3"
        shutil.copy2(db_path, backup_path)
        logger.info("SUCCESS: DB backup saved path=%s", backup_path)
        return {"ok": True, "path": str(backup_path)}
    except Exception as exc:
        logger.error("FAIL: DB backup failed reason=%s", exc)
        return {"ok": False, "error": str(exc)}


def get_trade_history(limit: int = 30) -> list[dict]:
    """daily_trade_summary 최근 N일 조회"""
    _ensure_tables()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM daily_trade_summary ORDER BY trade_date DESC LIMIT ?",
            (limit,)
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if isinstance(d.get("symbols_traded"), str):
            try:
                d["symbols_traded"] = json.loads(d["symbols_traded"])
            except Exception:
                pass
        result.append(d)
    return result
```

---

## 3. S11 — `backend/services/engine/us_market_watch.py` 신규

```python
"""S11: 22:00 KST 미국 장중 지표 수집 → overnight_market_snapshots 저장."""

import uuid, json
from datetime import datetime
from zoneinfo import ZoneInfo

from ..db import get_connection
from .market_data_fetcher import fetch_overnight_market_summary

logger = logging.getLogger("USMarketWatch")


def _ensure_table() -> None:
    with get_connection() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS overnight_market_snapshots (
            id TEXT PRIMARY KEY,
            snapshot_date TEXT NOT NULL,
            snapshot_time TEXT NOT NULL,
            sp500_chg_pct REAL,
            nasdaq_chg_pct REAL,
            dow_chg_pct REAL,
            ftse100_chg_pct REAL,
            dax_chg_pct REAL,
            oil_wti_chg_pct REAL,
            usdkrw_rate REAL,
            us_10y_yield REAL,
            raw_data TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )""")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_overnight_market_snapshot_date ON overnight_market_snapshots(snapshot_date)"
        )


async def run_us_market_watch() -> dict:
    """미국 장중 주요 지표를 수집하고 overnight_market_snapshots에 저장한다."""
    _ensure_table()
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    snapshot_date = now_kst.strftime("%Y-%m-%d")
    snapshot_time = now_kst.strftime("%H:%M")
    now_iso = now_kst.isoformat()

    # Yahoo Finance 수집 (market_data_fetcher 재사용)
    data = await fetch_overnight_market_summary()

    def _chg(key: str) -> float | None:
        item = data.get(key)
        if item and item.get("change_pct") is not None:
            try:
                return float(item["change_pct"])
            except (ValueError, TypeError):
                return None
        return None

    def _price(key: str) -> float | None:
        item = data.get(key)
        if item and item.get("price") is not None:
            try:
                return float(item["price"])
            except (ValueError, TypeError):
                return None
        return None

    snapshot_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO overnight_market_snapshots
               (id, snapshot_date, snapshot_time,
                sp500_chg_pct, nasdaq_chg_pct, dow_chg_pct,
                ftse100_chg_pct, dax_chg_pct, oil_wti_chg_pct,
                usdkrw_rate, us_10y_yield, raw_data, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                snapshot_id, snapshot_date, snapshot_time,
                _chg("sp500"), _chg("nasdaq"), _chg("dow"),
                _chg("ftse100"), _chg("dax"), _chg("oil_wti"),
                _price("usdkrw"), _price("us_10y_yield"),
                json.dumps(data, ensure_ascii=False),
                now_iso,
            )
        )

    logger.info("SUCCESS: USMarketWatch snapshot saved date=%s time=%s sp500=%s nasdaq=%s",
                snapshot_date, snapshot_time, _chg("sp500"), _chg("nasdaq"))

    return {
        "snapshot_date": snapshot_date,
        "snapshot_time": snapshot_time,
        "sp500_chg_pct": _chg("sp500"),
        "nasdaq_chg_pct": _chg("nasdaq"),
        "usdkrw_rate": _price("usdkrw"),
        "errors": data.get("errors", []),
    }


def get_latest_snapshot(trade_date: str | None = None) -> dict | None:
    """가장 최근 overnight snapshot 조회 (S2에서 활용)"""
    _ensure_table()
    with get_connection() as conn:
        if trade_date:
            row = conn.execute(
                "SELECT * FROM overnight_market_snapshots WHERE snapshot_date = ? ORDER BY snapshot_time DESC LIMIT 1",
                (trade_date,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM overnight_market_snapshots ORDER BY snapshot_date DESC, snapshot_time DESC LIMIT 1"
            ).fetchone()
    if not row:
        return None
    d = dict(row)
    if isinstance(d.get("raw_data"), str):
        try:
            d["raw_data"] = json.loads(d["raw_data"])
        except Exception:
            pass
    return d
```

---

## 4. API — `backend/api/routes/trades.py` 신규

```python
router = APIRouter(prefix="/api/v1/trades", tags=["trades"])

@router.get("/history")
async def get_trade_history(limit: int = 30):
    """일별 거래 요약 최근 N일 조회"""
    from ...services.engine.daily_summary import get_trade_history
    items = get_trade_history(limit=limit)
    return {"ok": True, "payload": {"items": items, "count": len(items)}}

@router.get("/history/{trade_date}")
async def get_trade_detail(trade_date: str):
    """특정 날짜 거래 상세 (주문 목록 포함)"""
    from ...services.engine.daily_summary import get_trade_history
    from ...services.engine.order_executor import get_today_orders
    from ...services.engine.decision_engine import get_today_signals
    orders = get_today_orders(trade_date)
    signals = get_today_signals(trade_date)
    history = get_trade_history(limit=365)
    summary = next((h for h in history if h["trade_date"] == trade_date), None)
    return {"ok": True, "payload": {
        "summary": summary,
        "orders": orders,
        "signals": signals,
    }}

@router.get("/overnight/latest")
async def get_overnight_snapshot():
    """최신 해외 시장 스냅샷 조회"""
    from ...services.engine.us_market_watch import get_latest_snapshot
    snapshot = get_latest_snapshot()
    return {"ok": True, "payload": {"snapshot": snapshot}}
```

---

## 5. scheduler.py 수정 — placeholder 교체

`job_data_backup()` 교체:
```python
async def job_data_backup() -> None:
    """Job S10 (18:00 KST): 당일 거래 결과 집계 + DB 백업"""
    logger.info("START: [Job S10] 당일 거래 요약 + DB 백업 (18:00 KST)")
    try:
        from .engine.daily_summary import run_daily_summary
        result = await run_daily_summary()
        logger.info("SUCCESS: [Job S10] 완료 orders=%d pnl=%.0f backup=%s",
                    result.get("total_orders", 0),
                    result.get("realized_pnl", 0),
                    result.get("backup", {}).get("ok"))
    except Exception as exc:
        logger.error("FAIL: [Job S10] 실패 — reason=%s", exc)
```

`job_us_market_watch()` 교체:
```python
async def job_us_market_watch() -> None:
    """Job S11 (22:00 KST): 미국 장중 지표 수집 + DB 저장"""
    logger.info("START: [Job S11] 미국장 관찰 (22:00 KST)")
    try:
        from .engine.us_market_watch import run_us_market_watch
        result = await run_us_market_watch()
        logger.info("SUCCESS: [Job S11] 완료 sp500=%s nasdaq=%s usdkrw=%s",
                    result.get("sp500_chg_pct"), result.get("nasdaq_chg_pct"),
                    result.get("usdkrw_rate"))
    except Exception as exc:
        logger.error("FAIL: [Job S11] 실패 — reason=%s", exc)
```

---

## 6. main.py 수정

```python
from .api.routes.trades import router as trades_router
app.include_router(trades_router)
```

---

## 7. console.html — Review & Audit 탭에 거래 히스토리 추가

`screen-review` 섹션에 "일별 거래 기록" 카드 추가:

```
[일별 거래 기록]                               [조회]  최근 [30 ▼]일
  날짜        주문수  매수  매도  실현손익      손익률   톤    거래종목
  2026-05-02   4     2    2    +12,000      +1.2%   중립  3개
  2026-05-01   6     3    3    -5,000       -0.5%   부정  4개
  (없으면 "거래 기록 없음")
```

클릭 시 상세 모달(또는 하단 확장): 해당 날짜 주문 목록 표시
- 컬럼: 시간 / 종목코드 / 종목명 / 구분 / 수량 / 가격 / 상태 / 이유

KIS System Test 탭에 S10/S11 카드 추가:
```
S10 — 당일 거래 요약    → POST /api/v1/trades/run-summary  (수동 실행)
S11 — 미국장 스냅샷     → GET /api/v1/trades/overnight/latest
```

`/api/v1/trades/run-summary` 엔드포인트도 trades.py에 추가:
```python
@router.post("/run-summary")
async def run_summary_manual():
    from ...services.engine.daily_summary import run_daily_summary
    result = await run_daily_summary()
    return {"ok": True, "payload": result}
```

---

## 완료 기준

```bash
python -m py_compile backend/services/engine/daily_summary.py && echo "daily_summary OK"
python -m py_compile backend/services/engine/us_market_watch.py && echo "us_market_watch OK"
python -m py_compile backend/api/routes/trades.py && echo "trades_route OK"
python -m py_compile backend/services/scheduler.py && echo "scheduler OK"
python -m py_compile backend/main.py && echo "main OK"
python3 -c "from html.parser import HTMLParser; p=HTMLParser(); p.feed(open('backend/static/console.html').read()); print('HTML OK')"
python -c "
from backend.services.engine.daily_summary import run_daily_summary, get_trade_history
from backend.services.engine.us_market_watch import run_us_market_watch, get_latest_snapshot
print('imports OK')
"
```

OUTBOX(`docs/agent-comm/OUTBOX_EXECUTOR_s10_s11_daily.md`)에 결과 작성.
