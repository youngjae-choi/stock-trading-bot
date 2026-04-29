# OUTBOX — Gemini (Frontend)

## 1) 완료 파일 목록
- `frontend/sections/trading_hub.py` (신규)
- `frontend/app.py` (수정: 사이드바 메뉴 및 섹션 분기 추가)

## 2) 구현 요약

### Step 6: `frontend/sections/trading_hub.py` 구현
- **[A] Universe**: 거래량/등락률/거래대금 순위 조회 및 종목 선택 기능 구현.
- **[B] 현재상태**: 선택된 종목의 현재가, 호가, 분봉 데이터 조회 및 JSON 표시 구현.
- **[C] 실시간**: WebSocket 연결 제어(시작/종료) 및 최신 체결 데이터 폴링(3초 자동 갱신 가능) 구현.
- **[D] 주문**: 잔고 조회 및 현금 주문(매수/매도) 기능 구현. '실주문동의' 안전장치 적용.
- **[E] 스윙**: 일봉 차트 조회 및 재무 데이터 조회 기능 구현. (재무 API 미구현 시 경고 표시 처리)

### Step 7: `frontend/app.py` 수정
- 사이드바 상단에 "페이지 선택" 라디오 버튼 추가 (KIS API 검증 / 단타봇 허브).
- 선택된 페이지에 따라 기존 검증 로직 또는 신규 트레이딩 허브 섹션을 렌더링하도록 분기 처리.
- 기존 코드를 최대한 유지하면서 신규 기능을 독립된 섹션으로 통합.

## 3) 검증 결과
- `python -m py_compile frontend/app.py frontend/sections/trading_hub.py` → **PASS** (exit 0)
- `python -c "from frontend.sections.trading_hub import render_trading_hub_section; print('OK')"` → **OK** (exit 0)
- `frontend/app.py`의 `main()` 함수 내 들여쓰기 정상화 확인.

## 4) 비고 및 리스크
- WebSocket 실시간 데이터는 백엔드의 `/api/v1/kis/realtime/latest`를 3초 주기로 폴링하여 표시합니다.
- 재무 데이터 조회(`GET /api/v1/kis/fundamental/{symbol}`)는 백엔드 구현 여부에 따라 실패할 수 있으며, 이 경우 사용자에게 경고 메시지를 노출합니다.
