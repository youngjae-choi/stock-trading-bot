# INBOX_EXECUTOR_trading_infra — 공휴일 관리 + 해외 시장 데이터 + 스케줄러 설정화

## 작업 개요

세 가지를 한 번에 구현한다:
1. 공휴일 DB 테이블 + CRUD 서비스 + API
2. 해외 시장 데이터 수집 서비스 (야후파이낸스, 환율, 금리)
3. S2 프롬프트에 해외 시장 데이터 주입
4. scheduler.py — S3/S4/S5는 비거래일(공휴일+주말) 스킵
5. scheduler.py — 실행 시간을 system_settings DB에서 읽어 사용

---

## 구현 파일 목록

| 파일 | 유형 |
|------|------|
| `backend/services/trading_calendar.py` | 신규 |
| `backend/services/engine/market_data_fetcher.py` | 신규 |
| `backend/api/routes/trading_calendar.py` | 신규 |
| `backend/services/engine/market_tone.py` | 수정 |
| `backend/services/scheduler.py` | 수정 |
| `backend/main.py` | 수정 |

---

## 참조 파일 (읽기 전용)

- `backend/services/db.py` — `get_connection()` 패턴
- `backend/services/settings_store.py` — `list_settings()` 함수
- `backend/services/engine/market_tone.py` — `_TONE_PROMPT`, `run_market_tone_analysis()`
- `backend/services/scheduler.py` — 전체 구조, `_build_scheduler()`
- `backend/api/routes/market_tone.py` — 라우터 패턴

---

## 1. `backend/services/trading_calendar.py` (신규)

### 역할
- 공휴일 CRUD
- `is_trading_day(date_str: str) -> bool`: 주말+공휴일이면 False

```python
"""거래 달력 서비스 — 공휴일 등록 및 비거래일 판단."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any

from .db import get_connection

logger = logging.getLogger("TradingCalendar")


def _ensure_table() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trading_holidays (
                id           TEXT PRIMARY KEY,
                holiday_date TEXT NOT NULL UNIQUE,   -- YYYY-MM-DD
                description  TEXT NOT NULL DEFAULT '',
                created_at   TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trading_holidays_date ON trading_holidays(holiday_date)"
        )


def is_trading_day(date_str: str) -> bool:
    """해당 날짜가 거래일인지 반환한다. 주말 또는 공휴일이면 False."""
    _ensure_table()
    try:
        d = date.fromisoformat(date_str)
    except ValueError:
        return False
    # 주말 체크 (0=월 ... 5=토, 6=일)
    if d.weekday() >= 5:
        return False
    # 공휴일 체크
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM trading_holidays WHERE holiday_date = ?",
            (date_str,),
        ).fetchone()
    return row is None


def add_holiday(holiday_date: str, description: str = "") -> dict[str, Any]:
    """공휴일을 등록한다."""
    _ensure_table()
    # 날짜 형식 검증
    date.fromisoformat(holiday_date)
    now = datetime.now(timezone.utc).isoformat()
    hid = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO trading_holidays (id, holiday_date, description, created_at) VALUES (?, ?, ?, ?)",
            (hid, holiday_date, description, now),
        )
    logger.info("SUCCESS: TradingCalendar.add_holiday date=%s", holiday_date)
    return {"id": hid, "holiday_date": holiday_date, "description": description}


def remove_holiday(holiday_date: str) -> bool:
    """공휴일을 삭제한다. 삭제 성공 시 True."""
    _ensure_table()
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM trading_holidays WHERE holiday_date = ?",
            (holiday_date,),
        )
    return cur.rowcount > 0


def list_holidays(year: int | None = None) -> list[dict[str, Any]]:
    """공휴일 목록을 반환한다. year 지정 시 해당 연도만."""
    _ensure_table()
    with get_connection() as conn:
        if year:
            rows = conn.execute(
                "SELECT * FROM trading_holidays WHERE holiday_date LIKE ? ORDER BY holiday_date",
                (f"{year}-%",),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trading_holidays ORDER BY holiday_date"
            ).fetchall()
    return [dict(r) for r in rows]
```

---

## 2. `backend/services/engine/market_data_fetcher.py` (신규)

### 역할
전날 밤 해외 시장 데이터를 야후파이낸스 API로 수집한다.
수집 항목: S&P500, NASDAQ, FTSE100, DAX, WTI 원유, USD/KRW, 미국 10년 국채금리

```python
"""해외 시장 데이터 수집 서비스 (S2용).

야후파이낸스 비공개 JSON API를 사용해 전날 종가 및 등락률을 수집한다.
API 실패 시 해당 항목을 errors 목록에 추가하고 나머지는 계속 진행한다.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger("MarketDataFetcher")

_TIMEOUT = 15.0
_SYMBOLS = {
    "sp500":        "^GSPC",
    "nasdaq":       "^IXIC",
    "ftse100":      "^FTSE",
    "dax":          "^GDAXI",
    "oil_wti":      "CL=F",
    "usdkrw":       "USDKRW=X",
    "us_10y_yield": "^TNX",
}
_YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=2d&interval=1d"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DantabotMarketFetcher/1.0)",
}


async def _fetch_symbol(client: httpx.AsyncClient, key: str, symbol: str) -> tuple[str, dict | None]:
    """단일 심볼을 조회해 (key, data_dict) 또는 (key, None)을 반환한다."""
    url = _YAHOO_URL.format(symbol=symbol)
    try:
        resp = await client.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        result = data["chart"]["result"]
        if not result:
            return key, None
        meta = result[0]["meta"]
        price = meta.get("regularMarketPrice") or meta.get("previousClose", 0)
        prev_close = meta.get("chartPreviousClose") or meta.get("previousClose", price)
        change_pct = round(((price - prev_close) / prev_close * 100) if prev_close else 0.0, 2)
        direction = "up" if change_pct > 0 else ("down" if change_pct < 0 else "flat")
        return key, {
            "symbol": symbol,
            "price": round(price, 4),
            "prev_close": round(prev_close, 4),
            "change_pct": change_pct,
            "direction": direction,
        }
    except Exception as exc:
        logger.warning("WARN: MarketDataFetcher symbol=%s failed — %s", symbol, exc)
        return key, None


async def fetch_overnight_market_summary() -> dict[str, Any]:
    """전날 밤 해외 시장 데이터를 수집해 dict로 반환한다."""
    from zoneinfo import ZoneInfo
    fetched_at = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
    logger.info("START: MarketDataFetcher.fetch_overnight_market_summary")

    results: dict[str, Any] = {}
    errors: list[str] = []

    # 개별 요청 순차 실행 (야후파이낸스 rate limit 고려)
    async with httpx.AsyncClient() as client:
        for key, symbol in _SYMBOLS.items():
            k, data = await _fetch_symbol(client, key, symbol)
            if data:
                results[k] = data
            else:
                results[k] = None
                errors.append(key)

    results["fetched_at"] = fetched_at
    results["errors"] = errors
    logger.info(
        "SUCCESS: MarketDataFetcher fetched=%d errors=%d",
        len(_SYMBOLS) - len(errors), len(errors),
    )
    return results


def format_for_prompt(market_data: dict[str, Any]) -> str:
    """market_data를 LLM 프롬프트용 텍스트로 변환한다."""
    lines = ["[전날 밤 해외 시장 현황]"]
    labels = {
        "sp500":        "S&P 500 (미국)",
        "nasdaq":       "NASDAQ (미국 기술주)",
        "ftse100":      "FTSE 100 (영국)",
        "dax":          "DAX (독일)",
        "oil_wti":      "WTI 원유 (달러/배럴)",
        "usdkrw":       "USD/KRW 환율 (원)",
        "us_10y_yield": "미국 10년 국채금리 (%)",
    }
    for key, label in labels.items():
        d = market_data.get(key)
        if d:
            arrow = "▲" if d["direction"] == "up" else ("▼" if d["direction"] == "down" else "━")
            lines.append(f"  {label}: {d['price']} {arrow}{d['change_pct']:+.2f}%")
        else:
            lines.append(f"  {label}: 데이터 없음")
    if market_data.get("errors"):
        lines.append(f"  (미수집: {', '.join(market_data['errors'])})")
    lines.append(f"  수집 시각: {market_data.get('fetched_at', '알 수 없음')}")
    return "\n".join(lines)
```

---

## 3. `backend/services/engine/market_tone.py` 수정

### `_TONE_PROMPT` 수정

기존 `_TONE_PROMPT` 상수에서 `오늘 날짜: {date}` 줄 아래에 `{market_data}` 플레이스홀더 추가:

```python
_TONE_PROMPT = """
너는 자동매매 시스템의 시장 분위기 분석 AI다.

주의사항:
- 투자 조언이 아니라 시장 분위기 분류 결과만 작성한다.
- 매수/매도 지시는 절대 하지 않는다.
- 입력 데이터에 없는 사실을 만들지 않는다.
- 결과는 반드시 아래 JSON 형식으로만 작성한다 (다른 텍스트 없이).

오늘 날짜: {date}
분석 시각: 장 시작 전 (08:00 KST)

{market_data}

분석 작업:
위 해외 시장 데이터를 기반으로 한국 주식시장 오늘의 시장 톤을 종합 판단해줘.
S&P500/NASDAQ 방향, 달러 환율 강약, 국채금리 방향, 원유 흐름을 종합한다.
(데이터가 "없음"으로 표시된 항목은 무시하고 가용한 데이터만 활용한다.)

출력 JSON:
{{
  "tone": "positive|neutral|negative|mixed",
  "confidence": 0.0,
  "summary": "한 줄 요약 (50자 이내)",
  "key_factors": ["요인1", "요인2"],
  "risk_factors": ["리스크1"],
  "data_note": "활용한 데이터 출처 메모"
}}
"""
```

### `run_market_tone_analysis()` 수정

`prompt = _TONE_PROMPT.format(date=today)` 부분을 아래로 교체:

```python
    # 해외 시장 데이터 수집
    try:
        from .market_data_fetcher import fetch_overnight_market_summary, format_for_prompt
        market_data = await fetch_overnight_market_summary()
        market_data_text = format_for_prompt(market_data)
    except Exception as exc:
        logger.warning("WARN: MarketToneService 해외 시장 데이터 수집 실패 — %s", exc)
        market_data_text = "[전날 밤 해외 시장 현황]\n  데이터 수집 실패 — LLM 자체 지식으로 판단"

    prompt = _TONE_PROMPT.replace("{date}", today).replace("{market_data}", market_data_text)
```

주의: `str.replace()` 사용 (`.format()` 사용 금지 — 중괄호 충돌).
기존 `_TONE_PROMPT.format(date=today)`를 위 replace 체인으로 교체.

---

## 4. `backend/api/routes/trading_calendar.py` (신규)

```python
"""거래 달력 API — 공휴일 등록/조회/삭제."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ...api.dependencies import require_console_user
from ...services.trading_calendar import (
    add_holiday, remove_holiday, list_holidays, is_trading_day
)

logger = logging.getLogger("TradingCalendarAPI")

router = APIRouter(
    prefix="/api/v1/trading-calendar",
    tags=["trading-calendar"],
    dependencies=[Depends(require_console_user)],
)


class HolidayIn(BaseModel):
    holiday_date: str   # YYYY-MM-DD
    description: str = ""


@router.get("/holidays", summary="공휴일 목록 조회")
async def get_holidays(year: int = Query(default=0)):
    today_year = datetime.now(ZoneInfo("Asia/Seoul")).year
    y = year if year else today_year
    items = list_holidays(y)
    return {"ok": True, "source": "backend", "live": True,
            "payload": {"holidays": items, "year": y}}


@router.post("/holiday", summary="공휴일 등록")
async def post_holiday(body: HolidayIn):
    try:
        result = add_holiday(body.holiday_date, body.description)
        logger.info("SUCCESS: TradingCalendarAPI.post_holiday date=%s", body.holiday_date)
        return {"ok": True, "source": "backend", "live": True, "payload": result}
    except ValueError as exc:
        return JSONResponse(status_code=400,
            content={"ok": False, "error": str(exc), "source": "backend", "live": True})


@router.delete("/holiday/{holiday_date}", summary="공휴일 삭제")
async def delete_holiday(holiday_date: str):
    removed = remove_holiday(holiday_date)
    if not removed:
        return JSONResponse(status_code=404,
            content={"ok": False, "error": "해당 날짜의 공휴일 없음", "source": "backend", "live": True})
    return {"ok": True, "source": "backend", "live": True, "payload": {"deleted": holiday_date}}


@router.get("/is-trading-day", summary="거래일 여부 확인")
async def check_trading_day(date: str = Query(default="")):
    if not date:
        date = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    result = is_trading_day(date)
    return {"ok": True, "source": "backend", "live": True,
            "payload": {"date": date, "is_trading_day": result}}
```

---

## 5. `backend/services/scheduler.py` 수정

### A. 스케줄러 실행 시간을 settings에서 읽기

`_build_scheduler()` 함수 시작 부분에 settings 로드 코드 추가:

```python
def _build_scheduler() -> AsyncIOScheduler:
    # settings에서 스케줄 시간 읽기 (없으면 기본값 사용)
    _schedule_times = {
        "s1": "07:45", "s2": "08:00", "s3": "08:15",
        "s4": "08:30", "s5": "08:45",
        "liquidation": "15:20", "backup": "18:00", "us_watch": "22:00",
    }
    try:
        from .settings_store import list_settings
        saved = {s["key"]: s["value"] for s in list_settings()
                 if s["key"].startswith("schedule_")}
        for key in _schedule_times:
            db_key = f"schedule_{key}_time"
            if db_key in saved and isinstance(saved[db_key], str):
                _schedule_times[key] = saved[db_key]
        logger.info("INFO: Scheduler 시간 로드 times=%s", _schedule_times)
    except Exception as exc:
        logger.warning("WARN: Scheduler settings 로드 실패 — 기본값 사용 %s", exc)

    def _parse(t: str):
        h, m = t.split(":")
        return int(h), int(m)

    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")

    # 각 job 등록 시 _parse(_schedule_times["s1"]) 등으로 hour/minute 읽기
```

각 `scheduler.add_job()` 호출에서 하드코딩된 `hour=7, minute=45`를 아래처럼 변경:
- S1: `h, m = _parse(_schedule_times["s1"]); CronTrigger(hour=h, minute=m, ...)`
- S2: `h, m = _parse(_schedule_times["s2"]); ...`
- S3~S8도 동일하게

### B. 비거래일 스킵 로직 추가

S3(`job_universe_filter`), S4(`job_hybrid_screening`), S5(`job_rulepack_generation`) 함수 시작 부분에 아래 코드 삽입:

```python
async def job_universe_filter() -> None:
    """Job 3 (설정 가능 KST): 유니버스 필터 (S3 구현)."""
    from zoneinfo import ZoneInfo
    today = __import__('datetime').datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    
    from .trading_calendar import is_trading_day
    if not is_trading_day(today):
        logger.info("SKIP: [Job3] 유니버스 필터 — 비거래일(%s) 스킵", today)
        return
    
    logger.info("START: [Job3] 유니버스 필터 (%s KST)", today)
    try:
        ...
```

S4와 S5도 동일하게 비거래일 스킵 코드 삽입.
S1(토큰 갱신), S2(시장 톤)는 스킵 없이 그대로 실행.

---

## 6. `backend/main.py` 수정

imports에 추가:
```python
from .api.routes.trading_calendar import router as trading_calendar_router
```

`app.include_router` 목록에 추가:
```python
app.include_router(trading_calendar_router)
```

---

## 완료 기준

```bash
python -m py_compile backend/services/trading_calendar.py && echo "OK"
python -m py_compile backend/services/engine/market_data_fetcher.py && echo "OK"
python -m py_compile backend/services/engine/market_tone.py && echo "OK"
python -m py_compile backend/api/routes/trading_calendar.py && echo "OK"
python -m py_compile backend/services/scheduler.py && echo "OK"
python -m py_compile backend/main.py && echo "OK"
python -c "from backend.services.trading_calendar import is_trading_day; print('holiday import OK')"
```

OUTBOX(`docs/agent-comm/OUTBOX_EXECUTOR_trading_infra.md`)에 결과 작성.
