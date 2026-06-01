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
from .missed_opportunity import record_missed_opportunity
from .pipeline_audit import finish_pipeline_run, normalize_trigger_source, start_pipeline_run
from .prompt_loader import render_prompt

logger = logging.getLogger("HybridScreeningService")

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


async def _fetch_news_summary(candidates: list[dict[str, Any]], max_symbols: int = 5) -> str:
    """상위 N개 종목의 KIS 뉴스 헤드라인을 수집해 LLM 프롬프트용 텍스트로 반환한다.

    Args:
        candidates: S3 후보 종목 목록 (rank 기준 정렬 상태 가정).
        max_symbols: 뉴스를 조회할 최대 종목 수 (KIS rate limit 고려).
    """
    from ..kis.domestic.service import get_news_title
    import asyncio
    from datetime import datetime
    from zoneinfo import ZoneInfo

    today_str = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")
    lines: list[str] = []
    top = candidates[:max_symbols]

    for item in top:
        symbol = str(item.get("symbol") or "")
        name = str(item.get("name") or symbol)
        if not symbol:
            continue
        try:
            await asyncio.sleep(0.07)  # KIS rate limit 여유
            result = await get_news_title(symbol=symbol, date_yyyymmdd=today_str)
            news_items = result.get("output") or []
            if isinstance(news_items, list) and news_items:
                headlines = [str(n.get("news_ttl") or "") for n in news_items[:2] if n.get("news_ttl")]
                if headlines:
                    lines.append(f"[{name}({symbol})] " + " / ".join(headlines))
        except Exception as exc:
            logger.debug("DEBUG: news_fetch failed symbol=%s reason=%s", symbol, exc)

    if not lines:
        return "뉴스 헤드라인 수집 실패 또는 해당 종목 뉴스 없음"
    return "\n".join(lines)


def _build_prompt(
    candidates_30: list[dict[str, Any]],
    market_tone: dict[str, Any] | None,
    morning_context: dict[str, Any] | None = None,
    memories: list[dict[str, Any]] | None = None,
    knowledge_items: list[dict[str, Any]] | None = None,
    news_summary: str | None = None,
) -> str:
    """스크리닝 프롬프트를 빌드한다.

    Args:
        candidates_30: S3에서 선별된 최대 30개 후보 종목.
        market_tone: S2 시장 톤 결과.
        morning_context: S2 시장 수치와 구조화 판단 결과.
        memories: S4_HYBRID_SCREENING 범위의 활성 Learning Memory 목록.
        knowledge_items: S4_HYBRID_SCREENING/ALL 범위의 승인된 Expert Knowledge 목록.
    """
    if market_tone is None:
        market_tone = {"tone": "neutral", "confidence": 0.5, "summary": "데이터 없음"}

    # candidates_30에서 필요한 필드만 추출 (volume_rank/trade_rank 포함 — LLM 점수 근거 제공)
    candidates_fields = []
    for item in candidates_30:
        entry: dict[str, Any] = {
            "symbol": item.get("symbol", ""),
            "name": item.get("name", ""),
            "price": item.get("price", 0),
            "change_rate": item.get("change_rate", 0.0),
            "trade_amount": item.get("trade_amount", 0),
            "volume_rank": item.get("volume_rank"),   # 거래량 순위 (숫자 낮을수록 상위)
            "trade_rank": item.get("trade_rank"),     # 거래대금 순위 (9999=미수신)
            "score": item.get("score", 0.0),
            "rank": item.get("rank", 0),
        }
        # 미수신 sentinel 제거 — LLM이 오해하지 않도록
        if entry["trade_rank"] is not None and entry["trade_rank"] > 100:
            entry["trade_rank"] = None
        candidates_fields.append(entry)

    candidates_json = json.dumps(candidates_fields, ensure_ascii=False, indent=2)
    market_tone_json = json.dumps(market_tone, ensure_ascii=False, indent=2)
    morning_context = morning_context or {}
    morning_context_json = json.dumps(
        {
            "regime": morning_context.get("regime", "neutral"),
            "risk_level": morning_context.get("risk_level", "normal"),
            "stock_character": morning_context.get("stock_character", ""),
            "rulepack_hint": morning_context.get("rulepack_hint", ""),
            "key_factors": morning_context.get("key_factors", []),
            "risk_factors": morning_context.get("risk_factors", []),
        },
        ensure_ascii=False,
        indent=2,
    )
    news_summary = news_summary or "뉴스 데이터 미제공"
    if memories:
        memory_lines = []
        for memory in memories:
            memory_lines.append(f"- [{memory.get('category', '?')}] {memory.get('summary', '')}")
        memory_section = "## 운영 메모리/RAG 참고사항 (전일 복기에서 구조화됨)\n" + "\n".join(memory_lines) + "\n"
    else:
        memory_section = ""
    if knowledge_items:
        knowledge_section = build_knowledge_prompt_snippet(knowledge_items)
    else:
        knowledge_section = ""

    prompt = render_prompt(
        "0830_opus_screening.md",
        {
            "candidates_json": candidates_json,
            "market_tone_json": market_tone_json,
            "morning_context_json": morning_context_json,
            "memory_section": memory_section,
            "knowledge_section": knowledge_section,
            "news_summary": news_summary,
        },
    )
    return prompt


def _build_universe_context(universe: dict[str, Any] | None) -> dict[str, Any]:
    """S4 no_universe 원인 분석에 필요한 S3 결과 요약만 안전하게 만든다."""
    items = universe.get("items", []) if universe else []
    if not isinstance(items, list):
        items = []
    return {
        "universe_present": universe is not None,
        "raw_count": int(universe.get("raw_count") or 0) if universe else 0,
        "filtered_count": int(universe.get("filtered_count") or 0) if universe else 0,
        "items_count": len(items),
    }


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


def _load_trading_cost_threshold() -> float:
    """system_settings에서 거래 비용 기반 최소 순수익률(%)을 반환한다.

    trading.min_net_return_pct == 0 이면 수수료×2 + 거래세로 자동 계산.
    반환값: 퍼센트 단위 (예: 0.35 → 0.35%)
    """
    try:
        with get_connection() as conn:
            def _setting(key: str, default: float) -> float:
                row = conn.execute("SELECT value_json FROM system_settings WHERE key=?", (key,)).fetchone()
                return float(json.loads(row["value_json"]) or default) if row else default

            min_net = _setting("trading.min_net_return_pct", 0.0)
            if min_net > 0:
                return min_net
            commission = _setting("trading.commission_rate", 0.015)
            tax = _setting("trading.transaction_tax_rate", 0.20)
            return commission * 2 + tax          # 왕복 수수료 + 거래세 (%)
    except Exception:
        return 0.015 * 2 + 0.20                  # 기본값: 0.23%


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


async def run_hybrid_screening(trigger_source: str = "api_manual") -> dict[str, Any]:
    """하이브리드 스크리닝을 실행하고 DB에 저장한 뒤 결과를 반환한다."""
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    safe_source = normalize_trigger_source(trigger_source)
    run_audit_id = start_pipeline_run(
        trade_date=today,
        step="S4",
        trigger_source=safe_source,
        display_source="manual-like-console" if safe_source == "console_manual" else safe_source,
    )
    logger.info("START: HybridScreeningService.run trade_date=%s source=%s", today, safe_source)

    try:
        _ensure_table()
        memories = get_active_memories(scope="S4_HYBRID_SCREENING")
        memory_refs = [m["memory_id"] for m in memories]
        knowledge_items = get_active_knowledge(scope="S4_HYBRID_SCREENING")
        knowledge_refs = [k["id"] for k in knowledge_items]
    except Exception as exc:
        finish_pipeline_run(
            run_id=run_audit_id,
            status="failed",
            message=f"startup_load_failed: {exc}",
            metadata={"trigger_source": safe_source},
        )
        logger.error("FAIL: HybridScreeningService startup load failed trade_date=%s reason=%s", today, exc)
        raise

    # S3 유니버스 필터 결과 조회
    universe = get_today_universe(today)
    if universe is None or not universe.get("items"):
        universe_context = _build_universe_context(universe)
        logger.warning(
            "WARN: HybridScreening S3 결과 없음 — 스크리닝 생략 trade_date=%s universe_present=%s raw_count=%d filtered_count=%d items_count=%d",
            today,
            universe_context["universe_present"],
            universe_context["raw_count"],
            universe_context["filtered_count"],
            universe_context["items_count"],
        )
        record_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        try:
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
        except Exception as exc:
            finish_pipeline_run(
                run_id=run_audit_id,
                status="failed",
                result_ref_id=record_id,
                message=f"save_failed: {exc}",
                metadata={"trigger_source": safe_source, "universe_context": universe_context},
            )
            logger.error("FAIL: HybridScreeningService no-universe save failed trade_date=%s reason=%s", today, exc)
            raise
        # S3 결과가 없으면 이전 후보 종목 기반 실시간 구독도 함께 정리한다.
        try:
            from ..kis.realtime_ws import realtime_ws_manager

            await realtime_ws_manager.stop()
            logger.info("INFO: HybridScreening S3 결과 없음 — KIS WebSocket 구독 중지")
        except Exception as ws_exc:
            logger.warning("WARN: HybridScreening KIS WebSocket 중지 실패 — %s", ws_exc)
        finish_pipeline_run(
            run_id=run_audit_id,
            status="skipped",
            result_ref_id=record_id,
            message="no_universe",
            metadata={
                "trigger_source": safe_source,
                "universe_context": universe_context,
                "memory_count": len(memories),
                "knowledge_count": len(knowledge_items),
            },
        )
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
    morning_context = {}
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

    try:
        from .market_tone import get_today_morning_context

        morning_context = get_today_morning_context(today) or {}
    except Exception as exc:
        logger.warning("WARN: HybridScreening morning_context 조회 실패 — %s", exc)

    # 뉴스 헤드라인 수집 (상위 5종목, 실패해도 스크리닝 계속 진행)
    news_summary: str | None = None
    try:
        news_summary = await _fetch_news_summary(items, max_symbols=5)
        logger.info("INFO: HybridScreening 뉴스 수집 완료 lines=%d", news_summary.count("\n") + 1 if news_summary else 0)
    except Exception as exc:
        logger.warning("WARN: HybridScreening 뉴스 수집 실패 (스크리닝 계속) reason=%s", exc)

    # 프롬프트 빌드 및 LLM 호출
    try:
        prompt = _build_prompt(
            items,
            market_tone,
            morning_context=morning_context,
            memories=memories,
            knowledge_items=knowledge_items,
            news_summary=news_summary,
        )
    except Exception as exc:
        finish_pipeline_run(
            run_id=run_audit_id,
            status="failed",
            message=f"prompt_render_failed: {exc}",
            metadata={"trigger_source": safe_source},
        )
        logger.error("FAIL: HybridScreeningService prompt render failed trade_date=%s reason=%s", today, exc)
        raise
    try:
        llm_result = await llm_router.call_llm(prompt, task_name="하이브리드 스크리닝")
    except Exception as exc:
        finish_pipeline_run(
            run_id=run_audit_id,
            status="failed",
            message=str(exc),
            metadata={"trigger_source": safe_source},
        )
        logger.error("FAIL: HybridScreeningService LLM call exception trade_date=%s reason=%s", today, exc)
        raise

    # LLM 응답 파싱
    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
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

    # 거래 비용 기반 하드 필터: 예상 수익률이 비용 합계에 못 미치는 후보 제거
    cost_threshold_pct = _load_trading_cost_threshold()
    if candidates and cost_threshold_pct > 0:
        cost_passed: list[dict[str, Any]] = []
        cost_filtered: list[dict[str, Any]] = []
        for cand in candidates:
            expected_return = float(cand.get("expected_return_pct") or cand.get("target_return_pct") or 0.0)
            if expected_return > 0 and expected_return < cost_threshold_pct:
                cost_filtered.append(cand)
                skipped.append({
                    **cand,
                    "reason": f"예상 수익률 {expected_return:.2f}% < 거래 비용 {cost_threshold_pct:.2f}% — 비용 회수 불가",
                })
                logger.info(
                    "INFO: HybridScreening 비용 필터 제거 symbol=%s expected_return=%.2f%% cost_threshold=%.2f%%",
                    cand.get("symbol"), expected_return, cost_threshold_pct,
                )
            else:
                # expected_return == 0 은 LLM이 수익률을 제공하지 않은 경우 — 필터 통과
                cost_passed.append(cand)
        if cost_filtered:
            logger.info(
                "INFO: HybridScreening 비용 필터 결과 before=%d after=%d filtered=%d threshold=%.2f%%",
                len(candidates), len(cost_passed), len(cost_filtered), cost_threshold_pct,
            )
        candidates = cost_passed

    # DB 저장
    record_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    try:
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
    except Exception as exc:
        finish_pipeline_run(
            run_id=run_audit_id,
            status="failed",
            result_ref_id=record_id,
            message=f"save_failed: {exc}",
            metadata={"trigger_source": safe_source},
        )
        logger.error("FAIL: HybridScreeningService save failed trade_date=%s reason=%s", today, exc)
        raise

    if entry_rules:
        _save_daily_rulepack_from_screening(
            trade_date=today,
            entry_rules=entry_rules,
            ai_source=provider,
            overall_confidence=overall_confidence,
        )

    # S4 탈락 종목 Missed Opportunities 기록.
    # 정책 제외 상품군 (ETF/ETN/인버스/레버리지/단일종목 파생) 은 S3에서 차단되어야 하지만
    # 누수 방지를 위해 S4에서도 동일 가드를 둔다.
    from .universe_filter import _is_excluded_product

    candidate_symbols = {c.get("symbol") or c.get("ticker") for c in candidates}
    # skipped 리스트에 있는 종목은 LLM이 명시적으로 제외한 것
    for sk in skipped:
        sym = sk.get("symbol") or sk.get("ticker") or ""
        if not sym:
            continue
        # 원본 S3 데이터에서 가격 찾기
        orig = next((i for i in items if i.get("symbol") == sym), {})
        if _is_excluded_product(sym, sk.get("name") or orig.get("name", "")):
            continue
        try:
            record_missed_opportunity(
                trade_date=today,
                symbol=sym,
                symbol_name=sk.get("name") or orig.get("name", ""),
                missed_stage="S4_HYBRID_SCREENING",
                missed_reason=f"S4_SCREENING: {sk.get('reason') or sk.get('skip_reason') or 'LLM 제외'}",
                price_at_missed=float(orig.get("price", 0)),
                improvement_candidate=False,
            )
        except Exception as _mo_exc:
            logger.warning("WARN: HybridScreening missed_opportunity 기록 실패 symbol=%s reason=%s", sym, _mo_exc)
    # items 중 candidates에도 skipped에도 없는 종목 (LLM 응답 누락)
    skipped_symbols = {sk.get("symbol") or sk.get("ticker") for sk in skipped}
    for orig in items:
        sym = orig.get("symbol", "")
        if sym in candidate_symbols or sym in skipped_symbols:
            continue
        if _is_excluded_product(sym, orig.get("name", "")):
            continue
        try:
            record_missed_opportunity(
                trade_date=today,
                symbol=sym,
                symbol_name=orig.get("name", ""),
                missed_stage="S4_HYBRID_SCREENING",
                missed_reason="S4_SCREENING: LLM 응답 미포함",
                price_at_missed=float(orig.get("price", 0)),
                improvement_candidate=False,
            )
        except Exception as _mo_exc:
            logger.warning("WARN: HybridScreening missed_opportunity 기록 실패 symbol=%s reason=%s", sym, _mo_exc)

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
    finish_pipeline_run(
        run_id=run_audit_id,
        status="success",
        result_ref_id=record_id,
        message=f"output={len(candidates)} provider={provider}",
        metadata={"provider": provider, "trigger_source": safe_source},
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
