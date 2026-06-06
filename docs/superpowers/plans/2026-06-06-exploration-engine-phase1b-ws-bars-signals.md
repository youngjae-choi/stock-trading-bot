# 탐색 엔진 Phase 1b — WS 틱→10초봉 + 라이브 신호 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** WS H0STCNT0 틱을 종목별 10초 OHLCV 봉으로 집계하고, 그 위에서 라이브 신호(체결강도·VWAP위치·틱거래량배수·당일고가돌파·눌림반등·연속상승봉)를 계산해, Phase 1a의 `evaluate_condition`이 소비하는 `state` dict를 채우는 인메모리 집계 엔진 `BarEngine`을 만든다(라이브 WS 없이 합성 틱으로 완전 단위테스트 가능).

**Architecture:** 신규 모듈 `intraday_bar_engine.py`가 종목별 `_SymbolState`를 유지한다. `ingest_tick(tick)`이 틱 1개를 받아 (1) 10초 버킷 OHLCV 갱신, (2) running VWAP(Σ가격·거래량 / Σ거래량), (3) 당일 고가/전일 동안 확정된 prior-day high, (4) 체결강도(shnu_rate 우선, 없으면 매수/매도 체결건수 비율), (5) 틱거래량 baseline 대비 현재 배수, (6) 연속 상승 10초봉 수를 갱신한다. `compute_signal_state(symbol)`이 이 누적 상태에서 파생 불리언(돌파·눌림반등·vwap_position)을 계산해 Phase 1a 계약대로의 `state` dict를 반환한다. 순수 인메모리이므로 KIS/WS 호출 없이 합성 틱 dict 리스트로 단위테스트한다. `tsi`는 일봉 TSI(다른 경로에서 주입)이므로 본 엔진에서는 항상 `None`을 채운다.

**Tech Stack:** Python 3, 표준 라이브러리만(collections.deque, dataclasses), pytest. KIS/WS/DB 의존 없음. 실행: `PYTHONPATH=. .venv/bin/python -m pytest`.

**설계서:** `docs/superpowers/specs/2026-06-06-exploration-buy-strategy-engine-design.md`
**선행 계획(state 계약 정의):** `docs/superpowers/plans/2026-06-06-exploration-engine-phase1a-condition-framework.md`

---

## WS 틱 입력 계약 (확인된 실제 키)

`backend/services/kis/realtime_ws.py`를 읽어 확인한 실제 구조. WS는 두 종류 dict를 만든다:

1. **`entry` dict** — `_cache`에 저장, `get_latest()` 반환:
   `received_at, raw, symbol, trade_time, price, change_rate, trade_volume, accumulated_volume, trade_strength, prev_volume_ratio, fields` (+ 제어메시지 키 `tr_id/count/event/json`).

2. **`tick` dict** — `register_tick_callback`로 등록한 콜백에 전달되는 것 (BarEngine이 받을 입력):
   `symbol, price, change_rate, prdy_ctrt, volume, trade_volume, accumulated_volume, trade_strength, prev_volume_ratio, time, fields`.

⚠️ **중요:** 콜백 `tick` dict에는 `shnu_rate`(체결강도 매수비율)·`cntg_vol`·`shnu_cntg_csnu`·`seln_cntg_csnu`가 **명명 키로는 없다**. 대신 원본 caret-분해 리스트 `fields`(순서 = `_H0STCNT0_FIELDS`)가 통째로 들어온다. 따라서 BarEngine은 `fields`에서 인덱스로 직접 추출한다.

`_H0STCNT0_FIELDS` 순서(0-base 인덱스):
```
0  mksc_shrn_iscd          (종목코드)
1  stck_cntg_hour          (체결시각 HHMMSS)
2  stck_prpr               (현재가/체결가)
3  prdy_vrss_sign
4  prdy_vrss
5  prdy_ctrt               (등락률 %)
6  wghn_avrg_stck_prc      (가중평균가)
7  stck_oprc
8  stck_hgpr
9  stck_lwpr
10 askp1
11 bidp1
12 cntg_vol                (체결 거래량 = 틱 거래량)
13 acml_vol                (누적 거래량)
14 acml_tr_pbmn
15 seln_cntg_csnu          (매도 체결건수)
16 shnu_cntg_csnu          (매수 체결건수)
17 ntby_cntg_csnu
18 cttr                    (체결강도 cttr, 0~200 스케일)
19 seln_cntg_smtn
20 shnu_cntg_smtn
21 ccld_dvsn
22 shnu_rate               (매수 체결비율 0~100)
23 prdy_vol_vrss_acml_vol_rate
```

**BarEngine 입력 정규화 규칙(엔진이 내부에서 적용):** 테스트와 실제 콜백 양쪽을 지원하기 위해, 엔진은 합성 틱이 명명 키(`price`, `cntg_vol`, `shnu_rate`, `stck_cntg_hour` 등)를 직접 주든, 콜백처럼 `fields` 리스트만 주든 **둘 다** 받아들인다. 우선순위: 명명 키 > `fields[인덱스]`. 합성 테스트는 가독성을 위해 명명 키를 쓴다.

---

## state dict 출력 계약 (Phase 1a 입력 — 본 엔진의 산출물)

```python
{
  "change_rate": float,                 # 등락률 % (마지막 틱 prdy_ctrt)
  "체결강도": float,                     # 0~1 (shnu_rate/100 또는 매수/(매수+매도) 체결건수)
  "tick_vol_mult": float,               # 현재 틱거래량 / baseline
  "tsi": None,                          # 일봉 TSI는 외부 주입 → 본 엔진은 항상 None
  "vwap_position": "above"|"below"|None,# 마지막가 vs running VWAP
  "day_high_breakout": bool,            # 현재가 > 전일 동안 확정된 prior-day high
  "pullback_rebound": bool,             # 급등→VWAP 근접 조정→마지막 10초봉 양봉
  "rising_bars": int,                   # 연속 상승(종가>이전종가) 10초봉 수
  "time_hhmm": "HH:MM",                 # 마지막 틱 시각 HH:MM
}
```

---

## File Structure

| 파일 | 책임 |
|---|---|
| `backend/services/engine/intraday_bar_engine.py` (신규) | `BarEngine` + `_SymbolState` + `_Bar`: 틱 정규화·10초봉 집계·VWAP·고가·체결강도·틱거래량배수·연속상승봉·파생불리언·`compute_signal_state` |
| `tests/unit/test_intraday_bar_engine.py` (신규) | 합성 틱 dict 시퀀스 기반 단위테스트(라이브 WS 불필요) |

엔진은 순수 인메모리·표준 라이브러리만 사용하므로 `backend.services.db`·KIS 클라이언트·WS를 import하지 않는다(테스트 격리 + 빠른 단위테스트).

---

### Task 1: 10초 봉 집계 (`BarEngine.ingest_tick` + OHLCV 버킷)

**Files:**
- Create: `backend/services/engine/intraday_bar_engine.py`
- Test: `tests/unit/test_intraday_bar_engine.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/test_intraday_bar_engine.py`:
```python
import backend.services.engine.intraday_bar_engine as ibe


def _tick(symbol="005930", price=1000.0, cntg_vol=10, shnu_rate=60.0,
          prdy_ctrt=2.0, stck_cntg_hour="103000",
          shnu_cntg_csnu=0, seln_cntg_csnu=0):
    """합성 H0STCNT0 틱(명명 키). 라이브 WS 불필요."""
    return {
        "symbol": symbol,
        "price": price,
        "cntg_vol": cntg_vol,
        "shnu_rate": shnu_rate,
        "prdy_ctrt": prdy_ctrt,
        "stck_cntg_hour": stck_cntg_hour,
        "shnu_cntg_csnu": shnu_cntg_csnu,
        "seln_cntg_csnu": seln_cntg_csnu,
    }


def test_single_tick_opens_one_bar():
    eng = ibe.BarEngine()
    eng.ingest_tick(_tick(price=1000.0, cntg_vol=10, stck_cntg_hour="103000"))
    bars = eng.get_bars("005930")
    assert len(bars) == 1
    b = bars[-1]
    assert b.open == 1000.0
    assert b.high == 1000.0
    assert b.low == 1000.0
    assert b.close == 1000.0
    assert b.volume == 10
    assert b.bucket == "103000"  # 10초 버킷 라벨 HHMMSS (초는 10초 내림)


def test_same_bucket_ticks_aggregate_into_one_bar():
    eng = ibe.BarEngine()
    # 103000~103009 → 같은 10초 버킷
    eng.ingest_tick(_tick(price=1000.0, cntg_vol=10, stck_cntg_hour="103001"))
    eng.ingest_tick(_tick(price=1005.0, cntg_vol=5, stck_cntg_hour="103004"))
    eng.ingest_tick(_tick(price=998.0, cntg_vol=7, stck_cntg_hour="103009"))
    bars = eng.get_bars("005930")
    assert len(bars) == 1
    b = bars[-1]
    assert b.open == 1000.0   # 첫 틱
    assert b.high == 1005.0
    assert b.low == 998.0
    assert b.close == 998.0   # 마지막 틱
    assert b.volume == 22


def test_next_bucket_opens_new_bar():
    eng = ibe.BarEngine()
    eng.ingest_tick(_tick(price=1000.0, cntg_vol=10, stck_cntg_hour="103005"))
    eng.ingest_tick(_tick(price=1010.0, cntg_vol=4, stck_cntg_hour="103011"))  # 다음 버킷 103010
    bars = eng.get_bars("005930")
    assert len(bars) == 2
    assert bars[0].bucket == "103000"
    assert bars[1].bucket == "103010"
    assert bars[1].open == 1010.0
    assert bars[1].close == 1010.0


def test_symbols_are_isolated():
    eng = ibe.BarEngine()
    eng.ingest_tick(_tick(symbol="AAA", price=100.0, stck_cntg_hour="103000"))
    eng.ingest_tick(_tick(symbol="BBB", price=200.0, stck_cntg_hour="103000"))
    assert eng.get_bars("AAA")[-1].close == 100.0
    assert eng.get_bars("BBB")[-1].close == 200.0
    assert eng.get_bars("CCC") == []


def test_rolling_window_caps_bar_count():
    eng = ibe.BarEngine(max_bars=3)
    for i in range(5):
        # 각기 다른 10초 버킷: 초를 0,10,20,30,40으로
        hhmmss = "1030" + f"{i*10:02d}"
        eng.ingest_tick(_tick(price=1000.0 + i, cntg_vol=1, stck_cntg_hour=hhmmss))
    bars = eng.get_bars("005930")
    assert len(bars) == 3            # 최근 3개만 유지
    assert bars[0].bucket == "103020"
    assert bars[-1].bucket == "103040"
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_intraday_bar_engine.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'backend.services.engine.intraday_bar_engine'`).

- [ ] **Step 3: 구현**

`backend/services/engine/intraday_bar_engine.py`:
```python
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

    def get_bars(self, symbol: str) -> list[_Bar]:
        st = self._states.get(symbol)
        if st is None:
            return []
        return list(st.bars)
```

- [ ] **Step 4: 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_intraday_bar_engine.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/intraday_bar_engine.py tests/unit/test_intraday_bar_engine.py
git commit -m "feat: BarEngine 10초봉 집계 — WS 틱→종목별 OHLCV 롤링윈도우"
```

---

### Task 2: running VWAP + 당일고가 / prior-day high 추적

**Files:**
- Modify: `backend/services/engine/intraday_bar_engine.py`
- Test: `tests/unit/test_intraday_bar_engine.py`

- [ ] **Step 1: 실패 테스트 추가**

`tests/unit/test_intraday_bar_engine.py` 에 추가:
```python
def test_running_vwap_is_volume_weighted():
    eng = ibe.BarEngine()
    eng.ingest_tick(_tick(price=1000.0, cntg_vol=10, stck_cntg_hour="103001"))
    eng.ingest_tick(_tick(price=1020.0, cntg_vol=30, stck_cntg_hour="103004"))
    # VWAP = (1000*10 + 1020*30) / (10+30) = (10000+30600)/40 = 1015.0
    assert eng.get_vwap("005930") == 1015.0


def test_vwap_none_when_no_volume():
    eng = ibe.BarEngine()
    assert eng.get_vwap("005930") is None
    eng.ingest_tick(_tick(price=1000.0, cntg_vol=0, stck_cntg_hour="103000"))
    # 거래량 0뿐이면 VWAP 정의 불가 → None
    assert eng.get_vwap("005930") is None


def test_day_high_tracks_max_price():
    eng = ibe.BarEngine()
    eng.ingest_tick(_tick(price=1000.0, cntg_vol=1, stck_cntg_hour="103000"))
    eng.ingest_tick(_tick(price=1030.0, cntg_vol=1, stck_cntg_hour="103010"))
    eng.ingest_tick(_tick(price=1010.0, cntg_vol=1, stck_cntg_hour="103020"))
    assert eng.get_day_high("005930") == 1030.0


def test_prior_day_high_seed_and_breakout_basis():
    eng = ibe.BarEngine()
    # 전일 고가를 외부(전일 일봉)에서 주입
    eng.set_prior_day_high("005930", 1050.0)
    assert eng.get_prior_day_high("005930") == 1050.0
    # 당일 고가는 prior-day high와 별개로 추적
    eng.ingest_tick(_tick(price=1000.0, cntg_vol=1, stck_cntg_hour="103000"))
    assert eng.get_day_high("005930") == 1000.0
    assert eng.get_prior_day_high("005930") == 1050.0
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_intraday_bar_engine.py -q`
Expected: FAIL (`AttributeError: 'BarEngine' object has no attribute 'get_vwap'`).

- [ ] **Step 3: 구현 — `_SymbolState` 확장 + `ingest_tick` 누적 + getter 추가**

`_SymbolState` 의 dataclass를 아래로 교체:
```python
@dataclass
class _SymbolState:
    bars: deque = field(default_factory=deque)
    vwap_pv_sum: float = 0.0      # Σ(price*vol)
    vwap_vol_sum: float = 0.0     # Σ(vol)
    day_high: float = 0.0
    prior_day_high: float | None = None
```

`ingest_tick` 의 봉 갱신 직후(메서드 끝)에 누적 로직 추가. `ingest_tick`을 아래로 교체:
```python
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
```

모듈에 getter 추가:
```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_intraday_bar_engine.py -q`
Expected: PASS (9 tests).

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/intraday_bar_engine.py tests/unit/test_intraday_bar_engine.py
git commit -m "feat: BarEngine running VWAP + 당일고가/전일고가 추적"
```

---

### Task 3: 체결강도 + 틱거래량 baseline/배수

**Files:**
- Modify: `backend/services/engine/intraday_bar_engine.py`
- Test: `tests/unit/test_intraday_bar_engine.py`

체결강도 규칙: `shnu_rate`(0~100, 매수 체결비율)가 있으면 `/100`. 없으면 매수/(매수+매도) 체결건수 비율. 둘 다 없으면 `0.0`.
틱거래량 배수: baseline = 지금까지 본 틱 거래량의 평균. 현재 = 마지막 틱 거래량. `mult = 현재/baseline`(baseline 0이면 0.0). 단일 틱뿐일 때 baseline=그 틱이므로 mult=1.0.

- [ ] **Step 1: 실패 테스트 추가**

```python
def test_chegyeol_gangdo_from_shnu_rate():
    eng = ibe.BarEngine()
    eng.ingest_tick(_tick(price=1000.0, cntg_vol=1, shnu_rate=62.0, stck_cntg_hour="103000"))
    # 62.0 / 100 = 0.62
    assert abs(eng.get_chegyeol_gangdo("005930") - 0.62) < 1e-9


def test_chegyeol_gangdo_falls_back_to_csnu_ratio():
    eng = ibe.BarEngine()
    # shnu_rate 없음(None) → 매수/(매수+매도) = 30/(30+10) = 0.75
    t = _tick(price=1000.0, cntg_vol=1, shnu_rate=None,
              shnu_cntg_csnu=30, seln_cntg_csnu=10, stck_cntg_hour="103000")
    eng.ingest_tick(t)
    assert abs(eng.get_chegyeol_gangdo("005930") - 0.75) < 1e-9


def test_chegyeol_gangdo_zero_when_no_data():
    eng = ibe.BarEngine()
    t = _tick(price=1000.0, cntg_vol=1, shnu_rate=None,
              shnu_cntg_csnu=0, seln_cntg_csnu=0, stck_cntg_hour="103000")
    eng.ingest_tick(t)
    assert eng.get_chegyeol_gangdo("005930") == 0.0


def test_tick_volume_mult_single_tick_is_one():
    eng = ibe.BarEngine()
    eng.ingest_tick(_tick(price=1000.0, cntg_vol=50, stck_cntg_hour="103000"))
    assert eng.get_tick_vol_mult("005930") == 1.0


def test_tick_volume_mult_against_baseline_average():
    eng = ibe.BarEngine()
    eng.ingest_tick(_tick(price=1000.0, cntg_vol=10, stck_cntg_hour="103000"))
    eng.ingest_tick(_tick(price=1001.0, cntg_vol=10, stck_cntg_hour="103001"))
    eng.ingest_tick(_tick(price=1002.0, cntg_vol=40, stck_cntg_hour="103002"))
    # baseline = (10+10+40)/3 = 20.0, 현재(마지막 틱) = 40 → 40/20 = 2.0
    assert abs(eng.get_tick_vol_mult("005930") - 2.0) < 1e-9


def test_tick_volume_mult_zero_baseline_returns_zero():
    eng = ibe.BarEngine()
    eng.ingest_tick(_tick(price=1000.0, cntg_vol=0, stck_cntg_hour="103000"))
    assert eng.get_tick_vol_mult("005930") == 0.0
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_intraday_bar_engine.py -q`
Expected: FAIL (`AttributeError: 'BarEngine' object has no attribute 'get_chegyeol_gangdo'`).

- [ ] **Step 3: 구현 — `_SymbolState` 확장 + `ingest_tick` 누적 + getter**

`_SymbolState` 에 필드 추가(기존 필드 아래에 이어서):
```python
@dataclass
class _SymbolState:
    bars: deque = field(default_factory=deque)
    vwap_pv_sum: float = 0.0
    vwap_vol_sum: float = 0.0
    day_high: float = 0.0
    prior_day_high: float | None = None
    last_chegyeol_gangdo: float = 0.0     # 마지막 틱 체결강도 0~1
    tick_vol_sum: float = 0.0             # Σ 틱거래량(baseline용)
    tick_count: int = 0                   # 틱 수
    last_tick_vol: float = 0.0            # 마지막 틱 거래량
```

`ingest_tick` 의 "당일 고가" 블록 뒤에 누적 로직 추가(메서드 끝에 붙임):
```python
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
```

모듈에 getter 추가:
```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_intraday_bar_engine.py -q`
Expected: PASS (15 tests).

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/intraday_bar_engine.py tests/unit/test_intraday_bar_engine.py
git commit -m "feat: BarEngine 체결강도(shnu_rate/체결건수) + 틱거래량 baseline·배수"
```

---

### Task 4: rising_bars 연속상승 + 당일고가돌파 / 눌림반등 파생

**Files:**
- Modify: `backend/services/engine/intraday_bar_engine.py`
- Test: `tests/unit/test_intraday_bar_engine.py`

규칙:
- `rising_bars` = 마지막 봉부터 거꾸로 세어 "직전 봉 종가보다 종가가 높은" 연속 10초봉 수. 봉 1개뿐이면 0.
- `day_high_breakout` = `prior_day_high`가 설정돼 있고 현재가(`get_last_price`) > `prior_day_high`. prior_day_high 미설정이면 False(기준선 없음 → 돌파 판정 불가).
- `pullback_rebound` = (1) 직전에 VWAP 대비 일정 비율 이상 위로 스파이크했고(누적 day_high가 VWAP보다 `spike_pct` 이상 위), (2) 가격이 VWAP 근처(`±near_pct`)까지 되눌렸다가, (3) 마지막 10초봉이 양봉(close>open). 셋 다일 때 True.

- [ ] **Step 1: 실패 테스트 추가**

```python
def test_rising_bars_counts_consecutive_up_closes():
    eng = ibe.BarEngine()
    # 4개 버킷, 종가 1000 1005 1010 1008 → 마지막 봉은 하락 → rising_bars=0
    for sec, price in [("103000", 1000.0), ("103010", 1005.0),
                       ("103020", 1010.0), ("103030", 1008.0)]:
        eng.ingest_tick(_tick(price=price, cntg_vol=1, stck_cntg_hour=sec))
    assert eng.get_rising_bars("005930") == 0


def test_rising_bars_three_in_a_row():
    eng = ibe.BarEngine()
    for sec, price in [("103000", 1000.0), ("103010", 1005.0),
                       ("103020", 1010.0), ("103030", 1015.0)]:
        eng.ingest_tick(_tick(price=price, cntg_vol=1, stck_cntg_hour=sec))
    # 1005>1000, 1010>1005, 1015>1010 → 3 연속 상승
    assert eng.get_rising_bars("005930") == 3


def test_rising_bars_single_bar_is_zero():
    eng = ibe.BarEngine()
    eng.ingest_tick(_tick(price=1000.0, cntg_vol=1, stck_cntg_hour="103000"))
    assert eng.get_rising_bars("005930") == 0


def test_day_high_breakout_true_above_prior_high():
    eng = ibe.BarEngine()
    eng.set_prior_day_high("005930", 1050.0)
    eng.ingest_tick(_tick(price=1060.0, cntg_vol=1, stck_cntg_hour="103000"))
    assert eng.is_day_high_breakout("005930") is True


def test_day_high_breakout_false_below_prior_high():
    eng = ibe.BarEngine()
    eng.set_prior_day_high("005930", 1050.0)
    eng.ingest_tick(_tick(price=1040.0, cntg_vol=1, stck_cntg_hour="103000"))
    assert eng.is_day_high_breakout("005930") is False


def test_day_high_breakout_false_without_prior_high():
    eng = ibe.BarEngine()
    eng.ingest_tick(_tick(price=9999.0, cntg_vol=1, stck_cntg_hour="103000"))
    assert eng.is_day_high_breakout("005930") is False


def test_pullback_rebound_true_after_spike_dip_then_up_bar():
    eng = ibe.BarEngine(max_bars=360)
    # 1) 초반 VWAP ~1000 형성
    eng.ingest_tick(_tick(price=1000.0, cntg_vol=100, stck_cntg_hour="103000"))
    # 2) 스파이크: day_high를 VWAP 대비 +3% 이상 위로
    eng.ingest_tick(_tick(price=1035.0, cntg_vol=1, stck_cntg_hour="103010"))
    # 3) VWAP 근처로 되눌림(다음 봉 시작 저가)
    eng.ingest_tick(_tick(price=1002.0, cntg_vol=1, stck_cntg_hour="103020"))
    # 4) 마지막 10초봉 양봉: 같은 버킷 안에서 close>open 되게 상승 마감
    eng.ingest_tick(_tick(price=1008.0, cntg_vol=1, stck_cntg_hour="103029"))
    assert eng.is_pullback_rebound("005930") is True


def test_pullback_rebound_false_when_last_bar_down():
    eng = ibe.BarEngine()
    eng.ingest_tick(_tick(price=1000.0, cntg_vol=100, stck_cntg_hour="103000"))
    eng.ingest_tick(_tick(price=1035.0, cntg_vol=1, stck_cntg_hour="103010"))
    # 마지막 봉이 음봉(open 1003 > close 999) → 반등 아님
    eng.ingest_tick(_tick(price=1003.0, cntg_vol=1, stck_cntg_hour="103020"))
    eng.ingest_tick(_tick(price=999.0, cntg_vol=1, stck_cntg_hour="103029"))
    assert eng.is_pullback_rebound("005930") is False


def test_pullback_rebound_false_without_spike():
    eng = ibe.BarEngine()
    # 스파이크 없이 완만: day_high가 VWAP 대비 +3% 미만
    eng.ingest_tick(_tick(price=1000.0, cntg_vol=100, stck_cntg_hour="103000"))
    eng.ingest_tick(_tick(price=1005.0, cntg_vol=1, stck_cntg_hour="103010"))
    eng.ingest_tick(_tick(price=1002.0, cntg_vol=1, stck_cntg_hour="103020"))
    eng.ingest_tick(_tick(price=1006.0, cntg_vol=1, stck_cntg_hour="103029"))
    assert eng.is_pullback_rebound("005930") is False
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_intraday_bar_engine.py -q`
Expected: FAIL (`AttributeError: 'BarEngine' object has no attribute 'get_rising_bars'`).

- [ ] **Step 3: 구현 — last_price getter + 파생 메서드 추가**

먼저 `__init__`에 파생 임계 파라미터 추가. `__init__`을 아래로 교체:
```python
    def __init__(self, max_bars: int = 360, spike_pct: float = 0.03, near_pct: float = 0.005):
        self._max_bars = max(1, int(max_bars))
        self._spike_pct = float(spike_pct)   # 스파이크 판정: day_high가 VWAP 대비 +N%
        self._near_pct = float(near_pct)     # 되눌림 근접: 저가가 VWAP의 ±N% 이내
        self._states: dict[str, _SymbolState] = {}
```

모듈에 메서드 추가:
```python
    def get_last_price(self, symbol: str) -> float | None:
        st = self._states.get(symbol)
        if st is None or not st.bars:
            return None
        return st.bars[-1].close

    def get_rising_bars(self, symbol: str) -> int:
        st = self._states.get(symbol)
        if st is None or len(st.bars) < 2:
            return 0
        bars = list(st.bars)
        count = 0
        for i in range(len(bars) - 1, 0, -1):
            if bars[i].close > bars[i - 1].close:
                count += 1
            else:
                break
        return count

    def is_day_high_breakout(self, symbol: str) -> bool:
        st = self._states.get(symbol)
        if st is None or st.prior_day_high is None:
            return False
        last = self.get_last_price(symbol)
        if last is None:
            return False
        return last > st.prior_day_high

    def is_pullback_rebound(self, symbol: str) -> bool:
        st = self._states.get(symbol)
        if st is None or not st.bars:
            return False
        vwap = self.get_vwap(symbol)
        if vwap is None or vwap <= 0:
            return False
        # (1) 스파이크: 당일고가가 VWAP 대비 +spike_pct 이상
        spiked = st.day_high >= vwap * (1.0 + self._spike_pct)
        if not spiked:
            return False
        last_bar = st.bars[-1]
        # (2) 되눌림: 마지막 봉 저가가 VWAP의 ±near_pct 이내까지 근접
        dipped = abs(last_bar.low - vwap) <= vwap * self._near_pct
        if not dipped:
            return False
        # (3) 마지막 10초봉 양봉
        rebounded = last_bar.close > last_bar.open
        return bool(rebounded)
```

- [ ] **Step 4: 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_intraday_bar_engine.py -q`
Expected: PASS (24 tests).

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/intraday_bar_engine.py tests/unit/test_intraday_bar_engine.py
git commit -m "feat: BarEngine 연속상승봉 + 당일고가돌파/눌림반등 파생"
```

---

### Task 5: `compute_signal_state` — 전체 state dict 조립 (Phase 1a 계약)

**Files:**
- Modify: `backend/services/engine/intraday_bar_engine.py`
- Test: `tests/unit/test_intraday_bar_engine.py`

규칙:
- `change_rate` = 마지막 틱 `prdy_ctrt`(엔진이 ingest 때 저장).
- `체결강도` = `get_chegyeol_gangdo`.
- `tick_vol_mult` = `get_tick_vol_mult`.
- `tsi` = 항상 `None`(일봉 TSI는 외부 주입).
- `vwap_position` = 마지막가>VWAP → "above", <VWAP → "below", VWAP 없거나 동일 → None.
- `day_high_breakout` = `is_day_high_breakout`.
- `pullback_rebound` = `is_pullback_rebound`.
- `rising_bars` = `get_rising_bars`.
- `time_hhmm` = 마지막 틱 시각 HHMMSS → "HH:MM"(앞 4자리). 없으면 "".
- 종목 미관측이면 모든 신호 기본값(0/None/False/"")으로 구성된 dict 반환(예외 금지).

검증: 결과 dict는 Phase 1a의 `evaluate_condition`에 그대로 먹여 통과해야 한다(실제 통합 검증). Phase 1a 모듈 `buy_condition_framework`가 존재한다는 전제(같은 Phase 1 산출물).

- [ ] **Step 1: 실패 테스트 추가**

```python
import backend.services.engine.buy_condition_framework as bcf


def test_compute_signal_state_full_shape():
    eng = ibe.BarEngine()
    eng.set_prior_day_high("005930", 1050.0)
    eng.ingest_tick(_tick(price=1000.0, cntg_vol=10, shnu_rate=60.0,
                          prdy_ctrt=2.0, stck_cntg_hour="103000"))
    eng.ingest_tick(_tick(price=1060.0, cntg_vol=30, shnu_rate=62.0,
                          prdy_ctrt=3.0, stck_cntg_hour="103010"))
    s = eng.compute_signal_state("005930")
    assert set(s.keys()) == {
        "change_rate", "체결강도", "tick_vol_mult", "tsi", "vwap_position",
        "day_high_breakout", "pullback_rebound", "rising_bars", "time_hhmm",
    }
    assert s["change_rate"] == 3.0            # 마지막 틱 등락률
    assert abs(s["체결강도"] - 0.62) < 1e-9
    assert s["tsi"] is None                   # 일봉 TSI는 외부 주입
    assert s["time_hhmm"] == "10:30"
    assert s["vwap_position"] == "above"      # 1060 > vwap
    assert s["day_high_breakout"] is True     # 1060 > 1050
    assert s["rising_bars"] == 1              # 1060 > 1000
    assert isinstance(s["pullback_rebound"], bool)


def test_compute_signal_state_unknown_symbol_safe_defaults():
    eng = ibe.BarEngine()
    s = eng.compute_signal_state("NOPE")
    assert s["change_rate"] == 0.0
    assert s["체결강도"] == 0.0
    assert s["tick_vol_mult"] == 0.0
    assert s["tsi"] is None
    assert s["vwap_position"] is None
    assert s["day_high_breakout"] is False
    assert s["pullback_rebound"] is False
    assert s["rising_bars"] == 0
    assert s["time_hhmm"] == ""


def test_vwap_position_below():
    eng = ibe.BarEngine()
    eng.ingest_tick(_tick(price=1000.0, cntg_vol=100, stck_cntg_hour="103000"))
    eng.ingest_tick(_tick(price=980.0, cntg_vol=1, stck_cntg_hour="103010"))
    # vwap ≈ (1000*100+980*1)/101 ≈ 999.8, 마지막가 980 < vwap → below
    assert eng.compute_signal_state("005930")["vwap_position"] == "below"


def test_state_feeds_phase1a_evaluate_condition():
    """본 엔진 출력이 Phase 1a 평가기에 그대로 호환되는지 통합 검증."""
    eng = ibe.BarEngine()
    eng.set_prior_day_high("005930", 1050.0)
    eng.ingest_tick(_tick(price=1000.0, cntg_vol=10, shnu_rate=60.0,
                          prdy_ctrt=2.3, stck_cntg_hour="103000"))
    eng.ingest_tick(_tick(price=1060.0, cntg_vol=30, shnu_rate=62.0,
                          prdy_ctrt=2.3, stck_cntg_hour="103010"))
    s = eng.compute_signal_state("005930")
    # 등락률 1.5~5% 밴드 통과
    assert bcf.evaluate_condition(
        {"ctype": "change_rate_band", "params": {"min": 1.5, "max": 5.0}}, s) is True
    # 체결강도 0.55+ 통과
    assert bcf.evaluate_condition(
        {"ctype": "chegyeol_gangdo_min", "params": {"min": 0.55}}, s) is True
    # 당일고가 돌파 통과
    assert bcf.evaluate_condition(
        {"ctype": "day_high_breakout", "params": {}}, s) is True
    # tsi None → tsi_positive는 통과(결손은 차단 안 함)
    assert bcf.evaluate_condition(
        {"ctype": "tsi_positive", "params": {}}, s) is True
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_intraday_bar_engine.py -q`
Expected: FAIL (`AttributeError: 'BarEngine' object has no attribute 'compute_signal_state'`).

- [ ] **Step 3: 구현 — 마지막 틱 메타 저장 + `compute_signal_state`**

`_SymbolState` 에 필드 추가(기존 필드 아래에 이어서):
```python
    last_change_rate: float = 0.0    # 마지막 틱 prdy_ctrt
    last_hhmmss: str = ""            # 마지막 틱 stck_cntg_hour
```

`ingest_tick` 의 "틱거래량 baseline/현재" 블록 뒤(메서드 끝)에 추가:
```python
        # 마지막 틱 메타(등락률·시각)
        st.last_change_rate = _to_float(_pick(tick, "prdy_ctrt", _IDX_PRDY_CTRT), st.last_change_rate)
        st.last_hhmmss = str(_pick(tick, "stck_cntg_hour", _IDX_CNTG_HOUR) or st.last_hhmmss)
```

모듈에 헬퍼 + 메서드 추가:
```python
    def _vwap_position(self, symbol: str) -> str | None:
        vwap = self.get_vwap(symbol)
        last = self.get_last_price(symbol)
        if vwap is None or last is None:
            return None
        if last > vwap:
            return "above"
        if last < vwap:
            return "below"
        return None

    @staticmethod
    def _hhmm(hhmmss: str) -> str:
        s = str(hhmmss or "").strip()
        if len(s) >= 4 and s[:4].isdigit():
            return f"{s[:2]}:{s[2:4]}"
        return ""

    def compute_signal_state(self, symbol: str) -> dict[str, Any]:
        """Phase 1a evaluate_condition이 소비하는 state dict.

        tsi는 일봉 TSI(외부 주입)이므로 항상 None. 미관측 종목은 안전 기본값.
        """
        st = self._states.get(symbol)
        if st is None:
            return {
                "change_rate": 0.0, "체결강도": 0.0, "tick_vol_mult": 0.0, "tsi": None,
                "vwap_position": None, "day_high_breakout": False,
                "pullback_rebound": False, "rising_bars": 0, "time_hhmm": "",
            }
        return {
            "change_rate": st.last_change_rate,
            "체결강도": self.get_chegyeol_gangdo(symbol),
            "tick_vol_mult": self.get_tick_vol_mult(symbol),
            "tsi": None,
            "vwap_position": self._vwap_position(symbol),
            "day_high_breakout": self.is_day_high_breakout(symbol),
            "pullback_rebound": self.is_pullback_rebound(symbol),
            "rising_bars": self.get_rising_bars(symbol),
            "time_hhmm": self._hhmm(st.last_hhmmss),
        }
```

- [ ] **Step 4: 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_intraday_bar_engine.py -q`
Expected: PASS (28 tests).
또한 전체 단위테스트 회귀 없음: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/ -q`
Expected: 신규 포함 전부 PASS.

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/intraday_bar_engine.py tests/unit/test_intraday_bar_engine.py
git commit -m "feat: BarEngine.compute_signal_state — Phase 1a state dict 조립 + 통합검증"
```

---

## 완료 기준 (Phase 1b)

- [ ] `BarEngine`이 합성 틱(명명 키) 및 WS 콜백(`fields` 리스트) 둘 다 ingest — 28개 단위테스트 PASS.
- [ ] 10초 OHLCV 봉(롤링 윈도우) + running VWAP + 당일/전일 고가 + 체결강도 + 틱거래량배수 + 연속상승봉.
- [ ] 파생 불리언: `day_high_breakout`(전일고가 기준선) · `pullback_rebound`(스파이크→VWAP 되눌림→양봉) · `vwap_position`.
- [ ] `compute_signal_state(symbol)`이 Phase 1a 계약 9키 dict 반환, `tsi`는 None, 미관측 종목 안전 기본값.
- [ ] 산출 state가 Phase 1a `evaluate_condition`에 그대로 통과(통합 테스트).
- [ ] KIS/WS/DB 의존 없음 — 표준 라이브러리만, 빠른 단위테스트.
- [ ] `tests/unit/` 전체 회귀 PASS.

## 후속 (이 계획 범위 밖)

- **Phase 1c:** 통짜 태깅(`trade_entry_tags`) + 선정사유 기록 — `compute_signal_state` 출력을 진입 순간 `condition_states`로 스냅샷.
- **Phase 1d:** S6 매수경로에 BarEngine wiring(`register_tick_callback(ingest_tick)` 어댑터) + `evaluate_groups_or` 통합 + prior-day high 주입(전일 일봉) + 일봉 TSI를 state에 주입 + 모의전용 게이트.
- 본 엔진의 임계(`spike_pct`/`near_pct`/`max_bars`)는 추후 Settings 노출 후보(현재는 생성자 파라미터 기본값).
