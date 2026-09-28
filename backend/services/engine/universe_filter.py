"""유니버스 필터 서비스 (S3 — 08:15 KST).

KIS 거래량 순위 + 등락률 순위를 병렬로 가져와 1차 유니버스를 구성하고
단타 모멘텀 정량 점수로 정렬한 뒤 DB에 저장한다.

필터 기준 (Layer 1):
- 상한가/하한가 제외: 변동률 ±29% 초과 종목
- 가격 0원 종목 제외
- 거래량 0 종목 제외

점수 계산 (단타 모멘텀 — 가중 합산):
- 상승폭(등락률) 점수: 50%
- 거래량급증(전일대비 거래량증가율%) 점수: 50%
  (거래대금 trade_amount 은 소스/점수에서 제거됨)

결과는 universe_filter_results 테이블에 저장된다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
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


def _is_excluded_product(symbol: str, name: str, allow_inverse_1x: bool = False) -> bool:
    """정책상 매수 제외 상품군 여부 판단.

    Args:
        symbol: 종목 코드 (예: '005930', 'Q610087', '0198D0').
        name: 종목명.
        allow_inverse_1x: 폭락 방어 모드에서 인버스 1x(비레버리지)를 후보로 허용할지.
            True면 인버스 1x는 제외하지 않는다(2X/레버리지는 계속 제외). 하락 수익 경로.

    Returns:
        True이면 매수 후보·미진입 추적에서 모두 제외.
    """
    # 폭락 방어 모드: 인버스 1x(비레버리지)만 예외 허용 — 하락장에서 하락 수익을 낸다.
    if allow_inverse_1x:
        from .intraday_profile import is_inverse_1x_product
        if is_inverse_1x_product(name):
            return False

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
    change_items: list[dict[str, Any]] | None = None,
    decline_items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """거래량·등락률 순위를 병합하고 중복을 제거한다.

    단타 모멘텀 선정으로 전환하며 거래대금(trade_amount) 소스를 제거했다.
    소스는 거래량 순위 + 등락률 순위 2종이다.

    Args:
        volume_items: 거래량 순위 리스트(순서=순위). 항목에 volume_surge(전일대비 거래량증가율%)를 carry-through 한다.
        change_items: 등락률(상승률) 순위 리스트(순서=순위). None이면 등락률 소스 미사용.
    """
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
            # 거래대금 sanity 게이트(volume==0 AND trade_amount==0) 유지를 위해 trade_amount 키는 남기되 항상 0.
            "trade_amount": 0,
            "volume_surge": item.get("volume_surge", 0.0),
            "volume_rank": idx + 1,
            "change_rate_rank": 9999,
        }

    for idx, item in enumerate(change_items or []):
        sym = item.get("symbol", "")
        if not sym:
            continue
        if sym in merged:
            merged[sym]["change_rate_rank"] = idx + 1
            if not merged[sym].get("change_rate"):
                merged[sym]["change_rate"] = item.get("change_rate", 0.0)
        else:
            merged[sym] = {
                "symbol": sym,
                "name": item.get("name", ""),
                "price": item.get("price", 0),
                "change_rate": item.get("change_rate", 0.0),
                "volume": 0,
                "trade_amount": 0,
                "volume_surge": 0.0,
                "volume_rank": 9999,
                "change_rate_rank": idx + 1,
            }

    # 반등 트랙: 하락률 상위(급락주). 거래대금을 보존해 '거래활발 급락주'만 살아남게 하고
    # (거래없는 급락주는 sanity 게이트가 제외), source_rebound로 태깅한다. ±29% 필터는 하한가를 계속 배제.
    for idx, item in enumerate(decline_items or []):
        sym = item.get("symbol", "")
        if not sym:
            continue
        if sym in merged:
            merged[sym]["rebound_rank"] = idx + 1
            merged[sym]["source_rebound"] = True
        else:
            merged[sym] = {
                "symbol": sym,
                "name": item.get("name", ""),
                "price": item.get("price", 0),
                "change_rate": item.get("change_rate", 0.0),
                "volume": 0,
                "trade_amount": item.get("trade_amount", 0),  # 거래대금 보존 → 거래활발 급락주만 생존
                "volume_surge": 0.0,
                "volume_rank": 9999,
                "change_rate_rank": 9999,
                "rebound_rank": idx + 1,
                "source_rebound": True,
            }

    return list(merged.values())


def _apply_filters(items: list[dict[str, Any]], allow_inverse_1x: bool = False) -> list[dict[str, Any]]:
    """상한가/하한가, 가격/거래량 0 종목, 정책상 제외 상품군(ETF/ETN/인버스/레버리지)을 제거한다.

    allow_inverse_1x=True(폭락 방어 모드)면 인버스 1x는 남긴다(하락 수익 경로).
    """
    exclude_policy_products = _exclude_etf_enabled()
    # 최소 유동성 하한(거래대금 근사) — 못 팔 극저유동주 배제로 EOD 완전청산 보장("매일 강제청산").
    # 0이면 비활성. price×volume 또는 거래대금 중 큰 값 기준. 기본 1억(월요일 데이터로 튜닝 가능).
    try:
        min_liq = float(get_setting("engine.min_liquidity_krw", 100_000_000) or 0)
    except Exception:
        min_liq = 0.0
    result = []
    for item in items:
        change = abs(item.get("change_rate", 0.0))
        if change >= _CHANGE_RATE_LIMIT:
            continue
        price = item.get("price", 0) or 0
        if price <= 0:
            continue
        vol = item.get("volume", 0) or 0
        tamt = item.get("trade_amount", 0) or 0
        if vol <= 0 and tamt <= 0:
            continue
        if min_liq > 0:
            liq = max(float(price) * float(vol), float(tamt))
            if 0 < liq < min_liq:
                continue  # 극저유동 — 매수해도 EOD 청산 불가 위험, 진입 배제
        if exclude_policy_products and _is_excluded_product(item.get("symbol", ""), item.get("name", ""), allow_inverse_1x=allow_inverse_1x):
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


# 단타 모멘텀 선정: 상승폭(등락률) 50% + 거래량급증(전일대비 거래량증가율) 50%.
# 거래대금(trade) 팩터는 제거됐다. (PM: "일단 50/50" — 모든 톤 동일)
_TONE_WEIGHTS: dict[str, dict[str, float]] = {
    "positive": {"change": 0.5, "volume_surge": 0.5},
    "neutral":  {"change": 0.5, "volume_surge": 0.5},
    "negative": {"change": 0.5, "volume_surge": 0.5},
    "mixed":    {"change": 0.5, "volume_surge": 0.5},
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


def _resolve_base_weights(tone: str) -> dict[str, float]:
    """선정 base 가중치 — 엔진③ 배선(2026-08-23).

    `selection.weights_source`=settings(기본) 이면 **설정 `selection.change_weight/surge_weight`**
    를 라이브 소스로 쓴다(Engine Monitor ③에서 편집 → 선정에 즉시 반영). 기본값 0.5/0.5라
    동작 보존. 롤백=tone 이면 구 `_TONE_WEIGHTS`(톤별, 현재 전부 0.5/0.5).
    레짐별 선정(하락장=상대강도 등)은 이 설정을 레짐SET/플레이북이 조절하는 후속 inc의 토대.
    """
    try:
        src = str(get_setting("selection.weights_source", "settings") or "settings").lower()
    except Exception:
        src = "settings"
    if src == "settings":
        try:
            cw = float(get_setting("selection.change_weight", 0.5))
            sw = float(get_setting("selection.surge_weight", 0.5))
            if cw >= 0.0 and sw >= 0.0 and (cw + sw) > 0.0:
                return {"change": cw, "volume_surge": sw}
        except (TypeError, ValueError):
            pass
    return dict(_TONE_WEIGHTS.get(tone, _DEFAULT_WEIGHTS))


def _get_tone_weights(trade_date: str) -> tuple[dict[str, float], str]:
    """오늘 시장 톤(top-N용) 조회 + base 선정 가중치 반환.

    가중치는 `_resolve_base_weights`(설정 소스, 엔진③ 배선). tone은 `_TONE_TOP_N`(선정 종목수)용.
    조회 실패 시 tone="fallback".
    """
    tone = "fallback"
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT tone FROM market_tone_results WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
                (trade_date,),
            ).fetchone()
        if row is None:
            logger.warning("WARN: UniverseFilter 시장 톤 미조회 — fallback trade_date=%s", trade_date)
        else:
            tone = str(row["tone"]).lower()
    except Exception as exc:
        logger.warning("WARN: UniverseFilter 시장 톤 조회 실패 — %s fallback", exc)
        tone = "fallback"
    weights = _resolve_base_weights(tone)
    logger.info("INFO: UniverseFilter 톤=%s 선정가중치=%s", tone, weights)
    return weights, tone


def _apply_memory_adjustments(weights: dict[str, float], memories: list[dict[str, Any]]) -> dict[str, float]:
    """S3 learning memories 기반으로 유니버스 필터 점수 가중치를 미세 조정한다.

    Args:
        weights: 시장 톤으로 산출된 change/volume_surge 가중치.
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


# 거래량급증(전일대비 거래량증가율%) 정규화 분모.
# vol_inrt 단위는 퍼센트(acml_vol/prdy_vol*100). 300% = 전일 대비 3배 → 점수 1.0 포화.
_VOLUME_SURGE_SATURATION_PCT = 300.0


# ---------------------------------------------------------------------------
# 수급(외국인+기관 순매수) 기반 선정 — SHADOW 우선 (2026-09-23)
# ---------------------------------------------------------------------------
#
# 근거: KOSPI 상승은 외국인·기관 순매수(수급)가 주도. 현행 선정(거래량+등락률)은
# 수급 없는 '고거래량 laggard'를 잡아 손실. 수급 팩터를 추가하되 SHADOW(로그만)로
# 먼저 관찰 후 enforce 전환한다. 모든 값은 selection.supply_demand_* 설정에서 온다.
#
# 데이터 의미(중요): KIS inquire-investor(FHKST01010900)는 **일별 시계열**을 반환한다
# (output = 리스트, 최근 거래일 first). S3 prep(~09:01)에는 오늘 장중 누적이 0에 가깝거나
# 미형성이라, **가장 최근 '유효' 거래일(순매수 데이터가 있는 첫 행)**의 외국인+기관 순매수를
# 수급 측정치로 쓴다. 전일 강한 매집 → 오늘 지속(연속성) 가정. (아래 _extract_supply_row)
#
# 정규화: 순매수'금액'(원)을 tanh로 [-1,1]에 압축한다. 금액 기반이 거래량 기반보다
# 종목 규모/가격에 덜 휘둘린다(대형주 소량주 비교 안정). 최종 supply_score=[0,1]로 shift.
#   raw = frgn_ntby_tr_pbmn + orgn_ntby_tr_pbmn  (외국인+기관 순매수 금액, 백만원 또는 원)
#   signed = tanh(raw / SATURATION)   → [-1,1]  (양수=매집, 음수=분산)
#   supply_score = (signed + 1) / 2   → [0,1]   (기존 점수와 결합용, 0.5=중립)
# SATURATION은 '이 금액이면 강한 수급'의 스케일. KIS 금액 단위는 백만원(tr_pbmn) 관례라
# 100(억원 근처)에서 포화하도록 잡되 설정 없이 상수로 문서화한다.

# 수급 순매수 금액 포화 스케일(백만원). 설정 `selection.supply_saturation_pbmn`로 조절(캐시리스).
# 2026-09-28 실측 재보정: 기존 10,000은 너무 커서 실제 순매수 분포(-2,043~+3,084백만)가 전부
#   0.4~0.5로 뭉쳐 분리력 상실(리더 매몰). 1,500(≈15억)에서 포화하도록 낮춰 수급 강약을 실제로 벌린다.
#   (단위가 원이어도 부호/순서는 보존됨)
_SUPPLY_AMOUNT_SATURATION = 1_500.0


def _extract_supply_row(payload: dict[str, Any]) -> dict[str, Any]:
    """KIS inquire-investor 일별 시계열에서 수급 측정에 쓸 행을 고른다.

    output은 최근 거래일 first 리스트다. S3 prep(~09:01)엔 오늘 장중 누적이 0/미형성이라
    **순매수 데이터가 존재하는 가장 최근 행**(사실상 직전 완료 거래일)을 고른다.
    dict(단일 행) 응답도 안전 처리. 유효 행이 없으면 빈 dict.
    """
    output = payload.get("output") if isinstance(payload, dict) else None
    rows: list[dict[str, Any]]
    if isinstance(output, list):
        rows = [r for r in output if isinstance(r, dict)]
    elif isinstance(output, dict):
        rows = [output]
    else:
        rows = []
    for row in rows:
        frgn = _to_number(row.get("frgn_ntby_tr_pbmn"))
        orgn = _to_number(row.get("orgn_ntby_tr_pbmn"))
        if frgn is not None or orgn is not None:
            return row
    return rows[0] if rows else {}


def _to_number(value: Any) -> float | None:
    try:
        if value is None:
            return None
        text = str(value).replace(",", "").strip()
        if not text:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _compute_supply_score(investor_payload: dict[str, Any] | None,
                          saturation: float | None = None) -> dict[str, Any]:
    """외국인+기관 순매수 금액을 [0,1] supply_score로 정규화한다.

    양수 순매수(매집) → score>0.5, 음수(분산) → score<0.5, 데이터 없음/실패 → 0.5(중립).
    tanh 압축으로 극단 금액이 점수를 지배하지 않게 한다(fail-open: None→중립).

    Returns:
        {"supply_score": [0,1], "frgn_ntby_amount": .., "orgn_ntby_amount": ..,
         "supply_signed": [-1,1], "as_of": 데이터 기준일, "available": bool}
    """
    row = _extract_supply_row(investor_payload or {})
    frgn = _to_number(row.get("frgn_ntby_tr_pbmn"))
    orgn = _to_number(row.get("orgn_ntby_tr_pbmn"))
    if frgn is None and orgn is None:
        return {
            "supply_score": 0.5,
            "frgn_ntby_amount": None,
            "orgn_ntby_amount": None,
            "supply_signed": 0.0,
            "as_of": row.get("stck_bsop_date", ""),
            "available": False,
        }
    combined = (frgn or 0.0) + (orgn or 0.0)
    _sat = float(saturation) if saturation and float(saturation) > 0 else _SUPPLY_AMOUNT_SATURATION
    signed = math.tanh(combined / _sat)
    supply_score = (signed + 1.0) / 2.0
    return {
        "supply_score": round(max(0.0, min(1.0, supply_score)), 6),
        "frgn_ntby_amount": frgn,
        "orgn_ntby_amount": orgn,
        "supply_signed": round(signed, 6),
        "as_of": row.get("stck_bsop_date", ""),
        "available": True,
    }


def _resolve_supply_config() -> dict[str, Any]:
    """수급 선정 설정을 라이브로 읽는다(매 호출 반영). 실패 시 안전 기본."""
    def _num(key: str, default: float) -> float:
        try:
            return float(get_setting(key, default))
        except (TypeError, ValueError):
            return default

    mode = "shadow"
    try:
        mode = str(get_setting("selection.supply_demand_mode", "shadow") or "shadow").strip().lower()
    except Exception:
        mode = "shadow"
    if mode not in ("off", "shadow", "enforce"):
        mode = "shadow"
    weight = _num("selection.supply_demand_weight", 0.6)  # 2026-09-28 수급 1차 승격(등락률보다 우선)
    weight = max(0.0, min(1.0, weight))
    topk = int(_num("selection.supply_demand_topk", 30))
    topk = max(1, topk)
    gate_min = _num("selection.supply_demand_gate_min", -0.1)
    saturation = _num("selection.supply_saturation_pbmn", _SUPPLY_AMOUNT_SATURATION)
    return {"mode": mode, "weight": weight, "topk": topk, "gate_min": gate_min, "saturation": saturation}


def _supply_combined_score(existing_score: float, supply_score: float, weight: float) -> float:
    """기존 선정점수와 수급점수를 가중 결합한다: (1-w)*existing + w*supply."""
    return round((1.0 - weight) * float(existing_score) + weight * float(supply_score), 6)


def _rerank_by_supply(candidates: list[dict[str, Any]], weight: float) -> list[dict[str, Any]]:
    """candidates(각 supply_score 보유)를 결합점수로 재정렬하고 rank 재부여한다.

    supply_score 부재 시 0.5(중립)로 취급 → 수급 데이터 없는 종목은 기존 순위 근처 유지.
    원본 리스트는 변경하지 않고 새 리스트를 반환한다.
    """
    reranked = []
    for item in candidates:
        base = float(item.get("score", 0.0) or 0.0)
        supply = float(item.get("supply_score", 0.5) if item.get("supply_score") is not None else 0.5)
        combined = _supply_combined_score(base, supply, weight)
        reranked.append({**item, "supply_combined_score": combined})
    reranked.sort(key=lambda x: x["supply_combined_score"], reverse=True)
    for idx, item in enumerate(reranked, start=1):
        item["supply_rank"] = idx
    return reranked


def _ensure_supply_shadow_table() -> None:
    """selection_supply_shadow 테이블(수급 shadow 비교 기록)이 없으면 생성한다."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS selection_supply_shadow (
                id                       TEXT PRIMARY KEY,
                trade_date               TEXT NOT NULL,
                current_topn_json        TEXT NOT NULL DEFAULT '[]',
                supply_reranked_topn_json TEXT NOT NULL DEFAULT '[]',
                detail_json              TEXT NOT NULL DEFAULT '{}',
                created_at               TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_selection_supply_shadow_trade_date ON selection_supply_shadow(trade_date)"
        )


async def _fetch_supply_for_candidates(
    candidates: list[dict[str, Any]],
    topk: int,
    spacing_sec: float = 0.34,
    saturation: float | None = None,
) -> dict[str, dict[str, Any]]:
    """상위 topk 후보에 대해 KIS inquire-investor를 순차 조회해 supply_score를 계산한다.

    KIS rate-limit 가드: 상위 K만, 호출 간 spacing_sec 간격(≈3tps). 각 조회는 fail-open
    (실패/누락 → 중립 0.5, S3를 절대 깨뜨리지 않음). get_investor_profile는 서버 내부 KIS.

    Returns: {symbol: supply_detail_dict}
    """
    from ..kis.domestic import service as domestic_service

    out: dict[str, dict[str, Any]] = {}
    subset = candidates[: max(1, topk)]
    for idx, item in enumerate(subset):
        sym = str(item.get("symbol") or "").strip()
        if not sym:
            continue
        try:
            payload = await domestic_service.get_investor_profile(symbol=sym, market_code="J")
            out[sym] = _compute_supply_score(payload if isinstance(payload, dict) else {}, saturation)
        except Exception as exc:  # fail-open — 수급 실패가 S3를 막지 않는다
            logger.warning("WARN: UniverseFilter 수급 조회 실패 symbol=%s reason=%s (중립 처리)", sym, exc)
            out[sym] = {
                "supply_score": 0.5,
                "frgn_ntby_amount": None,
                "orgn_ntby_amount": None,
                "supply_signed": 0.0,
                "as_of": "",
                "available": False,
            }
        if spacing_sec > 0 and idx < len(subset) - 1:
            await asyncio.sleep(spacing_sec)
    return out


def _score_and_rank(items: list[dict[str, Any]], total: int, weights: dict[str, float]) -> list[dict[str, Any]]:
    """단타 모멘텀 정량 점수를 계산하고 내림차순으로 정렬한다.

    점수 = 등락률 점수 * change_w + 거래량급증 점수 * surge_w   (거래대금 항 제거)
    - change_score: change_rate_rank 있으면 순위 점수, 없으면(=9999) 등락률 정규화 (change_rate+30)/60.
    - surge_score: volume_surge(전일대비 거래량증가율%) 정규화 = min(1.0, surge/300).
                   surge 가 0/부재이면 거래량 RANK 점수로 폴백해 여전히 정렬되게 한다.
    순위 점수 = (total - rank + 1) / total  (1등이 가장 높음)
    """
    if total == 0:
        total = 1

    change_w = weights.get("change", 0.5)
    surge_w = weights.get("volume_surge", 0.5)

    scored = []
    for item in items:
        # 등락률 순위가 있으면 순위 점수, 없으면(=9999 sentinel) 등락률 정규화 점수로 폴백
        raw_change_rank = item.get("change_rate_rank", 9999)
        if raw_change_rank <= total:
            change_score = (total - raw_change_rank + 1) / total
        else:
            change_score = (item.get("change_rate", 0.0) + 30.0) / 60.0
        change_score = max(0.0, min(1.0, change_score))

        # 거래량급증 점수: vol_inrt(%) 정규화. 0/부재 시 거래량 RANK 점수로 폴백.
        surge = float(item.get("volume_surge", 0.0) or 0.0)
        if surge > 0.0:
            surge_score = min(1.0, surge / _VOLUME_SURGE_SATURATION_PCT)
        else:
            raw_volume_rank = item.get("volume_rank", total)
            surge_score = (total - raw_volume_rank + 1) / total if raw_volume_rank <= total else 0.0
        surge_score = max(0.0, min(1.0, surge_score))

        total_score = change_w * change_score + surge_w * surge_score
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

    # 반등 트랙 토글 — 급락 반등 후보(하락률 상위)를 유니버스에 편입할지. 기본 ON, 롤백 가능.
    try:
        from ..settings_store import get_setting as _gs
        _rebound_on = bool(_gs("engine.rebound_universe_enabled", True))
    except Exception:
        _rebound_on = True

    # KIS 병렬 호출 — 거래량 순위 + 상승률 순위 + (반등) 하락률 순위
    try:
        _tasks = [
            get_volume_rank(market_code="J", top_n=_MAX_UNIVERSE),
            get_price_rank(sort_by="change_rate", market_code="J", top_n=_MAX_UNIVERSE),
        ]
        if _rebound_on:
            _tasks.append(get_price_rank(sort_by="change_rate", market_code="J", top_n=_MAX_UNIVERSE, direction="down"))
        _results = await asyncio.gather(*_tasks)
        volume_items = _results[0].get("items", [])
        change_items = _results[1].get("items", [])
        decline_items = _results[2].get("items", []) if (_rebound_on and len(_results) > 2) else []
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

    raw_split_counts = {
        "volume": len(volume_items),
        "change_rate": len(change_items),
        "rebound_decline": len(decline_items),
    }
    raw_count = raw_split_counts["volume"] + raw_split_counts["change_rate"] + raw_split_counts["rebound_decline"]
    merged = _merge_and_deduplicate(volume_items, change_items, decline_items)
    if decline_items:
        _reb = [m for m in merged if m.get("source_rebound")]
        logger.info("INFO: UniverseFilter 반등 트랙 편입 후보=%d (하락률 상위∩거래활발)", len(_reb))
    rejection_counts = _count_filter_rejections(merged)

    # 폭락 방어 모드 활성 시 인버스 1x를 유니버스에 허용 — 하락장에서 하락 수익(폭락장 +1% 경로).
    # (평소엔 인버스 제외 유지. 진입 게이트는 flash_crash_defense가 인버스 1x만 허용, 예산은 crash_playbook_cap.)
    _allow_inv1x = False
    try:
        from ..settings_store import get_setting as _gs2
        if bool(_gs2("engine.crash_inverse_universe_enabled", True)) and bool(_gs2("engine.crash_playbook_enabled", True)):
            from .intraday_regime_monitor import is_flash_crash_defense_active
            _allow_inv1x = bool(is_flash_crash_defense_active(today))
    except Exception as _e:
        logger.warning("WARN: UniverseFilter 폭락방어 인버스 허용 판정 실패 — %s", _e)
        _allow_inv1x = False
    if _allow_inv1x:
        logger.info("INFO: UniverseFilter 폭락 방어 모드 — 인버스 1x 유니버스 편입 허용")

    filtered = _apply_filters(merged, allow_inverse_1x=_allow_inv1x)
    ranked = _score_and_rank(filtered, total=len(merged), weights=weights)
    top_n_count = _TONE_TOP_N.get(tone_used, _TOP_N_RESULT)

    # ── 수급(외국인+기관 순매수) 기반 선정 — SHADOW 우선 (2026-09-23) ──
    # off=현행 그대로. shadow=수급 조회+비교 로그·테이블 기록만(top_n 불변).
    # enforce=수급 결합점수로 ranked 실제 재정렬 후 top_n 선택 + 강한 순매도 게이트.
    supply_cfg = _resolve_supply_config()
    supply_diag: dict[str, Any] = {"mode": supply_cfg["mode"]}
    if supply_cfg["mode"] != "off" and ranked:
        try:
            supply_map = await _fetch_supply_for_candidates(
                ranked, topk=supply_cfg["topk"], saturation=supply_cfg.get("saturation"))
            for item in ranked:
                sym = str(item.get("symbol") or "").strip()
                detail = supply_map.get(sym)
                if detail is not None:
                    item["supply_score"] = detail.get("supply_score", 0.5)
                    item["frgn_ntby_amount"] = detail.get("frgn_ntby_amount")
                    item["orgn_ntby_amount"] = detail.get("orgn_ntby_amount")
                    item["supply_available"] = detail.get("available", False)
                    item["supply_as_of"] = detail.get("as_of", "")
            supply_diag.update({
                "weight": supply_cfg["weight"],
                "topk": supply_cfg["topk"],
                "fetched": len(supply_map),
                "available": sum(1 for d in supply_map.values() if d.get("available")),
            })
        except Exception as _sd_exc:  # fail-open — 수급 전체 실패해도 현행 선정 유지
            logger.warning("WARN: UniverseFilter 수급 단계 실패 — 현행 선정 유지 reason=%s", _sd_exc)
            supply_diag["error"] = str(_sd_exc)
            supply_cfg = {**supply_cfg, "mode": "off"}

    if supply_cfg["mode"] == "enforce":
        # 실제 재정렬: 결합점수로 ranked 재정렬. 강한 순매도(gate_min 미만)는 후보 제외.
        gate_signed_min = float(supply_cfg["gate_min"])
        gated = [
            it for it in ranked
            if float((it.get("supply_score", 0.5) if it.get("supply_score") is not None else 0.5) * 2.0 - 1.0)
            >= gate_signed_min or not it.get("supply_available", False)
        ]
        reranked = _rerank_by_supply(gated, supply_cfg["weight"])
        excluded = len(ranked) - len(gated)
        top_n = reranked[:top_n_count]
        supply_diag.update({"enforced": True, "gate_excluded": excluded, "gate_signed_min": gate_signed_min})
        logger.info(
            "INFO: UniverseFilter 수급 ENFORCE — 결합점수 재정렬(w=%.2f) gate제외=%d top_n=%d",
            supply_cfg["weight"], excluded, len(top_n),
        )
    else:
        top_n = ranked[:top_n_count]

    if supply_cfg["mode"] == "shadow":
        # SHADOW: top_n 불변. 수급 재정렬 대안 top_n을 계산해 비교만 기록한다(매매 영향 없음).
        try:
            reranked_shadow = _rerank_by_supply(ranked, supply_cfg["weight"])
            supply_shadow_topn = reranked_shadow[:top_n_count]
            _cur_syms = [it.get("symbol") for it in top_n]
            _new_syms = [it.get("symbol") for it in supply_shadow_topn]
            _cur_set, _new_set = set(_cur_syms), set(_new_syms)
            added = [s for s in _new_syms if s not in _cur_set]     # 수급 반영 시 새로 진입
            dropped = [s for s in _cur_syms if s not in _new_set]   # 수급 반영 시 탈락
            _detail_by_sym = {
                str(it.get("symbol")): {
                    "score": it.get("score"),
                    "supply_score": it.get("supply_score"),
                    "supply_combined_score": it.get("supply_combined_score"),
                    "frgn_ntby_amount": it.get("frgn_ntby_amount"),
                    "orgn_ntby_amount": it.get("orgn_ntby_amount"),
                    "supply_available": it.get("supply_available"),
                    "supply_as_of": it.get("supply_as_of"),
                }
                for it in reranked_shadow
            }
            shadow_detail = {
                "weight": supply_cfg["weight"],
                "topk": supply_cfg["topk"],
                "added_symbols": added,
                "dropped_symbols": dropped,
                "added_detail": {s: _detail_by_sym.get(str(s)) for s in added},
                "dropped_detail": {s: _detail_by_sym.get(str(s)) for s in dropped},
                "supply_stats": {
                    "fetched": supply_diag.get("fetched", 0),
                    "available": supply_diag.get("available", 0),
                },
            }
            _ensure_supply_shadow_table()
            _shadow_id = str(uuid.uuid4())
            _shadow_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            with get_connection() as _sconn:
                _sconn.execute(
                    """
                    INSERT INTO selection_supply_shadow
                        (id, trade_date, current_topn_json, supply_reranked_topn_json, detail_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _shadow_id,
                        today,
                        json.dumps(_cur_syms, ensure_ascii=False),
                        json.dumps(_new_syms, ensure_ascii=False),
                        json.dumps(shadow_detail, ensure_ascii=False),
                        _shadow_now,
                    ),
                )
            supply_diag.update({"shadow_recorded": True, "added": added, "dropped": dropped})
            logger.info(
                "INFO: UniverseFilter 수급 SHADOW — 현행 top_n 불변, 수급 재정렬 대안 기록 added=%s dropped=%s (w=%.2f)",
                added, dropped, supply_cfg["weight"],
            )
        except Exception as _sh_exc:  # fail-open — shadow 기록 실패가 선정을 막지 않는다
            logger.warning("WARN: UniverseFilter 수급 SHADOW 기록 실패 — %s (선정 영향 없음)", _sh_exc)
            supply_diag["shadow_error"] = str(_sh_exc)

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
            "change_rate": _sample_symbols(change_items),
            "merged": _sample_symbols(merged),
            "filtered": _sample_symbols(filtered),
        },
        "supply_demand": supply_diag,
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
        "supply_demand": supply_diag,
        "items": top_n,
        "id": record_id,
    }
    logger.info(
        "SUCCESS: UniverseFilter trade_date=%s tone=%s raw_volume=%d raw_change=%d raw=%d merged=%d filtered=%d top_n=%d rejections=%s samples=%s memories=%d knowledge=%d",
        today,
        tone_used,
        raw_split_counts["volume"],
        raw_split_counts["change_rate"],
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
