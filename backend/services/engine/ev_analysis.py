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


def compute_ev_by_dimension(tags: list[dict[str, Any]], dimension: str) -> dict[str, dict[str, float]]:
    """차원별 EV 집계 → {key: {n, wins, win_rate, avg_win, avg_loss, ev}}.

    Args:
        tags: trade_tagging.load_tags() 형태의 태그 dict 리스트.
        dimension: "fired_group" | "selection_source" | "regime".
    """
    if dimension not in _DIMENSIONS:
        raise ValueError(f"unknown dimension: {dimension}")

    # key -> {"win_pnls": [..], "loss_pnls": [..]} (loss_pnls 는 양수 손실 크기)
    buckets: dict[str, dict[str, list[float]]] = {}
    for tag in tags:
        pnl = _settled_pnl(tag)
        if pnl is None:
            continue  # 미정산 제외
        win = _is_win(tag, pnl)
        for key in _keys_for_dimension(tag, dimension):
            b = buckets.setdefault(key, {"win_pnls": [], "loss_pnls": []})
            if win:
                b["win_pnls"].append(pnl)
            else:
                b["loss_pnls"].append(abs(pnl))

    results: dict[str, dict[str, float]] = {}
    for key, b in buckets.items():
        wins = len(b["win_pnls"])
        losses = len(b["loss_pnls"])
        n = wins + losses
        if n == 0:
            continue
        win_rate = wins / n
        loss_rate = losses / n
        avg_win = sum(b["win_pnls"]) / wins if wins else 0.0
        avg_loss = sum(b["loss_pnls"]) / losses if losses else 0.0
        ev = win_rate * avg_win - loss_rate * avg_loss
        results[key] = {
            "n": n,
            "wins": wins,
            "win_rate": round(win_rate, 6),
            "avg_win": round(avg_win, 6),
            "avg_loss": round(avg_loss, 6),
            "ev": round(ev, 6),
        }
    return results


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
        n = int(stat.get("n", 0))
        ev_value = float(stat.get("ev", 0.0))
        if n < min_sample or ev_value >= 0.0:
            continue
        action = "disable" if n >= disable_sample else "downweight"
        win_rate = float(stat.get("win_rate", 0.0))
        reason = (
            f"표본 {n}건 · 승률 {win_rate:.0%} · EV {ev_value:+.0f} "
            f"({'대표본 지속 음수 → 비활성' if action == 'disable' else 'EV 음수 → 가중 하향'})"
        )
        recs.append({"target": target, "action": action, "reason": reason,
                     "n": n, "ev": round(ev_value, 6)})
    recs.sort(key=lambda r: r["ev"])  # 가장 나쁜 것 먼저 (negative-first)
    return recs
