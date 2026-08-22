"""S6 Decision Engine for realtime tick evaluation and signal persistence."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import deque
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection
from ..kis.realtime_ws import realtime_ws_manager
from ..settings_store import get_setting
from .hybrid_screening import get_today_screening
from .position_manager import position_manager
from .rule_cache import load_daily_rules, get_rule, clear_cache, get_meta, set_intraday_profile
from .intraday_profile import classify_profile, record_intraday_event
from .shadow_trading import create_shadow_trade
from .decision_engine_utils import (  # 순수 파싱·숫자 유틸(Phase 1 분해)
    _first_float,
    _vwap_pullback_gate,  # 외부(test_vwap_pullback_gate)가 import — 재-export 보존
)
from .decision_context import (  # 시간·일별 컨텍스트 헬퍼(Phase 2 분해) — 재-export로 기존 참조 보존
    _ensure_signals_table,
    _now_kst,
    _save_daily_context_snapshot,
    _today_kst,
)
from .decision_position_sync import (  # 후보파싱·계좌편입·S8 동기화(Phase 3 분해) — 재-export로 기존 참조 보존
    _candidate_confidence,
    _candidate_symbol,
    _has_recent_submitted_buy,
    _resolve_import_entry_price,  # 외부(test_p0_scaleout_loop_fix)가 import
    _sync_managed_positions_with_account,
)
from .decision_entry_gate import _entry_gate_block_reason  # 진입게이트(Phase 4 분해)
from .decision_rules import (  # S6 룰 평가·시장맥락(Phase 5 분해) — 클래스는 얇은 위임 메서드로 호출
    _build_market_context as _rules_build_market_context,
    _evaluate_rules as _rules_evaluate_rules,
)

logger = logging.getLogger("DecisionEngine")


_REGIME_CACHE: dict[str, Any] = {"at": 0.0, "label": ""}


def _current_regime_label(ttl_seconds: float = 120.0) -> str:
    """당일 적용 레짐 라벨 — regime_set_applications(장중 전환 반영) 우선, snapshot 폴백.

    _evaluate_rules가 틱마다 호출하므로 TTL 캐시(기본 120초)로 DB 부하를 막는다.
    조회 실패 시 'neutral'(방어 강화 미적용 — 게이트는 fail-open, 손절은 별도).
    """
    now = time.monotonic()
    if _REGIME_CACHE["label"] and now - _REGIME_CACHE["at"] < ttl_seconds:
        return _REGIME_CACHE["label"]
    label = ""
    try:
        from ..regime_set_service import get_today_application

        app = get_today_application(_today_kst())
        if app:
            label = str(app.get("regime_label") or "")
    except Exception:
        label = ""
    if not label:
        try:
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT regime FROM daily_context_snapshot WHERE trade_date = ?",
                    (_today_kst(),),
                ).fetchone()
            label = str(row["regime"]) if row and row["regime"] else ""
        except Exception:
            label = ""
    label = label or "neutral"
    _REGIME_CACHE["at"] = now
    _REGIME_CACHE["label"] = label
    return label


def _rules_allow_signal(matched: dict[str, Any]) -> bool:
    """현재 S6 매수 신호 발행에 필요한 게이트 조건 통과 여부를 반환한다.

    정량 게이트만 AND로 평가. 정성 점수(ai_confidence)는 게이트에서 제외하고
    관찰·랭킹 용도로만 유지한다 (observed_values 에 기록).

    Args:
        matched: Rule evaluation payload from `_evaluate_rules`.
    """
    optional_keys = [
        key
        for key in ("vwap_position", "ma5_above_ma20", "rsi_range", "spread_max_pct")
        if key in matched
    ]
    core_keys = ["volume_ratio", "price_change", "time_window", "tsi_positive"]
    all_keys = core_keys + optional_keys

    return all(bool(matched.get(key)) for key in all_keys)


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


def _get_setting_bool(key: str, default: bool) -> bool:
    """system_settings에서 불리언 값을 읽는다. 실패 시 default 반환.

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
            return bool(json.loads(row["value_json"]))
    except Exception as exc:
        logger.warning("WARN: [S6] system setting bool 조회 실패 key=%s error=%s", key, exc)
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


_BLOCKED_SIGNAL_STATUSES = ("preflight_blocked", "rejected", "failed")


def _load_sent_symbols(trade_date: str) -> set[str]:
    """Return symbols that already emitted a NON-blocked signal for the trade date.

    Signals that never reached order submission (preflight_blocked/rejected/failed) are
    excluded so the monitoring loop can re-signal them when conditions re-trigger.
    """
    _ensure_signals_table()
    placeholders = ",".join("?" * len(_BLOCKED_SIGNAL_STATUSES))
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT DISTINCT symbol FROM trading_signals "
            f"WHERE trade_date = ? AND status NOT IN ({placeholders})",
            (trade_date, *_BLOCKED_SIGNAL_STATUSES),
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

    BLOCK_COOLDOWN_SECONDS = 30.0
    RATE_LIMIT_PRESSURE_WINDOW_SECONDS = 30 * 60
    RATE_LIMIT_PRESSURE_WARN_THRESHOLD = 50

    def __init__(self):
        """Initialize in-memory runtime state for one trading session."""
        self._active = False
        self._candidates: dict[str, dict[str, Any]] = {}
        self._signal_sent: set[str] = set()
        # symbol → monotonic timestamp when re-evaluation is allowed
        self._block_cooldown: dict[str, float] = {}
        self._account_sync_task: asyncio.Task | None = None
        self._account_sync_interval_seconds = 60.0
        self._account_sync_seq = 0
        self._account_sync_rate_limit_hits: deque[float] = deque()

        from .intraday_bar_engine import BarEngine

        self._bar_engine = BarEngine()

    def _record_account_sync_rate_limit_hits(self, hits: int) -> int:
        """Record EGW00201 hits observed during PositionSync and return the 30-minute count.

        Args:
            hits: Number of EGW00201 rate-limit hits detected in the current sync.
        """
        now = time.time()
        cutoff = now - self.RATE_LIMIT_PRESSURE_WINDOW_SECONDS
        while self._account_sync_rate_limit_hits and self._account_sync_rate_limit_hits[0] < cutoff:
            self._account_sync_rate_limit_hits.popleft()
        for _ in range(max(0, hits)):
            self._account_sync_rate_limit_hits.append(now)
        return len(self._account_sync_rate_limit_hits)

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
        realtime_ws_manager.register_tick_callback(self._bar_engine.ingest_tick)
        from .position_manager import position_manager
        from .fill_poller import fill_poller

        position_manager.activate()
        if not position_manager.get_positions():
            _restore_positions_from_db(today, [])
        account_symbols = await self._run_account_sync_once()
        fill_poller.start(today)
        self._start_account_sync_loop()

        managed_symbols = [str(pos.get("symbol") or "") for pos in position_manager.get_positions()]
        symbols = list(dict.fromkeys([*candidate_symbols, *managed_symbols]))
        if not symbols:
            self._active = False
            position_manager.deactivate()
            fill_poller.stop()
            realtime_ws_manager.unregister_tick_callback(self._on_tick)
            realtime_ws_manager.unregister_tick_callback(self._bar_engine.ingest_tick)
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

    async def _run_account_sync_once(self, *, refresh_subscriptions: bool = False) -> list[str]:
        """Fetch KIS holdings once and sync PositionManager from the account SSOT.

        Args:
            refresh_subscriptions: Refresh realtime WS subscriptions when sync changes managed symbols.
        """
        self._account_sync_seq += 1
        seq = self._account_sync_seq
        trade_date = _today_kst()
        if not self._active:
            logger.info("SKIP: PositionSync trade_date=%s seq=%d reason=engine_inactive", trade_date, seq)
            return []

        started = time.perf_counter()
        kis_response_ms = 0
        rate_limit_hits = 0
        logger.info("START: PositionSync trade_date=%s seq=%d", trade_date, seq)
        try:
            from ...api.routes.account import _build_balance_payload
            from ...utils import kis_rate_limiter
            from ..kis.domestic.service import get_balance

            rate_limit_before = float(kis_rate_limiter.snapshot().get("last_rate_limited_at") or 0.0)
            kis_started = time.perf_counter()
            balance_data = await get_balance()
            kis_response_ms = int((time.perf_counter() - kis_started) * 1000)
            rate_limit_after = float(kis_rate_limiter.snapshot().get("last_rate_limited_at") or 0.0)
            if rate_limit_after > rate_limit_before:
                rate_limit_hits = 1

            account_payload = _build_balance_payload(balance_data)
            account_positions = account_payload.get("positions", [])
            if isinstance(account_positions, list):
                stats = _sync_managed_positions_with_account(account_positions, return_stats=True)
                synced = list(stats.get("synced", [])) if isinstance(stats, dict) else []
                changed = bool(
                    isinstance(stats, dict)
                    and (stats.get("added") or stats.get("removed") or stats.get("qty_changed"))
                )
                ws_resub = False
                if refresh_subscriptions and changed:
                    try:
                        ws_resub = await self._refresh_realtime_subscriptions()
                    except Exception as ws_exc:
                        logger.error("FAIL: PositionSync seq=%d reason=ws_resub_error exc=%s", seq, ws_exc)
                last_30m_hits = self._record_account_sync_rate_limit_hits(rate_limit_hits)
                if last_30m_hits > self.RATE_LIMIT_PRESSURE_WARN_THRESHOLD:
                    logger.warning("WARN: KIS rate_limit pressure high last_30m_hits=%d", last_30m_hits)
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                logger.info(
                    "SUCCESS: PositionSync seq=%d kis_response_ms=%d kis_symbols=%d managed_before=%d managed_after=%d added=%s removed=%s qty_changed=%s ws_resub=%s elapsed_ms=%d rate_limit_hits=%d",
                    seq,
                    kis_response_ms,
                    int(stats.get("kis_symbols", 0)) if isinstance(stats, dict) else 0,
                    int(stats.get("managed_before", 0)) if isinstance(stats, dict) else 0,
                    int(stats.get("managed_after", 0)) if isinstance(stats, dict) else 0,
                    stats.get("added", []) if isinstance(stats, dict) else [],
                    stats.get("removed", []) if isinstance(stats, dict) else [],
                    stats.get("qty_changed", []) if isinstance(stats, dict) else [],
                    ws_resub,
                    elapsed_ms,
                    rate_limit_hits,
                )
                return synced
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            logger.error(
                "FAIL: PositionSync seq=%d reason=kis_balance_error exc=positions_not_list elapsed_ms=%d rate_limit_hits=%d",
                seq,
                elapsed_ms,
                rate_limit_hits,
            )
        except Exception as exc:
            error_text = str(exc)
            rate_limit_hits = error_text.count("EGW00201")
            if rate_limit_hits <= 0 and "EGW00201" in error_text:
                rate_limit_hits = 1
            last_30m_hits = self._record_account_sync_rate_limit_hits(rate_limit_hits)
            if last_30m_hits > self.RATE_LIMIT_PRESSURE_WARN_THRESHOLD:
                logger.warning("WARN: KIS rate_limit pressure high last_30m_hits=%d", last_30m_hits)
            logger.error(
                "FAIL: PositionSync seq=%d reason=kis_balance_error exc=%s elapsed_ms=%d rate_limit_hits=%d",
                seq,
                exc,
                int((time.perf_counter() - started) * 1000),
                rate_limit_hits,
            )
        return []

    async def _refresh_realtime_subscriptions(self) -> bool:
        """Restart realtime subscriptions when KIS sync changes protected symbols."""
        from .position_manager import position_manager
        from ..settings_store import get_setting as _gs

        managed_symbols = [str(pos.get("symbol") or "") for pos in position_manager.get_positions()]
        # 보유종목 우선(절대 미절단) + 후보(상한 내). 후보-우선 순서면 상한 절단에서 보유가 빠진다.
        _cap = int(_gs("realtime.ws_max", 41) or 41)
        symbols = _subscription_symbols(managed_symbols, list(self._candidates.keys()), cap=_cap)
        current_symbols = list(getattr(realtime_ws_manager, "_symbols", []) or [])
        if not symbols or symbols == current_symbols:
            return False
        await realtime_ws_manager.start(symbols=symbols)
        logger.info("SUCCESS: [S6] realtime subscriptions refreshed after KIS sync symbols=%s", symbols)
        return True

    async def _account_sync_loop(self) -> None:
        """Periodically sync KIS holdings while S6 is active to keep S8 on KIS SSOT."""
        try:
            while self._active:
                await asyncio.sleep(self._account_sync_interval_seconds)
                await self._run_account_sync_once(refresh_subscriptions=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("WARN: [S6] periodic KIS account sync stopped unexpectedly error=%s", exc)

    def _start_account_sync_loop(self) -> None:
        """Start the periodic KIS account sync task if it is not already running."""
        if self._account_sync_task and not self._account_sync_task.done():
            return
        self._account_sync_task = asyncio.create_task(self._account_sync_loop(), name="s6-kis-account-sync")
        logger.info(
            "SUCCESS: [S6] periodic KIS account sync started interval=%.0fs",
            self._account_sync_interval_seconds,
        )

    async def _stop_account_sync_loop(self) -> None:
        """Stop the periodic KIS account sync task during S6 shutdown."""
        task = self._account_sync_task
        self._account_sync_task = None
        if not task or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        logger.info("SUCCESS: [S6] periodic KIS account sync stopped")

    def is_active(self) -> bool:
        """Decision Engine 활성화 여부."""
        return self._active

    async def add_momentum_candidates(self, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        """모멘텀 스캐너가 발굴한 신규 종목을 watchlist에 병합 추가 + WS 재구독(상한 가드).

        기존 _candidates/보유는 유지하고 신규만 추가한다(교체 아님). 상한 초과 시 추가분을 자른다.
        """
        today = _today_kst()
        max_sub = int(get_setting("momentum_scan.max_subscriptions", 40) or 40)
        added = 0
        added_candidates: list[dict[str, Any]] = []
        for c in candidates:
            sym = _candidate_symbol(c)
            if not sym or sym in self._candidates:
                continue
            self._candidates[sym] = c
            added_candidates.append(c)
            added += 1
        if added == 0:
            return {"ok": True, "added": 0, "subscribed": len(self._candidates)}
        # 장중 유입 종목 레짐 연동 Risk Profile 휴리스틱 배정 (plan 미배정만, LLM 없음)
        profiled = self._assign_intraday_profiles(added_candidates)
        # 보유종목 우선(절대 미구독 금지) + 후보(상한 내)
        managed = [str(p.get("symbol") or "") for p in position_manager.get_positions()]
        all_symbols = _subscription_symbols(managed, list(self._candidates.keys()), cap=max_sub)
        load_daily_rules(today, list(self._candidates.keys()))
        self._record_intraday_plan_event("momentum_scan", profiled, today)
        try:
            await realtime_ws_manager.start(all_symbols)
        except Exception as exc:
            logger.warning("WARN: [S6] 모멘텀 후보 WS 재구독 실패 — %s", exc)
        logger.info("INFO: [S6] 모멘텀 신규편입 added=%d total_candidates=%d subscribed=%d",
                    added, len(self._candidates), len(all_symbols))
        return {"ok": True, "added": added, "subscribed": len(all_symbols)}

    def _assign_intraday_profiles(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """장중 유입 후보들에 레짐 연동 휴리스틱 Risk Profile을 배정한다 (best-effort).

        plan 배정 종목은 rule_cache가 거부하므로 절대 덮어쓰지 않는다.
        load_daily_rules 호출 **전**에 등록해야 그 로드에서 오버레이가 적용된다.

        Args:
            candidates: 신규 편입 후보 dict 목록 (name/change_rate/volume_surge 사용).

        Returns:
            실제 등록된 [{symbol, name, profile, reason}] 목록 (이력 기록용).
        """
        records: list[dict[str, Any]] = []
        if not candidates:
            return records
        try:
            regime = self._current_regime()
        except Exception:
            regime = None
        for cand in candidates:
            try:
                sym = _candidate_symbol(cand)
                if not sym:
                    continue
                profile, reason = classify_profile(cand, regime)
                if set_intraday_profile(sym, profile, reason):
                    records.append({
                        "symbol": sym,
                        "name": str(cand.get("name") or ""),
                        "profile": profile,
                        "reason": reason,
                    })
            except Exception as exc:
                logger.warning("WARN: [S6] intraday profile 배정 실패 symbol=%s — %s",
                               cand.get("symbol"), exc)
        if records:
            logger.info("INFO: [S6] intraday profile 배정 regime=%s assigned=%s",
                        regime, [(r["symbol"], r["profile"]) for r in records])
        return records

    def _record_intraday_plan_event(
        self, trigger: str, profiled: list[dict[str, Any]], today: str
    ) -> None:
        """장중 신규 편입 이력을 intraday_plan_events에 기록한다 (best-effort)."""
        if not profiled:
            return
        try:
            ctx = self._build_market_context(today)
            record_intraday_event(
                trigger=trigger,
                regime=ctx.get("regime"),
                market_tone=ctx.get("market_tone"),
                symbols_added=profiled,
                trade_date=today,
            )
        except Exception as exc:
            logger.warning("WARN: [S6] intraday plan event 기록 실패 trigger=%s — %s", trigger, exc)

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
            # 신규 편입(기존 watchlist에 없던) 종목만 레짐 연동 프로파일 휴리스틱 배정
            fresh = [c for s, c in new_candidates.items() if s not in old_candidates]
            profiled = self._assign_intraday_profiles(fresh)
            load_daily_rules(today, list(new_candidates.keys()))
            self._record_intraday_plan_event("intraday_refresh", profiled, today)
        else:
            logger.warning("WARN: [S6] refresh_candidates — 새 후보 없음 (기존 후보 유지)")
            self._candidates = old_candidates
            return {"ok": False, "reason": "no_new_candidates", "old_count": len(old_candidates)}

        # WS 구독 갱신: 보유종목 우선(절대 미구독 금지) + 새 후보(상한 내)
        from .position_manager import position_manager
        from ..settings_store import get_setting as _gs
        managed_symbols = [str(pos.get("symbol") or "") for pos in position_manager.get_positions()]
        _cap = int(_gs("realtime.ws_max", 41) or 41)
        all_symbols = _subscription_symbols(managed_symbols, list(new_candidates.keys()), cap=_cap)

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

        try:
            replacement_exec = await _maybe_execute_replacements(replacement_result, new_candidates)
            logger.info("INFO: [S6] 교체 실행 결과 executed=%s", replacement_exec.get("executed"))
        except Exception as exc:
            logger.warning("WARN: [S6] 교체 실행 실패 — %s", exc)

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

        from ..settings_store import get_setting as _gs
        # 보유종목 우선(절대 미절단) + 후보(상한 내) — 후보-우선 순서면 상한 절단에서 보유가 빠진다.
        _cap = int(_gs("realtime.ws_max", 41) or 41)
        all_symbols = _subscription_symbols(managed_symbols, list(self._candidates.keys()), cap=_cap)
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
        await self._stop_account_sync_loop()
        realtime_ws_manager.unregister_tick_callback(self._on_tick)
        realtime_ws_manager.unregister_tick_callback(self._bar_engine.ingest_tick)
        from .position_manager import position_manager
        from .fill_poller import fill_poller

        fill_poller.stop()
        position_manager.deactivate()

        # 감시했으나 매수 신호를 보내지 않은 종목 → shadow_trades 기록
        # deactivate가 마감 부근에 두 번 이상 호출(스윕/EOD/재시작)돼도 같은 (날짜,종목)을
        # 중복 적재하지 않도록 기존 기록을 조회해 건너뛴다. (record_s4_unentered_shadows와 동일 가드)
        today = _today_kst()
        now_iso = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
        existing_shadow_symbols: set[str] = set()
        try:
            from ..db import get_connection

            with get_connection() as _conn:
                existing_shadow_symbols = {
                    str(r[0])
                    for r in _conn.execute(
                        "SELECT DISTINCT symbol FROM shadow_trades WHERE trade_date = ?",
                        (today,),
                    ).fetchall()
                }
        except Exception as _ex_exc:
            logger.warning("WARN: [S6] 기존 shadow 조회 실패(중복가드 생략) reason=%s", _ex_exc)
        for symbol, cand in self._candidates.items():
            if symbol in self._signal_sent or symbol in existing_shadow_symbols:
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
        from .position_manager import position_manager

        managed_symbols = {str(pos.get("symbol") or "") for pos in position_manager.get_positions()}
        if symbol in managed_symbols:
            return
        if symbol not in self._candidates or symbol in self._signal_sent:
            return

        cooldown_until = self._block_cooldown.get(symbol)
        if cooldown_until is not None:
            if time.monotonic() < cooldown_until:
                return
            self._block_cooldown.pop(symbol, None)

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
            return

    def _current_regime(self) -> str | None:
        """현재 레짐을 daily_context_snapshot 에서 조회한다(60초 TTL 인스턴스 캐시).

        틱 처리에서 매 후보마다 호출될 수 있어 DB 조회를 캐시로 막는다.
        조회 실패/레코드 없음 → None 반환(레짐 필터 미적용 = fail-open).
        """
        now = time.monotonic()
        cached = getattr(self, "_regime_cache", None)
        if cached is not None and now - cached[0] < 60.0:
            return cached[1]
        regime: str | None = None
        try:
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT regime FROM daily_context_snapshot WHERE trade_date = ? "
                    "ORDER BY created_at DESC LIMIT 1",
                    (_today_kst(),),
                ).fetchone()
                if row and row["regime"]:
                    regime = str(row["regime"])
        except Exception as exc:
            logger.warning("WARN: [S6/탐색] regime 조회 실패(fail-open) reason=%s", exc)
            regime = None
        self._regime_cache: tuple[float, str | None] = (now, regime)
        return regime

    def _record_exploration_tag(
        self, symbol: str, candidate: dict[str, Any], decision: dict[str, Any]
    ) -> None:
        """매수 신호의 선정사유·발화그룹·조건상태·시장맥락을 태깅한다.

        _emit_signal 단일 길목에서 모든 진입 경로(베이스라인/탐색OR/교체매매)에 대해
        호출된다(2026-06-10 커버리지 갭 수정 — 이전엔 탐색OR만 태깅돼 학습 표본 누락).
        order_id 는 비동기 주문 제출 전이라 알 수 없으므로 빈 문자열로 기록하고,
        EOD backfill_outcomes_for_date 가 symbol+trade_date 로 정산한다.

        Args:
            symbol: 매수 종목.
            candidate: S4 후보 dict.
            decision: {fired, condition_states} — _derive_tag_decision 결과.
        """
        try:
            from .exploration_decision import build_exploration_tag_payload
            from .trade_tagging import record_entry_tag

            today = _today_kst()
            market_context = self._build_market_context(today)
            # 엣지 발굴 계측 — 진입 미시구조 피처(체결강도·VWAP거리·고점거리 등)를 태그에 첨부.
            market_context["entry_features"] = self._entry_feature_snapshot(symbol, candidate)
            payload = build_exploration_tag_payload(
                order_id="",
                symbol=symbol,
                trade_date=today,
                candidate=candidate,
                decision=decision,
                market_context=market_context,
            )
            record_entry_tag(**payload)
        except Exception as exc:
            logger.warning("WARN: [S6/탐색] 태깅 실패 symbol=%s reason=%s", symbol, exc)

    def _entry_feature_snapshot(self, symbol: str, candidate: dict[str, Any]) -> dict[str, Any]:
        """진입 시점 미시구조 피처 스냅샷(엣지 발굴 계측).

        bar_engine(체결강도·VWAP·일중고가·틱볼륨)에서 추가 KIS 호출 없이 스냅샷을 뜬다.
        trade_entry_tags.market_context_json.entry_features 로 저장돼, EOD outcome과
        조인하면 '무엇이 승패를 가르는가'를 데이터로 발굴할 수 있다(눌림목·체결강도·고점거리 등).
        """
        try:
            be = self._bar_engine
            price = _first_float(
                candidate.get("price"), candidate.get("current_price"),
                candidate.get("trigger_price"), candidate.get("last_price"),
            )
            vwap = be.get_vwap(symbol)
            day_high = be.get_day_high(symbol) or None
            gangdo = be.get_chegyeol_gangdo(symbol)
            tickvol = be.get_tick_vol_mult(symbol)

            def _pct(a: float | None, b: float | None) -> float | None:
                return round((a / b - 1.0) * 100.0, 2) if (a and b and b > 0) else None

            return {
                "chegyeol_gangdo": round(float(gangdo), 3) if gangdo is not None else None,
                "vwap_dist_pct": _pct(price, vwap),      # >0 VWAP위 · <0 아래(눌림 후보)
                "high_dist_pct": _pct(price, day_high),  # ~0 일중고가 추격 · <0 되돌림
                "tick_vol_mult": round(float(tickvol), 2) if tickvol else None,
                "change_rate": _first_float(candidate.get("change_rate")),
                "volume_ratio": _first_float(candidate.get("volume_ratio")),
                "confidence": _first_float(candidate.get("confidence")),
                "entry_hm": _now_kst().strftime("%H:%M"),
            }
        except Exception as exc:
            logger.warning("WARN: [S6] 진입 피처 스냅샷 실패 symbol=%s reason=%s", symbol, exc)
            return {}

    def _build_market_context(self, today: str) -> dict[str, Any]:
        """태깅용 시장맥락 dict 조립 — 구현은 decision_rules(Phase 5 분해)로 위임."""
        return _rules_build_market_context(today)

    def _evaluate_rules(
        self,
        *,
        candidate: dict[str, Any],
        final_rule: dict[str, Any],
        tick: dict[str, Any],
    ) -> dict[str, Any]:
        """S6 진입 룰 평가 — 구현은 decision_rules(Phase 5 분해)로 위임(engine._evaluate_rules 인터페이스 보존)."""
        return _rules_evaluate_rules(candidate=candidate, final_rule=final_rule, tick=tick)

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
        # 매매기법 보정(2026-06-22): 레버리지/인버스 2X는 거래당 기대값이 구조적 음(-)
        # (R:R 0.89·승률 12%·거래당 -40만원)이라 신규 진입을 차단한다. 모든 진입 경로
        # (베이스라인·탐색OR·모멘텀스캔·교체매매)가 이 단일 길목을 지나므로 여기서 한 번에 막는다.
        # engine.leverage_restriction_mode=off 면 구동작(허용). 보유분 청산은 영향 없음(진입만 차단).
        _name = str(candidate.get("name") or "")
        try:
            _lev_mode = str(get_setting("engine.leverage_restriction_mode", "exclude") or "exclude").lower()
        except Exception:
            _lev_mode = "exclude"
        if _lev_mode != "off":
            from .intraday_profile import is_inverse_1x_product, is_leverage_product
            if is_leverage_product(_name):
                # P3-5 폭락장 플레이북: 급락 방어 모드에서 인버스 1x만 예외 허용
                # (2X/레버리지는 구조적 감쇄로 계속 차단).
                _playbook_ok = False
                try:
                    if bool(get_setting("engine.crash_playbook_enabled", True)) and is_inverse_1x_product(_name):
                        from .intraday_regime_monitor import is_flash_crash_defense_active
                        _playbook_ok = is_flash_crash_defense_active()
                except Exception:
                    _playbook_ok = False
                if not _playbook_ok:
                    logger.info("INFO: [S6] SKIP 레버리지/인버스 진입 차단 symbol=%s name=%s (mode=%s)", symbol, _name, _lev_mode)
                    return
                logger.info("INFO: [S6] 인버스 1x 플레이북 허용 — 급락 방어 모드 symbol=%s name=%s", symbol, _name)

        confidence = _candidate_confidence(candidate)

        # ── Phase 2·3 진입 선별성 게이트 — 모든 진입 경로의 단일 길목 ──
        gate_reason = _entry_gate_block_reason(symbol, confidence, name=_name)
        if gate_reason:
            logger.info("INFO: [S6] SKIP 진입 게이트 차단 symbol=%s reason=%s", symbol, gate_reason)
            return

        # 눌림목 게이트(P-EDGE) — 데이터 확증 엣지(17일 백테스트: VWAP 아래 진입 승률 51→61%·흑자,
        # 꼭지추격 39%). 진입가가 VWAP보다 임계%(기본 0) 넘게 위(=추격)면 차단해 "VWAP 지지 부근/아래"
        # 진입으로 유도. mode=shadow는 로그만(무매매), off는 비활성. VWAP 미가용 시 fail-open.
        try:
            from .buy_engine import resolve_buy_gates
            _gates = resolve_buy_gates()  # ④ 매수 엔진에서 게이트 파라미터(get_playbook 경유)
            vwap_mode = str(_gates.get("vwap_pullback_mode", "enforce"))
            if vwap_mode != "off":
                max_dist = float(_gates.get("entry_max_vwap_dist_pct", 0.0))
                vwap_dist = _vwap_pullback_gate(self._bar_engine.get_vwap(symbol), price, max_dist)
                if vwap_dist is not None and vwap_mode == "shadow":
                    logger.info(
                        "SHADOW: [S6] 눌림목게이트 차단대상(로그만) symbol=%s vwap_dist=%.2f > %.2f",
                        symbol, vwap_dist, max_dist,
                    )
                elif vwap_dist is not None:
                    logger.info(
                        "INFO: [S6] SKIP 눌림목게이트 — VWAP 위 이격(추격) symbol=%s vwap_dist=%.2f > %.2f",
                        symbol, vwap_dist, max_dist,
                    )
                    return
        except Exception as exc:
            logger.warning("WARN: [S6] 눌림목 게이트 실패(fail-open) symbol=%s reason=%s", symbol, exc)

        # 9시 조기진입 shadow 실험 — entry_start_time을 09:00으로 열되 실제 매수는
        # entry_execute_start_time(기본 09:30)부터. 그 이전(모든 게이트 통과한 후보)은 로그만
        # 남겨 "상승장 조기진입" 가설을 무매매로 검증한다. fail-safe: exec_start 전엔 항상 차단.
        exec_start = "09:30"
        try:
            exec_start = _get_setting_str("engine.entry_execute_start_time", "09:30")
        except Exception:
            pass
        now_hm = _now_kst().strftime("%H:%M")
        if now_hm < exec_start:
            try:
                _vw = self._bar_engine.get_vwap(symbol)
                _vd = round((price / _vw - 1) * 100, 2) if (_vw and price) else None
                logger.info(
                    "SHADOW_EARLY: [S6] 9시조기진입 후보(로그만·무매매) symbol=%s time=%s price=%.0f vwap_dist=%s",
                    symbol, now_hm, price, _vd,
                )
            except Exception:
                logger.info("SHADOW_EARLY: [S6] 9시조기진입 후보 symbol=%s time=%s", symbol, now_hm)
            return  # exec_start(09:30) 전에는 실제 매수 차단(shadow만)

        today = _today_kst()
        signal_id = str(uuid.uuid4())
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
        # 통짜 태깅 — 모든 진입 경로의 단일 길목. 실패해도 신호/주문 흐름은 막지 않는다.
        self._record_exploration_tag(symbol, candidate, _derive_tag_decision(matched))
        from .order_executor import order_executor

        async def _execute_and_track() -> None:
            """Submit the signal and release re-signaling if preflight blocks it."""
            try:
                result = await order_executor.execute_signal(
                    {
                        "id": signal_id,
                        "symbol": symbol,
                        "name": candidate.get("name", ""),
                        "trigger_price": price,
                        "confidence": confidence,
                    }
                )
            except Exception as exc:
                logger.warning("WARN: [S6] order_executor task crashed symbol=%s reason=%s", symbol, exc)
                self._signal_sent.discard(symbol)
                self._block_cooldown[symbol] = time.monotonic() + self.BLOCK_COOLDOWN_SECONDS
                return

            if not (result or {}).get("ok"):
                reason = (result or {}).get("reason", "unknown")
                self._signal_sent.discard(symbol)
                self._block_cooldown[symbol] = time.monotonic() + self.BLOCK_COOLDOWN_SECONDS
                logger.info(
                    "INFO: [S6] signal blocked — released for re-signaling symbol=%s reason=%s cooldown=%.0fs",
                    symbol, reason, self.BLOCK_COOLDOWN_SECONDS,
                )

        asyncio.create_task(_execute_and_track())


def _subscription_symbols(held: list[str], candidates: list[str], *, cap: int) -> list[str]:
    """WS 구독 목록 = 보유(전부, 맨 앞) + 후보(상한 내). 보유는 절대 잘리지 않는다.

    2026-06-11: refresh_candidates가 [후보..., 보유...] 순서로 만들어 매니저 상한(41)
    절단에서 보유가 떨어져 손절 틱 공백이 생기던 버그의 단일 출처 수정.
    """
    out = list(dict.fromkeys(s for s in held if s))
    for sym in candidates:
        if not sym or sym in out:
            continue
        if len(out) >= cap:
            continue
        out.append(sym)
    return out


def _derive_tag_decision(matched: dict[str, Any]) -> dict[str, Any]:
    """_emit_signal의 matched dict에서 태깅용 {fired, condition_states}를 유도한다.

    진입 경로 판별: 탐색OR(fired_groups 보유) > 교체매매(replacement) > 베이스라인 게이트.
    베이스라인은 observed_values(관측값)와 matched(조건 통과 여부)를 합쳐 보존한다.
    """
    if matched.get("fired_groups"):
        return {
            "fired": list(matched["fired_groups"]),
            "condition_states": dict(matched.get("condition_states") or {}),
        }
    if matched.get("replacement"):
        return {"fired": ["교체매매"], "condition_states": dict(matched.get("condition_states") or {})}
    states: dict[str, Any] = {}
    states.update(matched.get("matched") or {})
    states.update(matched.get("observed_values") or {})
    return {"fired": ["베이스라인(기존게이트)"], "condition_states": states}


decision_engine = DecisionEngine()


async def _maybe_execute_replacements(replacement_result: dict, new_candidates: dict | None = None) -> dict:
    """교체 신호가 있으면 자동 실행기로 넘긴다(없으면 no-op)."""
    signals = replacement_result.get("signals") or []
    if not signals:
        return {"ok": True, "executed": 0}
    from .replacement_executor import execute_replacements
    if new_candidates is None:
        return await execute_replacements(signals)
    return await execute_replacements(signals, new_candidates)


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
