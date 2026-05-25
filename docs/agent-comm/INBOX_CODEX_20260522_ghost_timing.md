# INBOX: 귀신타이밍 전략 — Decision Engine 강화 + 분봉 백테스트

**날짜:** 2026-05-22  
**우선순위:** HIGH  
**대상:** Codex (Backend)

---

## 작업 1: Decision Engine — 진입 시간 창 필터 추가

파일: `backend/services/engine/decision_engine.py`

`_evaluate_entry_rules()` 메서드 내, `matched` 딕셔너리 생성 전에 시간 창 체크 추가.

### 추가할 로직

```python
# 진입 허용 시간 창 체크 (system_settings: entry_start_time, entry_end_time)
entry_start_str = _get_setting_str("engine.entry_start_time", "09:00")
entry_end_str   = _get_setting_str("engine.entry_end_time",   "10:30")
now_kst = _now_kst()
now_hhmm = now_kst.strftime("%H:%M")
time_window_ok = entry_start_str <= now_hhmm <= entry_end_str

if not time_window_ok:
    # 시간 창 외 진입 불가 — 조용히 False 반환
    return {
        "pass": False,
        "reason": f"진입 시간 창 외 ({now_hhmm}, 허용: {entry_start_str}~{entry_end_str})",
        "matched": {"time_window": False},
        "observed_values": {"now_hhmm": now_hhmm, "entry_start": entry_start_str, "entry_end": entry_end_str},
    }
```

`_get_setting_str` 헬퍼가 없으면 아래 방식으로 구현:
```python
def _get_setting_str(key: str, default: str) -> str:
    from ..settings_store import get_setting
    val = get_setting(key, default)
    return str(val) if val is not None else default
```

### 거래량 비율 최소값 settings 반영

현재 `volume_ratio_min`은 RulePack에서만 읽는다. settings 가드레일 추가:

```python
# 기존 코드 아래에 추가:
vol_floor = _get_setting_float("engine.min_volume_ratio", 1.0)
volume_ratio_min = max(volume_ratio_min, vol_floor)
```

이 코드는 기존 `volume_ratio_min = parsed_volume_ratio_min if ... else 1.0` 라인 바로 다음에 삽입한다.

### matched에 time_window 추가

```python
matched: dict[str, Any] = {
    "volume_ratio": volume_ok,
    "ai_confidence": ai_conf >= ai_conf_min,
    "price_change": price_ok,
    "time_window": time_window_ok,   # ← 추가
}
```

`required_keys` (진입 통과 조건 리스트)에도 `"time_window"` 추가:
```python
required_keys = ["volume_ratio", "ai_confidence", "price_change", "time_window"]
```

---

## 작업 2: 분봉 백테스트 — KIS API 기반으로 교체

파일: `backend/services/engine/backtest.py` (전면 교체)

현재 일봉(pykrx) 기반 시뮬레이션을 **KIS 분봉 API** 기반으로 교체한다.

### 핵심 변경사항

- `get_intraday_chart()` 사용 (이미 `backend/services/kis/domestic/service.py`에 구현됨)
  - `tr_id=FHKST03010200`, `FID_INPUT_HOUR_1` (조회 기준 시간), `FID_PW_DATA_INCU_YN=Y`
  - 응답: `output2` 리스트 (각 항목: 시분초, 시가, 고가, 저가, 현재가, 거래량)
- **진입 조건** (분봉 기준):
  - 분봉 시각 09:00~10:30 사이 캔들만 진입 대상
  - 해당 캔들에서 `등락률 >= min_price_change_pct` AND `누적거래량 비율 >= min_volume_ratio`
  - 등락률은 전일 종가 대비 현재 분봉 현재가
- **청산 시뮬레이션** (분봉 기준):
  - 진입 이후 분봉들을 순서대로 체크
  - `stop_loss`: 진입가 대비 <= stop_loss_pct
  - `trailing_stop`: 고점 대비 trailing_stop_pct 이상 하락 시 (trailing_activate_pct 도달 후 활성)
  - `force_exit`: 15:20 이후 무조건 청산

### backtest.py 주요 함수 구조

```python
async def fetch_intraday_bars(symbol: str, date_str: str) -> list[dict]:
    """KIS 분봉 데이터 조회. date_str=YYYYMMDD.
    Returns list of {time: 'HH:MM', open, high, low, close, volume, cum_volume}
    """
    from ..kis.domestic.service import get_intraday_chart
    # input_hour='153000' 으로 당일 전체 조회
    resp = await get_intraday_chart(symbol=symbol, input_hour="153000", include_past="Y")
    output2 = resp.get("output2") or []
    bars = []
    for item in output2:
        t = str(item.get("stck_cntg_hour", "") or item.get("bsop_hour", ""))  # HHMMSS
        if len(t) < 6:
            continue
        hhmm = t[:4]  # HHMM
        bars.append({
            "time": f"{hhmm[:2]}:{hhmm[2:]}",
            "open":   float(str(item.get("stck_oprc","0")).replace(",","")),
            "high":   float(str(item.get("stck_hgpr","0")).replace(",","")),
            "low":    float(str(item.get("stck_lwpr","0")).replace(",","")),
            "close":  float(str(item.get("stck_prpr","0") or item.get("stck_clpr","0")).replace(",","")),
            "volume": int(str(item.get("cntg_vol","0")).replace(",","")),
            "cum_vol":int(str(item.get("acml_vol","0")).replace(",","")),
        })
    # 시간 오름차순 정렬
    bars.sort(key=lambda x: x["time"])
    return bars


def simulate_intraday_trade(
    bars: list[dict],
    entry_bar_idx: int,
    prev_close: float,
    stop_loss_pct: float = -0.015,
    trailing_activate_pct: float = 0.02,
    trailing_stop_pct: float = 0.01,
    force_exit_time: str = "15:20",
) -> dict:
    """진입 bar부터 청산까지 분봉 시뮬레이션."""
    entry_price = bars[entry_bar_idx]["close"]
    peak = entry_price
    trailing_active = False

    for i in range(entry_bar_idx + 1, len(bars)):
        bar = bars[i]
        if bar["time"] >= force_exit_time:
            pnl = (bar["close"] - entry_price) / entry_price
            return {"pnl_pct": round(pnl*100,3), "exit_time": bar["time"], "exit_reason": "force_exit", "hold_bars": i - entry_bar_idx}
        price = bar["close"]
        pnl = (price - entry_price) / entry_price
        if pnl <= stop_loss_pct:
            return {"pnl_pct": round(pnl*100,3), "exit_time": bar["time"], "exit_reason": "stop_loss", "hold_bars": i - entry_bar_idx}
        if pnl >= trailing_activate_pct:
            trailing_active = True
        if price > peak:
            peak = price
        if trailing_active and peak > 0 and (peak - price) / peak >= trailing_stop_pct:
            return {"pnl_pct": round(pnl*100,3), "exit_time": bar["time"], "exit_reason": "trailing_stop", "hold_bars": i - entry_bar_idx}

    last = bars[-1]
    pnl = (last["close"] - entry_price) / entry_price
    return {"pnl_pct": round(pnl*100,3), "exit_time": last["time"], "exit_reason": "eod", "hold_bars": len(bars) - entry_bar_idx}


async def run_backtest_intraday(
    symbols: list[str],
    date_str: str,  # YYYYMMDD
    min_price_change_pct: float = 3.0,
    max_price_change_pct: float = 10.0,
    min_volume_ratio: float = 2.5,
    entry_start: str = "09:00",
    entry_end: str = "10:30",
    stop_loss_pct: float = -0.015,
    trailing_activate_pct: float = 0.02,
    trailing_stop_pct: float = 0.01,
) -> dict:
    """하루치 분봉 백테스트."""
    ...


async def run_backtest(
    start_date: str,
    end_date: str,
    **kwargs,
) -> dict:
    """날짜 범위 백테스트 — 각 날짜별 run_backtest_intraday 호출."""
    ...
```

### prev_close 확보 방법

분봉 데이터에 전일 종가가 없으므로 pykrx로 보완:
```python
from pykrx import stock as _pykrx
dt = datetime.strptime(date_str, "%Y%m%d")
fetch_start = (dt - timedelta(days=5)).strftime("%Y%m%d")
df = _pykrx.get_market_ohlcv(fetch_start, date_str, symbol)
if df is not None and len(df) >= 2:
    prev_close = float(df["종가"].iloc[-2])
```

---

## 작업 3: backtest API 업데이트

파일: `backend/api/routes/backtest.py`

`run_backtest` 엔드포인트를 async로 변경하고 새 `run_backtest()` 호출:
- `POST /api/v1/backtest/run?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&symbols=005930,000660`
- `GET /api/v1/backtest/quick` — 어제 날짜 + 현재 DB 유니버스 종목 30개 기준 1일 백테스트

quick 백테스트는 가장 최근 거래일 1일만 빠르게 실행.

---

## 완료 기준

1. `py_compile` 통과 (decision_engine.py, backtest.py, routes/backtest.py)
2. decision_engine: `time_window` 조건이 `required_keys`에 포함됨 확인
3. 서버 재시작 후:
   ```bash
   curl -X POST "http://127.0.0.1:8000/api/v1/backtest/quick"
   ```
   - `total > 0`, 각 trade에 `exit_time`, `exit_reason` 포함
   - 오류 없이 응답 반환
4. 10:31 이후 발생 신호는 decision_engine에서 `time_window: False`로 차단 확인 (로그)

결과: `docs/agent-comm/OUTBOX_CODEX_20260522_ghost_timing.md`
