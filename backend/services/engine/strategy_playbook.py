"""전략설정 엔진 — 레짐별 플레이북 단일 권위 (Phase 1, Increment 1).

시장분위기(레짐)를 판단하면 그에 대응하는 **플레이북**(그 장세의 종목선정·매수게이트·
매도·사이징 파라미터 한 벌)을 꺼내 쓴다. 나머지 엔진(시장감지·선정·매수·매도·매매)은
흩어진 소스 대신 **여기 하나**만 읽는다. (system_settings + 레짐SET + 코드기본 통합)

핵심: **사이징은 예수금 투입비중 기반**(결정4) — 종목당 5~15% 비중, 종목수 6~19는 파생.
확신↑ → 종목당 비중↑ → 집중(6종목). 확신↓ → 분산(19종목). 총배포 상한 95%.

Increment 1: 사이징 모델 + 플레이북 조립(읽기). 아직 소비자 미배선 = 동작 불변.
소비자(order_executor 등) 전환은 다음 Increment에서 shadow 검증 후.

관리자 수정: 아래 설정키를 바꾸면 재기동 없이 반영(get_setting은 캐시리스).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..settings_store import get_setting

# ── 사이징 모델 설정키 (결정4) — 관리자가 이 값으로 전략 조절 ──
#   per_position_rate ∈ [min, max] · positions ∈ [min, max] · 총배포 deploy_target
_SIZING_KEYS = {
    "per_rate_min": ("sizing.per_position_rate_min", 0.05),        # 종목당 최소 비중 5%
    "per_rate_max": ("risk.max_position_rate_per_stock", 0.15),    # 종목당 최대 비중 15%(기존키 재사용)
    "pos_min": ("sizing.positions_min", 6),                        # 최소 종목수
    "pos_max": ("sizing.positions_max", 19),                       # 최대 종목수
    "deploy_target": ("exploration.deploy_target_rate", 0.95),     # 총배포 상한 95%(기존키 재사용)
}


@dataclass
class SizingResult:
    """한 종목 진입 시 예수금비중 사이징 결과."""
    per_position_rate: float   # 종목당 예수금 비중 [min, max]
    target_positions: int      # 이 확신도에서의 목표 종목수 [min, max]
    per_position_krw: float    # 종목당 투입 금액
    deploy_target_rate: float  # 총 배포 상한


def _f(getter, key, default):
    try:
        return float(getter(key, default))
    except (TypeError, ValueError):
        return float(default)


def _i(getter, key, default):
    try:
        return int(float(getter(key, default)))
    except (TypeError, ValueError):
        return int(default)


def resolve_position_sizing(
    deposit: float, conviction: float, getter: Callable = get_setting
) -> SizingResult:
    """예수금비중 사이징 (결정4). conviction∈[0,1]: 높을수록 집중(비중↑·종목수↓).

    - per_position_rate = min + (max-min)×conviction  (확신↑ → 비중↑)
    - target_positions  = clamp(deploy_target / rate, [pos_min, pos_max])  (파생)
    - per_position_krw  = deposit × per_position_rate
    종목수는 결과일 뿐 사이징의 divisor가 아니다.
    """
    lo = _f(getter, *(_SIZING_KEYS["per_rate_min"][0], _SIZING_KEYS["per_rate_min"][1]))
    hi = _f(getter, *(_SIZING_KEYS["per_rate_max"][0], _SIZING_KEYS["per_rate_max"][1]))
    pmin = _i(getter, *(_SIZING_KEYS["pos_min"][0], _SIZING_KEYS["pos_min"][1]))
    pmax = _i(getter, *(_SIZING_KEYS["pos_max"][0], _SIZING_KEYS["pos_max"][1]))
    deploy = _f(getter, *(_SIZING_KEYS["deploy_target"][0], _SIZING_KEYS["deploy_target"][1]))
    if hi < lo:
        lo, hi = hi, lo
    c = max(0.0, min(1.0, conviction))
    rate = lo + (hi - lo) * c
    cnt = int(deploy / rate + 1e-9) if rate > 0 else pmax  # +eps: 0.95/0.05=18.999 부동소수 보정
    cnt = max(pmin, min(pmax, cnt))
    deposit = max(0.0, float(deposit or 0.0))
    return SizingResult(round(rate, 4), cnt, round(deposit * rate, 2), round(deploy, 4))


@dataclass
class Playbook:
    """한 레짐의 전략 한 벌. 소비 엔진이 읽는 단일 계약."""
    regime: str
    sell: dict = field(default_factory=dict)      # 손절·익절·트레일·수확 (레짐SET)
    sizing: dict = field(default_factory=dict)    # 예수금비중 모델 파라미터
    gates: dict = field(default_factory=dict)     # 매수 게이트 (다음 Increment 확장)


def build_playbook(regime: str, regime_settings: dict | None = None,
                   getter: Callable = get_setting) -> Playbook:
    """레짐 라벨 → 플레이북 조립(라이브 읽기). regime_settings=레짐SET applied_settings."""
    rs = regime_settings or {}
    sell = {
        "stop_loss_rate": rs.get("stop_loss_rate"),
        "take_profit_rate": rs.get("take_profit_rate"),
        "trailing_activate_profit": rs.get("trailing_activate_profit"),
        "trailing_stop_rate": rs.get("trailing_stop_rate"),
        "harvest_mode": bool(getter("engine.harvest_mode", True)),
        "scaleout_ratio": _f(getter, "engine.scaleout_ratio", 0.6),
        "scaleout_target_rate": _f(getter, "engine.scaleout_target_rate", 0.01),
    }
    sizing = {
        "per_position_rate_min": _f(getter, *(_SIZING_KEYS["per_rate_min"])),
        "per_position_rate_max": _f(getter, *(_SIZING_KEYS["per_rate_max"])),
        "positions_min": _i(getter, *(_SIZING_KEYS["pos_min"])),
        "positions_max": _i(getter, *(_SIZING_KEYS["pos_max"])),
        "deploy_target_rate": _f(getter, *(_SIZING_KEYS["deploy_target"])),
    }
    return Playbook(regime=regime, sell=sell, sizing=sizing)
