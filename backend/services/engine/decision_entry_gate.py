"""decision_engine 진입 게이트·Layer3 평가 헬퍼 (Phase 4 분해, 2026-08-22).

_add_layer3_evaluation: RulePack Layer3 지표(vwap/ma/rsi/spread)를 원시 payload가 있을 때만 평가.
_entry_gate_block_reason: _emit_signal 단일 길목의 진입 선별 게이트(손실스트릭·급락방어·하락전환·
new_entry·칼리브레이션·쿨다운·재진입churn) — 차단 사유 문자열 반환, 통과면 "".

로직은 원본과 100% 동일(순수 이동). 로거명 'DecisionEngine' 유지. sibling(loss_streak_guard·
intraday_regime_monitor·intraday_profile·regime_set_service·confidence_calibration·false_positive)은
모두 함수-지역 지연 import라 순환참조가 없다. decision_engine이 재-export한다.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from ..settings_store import get_setting
from .decision_context import _today_kst
from .decision_engine_utils import (
    _first_float_from_sources,
    _first_value_from_sources,
    _normalize_vwap_position,
    _parse_bool,
    _parse_rsi_range,
    _spread_percent_from_source,
    _to_float_or_none,
)

logger = logging.getLogger("DecisionEngine")


def _add_layer3_evaluation(
    *,
    matched: dict[str, Any],
    observed_values: dict[str, Any],
    unavailable_conditions: dict[str, Any],
    candidate: dict[str, Any],
    final_rule: dict[str, Any],
    tick: dict[str, Any],
    price: float | None,
) -> None:
    """Evaluate Layer3 indicators only when raw payload fields are present.

    Args:
        matched: Mutable rule result map returned from `_evaluate_rules`.
        observed_values: Mutable observed indicator map persisted with the signal.
        unavailable_conditions: Mutable map of rule keys that could not be evaluated.
        candidate: S4/S5 candidate metadata.
        final_rule: Resolved final rule from rule_cache.
        tick: Parsed realtime tick payload.
        price: Current tick price used only for VWAP comparison when VWAP is numeric.
    """
    vwap_rule = str(final_rule.get("vwap_position") or "any").strip().lower()
    if vwap_rule not in ("", "any"):
        raw_position, position_source = _first_value_from_sources(
            candidate,
            tick,
            ("vwap_position", "vwap_pos", "price_vs_vwap", "above_vwap", "is_above_vwap"),
        )
        observed_position = _normalize_vwap_position(raw_position)
        vwap_value, vwap_source = _first_float_from_sources(candidate, tick, ("vwap", "vwap_price"))
        if observed_position is None and vwap_value is not None and price is not None:
            observed_position = "above" if price >= vwap_value else "below"
            position_source = vwap_source
        if observed_position is None:
            unavailable_conditions["vwap_position"] = {"reason": "vwap_missing", "required": vwap_rule}
        else:
            matched["vwap_position"] = observed_position == vwap_rule
            observed_values["vwap_position"] = observed_position
            observed_values["vwap_required"] = vwap_rule
            observed_values["vwap_source"] = position_source
            if vwap_value is not None:
                observed_values["vwap"] = vwap_value

    if final_rule.get("ma5_above_ma20") not in (None, "", "any"):
        required_ma = _parse_bool(final_rule.get("ma5_above_ma20"))
        raw_ma, ma_source = _first_value_from_sources(
            candidate,
            tick,
            ("ma5_above_ma20", "ma_5_above_ma_20", "above_ma20"),
        )
        observed_ma = _parse_bool(raw_ma)
        ma5, ma5_source = _first_float_from_sources(candidate, tick, ("ma5", "ma_5", "moving_average_5"))
        ma20, ma20_source = _first_float_from_sources(candidate, tick, ("ma20", "ma_20", "moving_average_20"))
        if observed_ma is None and ma5 is not None and ma20 is not None:
            observed_ma = ma5 > ma20
            ma_source = f"{ma5_source}>{ma20_source}"
        if required_ma is None or observed_ma is None:
            unavailable_conditions["ma5_above_ma20"] = {
                "reason": "moving_average_missing",
                "required": final_rule.get("ma5_above_ma20"),
            }
        else:
            matched["ma5_above_ma20"] = observed_ma == required_ma
            observed_values["ma5_above_ma20"] = observed_ma
            observed_values["ma5_above_ma20_required"] = required_ma
            observed_values["ma_source"] = ma_source
            if ma5 is not None:
                observed_values["ma5"] = ma5
            if ma20 is not None:
                observed_values["ma20"] = ma20

    if final_rule.get("rsi_range") not in (None, "", "any"):
        required_rsi = _parse_rsi_range(final_rule.get("rsi_range"))
        rsi, rsi_source = _first_float_from_sources(
            candidate,
            tick,
            ("rsi", "rsi14", "rsi_14", "relative_strength_index"),
        )
        if required_rsi is None or rsi is None:
            unavailable_conditions["rsi_range"] = {"reason": "rsi_missing", "required": final_rule.get("rsi_range")}
        else:
            matched["rsi_range"] = required_rsi[0] <= rsi <= required_rsi[1]
            observed_values["rsi"] = rsi
            observed_values["rsi_range_required"] = list(required_rsi)
            observed_values["rsi_source"] = rsi_source

    spread_limit = _to_float_or_none(final_rule.get("spread_max_pct"))
    if spread_limit is not None:
        spread_raw, spread_source = _first_float_from_sources(
            candidate,
            tick,
            ("spread_pct", "spread_percent", "bid_ask_spread_pct", "spread_rate"),
        )
        if spread_raw is None:
            spread_raw, spread_source = _first_float_from_sources(candidate, tick, ("spread",))
        spread_pct, spread_reason = _spread_percent_from_source(spread_raw, spread_source, price)
        if spread_pct is None:
            unavailable_conditions["spread_max_pct"] = {"reason": spread_reason, "required": spread_limit}
        else:
            matched["spread_max_pct"] = spread_pct <= spread_limit
            observed_values["spread_pct"] = spread_pct
            observed_values["spread_max_pct_required"] = spread_limit
            observed_values["spread_source"] = spread_source


def _entry_gate_block_reason(symbol: str, confidence: float, name: str = "") -> str:
    """Phase 2·3 진입 선별성 게이트 — 차단 사유 문자열 반환, 통과면 "".

    _emit_signal 단일 길목에서 호출되어 모든 진입 경로(베이스라인·탐색OR·
    모멘텀스캔·교체매매)에 일괄 적용된다. 각 게이트는 fail-open(조회 실패 시
    차단하지 않음) — 손절/청산 안전장치는 별도 경로라 진입 게이트는 보수적으로.

    게이트:
      0. 급락 방어 모드(P3-3/P3-5) — flash crash 시 인버스 1x 플레이북 외 차단
      1. new_entry_allowed 강제(P3-2) — 당일 레짐 SET이 신규진입 금지면 차단
      2. 칼리브레이션 게이트(P2-1) — 누적 실적이 나쁜 confidence bin 차단
      3. entry_fail 쿨다운(P2-2) — 최근 반복 손실 진입 심볼 차단
      4. 장중 재진입 churn 차단(P-CHURN) — 오늘 N회 손절된 심볼 당일 재진입 금지
    """
    # -1) 손실 스트릭 하드 차단(결정론 안전망) — 3연패 자동차단 심볼은 신규진입 금지.
    try:
        if bool(get_setting("engine.loss_streak_hard_block_enabled", True)):
            from .loss_streak_guard import get_active_blocked_symbols

            if str(symbol) in get_active_blocked_symbols():
                return f"loss_streak_hard_block (3연패 자동차단 심볼 {symbol})"
    except Exception as exc:
        logger.warning("WARN: [S6] 손실스트릭 하드차단 게이트 조회 실패 — %s", exc)

    # 0) 급락 방어 모드 — 인버스 1x(플레이북)만 예외 허용
    try:
        from .intraday_regime_monitor import is_flash_crash_defense_active

        if is_flash_crash_defense_active():
            from .intraday_profile import is_inverse_1x_product

            playbook = bool(get_setting("engine.crash_playbook_enabled", True))
            if not (playbook and is_inverse_1x_product(name)):
                return "flash_crash_defense (급락 방어 모드 — 인버스 1x 외 신규진입 차단)"
    except Exception as exc:
        logger.warning("WARN: [S6] 급락 방어 게이트 조회 실패 — %s", exc)

    # 0.5) 하락전환 방어 + 상승전환 재개 래치(엔진② inc4) — 하락전환 시 신규매수를 **걸어두고**,
    #   None(불확실)에도 유지, **up_transition(반등 확인)에서만 해제**. 레벨은 아직 +여도 방향이
    #   꺾인 8/18 케이스 방어 + 데드캣 바운스 재진입 방지. flag-gated(regime.transition_
    #   response_active). 래치는 신선도 75분 가드로 stale시 자동해제(장초·종일차단 방지).
    try:
        if bool(get_setting("regime.transition_response_active", False)):
            from .intraday_regime_monitor import get_entry_suspended

            if get_entry_suspended():
                return "down_transition 래치 (하락전환 후 반등 미확인 — 상승전환까지 신규매수 중단)"
    except Exception as exc:
        logger.warning("WARN: [S6] 하락전환 게이트 조회 실패 — %s", exc)

    # 1) new_entry_allowed 강제 (engine.enforce_new_entry_allowed, 기본 ON)
    try:
        if bool(get_setting("engine.enforce_new_entry_allowed", True)):
            from ..regime_set_service import get_today_application

            app = get_today_application(_today_kst())
            applied = (app or {}).get("applied_settings") or {}
            if isinstance(applied, str):
                try:
                    applied = json.loads(applied)
                except Exception:
                    applied = {}
            if applied and not bool(applied.get("new_entry_allowed", True)):
                return f"new_entry_not_allowed (레짐 {(app or {}).get('regime_label', 'n/a')})"
    except Exception as exc:
        logger.warning("WARN: [S6] new_entry_allowed 게이트 조회 실패 — %s", exc)

    # 2) 칼리브레이션 게이트 — 실적 나쁜 confidence 구간 차단
    try:
        if bool(get_setting("engine.calibration_gate_enabled", True)):
            from .confidence_calibration import is_confidence_blocked

            min_samples = int(float(get_setting("engine.calibration_gate_min_samples", 30) or 30))
            gap = float(get_setting("engine.calibration_gate_gap", 0.15) or 0.15)
            blocked, why = is_confidence_blocked(confidence, min_samples=min_samples, gap_threshold=gap)
            if blocked:
                return why
    except Exception as exc:
        logger.warning("WARN: [S6] 칼리브레이션 게이트 조회 실패 — %s", exc)

    # 3) entry_fail 쿨다운 — 최근 N일 내 반복 손실 진입 심볼 차단
    try:
        if bool(get_setting("engine.entry_fail_cooldown_enabled", True)):
            from .false_positive import recent_entry_fail_count

            days = int(float(get_setting("engine.entry_fail_cooldown_days", 3) or 3))
            min_count = int(float(get_setting("engine.entry_fail_cooldown_min_count", 2) or 2))
            n = recent_entry_fail_count(symbol, days=days)
            if n >= max(min_count, 1):
                return f"entry_fail_cooldown (최근 {days}일 {n}회 손실진입)"
    except Exception as exc:
        logger.warning("WARN: [S6] entry_fail 쿨다운 조회 실패 — %s", exc)

    # 4) 장중 재진입 churn 차단(P-CHURN) — 오늘 N회 손절된 종목은 당일 재진입 금지.
    # entry_fail_cooldown은 false_positive_cases(EOD 생성)를 세어 '오늘 장중' 손절을 못 막는다.
    # trading_orders를 직접 집계해, 손절→즉시 재매수 루프(초비트장 churn)를 장중에 끊는다.
    try:
        if bool(get_setting("engine.intraday_reentry_block_enabled", True)):
            from .loss_streak_guard import intraday_stoploss_count

            max_sl = int(float(get_setting("engine.intraday_max_stoploss_per_symbol", 2) or 2))
            sl_n = intraday_stoploss_count(symbol, _today_kst())
            if sl_n >= max(max_sl, 1):
                return f"intraday_reentry_block (오늘 {sl_n}회 손절 — 당일 재진입 차단)"
    except Exception as exc:
        logger.warning("WARN: [S6] 장중 재진입 churn 가드 조회 실패 — %s", exc)

    return ""
