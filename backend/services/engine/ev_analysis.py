"""탐색엔진 EV 측정·가지치기 — 순수 함수 (DB/WS 무관, 합성 태그 dict 로 단위테스트 가능).

입력은 trade_tagging.load_tags() 가 반환하는 태그 dict 리스트다.
EV = win_rate*avg_win − loss_rate*avg_loss (승률만이 아니라 손익비 포함).
정산 안 된 태그(outcome 비었거나 realized_pnl 부재)는 표본에서 제외한다.
"""

from __future__ import annotations

from typing import Any

# 지원 차원. "condition"(개별 원자조건 임계 충족별 EV)은 후속 — per-fired_group 이 must-have.
_DIMENSIONS = ("fired_group", "selection_source", "regime")


def _settled_pnl(tag: dict[str, Any]) -> float | None:
    """정산된 태그면 realized_pnl(float)을, 미정산이면 None 을 반환한다."""
    outcome = tag.get("outcome") or {}
    if not isinstance(outcome, dict) or "realized_pnl" not in outcome:
        return None
    try:
        return float(outcome["realized_pnl"])
    except (TypeError, ValueError):
        return None


def _is_win(tag: dict[str, Any], pnl: float) -> bool:
    """승패 판정 — outcome.win(bool) 1순위, 없으면 realized_pnl>0."""
    outcome = tag.get("outcome") or {}
    win = outcome.get("win")
    if isinstance(win, bool):
        return win
    return pnl > 0.0


def _keys_for_dimension(tag: dict[str, Any], dimension: str) -> list[str]:
    """태그가 기여할 버킷 키(들)를 차원별로 반환한다.

    fired_group/selection_source 는 리스트라 다중 키, regime 은 단일 키.
    """
    if dimension == "fired_group":
        return [str(g) for g in (tag.get("fired_groups") or []) if str(g)]
    if dimension == "selection_source":
        sources = (tag.get("selection_reason") or {}).get("sources") or []
        return [str(s) for s in sources if str(s)]
    if dimension == "regime":
        regime = (tag.get("market_context") or {}).get("regime")
        return [str(regime)] if regime not in (None, "") else []
    raise ValueError(f"unknown dimension: {dimension}")


def _accumulate(
    buckets: dict[str, dict[str, float]], key: str, weight: float, pnl: float, win: bool
) -> None:
    """버킷에 가중 1건을 누적한다 — 승/패 가중 카운트와 가중 PnL 합."""
    b = buckets.setdefault(key, {"win_w": 0.0, "loss_w": 0.0, "win_pnl": 0.0, "loss_pnl": 0.0})
    if win:
        b["win_w"] += weight
        b["win_pnl"] += weight * pnl
    else:
        b["loss_w"] += weight
        b["loss_pnl"] += weight * abs(pnl)


def _aggregate_buckets(buckets: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    """가중 버킷 → {key: {n, wins, win_rate, avg_win, avg_loss, ev}} 통계로 변환한다.

    n/wins 는 가중 합(분할 가중 시 소수 허용). avg_win/avg_loss 는 가중 평균.
    """
    results: dict[str, dict[str, float]] = {}
    for key, b in buckets.items():
        wins = b["win_w"]
        losses = b["loss_w"]
        n = wins + losses
        if n <= 0:
            continue
        win_rate = wins / n
        loss_rate = losses / n
        avg_win = b["win_pnl"] / wins if wins else 0.0
        avg_loss = b["loss_pnl"] / losses if losses else 0.0
        ev = win_rate * avg_win - loss_rate * avg_loss
        results[key] = {
            "n": round(n, 6),
            "wins": round(wins, 6),
            "win_rate": round(win_rate, 6),
            "avg_win": round(avg_win, 6),
            "avg_loss": round(avg_loss, 6),
            "ev": round(ev, 6),
        }
    return results


def compute_ev_by_dimension(
    tags: list[dict[str, Any]], dimension: str, *, fractional: bool = True
) -> dict[str, dict[str, float]]:
    """차원별 EV 집계 → {key: {n, wins, win_rate, avg_win, avg_loss, ev}}.

    fractional=True(기본)면 한 태그가 키 N개에 속할 때 각 버킷에 1/N 가중으로
    집계한다 — 같은 PnL 의 중복 집계(독립성 위반·표본 과대평가) 방지.
    fractional=False 면 기존처럼 각 버킷에 1건씩(하위 호환).

    Args:
        tags: trade_tagging.load_tags() 형태의 태그 dict 리스트.
        dimension: "fired_group" | "selection_source" | "regime".
        fractional: 다중 키 분할 가중 여부(기본 True).
    """
    if dimension not in _DIMENSIONS:
        raise ValueError(f"unknown dimension: {dimension}")

    buckets: dict[str, dict[str, float]] = {}
    for tag in tags:
        pnl = _settled_pnl(tag)
        if pnl is None:
            continue  # 미정산 제외
        win = _is_win(tag, pnl)
        keys = _keys_for_dimension(tag, dimension)
        if not keys:
            continue
        weight = (1.0 / len(keys)) if fractional else 1.0
        for key in keys:
            _accumulate(buckets, key, weight, pnl, win)
    return _aggregate_buckets(buckets)


def compute_ev_stratified(
    tags: list[dict[str, Any]], *, by: tuple[str, str] = ("regime", "fired_group")
) -> dict[str, dict[str, float]]:
    """2차원 층화 EV 집계 → {"키1|키2": {n, wins, win_rate, avg_win, avg_loss, ev}}.

    레짐이 교란변수로 작용하는 것을 보기 위한 층화 — 기본 ("regime", "fired_group")
    이면 "risk_on|돌파전략" 같은 복합 키로 집계한다. 분할 가중 적용:
    한 태그가 복합 키 M개(키1 N1개 × 키2 N2개)에 속하면 각 버킷에 1/M 가중.
    어느 한 차원의 키가 비어 있는 태그는 층화 불가로 제외한다.

    Args:
        tags: trade_tagging.load_tags() 형태의 태그 dict 리스트.
        by: 층화할 차원 2개(둘 다 _DIMENSIONS 소속이어야 함).
    """
    if len(by) != 2:
        raise ValueError(f"stratify needs exactly 2 dimensions: {by}")
    for dim in by:
        if dim not in _DIMENSIONS:
            raise ValueError(f"unknown dimension: {dim}")

    buckets: dict[str, dict[str, float]] = {}
    for tag in tags:
        pnl = _settled_pnl(tag)
        if pnl is None:
            continue  # 미정산 제외
        win = _is_win(tag, pnl)
        keys1 = _keys_for_dimension(tag, by[0])
        keys2 = _keys_for_dimension(tag, by[1])
        if not keys1 or not keys2:
            continue  # 한쪽 차원 결측 → 층화 불가
        weight = 1.0 / (len(keys1) * len(keys2))
        for k1 in keys1:
            for k2 in keys2:
                _accumulate(buckets, f"{k1}|{k2}", weight, pnl, win)
    return _aggregate_buckets(buckets)


def filter_regime_confounded(
    recommendations: list[dict[str, Any]],
    stratified: dict[str, dict[str, float]],
    min_sample: int = 30,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """레짐 교란 방어 — 전체 평균 EV 음수라도 특정 레짐 층에서 양수인 대상은 권고에서 뺀다.

    제외 조건: 층화 결과("레짐|그룹")에서 그룹이 target 과 일치하고
    EV>0 AND 층 표본 n>=min_sample/2 인 층이 하나라도 존재.
    "risk_on 에서만 좋은 전략"이 전체 평균으로 가지치기되는 것을 막는다.

    Args:
        recommendations: recommend_pruning() 출력.
        stratified: compute_ev_stratified() 출력 {"레짐|그룹": stats}.
        min_sample: 가지치기 최소 표본(층 임계는 그 절반).

    Returns:
        (kept, skipped) — skipped 는 [{target, reason="regime_positive_layer",
        positive_layers, ev}].
    """
    half_sample = min_sample / 2.0
    kept: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for rec in recommendations or []:
        target = str(rec.get("target") or "")
        positive_layers = sorted(
            key for key, stat in (stratified or {}).items()
            if key.split("|", 1)[-1] == target
            and float(stat.get("ev", 0.0)) > 0.0
            and float(stat.get("n", 0.0)) >= half_sample
        )
        if positive_layers:
            skipped.append({
                "target": target,
                "reason": "regime_positive_layer",
                "positive_layers": positive_layers,
                "ev": rec.get("ev"),
            })
        else:
            kept.append(rec)
    return kept, skipped


def recommend_pruning(
    ev_results: dict[str, dict[str, float]],
    min_sample: int = 30,
    disable_sample: int = 90,
) -> list[dict[str, Any]]:
    """EV 음수 대상을 negative-first 로 가지치기 추천한다 — "사지/고르지 말아야 할" 도출.

    표본 n≥min_sample AND ev<0 인 대상만 추천한다. 기본 action 은 "downweight",
    표본이 매우 크고(n≥disable_sample) 지속 음수일 때만 "disable"(운 좋은 전략 안 죽임).
    출력은 EV 오름차순(가장 나쁜 것 먼저).

    Args:
        ev_results: compute_ev_by_dimension() 출력 {key: {n, ev, ...}}.
        min_sample: 가지치기 최소 표본(기본 30).
        disable_sample: disable 로 격상할 대표본 임계(기본 90).
    """
    recs: list[dict[str, Any]] = []
    for target, stat in ev_results.items():
        n = float(stat.get("n", 0.0))  # 분할 가중 시 소수 표본 허용 — 가중 n 기준 비교
        ev_value = float(stat.get("ev", 0.0))
        if n < min_sample or ev_value >= 0.0:
            continue
        action = "disable" if n >= disable_sample else "downweight"
        win_rate = float(stat.get("win_rate", 0.0))
        reason = (
            f"표본 {n:g}건 · 승률 {win_rate:.0%} · EV {ev_value:+.0f} "
            f"({'대표본 지속 음수 → 비활성' if action == 'disable' else 'EV 음수 → 가중 하향'})"
        )
        recs.append({"target": target, "action": action, "reason": reason,
                     "n": n, "ev": round(ev_value, 6)})
    recs.sort(key=lambda r: r["ev"])  # 가장 나쁜 것 먼저 (negative-first)
    return recs
