"""유니버스 필터 서비스 (S3 — 08:15 KST).

KIS 거래량/거래대금 순위를 병렬로 가져와 1차 유니버스를 구성하고
정량 점수로 정렬한 뒤 DB에 저장한다.

필터 기준 (Layer 1):
- 상한가/하한가 제외: 변동률 ±29% 초과 종목
- 가격 0원 종목 제외
- 거래량 0 종목 제외

점수 계산 (가중 합산):
- 거래대금 순위 점수: 50%
- 거래량 순위 점수: 30%
- 등락률 점수 (양수 선호): 20%

결과는 universe_filter_results 테이블에 저장된다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from ..db import get_connection
from ..kis.domestic.universe_service import get_price_rank, get_volume_rank
from ..settings_store import get_setting
from .expert_knowledge import get_active_knowledge
from .learning_memory import get_active_memories
from .missed_opportunity import record_missed_opportunity
from .pipeline_audit import finish_pipeline_run, normalize_trigger_source, start_pipeline_run

logger = logging.getLogger("UniverseFilterService")

_MAX_UNIVERSE = 60   # KIS에서 가져올 최대 종목 수
_TOP_N_RESULT = 30   # DB에 저장할 상위 종목 수
_CHANGE_RATE_LIMIT = 29.0  # 상한가/하한가 제외 기준

# 정책상 매수 대상에서 제외되는 상품군 식별.
# 단타 매매봇은 일반 주식의 단기 모멘텀만 거래한다 — ETF/ETN/인버스/레버리지/단일종목 파생은
# 후보군에 들어와도 매수하지 않으므로 universe 단계에서 차단한다.

# 정규 ETF 운용사 이름 prefix (6자리 코드만으로는 일반주와 구분 불가하므로 이름 기반 유지)
_ETF_NAME_PREFIXES: tuple[str, ...] = (
    "KODEX", "TIGER", "ACE", "RISE", "SOL", "KBSTAR", "HANARO", "KOSEF",
    "ARIRANG", "PLUS", "TIMEFOLIO", "TIME", "BNK", "WOORI", "KIWOOM",
    # 추가 운용사 (2026-06-01 발견: WON, 1Q, DAISHIN, MASTER, FOCUS, SMART)
    "WON", "1Q", "DAISHIN", "MASTER", "FOCUS", "SMART", "HK", "MEGA",
)

# 이름에 포함되면 정책상 제외되는 키워드.
# - "액티브": 액티브 ETF
# - "ETN": 상장지수증권 (Q-prefix 코드 외에 KIS 응답 이름에 ETN 표기되는 경우)
# - "인버스" / "Inverse": 시장 하락에 베팅하는 상품 (long-only 정책 반대)
# - "레버리지" / "Leverage": 배수 추종 상품
# - "2X", "3X", "2배", "3배": 배수 레버리지/인버스
# - "단일종목": 단일종목 선물 ETF (개별주 파생)
_EXCLUDED_NAME_KEYWORDS: tuple[str, ...] = (
    "액티브", "ETN", "인버스", "Inverse", "레버리지", "Leverage",
    "2X", "3X", "2배", "3배", "단일종목", "스팩",
)

# 종목 코드 패턴 — 코드 자체로 파생/ETN/단일종목 ETF 식별 가능한 경우.
# - Q + 6자리 숫자: KIS ETN 분류 (예: Q610087, Q700025, Q570060)
# - 4자리 숫자 + 알파벳 + 1자리: 단일종목 ETF/REITs/테마 ETF 6자리 코드
#   (예: 0103T0, 0177A0, 0174J0, 0198D0, 0193T0)
_EXCLUDED_CODE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^Q\d{6}$"),
    re.compile(r"^\d{4}[A-Z]\d$"),
)

# 우선주: 종목명이 '우' / 'N우' / '우B' / 'N우B' / '우C' 로 끝남 (예: 삼성전자우, 진흥기업2우B, 금강공업우).
# 단타봇은 보통주만 거래 — 우선주는 유동성 제한·괴리로 제외한다.
_PREFERRED_NAME_PATTERN = re.compile(r"\d*우[A-Z]?$")


def _is_excluded_product(symbol: str, name: str) -> bool:
    """정책상 매수 제외 상품군 여부 판단.

    Args:
        symbol: 종목 코드 (예: '005930', 'Q610087', '0198D0').
        name: 종목명.

    Returns:
        True이면 매수 후보·미진입 추적에서 모두 제외.
    """
    sym = str(symbol or "").strip().upper()
    if sym and any(p.match(sym) for p in _EXCLUDED_CODE_PATTERNS):
        return True

    raw = str(name or "").strip()
    if not raw:
        return False
    upper = raw.upper()
    if any(upper.startswith(prefix) for prefix in _ETF_NAME_PREFIXES):
        return True
    if any(keyword in raw for keyword in _EXCLUDED_NAME_KEYWORDS):
        return True
    if any(keyword.upper() in upper for keyword in _EXCLUDED_NAME_KEYWORDS):
        return True
    if _PREFERRED_NAME_PATTERN.search(raw):
        return True
    return False


# 하위 호환: 기존 _is_etf 호출 지점 보호 (deprecate 진행 중).
def _is_etf(name: str) -> bool:
    return _is_excluded_product("", name)


def _exclude_etf_enabled() -> bool:
    """system_settings에서 정책 제외 필터 활성 여부를 읽어 매 호출 반영한다.

    하위 호환을 위해 setting key는 engine.exclude_etf_enabled 유지하되,
    의미는 "정책 제외 상품군 전체" (ETF/ETN/인버스/레버리지/단일종목 파생) 로 확장됐다.
    """
    try:
        value = get_setting("engine.exclude_etf_enabled", True)
    except Exception as exc:
        logger.warning("WARN: UniverseFilter exclude_etf_enabled read failed reason=%s", exc)
        return True
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


# ---------------------------------------------------------------------------
# DB 초기화
# ---------------------------------------------------------------------------

def _ensure_table() -> None:
    """universe_filter_results 테이블이 없으면 생성한다."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS universe_filter_results (
                id          TEXT PRIMARY KEY,
                trade_date  TEXT NOT NULL,
                items       TEXT NOT NULL DEFAULT '[]',
                raw_count   INTEGER NOT NULL DEFAULT 0,
                filtered_count INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_universe_filter_trade_date ON universe_filter_results(trade_date)"
        )


# ---------------------------------------------------------------------------
# 내부 필터/점수 로직
# ---------------------------------------------------------------------------

def _merge_and_deduplicate(
    volume_items: list[dict[str, Any]],
    trade_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """거래량 순위와 거래대금 순위를 병합하고 중복을 제거한다."""
    merged: dict[str, dict[str, Any]] = {}

    for idx, item in enumerate(volume_items):
        sym = item.get("symbol", "")
        if not sym:
            continue
        merged[sym] = {
            "symbol": sym,
            "name": item.get("name", ""),
            "price": item.get("price", 0),
            "change_rate": item.get("change_rate", 0.0),
            "volume": item.get("volume", 0),
            "trade_amount": 0,
            "volume_rank": idx + 1,
            "trade_rank": 9999,
        }

    for idx, item in enumerate(trade_items):
        sym = item.get("symbol", "")
        if not sym:
            continue
        if sym in merged:
            merged[sym]["trade_amount"] = item.get("trade_amount", 0)
            merged[sym]["trade_rank"] = idx + 1
        else:
            merged[sym] = {
                "symbol": sym,
                "name": item.get("name", ""),
                "price": item.get("price", 0),
                "change_rate": item.get("change_rate", 0.0),
                "volume": 0,
                "trade_amount": item.get("trade_amount", 0),
                "volume_rank": 9999,
                "trade_rank": idx + 1,
            }

    return list(merged.values())


def _apply_filters(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """상한가/하한가, 가격/거래량 0 종목, 정책상 제외 상품군(ETF/ETN/인버스/레버리지)을 제거한다."""
    exclude_policy_products = _exclude_etf_enabled()
    result = []
    for item in items:
        change = abs(item.get("change_rate", 0.0))
        if change >= _CHANGE_RATE_LIMIT:
            continue
        if item.get("price", 0) <= 0:
            continue
        if item.get("volume", 0) <= 0 and item.get("trade_amount", 0) <= 0:
            continue
        if exclude_policy_products and _is_excluded_product(item.get("symbol", ""), item.get("name", "")):
            continue
        result.append(item)
    return result


def _count_filter_rejections(items: list[dict[str, Any]]) -> dict[str, int]:
    """필터 동작을 바꾸지 않고 S3 탈락 사유만 집계한다."""
    exclude_policy_products = _exclude_etf_enabled()
    counts = {
        "limit_change_rate": 0,
        "invalid_price": 0,
        "empty_liquidity": 0,
        "policy_excluded": 0,  # 기존 etf_excluded → 정책 제외 전체 (ETF/ETN/인버스/레버리지/단일종목)
    }
    for item in items:
        change = abs(item.get("change_rate", 0.0))
        if change >= _CHANGE_RATE_LIMIT:
            counts["limit_change_rate"] += 1
            continue
        if item.get("price", 0) <= 0:
            counts["invalid_price"] += 1
            continue
        if item.get("volume", 0) <= 0 and item.get("trade_amount", 0) <= 0:
            counts["empty_liquidity"] += 1
            continue
        if exclude_policy_products and _is_excluded_product(item.get("symbol", ""), item.get("name", "")):
            counts["policy_excluded"] += 1
            continue
    return counts


def _sample_symbols(items: list[dict[str, Any]], limit: int = 5) -> list[str]:
    """로그/audit에 안전하게 남길 종목 코드 샘플만 추출한다."""
    symbols: list[str] = []
    for item in items:
        symbol = str(item.get("symbol") or item.get("ticker") or "").strip()
        if symbol:
            symbols.append(symbol)
        if len(symbols) >= limit:
            break
    return symbols


def _market_data_readiness_status(merged_count: int, rejection_counts: dict[str, int]) -> str:
    """S3 후보 0개가 데이터 준비 문제인지 운영자가 볼 수 있게 분류한다."""
    if merged_count <= 0:
        return "no_ranking_rows"
    if rejection_counts.get("empty_liquidity", 0) == merged_count:
        return "liquidity_not_ready"
    if rejection_counts.get("invalid_price", 0) == merged_count:
        return "price_not_ready"
    if rejection_counts.get("limit_change_rate", 0) == merged_count:
        return "all_limit_change_rate"
    return "ready_or_mixed"


_TONE_WEIGHTS: dict[str, dict[str, float]] = {
    "positive": {"trade": 0.40, "volume": 0.40, "change": 0.20},
    "neutral":  {"trade": 0.50, "volume": 0.30, "change": 0.20},
    "negative": {"trade": 0.60, "volume": 0.30, "change": 0.10},
    "mixed":    {"trade": 0.50, "volume": 0.30, "change": 0.20},
}
_DEFAULT_WEIGHTS = _TONE_WEIGHTS["neutral"]

# 시장 톤별 상위 선정 종목 수 — 비관적 장에서는 보수적으로 줄이고 낙관적 장에서는 늘린다
_TONE_TOP_N: dict[str, int] = {
    "positive": 35,
    "neutral":  30,
    "negative": 20,
    "mixed":    25,
    "fallback": 30,
}


def _get_tone_weights(trade_date: str) -> tuple[dict[str, float], str]:
    """오늘 시장 톤을 DB에서 조회해 가중치를 반환한다.

    Returns:
        (weights_dict, tone_used)
        조회 실패 시 neutral 기본값과 "fallback" 반환.
    """
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT tone FROM market_tone_results WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
                (trade_date,),
            ).fetchone()
        if row is None:
            logger.warning("WARN: UniverseFilter 시장 톤 미조회 — neutral 기본값 사용 trade_date=%s", trade_date)
            return _DEFAULT_WEIGHTS, "fallback"
        tone = str(row["tone"]).lower()
        weights = _TONE_WEIGHTS.get(tone, _DEFAULT_WEIGHTS)
        logger.info("INFO: UniverseFilter 시장 톤=%s weights=%s", tone, weights)
        return weights, tone
    except Exception as exc:
        logger.warning("WARN: UniverseFilter 시장 톤 조회 실패 — %s neutral 기본값 사용", exc)
        return _DEFAULT_WEIGHTS, "fallback"


def _apply_memory_adjustments(weights: dict[str, float], memories: list[dict[str, Any]]) -> dict[str, float]:
    """S3 learning memories 기반으로 유니버스 필터 점수 가중치를 미세 조정한다.

    Args:
        weights: 시장 톤으로 산출된 trade/volume/change 가중치.
        memories: S3_UNIVERSE_FILTER 범위의 활성 Learning Memory 목록.
    """
    adjusted = dict(weights)
    for mem in memories:
        rec = mem.get("recommendation", {})
        if rec.get("type") == "weight_adjust":
            field = rec.get("field", "")
            delta = float(rec.get("delta", 0.0))
            if field in adjusted:
                adjusted[field] = max(0.0, min(1.0, adjusted[field] + delta))

    total = sum(adjusted.values())
    if total > 0:
        adjusted = {key: value / total for key, value in adjusted.items()}
    return adjusted


def _score_and_rank(items: list[dict[str, Any]], total: int, weights: dict[str, float]) -> list[dict[str, Any]]:
    """정량 점수를 계산하고 내림차순으로 정렬한다.

    점수 = 거래대금 순위 점수 * trade_w + 거래량 순위 점수 * volume_w + 등락률 점수 * change_w
    순위 점수 = (total - rank + 1) / total  (1등이 가장 높음)
    등락률 점수 = (change_rate + 30) / 60  (양수 선호, -30~+30 범위 정규화)
    """
    if total == 0:
        total = 1

    trade_w = weights.get("trade", 0.50)
    volume_w = weights.get("volume", 0.30)
    change_w = weights.get("change", 0.20)

    scored = []
    for item in items:
        # trade_rank가 total을 초과하면(KIS 거래대금 미수신 시 sentinel 9999) 0점 처리
        raw_trade_rank = item.get("trade_rank", total)
        trade_score = (total - raw_trade_rank + 1) / total if raw_trade_rank <= total else 0.0
        raw_volume_rank = item.get("volume_rank", total)
        volume_score = (total - raw_volume_rank + 1) / total if raw_volume_rank <= total else 0.0
        change_normalized = (item.get("change_rate", 0.0) + 30.0) / 60.0
        change_normalized = max(0.0, min(1.0, change_normalized))

        total_score = (
            trade_w * trade_score +
            volume_w * volume_score +
            change_w * change_normalized
        )
        scored.append({**item, "score": round(total_score, 4)})

    scored.sort(key=lambda x: x["score"], reverse=True)
    for idx, item in enumerate(scored, start=1):
        item["rank"] = idx

    return scored


# ---------------------------------------------------------------------------
# 공개 인터페이스
# ---------------------------------------------------------------------------

async def run_universe_filter(trigger_source: str = "api_manual") -> dict[str, Any]:
    """유니버스 필터를 실행하고 결과를 DB에 저장한 뒤 반환한다."""
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    safe_source = normalize_trigger_source(trigger_source)
    run_audit_id = start_pipeline_run(
        trade_date=today,
        step="S3",
        trigger_source=safe_source,
        display_source="manual-like-console" if safe_source == "console_manual" else safe_source,
    )
    logger.info("START: UniverseFilter.run trade_date=%s source=%s", today, safe_source)

    _ensure_table()
    memories = get_active_memories(scope="S3_UNIVERSE_FILTER")
    memory_refs = [m["memory_id"] for m in memories]
    knowledge_items = get_active_knowledge(scope="S3_UNIVERSE_FILTER")
    knowledge_refs = [k["id"] for k in knowledge_items]

    # KIS 병렬 호출
    try:
        volume_result, trade_result = await asyncio.gather(
            get_volume_rank(market_code="J", top_n=_MAX_UNIVERSE),
            get_price_rank(sort_by="trade_amount", market_code="J", top_n=_MAX_UNIVERSE),
        )
        volume_items = volume_result.get("items", [])
        trade_items = trade_result.get("items", [])
    except Exception as exc:
        finish_pipeline_run(
            run_id=run_audit_id,
            status="failed",
            message=str(exc),
            metadata={"trigger_source": safe_source},
        )
        logger.error("FAIL: UniverseFilter KIS 호출 실패 — %s", exc)
        raise

    # 시장 톤 기반 동적 가중치 결정
    weights, tone_used = _get_tone_weights(today)
    weights = _apply_memory_adjustments(weights, memories)

    raw_split_counts = {"volume": len(volume_items), "trade_amount": len(trade_items)}
    raw_count = raw_split_counts["volume"] + raw_split_counts["trade_amount"]
    merged = _merge_and_deduplicate(volume_items, trade_items)
    rejection_counts = _count_filter_rejections(merged)
    filtered = _apply_filters(merged)
    ranked = _score_and_rank(filtered, total=len(merged), weights=weights)
    top_n_count = _TONE_TOP_N.get(tone_used, _TOP_N_RESULT)
    top_n = ranked[:top_n_count]

    # 탈락 종목 Missed Opportunities 기록.
    # 정책상 절대 매수 안 하는 상품군 (ETF/ETN/인버스/레버리지/단일종목 파생) 은 학습 노이즈가 되므로
    # missed_opportunities 에 기록하지 않는다. 그 외 일반 주식의 탈락만 학습 대상.
    filtered_symbols = {item.get("symbol") for item in filtered}
    for item in merged:
        sym = item.get("symbol", "")
        if sym in filtered_symbols:
            continue
        if _is_excluded_product(sym, item.get("name", "")):
            # 정책 제외 상품군 — 처음부터 매수 후보가 아니므로 missed 기록 skip
            continue
        change = abs(item.get("change_rate", 0.0))
        if change >= _CHANGE_RATE_LIMIT:
            reason = f"S3_FILTER: 상한가/하한가 제외 change_rate={item.get('change_rate', 0):.1f}%"
        elif item.get("price", 0) <= 0:
            reason = "S3_FILTER: 가격 0원"
        else:
            reason = "S3_FILTER: 거래량/거래대금 0"
        try:
            record_missed_opportunity(
                trade_date=today,
                symbol=sym,
                symbol_name=item.get("name", ""),
                missed_stage="S3_UNIVERSE_FILTER",
                missed_reason=reason,
                price_at_missed=float(item.get("price", 0)),
                improvement_candidate=False,
            )
        except Exception as _mo_exc:
            logger.warning("WARN: UniverseFilter missed_opportunity 기록 실패 symbol=%s reason=%s", sym, _mo_exc)
    diagnostic_context = {
        "raw_split_counts": raw_split_counts,
        "raw_count": raw_count,
        "merged_count": len(merged),
        "filtered_count": len(filtered),
        "top_n": len(top_n),
        "rejection_reason_counts": rejection_counts,
        "data_readiness_status": _market_data_readiness_status(len(merged), rejection_counts),
        "sample_symbols": {
            "volume": _sample_symbols(volume_items),
            "trade_amount": _sample_symbols(trade_items),
            "merged": _sample_symbols(merged),
            "filtered": _sample_symbols(filtered),
        },
    }

    # DB 저장
    record_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO universe_filter_results
                (id, trade_date, items, raw_count, filtered_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                record_id,
                today,
                json.dumps(top_n, ensure_ascii=False),
                raw_count,
                len(filtered),
                now,
            ),
        )

    result = {
        "ok": True,
        "trade_date": today,
        "raw_count": raw_count,
        "raw_split_counts": raw_split_counts,
        "merged_count": len(merged),
        "filtered_count": len(filtered),
        "rejection_reason_counts": rejection_counts,
        "data_readiness_status": diagnostic_context["data_readiness_status"],
        "sample_symbols": diagnostic_context["sample_symbols"],
        "result_count": len(top_n),
        "tone_used": tone_used,
        "weights_used": weights,
        "memory_refs": memory_refs,
        "memory_count": len(memories),
        "knowledge_refs": knowledge_refs,
        "knowledge_count": len(knowledge_items),
        "items": top_n,
        "id": record_id,
    }
    logger.info(
        "SUCCESS: UniverseFilter trade_date=%s tone=%s raw_volume=%d raw_trade=%d raw=%d merged=%d filtered=%d top_n=%d rejections=%s samples=%s memories=%d knowledge=%d",
        today,
        tone_used,
        raw_split_counts["volume"],
        raw_split_counts["trade_amount"],
        raw_count,
        len(merged),
        len(filtered),
        len(top_n),
        rejection_counts,
        diagnostic_context["sample_symbols"],
        len(memories),
        len(knowledge_items),
    )
    finish_pipeline_run(
        run_id=run_audit_id,
        status="success",
        result_ref_id=record_id,
        message=f"raw={raw_count} filtered={len(filtered)} top_n={len(top_n)}",
        metadata={
            "tone_used": tone_used,
            "trigger_source": safe_source,
            "diagnostic_context": diagnostic_context,
        },
    )
    return result


def get_today_universe(trade_date: str) -> dict[str, Any] | None:
    """DB에서 특정 날짜의 유니버스 필터 결과를 조회한다."""
    _ensure_table()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM universe_filter_results WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
            (trade_date,),
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    if isinstance(d.get("items"), str):
        try:
            d["items"] = json.loads(d["items"])
        except Exception:
            d["items"] = []
    return d
