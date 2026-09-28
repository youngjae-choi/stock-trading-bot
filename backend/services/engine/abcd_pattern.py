"""ABCD 눌림목 패턴 (Andrew Aziz) — 진입 검출 순수함수 + 라이브 SHADOW 신호.

A(강한 1차상승 스윙고점) → B(눌림 저점) → C(higher-low 지지 후 반등) 지점 매수.
scripts/abcd_backtest.py 검증: **우리 전 유니버스에 기계적으로 걸면 손실**(상승장 승률 2.6~24%).
그러나 Aziz의 'stocks in play'(재료+거래량 정예 = 우리 **수급 리더**) 한정 효과는 과거 수급
데이터 부재로 백테스트 불가. → **수급 리더에 한해 SHADOW(로그만)** 로 향후 상승일 forward 관찰.
**매매 영향 0 · enforce 아님.** 관찰 후 수급리더 한정에서 이기면 그때 게이트화 판정.

`detect_abcd_entry`는 scripts/abcd_backtest.py와 동일 로직(1분봉·look-ahead 없음).
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

_LB, _IMPULSE, _PULL_MIN, _PULL_MAX = 30, 2.0, 1.0, 5.0
_ENTRY_START, _ENTRY_END = "0935", "1330"

# (date, symbol, minute) 단위 캐시 — 틱마다 재계산·재조회 방지(경량화).
_eval_cache: dict[tuple[str, str, str], dict | None] = {}
_leaders_cache: dict[str, set[str]] = {}


def detect_abcd_entry(bars: list[dict], i: int, cfg: dict) -> tuple[float, float] | None:
    """바 i가 ABCD 진입인지 판정(순수·look-ahead 없음). 성립 시 (stop, target) else None.

    bars[k] = {"m","o","h","l","c","v"} (1분봉). scripts/abcd_backtest.py와 동일.
    """
    if i < 1:
        return None
    cur = bars[i]
    if not (_ENTRY_START <= cur["m"] <= _ENTRY_END):
        return None
    lo = max(0, i - cfg["lookback"])
    window = bars[lo:i]
    if len(window) < 5:
        return None
    a_idx = max(range(len(window)), key=lambda k: window[k]["h"])
    A = window[a_idx]["h"]
    if a_idx >= len(window) - 2:
        return None
    pre = window[:a_idx + 1]
    base = min(b["l"] for b in pre) if pre else A
    if base <= 0 or (A / base - 1) * 100 < cfg["impulse"]:
        return None
    after = window[a_idx + 1:]
    if not after:
        return None
    B = min(b["l"] for b in after)
    pull = (A - B) / A * 100
    if not (cfg["pull_min"] <= pull <= cfg["pull_max"]):
        return None
    price = cur["c"]
    green = cur["c"] > cur["o"]
    turning_up = cur["c"] > bars[i - 1]["c"]
    holds_support = cur["l"] >= B * (1 - 0.001)
    room_to_A = B < price < A
    if not (holds_support and room_to_A and (green or turning_up)):
        return None
    return (B * (1 - 0.001), A)


def _load_minute_bars(symbol: str, today: str) -> list[dict]:
    """intraday_bars(10초봉)를 1분봉으로 집계(scripts와 동일 방식). 실패 시 []."""
    try:
        from ..db import get_connection
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT bar_ts, open, high, low, close, volume FROM intraday_bars "
                "WHERE trade_date=? AND symbol=? ORDER BY bar_ts, id", (today, symbol)).fetchall()
        mins: dict[str, dict] = {}
        for r in rows:
            c = float(r["close"] or 0)
            if c <= 0:
                continue
            m = str(r["bar_ts"])[:4]
            v = float(r["volume"] or 0)
            b = mins.get(m)
            if b is None:
                mins[m] = {"m": m, "o": float(r["open"] or c), "h": float(r["high"] or c),
                           "l": float(r["low"] or c), "c": c, "v": v}
            else:
                b["h"] = max(b["h"], float(r["high"] or c)); b["l"] = min(b["l"], float(r["low"] or c))
                b["c"] = c; b["v"] += v
        return [mins[m] for m in sorted(mins)]
    except Exception:
        return []


def is_supply_leader(symbol: str, today: str | None = None) -> bool:
    """오늘 수급 선정에서 이 종목이 순매수(수급 양+) 리더인지 — universe_filter_results 기준.

    supply_score >= 0.5 (외국인+기관 순매수 양). 데이터 없으면 False(shadow 미기록). 일 단위 캐시.
    """
    try:
        import json

        from ..db import get_connection
        if today is None:
            today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
        leaders = _leaders_cache.get(today)
        if leaders is None:
            leaders = set()
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT items FROM universe_filter_results WHERE trade_date=? ORDER BY rowid DESC LIMIT 1",
                    (today,)).fetchone()
            if row and row["items"]:
                for it in json.loads(row["items"]):
                    try:
                        if float(it.get("supply_score", 0) or 0) >= 0.5:
                            leaders.add(str(it.get("symbol")))
                    except (TypeError, ValueError):
                        continue
            _leaders_cache.clear()
            _leaders_cache[today] = leaders
        return symbol in leaders
    except Exception:
        return False


def abcd_shadow_signal(symbol: str, today: str | None = None) -> dict | None:
    """수급 리더 한해 라이브 ABCD 신호(최신 1분봉 기준). 로그/기록용. 매매 영향 없음.

    반환 {entry, stop, target} 또는 None. (symbol, 분) 캐시로 틱마다 재조회 방지.
    """
    if today is None:
        today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    if not is_supply_leader(symbol, today):
        return None
    now_m = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%H%M")
    key = (today, symbol, now_m)
    if key in _eval_cache:
        return _eval_cache[key]
    _eval_cache.clear()  # 분 바뀌면 이전 캐시 폐기(메모리 상한)
    bars = _load_minute_bars(symbol, today)
    cfg = {"lookback": _LB, "impulse": _IMPULSE, "pull_min": _PULL_MIN, "pull_max": _PULL_MAX}
    sig = None
    if len(bars) >= 7:
        got = detect_abcd_entry(bars, len(bars) - 1, cfg)
        if got is not None:
            sig = {"entry": bars[-1]["c"], "stop": got[0], "target": got[1]}
    _eval_cache[key] = sig
    return sig
