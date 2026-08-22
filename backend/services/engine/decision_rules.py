"""decision_engine S6 룰 평가·시장맥락 조립 (Phase 5 분해, 2026-08-22).

_build_market_context: 태깅용 시장맥락 dict를 daily_context_snapshot/market_tone_results에서 조립.
_evaluate_rules: S6 진입 룰(confidence 게이트·가격밴드·거래량·시간창·TSI·Layer3) 평가.

원래 DecisionEngine의 메서드(둘 다 self 미사용)를 자유함수로 분리했다. 로직 100% 동일(순수 이동).
DecisionEngine은 얇은 위임 메서드로 이 함수들을 호출해 기존 인터페이스(engine._evaluate_rules)를
보존한다. decision_engine에 잔류하는 헬퍼(_get_setting_*·_current_regime_label)는 함수-지역
지연 import로 참조한다 — 순환참조를 피하고, 테스트의 de.<helper> monkeypatch가 호출 시점에 반영되게.
로거명 'DecisionEngine' 유지.
"""
from __future__ import annotations

import logging
from typing import Any

from ..db import get_connection
from .decision_context import _now_kst
from .decision_engine_utils import _first_float, _first_positive_float, _to_float_or_none
from .decision_entry_gate import _add_layer3_evaluation
from .decision_position_sync import _candidate_confidence

logger = logging.getLogger("DecisionEngine")


def _build_market_context(today: str) -> dict[str, Any]:
    """태깅용 시장맥락 dict 를 daily_context_snapshot / market_tone_results 에서 조립한다.

    Args:
        today: YYYY-MM-DD 거래일.
    """
    regime = "neutral"
    market_tone = "neutral"
    vix: float | None = None
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT regime FROM daily_context_snapshot WHERE trade_date = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (today,),
            ).fetchone()
            if row and row["regime"]:
                regime = str(row["regime"])
            tone_row = conn.execute(
                "SELECT tone FROM market_tone_results WHERE trade_date = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (today,),
            ).fetchone()
            if tone_row and tone_row["tone"]:
                market_tone = str(tone_row["tone"])
    except Exception as exc:
        logger.warning("WARN: [S6/탐색] market_context 조회 실패 reason=%s", exc)
    return {
        "regime": regime,
        "market_tone": market_tone,
        "time_bucket": _now_kst().strftime("%H:%M"),
        "vix": vix,
    }


def _evaluate_rules(
    *,
    candidate: dict[str, Any],
    final_rule: dict[str, Any],
    tick: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate currently supported S6 entry rules and record unavailable Layer3 checks.

    Args:
        candidate: S4 candidate metadata for the symbol.
        final_rule: Resolved final rule from rule_cache.
        tick: Parsed realtime tick payload.
    """
    # decision_engine 잔류 헬퍼는 지연 import — 순환 회피 + de.<helper> monkeypatch 호출시점 반영.
    from .decision_engine import (
        _current_regime_label,
        _get_setting_bool,
        _get_setting_float,
        _get_setting_str,
    )

    # confidence 임계값: 최종 룰, legacy 키, system_settings 순서로 조회한다.
    ai_conf_min = float(
        final_rule.get("min_ai_confidence")
        or final_rule.get("ai_confidence_min")
        or _get_setting_float("engine.min_ai_confidence", 0.60)
    )
    ai_conf = _candidate_confidence(candidate)

    # RulePack entry_rules의 가격 등락률 조건을 평가한다.
    price_min_pct = float(final_rule.get("min_price_change_pct", 0.0) or 0.0)
    price_max_pct = float(final_rule.get("max_price_change_pct", 999.0) or 999.0)

    # AI가 생성한 진입 임계값에 Settings 가드레일을 적용한다.
    floor = _get_setting_float("engine.min_confidence_floor", 0.40)
    ai_conf_min = max(ai_conf_min, floor)

    # P2-3(Phase 2): 방어 레짐(risk_off/volatile)에서는 confidence 하한을 가산하고
    # 게이트로 강제한다. 평시(neutral/risk_on)는 탐색 철학대로 관찰용 유지.
    # engine.confidence_gate_mode: off | regime_defensive(기본) | always
    conf_gate_mode = _get_setting_str("engine.confidence_gate_mode", "regime_defensive")
    regime_label = _current_regime_label() if conf_gate_mode != "off" else ""
    defensive_regime = regime_label in ("risk_off", "volatile")
    if defensive_regime:
        if regime_label == "risk_off":
            bonus = _get_setting_float("engine.regime_confidence_bonus_risk_off", 0.05)
        else:
            bonus = _get_setting_float("engine.regime_confidence_bonus_volatile", 0.10)
        if bonus > 0:
            ai_conf_min = min(ai_conf_min + bonus, 0.95)
    enforce_confidence = conf_gate_mode == "always" or (
        conf_gate_mode == "regime_defensive" and defensive_regime
    )
    if enforce_confidence and ai_conf < ai_conf_min:
        return {
            "pass": False,
            "reason": (
                f"confidence 미달 (레짐 {regime_label or 'n/a'}: "
                f"{ai_conf:.2f} < {ai_conf_min:.2f})"
            ),
            "matched": {"ai_confidence": False},
            "observed_values": {
                "ai_confidence": ai_conf,
                "ai_confidence_min": ai_conf_min,
                "regime": regime_label,
                "confidence_gate_mode": conf_gate_mode,
            },
        }
    price_floor = _get_setting_float("engine.min_price_change_pct", 1.5)
    price_ceil = _get_setting_float("engine.max_price_change_pct", 8.0)
    # 가드레일이 스스로 역전(floor>ceil)돼 있으면 무시 — 잘못 튜닝된 설정이 진입을 영구차단하지 못하게.
    if price_floor > price_ceil:
        logger.warning(
            "WARN: [S6] 가격밴드 가드레일 역전 floor=%.2f > ceil=%.2f — 가드레일 무시",
            price_floor, price_ceil,
        )
        price_floor, price_ceil = 0.0, 999.0
    _band_min = max(price_min_pct, price_floor)
    _band_max = min(price_max_pct, price_ceil)
    # 가드레일∩RulePack 밴드가 공집합(min>=max)이면 진입이 수학적으로 불가능해진다.
    # (예: auto-tuner가 min_price_change_pct=8.0으로 래칫 → RulePack max=5.0과 충돌 → [8.0,5.0])
    # 이 경우 RulePack 원본 밴드로, 그것도 무효면 안전 기본값으로 폴백하고 경고를 남긴다.
    # 롤백: engine.band_inversion_guard_enabled=false 로 가드 비활성(구동작 유지).
    if _band_min >= _band_max and _get_setting_bool("engine.band_inversion_guard_enabled", True):
        if price_min_pct < price_max_pct:
            _band_min, _band_max = price_min_pct, price_max_pct
            _fallback = "RulePack 원본 밴드"
        else:
            _band_min, _band_max = 1.5, 12.0
            _fallback = "안전 기본값[1.5,12.0]"
        logger.warning(
            "WARN: [S6] 진입 가격밴드 역전 — 가드레일[%.2f,%.2f]∩RulePack[%.2f,%.2f] 공집합 → %s 폴백",
            price_floor, price_ceil, price_min_pct, price_max_pct, _fallback,
        )
    price_min_pct, price_max_pct = _band_min, _band_max

    change_rate = _first_float(
        tick.get("change_rate"),
        tick.get("prdy_ctrt"),
        candidate.get("change_rate"),
        candidate.get("chg_rate"),
    )
    price_ok = (
        price_min_pct <= change_rate <= price_max_pct
        if change_rate is not None
        else False
    )

    parsed_volume_ratio_min = _first_float(final_rule.get("volume_ratio_min"))
    volume_ratio_min = parsed_volume_ratio_min if parsed_volume_ratio_min is not None else 1.0
    vol_floor = _get_setting_float("engine.min_volume_ratio", 1.0)
    volume_ratio_min = max(volume_ratio_min, vol_floor)

    entry_start_str = _get_setting_str("engine.entry_start_time", "09:00")
    entry_end_str = _get_setting_str("engine.entry_end_time", "10:30")
    now_hhmm = _now_kst().strftime("%H:%M")
    time_window_ok = entry_start_str <= now_hhmm <= entry_end_str
    if not time_window_ok:
        return {
            "pass": False,
            "reason": f"진입 시간 창 외 ({now_hhmm}, 허용: {entry_start_str}~{entry_end_str})",
            "matched": {"time_window": False},
            "observed_values": {
                "now_hhmm": now_hhmm,
                "entry_start": entry_start_str,
                "entry_end": entry_end_str,
            },
        }

    # _first_positive_float: 0.0은 "데이터 없음"으로 건너뛰고 양수 값만 사용
    # candidate의 정적 volume_ratio가 0이면 tick의 실시간 prev_volume_ratio를 확인
    volume_ratio = _first_positive_float(
        tick.get("prev_volume_ratio"),
        tick.get("prdy_vol_vrss_acml_vol_rate"),
        tick.get("volume_ratio"),
        candidate.get("volume_ratio"),
        candidate.get("vol_ratio"),
        candidate.get("volume_ratio_20d"),
    )
    volume_ok = volume_ratio >= volume_ratio_min if volume_ratio is not None else False

    unavailable_conditions: dict[str, Any] = {}
    if change_rate is None and price_min_pct > 0:
        unavailable_conditions["price_change"] = {
            "reason": "change_rate_missing",
            "required": {"min_pct": price_min_pct, "max_pct": price_max_pct},
        }
    if volume_ratio is None and volume_ratio_min > 1.0:
        unavailable_conditions["volume_ratio"] = {
            "reason": "volume_ratio_missing",
            "required": {"min": volume_ratio_min},
        }

    # TSI 추세 필터: 상승추세(tsi>0)만 매수. 데이터 없으면 통과(차단 금지).
    tsi_val = _first_float(
        tick.get("tsi"), candidate.get("tsi"), candidate.get("tsi_value"),
    )
    tsi_positive = True if tsi_val is None else (tsi_val > 0)

    matched: dict[str, Any] = {
        "volume_ratio": volume_ok,
        "ai_confidence": ai_conf >= ai_conf_min,
        "price_change": price_ok,
        "time_window": time_window_ok,
        "tsi_positive": tsi_positive,
    }
    observed_values: dict[str, Any] = {
        "ai_confidence": ai_conf,
        "ai_confidence_min": ai_conf_min,
        "change_rate": change_rate,
        "price_change_min_pct": price_min_pct,
        "price_change_max_pct": price_max_pct,
        "volume_ratio": volume_ratio,
        "volume_ratio_min": volume_ratio_min,
        "tsi": tsi_val,
    }
    _add_layer3_evaluation(
        matched=matched,
        observed_values=observed_values,
        unavailable_conditions=unavailable_conditions,
        candidate=candidate,
        final_rule=final_rule,
        tick=tick,
        price=_to_float_or_none(tick.get("price")),
    )

    if unavailable_conditions:
        logger.warning(
            "WARN: [S6] 일부 Layer3 조건 평가 불가 symbol=%s unavailable=%s",
            str(candidate.get("symbol") or candidate.get("ticker") or ""),
            sorted(unavailable_conditions.keys()),
        )

    matched["observed_values"] = observed_values
    matched["unavailable_conditions"] = unavailable_conditions
    return matched
