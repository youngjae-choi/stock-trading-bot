"""Streamlit section for Trading Hub - Universe, Price, Realtime, Order, Swing."""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

REAL_ORDER_CONFIRM_TEXT = "실주문동의"


def render_trading_hub_section(
    *,
    base_url: str,
    responses: Dict[str, Any],
    request_json: Callable[..., Dict[str, Any]],
    render_call_status: Callable[[str, Dict[str, Any] | None], None],
    render_payload_expander: Callable[[str, Any], None],
    as_dict: Callable[[Any], Dict[str, Any]],
    as_list: Callable[[Any], List[Any]],
    format_dataframe_accounting: Callable[[pd.DataFrame], pd.DataFrame],
) -> None:
    """Render the Trading Hub section with 5 tabs."""
    st.header("단타봇 API 허브")

    tab_a, tab_b, tab_c, tab_d, tab_e = st.tabs(["[A] 우주 (Universe)", "[B] 현재 상태", "[C] 실시간", "[D] 주문", "[E] 스윙"])

    # --- [A] Universe ---
    with tab_a:
        st.subheader("종목 유니버스 조회")
        st.caption("전체 상장 종목 중 '오늘 주목할 종목 후보군'을 추립니다. 거래량·등락률·거래대금 기준으로 상위 N개를 뽑아 단타/스윙 대상 풀(Pool)을 구성합니다.")

        c1, c2 = st.columns([1, 2])
        market_code = c1.selectbox("시장 구분", options=["J", "STK", "KSQ"], index=0)
        top_n = c2.slider("조회 순위 (Top N)", min_value=10, max_value=60, value=30, step=10)

        # 시장 구분 설명
        market_desc = {
            "J": "**J — 전체 시장** : 코스피 + 코스닥을 합산한 전체 국내 주식 시장입니다. 가장 넓은 종목 풀을 대상으로 조회합니다.",
            "STK": "**STK — 코스피 (유가증권시장)** : 삼성전자, SK하이닉스 등 대형주 중심의 메인 시장입니다. 시가총액 규모가 크고 거래가 안정적입니다.",
            "KSQ": "**KSQ — 코스닥** : 중소·성장형 기업 중심의 시장입니다. 변동성이 크고 단타 기회가 많습니다.",
        }
        st.info(market_desc[market_code])

        bc1, bc2, bc3 = st.columns(3)
        bc1.caption("📊 오늘 가장 많이 거래된 종목 순서")
        bc2.caption("📈 오늘 주가가 가장 많이 오른 종목 순서")
        bc3.caption("💰 오늘 가장 많은 금액이 거래된 종목 순서")
        if bc1.button("거래량 순위 조회", use_container_width=True):
            responses["universe_volume"] = request_json(
                base_url, "GET", "/api/v1/kis/universe/volume-rank", params={"market_code": market_code, "top_n": top_n}
            )
            st.session_state["universe_last_key"] = "universe_volume"
            st.rerun()
        if bc2.button("등락률 순위 조회", use_container_width=True):
            responses["universe_price_rate"] = request_json(
                base_url,
                "GET",
                "/api/v1/kis/universe/price-rank",
                params={"sort_by": "change_rate", "market_code": market_code, "top_n": top_n},
            )
            st.session_state["universe_last_key"] = "universe_price_rate"
            st.rerun()
        if bc3.button("거래대금 순위 조회", use_container_width=True):
            responses["universe_price_amount"] = request_json(
                base_url,
                "GET",
                "/api/v1/kis/universe/price-rank",
                params={"sort_by": "trade_amount", "market_code": market_code, "top_n": top_n},
            )
            st.session_state["universe_last_key"] = "universe_price_amount"
            st.rerun()

        # Display Result — 마지막으로 클릭한 버튼의 결과를 표시
        last_key = st.session_state.get("universe_last_key", "universe_volume")
        universe_res = responses.get(last_key)
        if universe_res and universe_res["ok"]:
            # request_json이 백엔드 응답 전체를 payload로 감싸므로 두 단계 언래핑
            outer = as_dict(universe_res.get("payload"))
            payload = as_dict(outer.get("payload")) if "payload" in outer else outer
            items = as_list(payload.get("items"))
            if items:
                df = pd.DataFrame(items)
                st.dataframe(format_dataframe_accounting(df), use_container_width=True, hide_index=True)

                symbols = [f"{item['symbol']} | {item['name']}" for item in items]
                selected_item = st.selectbox("종목 선택 (현재상태/주문 탭 연동)", options=symbols, key="hub_symbol_select")
                if selected_item:
                    st.session_state.selected_symbol = selected_item.split(" | ")[0]
            else:
                st.info("조회 결과가 없습니다.")
        
        render_call_status("유니버스 조회", universe_res)

    # --- [B] 현재상태 ---
    with tab_b:
        symbol = st.session_state.get("selected_symbol", "005930")
        st.subheader(f"현재상태 조회: {symbol}")
        st.caption("선택한 종목의 '지금 이 순간' 상태를 조회합니다. [A] 우주 탭에서 종목을 선택하면 자동으로 연동됩니다.")

        bc1, bc2, bc3 = st.columns(3)
        bc1.caption("현재가·등락률·거래량 등 핵심 시세")
        bc2.caption("매수/매도 호가 10단계 (체결 압력 확인)")
        bc3.caption("분 단위 캔들 차트 데이터 (단타 타이밍)")
        if bc1.button("현재가 조회", use_container_width=True, key="btn_price"):
            responses["hub_price"] = request_json(base_url, "GET", f"/api/v1/kis/price/{symbol}")
            st.rerun()
        if bc2.button("호가 조회", use_container_width=True, key="btn_orderbook"):
            responses["hub_orderbook"] = request_json(base_url, "GET", f"/api/v1/kis/orderbook/{symbol}")
            st.rerun()
        if bc3.button("분봉 조회", use_container_width=True, key="btn_intraday"):
            responses["hub_intraday"] = request_json(base_url, "GET", f"/api/v1/kis/chart/intraday/{symbol}")
            st.rerun()

        res_p = responses.get("hub_price")
        res_o = responses.get("hub_orderbook")
        res_i = responses.get("hub_intraday")

        if res_p and res_p["ok"]:
            payload = as_dict(res_p.get("payload"))
            if "payload" in payload:
                payload = as_dict(payload["payload"])
            output = as_dict(payload.get("output"))
            if output:
                price = int(output.get("stck_prpr", "0").replace(",", "") or 0)
                change = float(output.get("prdy_ctrt", "0").replace(",", "") or 0)
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("현재가", f"{price:,}원", f"{change:+.2f}%")
                col2.metric("고가", f"{int(output.get('stck_hgpr', '0').replace(',', '') or 0):,}원")
                col3.metric("저가", f"{int(output.get('stck_lwpr', '0').replace(',', '') or 0):,}원")
                col4.metric("거래량", f"{int(output.get('acml_vol', '0').replace(',', '') or 0):,}")
            else:
                st.info("현재가 데이터가 없습니다.")

        if res_o and res_o["ok"]:
            st.markdown("**호가 (Orderbook)**")
            payload = as_dict(res_o.get("payload"))
            if "payload" in payload:
                payload = as_dict(payload["payload"])
            output1 = as_dict(payload.get("output1"))
            if output1:
                # 5 levels
                ask_data = []
                for i in range(5, 0, -1):
                    ask_data.append({
                        "매도잔량": int(output1.get(f"askp_rsqn{i}", 0)),
                        "가격": int(output1.get(f"askp{i}", 0)),
                        "매수잔량": 0
                    })
                bid_data = []
                for i in range(1, 6):
                    bid_data.append({
                        "매도잔량": 0,
                        "가격": int(output1.get(f"bidp{i}", 0)),
                        "매수잔량": int(output1.get(f"bidp_rsqn{i}", 0))
                    })
                df_ob = pd.DataFrame(ask_data + bid_data)
                
                def color_orderbook(row):
                    if row.name < 5:  # 매도 (상위 5개)
                        return ["background-color: #ffebee"] * len(row)
                    return ["background-color: #e3f2fd"] * len(row)

                st.dataframe(
                    df_ob.style.apply(color_orderbook, axis=1),
                    use_container_width=True,
                    hide_index=True
                )

        if res_i and res_i["ok"]:
            payload = as_dict(res_i.get("payload"))
            if "payload" in payload:
                payload = as_dict(payload["payload"])
            rows = as_list(payload.get("output2"))
            if rows:
                df = pd.DataFrame(rows)
                fig = go.Figure(data=[go.Candlestick(
                    x=df["stck_cntg_hour"],
                    open=df["stck_oprc"].astype(float),
                    high=df["stck_hgpr"].astype(float),
                    low=df["stck_lwpr"].astype(float),
                    close=df["stck_prpr"].astype(float),
                    increasing_line_color="#FF4B4B",
                    decreasing_line_color="#4B8BFF",
                )])
                fig.update_layout(title=f"{symbol} 분봉", xaxis_rangeslider_visible=False, height=400)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("분봉 데이터가 없습니다.")

    # --- [C] 실시간 ---
    with tab_c:
        st.subheader("실시간 체결 (WebSocket)")
        st.caption("KIS WebSocket에 연결해 실시간 체결 데이터를 수신합니다. 단타의 핵심 — 체결 속도·매수매도 강도·순간 거래량 급증을 감지합니다.")
        st.info("💡 **연결 방식**: 백엔드가 KIS WebSocket을 상시 유지하고, 이 화면은 3초마다 최신 데이터를 가져옵니다. 여러 종목을 쉼표로 구분해 동시 구독할 수 있습니다.")
        symbols_input = st.text_input("구독 종목코드 (쉼표 구분, 예: 005930,000660)", value=st.session_state.get("selected_symbol", "005930"))
        
        c1, c2 = st.columns(2)
        if c1.button("WebSocket 연결 시작", use_container_width=True):
            sym_list = [s.strip() for s in symbols_input.split(",") if s.strip()]
            responses["rt_start"] = request_json(base_url, "POST", "/api/v1/kis/realtime/start", body={"symbols": sym_list})
            st.rerun()
        if c2.button("연결 종료", use_container_width=True):
            responses["rt_stop"] = request_json(base_url, "POST", "/api/v1/kis/realtime/stop")
            st.rerun()

        # Status & Latest
        status_res = request_json(base_url, "GET", "/api/v1/kis/realtime/status", log=False)
        if status_res["ok"]:
            rt_status = as_dict(status_res.get("payload"))
            is_connected = rt_status.get("connected", False)
            if is_connected:
                st.success("WebSocket 연결됨")
                st.caption(f"구독 중: {rt_status.get('symbols', [])}")
            else:
                st.error("WebSocket 미연결")

        if st.button("최신 체결 조회", use_container_width=True):
            responses["rt_latest"] = request_json(base_url, "GET", "/api/v1/kis/realtime/latest", params={"n": 50})
            st.rerun()

        latest_res = responses.get("rt_latest")
        if latest_res and latest_res["ok"]:
            rt_items = as_list(as_dict(latest_res.get("payload")).get("items"))
            if rt_items:
                st.dataframe(pd.DataFrame(rt_items), use_container_width=True, hide_index=True)
            else:
                st.info("장마감 중 — 체결 데이터 없음. 장중(09:00~15:30)에 실시간 체결이 수신됩니다.")

        auto_refresh = st.checkbox("3초마다 자동 갱신", value=False)
        if auto_refresh:
            time.sleep(3)
            st.rerun()

    # --- [D] 주문 ---
    with tab_d:
        symbol = st.session_state.get("selected_symbol", "005930")
        st.subheader(f"주문 실행: {symbol}")
        st.caption("[A] 우주 탭에서 선택한 종목을 대상으로 실제 매수/매도 주문을 전송합니다. 실주문이므로 반드시 확인 문구를 입력해야 버튼이 활성화됩니다.")

        if st.button("잔고 조회", use_container_width=True):
            responses["hub_balance"] = request_json(base_url, "GET", "/api/v1/kis/balance")
            st.rerun()
        
        bal_res = responses.get("hub_balance")
        if bal_res and bal_res["ok"]:
            payload = as_dict(bal_res.get("payload"))
            if "payload" in payload:
                payload = as_dict(payload["payload"])
            
            output2 = as_list(payload.get("output2"))
            summary = as_dict(output2[0] if output2 else {})

            col1, col2, col3 = st.columns(3)
            col1.metric("예수금", f"{int(summary.get('dnca_tot_amt', '0').replace(',', '') or 0):,}원")
            col2.metric("주식평가금액", f"{int(summary.get('scts_evlu_amt', '0').replace(',', '') or 0):,}원")
            col3.metric("총평가금액", f"{int(summary.get('tot_evlu_amt', '0').replace(',', '') or 0):,}원")

            # 보유종목 테이블
            output1 = as_list(payload.get("output1"))
            if output1:
                df_bal = pd.DataFrame(output1)
                cols_to_show = ["pdno", "prdt_name", "hldg_qty", "pchs_avg_pric", "evlu_pfls_rt", "evlu_amt"]
                # Filter only existing columns to avoid KeyError
                cols_to_show = [c for c in cols_to_show if c in df_bal.columns]
                df_bal = df_bal[cols_to_show]
                
                rename_map = {
                    "pdno": "종목코드",
                    "prdt_name": "종목명",
                    "hldg_qty": "보유수량",
                    "pchs_avg_pric": "평균단가",
                    "evlu_pfls_rt": "손익률(%)",
                    "evlu_amt": "평가금액"
                }
                df_bal.columns = [rename_map.get(c, c) for c in df_bal.columns]
                st.dataframe(df_bal, use_container_width=True, hide_index=True)
            else:
                st.info("보유 종목 없음")
        
        st.divider()
        
        oc1, oc2 = st.columns(2)
        side = oc1.selectbox("매수/매도", options=["buy", "sell"], format_func=lambda x: "매수 (Buy)" if x == "buy" else "매도 (Sell)")
        qty = oc2.number_input("주문 수량 (주)", min_value=1, value=1, step=1)
        price = oc1.text_input("주문 가격 (원, 0 입력 시 시장가)", value="0")
        ord_dvsn = oc2.selectbox("주문 유형", options=["00", "01"], format_func=lambda x: "00 — 지정가 (내가 정한 가격에만 체결)" if x == "00" else "01 — 시장가 (즉시 현재가로 체결)")

        # 주문 유형 설명
        if ord_dvsn == "00":
            st.caption("📌 **지정가**: 입력한 가격 이하(매수) 또는 이상(매도)일 때만 체결됩니다. 원하는 가격에 사고 싶을 때 사용.")
        else:
            st.caption("⚡ **시장가**: 현재 시장 가격으로 즉시 체결됩니다. 빠른 진입/청산이 필요한 단타에서 주로 사용. 가격 입력값은 무시됩니다.")

        st.warning("⚠️ 실주문 주의: 확인 문구를 정확히 입력해야 버튼이 활성화됩니다.")
        confirm_text = st.text_input(f"'{REAL_ORDER_CONFIRM_TEXT}' 입력", value="")
        
        order_allowed = confirm_text == REAL_ORDER_CONFIRM_TEXT
        if st.button("주문 전송", use_container_width=True, disabled=not order_allowed):
            responses["hub_order"] = request_json(
                base_url, 
                "POST", 
                "/api/v1/kis/order/cash", 
                body={
                    "side": side,
                    "symbol": symbol,
                    "qty": qty,
                    "price": price,
                    "ord_dvsn": ord_dvsn,
                    "excg_id_dvsn_cd": "KRX"
                }
            )
            st.rerun()
        
        render_call_status("주문 결과", responses.get("hub_order"))
        if responses.get("hub_order"):
            st.json(responses["hub_order"].get("payload", {}))

    # --- [E] 스윙 ---
    with tab_e:
        symbol = st.session_state.get("selected_symbol", "005930")
        st.subheader(f"스윙/재무 분석: {symbol}")
        st.caption("며칠~몇 주 단위로 보유하는 스윙 매매를 위한 추세·재무 분석입니다. 일봉 흐름과 기업 기초체력(재무)을 함께 확인합니다.")

        c1, c2 = st.columns(2)
        period_code = c1.selectbox(
            "차트 주기",
            options=["D", "W", "M"],
            index=0,
            key="swing_period",
            format_func=lambda x: {"D": "D — 일봉 (하루 단위)", "W": "W — 주봉 (1주 단위)", "M": "M — 월봉 (1달 단위)"}[x]
        )
        # 주기 설명
        period_desc = {
            "D": "📅 **일봉**: 하루의 시가·고가·저가·종가를 하나의 캔들로 표시합니다. 스윙 매매의 기본 단위입니다.",
            "W": "📅 **주봉**: 한 주(5거래일)를 하나의 캔들로 요약합니다. 중기 추세 파악에 적합합니다.",
            "M": "📅 **월봉**: 한 달을 하나의 캔들로 요약합니다. 장기 방향성 확인에 사용합니다.",
        }
        c1.caption(period_desc[period_code])
        if c2.button("일봉 차트 조회", use_container_width=True):
            responses["hub_daily_chart"] = request_json(
                base_url, "GET", f"/api/v1/kis/chart/daily/{symbol}", params={"period_code": period_code}
            )
            st.rerun()

        chart_res = responses.get("hub_daily_chart")
        if chart_res and chart_res["ok"]:
            payload = as_dict(chart_res.get("payload"))
            if "payload" in payload:
                payload = as_dict(payload["payload"])
            rows_data = as_list(payload.get("output"))
            
            if rows_data:
                df = pd.DataFrame(rows_data)
                df["date"] = pd.to_datetime(df["stck_bsop_date"], format="%Y%m%d")
                df = df.sort_values("date")

                fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                                    row_heights=[0.7, 0.3], vertical_spacing=0.03)
                fig.add_trace(go.Candlestick(
                    x=df["date"], open=df["stck_oprc"].astype(float),
                    high=df["stck_hgpr"].astype(float), low=df["stck_lwpr"].astype(float),
                    close=df["stck_clpr"].astype(float),
                    increasing_line_color="#FF4B4B", decreasing_line_color="#4B8BFF",
                    name="봉차트"
                ), row=1, col=1)
                fig.add_trace(go.Bar(
                    x=df["date"], y=df["acml_vol"].astype(float),
                    marker_color="#888888", name="거래량"
                ), row=2, col=1)
                fig.update_layout(xaxis_rangeslider_visible=False, height=500,
                                  title=f"{symbol} {period_code}봉 차트")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("차트 데이터가 없습니다.")

        st.divider()
        if st.button("재무 데이터 조회", use_container_width=True):
            res = request_json(base_url, "GET", f"/api/v1/kis/fundamental/{symbol}")
            if not res["ok"]:
                st.warning("재무 API 미지원 또는 미구현 (404/500)")
            else:
                st.json(res.get("payload", {}))
            responses["hub_fundamental"] = res
            st.rerun()
