"""종목선정 엔진 — 선정 점수(등락률+거래량급증) 검증 (엔진③).

기존 universe_filter._score_and_rank와 동일 로직, 가중치만 설정화.
"""
from __future__ import annotations

from backend.services.engine.stock_selection import selection_score

_CFG = {"selection.change_weight": 0.5, "selection.surge_weight": 0.5}


def _g(key, default=None):
    return _CFG.get(key, default)


def test_top_rank_high_score():
    # 등락률 1위 + 거래량급증 300%(포화) → 0.5*1.0 + 0.5*1.0 = 1.0
    s = selection_score(change_rank=1, volume_surge=300.0, total=40, getter=_g)
    assert s == 1.0


def test_rank_based_change_score():
    # 40개 중 20위 → 등락률점수 (40-20+1)/40 = 0.525
    s = selection_score(change_rank=20, volume_surge=0.0, volume_rank=1, total=40, getter=_g)
    # change 0.525*0.5 + surge(1위=1.0)*0.5 = 0.2625+0.5=0.7625
    assert abs(s - 0.7625) < 1e-6


def test_change_rate_fallback_when_no_rank():
    # 순위 없으면(9999) 등락률 정규화 (change+30)/60. change=+3 → 33/60=0.55
    s = selection_score(change_rate=3.0, change_rank=None, volume_surge=150.0, total=40, getter=_g)
    # change 0.55*0.5 + surge(150/300=0.5)*0.5 = 0.275+0.25=0.525
    assert abs(s - 0.525) < 1e-6


def test_weights_configurable():
    # 등락률 가중 1.0, 거래량 0 → 등락률 점수만
    cfg = {"selection.change_weight": 1.0, "selection.surge_weight": 0.0}
    s = selection_score(change_rank=1, volume_surge=300.0, total=40,
                        getter=lambda k, d=None: cfg.get(k, d))
    assert s == 1.0  # 등락률 1위 = 1.0 * 1.0
    s2 = selection_score(change_rank=40, volume_surge=300.0, total=40,
                         getter=lambda k, d=None: cfg.get(k, d))
    assert abs(s2 - (1 / 40)) < 1e-6  # 꼴찌 등락률, 거래량 무시


def test_score_clamped_0_1():
    for cr in (-50.0, 0.0, 50.0):
        s = selection_score(change_rate=cr, volume_surge=1000.0, total=40, getter=_g)
        assert 0.0 <= s <= 1.0
