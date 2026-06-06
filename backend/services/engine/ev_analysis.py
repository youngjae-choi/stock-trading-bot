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
