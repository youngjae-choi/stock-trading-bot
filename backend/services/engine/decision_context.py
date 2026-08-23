"""decision_engine 시간·일별 컨텍스트 헬퍼 (Phase 2 분해, 2026-08-22).

KST 시각, 거래일 계산, signals 테이블 보장, 장후 sentiment 로드, 그리고 S6 activate 시점의
daily_context_snapshot 저장을 담당한다. 로직은 원본과 100% 동일(순수 이동). 로거 이름도
"DecisionEngine"으로 유지해 로그 출력을 보존한다. decision_engine이 재-export한다.

sibling 모듈(trading_calendar·evening_briefing·market_tone·rulepack_generation·
regime_set_service)은 모두 함수-지역 지연 import라 순환참조가 없다.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ..db import get_connection
from ..settings_store import get_setting
from .decision_engine_utils import _to_float_or_none

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


def _prev_trading_day(today: str, max_lookback: int = 7) -> str | None:
    """today 직전 거래일(YYYY-MM-DD)을 trading_calendar 기준으로 찾는다.

    별도 헬퍼가 없어 is_trading_day로 하루씩 거슬러 올라간다(주말·휴장 스킵).
    """
    try:
        from .trading_calendar import is_trading_day

        base = datetime.strptime(today, "%Y-%m-%d").date()
    except Exception:
        return None
    for back in range(1, max_lookback + 1):
        cand = base - timedelta(days=back)
        try:
            if is_trading_day(cand):
                return cand.strftime("%Y-%m-%d")
        except Exception:
            continue
    return None


def _load_prev_evening_sentiment(today: str) -> str | None:
    """직전 거래일 장후 브리핑 sentiment를 로드한다. 없으면 None."""
    prev = _prev_trading_day(today)
    if not prev:
        return None
    try:
        from .evening_briefing import get_evening_briefing

        row = get_evening_briefing(prev)
    except Exception:
        return None
    if not row:
        return None
    sentiment = row.get("sentiment")
    return str(sentiment) if sentiment else None


def _save_daily_context_snapshot(today: str) -> None:
    """오늘의 레짐과 RulePack 파라미터를 daily_context_snapshot에 저장한다.

    Args:
        today: Snapshot 대상 거래일(YYYY-MM-DD). S6 activate 시점에 호출되며 실패해도 거래 흐름은 유지한다.
    """
    try:
        from .market_tone import get_today_morning_context

        ctx = get_today_morning_context(today) or {}
        # RulePack 제거(2026-08-23 PM) — 스냅샷의 rulepack/risk 필드는 빈값(손절/트레일은
        # 진입 시 레짐SET/프로필이 결정, 이 스냅샷은 기록용).
        rulepack: dict = {}
        machine_rules: dict = {}
        risk: dict = {}
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
            from ..regime_set_service import compute_confidence_adjustment

            market_data = ctx.get("market_data") if isinstance(ctx.get("market_data"), dict) else {}
            vix_data = market_data.get("vix") if isinstance(market_data.get("vix"), dict) else {}
            kospi_data = market_data.get("kospi") if isinstance(market_data.get("kospi"), dict) else {}
            regime_label = str(ctx.get("regime") or "neutral")
            vix_value = _to_float_or_none(vix_data.get("price") if isinstance(vix_data, dict) else None)
            kospi_change = _to_float_or_none(kospi_data.get("change_pct") if isinstance(kospi_data, dict) else None)

            # Phase2: 전날 장후 브리핑 sentiment vs 당일 아침 regime 정렬 → 신뢰도 보정.
            evening_alignment: str | None = None
            confidence_adjustment = 0.0
            try:
                if bool(get_setting("regime.evening_confidence_enabled", True)):
                    evening_sentiment = _load_prev_evening_sentiment(today)
                    evening_alignment, confidence_adjustment = compute_confidence_adjustment(
                        regime_label, evening_sentiment
                    )
                    logger.info(
                        "INFO: [S6] evening confidence trade_date=%s morning_regime=%s "
                        "prev_evening=%s alignment=%s adjustment=%+.2f",
                        today,
                        regime_label,
                        evening_sentiment,
                        evening_alignment,
                        confidence_adjustment,
                    )
            except Exception as conf_exc:
                logger.warning("WARN: [S6] evening confidence 계산 실패 (보정 0) - %s", conf_exc)
                evening_alignment, confidence_adjustment = None, 0.0

            match_regime_set(
                regime_label,
                vix_value,
                kospi_change,
                today,
                evening_alignment=evening_alignment,
                confidence_adjustment=confidence_adjustment,
            )
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
