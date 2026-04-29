# INBOX — Gemini (Frontend)
**작업**: 단타봇 API 허브 — 프론트엔드 구현 (Step 6~7)  
**계획서**: `docs/planning/작업계획서_단타봇_API허브_메뉴_v1.md` 반드시 먼저 읽을 것  
**⚠️ 전제**: 백엔드 OUTBOX(`docs/agent-comm/OUTBOX_CODEX_trading_hub_backend.md`)가 존재하면 먼저 읽을 것  
**완료 후**: `docs/agent-comm/OUTBOX_GEMINI_trading_hub_frontend.md` 에 결과 작성

---

## 구현 지시 (순서 엄수)

### Step 6: `frontend/sections/trading_hub.py` 신규 작성

기존 `frontend/sections/` 파일들(api_smoke.py, autotrade.py 등)의 패턴을 따른다.

**메인 함수**: `render_trading_hub_section(base_url: str) -> None`

내부에 `st.tabs(["[A] Universe", "[B] 현재상태", "[C] 실시간", "[D] 주문", "[E] 스윙"])` 구조.

---

#### [A] Universe 탭

UI 요소:
- `market_code` 셀렉트박스 (옵션: "J"=전체, "STK"=코스피, "KSQ"=코스닥)
- `top_n` 슬라이더 (10~100, 기본 50)
- 버튼 3개: "거래량 순위 조회", "등락률 순위 조회", "거래대금 순위 조회"

동작:
- "거래량 순위 조회" → `GET {base_url}/api/v1/kis/universe/volume-rank?market_code=...&top_n=...`
- "등락률 순위 조회" → `GET {base_url}/api/v1/kis/universe/price-rank?sort_by=change_rate&...`
- "거래대금 순위 조회" → `GET {base_url}/api/v1/kis/universe/price-rank?sort_by=trade_amount&...`

결과 표시: `st.dataframe()`으로 테이블 출력  
종목 선택: 테이블 아래 `st.selectbox`로 종목 선택 → `st.session_state.selected_symbol` 업데이트

---

#### [B] 현재상태 탭

선택 종목(`st.session_state.selected_symbol`) 기준으로:
- 버튼: "현재가 조회" → `GET {base_url}/api/v1/kis/price/{symbol}`
- 버튼: "호가 조회" → `GET {base_url}/api/v1/kis/orderbook/{symbol}`
- 버튼: "분봉 조회" → `GET {base_url}/api/v1/kis/chart/intraday/{symbol}`

각 결과 JSON 표시 (기존 app.py의 `st.json()` 패턴 참고)

---

#### [C] 실시간 탭

- 종목코드 입력 (복수, 쉼표 구분)
- 버튼: "WebSocket 연결 시작" → `POST {base_url}/api/v1/kis/realtime/start` (body: symbols 리스트)
- 버튼: "연결 종료" → `POST {base_url}/api/v1/kis/realtime/stop`
- 연결 상태 표시 → `GET {base_url}/api/v1/kis/realtime/status`
- "최신 체결 조회" 버튼 → `GET {base_url}/api/v1/kis/realtime/latest?n=50` → `st.dataframe()`
- 자동 갱신 체크박스: 켜면 3초마다 `st.rerun()` (기존 app.py의 time.sleep 패턴 참고)

---

#### [D] 주문 탭

선택 종목 기준으로:
- 잔고 조회: `GET {base_url}/api/v1/kis/balance`
- 매수/매도: `POST {base_url}/api/v1/kis/order/cash`
  - 입력: 주문 방향(buy/sell), 수량, 가격, 주문유형
  - 실주문 안전장치: "실주문동의" 텍스트 입력 확인 후에만 실행 (기존 app.py REAL_ORDER_CONFIRM_TEXT 패턴 그대로 사용)

---

#### [E] 스윙 탭

선택 종목 기준으로:
- 버튼: "일봉 차트" → `GET {base_url}/api/v1/kis/chart/daily/{symbol}`
- period_code 셀렉트박스 (D/W/M)
- 재무 데이터: `GET {base_url}/api/v1/kis/fundamental/{symbol}` 호출 시도
  - 실패하면 `st.warning("재무 API 미지원 또는 미구현")` 표시 (에러로 죽으면 안 됨)

---

### Step 7: `frontend/app.py` 사이드바 수정

⚠️ 기존 코드는 최소한으로 수정한다. 기존 검증 페이지 로직은 건드리지 않는다.

수정 내용:
1. `from frontend.sections.trading_hub import render_trading_hub_section` import 추가
2. `with st.sidebar:` 블록 상단에 페이지 선택 라디오 추가:

```python
page = st.radio(
    "페이지 선택",
    options=["KIS API 검증", "단타봇 허브"],
    index=0,
    key="page_select"
)
st.divider()
```

3. 기존 페이지 렌더 코드 전체를 `if page == "KIS API 검증":` 블록으로 감싸기
4. `elif page == "단타봇 허브":` 추가 → `render_trading_hub_section(base_url)` 호출

---

## 완료 조건

- `python -c "from frontend.sections.trading_hub import render_trading_hub_section; print('OK')"` exit 0
- `python -m py_compile frontend/app.py` exit 0
- `OUTBOX_GEMINI_trading_hub_frontend.md`에 결과 작성:
  - 완료 파일 목록
  - 실패/스킵 항목
