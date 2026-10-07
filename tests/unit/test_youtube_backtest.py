"""유튜브 전략 백테스트 엔진 — 체결·청산·통계 로직 검증(가짜 분봉)."""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

_spec = importlib.util.spec_from_file_location("ytbt", Path(__file__).resolve().parents[2] / "scripts" / "youtube_strategy_backtest.py")
bt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bt)


def _day(price=100.0, patch=None):
    """09:00~15:19 평탄 분봉. patch = {분(분봉시작): dict(o,h,l,c)}"""
    rows = []
    for tm in range(540, 920):
        r = dict(o=price, h=price, l=price, c=price)
        if patch and tm in patch:
            r.update(patch[tm])
        rows.append((f"{tm // 60:02d}{tm % 60:02d}", r["o"], r["h"], r["l"], r["c"], 1000.0, 0.0))
    return bt.SymDay(pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume", "cum_amount"]).assign(symbol="X"))


def test_gap_through_stop_fills_at_open():
    sd = _day(patch={690: dict(o=95.0, h=95.0, l=94.0, c=95.0)})  # 11:30 갭하락
    e = sd.bar_at(640)
    gross, why, _ = bt.simulate(sd, e, 97.0, trend=False)
    assert why == "stop" and abs(gross - (-0.05)) < 1e-9


def test_intrabar_stop_fills_at_stop_price():
    sd = _day(patch={690: dict(o=99.0, h=99.0, l=96.0, c=98.0)})
    gross, why, _ = bt.simulate(sd, sd.bar_at(640), 97.0, trend=False)
    assert why == "stop" and abs(gross - (-0.03)) < 1e-9


def test_force_exit_at_1510_open():
    sd = _day(patch={910: dict(o=102.0, h=102.0, l=102.0, c=102.0)})
    gross, why, hold = bt.simulate(sd, sd.bar_at(640), 97.0, trend=False)
    assert why == "force" and abs(gross - 0.02) < 1e-9 and hold == 910 - 640


def test_trend_exit_on_completed_five_minute_close_below_ma():
    # 11:30부터 99.5로 하락 지속 → 11:30~11:34 5분봉 완성(11:35) 후 첫 봉 시가에서 청산
    patch = {tm: dict(o=99.5, h=99.5, l=99.5, c=99.5) for tm in range(690, 920)}
    sd = _day(patch=patch)
    gross, why, _ = bt.simulate(sd, sd.bar_at(640), 90.0, trend=True)
    assert why == "trend"
    assert abs(gross - (-0.005)) < 1e-9


def test_decisions_use_completed_bars_only():
    sd = _day()
    c5, h5, l5, ma = sd.five()
    assert np.isnan(ma[18]) and not np.isnan(ma[19])          # 20개 완성 전엔 MA 없음 → 최초 10:40 완성
    assert sd.bar_at(640) == int(np.where(sd.tm >= 640)[0][0])  # 신호 완성 시각 이후 첫 봉에서 체결


def test_jump_filter_marks_symbol_day_unusable():
    sd = _day(patch={700: dict(o=130.0, h=130.0, l=130.0, c=130.0)})
    assert sd.ok is False


def test_cluster_t_uses_day_clustered_se():
    # 같은 날 동일 값 10개 + 다른 날 -1 → 거래 단위 t는 크지만 날짜 클러스터 t는 작아야 한다
    r = np.array([0.01] * 10 + [-0.002] * 5)
    d = np.array(["a"] * 10 + ["b"] * 5)
    naive = r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))
    assert bt.cstat(r, d)["t"] < naive
