"""계좌 수익·평가 단일 계산 소스(SSOT). 모든 페이지/엔드포인트가 이걸 호출한다.

원칙:
- 모든 % 는 원금(principal) 기준으로 나눈다 (현금으로 나누는 버그 금지).
- cumulative_pnl = total_eval - principal (계좌 진실).
- daily_pnl = total_eval - 장시작 total_eval baseline (자본변화 A안). baseline 없으면 None.
"""

from __future__ import annotations

import logging
from typing import Any

from ..settings_store import get_setting

logger = logging.getLogger("AccountPnl")


def _to_float(value: Any, default: float = 0.0) -> float:
    """KIS numeric string -> float (콤마/공백 허용, 변환 불가 시 default)."""
    try:
        return float(str(value).replace(",", "").strip() or default)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    """KIS numeric string -> int (소수/콤마 허용)."""
    return int(_to_float(value, float(default)))


def _principal() -> int:
    """settings account.principal (기본 1억). 조회 실패 시 기본값."""
    try:
        return int(_to_float(get_setting("account.principal", 100000000), 100000000))
    except Exception:
        return 100000000


def compute_account_pnl(balance: dict, *, trade_date: str | None = None) -> dict:
    """KIS balance(get_balance 결과)로 단일 수익 지표를 계산한다.

    balance: get_balance() 반환(dict, output1=보유목록, output2=[summary]).
    trade_date: 당일 baseline 조회 기준일(YYYY-MM-DD). None이면 KST 오늘.

    반환 dict:
      principal, total_eval, cash(주문가능), deposit, stock_eval, purchase_total,
      cumulative_pnl, cumulative_return_pct,
      unrealized_pnl, unrealized_pct,
      realized_pnl,                          # = cumulative - unrealized
      daily_pnl, daily_return_pct,           # baseline 없으면 둘 다 None
      daily_baseline_available: bool,
      deployed_rate_pct,
      today_realized_pnl                     # trade_pairs 기준(보조)
    """
    summary_rows = balance.get("output2") or []
    summary = summary_rows[0] if summary_rows else {}

    principal = _principal()

    total_eval = _to_int(summary.get("tot_evlu_amt"))
    stock_eval = _to_int(summary.get("scts_evlu_amt"))
    purchase_total = _to_int(summary.get("pchs_amt_smtl_amt"))
    unrealized_pnl = _to_int(summary.get("evlu_pfls_smtl_amt"))
    deposit = _to_int(summary.get("dnca_tot_amt"))

    # 주문가능현금(cash): account.py와 동일 로직.
    #   실계좌: ord_psbl_cash 우선. 모의/0이면 total_eval - stock_eval 근사.
    ord_psbl_cash = _to_int(summary.get("ord_psbl_cash"))
    if ord_psbl_cash > 0:
        cash = ord_psbl_cash
    elif total_eval > 0 and stock_eval >= 0:
        cash = max(0, total_eval - stock_eval)
    else:
        cash = 0
        for key in ("nxdy_excc_amt", "prvs_rcdl_excc_amt", "dnca_tot_amt"):
            candidate = _to_int(summary.get(key))
            if candidate > 0:
                cash = candidate
                break

    # 누적: 시드(원금) 대비. % 는 항상 원금으로 나눈다.
    if principal > 0:
        cumulative_pnl = total_eval - principal
        cumulative_return_pct = round((total_eval - principal) / principal * 100, 2)
        unrealized_pct = round(unrealized_pnl / principal * 100, 2)
    else:
        cumulative_pnl = 0
        cumulative_return_pct = 0.0
        unrealized_pct = 0.0

    # 실현 = 누적 - 미실현.
    realized_pnl = cumulative_pnl - unrealized_pnl

    # 당일: 장시작 total_eval baseline 기준(자본변화 A안). 없으면 None.
    daily_pnl: int | None = None
    daily_return_pct: float | None = None
    daily_baseline_available = False
    try:
        from .daily_capital import get_total_eval_baseline

        base = get_total_eval_baseline(trade_date)
        if base and base > 0 and total_eval > 0:
            daily_pnl = int(total_eval - base)
            daily_baseline_available = True
            if principal > 0:
                daily_return_pct = round(daily_pnl / principal * 100, 2)
            else:
                daily_return_pct = 0.0
    except Exception as exc:
        logger.warning("WARN: daily baseline 조회 실패 — %s", exc)
        daily_pnl = None
        daily_return_pct = None
        daily_baseline_available = False

    # 보조: 당일 청산 실현손익(trade_pairs FIFO 기준).
    today_realized_pnl = 0
    try:
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo as _ZI

        from .trade_pairs import get_today_realized_pnl

        _d = trade_date or _dt.now(_ZI("Asia/Seoul")).strftime("%Y-%m-%d")
        today_realized_pnl = int(get_today_realized_pnl(_d))
    except Exception as exc:
        logger.warning("WARN: today_realized_pnl 조회 실패 — %s", exc)
        today_realized_pnl = 0

    deployed_rate_pct = round((total_eval - cash) / total_eval * 100, 1) if total_eval else 0.0

    return {
        "principal": principal,
        "total_eval": total_eval,
        "cash": cash,
        "deposit": deposit,
        "stock_eval": stock_eval,
        "purchase_total": purchase_total,
        "cumulative_pnl": cumulative_pnl,
        "cumulative_return_pct": cumulative_return_pct,
        "unrealized_pnl": unrealized_pnl,
        "unrealized_pct": unrealized_pct,
        "realized_pnl": realized_pnl,
        "daily_pnl": daily_pnl,
        "daily_return_pct": daily_return_pct,
        "daily_baseline_available": daily_baseline_available,
        "deployed_rate_pct": deployed_rate_pct,
        "today_realized_pnl": today_realized_pnl,
    }
