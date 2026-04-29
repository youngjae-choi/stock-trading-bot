"""Domestic stock filter console page."""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pandas as pd
import requests
import streamlit as st

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
TEST_OPTIONS = [
    "price_positive",
    "volume_positive",
    "turnover_positive",
    "change_rate_nonzero",
]
CONDITION_KEY_OPTIONS = [
    "price",
    "volume",
    "turnover",
    "change_rate",
    "market_cap",
    "avg_volume_20d",
    "volume_ratio_20d",
    "symbol",
    "name",
    "market",
]
CONDITION_OP_OPTIONS = ["eq", "ne", "gt", "gte", "lt", "lte", "contains", "in", "between"]
UNIVERSE_MODE_OPTIONS = ["market", "topn", "manual"]
UNIVERSE_MARKET_OPTIONS = ["ALL", "KOSPI", "KOSDAQ", "KONEX"]
DAILY_DERIVED_KEYS = {"avg_volume_20d", "volume_ratio_20d"}
UNIVERSE_FILTER_KEYS = {"market_cap", "market", "symbol", "name"}
TIMING_FILTER_KEYS = {"avg_volume_20d", "volume_ratio_20d", "volume", "turnover"}
CHANGE_FILTER_KEYS = {"price", "change_rate"}

CONDITION_KEY_LABELS = {
    "price": "현재가 (원)",
    "volume": "누적거래량 (주)",
    "turnover": "거래대금 (백만원)",
    "change_rate": "등락률 (%)",
    "market_cap": "시가총액 (억원)",
    "avg_volume_20d": "20일평균거래량 (주)",
    "volume_ratio_20d": "거래량비율 (20일대비, %)",
    "symbol": "종목코드",
    "name": "종목명",
    "market": "시장",
}

CONDITION_DESCRIPTIONS = {
    "price": "실시간 현재가 (예: 50000)",
    "volume": "당일 누적 거래량 (예: 100000)",
    "turnover": "당일 누적 거래대금 (예: 1000)",
    "change_rate": "전일 대비 등락률 (예: 3)",
    "market_cap": "시가총액 규모 (예: 10000 = 1조원)",
    "avg_volume_20d": "최근 20거래일 평균 거래량",
    "volume_ratio_20d": "평균 대비 현재 거래량 비율 (예: 200 = 2배)",
    "symbol": "6자리 종목코드 (예: 005930)",
    "name": "종목 명칭 (예: 삼성전자)",
    "market": "시장 구분 (KOSPI, KOSDAQ)",
}

TEST_LABELS = {
    "price_positive": "현재가 양수",
    "volume_positive": "거래량 양수",
    "turnover_positive": "거래대금 양수",
    "change_rate_nonzero": "등락률 0 아님",
}
OPERATOR_LABELS = {
    "eq": "같음",
    "ne": "다름",
    "gt": "초과",
    "gte": "이상",
    "lt": "미만",
    "lte": "이하",
    "contains": "포함",
    "in": "목록 포함",
    "between": "사이",
}


def _to_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _call_console_api(base_url: str, body: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{base_url.rstrip('/')}/api/v1/kis/strategy/domestic-filter/console"
    try:
        response = requests.post(url, json=body, timeout=60)
        payload = response.json()
        return {
            "ok": response.ok and not (isinstance(payload, dict) and payload.get("ok") is False),
            "status_code": response.status_code,
            "payload": payload,
        }
    except Exception as exc:
        return {
            "ok": False,
            "status_code": 0,
            "payload": {"ok": False, "error": str(exc)},
        }


def _parse_symbols(text: str) -> List[str]:
    return [token.strip().upper() for token in text.split(",") if token.strip()]


def _has_daily_derived_condition(conditions: List[Dict[str, Any]]) -> bool:
    for condition in conditions:
        if not isinstance(condition, dict):
            continue
        if not condition.get("enabled"):
            continue
        key = str(condition.get("key", "")).strip()
        if key in DAILY_DERIVED_KEYS:
            return True
    return False


def _split_conditions_by_key(conditions: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    universe_filters: List[Dict[str, Any]] = []
    timing_filters: List[Dict[str, Any]] = []
    change_filters: List[Dict[str, Any]] = []

    for condition in conditions:
        if not isinstance(condition, dict):
            continue
        key = str(condition.get("key", "")).strip()
        if key in UNIVERSE_FILTER_KEYS:
            universe_filters.append(condition)
        elif key in TIMING_FILTER_KEYS:
            timing_filters.append(condition)
        elif key in CHANGE_FILTER_KEYS:
            change_filters.append(condition)

    return {
        "universe_filters": universe_filters,
        "timing_filters": timing_filters,
        "change_filters": change_filters,
    }


def _collect_conditions() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    sections = [
        ("📂 1. 종목 필터 (대상/규모)", ["market_cap", "market", "symbol", "name"], [0, 1]),
        ("⏳ 2. 타이밍 필터 (거래량/수급)", ["avg_volume_20d", "volume_ratio_20d", "volume", "turnover"], [2, 3]),
        ("📈 3. 변화 필터 (가격/등락)", ["price", "change_rate"], [4, 5]),
    ]

    for title, recommended_keys, indices in sections:
        with st.expander(title, expanded=True):
            for idx in indices:
                c1, c2, c3, c4, c5 = st.columns([0.8, 1.8, 1.2, 1.5, 1.5])
                enabled = c1.checkbox("사용", key=f"condition_enabled_{idx}")
                
                # Filter key options to prioritize recommended ones, but allow all
                default_key = recommended_keys[0] if idx % 2 == 0 and len(recommended_keys) > 0 else recommended_keys[-1]
                if f"condition_key_{idx}" not in st.session_state:
                     st.session_state[f"condition_key_{idx}"] = default_key

                key = c2.selectbox(
                    "지표",
                    options=CONDITION_KEY_OPTIONS,
                    key=f"condition_key_{idx}",
                    format_func=lambda item: f"{CONDITION_KEY_LABELS.get(item, item)}",
                    help=CONDITION_DESCRIPTIONS.get(st.session_state.get(f"condition_key_{idx}", ""), "")
                )
                op = c3.selectbox("조건", options=CONDITION_OP_OPTIONS, key=f"condition_op_{idx}", 
                                format_func=lambda x: OPERATOR_LABELS.get(x, x))
                value = c4.text_input("값", key=f"condition_value_{idx}", placeholder="예: 1000")
                value_to = c5.text_input("값2 (between)", key=f"condition_value_to_{idx}", placeholder="범위 끝값")
                
                rows.append({
                    "key": key,
                    "enabled": enabled,
                    "op": op,
                    "value": value,
                    "value_to": value_to,
                })
    return rows


def _render_condition_guide() -> None:
    with st.expander("❓ 필터 지표 상세 안내", expanded=False):
        st.markdown(
            "- **현재가**: 실시간 현재 가격 (원 단위)\n"
            "- **누적거래량**: 당일 총 거래 주수\n"
            "- **거래대금**: 당일 총 거래 금액 (백만원 단위)\n"
            "- **등락률(%)**: 전일 종가 대비 현재가 변동 비율\n"
            "- **시가총액**: 기업의 총 시장 가치 (억원 단위, 1조원 = 10000 입력)\n"
            "- **20일평균거래량**: 최근 20거래일의 평균 거래량\n"
            "- **거래량비율(20일대비, %)**: `현재거래량 / 20일평균거래량 * 100` (200% = 평소의 2배)"
        )


def _derive_display_columns(payload: Dict[str, Any], last_request: Dict[str, Any] | None) -> List[str]:
    display_columns = payload.get("display_columns") if isinstance(payload.get("display_columns"), list) else []
    if display_columns:
        return [str(col) for col in display_columns if str(col).strip()]

    if not isinstance(last_request, dict):
        return []

    derived: List[str] = []
    conditions = last_request.get("conditions") if isinstance(last_request.get("conditions"), list) else []
    for condition in conditions:
        if not isinstance(condition, dict):
            continue
        if not condition.get("enabled"):
            continue
        key = str(condition.get("key", "")).strip()
        if key and key not in derived:
            derived.append(key)
    return derived


def _format_condition_korean(condition: Dict[str, Any]) -> str:
    key = str(condition.get("key", "")).strip()
    key_label = CONDITION_KEY_LABELS.get(key, key)
    op = str(condition.get("op", "")).strip()
    value = str(condition.get("value", "")).strip()
    value_to = str(condition.get("value_to", "")).strip()
    op_label = OPERATOR_LABELS.get(op, op)

    if op == "between":
        return f"[{key_label}]이 {value}에서 {value_to} 사이"
    if op == "in":
        return f"[{key_label}]이 ({value}) 목록에 포함"
    if op == "gt": return f"[{key_label}]이 {value} 초과"
    if op == "gte": return f"[{key_label}]이 {value} 이상"
    if op == "lt": return f"[{key_label}]이 {value} 미만"
    if op == "lte": return f"[{key_label}]이 {value} 이하"
    if op == "eq": return f"[{key_label}]이 {value}와 같음"
    if op == "ne": return f"[{key_label}]이 {value}와 다름"
    if op == "contains": return f"[{key_label}]에 '{value}' 포함"
    
    return f"[{key_label}] {op_label} {value}"


def _get_natural_summary(request: Dict[str, Any]) -> str:
    universe = request.get("universe", {})
    mode = universe.get("mode", "market")
    market = universe.get("market", "ALL")
    top_n = universe.get("top_n", 0)
    
    mode_text = {
        "market": f"**{market}** 시장 전체",
        "topn": f"**{market}** 시장 거래대금 상위 **{top_n}**개 종목",
        "manual": "직접 입력한 종목들"
    }.get(mode, mode)
    
    conditions = request.get("conditions", [])
    active_conds = [c for c in conditions if c.get("enabled")]
    
    if not active_conds:
        cond_text = "별도 조건 없이"
    else:
        cond_text = " + ".join([_format_condition_korean(c) for c in active_conds])
    
    summary = f"🔍 {mode_text} 중 {cond_text}인 종목을 탐색합니다. (최대 {request.get('limit')}개 출력)"
    return summary


def _render_execution_summary(payload: Dict[str, Any]) -> None:
    universe_count = payload.get("universe_count", payload.get("candidate_count", 0))
    enriched_success = payload.get("enriched_success_count", 0)
    filtered_pass = payload.get("filter_pass_count", payload.get("count", 0))

    def _safe_number(value: Any) -> Any:
        try:
            return int(value)
        except (TypeError, ValueError):
            return value

    st.markdown("**📊 실행 결과 요약**")
    c1, c2, c3 = st.columns(3)
    c1.metric("대상 유니버스", _safe_number(universe_count))
    c2.metric("데이터 수집 성공", _safe_number(enriched_success))
    c3.metric("최종 필터 통과", _safe_number(filtered_pass))


def _render_result(result: Dict[str, Any], last_request: Dict[str, Any] | None = None) -> None:
    payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
    
    if last_request:
        st.info(_get_natural_summary(last_request))

    if result.get("ok"):
        st.success(
            "✅ 조회 성공 | 후보 {candidate}건 중 {success}건 성공, {count}건 필터 통과".format(
                candidate=payload.get("candidate_count", 0),
                success=payload.get("enriched_success_count", 0),
                count=payload.get("count", 0),
            )
        )
    else:
        st.error(f"❌ 조회 실패 (HTTP {result.get('status_code', 0)})")
        error_code = payload.get("error_code") or payload.get("rt_cd")
        if error_code == "EGW00201" or "EGW00201" in str(payload):
            st.warning("⚠️ **[API 제한]** 초당 거래건수 제한이 발생했습니다. 잠시 후 시도하세요.")
        with st.expander("상세 에러 확인 (JSON)", expanded=False):
            st.code(_to_json(payload), language="json")
        return

    _render_execution_summary(payload)

    applied_candidates = payload.get("applied_max_candidates")
    requested_candidates = payload.get("max_candidates")
    if applied_candidates and requested_candidates and applied_candidates < requested_candidates:
        st.warning(f"⚠️ 시스템 보호를 위해 탐색 후보 수가 {requested_candidates} → {applied_candidates}로 자동 제한되었습니다.")

    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    display_columns = _derive_display_columns(payload, last_request)

    if not items:
        st.info("조회 결과가 없습니다.")
    else:
        frame = pd.DataFrame(items)
        candidate_columns = ["symbol", "name", *display_columns]
        seen: set[str] = set()
        picked_columns: list[str] = []
        for col in candidate_columns:
            if col not in frame.columns or col in seen:
                continue
            seen.add(col)
            picked_columns.append(col)
        
        view = frame[picked_columns] if picked_columns else frame
        st.dataframe(view, use_container_width=True, hide_index=True)
        
        csv_data = view.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📥 결과 CSV 다운로드", data=csv_data, file_name="filter_result.csv", mime="text/csv", use_container_width=True)

    with st.expander("📦 Raw Response JSON", expanded=False):
        st.code(_to_json(payload), language="json")


def _reset_form() -> None:
    for key in list(st.session_state.keys()):
        if key.startswith("condition_") or key.startswith("universe_"):
            del st.session_state[key]
    st.session_state["df_result"] = None
    st.session_state["df_last_request"] = None


def apply_preset_strong_supply() -> None:
    """Apply preset: KOSPI + Market Cap >= 1T + Volume Ratio >= 200%"""
    _reset_form()
    st.session_state["universe_mode"] = "market"
    st.session_state["universe_market"] = "KOSPI"
    
    # Condition 0: Market Cap >= 10000 (1 trillion KRW)
    st.session_state["condition_enabled_0"] = True
    st.session_state["condition_key_0"] = "market_cap"
    st.session_state["condition_op_0"] = "gte"
    st.session_state["condition_value_0"] = "10000"
    
    # Condition 2: Volume Ratio >= 200%
    st.session_state["condition_enabled_2"] = True
    st.session_state["condition_key_2"] = "volume_ratio_20d"
    st.session_state["condition_op_2"] = "gte"
    st.session_state["condition_value_2"] = "200"
    
    st.toast("강력 수급 프리셋이 적용되었습니다!")


def main() -> None:
    st.set_page_config(page_title="Domestic Stock Filter", layout="wide")
    st.title("🚀 국내주식 전략 필터 콘솔")
    
    if "df_result" not in st.session_state:
        st.session_state["df_result"] = None
    if "df_last_request" not in st.session_state:
        st.session_state["df_last_request"] = None

    with st.sidebar:
        st.header("⚙️ 설정")
        base_url = st.text_input("백엔드 URL", value=DEFAULT_BASE_URL).strip()
        st.divider()
        st.subheader("💡 빠른 프리셋")
        if st.button("🔥 강력 수급 종목\n(코스피/1조↑/거래량200%↑)", use_container_width=True):
            apply_preset_strong_supply()
            st.rerun()
        
        st.divider()
        if st.button("🔄 초기화", use_container_width=True):
            _reset_form()
            st.rerun()

    # 1. 대상 유니버스 설정
    st.subheader("1. 탐색 대상 설정 (Universe)")
    u1, u2, u3 = st.columns(3)
    universe_mode = u1.selectbox(
        "유니버스 모드",
        options=UNIVERSE_MODE_OPTIONS,
        key="universe_mode",
        format_func=lambda x: {"market": "시장 전체", "topn": "거래대금 상위(TopN)", "manual": "직접 입력"}.get(x, x),
    )
    universe_market = u2.selectbox("대상 시장", options=UNIVERSE_MARKET_OPTIONS, key="universe_market")
    universe_top_n = int(u3.number_input("TopN 수량", min_value=1, max_value=200, value=40, step=1, key="universe_top_n"))
    
    if universe_mode == "manual":
        manual_symbols_text = st.text_area("종목코드 입력 (쉼표 또는 줄바꿈 구분)", value="", height=80, key="manual_symbols_input")
    else:
        manual_symbols_text = ""

    # 2. 필터 조건 설정
    st.subheader("2. 전략 필터 설정 (Conditions)")
    conditions = _collect_conditions()
    _render_condition_guide()

    # 3. 추가 옵션
    st.subheader("3. 상세 옵션")
    c1, c2, c3 = st.columns(3)
    limit = int(c1.number_input("결과 제한 (Limit)", min_value=1, max_value=200, value=30, step=1))
    max_candidates = int(c2.number_input("탐색 후보 수 (Max)", min_value=1, max_value=200, value=40, step=1))
    include_failed_rows = c3.checkbox("필터 미통과 행 포함 (디버그용)", value=False)

    selected_tests = st.multiselect(
        "기본 유효성 테스트",
        options=TEST_OPTIONS,
        default=["price_positive", "volume_positive"],
        format_func=lambda item: TEST_LABELS.get(item, item),
    )

    # 타임아웃 경고
    effective_candidates = universe_top_n if universe_mode == "topn" else max_candidates
    if _has_daily_derived_condition(conditions) and effective_candidates > 30:
        st.warning("⚠️ **[속도 경고]** 20일 평균/비율 조건 사용 시 탐색 후보가 많으면 60초 타임아웃이 발생할 수 있습니다. (후보수를 30 이하로 권장)")

    # 실행 버튼
    if st.button("🔍 전략 조건으로 종목 검색", type="primary", use_container_width=True):
        manual_symbols = _parse_symbols(manual_symbols_text.replace("\n", ","))
        
        request_max_candidates = max_candidates
        request_symbols = []
        request_keyword = ""

        if universe_mode == "manual" and manual_symbols:
            request_symbols = manual_symbols
        if universe_mode == "topn":
            request_max_candidates = universe_top_n

        split_conditions = _split_conditions_by_key(conditions)

        body = {
            "keyword": request_keyword,
            "symbols": request_symbols,
            "limit": limit,
            "max_candidates": request_max_candidates,
            "selected_tests": selected_tests,
            "conditions": conditions,
            "universe_filters": split_conditions["universe_filters"],
            "timing_filters": split_conditions["timing_filters"],
            "change_filters": split_conditions["change_filters"],
            "include_raw": True,
            "include_failed_rows": include_failed_rows,
            "universe": {
                "mode": universe_mode,
                "market": universe_market,
                "top_n": universe_top_n,
                "manual_symbols": manual_symbols,
            },
            "market": universe_market,
            "top_n": universe_top_n
        }

        st.session_state["df_last_request"] = body
        st.session_state["df_result"] = _call_console_api(base_url, body)

    # 결과 표시
    result = st.session_state.get("df_result")
    if result:
        st.divider()
        _render_result(result, last_request=st.session_state.get("df_last_request"))


if __name__ == "__main__":
    main()

