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
    "per_rate_min": ("sizing.per_position_rate_min", 0.05),        # (레거시·표시용) 종목당 최소 비중
    "per_rate_max": ("risk.max_position_rate_per_stock", 0.15),    # 폭등 티어 확대 비율 판정용
    "pos_min": ("sizing.positions_min", 6),                        # (레거시) 무결성 백스톱용
    "pos_max": ("sizing.positions_max", 19),                       # (레거시) 무결성 백스톱용
    "deploy_target": ("exploration.deploy_target_rate", 0.95),     # 총배포 상한 95%(기존키 재사용)
    # 2026-08-29 PM: 종목수 결정 폐지 → 종목당 절대금액으로 통제(투입율 + [min,max] 금액).
    "per_position_min_krw": ("sizing.per_position_min_krw", 5_000_000),   # 종목당 최소 500만
    "per_position_max_krw": ("sizing.per_position_max_krw", 20_000_000),  # 종목당 최대 2000만
}


# ── 확신도(conviction) 모델 설정키 (결정: 레짐×눌림 결합, 전부 설정화 = 언제든 수정) ──
#   conviction = regime_weight×레짐점수 + (1-regime_weight)×눌림점수
#   관리자가 regime_weight로 "장세 vs 눌림" 비중을, regime_scores로 장세별 점수를,
#   pullback_full_dist_pct로 "얼마나 눌려야 만점"을 코드 없이 조절한다.
_DEFAULT_REGIME_SCORES = {
    "risk_on": 1.0, "neutral": 0.5, "risk_off": 0.2, "volatile": 0.3, "flash_crash": 0.0,
}


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def resolve_conviction(
    regime: str, vwap_dist_pct: float | None, getter: Callable = get_setting
) -> float:
    """확신도 ∈ [0,1] = 레짐×눌림 결합 (모든 파라미터 설정화 — 언제든 수정 가능).

    - 레짐점수: `conviction.regime_scores`(JSON) — risk_on 높음, risk_off 낮음.
    - 눌림점수: VWAP 아래로 깊을수록↑. `conviction.pullback_full_dist_pct`(기본 -3%)서 만점.
      VWAP 위(추격)=0, 미상=0.5(중립).
    - 결합가중: `conviction.regime_weight`(기본 0.5) — 1.0=레짐만, 0.0=눌림만.
    """
    w = _clamp01(_f(getter, "conviction.regime_weight", 0.5))
    scores = getter("conviction.regime_scores", _DEFAULT_REGIME_SCORES) or _DEFAULT_REGIME_SCORES
    try:
        regime_score = _clamp01(float(scores.get(regime, 0.5)))
    except (TypeError, ValueError, AttributeError):
        regime_score = 0.5
    full = _f(getter, "conviction.pullback_full_dist_pct", -3.0)
    if vwap_dist_pct is None:
        pullback_score = 0.5
    elif vwap_dist_pct >= 0:
        pullback_score = 0.0            # VWAP 위 = 추격 = 눌림 확신 없음
    elif full < 0:
        pullback_score = _clamp01(vwap_dist_pct / full)   # -1.5/-3=0.5, -3↓=1.0
    else:
        pullback_score = 0.5
    return _clamp01(w * regime_score + (1.0 - w) * pullback_score)


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
    deposit: float, conviction: float, getter: Callable = get_setting,
    per_rate_max: float | None = None,
) -> SizingResult:
    """종목당 금액 사이징 (2026-08-29 PM: 종목수 결정 폐지, 투입율 + min/max 금액 통제).

    - per_position_krw  = min_krw + (max_krw − min_krw)×conviction  (확신↑ → 금액↑ = 집중)
    - target_positions  = (deposit×deploy) / per_position_krw        (순수 파생, [6,19] 클램프 제거)
    - 폭등 티어: per_rate_max가 기본 상한보다 크면 max_krw를 그 비율만큼 확대.
    종목수는 결과일 뿐 divisor가 아니다. 통제 = 투입율(deploy) + 종목당 절대금액 [min_krw, max_krw].
    per_rate_max: 폭등 사이징확대 신호(비율). None이면 확대 없음.
    """
    min_krw = _f(getter, *(_SIZING_KEYS["per_position_min_krw"][0], _SIZING_KEYS["per_position_min_krw"][1]))
    max_krw = _f(getter, *(_SIZING_KEYS["per_position_max_krw"][0], _SIZING_KEYS["per_position_max_krw"][1]))
    base_max_rate = _f(getter, *(_SIZING_KEYS["per_rate_max"][0], _SIZING_KEYS["per_rate_max"][1]))
    deploy = _f(getter, *(_SIZING_KEYS["deploy_target"][0], _SIZING_KEYS["deploy_target"][1]))
    # 폭등 사이징확대: surge 티어면 per_rate_max↑ → 최대 금액을 비례 확대.
    if per_rate_max is not None and base_max_rate > 0 and float(per_rate_max) > base_max_rate:
        max_krw = max_krw * (float(per_rate_max) / base_max_rate)
    if max_krw < min_krw:
        min_krw, max_krw = max_krw, min_krw
    c = max(0.0, min(1.0, conviction))
    per_position_krw = min_krw + (max_krw - min_krw) * c
    deposit = max(0.0, float(deposit or 0.0))
    deployable = deposit * deploy
    cnt = int(deployable / per_position_krw + 1e-9) if per_position_krw > 0 else 0
    rate = round(per_position_krw / deposit, 4) if deposit > 0 else 0.0  # 파생(표시·shadow용)
    return SizingResult(rate, cnt, round(per_position_krw, 2), round(deploy, 4))


def resolve_max_positions(getter: Callable = get_setting) -> int:
    """[6,19] 모델의 종목수 상한(하드 ceiling) — max_positions 단일 출처(결정4).

    실제 종목수는 예수금비중 사이징으로 6~19 사이 파생. 이건 fallback/백스톱용 상한.
    (주력 제약은 이미 95% 배포 캡 — order_preflight 배포 게이트.)
    """
    return _i(getter, *(_SIZING_KEYS["pos_max"]))


# 5장세 → 레짐 SET 매핑(하위호환: SET은 4종). 폭등=상승SET+사이징확대.
_REGIME5_TO_SET = {
    "crash": "risk_off", "down": "risk_off", "flat": "neutral",
    "up": "risk_on", "surge": "risk_on", "volatile": "volatile",
}


@dataclass
class Playbook:
    """한 레짐의 전략 한 벌(선정+매수+매도+사이징). 소비 엔진이 읽는 단일 계약(전략설정 엔진①)."""
    regime: str                                   # 5장세 라벨
    set_label: str = "neutral"                    # 매핑된 레짐 SET
    selection: dict = field(default_factory=dict)  # 종목선정 가중치(엔진③)
    gates: dict = field(default_factory=dict)     # 매수 게이트(엔진④)
    sell: dict = field(default_factory=dict)      # 손절·익절·트레일·수확(엔진⑤, 레짐SET)
    sizing: dict = field(default_factory=dict)    # 예수금비중 모델(엔진⑥ 사이징)


def build_playbook(regime: str, regime_settings: dict | None = None,
                   getter: Callable = get_setting) -> Playbook:
    """레짐(5장세 또는 SET) → 전략 한 벌 조립(라이브 읽기). regime_settings=레짐SET applied_settings.

    전 축을 한 곳에서: 선정 가중치·매수 게이트·매도 파라미터·예수금비중 사이징.
    이게 "레짐→플레이북" 권위의 핵심 — 나머지 엔진이 여기서 전략을 꺼내 쓴다.
    """
    rs = regime_settings or {}
    is_surge = regime == "surge"
    selection = {
        "change_weight": _f(getter, "selection.change_weight", 0.5),
        "surge_weight": _f(getter, "selection.surge_weight", 0.5),
    }
    gates = {  # 매수 게이트(엔진④) — 전 레짐 공통 값(레짐별 차등은 후속)
        "vwap_pullback_mode": getter("engine.entry_vwap_pullback_mode", "enforce"),
        "entry_max_vwap_dist_pct": _f(getter, "engine.entry_max_vwap_dist_pct", -1.0),  # VWAP -1%↓ 눌림만(BackDB검증 2026-09-01)
        "max_price_change_pct": _f(getter, "engine.max_price_change_pct", 4.0),
        "min_price_change_pct": _f(getter, "engine.min_price_change_pct", 1.5),
        "min_volume_ratio": _f(getter, "engine.min_volume_ratio", 1.5),
        "confidence_gate_mode": getter("engine.confidence_gate_mode", "regime_defensive"),
        "min_ai_confidence": _f(getter, "engine.min_ai_confidence", 0.6),
        "intraday_max_stoploss": _i(getter, "engine.intraday_max_stoploss_per_symbol", 2),
        "leverage_restriction": getter("engine.leverage_restriction_mode", "exclude"),
    }
    sell = {
        "stop_loss_rate": rs.get("stop_loss_rate"),
        "take_profit_rate": rs.get("take_profit_rate"),
        "trailing_activate_profit": rs.get("trailing_activate_profit"),
        "trailing_stop_rate": rs.get("trailing_stop_rate"),
        "harvest_mode": bool(getter("engine.harvest_mode", True)),
        "scaleout_ratio": _f(getter, "engine.scaleout_ratio", 0.6),
        "scaleout_target_rate": _f(getter, "engine.scaleout_target_rate", 0.01),
    }
    per_rate_max = (_f(getter, "sizing.surge_per_position_rate_max", 0.15) if is_surge
                    else _f(getter, *(_SIZING_KEYS["per_rate_max"])))
    sizing = {
        "per_position_rate_min": _f(getter, *(_SIZING_KEYS["per_rate_min"])),
        "per_position_rate_max": per_rate_max,
        "positions_min": _i(getter, *(_SIZING_KEYS["pos_min"])),
        "positions_max": _i(getter, *(_SIZING_KEYS["pos_max"])),
        "deploy_target_rate": _f(getter, *(_SIZING_KEYS["deploy_target"])),
        "surge_tier": is_surge,
    }
    return Playbook(regime=regime, set_label=_REGIME5_TO_SET.get(regime, regime),
                    selection=selection, gates=gates, sell=sell, sizing=sizing)


def get_playbook(regime5: str, regime_set: dict | None = None,
                 getter: Callable = get_setting) -> Playbook:
    """★ 레짐→플레이북 권위(전략설정 엔진①). 5장세 라벨 → 그 장세의 전략 한 벌.

    regime_set: 매핑된 레짐 SET의 applied_settings(매도 파라미터). 호출부가 조회해 전달.
    나머지 엔진(선정·매수·매도·매매)은 이 결과에서 전략을 읽는다(설정 4중구조 단일화의 시작).
    """
    return build_playbook(regime5, regime_settings=regime_set, getter=getter)
