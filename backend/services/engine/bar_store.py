"""10초봉 영구 저장 계층 (intraday_bars) — 전략 백테스트·재검증 데이터 토대.

BarEngine은 봉 '마감' 시 enqueue_bar()로 모듈 버퍼에 적재만 한다(DB 쓰기 없음
— 틱 경로 성능 보호). 스케줄러 job이 주기적으로 flush_bars()를 호출해
intraday_bars 테이블에 일괄 INSERT하고, EOD에 cleanup_old_bars()로
보존기간(기본 30일) 초과분을 삭제한다.

설정: bar_store.enabled (기본 True, 시드 불필요 — 코드 기본값으로 동작).
False면 enqueue는 no-op. 설정 조회는 TTL 캐시로 틱 경로 DB 접근을 억제한다.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection
from ..settings_store import get_setting

logger = logging.getLogger("BarStore")

_KST = ZoneInfo("Asia/Seoul")

# flush가 장기간 중단돼도 메모리가 무한 증가하지 않도록 상한(초과 시 오래된 봉부터 폐기)
_MAX_BUFFER_ROWS = 50_000
# enabled 설정 캐시 TTL(초) — 봉 마감마다 DB를 읽지 않기 위한 보호
_ENABLED_TTL_SEC = 60.0

_buffer: list[tuple] = []
_lock = threading.Lock()
_enabled_cache: tuple[float, bool] | None = None  # (monotonic 시각, 값)


def _to_float_or_none(value: Any) -> float | None:
    """숫자 변환. 실패/공백은 None(컬럼 NULL 허용)."""
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_enabled() -> bool:
    """bar_store.enabled 설정 조회(TTL 캐시). 조회 실패 시 기본 True."""
    global _enabled_cache
    now = time.monotonic()
    if _enabled_cache is not None and (now - _enabled_cache[0]) < _ENABLED_TTL_SEC:
        return _enabled_cache[1]
    try:
        enabled = bool(get_setting("bar_store.enabled", True))
    except Exception as exc:
        logger.warning("WARN: bar_store.enabled 조회 실패 — 기본 True 사용 reason=%s", exc)
        enabled = True
    _enabled_cache = (now, enabled)
    return enabled


def _ensure_table() -> None:
    """intraday_bars 테이블과 인덱스를 없으면 생성한다."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS intraday_bars (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date TEXT NOT NULL,
                symbol     TEXT NOT NULL,
                bar_ts     TEXT NOT NULL,
                open       REAL,
                high       REAL,
                low        REAL,
                close      REAL,
                volume     REAL,
                shnu_rate  REAL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_intraday_bars_date_symbol ON intraday_bars(trade_date, symbol)"
        )


def enqueue_bar(symbol: str, bar: dict[str, Any]) -> None:
    """마감된 10초봉 1개를 버퍼에 적재한다(DB 쓰기 없음 — 틱 경로 보호).

    Args:
        symbol: 종목 코드.
        bar: {"bar_ts", "open", "high", "low", "close", "volume", "shnu_rate"(선택)} dict.
    """
    if not _is_enabled():
        return
    sym = str(symbol or "").strip()
    if not sym or not isinstance(bar, dict):
        return
    now_kst = datetime.now(_KST)
    row = (
        now_kst.strftime("%Y-%m-%d"),
        sym,
        str(bar.get("bar_ts") or bar.get("bucket") or ""),
        _to_float_or_none(bar.get("open")),
        _to_float_or_none(bar.get("high")),
        _to_float_or_none(bar.get("low")),
        _to_float_or_none(bar.get("close")),
        _to_float_or_none(bar.get("volume")),
        _to_float_or_none(bar.get("shnu_rate")),
        now_kst.isoformat(),
    )
    with _lock:
        _buffer.append(row)
        # 상한 초과 시 오래된 봉부터 폐기(메모리 보호)
        if len(_buffer) > _MAX_BUFFER_ROWS:
            del _buffer[: len(_buffer) - _MAX_BUFFER_ROWS]


def flush_bars() -> int:
    """버퍼의 봉들을 intraday_bars에 일괄 INSERT 후 버퍼를 비운다.

    Returns:
        저장한 행 수. 실패 시 행을 버퍼에 되돌려 다음 flush에서 재시도한다.
    """
    with _lock:
        if not _buffer:
            return 0
        rows = list(_buffer)
        _buffer.clear()
    try:
        _ensure_table()
        with get_connection() as conn:
            conn.executemany(
                """
                INSERT INTO intraday_bars
                    (trade_date, symbol, bar_ts, open, high, low, close, volume, shnu_rate, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)
    except Exception:
        # 실패 시 유실 방지: 버퍼 앞쪽으로 되돌리고 예외 전파(호출 job이 FAIL 로깅)
        with _lock:
            _buffer[:0] = rows
        raise


def cleanup_old_bars(retention_days: int = 30) -> int:
    """보존기간을 넘긴 봉을 삭제한다(trade_date < 오늘-retention).

    Args:
        retention_days: 보존 일수(기본 30일).

    Returns:
        삭제한 행 수.
    """
    cutoff = (datetime.now(_KST) - timedelta(days=int(retention_days))).strftime("%Y-%m-%d")
    _ensure_table()
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM intraday_bars WHERE trade_date < ?", (cutoff,))
        removed = cursor.rowcount or 0
    if removed:
        logger.info("SUCCESS: [BarStore] 보존기간(%d일) 초과 10초봉 %d행 삭제 cutoff=%s", retention_days, removed, cutoff)
    return removed
