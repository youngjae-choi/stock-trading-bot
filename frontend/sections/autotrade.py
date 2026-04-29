"""Streamlit section for auto-trading workflow tests."""

from __future__ import annotations

from typing import Any, Callable, Dict

import streamlit as st


def render_autotrade_section(
    *,
    base_url: str,
    responses: Dict[str, Any],
    request_json: Callable[..., Dict[str, Any]],
    render_call_status: Callable[[str, Dict[str, Any] | None], None],
    render_payload_expander: Callable[[str, Any], None],
    as_dict: Callable[[Any], Dict[str, Any]],
) -> None:
    """Render dry-run/live guarded auto-trading controls."""
    st.subheader("12) 자동거래 실행 플로우 테스트")

    if st.button("자동거래 가드 정책 조회", use_container_width=True):
        responses["autotrade_guard"] = request_json(base_url, "GET", "/api/v1/kis/autotrade/guard")
        st.rerun()

    c1, c2, c3 = st.columns(3)
    mode = c1.selectbox("실행 모드", options=["dry_run", "live"], index=0)
    market = c2.selectbox("시장", options=["domestic", "overseas"], index=0)
    exchange = c3.selectbox("거래소", options=["NASD", "NYSE", "AMEX", "SEHK", "TKSE"], index=0)

    c4, c5, c6, c7 = st.columns(4)
    symbol = c4.text_input("종목코드", value="005930" if market == "domestic" else "AAPL").strip().upper()
    side = c5.selectbox("주문 방향", options=["buy", "sell"], index=0)
    qty = int(c6.number_input("수량", min_value=1, value=1, step=1))
    price = c7.text_input("가격", value="70000" if market == "domestic" else "150").strip()

    confirm_text = st.text_input("live 확인문구", value="") if mode == "live" else ""

    b1, b2 = st.columns(2)
    if b1.button("자동거래 실행", use_container_width=True):
        responses["autotrade_execute"] = request_json(
            base_url,
            "POST",
            "/api/v1/kis/autotrade/execute",
            body={
                "mode": mode,
                "market": market,
                "exchange": exchange,
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "price": price,
                "confirm_text": confirm_text,
            },
        )
        st.rerun()
    if b2.button("자동거래 시나리오 테스트", use_container_width=True):
        responses["autotrade_scenario"] = request_json(base_url, "POST", "/api/v1/kis/autotrade/scenario-test", body={})
        st.rerun()

    guard_result = responses.get("autotrade_guard")
    execute_result = responses.get("autotrade_execute")
    scenario_result = responses.get("autotrade_scenario")

    if guard_result and guard_result.get("ok"):
        st.info(f"live 확인문구: {as_dict(guard_result.get('payload')).get('live_confirm_text', '-')}")

    if execute_result:
        payload = as_dict(execute_result.get("payload"))
        if execute_result.get("ok"):
            st.success(
                f"workflow_id={payload.get('workflow_id', '-')} | mode={payload.get('mode', '-')} | 상태={as_dict(payload.get('order')).get('status', '-') }"
            )
        else:
            st.warning(f"자동거래 실행 실패: {as_dict(payload.get('error')).get('code', 'unknown')}")
        render_payload_expander("자동거래 실행 원문 payload", payload)

    if scenario_result and scenario_result.get("ok"):
        payload = as_dict(scenario_result.get("payload"))
        st.caption(
            f"시나리오 {payload.get('count', 0)}건 | 통과 {payload.get('passed', 0)} | 실패 {payload.get('failed', 0)}"
        )
        render_payload_expander("자동거래 시나리오 원문 payload", payload)

    render_call_status("자동거래 가드", guard_result)
    render_call_status("자동거래 실행", execute_result)
    render_call_status("자동거래 시나리오", scenario_result)
