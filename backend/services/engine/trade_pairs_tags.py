"""거래내역(pair) 리스트에 trade_entry_tags 태그를 병합한다(선정/매수 사유 요약 포함).

UI(Trade History)가 한 행에서 "왜 골랐고·왜 샀고·어떻게 끝났나"를 보여주기 위해
trade_pairs.get_trade_pairs() 결과 각 pair에 매수 order_id 기준으로 태그를 붙인다.
"""

from __future__ import annotations

from typing import Any


def _buy_order_ids(pair: dict[str, Any]) -> list[str]:
    """pair.orders[] 중 매수 주문의 id 후보(id 또는 order_id)를 모은다."""
    ids: list[str] = []
    for o in pair.get("orders") or []:
        if str(o.get("side") or "").lower() != "buy":
            continue
        oid = o.get("id") or o.get("order_id")
        if oid:
            ids.append(str(oid))
    return ids


def _selection_summary(tag: dict[str, Any]) -> str:
    """선정사유를 한 줄 요약: sources 조인 + (있으면) llm_note."""
    sr = tag.get("selection_reason") or {}
    sources = sr.get("sources") or []
    note = str(sr.get("llm_note") or "").strip()
    head = " · ".join(str(s) for s in sources)
    if head and note:
        return head + " · " + note
    return head or note


def enrich_pairs_with_tags(pairs: list[dict[str, Any]], tags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """각 pair에 entry_tag + selection_summary + buy_reason_summary 를 더해 반환한다.

    매칭 우선순위: (1) 매수 order_id == tag.order_id, (2) symbol+trade_date 폴백.
    원본 pair dict를 변형하지 않고 얕은 복사본을 반환한다.

    Args:
        pairs: trade_pairs.get_trade_pairs() 결과.
        tags: trade_tagging.load_tags(trade_date) 결과(여러 날 합쳐도 됨).
    """
    by_order: dict[str, dict[str, Any]] = {}
    by_sym_date: dict[tuple[str, str], dict[str, Any]] = {}
    for t in tags:
        oid = str(t.get("order_id") or "")
        if oid:
            by_order.setdefault(oid, t)
        key = (str(t.get("symbol") or ""), str(t.get("trade_date") or ""))
        by_sym_date.setdefault(key, t)

    out: list[dict[str, Any]] = []
    for pair in pairs:
        enriched = dict(pair)
        tag = None
        for oid in _buy_order_ids(pair):
            if oid in by_order:
                tag = by_order[oid]
                break
        if tag is None:
            key = (str(pair.get("symbol") or ""), str(pair.get("trade_date") or ""))
            tag = by_sym_date.get(key)

        enriched["entry_tag"] = tag
        if tag:
            enriched["selection_summary"] = _selection_summary(tag)
            enriched["buy_reason_summary"] = " / ".join(str(g) for g in (tag.get("fired_groups") or []))
        else:
            enriched["selection_summary"] = ""
            enriched["buy_reason_summary"] = ""
        out.append(enriched)
    return out
