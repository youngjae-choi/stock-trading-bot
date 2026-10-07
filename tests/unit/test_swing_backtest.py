"""스윙 백테스트 엔진 — 체결 시점·청산·미래정보 차단·통계 검증(가짜 일봉 패널)."""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

_spec = importlib.util.spec_from_file_location("swbt", Path(__file__).resolve().parents[2] / "scripts" / "swing_backtest.py")
sw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sw)

N = 220
DATES = [d.strftime("%Y%m%d") for d in pd.bdate_range("2025-01-01", periods=N)]


def _panels(close_by_sym, open_by_sym=None, low_by_sym=None, vol_by_sym=None):
    P = {}
    c = pd.DataFrame(close_by_sym, index=DATES)
    P["close"] = c
    P["open"] = pd.DataFrame(open_by_sym, index=DATES) if open_by_sym else c.copy()
    P["high"] = np.maximum(P["open"], c)
    P["low"] = pd.DataFrame(low_by_sym, index=DATES) if low_by_sym else np.minimum(P["open"], c)
    P["volume"] = pd.DataFrame(vol_by_sym, index=DATES) if vol_by_sym else c * 0 + 1000.0
    P["amount"] = c * P["volume"]
    return P


def _trend(i0=0.0):
    return np.array([10000 * (1 + 0.0005 * i) + i0 for i in range(N)])


def _breakout_case():
    c = _trend()
    c[160:] = c[159] * 1.03  # 160일 돌파 후 횡보
    v = np.full(N, 1000.0); v[160] = 3000.0
    return c, v


def test_breakout_enters_next_open_and_gap_stop_fills_at_open():
    c, v = _breakout_case()
    o = c.copy(); lo = c.copy()
    entry = o[161]
    o[163] = lo[163] = c[163] = entry * 0.85  # 갭 하락 → 손절가(0.92) 아닌 시가 0.85에 체결
    P = _panels({"A": c, "B": _trend(5)}, {"A": o, "B": _trend(5)}, {"A": lo, "B": _trend(5)}, {"A": v, "B": np.full(N, 1000.0)})
    tr = sw.breakout_trades(P, sw.universe(P))
    t = tr[tr.sym == "A"].iloc[0]
    assert t.t == DATES[160] and t.why == "stop"
    assert abs(t.gross - (-0.15)) < 1e-9


def test_breakout_ma20_exit_next_open():
    c, v = _breakout_case()
    o = c.copy()
    c[170] = c[169] * 0.80  # 20일선 아래 종가 → 다음날(171) 시가 청산
    o[171] = c[169] * 0.95
    c[171:] = c[169] * 0.95
    o[172:] = c[172:]
    P = _panels({"A": c, "B": _trend(5)}, {"A": o, "B": _trend(5)}, {"A": np.minimum(o, c) * 0 + np.minimum(o, c).min() * 0 + np.minimum(o, c), "B": _trend(5)}, {"A": v, "B": np.full(N, 1000.0)})
    # 손절(0.92)에 걸리지 않게 저가 = min(시가, 종가)지만 170일 종가 0.80 → 손절 먼저 성립하므로 저가를 진입가 위로 고정
    P["low"].loc[:, "A"] = np.maximum(P["low"]["A"], o[161] * 0.93)
    tr = sw.breakout_trades(P, sw.universe(P))
    t = tr[tr.sym == "A"].iloc[0]
    assert t.why == "ma20"
    assert abs(t.gross - (o[171] / o[161] - 1)) < 1e-9


def test_cohort_uses_next_open_and_hold_5_days():
    c = {f"S{k}": _trend(k) for k in range(60)}
    o = {s: v.copy() for s, v in c.items()}
    P = _panels(c, o)
    df = sw.cohorts(P, sw.universe(P), "rev")
    i = DATES.index(df.t.iloc[0])
    sel_ret = np.mean([o[s][i + 6] / o[s][i + 1] - 1 for s in c])  # 평탄 추세에선 모든 종목 수익률 동일
    assert abs(df.B.iloc[0] - sel_ret) < 1e-9


def test_no_lookahead_future_jump_does_not_change_pick():
    c = {f"S{k}": _trend(k) for k in range(60)}
    P1 = _panels(c)
    base = sw.cohorts(P1, sw.universe(P1), "mom")
    c2 = {s: v.copy() for s, v in c.items()}
    c2["S0"][200:] *= 1.25  # 형성일 이후만 변경
    P2 = _panels(c2)
    alt = sw.cohorts(P2, sw.universe(P2), "mom")
    a = base[base.t < DATES[190]].reset_index(drop=True)
    b = alt[alt.t < DATES[190]].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)


def test_newey_west_shrinks_t_for_autocorrelated_series():
    x = np.repeat([0.01, -0.005, 0.008, -0.002], 25) + 0.001
    naive = x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))
    assert sw.newey_west_t(x) < naive


def test_hansen_hodrick_null_size_on_overlapping_5day_cohorts():
    """검토 지적: Bartlett lag4는 5일 겹침 묶음에서 t를 부풀린다 → 균등 가중(HH) 사용 시 귀무 t 표준편차 ≈ 1."""
    rng = np.random.default_rng(0)
    ts = []
    for _ in range(1500):
        d = rng.standard_normal(190)
        x = np.convolve(d, np.ones(5), "valid")  # 5일 겹침 합
        ts.append(sw.newey_west_t(x, 4, uniform=True))
    sd = np.nanstd(ts)
    assert 0.9 < sd < 1.15


def test_exact_limit_up_is_not_an_outlier():
    """+30% 상한가(부동소수 0.30000000000000004)는 이상치가 아니다 → LIMIT 0.31."""
    assert abs(17290 / 13300 - 1) <= sw.LIMIT


def test_halt_rows_become_untradeable(tmp_path):
    d = tmp_path / "daily"; d.mkdir()
    pd.DataFrame({"date": DATES[:3], "open": [100.0, 100.0, 110.0], "high": [100.0, 100.0, 111.0], "low": [100.0, 100.0, 109.0],
                  "close": [100.0, 100.0, 110.0], "volume": [10.0, 0.0, 10.0], "amount": [1e3, 0.0, 1e3]}).to_parquet(d / "A.parquet")
    P = sw.load_panels(tmp_path)
    assert np.isnan(P["open"].loc[DATES[1], "A"]) and P["volume"].loc[DATES[1], "A"] == 0
    assert abs(sw._ret(P["close"]).loc[DATES[2], "A"] - 0.10) < 1e-12  # 재개일 변화는 직전 유효 종가 기준


def test_h3_formation_cutoff_leaves_room_for_full_hold():
    c, v = _breakout_case()
    c[N - 15] = c[N - 16] * 1.05  # 데이터 끝 15일 전 재돌파 → 최대 보유가 안 들어감 → 제외
    P = _panels({"A": c, "B": _trend(5)}, None, None, {"A": np.where(np.arange(N) == N - 15, 3000.0, v), "B": np.full(N, 1000.0)})
    tr = sw.breakout_trades(P, sw.universe(P))
    assert (tr.e.astype(int) <= N - sw.H3_MAX).all()
