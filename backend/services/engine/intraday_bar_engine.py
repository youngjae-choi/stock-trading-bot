"""WS H0STCNT0 틱 → 종목별 10초 OHLCV 봉 집계 + 라이브 신호 → state dict.

순수 인메모리. KIS/WS/DB 의존 없음. Phase 1a의 evaluate_condition이 소비하는
state dict를 채운다. tsi(일봉)는 외부 주입이므로 본 엔진은 항상 None을 채운다.

틱 입력은 합성(명명 키) 또는 WS 콜백(원본 fields 리스트) 둘 다 받는다.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("IntradayBarEngine")

# _H0STCNT0_FIELDS 순서와 동일한 인덱스 (realtime_ws._H0STCNT0_FIELDS 기준)
_IDX_SYMBOL = 0
_IDX_CNTG_HOUR = 1
_IDX_PRPR = 2
_IDX_PRDY_CTRT = 5
_IDX_CNTG_VOL = 12
_IDX_SELN_CSNU = 15
_IDX_SHNU_CSNU = 16
_IDX_SHNU_RATE = 22

_BUCKET_SECONDS = 10


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _from_fields(fields: list[Any], idx: int) -> Any:
    if not isinstance(fields, (list, tuple)) or len(fields) <= idx:
        return None
    return fields[idx]


def _pick(tick: dict[str, Any], named_key: str, field_idx: int) -> Any:
    """명명 키 우선, 없으면 원본 fields[idx]."""
    if named_key in tick and tick[named_key] not in (None, ""):
        return tick[named_key]
    return _from_fields(tick.get("fields") or [], field_idx)


def _bucket_label(hhmmss: str) -> str:
    """HHMMSS 체결시각 → 10초 버킷 라벨(초를 10초 단위로 내림). 비정상은 원문 반환."""
    s = str(hhmmss or "").strip()
    if len(s) < 6 or not s[:6].isdigit():
        return s or "000000"
    hhmm = s[:4]
    sec = int(s[4:6])
    floored = (sec // _BUCKET_SECONDS) * _BUCKET_SECONDS
    return f"{hhmm}{floored:02d}"


@dataclass
class _Bar:
    bucket: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class _SymbolState:
    bars: deque = field(default_factory=deque)
    vwap_pv_sum: float = 0.0      # Σ(price*vol)
    vwap_vol_sum: float = 0.0     # Σ(vol)
    day_high: float = 0.0
    prior_day_high: float | None = None
    last_chegyeol_gangdo: float = 0.0     # 마지막 틱 체결강도 0~1
    tick_vol_sum: float = 0.0             # Σ 틱거래량(baseline용)
    tick_count: int = 0                   # 틱 수
    last_tick_vol: float = 0.0            # 마지막 틱 거래량


class BarEngine:
    """종목별 틱 → 10초 OHLCV 봉 집계."""

    def __init__(self, max_bars: int = 360):
        self._max_bars = max(1, int(max_bars))
        self._states: dict[str, _SymbolState] = {}

    def _state(self, symbol: str) -> _SymbolState:
        st = self._states.get(symbol)
        if st is None:
            st = _SymbolState(bars=deque(maxlen=self._max_bars))
            self._states[symbol] = st
        return st

    def ingest_tick(self, tick: dict[str, Any]) -> None:
        symbol = str(_pick(tick, "symbol", _IDX_SYMBOL) or "").strip()
        if not symbol:
            return
        price = _to_float(_pick(tick, "price", _IDX_PRPR))
        if price <= 0:
            return
        vol = _to_float(_pick(tick, "cntg_vol", _IDX_CNTG_VOL))
        hhmmss = str(_pick(tick, "stck_cntg_hour", _IDX_CNTG_HOUR) or "")
        bucket = _bucket_label(hhmmss)

        st = self._state(symbol)
        if st.bars and st.bars[-1].bucket == bucket:
            b = st.bars[-1]
            b.high = max(b.high, price)
            b.low = min(b.low, price)
            b.close = price
            b.volume += vol
        else:
            st.bars.append(_Bar(bucket=bucket, open=price, high=price, low=price, close=price, volume=vol))

        # running VWAP 누적
        if vol > 0:
            st.vwap_pv_sum += price * vol
            st.vwap_vol_sum += vol
        # 당일 고가
        if price > st.day_high:
            st.day_high = price

        # 체결강도: shnu_rate(0~100) 우선, 없으면 매수/(매수+매도) 체결건수 비율
        shnu_rate_raw = _pick(tick, "shnu_rate", _IDX_SHNU_RATE)
        if shnu_rate_raw not in (None, ""):
            st.last_chegyeol_gangdo = max(0.0, min(1.0, _to_float(shnu_rate_raw) / 100.0))
        else:
            buy_cnt = _to_float(_pick(tick, "shnu_cntg_csnu", _IDX_SHNU_CSNU))
            sell_cnt = _to_float(_pick(tick, "seln_cntg_csnu", _IDX_SELN_CSNU))
            denom = buy_cnt + sell_cnt
            st.last_chegyeol_gangdo = (buy_cnt / denom) if denom > 0 else 0.0

        # 틱거래량 baseline/현재
        st.tick_vol_sum += vol
        st.tick_count += 1
        st.last_tick_vol = vol

    def get_chegyeol_gangdo(self, symbol: str) -> float:
        st = self._states.get(symbol)
        return st.last_chegyeol_gangdo if st is not None else 0.0

    def get_tick_vol_mult(self, symbol: str) -> float:
        st = self._states.get(symbol)
        if st is None or st.tick_count <= 0:
            return 0.0
        baseline = st.tick_vol_sum / st.tick_count
        if baseline <= 0:
            return 0.0
        return st.last_tick_vol / baseline

    def get_vwap(self, symbol: str) -> float | None:
        st = self._states.get(symbol)
        if st is None or st.vwap_vol_sum <= 0:
            return None
        return st.vwap_pv_sum / st.vwap_vol_sum

    def get_day_high(self, symbol: str) -> float:
        st = self._states.get(symbol)
        return st.day_high if st is not None else 0.0

    def set_prior_day_high(self, symbol: str, value: float) -> None:
        """전일 일봉 고가를 외부에서 주입(돌파 기준선)."""
        self._state(symbol).prior_day_high = float(value)

    def get_prior_day_high(self, symbol: str) -> float | None:
        st = self._states.get(symbol)
        return st.prior_day_high if st is not None else None

    def get_bars(self, symbol: str) -> list[_Bar]:
        st = self._states.get(symbol)
        if st is None:
            return []
        return list(st.bars)
