"""index-board.space 시황 브리핑 스크래퍼 (httpx + RSC JSON 파싱, 브라우저 불필요).

index-board.space는 Next.js SSR이라 브리핑 텍스트가 초기 HTML 안에
escaped JSON 객체로 박혀 있다. Chromium/Playwright 없이 httpx GET + 정규식으로
충분히 수집 가능하다.

아침(장전)  = type=pre,  market=kospi  의 generatedAt 최신 1건
장후       = type=post, market=nasdaq 의 generatedAt 최신 1건
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

logger = logging.getLogger("IndexBoardScraper")

DEFAULT_URL = "https://index-board.space/briefing"
_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"

# HTML 원문에는 백슬래시-이스케이프된 JSON이 들어있다:
#   \"text\":\"...\",\"type\":\"pre\",\"market\":\"kospi\",\"generatedAt\":\"...Z\"
# text 안에는 \uXXXX 유니코드 이스케이프가 있을 수 있으나, \" 이스케이프된 따옴표는
# fixture 기준 text 내부에 없다고 가정하고 비탐욕(.*?) 매칭으로 첫 종료 따옴표까지 잡는다.
_BRIEFING_RE = re.compile(
    r'\\"text\\":\\"(?P<text>.*?)\\",'
    r'\\"type\\":\\"(?P<type>pre|post)\\",'
    r'\\"market\\":\\"(?P<market>[a-z0-9_]+)\\",'
    r'\\"generatedAt\\":\\"(?P<generated_at>[0-9T:.\-]+Z?)\\"',
    re.S,
)


def _unescape_text(raw: str) -> str:
    """escaped JSON 문자열 조각을 사람이 읽는 텍스트로 복원한다."""
    # \uXXXX → 실제 문자, \\" → ", \\\\ → \, \\n → 개행 등 흔한 이스케이프 처리.
    out = raw
    # 유니코드 이스케이프 (& 등)
    out = re.sub(
        r"\\u([0-9a-fA-F]{4})",
        lambda m: chr(int(m.group(1), 16)),
        out,
    )
    out = out.replace('\\"', '"')
    out = out.replace("\\n", "\n")
    out = out.replace("\\t", "\t")
    out = out.replace("\\/", "/")
    out = out.replace("\\\\", "\\")
    return out


def parse_briefings(html: str) -> list[dict[str, Any]]:
    """HTML 안에 escaped JSON으로 박힌 브리핑 객체들을 추출한다.

    반환: [{"text": str, "type": "pre"|"post", "market": str, "generated_at": str}, ...]
    파싱 실패/객체 없음이면 빈 리스트.
    """
    if not html:
        return []
    results: list[dict[str, Any]] = []
    try:
        for m in _BRIEFING_RE.finditer(html):
            results.append(
                {
                    "text": _unescape_text(m.group("text")),
                    "type": m.group("type"),
                    "market": m.group("market"),
                    "generated_at": m.group("generated_at"),
                }
            )
    except Exception as exc:  # pragma: no cover - 방어적
        logger.warning("WARN: IndexBoardScraper.parse_briefings 파싱 실패 — %s", exc)
        return []
    return results


def select_latest(briefings: list[dict], type_: str, market: str) -> dict | None:
    """주어진 type/market 조합 중 generated_at이 가장 최신인 1건 반환. 없으면 None."""
    candidates = [
        b
        for b in briefings
        if b.get("type") == type_ and b.get("market") == market
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda b: b.get("generated_at") or "")


def _resolve_url() -> str:
    try:
        from ..settings_store import get_setting

        url = get_setting("briefing.scrape_url", DEFAULT_URL)
        return str(url) if url else DEFAULT_URL
    except Exception:  # pragma: no cover - settings 미초기화 등
        return DEFAULT_URL


def _resolve_timeout(default: float) -> float:
    try:
        from ..settings_store import get_setting

        val = get_setting("briefing.scrape_timeout_sec", default)
        return float(val) if val is not None else default
    except Exception:  # pragma: no cover
        return default


async def fetch_html(url: str | None = None, timeout: float = 20.0) -> str | None:
    """httpx로 페이지 HTML을 가져온다. 실패 시 None (예외는 잡아서 로깅)."""
    target = url or _resolve_url()
    eff_timeout = _resolve_timeout(timeout) if url is None else timeout
    try:
        import httpx

        async with httpx.AsyncClient(timeout=eff_timeout, headers={"User-Agent": _UA}) as client:
            resp = await client.get(target, follow_redirects=True)
            resp.raise_for_status()
            return resp.text
    except Exception as exc:
        logger.warning("WARN: IndexBoardScraper.fetch_html 실패 url=%s — %s", target, exc)
        return None


async def _scrape(type_: str, market: str) -> dict | None:
    html = await fetch_html()
    if not html:
        return None
    briefings = parse_briefings(html)
    selected = select_latest(briefings, type_, market)
    if selected is None:
        logger.warning(
            "WARN: IndexBoardScraper — %s/%s 브리핑 없음 (parsed=%d)",
            type_,
            market,
            len(briefings),
        )
    return selected


async def scrape_morning() -> dict | None:
    """장전(pre/kospi) 최신 브리핑 1건. {text, type, market, generated_at} 또는 None."""
    return await _scrape("pre", "kospi")


async def scrape_evening() -> dict | None:
    """장후(post/nasdaq) 최신 브리핑 1건. None 가능."""
    return await _scrape("post", "nasdaq")


_LIVE_CACHE: dict[str, Any] = {"data": None, "ts": 0.0}
_LIVE_TTL_SEC = 600.0  # 10분


async def scrape_both_live(ttl: float = _LIVE_TTL_SEC) -> dict:
    """장전+장후 브리핑을 1회 fetch로 파싱해 반환. 10분 메모리 캐시.

    반환: {
      "ok": bool,
      "morning": {text, generated_at, market, type} | None,
      "evening": {text, generated_at, market, type} | None,
      "cached": bool,                  # 캐시 히트 여부
    }
    실패(fetch None) 시 직전 캐시(stale)라도 있으면 반환, 없으면 빈 결과.
    """
    now = time.monotonic()
    cached = _LIVE_CACHE.get("data")
    if cached is not None and (now - _LIVE_CACHE.get("ts", 0.0)) < ttl:
        result = dict(cached)
        result["cached"] = True
        return result
    html = await fetch_html()
    if not html:
        # 실패 시 직전 캐시라도 있으면 그걸 반환(stale 허용), 없으면 빈 결과
        if cached is not None:
            stale = dict(cached)
            stale["cached"] = True
            stale["stale"] = True
            return stale
        return {"ok": False, "morning": None, "evening": None, "cached": False}
    items = parse_briefings(html)
    morning = select_latest(items, "pre", "kospi")
    evening = select_latest(items, "post", "nasdaq")
    data = {"ok": True, "morning": morning, "evening": evening, "cached": False}
    _LIVE_CACHE["data"] = data
    _LIVE_CACHE["ts"] = now
    return dict(data)


# ──────────────────────────────────────────────────────────────────────────
# DB 영속 캐시 — 아침/장후 브리핑은 하루 1회 산출되는 안정 데이터.
# 한 번 스크랩해 DB에 저장하면, 그 이후엔 DB에서 조회해 표시한다. (PM 지시 2026-06-15)
# 누락된 조각(morning/evening)만 채우기 위해 스크랩하고, 이미 저장된 조각은 DB값을 유지한다.
# ──────────────────────────────────────────────────────────────────────────

def _ensure_briefing_table() -> None:
    from ..db import get_connection

    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS index_board_briefing_cache (
                trade_date   TEXT PRIMARY KEY,
                morning_json TEXT,
                evening_json TEXT,
                updated_at   TEXT NOT NULL
            )
            """
        )


def _load_briefing_db(trade_date: str) -> dict:
    """DB에 저장된 trade_date 브리핑 조각 반환. {morning, evening} (없으면 None)."""
    import json

    _ensure_briefing_table()
    from ..db import get_connection

    with get_connection() as conn:
        row = conn.execute(
            "SELECT morning_json, evening_json FROM index_board_briefing_cache WHERE trade_date = ?",
            (trade_date,),
        ).fetchone()
    if not row:
        return {"morning": None, "evening": None}
    def _parse(s):
        try:
            return json.loads(s) if s else None
        except Exception:
            return None
    return {"morning": _parse(row[0]), "evening": _parse(row[1])}


def _save_briefing_db(trade_date: str, morning: dict | None, evening: dict | None) -> None:
    import json
    from datetime import datetime, timezone

    _ensure_briefing_table()
    from ..db import get_connection

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO index_board_briefing_cache (trade_date, morning_json, evening_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(trade_date) DO UPDATE SET
                morning_json = excluded.morning_json,
                evening_json = excluded.evening_json,
                updated_at   = excluded.updated_at
            """,
            (
                trade_date,
                json.dumps(morning, ensure_ascii=False) if morning else None,
                json.dumps(evening, ensure_ascii=False) if evening else None,
                datetime.now(timezone.utc).isoformat(),
            ),
        )


async def scrape_both_with_db(trade_date: str) -> dict:
    """DB 우선 조회. 누락 조각만 스크랩해 DB에 저장 후 병합 반환.

    - morning/evening 둘 다 DB에 있으면 → 스크랩 없이 DB 반환 (source="db").
    - 하나라도 없으면 → 1회 스크랩으로 누락분만 채우고 upsert.
      (이미 저장된 조각은 DB값 유지 — 한 번 확정되면 바뀌지 않음)
    반환: {ok, morning, evening, source}
    """
    db = _load_briefing_db(trade_date)
    db_morning, db_evening = db.get("morning"), db.get("evening")

    if db_morning and db_evening:
        return {"ok": True, "morning": db_morning, "evening": db_evening, "source": "db"}

    # 누락 조각이 있으니 1회 스크랩 시도
    live = await scrape_both_live()
    morning = db_morning or (live.get("morning") if live.get("ok") else None)
    evening = db_evening or (live.get("evening") if live.get("ok") else None)

    # 새로 확보한 조각이 있으면 저장
    if (morning and not db_morning) or (evening and not db_evening):
        try:
            _save_briefing_db(trade_date, morning, evening)
        except Exception as exc:  # 저장 실패는 비치명 — 화면 표시는 유지
            logger.warning("WARN: index-board 브리핑 DB 저장 실패 date=%s — %s", trade_date, exc)

    source = "db" if (db_morning or db_evening) else "scrape"
    return {"ok": bool(morning or evening), "morning": morning, "evening": evening, "source": source}
