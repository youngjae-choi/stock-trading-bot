"""계좌 수익·평가 단일 계산 소스(SSOT). 모든 페이지/엔드포인트가 이걸 호출한다.

원칙:
- 누적 % 는 원금(principal) 기준으로 나눈다 (현금으로 나누는 버그 금지).
- cumulative_pnl = total_eval - principal (계좌 진실).
- daily_pnl = total_eval - 장시작 total_eval baseline (자본변화 A안). baseline 없으면 None.
- daily_return_pct 는 '계좌 잔고 대비'(당일 시작 baseline 기준)로 나눈다. PM 정의: 하루 목표
  2%는 총자산 대비 매일 복리(2026-07-06). 누적%(원금 기준)와 분모가 다름에 유의.
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


# ══ 계좌 당일손익(종가-종가, close-to-close) SSOT — Daily Results·Statistics·리뷰 공유 ══
# equity_pnl(장시작 baseline 대비 자본변화, intraday)은 간밤 갭을 제외해 '전일 대비 계좌 성장'과
# 다르다. PM 정의('당일 20만원 수익' = 전일 종가 대비)와 Daily Results 표가 쓰는 값이 이것이다.
# 하드코딩 앵커: 계좌 전환·리셋으로 종가총평가 이력이 끊긴 지점의 시작값. (PM 2026-07-23: 1억 리셋)
_EOD_ANCHORS: dict[str, float] = {"2026-07-23": 100_000_000.0}


def load_eod_total_eval_by_date() -> dict[str, float]:
    """거래일별 종가총평가(equity_eod_total_eval) 맵 — daily_review_reports + 하드코딩 앵커."""
    from ..db import get_connection

    out: dict[str, float] = {}
    try:
        with get_connection() as conn:
            for r in conn.execute(
                "SELECT trade_date, equity_eod_total_eval FROM daily_review_reports "
                "WHERE equity_eod_total_eval IS NOT NULL ORDER BY trade_date"
            ).fetchall():
                out[str(r["trade_date"])] = float(r["equity_eod_total_eval"])
    except Exception as exc:
        logger.warning("WARN: 종가총평가 이력 조회 실패 — %s", exc)
    out.update(_EOD_ANCHORS)
    return out


def _prior_eod(eod_by_date: dict[str, float], trade_date: str) -> float | None:
    """trade_date 직전(<) 거래일의 종가총평가. 없으면 None."""
    import bisect

    dates = sorted(eod_by_date.keys())
    i = bisect.bisect_left(dates, trade_date)
    return eod_by_date[dates[i - 1]] if i > 0 else None


def daily_account_pnl(trade_date: str, eod_by_date: dict[str, float] | None = None) -> dict[str, Any]:
    """계좌 당일손익(종가-종가, close-to-close) 단일 계산 소스.

    = 종가총평가[trade_date] − 종가총평가[직전 거래일]. Daily Results·Statistics·리뷰
    헤드라인이 이 하나를 공유해 화면간 당일손익이 일치한다.

    Args:
        trade_date: 대상 거래일(YYYY-MM-DD).
        eod_by_date: 미리 로드한 종가총평가 맵(다건 반복 호출 최적화). None이면 조회.

    반환: {account_pnl, eod_total_eval, prior_eod, available}. eod/prior 결손이면 available=False·account_pnl=None.
    """
    m = eod_by_date if eod_by_date is not None else load_eod_total_eval_by_date()
    eod = m.get(trade_date)
    prior = _prior_eod(m, trade_date)
    if eod is None or prior is None:
        return {
            "account_pnl": None,
            "account_pnl_pct": None,
            "eod_total_eval": eod,
            "prior_eod": prior,
            "available": False,
        }
    pnl = round(eod - prior)
    # 수익률은 전일 종가총평가 대비(계좌 잔고 대비 복리) — Daily Results RETURN 컬럼과 동일.
    pct = round((eod - prior) / prior * 100, 2) if prior else None
    return {
        "account_pnl": pnl,
        "account_pnl_pct": pct,
        "eod_total_eval": eod,
        "prior_eod": prior,
        "available": True,
    }


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

    # 당일: 전일 종가총평가(prev EOD) 대비 — 계좌(종가-종가) SSOT와 동일 기준(2026-08-24 PM 통일).
    # 라이브 total_eval − 전일 종가총평가. 전일 eod 없으면 None(허위 0 금지). baseline을 9시→전일종가로
    # 바꿔 EOD 요약(Daily Results·리뷰)과 라이브 화면(Today Control·Trading Monitor)의 당일손익을 일치시킨다.
    # 전일종가 baseline도 매일 리셋되므로 '계좌 잔고 대비 복리'(PM 2026-07-06) 원칙은 유지된다.
    daily_pnl: int | None = None
    daily_return_pct: float | None = None
    daily_baseline_available = False
    try:
        from datetime import datetime as _dt2
        from zoneinfo import ZoneInfo as _ZI2

        _td = trade_date or _dt2.now(_ZI2("Asia/Seoul")).strftime("%Y-%m-%d")
        prior_eod = _prior_eod(load_eod_total_eval_by_date(), _td)
        if prior_eod and prior_eod > 0 and total_eval > 0:
            daily_pnl = int(total_eval - prior_eod)
            daily_baseline_available = True
            daily_return_pct = round(daily_pnl / prior_eod * 100, 2)
    except Exception as exc:
        logger.warning("WARN: 전일 종가총평가(당일손익 baseline) 조회 실패 — %s", exc)
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
