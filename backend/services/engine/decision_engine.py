"""S6 Decision Engine for realtime tick evaluation and signal persistence."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection
from ..kis.realtime_ws import realtime_ws_manager
from .hybrid_screening import get_today_screening
from .rule_cache import load_daily_rules, get_rule, clear_cache, get_meta

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
    """서버 재시작 후 position_stop_states에서 오늘 포지션을 복원한다.

    Args:
        trade_date: YYYY-MM-DD 형식의 거래일.
        candidate_symbols: 현재 DecisionEngine 후보 종목 코드 목록.
    """
    if not candidate_symbols:
        logger.info("INFO: [S6] 포지션 복원 후보 없음")
        return

    placeholders = ",".join("?" for _ in candidate_symbols)
    try:
        with get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT ps.*, latest.qty
                FROM position_stop_states ps
                JOIN (
                    SELECT symbol, qty, MAX(created_at) AS latest_created_at
                    FROM trading_orders
                    WHERE trade_date = ?
                      AND status IN ('submitted', 'filled')
                      AND side = 'buy'
                      AND symbol IN ({placeholders})
                    GROUP BY symbol
                ) latest
                  ON latest.symbol = ps.symbol_code
                JOIN (
                    SELECT symbol_code, MAX(last_updated_at) AS latest_updated_at
                    FROM position_stop_states
                    WHERE symbol_code IN ({placeholders})
                    GROUP BY symbol_code
                ) latest_stop
                  ON latest_stop.symbol_code = ps.symbol_code
                 AND latest_stop.latest_updated_at = ps.last_updated_at
                """,
                [trade_date] + candidate_symbols + candidate_symbols,
            ).fetchall()
    except Exception as exc:
        logger.warning("WARN: [S6] 포지션 복원 쿼리 실패 error=%s", exc)
        return

    from .position_manager import position_manager

    restored = 0
    for row in rows:
        data = dict(row)
        symbol = str(data.get("symbol_code") or "")
        qty = int(data.get("qty") or 0)
        entry_price = float(data.get("entry_price") or 0)
        if not symbol or qty <= 0 or entry_price <= 0:
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
            "SUCCESS: [S6] 포지션 복원 symbol=%s qty=%d entry=%.2f",
            symbol,
            qty,
            entry_price,
        )

    logger.info("SUCCESS: [S6] 포지션 복원 완료 count=%d", restored)


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

        screening = get_today_screening(today)
        candidates = screening.get("candidates", []) if screening else []
        if not candidates:
            self._active = False
            logger.warning("WARN: [S6] 오늘 S4 스크리닝 결과 없음 — Decision Engine 비활성")
            return {"ok": False, "reason": "no_screening_results"}

        self._candidates = {
            symbol: candidate
            for candidate in candidates
            if (symbol := _candidate_symbol(candidate))
        }
        if not self._candidates:
            self._active = False
            logger.warning("WARN: [S6] S4 후보에 유효한 종목코드 없음 — Decision Engine 비활성")
            return {"ok": False, "reason": "no_valid_candidates"}

        load_daily_rules(today, list(self._candidates.keys()))

        self._signal_sent = _load_sent_symbols(today)
        self._active = True
        realtime_ws_manager.register_tick_callback(self._on_tick)
        from .position_manager import position_manager
        from .fill_poller import fill_poller

        position_manager.activate()
        if not position_manager.get_positions():
            _restore_positions_from_db(today, list(self._candidates.keys()))
        fill_poller.start(today)

        symbols = list(self._candidates.keys())
        await realtime_ws_manager.start(symbols=symbols)

        logger.info(
            "SUCCESS: [S6] Decision Engine 활성화 candidates=%d already_sent=%d symbols=%s",
            len(symbols),
            len(self._signal_sent),
            symbols,
        )
        return {
            "ok": True,
            "candidates": len(symbols),
            "already_sent": len(self._signal_sent),
            "symbols": symbols,
            "cache_meta": get_meta(),
        }

    async def deactivate(self) -> None:
        """장 종료 시 호출 — WS 콜백 등록을 해제하고 실시간 연결을 종료한다."""
        logger.info("START: [S6] Decision Engine deactivate")
        self._active = False
        realtime_ws_manager.unregister_tick_callback(self._on_tick)
        from .position_manager import position_manager
        from .fill_poller import fill_poller

        fill_poller.stop()
        position_manager.deactivate()
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

        if all(matched.values()):
            await self._emit_signal(symbol, candidate, price, matched)

    def _evaluate_rules(
        self,
        *,
        candidate: dict[str, Any],
        final_rule: dict[str, Any],
        tick: dict[str, Any],
    ) -> dict[str, bool]:
        """Evaluate currently supported S6 entry rules.

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

        try:
            change_rate = float(tick.get("change_rate") or tick.get("prdy_ctrt") or 0.0)
        except (TypeError, ValueError):
            change_rate = 0.0
        price_ok = price_min_pct <= change_rate <= price_max_pct if price_min_pct > 0 else True

        # 현재 WS tick에는 5일 평균 거래량 기준값이 없으므로 수신 여부만 기본 충족으로 둔다.
        volume_value = tick.get("volume")
        volume_seen = volume_value not in (None, "")
        return {
            "volume_ratio": bool(volume_seen or final_rule.get("volume_ratio_min", 1.0) <= 1.0),
            "ai_confidence": ai_conf >= ai_conf_min,
            "price_change": price_ok,
        }

    async def _emit_signal(
        self,
        symbol: str,
        candidate: dict[str, Any],
        price: float,
        matched: dict[str, bool],
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
