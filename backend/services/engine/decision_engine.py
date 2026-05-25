"""S6 Decision Engine for realtime tick evaluation and signal persistence."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection
from ..kis.realtime_ws import realtime_ws_manager
from .hybrid_screening import get_today_screening
from .rule_cache import load_daily_rules, get_rule, clear_cache, get_meta
from .shadow_trading import create_shadow_trade

logger = logging.getLogger("DecisionEngine")


def _now_kst() -> datetime:
    """Return the current Asia/Seoul datetime."""
    return datetime.now(ZoneInfo("Asia/Seoul"))


def _today_kst() -> str:
    """Return today's Asia/Seoul date as YYYY-MM-DD."""
    return _now_kst().strftime("%Y-%m-%d")

def _ensure_signals_table() -> None:
    """Create the trading_signals table and index when they do not exist."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trading_signals (
                id TEXT PRIMARY KEY,
                trade_date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                signal_type TEXT NOT NULL DEFAULT 'BUY',
                trigger_price REAL NOT NULL DEFAULT 0.0,
                confidence REAL NOT NULL DEFAULT 0.0,
                rule_matched TEXT NOT NULL DEFAULT '{}',
                profile_assigned TEXT NOT NULL DEFAULT 'MID_VOL',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trading_signals_trade_date ON trading_signals(trade_date)"
        )
        cols = {row[1] for row in conn.execute("PRAGMA table_info(trading_signals)").fetchall()}
        if "profile_assigned" not in cols:
            conn.execute("ALTER TABLE trading_signals ADD COLUMN profile_assigned TEXT NOT NULL DEFAULT 'MID_VOL'")
        if "realized_pnl" not in cols:
            conn.execute("ALTER TABLE trading_signals ADD COLUMN realized_pnl REAL")


def _save_daily_context_snapshot(today: str) -> None:
    """오늘의 레짐과 RulePack 파라미터를 daily_context_snapshot에 저장한다.

    Args:
        today: Snapshot 대상 거래일(YYYY-MM-DD). S6 activate 시점에 호출되며 실패해도 거래 흐름은 유지한다.
    """
    try:
        from .market_tone import get_today_morning_context
        from .rulepack_generation import get_active_rulepack

        ctx = get_today_morning_context(today) or {}
        rulepack = get_active_rulepack(today) or {}
        machine_rules = rulepack.get("machine_rules") if isinstance(rulepack.get("machine_rules"), dict) else rulepack
        risk = machine_rules.get("risk_limits") if isinstance(machine_rules, dict) else {}
        risk = risk or {}
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        with get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO daily_context_snapshot
                    (trade_date, regime, risk_level, rulepack_id,
                     stop_loss_rate, take_profit_rate, max_positions,
                     max_position_size_rate, trailing_activate_profit,
                     trailing_stop_rate, new_entry_allowed,
                     raw_rulepack_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    today,
                    ctx.get("regime", "neutral"),
                    ctx.get("risk_level", "normal"),
                    rulepack.get("rulepack_id", ""),
                    risk.get("stop_loss_rate"),
                    risk.get("take_profit_rate"),
                    risk.get("max_positions"),
                    risk.get("max_position_size_rate"),
                    None,
                    None,
                    1 if machine_rules.get("new_entry_allowed", True) else 0,
                    json.dumps(rulepack, ensure_ascii=False),
                    now,
                ),
            )
        try:
            from ..regime_set_service import match_set as match_regime_set

            market_data = ctx.get("market_data") if isinstance(ctx.get("market_data"), dict) else {}
            vix_data = market_data.get("vix") if isinstance(market_data.get("vix"), dict) else {}
            kospi_data = market_data.get("kospi") if isinstance(market_data.get("kospi"), dict) else {}
            regime_label = str(ctx.get("regime") or "neutral")
            vix_value = _to_float_or_none(vix_data.get("price") if isinstance(vix_data, dict) else None)
            kospi_change = _to_float_or_none(kospi_data.get("change_pct") if isinstance(kospi_data, dict) else None)
            match_regime_set(regime_label, vix_value, kospi_change, today)
            logger.info(
                "SUCCESS: [S6] regime_set matched trade_date=%s regime=%s vix=%s kospi_change_pct=%s",
                today,
                regime_label,
                vix_value,
                kospi_change,
            )
        except Exception as regime_exc:
            logger.warning("WARN: [S6] regime set matching failed (비치명) - %s", regime_exc)
        logger.info("INFO: [S6] daily_context_snapshot saved trade_date=%s regime=%s", today, ctx.get("regime"))
    except Exception as exc:
        logger.warning("WARN: [S6] daily_context_snapshot 저장 실패 (비치명) - %s", exc)


def _candidate_symbol(candidate: dict[str, Any]) -> str:
    """Extract a candidate symbol from S4/S5 compatible key names.

    Args:
        candidate: Candidate dictionary from hybrid screening.
    """
    return str(candidate.get("symbol") or candidate.get("ticker") or "").strip()


def _candidate_confidence(candidate: dict[str, Any]) -> float:
    """Extract a confidence score from S4/S5 compatible key names.

    Args:
        candidate: Candidate dictionary from hybrid screening.
    """
    try:
        return float(candidate.get("confidence", candidate.get("suitability_score", 0.0)) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _has_recent_submitted_buy(symbol: str, within_minutes: int = 5) -> bool:
    """Return True if there is a submitted buy order for symbol within the last N minutes.

    Used to protect freshly-placed positions from being evicted by the KIS balance sync
    before KIS settlement has propagated (typically 1-3 minutes after order submission).

    Args:
        symbol: Stock symbol to check.
        within_minutes: Grace period in minutes after order submission.
    """
    cutoff = (datetime.now(ZoneInfo("Asia/Seoul")) - timedelta(minutes=within_minutes)).isoformat()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id FROM trading_orders
            WHERE symbol = ? AND side = 'buy' AND status IN ('submitted', 'filled')
              AND created_at >= ?
            LIMIT 1
            """,
            (symbol, cutoff),
        ).fetchone()
    return row is not None


def _sync_managed_positions_with_account(account_positions: list[dict[str, Any]]) -> list[str]:
    """Align S8-managed quantities to KIS real holdings without adding unmanaged holdings.

    Positions with a recent submitted/filled buy order are NOT removed even if KIS
    balance does not yet reflect them — KIS settlement can lag 1-3 minutes after order
    placement (race condition between S7 and S8 activation sync).

    Args:
        account_positions: Public account positions from the KIS balance API.
    """
    from .position_manager import position_manager

    holdings = {str(item.get("symbol") or "").strip(): item for item in account_positions}
    synced: list[str] = []
    for position in position_manager.get_positions():
        symbol = str(position.get("symbol") or "").strip()
        if not symbol:
            continue
        holding = holdings.get(symbol)
        if not holding:
            if _has_recent_submitted_buy(symbol):
                logger.info(
                    "INFO: [S6] KIS 잔고 미존재 but 최근 매수 주문 있음 → S8 포지션 유지 symbol=%s",
                    symbol,
                )
                continue
            position_manager.remove_position(symbol)
            logger.warning("WARN: [S6] KIS 잔고 미존재 S8 포지션 제거 symbol=%s", symbol)
            continue
        qty = int(float(str(holding.get("qty") or 0).replace(",", "")))
        if qty <= 0:
            if _has_recent_submitted_buy(symbol):
                logger.info(
                    "INFO: [S6] KIS 수량 0 but 최근 매수 주문 있음 → S8 포지션 유지 symbol=%s",
                    symbol,
                )
                continue
            position_manager.remove_position(symbol)
            logger.warning("WARN: [S6] KIS 수량 0 S8 포지션 제거 symbol=%s", symbol)
            continue
        if position_manager.update_position_quantity(symbol, qty):
            synced.append(symbol)
    logger.info("SUCCESS: [S6] KIS 실잔고 기준 S8 수량 동기화 count=%d", len(synced))
    return synced


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


_OR_GATE_AI_MIN = 0.85   # AI 신뢰도 OR 게이트 임계값
_OR_GATE_VOL_MIN = 3.0   # 거래량비율 OR 게이트 임계값


def _rules_allow_signal(matched: dict[str, Any]) -> bool:
    """현재 S6 매수 신호 발행에 필요한 게이트 조건 통과 여부를 반환한다.

    기본 AND 게이트: 모든 조건이 True여야 통과.
    OR 게이트(폴백): price_change만 미달이고 AI신뢰도≥0.85 + 거래량비율≥3.0이면 통과.

    Args:
        matched: Rule evaluation payload from `_evaluate_rules`.
    """
    optional_keys = [
        key
        for key in ("vwap_position", "ma5_above_ma20", "rsi_range", "spread_max_pct")
        if key in matched
    ]
    core_keys = ["volume_ratio", "ai_confidence", "price_change", "time_window"]
    all_keys = core_keys + optional_keys

    # 기본 AND 게이트
    if all(bool(matched.get(key)) for key in all_keys):
        return True

    # OR 게이트: time_window·volume_ratio·ai_confidence 필수, price_change만 미달 허용
    if not bool(matched.get("time_window")):
        return False
    if not bool(matched.get("volume_ratio")):
        return False
    if not bool(matched.get("ai_confidence")):
        return False
    if bool(matched.get("price_change")):
        # price_change 이외 다른 조건이 실패 → OR 게이트 대상 아님
        return False
    if not all(bool(matched.get(key)) for key in optional_keys):
        return False

    obs = matched.get("observed_values") or {}
    ai_conf = float(obs.get("ai_confidence") or 0.0)
    vol_ratio = float(obs.get("volume_ratio") or 0.0)
    if ai_conf >= _OR_GATE_AI_MIN and vol_ratio >= _OR_GATE_VOL_MIN:
        logger.info(
            "INFO: [S6] OR-gate 통과 (price_change 미달 면제) ai_conf=%.2f vol_ratio=%.1f",
            ai_conf, vol_ratio,
        )
        return True

    return False


def _get_setting_float(key: str, default: float) -> float:
    """system_settings에서 숫자 값을 읽는다. 실패 시 default 반환.

    Args:
        key: system_settings key to read.
        default: Fallback value when the key is absent or invalid.
    """
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT value_json FROM system_settings WHERE key = ?", (key,)
            ).fetchone()
        if row:
            return float(json.loads(row["value_json"]))
    except Exception as exc:
        logger.warning("WARN: [S6] system setting float 조회 실패 key=%s error=%s", key, exc)
    return default


def _get_setting_str(key: str, default: str) -> str:
    """system_settings에서 문자열 값을 읽는다. 실패 시 default 반환.

    Args:
        key: system_settings key to read.
        default: Fallback value when the key is absent or invalid.
    """
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT value_json FROM system_settings WHERE key = ?", (key,)
            ).fetchone()
        if row:
            value = json.loads(row["value_json"])
            return str(value) if value is not None else default
    except Exception as exc:
        logger.warning("WARN: [S6] system setting str 조회 실패 key=%s error=%s", key, exc)
    return default


def _load_sent_symbols(trade_date: str) -> set[str]:
    """Return symbols that already emitted a signal for the trade date."""
    _ensure_signals_table()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT symbol FROM trading_signals WHERE trade_date = ?",
            (trade_date,),
        ).fetchall()
    return {str(row["symbol"]) for row in rows if row["symbol"]}


def _restore_positions_from_db(trade_date: str, candidate_symbols: list[str]) -> None:
    """서버 재시작 후 DB 주문 순수량 기준으로 오늘 포지션을 복원한다.

    Args:
        trade_date: YYYY-MM-DD 형식의 거래일.
        candidate_symbols: 현재 DecisionEngine 후보 종목 코드 목록. 비어 있으면 오늘 매수 주문 전체를 대상으로 복원한다.
    """
    try:
        from .position_integrity import build_restore_position_plan

        rows = build_restore_position_plan(trade_date, candidate_symbols)
    except Exception as exc:
        logger.warning("WARN: [S6] 포지션 복원 쿼리 실패 error=%s", exc)
        return

    from .position_manager import position_manager

    restored = 0
    for row in rows:
        data = dict(row)
        symbol = str(data.get("symbol_code") or "")
        if not symbol:
            symbol = str(data.get("symbol") or "")
        buy_qty = int(data.get("buy_qty") or 0)
        sell_qty = int(data.get("sell_qty") or 0)
        net_qty = int(data.get("net_qty") or 0)
        skipped_reason = str(data.get("skipped_reason") or "")
        if not data.get("should_restore"):
            logger.warning(
                "WARN: [S6] 포지션 복원 스킵 symbol=%s buy_qty=%d sell_qty=%d net_qty=%d skipped_reason=%s",
                symbol,
                buy_qty,
                sell_qty,
                net_qty,
                skipped_reason or "not_restorable",
            )
            continue
        qty = int(data.get("qty") or 0)
        entry_price = float(data.get("entry_price") or 0)
        if not symbol or qty <= 0 or entry_price <= 0:
            logger.warning(
                "WARN: [S6] 포지션 복원 스킵 symbol=%s buy_qty=%d sell_qty=%d net_qty=%d skipped_reason=%s",
                symbol,
                buy_qty,
                sell_qty,
                net_qty,
                "invalid_restore_payload",
            )
            continue
        position_manager.add_position(
            symbol=symbol,
            name="",
            qty=qty,
            entry_price=entry_price,
            final_rule=get_rule(symbol) or {},
        )
        restored += 1
        logger.info(
            "SUCCESS: [S6] 포지션 복원 symbol=%s qty=%d entry=%.2f buy_qty=%d sell_qty=%d net_qty=%d skipped_reason=%s",
            symbol,
            qty,
            entry_price,
            buy_qty,
            sell_qty,
            net_qty,
            skipped_reason,
        )

    logger.info("SUCCESS: [S6] 포지션 복원 완료 count=%d trade_date=%s", restored, trade_date)


class DecisionEngine:
    """S6: 실시간 tick을 받아 RulePack 조건을 평가하고 매수 신호를 생성한다."""

    def __init__(self):
        """Initialize in-memory runtime state for one trading session."""
        self._active = False
        self._candidates: dict[str, dict[str, Any]] = {}
        self._signal_sent: set[str] = set()

    async def activate(self) -> dict[str, Any]:
        """장 시작에 호출 — RulePack과 S4 후보 로드 후 WS 콜백을 등록한다."""
        today = _today_kst()
        logger.info("START: [S6] Decision Engine activate trade_date=%s", today)
        _ensure_signals_table()
        _save_daily_context_snapshot(today)

        screening = get_today_screening(today)
        candidates = screening.get("candidates", []) if screening else []
        self._candidates = {
            symbol: candidate
            for candidate in candidates
            if (symbol := _candidate_symbol(candidate))
        }

        candidate_symbols = list(self._candidates.keys())
        if candidate_symbols:
            load_daily_rules(today, candidate_symbols)
        else:
            logger.warning("WARN: [S6] 오늘 S4 유효 후보 없음 — 신규 매수 판단 없이 보유 포지션 보호만 시도")

        self._signal_sent = _load_sent_symbols(today)
        self._active = True
        realtime_ws_manager.register_tick_callback(self._on_tick)
        from .position_manager import position_manager
        from .fill_poller import fill_poller

        position_manager.activate()
        if not position_manager.get_positions():
            _restore_positions_from_db(today, [])
        account_symbols: list[str] = []
        try:
            from ...api.routes.account import _build_balance_payload
            from ..kis.domestic.service import get_balance

            account_payload = _build_balance_payload(await get_balance())
            account_positions = account_payload.get("positions", [])
            if isinstance(account_positions, list):
                account_symbols = _sync_managed_positions_with_account(account_positions)
        except Exception as exc:
            logger.warning("WARN: [S6] KIS 실잔고 기준 S8 동기화 실패 error=%s", exc)
        fill_poller.start(today)

        managed_symbols = [str(pos.get("symbol") or "") for pos in position_manager.get_positions()]
        symbols = list(dict.fromkeys([*candidate_symbols, *managed_symbols]))
        if not symbols:
            self._active = False
            position_manager.deactivate()
            fill_poller.stop()
            realtime_ws_manager.unregister_tick_callback(self._on_tick)
            logger.warning("WARN: [S6] S4 후보와 KIS 실보유 포지션 모두 없어 Decision Engine 비활성")
            return {"ok": False, "reason": "no_candidates_or_positions"}

        await realtime_ws_manager.start(symbols=symbols)

        logger.info(
            "SUCCESS: [S6] Decision Engine 활성화 candidates=%d holdings=%d already_sent=%d symbols=%s",
            len(candidate_symbols),
            len(account_symbols),
            len(self._signal_sent),
            symbols,
        )
        return {
            "ok": True,
            "candidates": len(candidate_symbols),
            "holdings": len(account_symbols),
            "already_sent": len(self._signal_sent),
            "symbols": symbols,
            "cache_meta": get_meta(),
        }

    def is_active(self) -> bool:
        """Decision Engine 활성화 여부."""
        return self._active

    async def refresh_candidates(self) -> dict[str, Any]:
        """장중 재선별 후 호출 — 후보 목록을 교체하고 WS 구독을 갱신한다.

        기존 signal_sent는 유지 (이미 주문 나간 종목 중복 방지).
        보유 포지션 종목은 제거하지 않음.
        """
        if not self._active:
            return {"ok": False, "reason": "not_active"}

        today = _today_kst()
        logger.info("START: [S6] refresh_candidates trade_date=%s", today)

        old_candidates = dict(self._candidates)

        # 새 S4 후보 로드
        screening = get_today_screening(today)
        new_candidates_raw = screening.get("candidates", []) if screening else []
        new_candidates: dict[str, dict[str, Any]] = {
            symbol: candidate
            for candidate in new_candidates_raw
            if (symbol := _candidate_symbol(candidate))
        }

        self._candidates = new_candidates
        if new_candidates:
            load_daily_rules(today, list(new_candidates.keys()))
        else:
            logger.warning("WARN: [S6] refresh_candidates — 새 후보 없음 (기존 후보 유지)")
            self._candidates = old_candidates
            return {"ok": False, "reason": "no_new_candidates", "old_count": len(old_candidates)}

        # WS 구독 갱신: 기존 포지션 종목 + 새 후보 합집합
        from .position_manager import position_manager
        managed_symbols = [str(pos.get("symbol") or "") for pos in position_manager.get_positions()]
        all_symbols = list(dict.fromkeys([*list(new_candidates.keys()), *managed_symbols]))

        try:
            await realtime_ws_manager.stop()
            await realtime_ws_manager.start(symbols=all_symbols)
        except Exception as exc:
            logger.warning("WARN: [S6] refresh_candidates WS 재구독 실패 — %s", exc)

        replacement_result: dict[str, Any] = {"skipped": True, "reason": "not_evaluated"}
        try:
            from .replacement_signal import evaluate_replacement_signals

            replacement_result = await evaluate_replacement_signals(
                new_candidates=new_candidates,
                current_positions=position_manager.get_positions(),
            )
        except Exception as exc:
            replacement_result = {"ok": False, "error": str(exc)}
            logger.warning("WARN: [S6] replacement signal evaluation failed — %s", exc)

        logger.info(
            "SUCCESS: [S6] refresh_candidates old=%d new=%d symbols=%s replacement_created=%s",
            len(old_candidates),
            len(new_candidates),
            all_symbols,
            replacement_result.get("created", 0),
        )
        return {
            "ok": True,
            "old_count": len(old_candidates),
            "new_count": len(new_candidates),
            "symbols": all_symbols,
            "replacement_signal": replacement_result,
        }

    async def on_position_slot_opened(self, exited_symbol: str, reason: str) -> dict[str, Any]:
        """Refresh candidate watch after a trailing-stop exit opens capacity.

        Args:
            exited_symbol: Symbol that just submitted a sell order.
            reason: PositionManager exit reason. This method only re-arms natural
                candidate evaluation and never submits a forced buy order.
        """
        if not self._active:
            return {"ok": False, "reason": "not_active"}
        from .position_manager import position_manager

        managed_symbols = [str(pos.get("symbol") or "") for pos in position_manager.get_positions()]
        rearmed: list[str] = []
        for symbol in self._candidates:
            if symbol == exited_symbol or symbol in managed_symbols or _has_recent_submitted_buy(symbol):
                continue
            if symbol in self._signal_sent:
                self._signal_sent.discard(symbol)
                rearmed.append(symbol)

        all_symbols = list(dict.fromkeys([*list(self._candidates.keys()), *managed_symbols]))
        try:
            await realtime_ws_manager.stop()
            await realtime_ws_manager.start(symbols=all_symbols)
        except Exception as exc:
            logger.warning("WARN: [S6] slot-open WS refresh failed exited=%s reason=%s", exited_symbol, exc)
        logger.info(
            "SUCCESS: [S6] position slot opened exited=%s reason=%s rearmed=%d symbols=%d",
            exited_symbol,
            reason,
            len(rearmed),
            len(all_symbols),
        )
        return {"ok": True, "exited_symbol": exited_symbol, "rearmed": rearmed, "symbols": all_symbols}

    async def deactivate(self) -> None:
        """장 종료 시 호출 — WS 콜백 등록을 해제하고 실시간 연결을 종료한다."""
        logger.info("START: [S6] Decision Engine deactivate")
        self._active = False
        realtime_ws_manager.unregister_tick_callback(self._on_tick)
        from .position_manager import position_manager
        from .fill_poller import fill_poller

        fill_poller.stop()
        position_manager.deactivate()

        # 감시했으나 매수 신호를 보내지 않은 종목 → shadow_trades 기록
        today = _today_kst()
        now_iso = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
        for symbol, cand in self._candidates.items():
            if symbol in self._signal_sent:
                continue
            try:
                create_shadow_trade(
                    trade_date=today,
                    symbol=symbol,
                    symbol_name=cand.get("name", ""),
                    missed_stage="S6_NO_SIGNAL",
                    entry_price=float(cand.get("price") or cand.get("trigger_price") or 0),
                    entry_time=now_iso,
                )
            except Exception as _st_exc:
                logger.warning("WARN: [S6] shadow_trade 기록 실패 symbol=%s reason=%s", symbol, _st_exc)

        clear_cache()
        await realtime_ws_manager.stop()
        logger.info("SUCCESS: [S6] Decision Engine 비활성화")

    async def _on_tick(self, tick: dict[str, Any]) -> None:
        """tick 수신 콜백 — 후보 종목이면 RulePack 조건을 평가한다.

        Args:
            tick: Parsed realtime tick from RealtimeWSManager.
        """
        if not self._active:
            return

        symbol = str(tick.get("symbol") or "").strip()
        if symbol not in self._candidates or symbol in self._signal_sent:
            return

        try:
            price = float(tick.get("price") or 0)
        except (TypeError, ValueError):
            logger.warning("WARN: [S6] tick price parse failed symbol=%s price=%s", symbol, tick.get("price"))
            return
        if price <= 0:
            return

        candidate = self._candidates[symbol]
        final_rule = get_rule(symbol) or {}
        matched = self._evaluate_rules(candidate=candidate, final_rule=final_rule, tick=tick)

        if _rules_allow_signal(matched):
            await self._emit_signal(symbol, candidate, price, matched)

    def _evaluate_rules(
        self,
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
        price_floor = _get_setting_float("engine.min_price_change_pct", 0.5)
        price_ceil = _get_setting_float("engine.max_price_change_pct", 8.0)
        price_min_pct = max(price_min_pct, price_floor)
        price_max_pct = min(price_max_pct, price_ceil)

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

        matched: dict[str, Any] = {
            "volume_ratio": volume_ok,
            "ai_confidence": ai_conf >= ai_conf_min,
            "price_change": price_ok,
            "time_window": time_window_ok,
        }
        observed_values: dict[str, Any] = {
            "ai_confidence": ai_conf,
            "ai_confidence_min": ai_conf_min,
            "change_rate": change_rate,
            "price_change_min_pct": price_min_pct,
            "price_change_max_pct": price_max_pct,
            "volume_ratio": volume_ratio,
            "volume_ratio_min": volume_ratio_min,
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

    async def _emit_signal(
        self,
        symbol: str,
        candidate: dict[str, Any],
        price: float,
        matched: dict[str, Any],
    ) -> None:
        """BUY 신호를 DB에 저장하고 중복 발행을 방지한다.

        Args:
            symbol: Stock symbol that triggered the signal.
            candidate: S4 candidate metadata for the symbol.
            price: Trigger price from realtime tick.
            matched: Rule evaluation result map.
        """
        today = _today_kst()
        signal_id = str(uuid.uuid4())
        confidence = _candidate_confidence(candidate)
        profile_assigned = (get_rule(symbol) or {}).get("profile_assigned", "MID_VOL")

        _ensure_signals_table()
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO trading_signals
                    (id, trade_date, symbol, name, signal_type, trigger_price,
                     confidence, rule_matched, profile_assigned, status, created_at)
                VALUES (?, ?, ?, ?, 'BUY', ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    signal_id,
                    today,
                    symbol,
                    str(candidate.get("name") or ""),
                    price,
                    confidence,
                    json.dumps(matched, ensure_ascii=False),
                    profile_assigned,
                    _now_kst().isoformat(),
                ),
            )

        try:
            from .technical_indicators import save_signal_indicators as _save_signal_indicators

            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, _save_signal_indicators, signal_id, symbol, today)
            logger.info("INFO: [S6] signal indicators save scheduled signal_id=%s symbol=%s", signal_id, symbol)
        except Exception as sti_exc:
            logger.warning("WARN: [S6] signal indicators save skipped signal_id=%s reason=%s", signal_id, sti_exc)

        self._signal_sent.add(symbol)
        logger.info("SIGNAL: [S6] BUY signal symbol=%s price=%.0f confidence=%.2f", symbol, price, confidence)
        from .order_executor import order_executor

        asyncio.create_task(
            order_executor.execute_signal(
                {
                    "id": signal_id,
                    "symbol": symbol,
                    "name": candidate.get("name", ""),
                    "trigger_price": price,
                    "confidence": confidence,
                }
            )
        )


decision_engine = DecisionEngine()


def get_today_signals(trade_date: str) -> list[dict[str, Any]]:
    """오늘 생성된 매수 신호 목록을 조회한다.

    Args:
        trade_date: YYYY-MM-DD trade date.
    """
    _ensure_signals_table()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM trading_signals WHERE trade_date = ? ORDER BY created_at DESC",
            (trade_date,),
        ).fetchall()
    return [dict(row) for row in rows]
