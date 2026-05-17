"""배당락일 유틸리티.

KIS API에는 배당락일을 직접 조회하는 공식 endpoint가 없다.
배당락일은 PM이 직접 입력하며, 이 모듈은 날짜 유효성 검사만 제공한다.
"""

from __future__ import annotations

import logging
from datetime import date

logger = logging.getLogger("DividendService")


def validate_ex_date(ex_date_str: str | None) -> tuple[bool, str]:
    """배당락일 문자열 유효성 검사.

    Returns:
        (is_valid, message)
    """
    if not ex_date_str:
        return False, "배당락일을 입력해 주세요."
    try:
        d = date.fromisoformat(ex_date_str)
    except ValueError:
        return False, "날짜 형식이 올바르지 않습니다 (YYYY-MM-DD)."
    if d < date.today():
        return False, "이미 지난 날짜입니다. 미래 날짜를 입력하세요."
    return True, ""
