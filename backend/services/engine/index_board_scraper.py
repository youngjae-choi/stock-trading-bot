"""index-board.space 시황 브리핑 스크래퍼 (httpx + RSC JSON 파싱, 브라우저 불필요).

index-board.space는 Next.js SSR이라 브리핑 텍스트가 초기 HTML 안에
escaped JSON 객체로 박혀 있다. Chromium/Playwright 없이 httpx GET + 정규식으로
충분히 수집 가능하다.

아침(장전)  = type=pre,     market=kospi  의 generatedAt 최신 1건
장중       = type=regular, market 무관  의 generatedAt 최신 1건
장후       = type=post,    market=nasdaq 의 generatedAt 최신 1건
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
#   \"text\":\"...\",\"type\":\"regular\",\"market\":\"nasdaq\",\"generatedAt\":\"...Z\"
# text 안에는 \uXXXX 유니코드 이스케이프가 있을 수 있으나, \" 이스케이프된 따옴표는
# fixture 기준 text 내부에 없다고 가정하고 비탐욕(.*?) 매칭으로 첫 종료 따옴표까지 잡는다.
# type은 pre(장전)/regular(장중)/post(장후) 외 향후 신규 타입도 잡도록 [a-z]+ 로 일반화한다.
_BRIEFING_RE = re.compile(
    r'\\"text\\":\\"(?P<text>.*?)\\",'
    r'\\"type\\":\\"(?P<type>[a-z]+)\\",'
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

    반환: [{"text": str, "type": "pre"(장전)|"regular"(장중)|"post"(장후), "market": str, "generated_at": str}, ...]
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


def _to_float(raw: str | None, *, neg_paren: bool = False) -> float | None:
    """'1,541' / '+3.93' / '-1.73' 같은 조각을 float로. neg_paren=True면 (..)도 음수로 본다."""
    if raw is None:
        return None
    s = raw.strip().replace(",", "")
    neg = False
    if neg_paren and s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1].strip()
    # 부호 추출
    if s.startswith("+"):
        s = s[1:]
    elif s.startswith("-"):
        neg = True
        s = s[1:]
    # 숫자 코어만 남기기 (혹시 모를 잔여 문자 제거)
    m = re.search(r"\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        val = float(m.group(0))
    except ValueError:
        return None
    return -val if neg else val


# 부호 + 숫자(소수 가능) 조각. + / - 선택, 콤마는 _to_float에서 제거하므로 여기선 안 잡음.
_SIGNED_NUM = r"[+\-]?\d+(?:\.\d+)?"


def parse_briefing_numbers(text: str) -> dict:
    """브리핑 텍스트에서 핵심 수치 지표를 추출한다(없으면 해당 키는 None).

    추출 항목(평탄 dict):
      - vix (float)                  : "VIX가 18.84" / "VIX 18.84"
      - fear_greed (int)             : "공포&탐욕 지수가 26점(Fear)" → 26
      - fear_greed_label (str)       : 위 괄호 라벨 → "Fear"
      - kospi200_futures_pct (float) : "코스피200 선물 약세(-1.73%)" → -1.73
      - usdkrw (float)               : "원/달러 환율 ...(1,541원대)" / "1,541원" → 1541.0
      - sox_pct (float)              : "필라델피아 반도체지수가 +3.93%" / "3.39% 급등" → 3.93 / 3.39
      - foreign_flow (str)           : "외국인 수급 불안" 류 정성 문구 (없으면 None)

    파싱 불가/누락은 항상 None으로 둔다 — 절대 예외를 던지지 않는다.
    """
    out: dict[str, Any] = {
        "vix": None,
        "fear_greed": None,
        "fear_greed_label": None,
        "kospi200_futures_pct": None,
        "usdkrw": None,
        "sox_pct": None,
        "foreign_flow": None,
    }
    if not text or not isinstance(text, str):
        return out
    try:
        # VIX: "VIX가 18.84" / "VIX 18.84" / "VIX는 18.84"
        m = re.search(r"VIX[가는은이]?\s*([0-9]+(?:\.[0-9]+)?)", text, re.I)
        if m:
            out["vix"] = _to_float(m.group(1))

        # 공포&탐욕 지수: "공포&탐욕 지수가 26점(Fear)" — 점수 + 괄호 라벨
        m = re.search(
            r"(?:공포\s*[&·/]?\s*탐욕|공포\s*탐욕|fear\s*&?\s*greed)[^0-9]{0,12}"
            r"([0-9]+)\s*점?\s*(?:\(([^)]+)\))?",
            text,
            re.I,
        )
        if m:
            try:
                out["fear_greed"] = int(m.group(1))
            except (TypeError, ValueError):
                out["fear_greed"] = None
            if m.group(2):
                out["fear_greed_label"] = m.group(2).strip()

        # 코스피200 선물 등락: "코스피200 선물 ...(-1.73%)" — 괄호 안 부호숫자%
        m = re.search(
            r"코스피\s*200\s*선물[^()]*\(\s*(" + _SIGNED_NUM + r")\s*%?\s*\)",
            text,
        )
        if m:
            out["kospi200_futures_pct"] = _to_float(m.group(1))

        # 원/달러 환율: "원/달러 환율 ...(1,541원대)" 또는 "1,541원"
        m = re.search(r"원\s*/?\s*달러[^()0-9]*\(?\s*([0-9][0-9,]*)\s*원", text)
        if not m:
            m = re.search(r"([0-9][0-9,]*)\s*원\s*대?", text)
        if m:
            out["usdkrw"] = _to_float(m.group(1))

        # 필라델피아 반도체(SOX): "...반도체지수가 +3.93%" 또는 "...반도체지수가 3.39% 급등"
        m = re.search(
            r"필라델피아\s*반도체\S*[가이]?\s*(" + _SIGNED_NUM + r")\s*%",
            text,
        )
        if m:
            out["sox_pct"] = _to_float(m.group(1))

        # 외국인 수급(정성): "외국인 수급 불안" / "외국인 수급 호조" 등 — 뒤따르는 한 단어
        m = re.search(r"외국인\s*수급\s*([가-힣]{1,6})", text)
        if m:
            out["foreign_flow"] = m.group(1).strip()
    except Exception as exc:  # pragma: no cover - 절대 예외 전파 금지
        logger.warning("WARN: parse_briefing_numbers 파싱 중 예외 — %s", exc)
    return out


def select_latest(briefings: list[dict], type_: str, market: str | None = None) -> dict | None:
    """주어진 type(+선택적 market) 중 generated_at이 가장 최신인 1건 반환. 없으면 None.

    market=None이면 market 무관으로 type만 매칭한다(장중 regular처럼 시장이 여러 개일 때).
    """
    candidates = [
        b
        for b in briefings
        if b.get("type") == type_ and (market is None or b.get("market") == market)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda b: b.get("generated_at") or "")


def select_latest_by_type(briefings: list[dict], type_: str) -> dict | None:
    """market 무관으로 주어진 type 중 generated_at 최신 1건 반환. 없으면 None."""
    return select_latest(briefings, type_, market=None)


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


async def _scrape(type_: str, market: str | None = None) -> dict | None:
    html = await fetch_html()
    if not html:
        return None
    briefings = parse_briefings(html)
    selected = select_latest(briefings, type_, market)
    if selected is None:
        logger.warning(
            "WARN: IndexBoardScraper — %s/%s 브리핑 없음 (parsed=%d)",
            type_,
            market if market is not None else "*",
            len(briefings),
        )
    return selected


async def scrape_morning() -> dict | None:
    """장전(pre/kospi) 최신 브리핑 1건. {text, type, market, generated_at} 또는 None."""
    return await _scrape("pre", "kospi")


async def scrape_evening() -> dict | None:
    """장후(post/nasdaq) 최신 브리핑 1건. None 가능."""
    return await _scrape("post", "nasdaq")


async def scrape_intraday() -> dict | None:
    """장중(regular, market 무관) 최신 브리핑 1건. {text, type, market, generated_at} 또는 None.

    장중 브리핑은 여러 시장(nasdaq 등)으로 나올 수 있어 market을 가리지 않고
    generatedAt 최신 1건을 고른다. 선택된 브리핑의 market은 그대로 노출된다.
    """
    return await _scrape("regular", None)


_LIVE_CACHE: dict[str, Any] = {"data": None, "ts": 0.0}
_LIVE_TTL_SEC = 600.0  # 10분


async def scrape_both_live(ttl: float = _LIVE_TTL_SEC) -> dict:
    """장전+장후 브리핑을 1회 fetch로 파싱해 반환. 10분 메모리 캐시.

    반환: {
      "ok": bool,
      "morning": {text, generated_at, market, type} | None,   # pre/kospi
      "intraday": {text, generated_at, market, type} | None,  # regular (market 무관 최신)
      "evening": {text, generated_at, market, type} | None,   # post/nasdaq
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
        return {"ok": False, "morning": None, "intraday": None, "evening": None, "cached": False}
    items = parse_briefings(html)
    morning = select_latest(items, "pre", "kospi")
    intraday = select_latest_by_type(items, "regular")
    evening = select_latest(items, "post", "nasdaq")
    data = {"ok": True, "morning": morning, "intraday": intraday, "evening": evening, "cached": False}
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
    - intraday(regular)는 장중 갱신되는 휘발성 데이터라 DB에 저장하지 않고,
      live 스크랩이 일어난 경우에만 그 시점 최신값을 함께 노출한다(없으면 None).
    반환: {ok, morning, intraday, evening, source}
    """
    db = _load_briefing_db(trade_date)
    db_morning, db_evening = db.get("morning"), db.get("evening")

    if db_morning and db_evening:
        return {
            "ok": True,
            "morning": db_morning,
            "intraday": None,  # 스크랩 없이 DB만 반환하는 경로 — 장중값 미조회
            "evening": db_evening,
            "source": "db",
        }

    # 누락 조각이 있으니 1회 스크랩 시도
    live = await scrape_both_live()
    morning = db_morning or (live.get("morning") if live.get("ok") else None)
    evening = db_evening or (live.get("evening") if live.get("ok") else None)
    intraday = live.get("intraday") if live.get("ok") else None

    # 새로 확보한 조각이 있으면 저장 (intraday는 휘발성이라 저장 대상 아님)
    if (morning and not db_morning) or (evening and not db_evening):
        try:
            _save_briefing_db(trade_date, morning, evening)
        except Exception as exc:  # 저장 실패는 비치명 — 화면 표시는 유지
            logger.warning("WARN: index-board 브리핑 DB 저장 실패 date=%s — %s", trade_date, exc)

    source = "db" if (db_morning or db_evening) else "scrape"
    return {
        "ok": bool(morning or evening),
        "morning": morning,
        "intraday": intraday,
        "evening": evening,
        "source": source,
    }
