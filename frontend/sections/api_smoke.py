"""Streamlit section for KIS API inventory and smoke-test execution."""

from __future__ import annotations

from typing import Any, Callable, Dict

import pandas as pd
import streamlit as st


def _to_df(rows: list[Dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    ordered = [col for col in ["id", "market", "domain", "status", "http_status", "failure_type", "reason", "elapsed_ms"] if col in frame.columns]
    return frame[ordered] if ordered else frame


def render_api_smoke_section(
    *,
    base_url: str,
    responses: Dict[str, Any],
    request_json: Callable[..., Dict[str, Any]],
    render_call_status: Callable[[str, Dict[str, Any] | None], None],
    render_payload_expander: Callable[[str, Any], None],
    as_dict: Callable[[Any], Dict[str, Any]],
) -> None:
    """Render inventory/matrix and smoke runner controls."""
    st.subheader("10) API 전수 스모크 테스트")
    st.caption("국내/해외 시세·계좌·주문·정정취소·차트·검색·필터 API를 자동 점검합니다.")

    c1, c2, c3 = st.columns(3)
    if c1.button("API 인벤토리 조회", use_container_width=True):
        responses["api_inventory"] = request_json(base_url, "GET", "/api/v1/kis/testing/inventory")
        st.rerun()

    include_schema = c2.toggle("주문 스키마 테스트 포함", value=True)
    if c3.button("스모크 테스트 실행", use_container_width=True):
        responses["api_smoke_run"] = request_json(
            base_url,
            "POST",
            "/api/v1/kis/testing/smoke/run",
            body={"base_url": base_url, "include_schema_only": include_schema, "timeout_seconds": 25},
        )
        st.rerun()

    if st.button("최근 스모크 결과 로드", use_container_width=True):
        responses["api_smoke_latest"] = request_json(base_url, "GET", "/api/v1/kis/testing/smoke/latest")
        st.rerun()

    inv_result = responses.get("api_inventory")
    if inv_result and inv_result.get("ok"):
        inv_payload = as_dict(inv_result.get("payload"))
        coverage = as_dict(inv_payload.get("coverage"))
        st.caption(f"인벤토리 총수: {inv_payload.get('count', 0)} | 기준문서: {inv_payload.get('reference_document', '-')}")
        matrix = as_dict(coverage.get("matrix"))
        if matrix:
            st.json(matrix)
        frame = _to_df(inv_payload.get("items", []))
        if not frame.empty:
            st.dataframe(frame, use_container_width=True, hide_index=True)
    render_call_status("API 인벤토리", inv_result)

    run_result = responses.get("api_smoke_run")
    latest_result = responses.get("api_smoke_latest")
    chosen = run_result if run_result else latest_result
    if chosen:
        payload = as_dict(chosen.get("payload"))
        summary = as_dict(payload.get("summary"))
        artifacts = as_dict(payload.get("artifacts"))
        if summary:
            st.success(
                f"총 {summary.get('total', 0)}건 | 성공 {summary.get('success', 0)} | 실패 {summary.get('fail', 0)} | 스킵 {summary.get('skip', 0)}"
            )
        st.caption(
            f"실패 유형: {summary.get('failure_type_counts', {})} | JSON={artifacts.get('json_path', '-')} | REPORT={artifacts.get('report_path', '-')}"
        )
        result_rows = payload.get("results") or as_dict(payload.get("payload", {})).get("results", [])
        frame = _to_df(result_rows if isinstance(result_rows, list) else [])
        if not frame.empty:
            st.dataframe(frame, use_container_width=True, hide_index=True)
        render_payload_expander("스모크 테스트 원문 payload", payload)

    render_call_status("스모크 실행", run_result)
    render_call_status("최근 스모크", latest_result)
