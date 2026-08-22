"""decision_engine 후보 파싱·계좌 보유 편입·S8 포지션 동기화 헬퍼 (Phase 3 분해, 2026-08-22).

KIS 실잔고와 S8 관리 포지션을 정합(_sync_managed_positions_with_account)하고, KIS-only 보유를
자동 편입하며, 자동편입 진입가를 원가 근거 우선순위로 결정한다. 로직은 원본과 100% 동일(순수 이동).
로거명 'DecisionEngine' 유지. position_manager·position_cost_basis는 원본처럼 함수-지역 지연
import라 순환참조가 없다(position_manager가 decision_engine을 역참조). decision_engine이 재-export한다.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection
from .decision_engine_utils import _first_positive_float
from .rule_cache import get_rule
from .symbol_norm import norm_symbol, symbol_variants

logger = logging.getLogger("DecisionEngine")


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
    # ETN은 매수가 Q-형('Q520100'), KIS 잔고가 무Q('520100')로 와서 형이 갈릴 수 있어 변형 IN 매칭
    variants = symbol_variants(symbol)
    if not variants:
        return False
    placeholders = ",".join("?" for _ in variants)
    with get_connection() as conn:
        row = conn.execute(
            f"""
            SELECT id FROM trading_orders
            WHERE symbol IN ({placeholders}) AND side = 'buy' AND status IN ('submitted', 'filled')
              AND created_at >= ?
            LIMIT 1
            """,
            (*variants, cutoff),
        ).fetchone()
    return row is not None


def _account_holding_qty(holding: dict[str, Any]) -> int:
    """Return a parsed positive KIS holding quantity, or zero when invalid.

    Args:
        holding: Public account position payload from _build_balance_payload().
    """
    try:
        return int(float(str(holding.get("qty") or 0).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def _account_holding_entry_price(holding: dict[str, Any]) -> float:
    """Return the KIS average purchase price used for imported S8 stop state.

    Args:
        holding: Public account position payload from _build_balance_payload().
    """
    return _first_positive_float(
        holding.get("avg_price"),
        holding.get("entry_price"),
        holding.get("current_price"),
    ) or 0.0


def _resolve_import_entry_price(symbol: str, kis_avg: float) -> tuple[float, str]:
    """자동편입 포지션의 진입가를 원가 근거 우선순위로 결정한다.

    KIS 평균매입가는 모의계좌에서 부분매도 직후 실매수가와 다르게 내려오는 사례가
    있어(2026-07-08: 6,480 매수 → KIS avg 6,364로 편입 → 진입가 아래에서 익절 태깅),
    실제 원가 근거를 우선한다:
      1. 오늘 체결된 매수 주문의 수량가중 평균가 (trading_orders)
      2. cost_basis 원장 (이월 포지션의 매수측 원가 SSOT)
      3. KIS 평균매입가 (폴백)

    Returns:
        (entry_price, source) — source는 로그 추적용.
    """
    safe_symbol = str(symbol or "").strip()
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    try:
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT SUM(qty * price) * 1.0 / SUM(qty) AS avg_price
                FROM trading_orders
                WHERE symbol = ? AND trade_date = ? AND side = 'buy'
                  AND status IN ('filled', 'partial') AND price > 0 AND qty > 0
                """,
                (safe_symbol, today),
            ).fetchone()
        if row is not None:
            avg = row["avg_price"]
            if avg is not None and float(avg) > 0:
                return float(avg), "today_buy_orders"
    except Exception as exc:
        logger.warning("WARN: [S6] 편입 진입가 매수주문 조회 실패 symbol=%s reason=%s", safe_symbol, exc)
    try:
        from .position_cost_basis import get_cost_basis

        ledger = get_cost_basis(safe_symbol, today)
        if ledger and float(ledger.get("avg_price") or 0) > 0:
            return float(ledger["avg_price"]), "cost_basis"
    except Exception as exc:
        logger.warning("WARN: [S6] 편입 진입가 원장 조회 실패 symbol=%s reason=%s", safe_symbol, exc)
    return float(kis_avg or 0), "kis_avg"


def _import_rule_for_account_holding(symbol: str) -> dict[str, Any]:
    """Return the active risk rule for a KIS-imported holding with LOW_VOL fallback.

    Args:
        symbol: KIS holding symbol.
    """
    rule = dict(get_rule(symbol) or {})
    if not rule.get("profile_assigned"):
        rule["profile_assigned"] = "LOW_VOL"
    return rule


def _sync_managed_positions_with_account(
    account_positions: list[dict[str, Any]],
    *,
    return_stats: bool = False,
) -> list[str] | dict[str, Any]:
    """Align S8-managed positions to KIS real holdings and import KIS-only holdings.

    Positions with a recent submitted/filled buy order are NOT removed even if KIS
    balance does not yet reflect them — KIS settlement can lag 1-3 minutes after order
    placement (race condition between S7 and S8 activation sync).

    Args:
        account_positions: Public account positions from the KIS balance API.
        return_stats: When True, return analysis-friendly sync deltas instead of only symbols.
    """
    from .position_manager import position_manager

    # KIS 잔고는 무Q('520100'), 메모리 포지션은 진입 시 Q-형('Q520100')일 수 있어
    # 매칭 키는 norm_symbol로 통일한다. position_manager 호출·신규 등록은 원본 심볼 유지.
    holdings: dict[str, dict[str, Any]] = {}
    for item in account_positions:
        raw_symbol = str(item.get("symbol") or "").strip()
        if raw_symbol:
            holdings[norm_symbol(raw_symbol)] = item
    synced: list[str] = []
    managed_symbols: set[str] = set()
    before_positions = position_manager.get_positions()
    before_qty = {
        str(position.get("symbol") or "").strip(): int(position.get("qty") or 0)
        for position in before_positions
        if str(position.get("symbol") or "").strip()
    }
    removed: list[str] = []
    qty_changed: list[tuple[str, int, int]] = []
    added: list[str] = []
    for position in before_positions:
        symbol = str(position.get("symbol") or "").strip()
        if not symbol:
            continue
        managed_symbols.add(norm_symbol(symbol))
        holding = holdings.get(norm_symbol(symbol))
        if not holding:
            if _has_recent_submitted_buy(symbol):
                logger.info(
                    "INFO: [S6] KIS 잔고 미존재 but 최근 매수 주문 있음 → S8 포지션 유지 symbol=%s",
                    symbol,
                )
                continue
            position_manager.remove_position(symbol)
            removed.append(symbol)
            logger.warning("WARN: [S6] KIS 잔고 미존재 S8 포지션 제거 symbol=%s", symbol)
            continue
        qty = _account_holding_qty(holding)
        if qty <= 0:
            if _has_recent_submitted_buy(symbol):
                logger.info(
                    "INFO: [S6] KIS 수량 0 but 최근 매수 주문 있음 → S8 포지션 유지 symbol=%s",
                    symbol,
                )
                continue
            position_manager.remove_position(symbol)
            removed.append(symbol)
            logger.warning("WARN: [S6] KIS 수량 0 S8 포지션 제거 symbol=%s", symbol)
            continue
        if position_manager.update_position_quantity(symbol, qty):
            synced.append(symbol)
            previous_qty = before_qty.get(symbol, 0)
            if previous_qty != qty:
                qty_changed.append((symbol, previous_qty, qty))

    imported = 0
    for holding_key, holding in holdings.items():
        if holding_key in managed_symbols:
            continue
        # 신규 등록은 KIS 원본 심볼 그대로 (정규화 키는 매칭 전용)
        symbol = str(holding.get("symbol") or "").strip()
        qty = _account_holding_qty(holding)
        kis_entry = _account_holding_entry_price(holding)
        entry_price, entry_source = _resolve_import_entry_price(symbol, kis_entry)
        if qty <= 0 or entry_price <= 0:
            logger.warning(
                "WARN: [S6] KIS 보유 포지션 자동등록 스킵 symbol=%s qty=%s entry=%s",
                symbol,
                qty,
                entry_price,
            )
            continue
        if entry_source != "kis_avg" and abs(entry_price - kis_entry) > 1e-9:
            logger.info(
                "INFO: [S6] 편입 진입가 보정 symbol=%s kis_avg=%.2f → %.2f (source=%s)",
                symbol, kis_entry, entry_price, entry_source,
            )
        if position_manager.sync_account_position(
            symbol=symbol,
            name=str(holding.get("name") or ""),
            qty=qty,
            entry_price=entry_price,
            final_rule=_import_rule_for_account_holding(symbol),
        ):
            synced.append(symbol)
            imported += 1
            added.append(symbol)
            logger.info(
                "EVENT: position auto_imported symbol=%s name=%s qty=%d entry_price=%.2f profile=%s detection_reason=kis_only_holding",
                symbol,
                str(holding.get("name") or ""),
                qty,
                entry_price,
                _import_rule_for_account_holding(symbol).get("profile_assigned", "LOW_VOL"),
            )
    logger.info(
        "SUCCESS: [S6] KIS 실잔고 기준 S8 동기화 count=%d imported=%d",
        len(synced),
        imported,
    )
    if return_stats:
        after_positions = position_manager.get_positions()
        return {
            "synced": synced,
            "managed_before": len(before_positions),
            "managed_after": len(after_positions),
            "added": added,
            "removed": removed,
            "qty_changed": qty_changed,
            "imported": imported,
            "kis_symbols": len(holdings),
        }
    return synced
