"""국내 시장 라이브 데이터 API (Today Control)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter

logger = logging.getLogger("MarketAPI")
router = APIRouter(prefix="/api/v1/market", tags=["market"])

KST = ZoneInfo("Asia/Seoul")

# 모듈 레벨 재바인딩(테스트 monkeypatch 대상)
from ...services.kis.domestic.universe_service import fetch_intraday_kr_market_snapshot  # noqa: E402

import asyncio  # noqa: E402
import time as _time  # noqa: E402

# 화면 라이브 KIS 콜 완충 — 엔진 KIS 부하와 경합해 초당호출 초과(EGW00201)가 나던 문제 대응.
# 짧은 TTL 내 새로고침은 KIS 재호출 없이 캐시 반환, KIS 실패 시 마지막 성공값 유지(빈칸 방지).
_KR_INDEX_CACHE: dict[str, Any] = {"kospi": None, "kosdaq": None, "ts": 0.0}
_KR_INDEX_TTL = 12.0
_KR_INDEX_LOCK = asyncio.Lock()


def _now_kst() -> datetime:
    """현재 KST 시각 (테스트에서 monkeypatch 가능)."""
    return datetime.now(KST)


def _is_market_open(now: datetime) -> bool:
    """KST 기준 거래일 09:00~15:30 여부."""
    try:
        from ...services.engine.trading_calendar import is_trading_day
        if not is_trading_day(now):
            return False
    except Exception as exc:  # 판정 실패 시 시간 기준만 적용 (차단 안 함)
        logger.warning("WARN: kr-index-live trading_day 판정 실패 — %s", exc)
    open_min = 9 * 60          # 09:00
    close_min = 15 * 60 + 30   # 15:30
    cur_min = now.hour * 60 + now.minute
    return open_min <= cur_min <= close_min


def _index_view(raw: Any) -> dict[str, Any]:
    """스냅샷의 지수 dict에서 price/change_rate만 추려 정규화한다."""
    if not isinstance(raw, dict):
        return {"price": None, "change_rate": None}
    return {
        "price": raw.get("price"),
        "change_rate": raw.get("change_rate"),
    }


@router.get("/kr-index-live")
async def get_kr_index_live() -> dict[str, Any]:
    """라이브 국내지수(KOSPI/KOSDAQ) 스냅샷.

    - 장중: KIS 실시간 등락률.
    - 개장 전/실패: price/change_rate=None (프론트 '장전'/'—' 처리). ok=true 유지.
    - market_open: 시간 기준으로 항상 계산(스냅샷 실패와 무관).
    """
    now = _now_kst()
    market_open = _is_market_open(now)

    _empty = {"price": None, "change_rate": None}
    mono = _time.monotonic()
    cached = False
    stale = False

    def _cache_fresh() -> bool:
        return _KR_INDEX_CACHE["kospi"] is not None and (mono - _KR_INDEX_CACHE["ts"]) < _KR_INDEX_TTL

    if _cache_fresh():
        kospi, kosdaq, cached = _KR_INDEX_CACHE["kospi"], _KR_INDEX_CACHE["kosdaq"], True
    else:
        async with _KR_INDEX_LOCK:
            # 락 획득 사이 다른 요청이 갱신했을 수 있으니 재확인(thundering-herd 방지).
            mono = _time.monotonic()
            if _cache_fresh():
                kospi, kosdaq, cached = _KR_INDEX_CACHE["kospi"], _KR_INDEX_CACHE["kosdaq"], True
            else:
                try:
                    snapshot = await fetch_intraday_kr_market_snapshot()
                    kospi = _index_view(snapshot.get("kospi"))
                    kosdaq = _index_view(snapshot.get("kosdaq"))
                    _KR_INDEX_CACHE.update({"kospi": kospi, "kosdaq": kosdaq, "ts": _time.monotonic()})
                except Exception as exc:
                    logger.warning("WARN: GET /api/v1/market/kr-index-live 스냅샷 실패 — %s", exc)
                    # KIS 실패 시 마지막 성공값 유지(빈칸 방지). 최초 실패면 None.
                    kospi = _KR_INDEX_CACHE["kospi"] or dict(_empty)
                    kosdaq = _KR_INDEX_CACHE["kosdaq"] or dict(_empty)
                    cached = True
                    stale = _KR_INDEX_CACHE["kospi"] is not None

    return {
        "ok": True,
        "payload": {
            "kospi": kospi,
            "kosdaq": kosdaq,
            "market_open": market_open,
            "as_of": now.isoformat(),
            "cached": cached,
            "stale": stale,
        },
    }
