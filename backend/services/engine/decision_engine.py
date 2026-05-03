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
from .rulepack_store import get_active_rulepack_for_date

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
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trading_signals_trade_date ON trading_signals(trade_date)"
        )


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


class DecisionEngine:
    """S6: 실시간 tick을 받아 RulePack 조건을 평가하고 매수 신호를 생성한다."""

    def __init__(self):
        """Initialize in-memory runtime state for one trading session."""
        self._active = False
        self._rulepack: dict[str, Any] = {}
        self._candidates: dict[str, dict[str, Any]] = {}
        self._signal_sent: set[str] = set()

    async def activate(self) -> dict[str, Any]:
        """장 시작에 호출 — RulePack과 S4 후보 로드 후 WS 콜백을 등록한다."""
        today = _today_kst()
        logger.info("START: [S6] Decision Engine activate trade_date=%s", today)
        _ensure_signals_table()

        rulepack = get_active_rulepack_for_date(today)
        if not rulepack:
            self._active = False
            logger.warning("WARN: [S6] 오늘 활성 RulePack 없음 — Decision Engine 비활성")
            return {"ok": False, "reason": "no_active_rulepack"}

        screening = get_today_screening(today)
        candidates = screening.get("candidates", []) if screening else []
        if not candidates:
            self._active = False
            logger.warning("WARN: [S6] 오늘 S4 스크리닝 결과 없음 — Decision Engine 비활성")
            return {"ok": False, "reason": "no_screening_results"}

        self._rulepack = rulepack.get("machine_rules", {}) or {}
        self._candidates = {
            symbol: candidate
            for candidate in candidates
            if (symbol := _candidate_symbol(candidate))
        }
        if not self._candidates:
            self._active = False
            logger.warning("WARN: [S6] S4 후보에 유효한 종목코드 없음 — Decision Engine 비활성")
            return {"ok": False, "reason": "no_valid_candidates"}

        self._signal_sent = set()
        self._active = True
        realtime_ws_manager.register_tick_callback(self._on_tick)
        from .position_manager import position_manager

        position_manager.activate()

        symbols = list(self._candidates.keys())
        await realtime_ws_manager.start(symbols=symbols)

        logger.info("SUCCESS: [S6] Decision Engine 활성화 candidates=%d symbols=%s", len(symbols), symbols)
        return {"ok": True, "candidates": len(symbols), "symbols": symbols}

    async def deactivate(self) -> None:
        """장 종료 시 호출 — WS 콜백 등록을 해제하고 실시간 연결을 종료한다."""
        logger.info("START: [S6] Decision Engine deactivate")
        self._active = False
        realtime_ws_manager.unregister_tick_callback(self._on_tick)
        from .position_manager import position_manager

        position_manager.deactivate()
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
        rules = self._rulepack.get("layer3_entry", {}) if isinstance(self._rulepack, dict) else {}
        matched = self._evaluate_rules(candidate=candidate, rules=rules, tick=tick)

        if all(matched.values()):
            await self._emit_signal(symbol, candidate, price, matched)

    def _evaluate_rules(
        self,
        *,
        candidate: dict[str, Any],
        rules: dict[str, Any],
        tick: dict[str, Any],
    ) -> dict[str, bool]:
        """Evaluate currently supported S6 entry rules.

        Args:
            candidate: S4 candidate metadata for the symbol.
            rules: Active RulePack layer3_entry rules.
            tick: Parsed realtime tick payload.
        """
        ai_conf_min = float(rules.get("ai_confidence_min", 0.0) or 0.0)
        ai_conf = _candidate_confidence(candidate)

        # 현재 WS tick에는 5일 평균 거래량 기준값이 없으므로 수신 여부만 기본 충족으로 둔다.
        volume_value = tick.get("volume")
        volume_seen = volume_value not in (None, "")
        return {
            "volume_ratio": bool(volume_seen or rules.get("volume_ratio_min", 1.0) <= 1.0),
            "ai_confidence": ai_conf >= ai_conf_min,
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
        self._signal_sent.add(symbol)
        today = _today_kst()
        signal_id = str(uuid.uuid4())
        confidence = _candidate_confidence(candidate)

        _ensure_signals_table()
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO trading_signals
                    (id, trade_date, symbol, name, signal_type, trigger_price,
                     confidence, rule_matched, status, created_at)
                VALUES (?, ?, ?, ?, 'BUY', ?, ?, ?, 'pending', ?)
                """,
                (
                    signal_id,
                    today,
                    symbol,
                    str(candidate.get("name") or ""),
                    price,
                    confidence,
                    json.dumps(matched, ensure_ascii=False),
                    _now_kst().isoformat(),
                ),
            )

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
