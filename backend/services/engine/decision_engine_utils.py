"""decision_engine 순수 파싱·숫자 유틸 (Phase 1 분해, 2026-08-22).

decision_engine.py가 진입 판정에서 쓰던 순수 함수(부작용 없음: DB·IO·전역상태 무접근)를
이 모듈로 분리한다. 로직은 원본과 100% 동일(순수 이동). decision_engine이 재-export하므로
`from ...decision_engine import _vwap_pullback_gate` 같은 기존 import는 그대로 동작한다.
"""
from __future__ import annotations

from typing import Any


def _to_float_or_none(value: Any) -> float | None:
    """숫자 변환 가능한 값만 float로 반환한다.

    Args:
        value: Candidate, tick, or rule value to parse.
    """
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _first_float(*values: Any) -> float | None:
    """여러 후보 값 중 실제 숫자로 확인 가능한 첫 값을 반환한다.

    Args:
        values: Values ordered by runtime trust priority.
    """
    for value in values:
        parsed = _to_float_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _vwap_pullback_gate(vwap: float | None, price: float | None, max_dist_pct: float) -> float | None:
    """VWAP 위 이격 진입(추격) 판정 — 눌림목 게이트.

    진입가가 VWAP보다 max_dist_pct(%) 넘게 위면 vwap_dist(%)를 반환(=차단대상),
    아니면 None(통과). VWAP·가격 미가용 시 None(fail-open, 차단 안 함).
    데이터 확증 엣지(2026-08-14 백테스트): VWAP 아래 진입 승률 51→61%·흑자.

    Args:
        vwap: 진입 시점 누적 VWAP(bar_engine). None이면 fail-open.
        price: 진입가.
        max_dist_pct: 허용 이격 상한(%). 이보다 위면 차단.
    """
    if not vwap or vwap <= 0 or not price or price <= 0:
        return None
    vwap_dist = (price / vwap - 1.0) * 100.0
    return round(vwap_dist, 2) if vwap_dist > max_dist_pct else None


def _vwap_dist_pct(vwap: float | None, price: float | None) -> float | None:
    """진입가의 VWAP 이격(%) = (price/vwap−1)×100. VWAP·가격 미가용 시 None(fail-open).

    _vwap_pullback_gate가 '천장(추격) 판정'만 하는 것과 달리, 이 함수는 순수 이격값을 돌려
    바닥(딥눌림 falling knife) 판정에도 쓴다. 2026-09-05: 진입 밴드[floor, ceiling] 양방향 게이트.
    """
    if not vwap or vwap <= 0 or not price or price <= 0:
        return None
    return round((price / vwap - 1.0) * 100.0, 2)


def _fallback_vwap_from_bars(symbol: str, today: str | None = None) -> float | None:
    """실시간 VWAP 미가용 시 폴백 VWAP — intraday_bars(10초봉) 기준 Σ(close×vol)/Σ(vol).

    bar_engine 실시간 VWAP은 재기동 시 메모리가 날아가 None이 되고(눌림목 게이트 fail-open →
    추격 진입 누수, 2026-08-29 백테스트: 추격 -0.7% 손실뿌리), intraday_bars는 장중 실시간
    적재되고 재기동에도 유지된다. 백테스트가 엣지를 검증한 동일 소스라 일관적이다. 오늘 봉이
    있으면 오늘(재기동 대비), 없으면 직전 거래일(≤today) 것을 쓴다. 데이터 없으면 None(그때만 fail-open).

    Args:
        symbol: 종목코드.
        today: 기준일(YYYY-MM-DD). None이면 KST 오늘.
    """
    try:
        from ..db import get_connection

        if today is None:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
        with get_connection() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(close*volume),0.0) AS pv, COALESCE(SUM(volume),0.0) AS v "
                "FROM intraday_bars WHERE symbol=? AND trade_date=("
                "  SELECT MAX(trade_date) FROM intraday_bars WHERE symbol=? AND trade_date<=?)",
                (symbol, symbol, today),
            ).fetchone()
        if row and row["v"] and float(row["v"]) > 0:
            return float(row["pv"]) / float(row["v"])
    except Exception:
        return None
    return None


def _day_open_from_bars(symbol: str, today: str | None = None) -> float | None:
    """오늘 시가(장 첫 봉의 open) — intraday_bars 최소 bar_ts의 open. 시가대비 추격 판정용.

    엣지(2026-09-05 BackDB 335건): 진입가/시가−1 > 임계 = 갭 추격 → 승률 33%·순 -0.95%(최악),
    VWAP 눌림과 **독립**(눌림 안에서도 시가 위 48% vs 시가 아래 69%). 우리 기존 등락률게이트는
    전일종가 대비라 이걸 못 걸렀다. VWAP 폴백과 같은 소스(재기동에도 유지). 데이터 없으면 None(fail-open).
    """
    try:
        from ..db import get_connection

        if today is None:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
        with get_connection() as conn:
            row = conn.execute(
                "SELECT open FROM intraday_bars WHERE symbol=? AND trade_date=("
                "  SELECT MAX(trade_date) FROM intraday_bars WHERE symbol=? AND trade_date<=?)"
                " AND open IS NOT NULL AND open>0 ORDER BY bar_ts LIMIT 1",
                (symbol, symbol, today),
            ).fetchone()
        if row and row["open"] and float(row["open"]) > 0:
            return float(row["open"])
    except Exception:
        return None
    return None


def _first_positive_float(*values: Any) -> float | None:
    """여러 후보 값 중 0보다 큰 첫 번째 숫자를 반환한다.

    volume_ratio처럼 0.0이 "데이터 없음"을 의미하는 필드에 사용한다.
    0.0은 건너뛰고 다음 후보를 확인한다.

    Args:
        values: Values ordered by runtime trust priority.
    """
    for value in values:
        parsed = _to_float_or_none(value)
        if parsed is not None and parsed > 0:
            return parsed
    return None


def _first_float_from_sources(
    candidate: dict[str, Any],
    tick: dict[str, Any],
    keys: tuple[str, ...],
) -> tuple[float | None, str | None]:
    """Return the first numeric indicator found in candidate or tick payloads.

    Args:
        candidate: S4/S5 candidate metadata.
        tick: Realtime tick payload.
        keys: Common indicator key names to inspect in priority order.
    """
    for source_name, payload in (("candidate", candidate), ("tick", tick)):
        for key in keys:
            parsed = _to_float_or_none(payload.get(key))
            if parsed is not None:
                return parsed, f"{source_name}.{key}"
    return None, None


def _first_value_from_sources(
    candidate: dict[str, Any],
    tick: dict[str, Any],
    keys: tuple[str, ...],
) -> tuple[Any, str | None]:
    """Return the first present indicator value found in candidate or tick payloads.

    Args:
        candidate: S4/S5 candidate metadata.
        tick: Realtime tick payload.
        keys: Common indicator key names to inspect in priority order.
    """
    for source_name, payload in (("candidate", candidate), ("tick", tick)):
        for key in keys:
            if key in payload and payload.get(key) not in (None, ""):
                return payload.get(key), f"{source_name}.{key}"
    return None, None


def _parse_bool(value: Any) -> bool | None:
    """Parse bool-like payload values without guessing from missing data.

    Args:
        value: Raw indicator value from candidate or tick payloads.
    """
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1", "yes", "y", "above", "상단", "위"):
        return True
    if text in ("false", "0", "no", "n", "below", "하단", "아래"):
        return False
    return None


def _parse_rsi_range(value: Any) -> tuple[float, float] | None:
    """Parse RSI range rules expressed as [min, max] or 'min-max'.

    Args:
        value: RulePack rsi_range field.
    """
    if isinstance(value, (list, tuple)) and len(value) == 2:
        low = _to_float_or_none(value[0])
        high = _to_float_or_none(value[1])
        if low is not None and high is not None and low < high:
            return low, high
    text = str(value or "").replace("~", "-").strip()
    if "-" in text:
        left, right = text.split("-", 1)
        low = _to_float_or_none(left)
        high = _to_float_or_none(right)
        if low is not None and high is not None and low < high:
            return low, high
    return None


def _normalize_vwap_position(value: Any) -> str | None:
    """Normalize VWAP position payloads into 'above' or 'below'.

    Args:
        value: Raw VWAP position value.
    """
    parsed_bool = _parse_bool(value)
    if parsed_bool is True:
        return "above"
    if parsed_bool is False:
        return "below"
    return None


def _spread_percent_from_source(
    value: float | None,
    source: str | None,
    price: float | None,
) -> tuple[float | None, str | None]:
    """Normalize explicit spread fields or raw KRW spread to percent.

    Args:
        value: Raw spread value from candidate or tick.
        source: Source key path returned by `_first_float_from_sources`.
        price: Current price used to convert raw KRW spread.
    """
    if value is None:
        return None, "spread_missing"
    if source and "rate" in source and abs(value) <= 1:
        return value * 100.0, None
    if source and source.endswith(".spread"):
        if price is None or price <= 0:
            return None, "spread_price_missing_for_raw_krw"
        return value / price * 100.0, None
    return value, None
