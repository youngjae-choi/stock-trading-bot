"""비교/매칭용 심볼 정규화 — ETN 'Q'+6자리 변형 통일 (P1-T3).

배경(2026-06-11): 랭킹 API는 ETN을 'Q520100' 형식으로 주고, KIS 잔고·매도는
'520100'으로 온다. 매수는 Q-형, 매도는 무Q-형으로 기록돼 FIFO 짝맞춤 실패,
무결성 오류(buy 0 / sell 614), 중복매도 가드 무력화가 발생했다.

원칙: 정규화는 **비교/매칭 시점에만** 사용한다.
주문 제출·표시·DB 저장은 원본 심볼을 그대로 유지한다.
"""

from __future__ import annotations

import re

_ETN_Q_PATTERN = re.compile(r"Q\d{6}")
_BARE_CODE_PATTERN = re.compile(r"\d{6}")


def norm_symbol(symbol) -> str:
    """비교/매칭용 심볼 정규화 — ETN 'Q'+6자리 → 6자리. 주문 제출에는 사용 금지.

    규칙:
    - 대문자 'Q' 뒤에 숫자 정확히 6자리인 경우만 Q를 제거한다.
    - '0192S0' 같은 영숫자 ETF/ETN 코드와 일반 6자리 코드는 그대로 둔다.
    - 소문자 'q520100'은 KIS 정식 코드가 아니므로 정규화하지 않는다(원본 유지).
      소문자 심볼이 관측되면 정규화로 가리지 말고 데이터 원인을 조사한다.
    - 앞뒤 공백은 제거한다. None/비문자열 입력은 str 변환 후 처리한다.

    Args:
        symbol: 원본 심볼(임의 타입 허용).
    """
    s = str(symbol or "").strip()
    if _ETN_Q_PATTERN.fullmatch(s):
        return s[1:]
    return s


def symbol_variants(symbol) -> list[str]:
    """SQL IN 필터용 심볼 변형 목록 — 원본 · 정규화형 · Q부착형.

    Q부착형은 정규화형이 숫자 6자리일 때만 추가한다('0192S0' 등 영숫자
    코드에는 Q를 붙이지 않는다). 중복 제거, 원본 우선 순서 유지.
    빈 입력이면 빈 리스트를 반환한다.

    Args:
        symbol: 원본 심볼(임의 타입 허용).
    """
    s = str(symbol or "").strip()
    if not s:
        return []
    variants = [s]
    base = norm_symbol(s)
    if base not in variants:
        variants.append(base)
    if _BARE_CODE_PATTERN.fullmatch(base):
        q_form = f"Q{base}"
        if q_form not in variants:
            variants.append(q_form)
    return variants
