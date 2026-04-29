"""KIS API capability verification page (REST-first, no HTS dependency)."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pandas as pd
import requests
import streamlit as st

from frontend.sections.api_smoke import render_api_smoke_section
from frontend.sections.autotrade import render_autotrade_section
from frontend.sections.overseas import render_overseas_test_section
from frontend.sections.strategy import render_strategy_section
from frontend.sections.trading_hub import render_trading_hub_section

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_SYMBOL = "005930"
KST = timezone(timedelta(hours=9))
REAL_ORDER_CONFIRM_TEXT = "실주문동의"


def now_kst_text() -> str:
    """Return current KST time text."""
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")


def to_json_text(payload: Any) -> str:
    """Serialize payload as readable JSON."""
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def as_dict(value: Any) -> Dict[str, Any]:
    """Return dict value safely."""
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> List[Any]:
    """Return list value safely."""
    return value if isinstance(value, list) else []


def init_state() -> None:
    """Initialize session state containers."""
    defaults = {
        "logs": [],
        "responses": {},
        "last_price_alarm_sent": "",
        "selected_symbol": DEFAULT_SYMBOL,
        "stock_search_items": [],
        "show_account_raw": False,
        "show_stock_raw": False,
        "show_news_raw": False,
        "show_chart_daily_raw": False,
        "show_chart_intraday_raw": False,
        "show_filter_test_raw": {},
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def add_log(level: str, message: str) -> None:
    """Store log rows in memory."""
    st.session_state.logs.insert(0, {"time": now_kst_text(), "level": level, "message": message})
    st.session_state.logs = st.session_state.logs[:200]


def request_json(
    base_url: str,
    method: str,
    endpoint: str,
    body: Dict[str, Any] | None = None,
    params: Dict[str, Any] | None = None,
    log: bool = True,
) -> Dict[str, Any]:
    """Call backend API and normalize response."""
    url = f"{base_url.rstrip('/')}{endpoint}"
    started = time.time()
    if log:
        add_log("INFO", f"START {method} {endpoint}")
    try:
        response = requests.request(method=method, url=url, params=params, json=body, timeout=25)
        elapsed_ms = int((time.time() - started) * 1000)
        try:
            payload: Any = response.json()
        except ValueError:
            payload = {"raw_text": response.text}

        ok = response.ok and not (isinstance(payload, dict) and payload.get("ok") is False)
        result = {
            "ok": ok,
            "status_code": response.status_code,
            "elapsed_ms": elapsed_ms,
            "endpoint": endpoint,
            "method": method,
            "params": params or {},
            "payload": payload,
        }
        if log:
            if ok:
                add_log("SUCCESS", f"SUCCESS {method} {endpoint} {response.status_code} {elapsed_ms}ms")
            else:
                add_log("FAIL", f"FAIL {method} {endpoint} {response.status_code} {elapsed_ms}ms")
        return result
    except requests.RequestException as exc:
        elapsed_ms = int((time.time() - started) * 1000)
        if log:
            add_log("FAIL", f"FAIL {method} {endpoint} Network {exc}")
        return {
            "ok": False,
            "status_code": 0,
            "elapsed_ms": elapsed_ms,
            "endpoint": endpoint,
            "method": method,
            "params": params or {},
            "payload": {"error": str(exc)},
        }


def parse_current_price(price_payload: Dict[str, Any]) -> float | None:
    """Extract numeric current price from price payload."""
    output = as_dict(price_payload.get("output"))
    value = output.get("stck_prpr")
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def is_number_like(text: str) -> bool:
    """Return whether text is numeric."""
    text = text.strip()
    if not text:
        return False
    try:
        float(text.replace(",", ""))
        return True
    except ValueError:
        return False


def format_accounting(value: Any) -> Any:
    """Format numeric value with accounting thousand separators."""
    if isinstance(value, (int, float)):
        return f"{value:,.2f}" if isinstance(value, float) and not value.is_integer() else f"{int(value):,}"
    if isinstance(value, str):
        stripped = value.strip().replace(",", "")
        if is_number_like(stripped):
            number = float(stripped)
            if number.is_integer():
                return f"{int(number):,}"
            return f"{number:,.4f}".rstrip("0").rstrip(".")
    return value


def format_dataframe_accounting(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply accounting format to dataframe cells."""
    converted = frame.copy()
    for column in converted.columns:
        converted[column] = converted[column].map(format_accounting)
    return converted


def render_call_status(title: str, result: Dict[str, Any] | None) -> None:
    """Render compact status row for API call."""
    if not result:
        st.caption(f"{title}: 호출 이력 없음")
        return
    state = "OK" if result["ok"] else "FAIL"
    st.caption(
        f"{title}: {state} | {result['method']} {result['endpoint']} | HTTP {result['status_code']} | {result['elapsed_ms']}ms"
    )


def render_field_table(title: str, rows: List[Dict[str, Any]]) -> None:
    """Render flattened field table."""
    st.markdown(f"**{title}**")
    if not rows:
        st.info("데이터 없음")
        return
    frame = pd.DataFrame(rows)
    wanted = [col for col in ["field", "description_ko", "mapping_status", "sample_value"] if col in frame.columns]
    view = frame[wanted] if wanted else frame
    st.dataframe(format_dataframe_accounting(view), use_container_width=True, hide_index=True)


def flatten_filter_catalog(items: List[Dict[str, Any]]) -> pd.DataFrame:
    """Flatten filter catalog rows for a compact table view."""
    rows: List[Dict[str, Any]] = []
    for item in items:
        scope = item.get("market_scope", "")
        status = item.get("status", "")
        api = item.get("api")
        purpose = item.get("purpose")
        note = item.get("note", "")
        for flt in as_list(item.get("filters")):
            default_value = flt.get("default", "")
            option_values = [str(opt) for opt in as_list(flt.get("options"))]
            rows.append(
                {
                    "시장": "국내주식" if scope == "domestic" else ("해외주식" if scope == "overseas" else ""),
                    "상태": "구현" if status == "implemented" else ("참고" if status == "reference" else status),
                    "API": api,
                    "용도": purpose,
                    "필터명": flt.get("name"),
                    "필수": "Y" if flt.get("required") else "N",
                    "타입": flt.get("type"),
                    "설명": flt.get("description_ko"),
                    "기본값": "" if default_value in (None, "") else str(default_value),
                    "옵션": ", ".join(option_values),
                    "호출방식": item.get("method", "GET"),
                    "테스트가능": "Y" if item.get("testable") else "N",
                    "비고": note,
                }
            )
    return pd.DataFrame(rows)


def flatten_scope_catalog(items: List[Dict[str, Any]]) -> pd.DataFrame:
    """Render domestic/overseas account-stock-trade scope table."""
    rows: List[Dict[str, Any]] = []
    domain_name = {"account": "계좌", "stock": "종목", "trade": "거래"}
    status_name = {"implemented": "구현", "reference": "참고", "not_supported": "제외"}
    for item in items:
        rows.append(
            {
                "시장": "국내주식" if item.get("market_scope") == "domestic" else "해외주식",
                "분류": domain_name.get(item.get("domain"), item.get("domain")),
                "기능": item.get("feature"),
                "상태": status_name.get(item.get("status"), item.get("status")),
                "API": item.get("api"),
                "비고": item.get("note", ""),
            }
        )
    return pd.DataFrame(rows)


def render_payload_expander(title: str, payload: Any) -> None:
    """Keep raw payload separated behind expandable section."""
    with st.expander(title, expanded=False):
        st.code(to_json_text(payload), language="json")


def render_filter_testers(base_url: str, items: List[Dict[str, Any]], default_symbol: str) -> None:
    """Render interactive tester blocks for each stock filter API."""
    st.markdown("**필터별 직접 호출 테스트**")
    if not items:
        st.info("테스트할 필터 카탈로그가 없습니다.")
        return

    for idx, item in enumerate(items):
        scope = "국내주식" if item.get("market_scope") == "domestic" else "해외주식"
        status = item.get("status")
        status_text = "구현" if status == "implemented" else ("참고" if status == "reference" else status)
        api = str(item.get("api", ""))
        purpose = item.get("purpose", "")
        expander_title = f"[{scope}] {purpose} | {status_text}"
        with st.expander(expander_title, expanded=False):
            st.caption(f"API: {api}")
            filters = as_list(item.get("filters"))
            values: Dict[str, Any] = {}
            for flt in filters:
                name = str(flt.get("name", ""))
                dtype = str(flt.get("type", "string"))
                options = as_list(flt.get("options"))
                default_value: Any = flt.get("default", default_symbol if name == "symbol" else "")
                key_prefix = f"flt_{idx}_{name}"
                if dtype == "enum" and options:
                    picked = st.selectbox(f"{name} ({dtype})", options=options, index=options.index(default_value) if default_value in options else 0, key=key_prefix)
                    values[name] = picked
                elif dtype == "int":
                    number_default = int(default_value) if str(default_value).strip().isdigit() else 0
                    values[name] = int(st.number_input(f"{name} ({dtype})", value=number_default, step=1, key=key_prefix))
                else:
                    values[name] = st.text_input(f"{name} ({dtype})", value=str(default_value), key=key_prefix).strip()

            response_key = f"filter_test_{idx}"
            can_test = bool(item.get("testable")) and api.startswith("/")
            if st.button(f"테스트 호출 #{idx + 1}", key=f"run_filter_test_{idx}", use_container_width=True, disabled=not can_test):
                endpoint = api
                params: Dict[str, Any] = {}
                for flt in filters:
                    name = str(flt.get("name", ""))
                    value = values.get(name)
                    if value in ("", None):
                        if flt.get("required"):
                            params[name] = value
                        continue
                    if f"{{{name}}}" in endpoint:
                        endpoint = endpoint.replace(f"{{{name}}}", str(value))
                    else:
                        params[name] = value
                st.session_state.responses[response_key] = request_json(base_url, item.get("method", "GET"), endpoint, params=params)
                st.rerun()

            if not can_test:
                st.info("현재 서버 미구현 항목으로 테스트 호출이 비활성화되어 있습니다.")
            test_result = st.session_state.responses.get(response_key)
            render_call_status(f"필터 테스트 #{idx + 1}", test_result)
            if test_result:
                render_payload_expander(f"필터 테스트 #{idx + 1} 원본 payload", test_result.get("payload"))


def extract_daily_chart_df(payload: Dict[str, Any]) -> pd.DataFrame:
    """Extract daily chart dataframe from KIS payload."""
    rows = as_list(payload.get("output"))
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    cols = [c for c in ["stck_bsop_date", "stck_clpr", "stck_oprc", "stck_hgpr", "stck_lwpr", "acml_vol"] if c in frame.columns]
    return frame[cols] if cols else frame


def extract_intraday_chart_df(payload: Dict[str, Any]) -> pd.DataFrame:
    """Extract intraday chart dataframe from KIS payload."""
    rows = as_list(payload.get("output2"))
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    cols = [c for c in ["stck_cntg_hour", "stck_prpr", "stck_oprc", "stck_hgpr", "stck_lwpr", "cntg_vol"] if c in frame.columns]
    return frame[cols] if cols else frame


def main() -> None:
    """Render API capability verification page."""
    st.set_page_config(page_title="KIS API 기능 검증", layout="wide")
    init_state()

    with st.sidebar:
        page = st.radio(
            "페이지 선택",
            options=["KIS API 검증", "단타봇 허브"],
            index=0,
            key="page_select"
        )
        st.divider()
        st.header("연결 설정")
        base_url = st.text_input("백엔드 URL", value=DEFAULT_BASE_URL).strip()
        manual_symbol = st.text_input("종목코드 직접 입력", value=st.session_state.selected_symbol, max_chars=12).strip().upper()
        if manual_symbol:
            st.session_state.selected_symbol = manual_symbol
        st.caption(f"기준시: {now_kst_text()}")

    symbol = st.session_state.selected_symbol

    if page == "단타봇 허브":
        render_trading_hub_section(
            base_url=base_url,
            responses=st.session_state.responses,
            request_json=request_json,
            render_call_status=render_call_status,
            render_payload_expander=render_payload_expander,
            as_dict=as_dict,
            as_list=as_list,
            format_dataframe_accounting=format_dataframe_accounting,
        )
    else:
        st.title("KIS API 기능 검증 페이지")
        st.warning("목적: KIS API 제공 데이터/주문 가능 범위를 실제 호출로 검증")
        st.info("서버 구조: 한국투자증권 REST API 직접 호출. 로컬 HTS 설치/제어를 경유하지 않음.")

        if "capabilities" not in st.session_state.responses:
            st.session_state.responses["capabilities"] = request_json(base_url, "GET", "/api/v1/kis/meta/capabilities", log=False)
        if "trading_scope" not in st.session_state.responses:
            st.session_state.responses["trading_scope"] = request_json(base_url, "GET", "/api/v1/kis/meta/trading-scope", log=False)
        cap_result = st.session_state.responses.get("capabilities")
        cap_payload = as_dict(as_dict(cap_result).get("payload"))
        scope_result = st.session_state.responses.get("trading_scope")
        scope_payload = as_dict(as_dict(scope_result).get("payload"))
        connection_mode = cap_payload.get("connection_mode", "unknown")

        st.subheader("0) 구조/기능 매트릭스")
        cap_col, scope_col, health_col = st.columns(3)
        if cap_col.button("KIS 기능 매트릭스 새로고침", use_container_width=True):
            st.session_state.responses["capabilities"] = request_json(base_url, "GET", "/api/v1/kis/meta/capabilities")
            st.rerun()
        if scope_col.button("국내/해외 범위 새로고침", use_container_width=True):
            st.session_state.responses["trading_scope"] = request_json(base_url, "GET", "/api/v1/kis/meta/trading-scope")
            st.rerun()
        if health_col.button("헬스체크", use_container_width=True):
            st.session_state.responses["health"] = request_json(base_url, "GET", "/health")
            st.rerun()

        if cap_result and cap_result["ok"]:
            st.success(
                f"연결모드={cap_payload.get('connection_mode')} | direct_rest={cap_payload.get('direct_rest')} | requires_local_hts={cap_payload.get('requires_local_hts')}"
            )
            st.dataframe(pd.DataFrame(as_list(cap_payload.get("capabilities"))), use_container_width=True, hide_index=True)
        render_call_status("기능 매트릭스", cap_result)

        if scope_result and scope_result["ok"]:
            summary = as_dict(scope_payload.get("groups"))
            domestic_count = as_dict(summary.get("domestic")).get("count", 0)
            overseas_count = as_dict(summary.get("overseas")).get("count", 0)
            st.caption(f"시장 범위 요약: 국내 {domestic_count}건 | 해외 {overseas_count}건 | 선물옵션 제외")
            scope_frame = flatten_scope_catalog(as_list(scope_payload.get("items")))
            if not scope_frame.empty:
                st.dataframe(scope_frame, use_container_width=True, hide_index=True)
        render_call_status("시장 범위 매트릭스", scope_result)

        st.subheader("1) 종목조회 필터 조건 목록")
        if st.button("필터 조건 전체 보기", use_container_width=True):
            st.session_state.responses["stock_filters"] = request_json(base_url, "GET", "/api/v1/kis/meta/stock-filters")
            st.rerun()

        stock_filters_result = st.session_state.responses.get("stock_filters")
        if stock_filters_result and stock_filters_result["ok"]:
            payload = as_dict(stock_filters_result["payload"])
            items = as_list(payload.get("items"))
            groups = as_dict(payload.get("groups"))
            domestic_count = as_dict(groups.get("domestic")).get("count", 0)
            overseas_count = as_dict(groups.get("overseas")).get("count", 0)
            st.caption(f"카탈로그 요약: 국내 {domestic_count}건 | 해외 {overseas_count}건")
            frame = flatten_filter_catalog(items)
            if frame.empty:
                st.info("필터 조건 데이터가 없습니다.")
            else:
                st.dataframe(frame, use_container_width=True, hide_index=True)
                render_filter_testers(base_url, items, st.session_state.selected_symbol)
        render_call_status("필터 조건 목록", stock_filters_result)

        st.subheader("2) 종목 검색 (키워드)")
        search_col1, search_col2 = st.columns([2, 1])
        keyword = search_col1.text_input("종목명/코드 키워드", value="")
        if search_col2.button("키워드 검색", use_container_width=True):
            result = request_json(base_url, "GET", "/api/v1/kis/meta/stocks/search", params={"keyword": keyword, "limit": 50})
            st.session_state.responses["stock_search"] = result
            payload = as_dict(result.get("payload"))
            st.session_state.stock_search_items = as_list(payload.get("items"))
            st.rerun()

        search_items = st.session_state.stock_search_items
        if search_items:
            labels = [f"{item['symbol']} | {item['name']} | {item['market']}" for item in search_items]
            selected_label = st.selectbox("검색 결과에서 종목 선택", options=labels)
            picked = search_items[labels.index(selected_label)]
            if st.button("선택 종목 적용", use_container_width=True):
                st.session_state.selected_symbol = picked["symbol"]
                st.rerun()
        render_call_status("종목검색", st.session_state.responses.get("stock_search"))
        st.caption(f"현재 선택 종목: {st.session_state.selected_symbol}")

        st.subheader("3) 계좌조회 - 제공 필드/의미")
        if connection_mode == "demo":
            st.info("현재 demo(모의투자) 모드입니다. 예수금 1억 등 모의계좌 기본값이 보일 수 있습니다.")
        else:
            st.success("현재 real(실전) 모드입니다. 실제 계좌 정보가 조회됩니다.")

        if st.button("계좌 필드 전체 조회", use_container_width=True):
            st.session_state.responses["account_fields"] = request_json(base_url, "GET", "/api/v1/kis/meta/account-fields")
            st.rerun()

        account_result = st.session_state.responses.get("account_fields")
        if account_result and account_result["ok"]:
            account_payload = as_dict(account_result["payload"])
            st.caption(f"총 필드 수: {account_payload.get('count', 0)}")
            render_field_table("계좌 응답 필드 (한국어 설명 + 회계표기)", as_list(account_payload.get("fields")))
            render_payload_expander("계좌 원문 payload", account_payload.get("payload", {}))
        render_call_status("계좌 필드 조회", account_result)

        st.subheader("4) 종목조회 - 제공 필드/의미")
        stock_left, stock_right = st.columns([1, 1])
        if stock_left.button("선택 종목 필드 전체 조회", use_container_width=True):
            st.session_state.responses["stock_fields"] = request_json(base_url, "GET", f"/api/v1/kis/meta/stock-fields/{symbol}")
            st.rerun()

        with stock_right:
            alarm_enabled = st.toggle("가격 알람 사용", value=False)
            alarm_mode = st.selectbox("알람 조건", options=[">=", "<="], index=0)
            alarm_price = st.number_input("기준 가격", min_value=0.0, value=100000.0, step=100.0)

        stock_result = st.session_state.responses.get("stock_fields")
        if stock_result and stock_result["ok"]:
            stock_payload = as_dict(stock_result["payload"])
            st.caption(
                f"현재가 필드: {stock_payload.get('price_field_count', 0)}개 | 호가 필드: {stock_payload.get('orderbook_field_count', 0)}개"
            )
            c1, c2 = st.columns(2)
            with c1:
                render_field_table("현재가 응답 필드 (한국어 설명 + 회계표기)", as_list(stock_payload.get("price_fields")))
            with c2:
                render_field_table("호가 응답 필드 (한국어 설명 + 회계표기)", as_list(stock_payload.get("orderbook_fields")))

            price_payload = as_dict(stock_payload.get("price_payload"))
            current_price = parse_current_price(price_payload)
            if current_price is not None:
                st.metric("현재가", f"{int(current_price):,}")
                should_alert = alarm_enabled and ((alarm_mode == ">=" and current_price >= alarm_price) or (alarm_mode == "<=" and current_price <= alarm_price))
                alert_key = f"{symbol}:{alarm_mode}:{alarm_price}:{int(current_price)}"
                if should_alert and st.session_state.last_price_alarm_sent != alert_key:
                    msg = f"{symbol} 현재가 {int(current_price):,}원, 조건 {alarm_mode} {int(alarm_price):,}원 충족"
                    st.session_state.responses["telegram_alert"] = request_json(base_url, "POST", "/api/v1/alerts/telegram/test", body={"message": msg})
                    st.session_state.last_price_alarm_sent = alert_key
                    st.rerun()

            render_payload_expander("종목 원문 payload", stock_payload)

        render_call_status("종목 필드 조회", stock_result)

        st.subheader("5) 차트 정보")
        chart_col1, chart_col2 = st.columns(2)
        with chart_col1:
            period_code = st.selectbox("일봉 주기", options=["D", "W", "M"], index=0)
            adjusted_price = st.selectbox("수정주가 반영", options=["1", "0"], index=0)
            if st.button("일/주/월 차트 조회", use_container_width=True):
                st.session_state.responses["chart_daily"] = request_json(
                    base_url,
                    "GET",
                    f"/api/v1/kis/chart/daily/{symbol}",
                    params={"period_code": period_code, "adjusted_price": adjusted_price},
                )
                st.rerun()

        with chart_col2:
            input_hour = st.text_input("분봉 기준시각(HHMMSS)", value="153000")
            include_past = st.selectbox("과거 포함", options=["Y", "N"], index=0)
            if st.button("당일 분봉 조회", use_container_width=True):
                st.session_state.responses["chart_intraday"] = request_json(
                    base_url,
                    "GET",
                    f"/api/v1/kis/chart/intraday/{symbol}",
                    params={"input_hour": input_hour, "include_past": include_past},
                )
                st.rerun()

        daily_result = st.session_state.responses.get("chart_daily")
        if daily_result and daily_result["ok"]:
            payload = as_dict(as_dict(daily_result["payload"]).get("payload"))
            frame = extract_daily_chart_df(payload)
            if not frame.empty:
                st.markdown("**일/주/월 차트 데이터**")
                st.dataframe(format_dataframe_accounting(frame), use_container_width=True, hide_index=True)
                if "stck_bsop_date" in frame.columns and "stck_clpr" in frame.columns:
                    chart_frame = frame.copy()
                    chart_frame["stck_clpr"] = pd.to_numeric(chart_frame["stck_clpr"], errors="coerce")
                    st.line_chart(chart_frame.set_index("stck_bsop_date")["stck_clpr"].dropna())
            render_payload_expander("일/주/월 원문 payload", daily_result["payload"])
        render_call_status("일/주/월 차트", daily_result)

        intraday_result = st.session_state.responses.get("chart_intraday")
        if intraday_result and intraday_result["ok"]:
            payload = as_dict(as_dict(intraday_result["payload"]).get("payload"))
            frame = extract_intraday_chart_df(payload)
            if not frame.empty:
                st.markdown("**당일 분봉 데이터**")
                st.dataframe(format_dataframe_accounting(frame), use_container_width=True, hide_index=True)
                if "stck_cntg_hour" in frame.columns and "stck_prpr" in frame.columns:
                    chart_frame = frame.copy()
                    chart_frame["stck_prpr"] = pd.to_numeric(chart_frame["stck_prpr"], errors="coerce")
                    st.line_chart(chart_frame.set_index("stck_cntg_hour")["stck_prpr"].dropna())
            render_payload_expander("분봉 원문 payload", intraday_result["payload"])
        render_call_status("당일 분봉", intraday_result)

        st.subheader("6) 뉴스/공시 제공 여부")
        news_col1, news_col2 = st.columns([1, 1])
        news_date = news_col1.text_input("조회일(YYYYMMDD, 선택)", value="")
        news_time = news_col2.text_input("조회시각(HHMMSS, 선택)", value="000000")
        if st.button("선택 종목 뉴스/공시 제목 조회", use_container_width=True):
            st.session_state.responses["news_title"] = request_json(
                base_url,
                "GET",
                f"/api/v1/kis/news-title/{symbol}",
                params={"date_yyyymmdd": news_date, "time_hhmmss": news_time},
            )
            st.rerun()

        news_result = st.session_state.responses.get("news_title")
        if news_result and news_result["ok"]:
            news_payload = as_dict(news_result["payload"])
            payload = as_dict(news_payload.get("payload"))
            output_rows = as_list(payload.get("output"))
            if output_rows:
                st.dataframe(format_dataframe_accounting(pd.DataFrame(output_rows)), use_container_width=True, hide_index=True)
            else:
                st.info("뉴스/공시 데이터가 없거나 제공업체 응답이 비어 있습니다.")
            render_payload_expander("뉴스/공시 원문 payload", news_payload)
        render_call_status("뉴스/공시 조회", news_result)

        st.subheader("7) 거래 기능 테스트 (REST)")
        st.caption("주의: KIS_URL이 실전이면 실제 주문이 전송됩니다.")
        execution_mode = st.radio(
            "주문 실행 경로",
            options=["로컬 시뮬레이션(권장)", "KIS REST 주문"],
            horizontal=True,
        )
        if connection_mode == "real":
            st.error("현재 실전 모드입니다. KIS REST 주문 선택 시 안전가드 통과 전까지 버튼이 잠금됩니다.")
        else:
            st.info("현재 모의 모드입니다. KIS REST 주문은 모의계좌로 전달됩니다.")

        use_kis_rest_order = execution_mode == "KIS REST 주문"
        order_col, rvse_col, reserve_col = st.columns(3)
        real_order_ack = st.checkbox("실주문 위험을 이해했고 진행에 동의", disabled=not use_kis_rest_order)
        real_order_text = st.text_input(f"확인 문구 입력: {REAL_ORDER_CONFIRM_TEXT}", value="", disabled=not use_kis_rest_order)
        symbol_confirm = st.text_input("확인용 종목코드 재입력", value="", disabled=not use_kis_rest_order).strip().upper()

        if not use_kis_rest_order:
            real_order_allowed = True
        elif connection_mode != "real":
            real_order_allowed = True
        else:
            real_order_allowed = real_order_ack and real_order_text.strip() == REAL_ORDER_CONFIRM_TEXT and symbol_confirm == symbol

        with order_col:
            st.markdown("**현금 주문(매수/매도) / 로컬 시뮬레이션**")
            order_side = st.selectbox("주문 방향", options=["buy", "sell"], key="order_side")
            order_qty = int(st.number_input("주문 수량", min_value=1, value=1, step=1, key="order_qty"))
            order_price = st.text_input("주문 가격", value="70000", key="order_price").strip()
            if st.button("현금주문 실행", use_container_width=True, disabled=not real_order_allowed):
                if use_kis_rest_order:
                    st.session_state.responses["order_cash"] = request_json(
                        base_url,
                        "POST",
                        "/api/v1/kis/order/cash",
                        body={"side": order_side, "symbol": symbol, "qty": order_qty, "price": order_price, "ord_dvsn": "00", "excg_id_dvsn_cd": "KRX"},
                    )
                else:
                    sim_price = float(order_price.replace(",", "")) if is_number_like(order_price) else 0.0
                    st.session_state.responses["order_cash"] = request_json(
                        base_url,
                        "POST",
                        "/api/v1/sim/orders",
                        body={"symbol": symbol, "side": "BUY" if order_side == "buy" else "SELL", "qty": order_qty, "price": sim_price},
                    )
                st.rerun()

        with rvse_col:
            st.markdown("**정정/취소 주문**")
            st.caption("KIS REST 주문에서만 테스트 가능")
            rvse_mode = st.selectbox("정정취소", options=["cancel", "modify"], key="rvse_mode")
            orgn_odno = st.text_input("원주문번호", value="", key="orgn_odno")
            rvse_qty = int(st.number_input("처리수량", min_value=0, value=0, step=1, key="rvse_qty"))
            rvse_price = st.text_input("정정가격", value="0", key="rvse_price")
            if st.button("정정/취소 실행", use_container_width=True, disabled=(not use_kis_rest_order) or (not real_order_allowed)):
                st.session_state.responses["order_rvsecncl"] = request_json(
                    base_url,
                    "POST",
                    "/api/v1/kis/order/rvsecncl",
                    body={"mode": rvse_mode, "orgn_odno": orgn_odno, "qty": rvse_qty, "order_qty": rvse_qty, "order_price": rvse_price, "qty_all_ord_yn": "N"},
                )
                st.rerun()

        with reserve_col:
            st.markdown("**예약 주문(매수/매도)**")
            st.caption("KIS REST 주문에서만 테스트 가능")
            reserve_side = st.selectbox("예약 방향", options=["buy", "sell"], key="reserve_side")
            reserve_qty = int(st.number_input("예약 수량", min_value=1, value=1, step=1, key="reserve_qty"))
            reserve_price = st.text_input("예약 가격", value="70000", key="reserve_price").strip()
            reserve_end_dt = st.text_input("예약종료일(선택, YYYYMMDD)", value="", key="reserve_end_dt").strip()
            if st.button("예약주문 실행", use_container_width=True, disabled=(not use_kis_rest_order) or (not real_order_allowed)):
                st.session_state.responses["order_reserve"] = request_json(
                    base_url,
                    "POST",
                    "/api/v1/kis/order/reserve",
                    body={"side": reserve_side, "symbol": symbol, "qty": reserve_qty, "price": reserve_price, "ord_dvsn_cd": "00", "ord_objt_cblc_dvsn_cd": "10", "rsvn_ord_end_dt": reserve_end_dt},
                )
                st.rerun()

        render_call_status("현금주문", st.session_state.responses.get("order_cash"))
        render_call_status("정정/취소", st.session_state.responses.get("order_rvsecncl"))
        render_call_status("예약주문", st.session_state.responses.get("order_reserve"))
        if st.session_state.responses.get("order_cash"):
            render_payload_expander("현금주문 원본 payload", as_dict(st.session_state.responses["order_cash"]).get("payload"))
        if st.session_state.responses.get("order_rvsecncl"):
            render_payload_expander("정정/취소 원본 payload", as_dict(st.session_state.responses["order_rvsecncl"]).get("payload"))
        if st.session_state.responses.get("order_reserve"):
            render_payload_expander("예약주문 원본 payload", as_dict(st.session_state.responses["order_reserve"]).get("payload"))

        render_overseas_test_section(
            base_url=base_url,
            responses=st.session_state.responses,
            request_json=request_json,
            render_call_status=render_call_status,
            render_payload_expander=render_payload_expander,
            as_dict=as_dict,
            format_dataframe_accounting=format_dataframe_accounting,
        )

        render_api_smoke_section(
            base_url=base_url,
            responses=st.session_state.responses,
            request_json=request_json,
            render_call_status=render_call_status,
            render_payload_expander=render_payload_expander,
            as_dict=as_dict,
        )

        render_strategy_section(
            base_url=base_url,
            responses=st.session_state.responses,
            request_json=request_json,
            render_call_status=render_call_status,
            render_payload_expander=render_payload_expander,
            as_dict=as_dict,
            format_dataframe_accounting=format_dataframe_accounting,
        )

        render_autotrade_section(
            base_url=base_url,
            responses=st.session_state.responses,
            request_json=request_json,
            render_call_status=render_call_status,
            render_payload_expander=render_payload_expander,
            as_dict=as_dict,
        )

        st.subheader("9) 텔레그램 연동")
        test_message = st.text_input("테스트 메시지", value="KIS API 알림 테스트")
        if st.button("텔레그램 테스트 발송", use_container_width=True):
            st.session_state.responses["telegram_test"] = request_json(base_url, "POST", "/api/v1/alerts/telegram/test", body={"message": test_message})
            st.rerun()
        render_call_status("텔레그램 발송", st.session_state.responses.get("telegram_test"))
        render_call_status("가격 알람 발송", st.session_state.responses.get("telegram_alert"))

        st.subheader("호출 로그")
        logs = pd.DataFrame(st.session_state.logs)
        if logs.empty:
            st.info("아직 로그가 없습니다.")
        else:
            st.dataframe(logs, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
