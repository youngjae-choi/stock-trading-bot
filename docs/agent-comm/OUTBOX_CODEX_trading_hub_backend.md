# OUTBOX — Codex (Backend)

## 1) 완료 파일 목록
- `backend/services/kis/domestic/universe_service.py` (신규)
- `backend/api/routes/universe.py` (신규)
- `backend/services/kis/realtime_ws.py` (신규)
- `backend/api/routes/realtime.py` (신규)
- `backend/main.py` (수정: universe/realtime 라우터 등록)

## 2) 구현 요약
- Universe 서비스 2개 함수 구현
  - `get_volume_rank(market_code="J", top_n=100)`
  - `get_price_rank(sort_by="change_rate", market_code="J", top_n=100)`
- `top_n`은 최대 100으로 clamp 처리.
- Universe 라우트 추가
  - `GET /api/v1/kis/universe/volume-rank`
  - `GET /api/v1/kis/universe/price-rank`
  - 응답 형식: `{"ok": True, "payload": ...}`
- Realtime WebSocket 매니저 추가
  - `RealtimeWSManager` 싱글턴
  - `start(symbols)`, `stop()`, `get_latest(n)`, `is_connected`
  - 체결 캐시: `deque(maxlen=200)`
- Realtime 라우트 추가
  - `GET /api/v1/kis/realtime/status`
  - `GET /api/v1/kis/realtime/latest`
  - `POST /api/v1/kis/realtime/start`
  - `POST /api/v1/kis/realtime/stop`

## 3) 실제 사용한 KIS TR 코드 / Endpoint (확인된 것만)
- 거래량 순위
  - TR: `FHPST01710000`
  - Endpoint: `/uapi/domestic-stock/v1/quotations/volume-rank`
- 등락률 순위
  - TR: `FHPST01700000`
  - Endpoint: `/uapi/domestic-stock/v1/ranking/fluctuation`
- 거래대금 sort_by 대응(요청 명세 기반 TR 사용)
  - TR: `FHPST01740000`
  - Endpoint: `/uapi/domestic-stock/v1/ranking/market-cap` (로컬 레퍼런스 매핑 기준)
- 실시간 체결 구독
  - WS TR: `H0STCNT0`
  - WS URL: `ws://ops.koreainvestment.com:21000`
- 웹소켓 승인키 발급
  - REST: `POST /oauth2/Approval`

## 4) 검증 결과
- `python -c "from backend.services.kis.domestic import universe_service; print('OK')"` → `OK` (exit 0)
- `python -c "from backend.api.routes import universe, realtime; print('OK')"` → `OK` (exit 0)

## 5) 실패/불확실 항목
- `sort_by="trade_amount"`를 `FHPST01740000`에 연결했으나, 레퍼런스 CSV 기준 해당 TR endpoint는 `market-cap`으로 매핑되어 의미가 "거래대금"인지 불확실함.
- KIS 실시간 체결 payload 필드 인덱스는 문서 전체 대조 없이 범용 파서(원문+부분 필드 추출)로 구현됨.
- WebSocket 실전/모의 URL 포트 구분은 인박스 지시에 맞춰 `21000`으로 고정했음.
