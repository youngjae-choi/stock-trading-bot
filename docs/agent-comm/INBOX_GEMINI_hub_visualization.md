# INBOX — Gemini (Frontend Visualization)
**파일**: `frontend/sections/trading_hub.py` 수정
**완료 후**: `docs/agent-comm/OUTBOX_GEMINI_hub_visualization.md` 작성

## 전제
- 기존 `frontend/sections/trading_hub.py` 코드를 먼저 읽고 수정
- plotly 사용 (`import plotly.graph_objects as go`, `st.plotly_chart()`)
- 기존 API 호출 로직(request_json, responses) 유지하고 표시 부분만 교체

---

## [B] 현재상태 탭 시각화

### 현재가 (hub_price) 응답 구조
```python
# response["payload"] 는 dict:
# 최상위 키: "output" (dict), "rt_cd", "msg_cd", "msg1"
# output 안: stck_prpr(현재가), prdy_vrss(전일대비), prdy_ctrt(등락률%),
#            stck_hgpr(고가), stck_lwpr(저가), stck_oprc(시가),
#            acml_vol(누적거래량), acml_tr_pbmn(거래대금)
```

### 현재가 표시 방법
```python
payload = as_dict(res_p.get("payload"))
output = as_dict(payload.get("output"))
price = int(output.get("stck_prpr","0").replace(",","") or 0)
change = float(output.get("prdy_ctrt","0").replace(",","") or 0)
col1, col2, col3, col4 = st.columns(4)
col1.metric("현재가", f"{price:,}원", f"{change:+.2f}%")
col2.metric("고가", f"{int(output.get('stck_hgpr','0').replace(',','') or 0):,}원")
col3.metric("저가", f"{int(output.get('stck_lwpr','0').replace(',','') or 0):,}원")
col4.metric("거래량", f"{int(output.get('acml_vol','0').replace(',','') or 0):,}")
```

### 호가 (hub_orderbook) 응답 구조
```
payload["output1"]["askp1~5"] (매도호가), "askp_rsqn1~5" (매도잔량)
payload["output1"]["bidp1~5"] (매수호가), "bidp_rsqn1~5" (매수잔량)
```

### 호가 표시 방법
- 매도호가(빨강) 5단계 위에, 매수호가(파랑) 5단계 아래로 표시
- `st.dataframe()` with background_gradient or progress bar
- 매도/매수 컬럼 좌우 배치:
  ```
  [매도잔량 | 가격 | 매수잔량]
  ```
- 매도는 빨간색 배경, 매수는 파란색 배경 (Pandas Styler 사용)

### 분봉 (hub_intraday) 응답 구조
```
payload["output2"] = list of candles:
  each: stck_bsop_date(날짜), stck_cntg_hour(시간HH:MM:SS),
        stck_prpr(현재가/종가), stck_oprc(시가), stck_hgpr(고가), stck_lwpr(저가),
        cntg_vol(체결량)
```

### 분봉 표시 방법 — Plotly Candlestick
```python
import plotly.graph_objects as go
rows = as_list(as_dict(payload).get("output2"))
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
```

---

## [C] 실시간 탭 — 장마감 안내 추가

WebSocket이 연결됐지만 장마감 후에는 PINGPONG만 수신됨.
- 연결 상태: `st.success("연결됨")` / `st.error("미연결")`
- 체결 데이터가 없을 때: `st.info("장마감 중 — 체결 데이터 없음. 장중(09:00~15:30)에 실시간 체결이 수신됩니다.")`
- 데이터가 있을 때: 기존 dataframe 표시 유지

---

## [D] 주문 탭 — 잔고 시각화

### 잔고 (hub_balance) 응답 구조
```python
# response["payload"] 구조:
# output1: list of holdings [{pdno(종목코드), prdt_name(종목명),
#           hldg_qty(보유수량), pchs_avg_pric(평균단가),
#           evlu_pfls_rt(평가손익율%), evlu_amt(평가금액)}]
# output2: list (1개) [{dnca_tot_amt(예수금), scts_evlu_amt(주식평가금액),
#           tot_evlu_amt(총평가금액), pchs_amt_smtl_amt(매입금액합계)}]
```

### 잔고 표시 방법
```python
payload = as_dict(res.get("payload"))
output2 = as_list(payload.get("output2"))
summary = as_dict(output2[0] if output2 else {})

col1, col2, col3 = st.columns(3)
col1.metric("예수금", f"{int(summary.get('dnca_tot_amt','0').replace(',','') or 0):,}원")
col2.metric("주식평가금액", f"{int(summary.get('scts_evlu_amt','0').replace(',','') or 0):,}원")
col3.metric("총평가금액", f"{int(summary.get('tot_evlu_amt','0').replace(',','') or 0):,}원")

# 보유종목 테이블
output1 = as_list(payload.get("output1"))
if output1:
    df = pd.DataFrame(output1)[["pdno","prdt_name","hldg_qty","pchs_avg_pric","evlu_pfls_rt","evlu_amt"]]
    df.columns = ["종목코드","종목명","보유수량","평균단가","손익률(%)","평가금액"]
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.info("보유 종목 없음")
```

---

## [E] 스윙 탭 — 봉차트 시각화

### 일봉 (hub_daily_chart) 응답 구조
```python
# response["payload"]["output"] = list of candles:
# stck_bsop_date(YYYYMMDD), stck_oprc(시가), stck_hgpr(고가),
# stck_lwpr(저가), stck_clpr(종가), acml_vol(거래량)
```

### 봉차트 표시 방법 — Plotly Candlestick + 거래량 바
```python
import plotly.graph_objects as go
from plotly.subplots import make_subplots

rows_data = as_list(as_dict(as_dict(chart_res.get("payload"))).get("output"))
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
```

---

## 완료 조건
- `python -m py_compile frontend/sections/trading_hub.py` exit 0
- `python -c "from frontend.sections.trading_hub import render_trading_hub_section; print('OK')"` exit 0
- OUTBOX에 수정 내용 요약 작성
