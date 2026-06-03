"""한국 증시 거래일/휴장일 판정 단일 소스.

주말 + 한국 공휴일(holidays 라이브러리)을 휴장으로 본다. KIS chk-holiday API가
모의투자에서 미지원이라, 이 모듈이 신뢰 가능한 폴백 겸 단일 기준이 된다.
임시공휴일·대체공휴일은 holidays 라이브러리가 매년 자동 반영한다.
"""
from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache

import holidays


@lru_cache(maxsize=8)
def _kr_holidays(year: int) -> holidays.HolidayBase:
    """연도별 한국 공휴일 셋(캐시)."""
    return holidays.SouthKorea(years=year)


def _to_date(value: str | date | datetime) -> date:
    """YYYY-MM-DD / YYYYMMDD / date / datetime 을 date로 정규화한다."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if "-" in text:
        return datetime.strptime(text, "%Y-%m-%d").date()
    return datetime.strptime(text, "%Y%m%d").date()


def is_trading_day(value: str | date | datetime) -> bool:
    """해당 날짜가 한국 증시 거래일인지(주말·공휴일이 아니면 True)."""
    d = _to_date(value)
    if d.weekday() >= 5:  # 토(5)/일(6)
        return False
    return d not in _kr_holidays(d.year)


def non_trading_reason(value: str | date | datetime) -> str | None:
    """비거래일이면 사유('weekend'|'휴장일명'), 거래일이면 None."""
    d = _to_date(value)
    if d.weekday() >= 5:
        return "weekend"
    name = _kr_holidays(d.year).get(d)
    return name if name else None
