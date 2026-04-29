"""Overseas stock testing UI section for Streamlit."""

from __future__ import annotations

from typing import Any, Callable, Dict

import pandas as pd
import streamlit as st


def _to_frame(payload: Dict[str, Any]) -> pd.DataFrame:
    body = payload.get("payload") if isinstance(payload, dict) else {}
    if not isinstance(body, dict):
        return pd.DataFrame()
    for key in ("output2", "output1", "output"):
        rows = body.get(key)
        if isinstance(rows, list) and rows:
            return pd.DataFrame(rows)
    return pd.DataFrame()


def render_overseas_test_section(
    *,
    base_url: str,
    responses: Dict[str, Any],
    request_json: Callable[..., Dict[str, Any]],
    render_call_status: Callable[[str, Dict[str, Any] | None], None],
    render_payload_expander: Callable[[str, Any], None],
    as_dict: Callable[[Any], Dict[str, Any]],
    format_dataframe_accounting: Callable[[pd.DataFrame], pd.DataFrame],
) -> None:
    """Render overseas stock quote/chart/order/revise-cancel testers."""
    st.subheader("8) 해외주식 테스트")
    st.caption("해외 거래소/티커 기준으로 현재가·차트·주문·정정취소 API를 검증합니다.")

    exchange = st.selectbox(
        "거래소",
        options=["NASD", "NYSE", "AMEX", "SEHK", "TKSE", "SHAA", "SZAA", "HASE", "VNSE"],
        index=0,
        key="ov_exchange",
    )
    ticker = st.text_input("해외 티커", value="AAPL", key="ov_ticker").strip().upper()

    quote_col, chart_col = st.columns(2)
    with quote_col:
        if st.button("해외 현재가 조회", use_container_width=True):
            responses["ov_price"] = request_json(base_url, "GET", f"/api/v1/kis/overseas/price/{exchange}/{ticker}")
            st.rerun()

    with chart_col:
        ov_period = st.selectbox("해외 차트 주기", options=["D", "W", "M"], index=0, key="ov_period")
        ov_adjusted = st.selectbox("해외 수정주가 반영", options=["1", "0"], index=0, key="ov_adjusted")
        if st.button("해외 차트 조회", use_container_width=True):
            responses["ov_chart"] = request_json(
                base_url,
                "GET",
                f"/api/v1/kis/overseas/chart/daily/{exchange}/{ticker}",
                params={"period_code": ov_period, "adjusted_price": ov_adjusted},
            )
            st.rerun()

    price_result = responses.get("ov_price")
    chart_result = responses.get("ov_chart")

    if price_result and price_result.get("ok"):
        frame = _to_frame(as_dict(price_result.get("payload")))
        if not frame.empty:
            st.markdown("**해외 현재가 응답 테이블**")
            st.dataframe(format_dataframe_accounting(frame), use_container_width=True, hide_index=True)
        render_payload_expander("해외 현재가 원문 payload", as_dict(price_result).get("payload"))

    if chart_result and chart_result.get("ok"):
        frame = _to_frame(as_dict(chart_result.get("payload")))
        if not frame.empty:
            st.markdown("**해외 차트 응답 테이블**")
            st.dataframe(format_dataframe_accounting(frame), use_container_width=True, hide_index=True)
        render_payload_expander("해외 차트 원문 payload", as_dict(chart_result).get("payload"))

    render_call_status("해외 현재가", price_result)
    render_call_status("해외 차트", chart_result)

    st.markdown("**해외 주문/정정취소 테스트**")
    order_col, rvse_col = st.columns(2)

    with order_col:
        ov_side = st.selectbox("해외 주문 방향", options=["buy", "sell"], key="ov_order_side")
        ov_qty = int(st.number_input("해외 주문 수량", min_value=1, value=1, step=1, key="ov_order_qty"))
        ov_price = st.text_input("해외 주문 가격", value="150", key="ov_order_price").strip()
        if st.button("해외 주문 실행", use_container_width=True):
            responses["ov_order_cash"] = request_json(
                base_url,
                "POST",
                "/api/v1/kis/overseas/order/cash",
                body={
                    "side": ov_side,
                    "exchange": exchange,
                    "symbol": ticker,
                    "qty": ov_qty,
                    "price": ov_price,
                    "ord_dvsn": "00",
                },
            )
            st.rerun()

    with rvse_col:
        ov_mode = st.selectbox("해외 정정취소", options=["cancel", "modify"], key="ov_rvse_mode")
        ov_orgn = st.text_input("해외 원주문번호", value="", key="ov_orgn_odno")
        ov_rvse_qty = int(st.number_input("해외 처리수량", min_value=0, value=0, step=1, key="ov_rvse_qty"))
        ov_rvse_price = st.text_input("해외 정정가격", value="0", key="ov_rvse_price")
        if st.button("해외 정정/취소 실행", use_container_width=True):
            responses["ov_order_rvsecncl"] = request_json(
                base_url,
                "POST",
                "/api/v1/kis/overseas/order/rvsecncl",
                body={
                    "mode": ov_mode,
                    "exchange": exchange,
                    "symbol": ticker,
                    "orgn_odno": ov_orgn,
                    "qty": ov_rvse_qty,
                    "order_price": ov_rvse_price,
                },
            )
            st.rerun()

    render_call_status("해외 주문", responses.get("ov_order_cash"))
    render_call_status("해외 정정/취소", responses.get("ov_order_rvsecncl"))
    if responses.get("ov_order_cash"):
        render_payload_expander("해외 주문 원문 payload", as_dict(responses["ov_order_cash"]).get("payload"))
    if responses.get("ov_order_rvsecncl"):
        render_payload_expander("해외 정정/취소 원문 payload", as_dict(responses["ov_order_rvsecncl"]).get("payload"))
