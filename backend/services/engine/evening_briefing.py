"""장후 브리핑 저장/조회 + LLM 감성 분류.

evening_briefing 테이블에 거래일(trade_date) 단위로 장후 브리핑을 저장한다.
감성 분류는 LLM으로 risk_on/neutral/risk_off/volatile 중 하나로 판정하며,
실패 시 'neutral'로 폴백한다 (복기·신뢰도 보정용이라 비치명).
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from ..db import get_connection

logger = logging.getLogger("EveningBriefing")


def _today_kst() -> str:
    """Return today's Asia/Seoul date as YYYY-MM-DD."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")

VALID_SENTIMENTS = {"risk_on", "neutral", "risk_off", "volatile"}


def save_evening_briefing(
    trade_date: str,
    briefing_text: str,
    sentiment: str,
    market_data: dict | None = None,
    source_ts: str | None = None,
    provider: str = "index-board",
) -> None:
    """trade_date UNIQUE 기준 INSERT OR REPLACE."""
    if sentiment not in VALID_SENTIMENTS:
        logger.warning("WARN: EveningBriefing 잘못된 sentiment=%s → neutral 대체", sentiment)
        sentiment = "neutral"
    market_json = json.dumps(market_data or {}, ensure_ascii=False)
    now_expr = "strftime('%Y-%m-%dT%H:%M:%fZ','now')"
    with get_connection() as conn:
        conn.execute(
            f"""
            INSERT OR REPLACE INTO evening_briefing
                (id, trade_date, market_data, briefing_text, sentiment,
                 source_ts, provider, created_at)
            VALUES (
                COALESCE(
                    (SELECT id FROM evening_briefing WHERE trade_date = ?),
                    ?
                ),
                ?, ?, ?, ?, ?, ?, {now_expr}
            )
            """,
            (
                trade_date,
                uuid.uuid4().hex,
                trade_date,
                market_json,
                briefing_text,
                sentiment,
                source_ts,
                provider,
            ),
        )
    logger.info(
        "SUCCESS: EveningBriefing.save trade_date=%s sentiment=%s provider=%s",
        trade_date,
        sentiment,
        provider,
    )


def _row_to_dict(row: Any) -> dict[str, Any]:
    data = dict(row)
    raw_md = data.get("market_data") or "{}"
    try:
        data["market_data"] = json.loads(raw_md)
    except (json.JSONDecodeError, TypeError):
        data["market_data"] = {}
    return data


def get_evening_briefing(trade_date: str) -> dict | None:
    """해당 거래일 장후 브리핑 1건. market_data는 JSON 파싱해서 반환."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM evening_briefing WHERE trade_date = ?",
            (trade_date,),
        ).fetchone()
    if row is None:
        return None
    return _row_to_dict(row)


def get_evening_briefings_range(start: str, end: str) -> list[dict]:
    """기간 내 장후 브리핑 목록 (최근순)."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM evening_briefing
            WHERE trade_date >= ? AND trade_date <= ?
            ORDER BY trade_date DESC
            """,
            (start, end),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


_SENTIMENT_PROMPT = (
    "다음 한국 증시 시황 브리핑의 시장 심리를 "
    "risk_on / neutral / risk_off / volatile 중 하나로만 답하라. "
    "설명 없이 단어 하나만 출력하라.\n\n브리핑:\n{text}"
)


async def classify_sentiment(briefing_text: str) -> str:
    """브리핑 텍스트를 LLM으로 risk_on/neutral/risk_off/volatile 중 하나로 분류.

    LLM 실패 또는 매칭 실패 시 'neutral' 폴백.
    """
    from . import llm_router

    try:
        result = await llm_router.call_llm(
            _SENTIMENT_PROMPT.format(text=(briefing_text or "")[:2000]),
            task_name="장후 브리핑 감성 분류",
        )
    except Exception as exc:  # pragma: no cover - 방어적
        logger.warning("WARN: EveningBriefing.classify_sentiment LLM 호출 예외 — %s", exc)
        return "neutral"

    if not result or not result.get("ok"):
        logger.warning("WARN: EveningBriefing.classify_sentiment LLM 실패 → neutral 폴백")
        return "neutral"

    raw = str(result.get("raw") or "").lower()
    # 정반대 오인 방지를 위해 명시 우선순위: risk_off → risk_on → volatile → neutral
    for keyword in ("risk_off", "risk_on", "volatile", "neutral"):
        if keyword in raw:
            return keyword
    logger.info("INFO: EveningBriefing.classify_sentiment 키워드 미검출 raw=%r → neutral", raw[:80])
    return "neutral"


async def collect_and_store_evening_briefing(trade_date: str | None = None) -> dict:
    """장후 브리핑을 스크랩→감성분류→저장. 반환: {ok, stored, sentiment, reason}.

    - scrape_evening() None이면 stored=False, reason='scrape_failed' (저장 스킵, WARN 로그).
    - 성공 시 classify_sentiment 후 save_evening_briefing.
    - trade_date 미지정 시 KST 오늘.
    - 연속 실패 추적은 단순 로깅으로(별도 상태 테이블 불필요).
    """
    td = trade_date or _today_kst()
    logger.info("START: EveningBriefing.collect trade_date=%s", td)

    # 모듈 단위로 참조해 테스트에서 scrape_evening monkeypatch 가능하도록 한다.
    from . import index_board_scraper

    try:
        scraped = await index_board_scraper.scrape_evening()
    except Exception as exc:
        logger.warning("WARN: EveningBriefing.collect 스크랩 예외 trade_date=%s — %s", td, exc)
        scraped = None

    if not scraped:
        logger.warning(
            "WARN: EveningBriefing.collect 스크랩 실패 trade_date=%s — 저장 스킵(복기용 비치명)", td
        )
        return {"ok": False, "stored": False, "sentiment": None, "reason": "scrape_failed"}

    briefing_text = str(scraped.get("text") or "")
    source_ts = scraped.get("generated_at")

    try:
        sentiment = await classify_sentiment(briefing_text)
    except Exception as exc:  # pragma: no cover - classify_sentiment 자체가 폴백 처리
        logger.warning("WARN: EveningBriefing.collect 감성분류 예외 trade_date=%s — %s", td, exc)
        sentiment = "neutral"

    try:
        save_evening_briefing(
            trade_date=td,
            briefing_text=briefing_text,
            sentiment=sentiment,
            market_data=None,
            source_ts=source_ts,
        )
    except Exception as exc:
        logger.error("FAIL: EveningBriefing.collect 저장 실패 trade_date=%s — %s", td, exc)
        return {"ok": False, "stored": False, "sentiment": sentiment, "reason": f"store_failed: {exc}"}

    logger.info("SUCCESS: EveningBriefing.collect trade_date=%s sentiment=%s", td, sentiment)
    return {"ok": True, "stored": True, "sentiment": sentiment, "reason": "ok"}
