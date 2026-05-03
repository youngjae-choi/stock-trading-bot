"""시장 톤 분석 서비스 (S2 — 08:00 KST).

LLM Router를 통해 오늘의 시장 분위기(긍정/중립/부정)를 분석하고
결과를 DB의 market_tone_results 테이블에 저장한다.

주의:
- LLM 분석 결과는 "참고용 분석 보조"다. 매매 실행 판단은 Python 룰 엔진이 한다.
- 분석 실패 시 기본값(neutral)을 반환하고 시스템은 계속 실행된다.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from ..db import get_connection
from . import llm_router

logger = logging.getLogger("MarketToneService")

_TONE_PROMPT = """
너는 자동매매 시스템의 시장 분위기 분석 AI다.

주의사항:
- 투자 조언이 아니라 시장 분위기 분류 결과만 작성한다.
- 매수/매도 지시는 절대 하지 않는다.
- 입력 데이터에 없는 사실을 만들지 않는다.
- 결과는 반드시 아래 JSON 형식으로만 작성한다 (다른 텍스트 없이).

오늘 날짜: {date}
분석 시각: 장 시작 전

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


def _ensure_table() -> None:
    """market_tone_results 테이블이 없으면 생성한다."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS market_tone_results (
                id          TEXT PRIMARY KEY,
                trade_date  TEXT NOT NULL,
                tone        TEXT NOT NULL DEFAULT 'neutral',
                confidence  REAL NOT NULL DEFAULT 0.0,
                summary     TEXT NOT NULL DEFAULT '',
                key_factors TEXT NOT NULL DEFAULT '[]',
                risk_factors TEXT NOT NULL DEFAULT '[]',
                raw_response TEXT NOT NULL DEFAULT '',
                provider    TEXT NOT NULL DEFAULT 'none',
                created_at  TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_market_tone_trade_date ON market_tone_results(trade_date)"
        )


def _parse_tone_response(raw: str) -> dict[str, Any]:
    """LLM 응답 문자열에서 JSON을 추출해 파싱한다."""
    # 마크다운 코드 블록 제거
    text = raw.strip()
    if "```" in text:
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    # JSON 파싱
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # JSON 블록만 추출 시도
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            data = json.loads(text[start:end])
        else:
            raise

    tone = str(data.get("tone", "neutral")).lower()
    if tone not in ("positive", "neutral", "negative", "mixed"):
        tone = "neutral"

    return {
        "tone": tone,
        "confidence": float(data.get("confidence", 0.0)),
        "summary": str(data.get("summary", ""))[:200],
        "key_factors": data.get("key_factors", []),
        "risk_factors": data.get("risk_factors", []),
        "data_note": str(data.get("data_note", "")),
    }


async def run_market_tone_analysis() -> dict[str, Any]:
    """시장 톤 분석을 실행하고 결과를 DB에 저장한 뒤 반환한다.

    Returns:
        {
            "ok": bool,
            "trade_date": str,
            "tone": str,
            "confidence": float,
            "summary": str,
            "provider": str,
            "id": str,
        }
    """
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    logger.info("START: MarketToneService.run trade_date=%s", today)

    _ensure_table()

    # 해외 시장 데이터를 먼저 수집하고 실패 시에도 LLM 분석 자체는 계속 진행한다.
    try:
        from .market_data_fetcher import fetch_overnight_market_summary, format_for_prompt

        market_data = await fetch_overnight_market_summary()
        market_data_text = format_for_prompt(market_data)
    except Exception as exc:
        logger.warning("WARN: MarketToneService 해외 시장 데이터 실시간 수집 실패 — %s", exc)
        # S11 overnight snapshot fallback.
        try:
            from .us_market_watch import get_latest_snapshot
            from .market_data_fetcher import format_for_prompt as _fmt

            snapshot = get_latest_snapshot()
            if snapshot and snapshot.get("raw_data") and isinstance(snapshot["raw_data"], dict):
                market_data_text = _fmt(snapshot["raw_data"])
                market_data_text += (
                    f"\n[참고: S11 스냅샷 기준 {snapshot['snapshot_date']} "
                    f"{snapshot['snapshot_time']} KST]"
                )
                logger.info(
                    "INFO: MarketToneService S11 스냅샷 폴백 적용 date=%s time=%s",
                    snapshot["snapshot_date"], snapshot["snapshot_time"],
                )
            else:
                market_data_text = "[전날 밤 해외 시장 현황]\n  데이터 수집 실패 — 가용한 정보만 기준으로 판단"
        except Exception as snap_exc:
            logger.warning("WARN: MarketToneService S11 스냅샷 폴백도 실패 — %s", snap_exc)
            market_data_text = "[전날 밤 해외 시장 현황]\n  데이터 수집 실패 — 가용한 정보만 기준으로 판단"

    # LLM 호출
    prompt = _TONE_PROMPT.replace("{date}", today).replace("{market_data}", market_data_text)
    llm_result = await llm_router.call_llm(prompt, task_name="시장 톤 분석")

    # 파싱
    if llm_result["ok"]:
        try:
            parsed = _parse_tone_response(llm_result["raw"])
        except Exception as parse_exc:
            logger.warning("WARN: MarketToneService JSON 파싱 실패 — %s", parse_exc)
            parsed = {
                "tone": "neutral",
                "confidence": 0.0,
                "summary": "LLM 응답 파싱 실패",
                "key_factors": [],
                "risk_factors": ["파싱 오류"],
                "data_note": str(parse_exc),
            }
    else:
        parsed = {
            "tone": "neutral",
            "confidence": 0.0,
            "summary": "LLM 분석 실패 — 기본값(중립) 적용",
            "key_factors": [],
            "risk_factors": ["LLM 호출 실패"],
            "data_note": llm_result.get("error", "unknown"),
        }

    # DB 저장
    record_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO market_tone_results
                (id, trade_date, tone, confidence, summary,
                 key_factors, risk_factors, raw_response, provider, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_id,
                today,
                parsed["tone"],
                parsed["confidence"],
                parsed["summary"],
                json.dumps(parsed["key_factors"], ensure_ascii=False),
                json.dumps(parsed["risk_factors"], ensure_ascii=False),
                llm_result.get("raw", ""),
                llm_result.get("provider", "none"),
                now,
            ),
        )

    result = {
        "ok": True,
        "trade_date": today,
        "tone": parsed["tone"],
        "confidence": parsed["confidence"],
        "summary": parsed["summary"],
        "key_factors": parsed["key_factors"],
        "risk_factors": parsed["risk_factors"],
        "provider": llm_result.get("provider", "none"),
        "id": record_id,
    }
    logger.info(
        "SUCCESS: MarketToneService trade_date=%s tone=%s provider=%s",
        today, parsed["tone"], llm_result.get("provider", "none"),
    )
    return result


def get_today_market_tone(trade_date: str) -> dict[str, Any] | None:
    """DB에서 특정 날짜의 시장 톤 결과를 조회한다."""
    _ensure_table()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM market_tone_results WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
            (trade_date,),
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    for field in ("key_factors", "risk_factors"):
        if isinstance(d.get(field), str):
            try:
                d[field] = json.loads(d[field])
            except Exception:
                d[field] = []
    return d
