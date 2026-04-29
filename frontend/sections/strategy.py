"""Streamlit section for strategy schema/mapping and search-filter pipeline."""

from __future__ import annotations

from typing import Any, Callable, Dict

import pandas as pd
import streamlit as st


def render_strategy_section(
    *,
    base_url: str,
    responses: Dict[str, Any],
    request_json: Callable[..., Dict[str, Any]],
    render_call_status: Callable[[str, Dict[str, Any] | None], None],
    render_payload_expander: Callable[[str, Any], None],
    as_dict: Callable[[Any], Dict[str, Any]],
    format_dataframe_accounting: Callable[[pd.DataFrame], pd.DataFrame],
) -> None:
    """Render strategy setup and keyword+filter test UI."""
    st.subheader("11) 전략설정 + 종목필터/검색")

    market = st.selectbox("전략 시장", options=["domestic", "overseas", "all"], index=0)
    keyword = st.text_input("전략 검색 키워드", value="")
    c1, c2, c3, c4 = st.columns(4)
    price_min = c1.number_input("최소가격", min_value=0.0, value=0.0, step=1.0)
    price_max = c2.number_input("최대가격", min_value=0.0, value=0.0, step=1.0)
    volume_min = c3.number_input("최소거래량", min_value=0.0, value=0.0, step=1.0)
    min_turnover = c4.number_input("최소거래대금", min_value=0.0, value=0.0, step=1.0)

    c5, c6, c7, c8 = st.columns(4)
    vol_min = c5.number_input("최소변동성(%)", min_value=0.0, value=0.0, step=0.1)
    vol_max = c6.number_input("최대변동성(%)", min_value=0.0, value=0.0, step=0.1)
    limit = int(c7.number_input("결과 제한", min_value=1, value=20, step=1))
    max_candidates = int(c8.number_input("탐색 후보수", min_value=1, max_value=100, value=30, step=1))

    strategy = {
        "market": market,
        "limit": limit,
        "min_turnover": min_turnover,
        "volatility_min": vol_min,
        "volatility_max": vol_max,
        "price_min": price_min,
        "price_max": price_max,
        "volume_min": volume_min,
        "volume_max": 0,
    }

    b1, b2, b3 = st.columns(3)
    if b1.button("전략 스키마 조회", use_container_width=True):
        responses["strategy_schema"] = request_json(base_url, "GET", "/api/v1/kis/strategy/schema")
        st.rerun()
    if b2.button("필터-API 매핑 조회", use_container_width=True):
        responses["strategy_mapping"] = request_json(base_url, "POST", "/api/v1/kis/strategy/mapping", body=strategy)
        st.rerun()
    if b3.button("검색+필터 실행", use_container_width=True):
        responses["strategy_search"] = request_json(
            base_url,
            "POST",
            "/api/v1/kis/strategy/search-filter",
            body={"keyword": keyword, "market": market, "strategy": strategy, "max_candidates": max_candidates},
        )
        st.rerun()

    schema_result = responses.get("strategy_schema")
    mapping_result = responses.get("strategy_mapping")
    search_result = responses.get("strategy_search")

    if mapping_result and mapping_result.get("ok"):
        mapping_payload = as_dict(mapping_result.get("payload"))
        st.caption(f"활성 필터 수: {as_dict(mapping_payload.get('mapping')).get('active_filter_count', 0)}")
        render_payload_expander("필터-API 매핑 원문 payload", mapping_payload)

    if search_result and search_result.get("ok"):
        payload = as_dict(search_result.get("payload"))
        st.success(
            f"후보 {payload.get('candidate_count', 0)}건 | 통과 {payload.get('count', 0)}건 | 수집실패 {payload.get('enriched_fail_count', 0)}건"
        )
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        if items:
            frame = pd.DataFrame(items)
            st.dataframe(format_dataframe_accounting(frame), use_container_width=True, hide_index=True)
        render_payload_expander("검색+필터 원문 payload", payload)

    render_call_status("전략 스키마", schema_result)
    render_call_status("필터-API 매핑", mapping_result)
    render_call_status("검색+필터", search_result)

    st.markdown("---")
    st.markdown("**주체별 매수 주도 종목 리스트**")
    st.caption("KIS 원천(주식현재가 투자자 + 현재가) 호출을 결합해 외국인/기관/개인 순매수 주도 종목을 계산합니다.")

    l1, l2, l3, l4 = st.columns(4)
    investor_subject = l1.selectbox("주체", options=["all", "foreign", "institution", "individual"], index=0)
    investor_market = l2.selectbox("시장 필터", options=["all", "KOSPI", "KOSDAQ", "KONEX"], index=0)
    investor_sort_by = l3.selectbox("정렬 기준", options=["net_buy_amount", "net_buy_qty", "buy_strength", "turnover"], index=0)
    investor_order = l4.selectbox("정렬 방향", options=["desc", "asc"], index=0)

    l5, l6, l7 = st.columns(3)
    investor_limit = int(l5.number_input("표시 개수", min_value=1, max_value=100, value=20, step=1))
    investor_candidates = int(l6.number_input("조회 후보수", min_value=1, max_value=120, value=50, step=1))
    investor_include_non_positive = l7.toggle("순매수<=0 포함", value=False)

    if st.button("매수 주도 리스트 조회", use_container_width=True):
        responses["strategy_investor_leaders"] = request_json(
            base_url,
            "GET",
            "/api/v1/kis/strategy/investor-buy-leaders",
            params={
                "subject": investor_subject,
                "market": investor_market,
                "sort_by": investor_sort_by,
                "order": investor_order,
                "limit": investor_limit,
                "max_candidates": investor_candidates,
                "include_non_positive": investor_include_non_positive,
            },
        )
        st.rerun()

    investor_result = responses.get("strategy_investor_leaders")
    if investor_result and investor_result.get("ok"):
        payload = as_dict(investor_result.get("payload"))
        st.success(
            "후보 {candidate}건 | 수집성공 {fetched}건 | 실패 {failed}건 | 결과 {count}건".format(
                candidate=payload.get("candidate_count", 0),
                fetched=payload.get("fetched_count", 0),
                failed=payload.get("failed_count", 0),
                count=payload.get("count", 0),
            )
        )
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        if items:
            frame = pd.DataFrame(items)
            wanted = [
                col
                for col in [
                    "symbol",
                    "name",
                    "market",
                    "subject_label",
                    "net_buy_qty",
                    "net_buy_amount",
                    "buy_strength",
                    "turnover",
                    "as_of",
                ]
                if col in frame.columns
            ]
            view = frame[wanted] if wanted else frame
            st.dataframe(format_dataframe_accounting(view), use_container_width=True, hide_index=True)
        constraints = payload.get("constraints") if isinstance(payload.get("constraints"), list) else []
        if constraints:
            st.dataframe(format_dataframe_accounting(pd.DataFrame(constraints)), use_container_width=True, hide_index=True)
        render_payload_expander("매수 주도 리스트 원문 payload", payload)

    render_call_status("주체별 매수주도", investor_result)
