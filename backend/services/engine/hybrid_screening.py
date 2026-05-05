"""하이브리드 스크리닝 서비스 (S4 — 08:30 KST).

S3 유니버스 필터 결과(top 30)를 LLM에 넘겨 정성 적합도 점수를 받고
hybrid_screening_results 테이블에 저장한다.

뉴스 데이터는 이번 버전에서 제외한다 (S4-v2에서 추가 예정).
LLM 호출 실패 시 provider="none"으로 저장하고 서버는 계속 실행된다.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from ..db import get_connection
from .universe_filter import get_today_universe
from . import llm_router
from .expert_knowledge import build_knowledge_prompt_snippet, get_active_knowledge
from .learning_memory import get_active_memories

logger = logging.getLogger("HybridScreeningService")

_SCREENING_PROMPT_TEMPLATE = """# 08:30 Opus — 하이브리드 스크리닝 (정성 점수 부여)

## 역할
시스템이 정량 점수로 좁힌 30종목 후보를 받아, 각 종목의 **정성 적합도 점수**만 매긴다.
"매수해라"가 아니라 "이 종목은 OO 이유로 적합도 X점"이라고만 응답한다.

## 절대 규칙
- 출력은 반드시 아래 JSON 포맷
- 종목별로 매수/매도 지시 금지 (suitability_score만 부여)
- 입력에 없는 종목을 추가하지 않는다
- 점수 근거는 입력 데이터에서만 끌어온다
- 모르는 종목은 suitability_score를 0.3 이하로

## 입력 데이터

### 30종목 후보
{candidates_json}

### 시장 톤
{market_tone_json}

{memory_section}
{knowledge_section}
### 뉴스 요약
{news_summary}

## 출력 포맷 (반드시 이대로, 다른 텍스트 없이 JSON만)
{
  "schema_version": "1.0",
  "generated_at": "YYYY-MM-DDTHH:MM:SS+09:00",
  "model": "llm",
  "entry_rules": {
    "min_ai_confidence": 0.65,
    "min_price_change_pct": 1.0,
    "max_price_change_pct": 5.0,
    "entry_rule_reason": "한 문장 근거"
  },
  "candidates": [
    {
      "ticker": "005930",
      "name": "삼성전자",
      "sector": "기타",
      "suitability_score": 0.72,
      "reason": "한 문장 핵심 근거",
      "matched_themes": ["테마1"],
      "risk_factors": ["리스크1"],
      "data_source": "macro"
    }
  ],
  "skipped": [
    {"ticker": "XXXXXX", "reason": "정보 부족"}
  ],
  "overall_confidence": 0.7
}

## entry_rules 설정 기준

오늘 시장 톤을 보고 아래 기준으로 매수 진입 조건을 설정한다:

| 시장톤 | min_ai_confidence | min_price_change_pct | max_price_change_pct |
|--------|-------------------|----------------------|----------------------|
| positive | 0.60 | 0.8 | 6.0 |
| neutral  | 0.65 | 1.0 | 5.0 |
| negative | 0.72 | 1.5 | 4.0 |
| mixed    | 0.65 | 1.0 | 5.0 |

- 시장 톤 confidence < 0.4이면 모든 임계값을 보수적으로 +10% 조정
- 위 표는 참고값이며, 오늘 시장 상황에 맞게 조정 가능
- 절대 한도: min_ai_confidence는 0.40~0.85 사이만 허용
- entry_rule_reason: 왜 이 임계값을 설정했는지 한 문장

## suitability_score 기준
- 0.8~1.0: 오늘 톤/테마와 강하게 부합, 명확한 재료 있음
- 0.5~0.8: 부분적으로 부합, 일반적 매력
- 0.3~0.5: 약한 근거, 큰 매력 없음
- 0.0~0.3: 부합하지 않거나 정보 부족

시장 톤 confidence < 0.4이면 모든 suitability_score를 0.5 이하로 보수적으로 평가한다.
"""


def _ensure_table() -> None:
    """hybrid_screening_results 테이블이 없으면 생성한다."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hybrid_screening_results (
                id              TEXT PRIMARY KEY,
                trade_date      TEXT NOT NULL,
                candidates      TEXT NOT NULL DEFAULT '[]',
                skipped         TEXT NOT NULL DEFAULT '[]',
                overall_confidence REAL NOT NULL DEFAULT 0.0,
                provider        TEXT NOT NULL DEFAULT '',
                raw_input_count INTEGER NOT NULL DEFAULT 0,
                output_count    INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_hybrid_screening_trade_date ON hybrid_screening_results(trade_date)"
        )


def _build_prompt(
    candidates_30: list[dict],
    market_tone: dict | None,
    memories: list[dict] | None = None,
    knowledge_items: list[dict] | None = None,
) -> str:
    """스크리닝 프롬프트를 빌드한다.

    Args:
        candidates_30: S3에서 선별된 최대 30개 후보 종목.
        market_tone: S2 시장 톤 결과.
        memories: S4_HYBRID_SCREENING 범위의 활성 Learning Memory 목록.
        knowledge_items: S4_HYBRID_SCREENING/ALL 범위의 승인된 Expert Knowledge 목록.
    """
    if market_tone is None:
        market_tone = {"tone": "neutral", "confidence": 0.5, "summary": "데이터 없음"}

    # candidates_30에서 필요한 필드만 추출
    candidates_fields = []
    for item in candidates_30:
        candidates_fields.append({
            "symbol": item.get("symbol", ""),
            "name": item.get("name", ""),
            "price": item.get("price", 0),
            "change_rate": item.get("change_rate", 0.0),
            "trade_amount": item.get("trade_amount", 0),
            "score": item.get("score", 0.0),
            "rank": item.get("rank", 0),
        })

    candidates_json = json.dumps(candidates_fields, ensure_ascii=False, indent=2)
    market_tone_json = json.dumps(market_tone, ensure_ascii=False, indent=2)
    news_summary = "뉴스 데이터 미제공 — 이번 버전 제외"
    if memories:
        memory_lines = []
        for memory in memories:
            memory_lines.append(f"- [{memory.get('category', '?')}] {memory.get('summary', '')}")
        memory_section = "## 📌 Learning Memory (어제 복기 결과 — 반드시 반영)\n" + "\n".join(memory_lines) + "\n"
    else:
        memory_section = ""
    if knowledge_items:
        knowledge_section = build_knowledge_prompt_snippet(knowledge_items)
    else:
        knowledge_section = ""

    prompt = (
        _SCREENING_PROMPT_TEMPLATE
        .replace("{candidates_json}", candidates_json)
        .replace("{market_tone_json}", market_tone_json)
        .replace("{memory_section}", memory_section)
        .replace("{knowledge_section}", knowledge_section)
        .replace("{news_summary}", news_summary)
    )
    return prompt


def _parse_screening_response(raw: str) -> dict[str, Any]:
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

    candidates = data.get("candidates", [])
    # suitability_score 범위 강제 (0.0~1.0)
    for item in candidates:
        if "suitability_score" in item:
            item["suitability_score"] = max(0.0, min(1.0, float(item["suitability_score"])))

    return {
        "entry_rules": data.get("entry_rules", {}),
        "candidates": candidates,
        "skipped": data.get("skipped", []),
        "overall_confidence": float(data.get("overall_confidence", 0.0)),
    }


def _save_daily_rulepack_from_screening(
    trade_date: str,
    entry_rules: dict[str, Any],
    ai_source: str,
    overall_confidence: float,
) -> None:
    """S4 Opus가 생성한 entry_rules를 오늘 날짜의 활성 RulePack으로 저장한다.

    Args:
        trade_date: YYYY-MM-DD 형식의 거래일.
        entry_rules: LLM이 생성한 매수 진입 조건.
        ai_source: S4 응답을 생성한 LLM provider.
        overall_confidence: S4 전체 응답 confidence.
    """
    if not entry_rules:
        logger.info("INFO: [S4] entry_rules 없음 — RulePack 저장 생략 trade_date=%s", trade_date)
        return

    now = datetime.now(timezone.utc).isoformat()
    machine_rules = {
        "schema_version": "1.1",
        "rulepack_id": f"RP-S4-{trade_date.replace('-', '')}",
        "generated_at": now,
        "valid_for_date": trade_date,
        "ai_source": ai_source,
        "market_context": {"overall_confidence": overall_confidence},
        "entry_rules": entry_rules,
        "risk_limits": {},
        "notes": "S4 Hybrid Screening에서 자동 생성된 매수 진입 조건",
    }

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT rulepack_id FROM rulepacks WHERE trade_date = ? AND status = 'active' LIMIT 1",
            (trade_date,),
        ).fetchone()

        if existing:
            row = conn.execute(
                "SELECT machine_rules FROM rulepacks WHERE rulepack_id = ?",
                (existing["rulepack_id"],),
            ).fetchone()
            try:
                existing_rules = json.loads(row["machine_rules"] or "{}") if row else {}
            except Exception:
                existing_rules = {}
            existing_rules["entry_rules"] = entry_rules
            existing_rules["generated_at"] = now
            conn.execute(
                "UPDATE rulepacks SET machine_rules = ?, activated_at = ? WHERE rulepack_id = ?",
                (json.dumps(existing_rules, ensure_ascii=False), now, existing["rulepack_id"]),
            )
            logger.info(
                "SUCCESS: [S4] 기존 RulePack entry_rules 업데이트 rulepack_id=%s",
                existing["rulepack_id"],
            )
        else:
            rulepack_id = f"RP-S4-{trade_date.replace('-', '')}-{str(uuid.uuid4())[:6].upper()}"
            conn.execute(
                """
                INSERT INTO rulepacks
                    (rulepack_id, trade_date, mode, status, machine_rules, summary,
                     changes, validation, created_at, activated_at)
                VALUES (?, ?, 'auto', 'active', ?, ?, '', '{}', ?, ?)
                """,
                (
                    rulepack_id,
                    trade_date,
                    json.dumps(machine_rules, ensure_ascii=False),
                    f"S4 자동 생성 - min_confidence={entry_rules.get('min_ai_confidence', 0.65)}",
                    now,
                    now,
                ),
            )
            logger.info(
                "SUCCESS: [S4] 신규 RulePack 생성 rulepack_id=%s entry_rules=%s",
                rulepack_id,
                entry_rules,
            )


async def run_hybrid_screening() -> dict[str, Any]:
    """하이브리드 스크리닝을 실행하고 DB에 저장한 뒤 결과를 반환한다."""
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    logger.info("START: HybridScreeningService.run trade_date=%s", today)

    _ensure_table()
    memories = get_active_memories(scope="S4_HYBRID_SCREENING")
    memory_refs = [m["memory_id"] for m in memories]
    knowledge_items = get_active_knowledge(scope="S4_HYBRID_SCREENING")
    knowledge_refs = [k["id"] for k in knowledge_items]

    # S3 유니버스 필터 결과 조회
    universe = get_today_universe(today)
    if universe is None or not universe.get("items"):
        logger.warning("WARN: HybridScreening S3 결과 없음 — 스크리닝 생략 trade_date=%s", today)
        record_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        with get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO hybrid_screening_results
                    (id, trade_date, candidates, skipped, overall_confidence,
                     provider, raw_input_count, output_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (record_id, today, "[]", "[]", 0.0, "none", 0, 0, now),
            )
        # S3 결과가 없으면 이전 후보 종목 기반 실시간 구독도 함께 정리한다.
        try:
            from ..kis.realtime_ws import realtime_ws_manager

            await realtime_ws_manager.stop()
            logger.info("INFO: HybridScreening S3 결과 없음 — KIS WebSocket 구독 중지")
        except Exception as ws_exc:
            logger.warning("WARN: HybridScreening KIS WebSocket 중지 실패 — %s", ws_exc)
        return {
            "ok": True,
            "trade_date": today,
            "provider": "none",
            "raw_input_count": 0,
            "output_count": 0,
            "overall_confidence": 0.0,
            "candidates": [],
            "skipped": [],
            "skipped_reason": "no_universe",
            "memory_refs": memory_refs,
            "memory_count": len(memories),
            "knowledge_refs": knowledge_refs,
            "knowledge_count": len(knowledge_items),
            "id": record_id,
        }

    items = universe["items"][:30]

    # 시장 톤 조회
    market_tone = None
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT tone, confidence, summary FROM market_tone_results WHERE trade_date=? ORDER BY created_at DESC LIMIT 1",
                (today,),
            ).fetchone()
        if row is not None:
            market_tone = dict(row)
    except Exception as exc:
        logger.warning("WARN: HybridScreening 시장 톤 조회 실패 — %s", exc)

    # 프롬프트 빌드 및 LLM 호출
    prompt = _build_prompt(items, market_tone, memories=memories, knowledge_items=knowledge_items)
    llm_result = await llm_router.call_llm(prompt, task_name="하이브리드 스크리닝")

    # LLM 응답 파싱
    candidates: list = []
    skipped: list = []
    entry_rules: dict[str, Any] = {}
    overall_confidence = 0.0

    if llm_result["ok"]:
        try:
            parsed = _parse_screening_response(llm_result["raw"])
            candidates = parsed["candidates"]
            skipped = parsed["skipped"]
            parsed_entry_rules = parsed.get("entry_rules", {})
            if isinstance(parsed_entry_rules, dict):
                entry_rules = parsed_entry_rules
            overall_confidence = parsed["overall_confidence"]
        except Exception as parse_exc:
            logger.warning(
                "WARN: HybridScreening JSON 파싱 실패 — %s | raw_preview=%s",
                parse_exc,
                llm_result.get("raw", "")[:200],
            )

    provider = llm_result.get("provider", "none")

    # DB 저장
    record_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO hybrid_screening_results
                (id, trade_date, candidates, skipped, overall_confidence,
                 provider, raw_input_count, output_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_id,
                today,
                json.dumps(candidates, ensure_ascii=False),
                json.dumps(skipped, ensure_ascii=False),
                overall_confidence,
                provider,
                len(items),
                len(candidates),
                now,
            ),
        )

    if entry_rules:
        _save_daily_rulepack_from_screening(
            trade_date=today,
            entry_rules=entry_rules,
            ai_source=provider,
            overall_confidence=overall_confidence,
        )

    result = {
        "ok": True,
        "trade_date": today,
        "provider": provider,
        "raw_input_count": len(items),
        "output_count": len(candidates),
        "overall_confidence": overall_confidence,
        "entry_rules": entry_rules,
        "candidates": candidates,
        "skipped": skipped,
        "memory_refs": memory_refs,
        "memory_count": len(memories),
        "knowledge_refs": knowledge_refs,
        "knowledge_count": len(knowledge_items),
        "id": record_id,
    }
    logger.info(
        "SUCCESS: HybridScreeningService trade_date=%s output=%d provider=%s confidence=%.2f memories=%d knowledge=%d",
        today, len(candidates), provider, overall_confidence, len(memories), len(knowledge_items),
    )

    # S4 완료 후 후보 종목을 KIS WebSocket에 자동 구독해 실시간 체결 데이터를 수집한다.
    try:
        from ..kis.realtime_ws import realtime_ws_manager

        tickers = [c["ticker"] for c in candidates if c.get("ticker")]
        if tickers:
            await realtime_ws_manager.start(symbols=tickers)
            logger.info(
                "SUCCESS: HybridScreening KIS WebSocket 구독 시작 symbols=%s count=%d",
                tickers,
                len(tickers),
            )
        else:
            logger.warning("WARN: HybridScreening 후보 종목 없음 — KIS WebSocket 구독 생략")
    except Exception as ws_exc:
        logger.warning("WARN: HybridScreening KIS WebSocket 시작 실패 — %s", ws_exc)
    return result


def get_today_screening(trade_date: str) -> dict[str, Any] | None:
    """DB에서 특정 날짜의 하이브리드 스크리닝 결과를 조회한다."""
    _ensure_table()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM hybrid_screening_results WHERE trade_date=? ORDER BY created_at DESC LIMIT 1",
            (trade_date,),
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    for field in ("candidates", "skipped"):
        if isinstance(d.get(field), str):
            try:
                d[field] = json.loads(d[field])
            except Exception:
                d[field] = []
    return d
