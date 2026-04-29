# INBOX — Codex (Backend)
**작업**: 단타봇 API 허브 — 백엔드 구현 (Step 1~5)  
**계획서**: `docs/planning/작업계획서_단타봇_API허브_메뉴_v1.md` 반드시 먼저 읽을 것  
**완료 후**: `docs/agent-comm/OUTBOX_CODEX_trading_hub_backend.md` 에 결과 작성

---

## 구현 지시 (순서 엄수)

### Step 1: `backend/services/kis/domestic/universe_service.py` 신규 작성

KIS REST API를 호출하는 두 함수를 구현한다.

**함수 1: `get_volume_rank(market_code="J", top_n=100)`**
- KIS TR: `FHPST01710000` (주식 거래량 순위)
- KIS endpoint: `/uapi/domestic-stock/v1/quotations/volume-rank`
- 기존 `backend/services/kis/domestic/service.py`의 KIS 클라이언트 호출 패턴을 그대로 따라서 구현
- 반환: `{"items": [...], "count": N}`
  - items 각 항목: `rank`, `symbol`(종목코드), `name`(종목명), `volume`(거래량), `price`(현재가), `change_rate`(등락률)

**함수 2: `get_price_rank(sort_by="change_rate", market_code="J", top_n=100)`**
- `sort_by="change_rate"` → KIS TR `FHPST01700000` (등락률 순위)
- `sort_by="trade_amount"` → KIS TR `FHPST01740000` (거래대금 순위)
- KIS endpoint: `/uapi/domestic-stock/v1/quotations/disparity` 또는 실제 TR에 맞는 endpoint 사용
- 반환: `{"sort_by": sort_by, "items": [...], "count": N}`

⚠️ KIS 클라이언트 인스턴스 취득 방법은 기존 `service.py` 참고해서 동일 패턴 사용.  
⚠️ top_n은 최대 100으로 제한. 초과 요청 시 100으로 clamp.

---

### Step 2: `backend/api/routes/universe.py` 신규 작성

```python
# 엔드포인트 2개
GET /api/v1/kis/universe/volume-rank
  query params: market_code: str = "J", top_n: int = 100
  → universe_service.get_volume_rank() 호출
  → 표준 응답 형식: {"ok": True, "payload": {...}}

GET /api/v1/kis/universe/price-rank
  query params: sort_by: str = "change_rate", market_code: str = "J", top_n: int = 100
  → universe_service.get_price_rank() 호출
  → 표준 응답 형식: {"ok": True, "payload": {...}}
```

기존 `backend/api/routes/kis.py`의 라우터/응답 패턴을 그대로 따른다.  
prefix: `/api/v1/kis/universe`, tags: `["universe"]`

---

### Step 3: `backend/services/kis/realtime_ws.py` 신규 작성

KIS WebSocket 연결을 관리하고 체결 데이터를 캐시하는 모듈.

**요구사항:**
- `RealtimeWSManager` 클래스 (싱글턴)
- `async def start(symbols: list[str])`: KIS WebSocket 연결 시작
  - KIS WebSocket URL: `ws://ops.koreainvestment.com:21000` (모의) 또는 실전 URL
  - 구독: 실시간 체결(`H0STCNT0`) TR 코드로 symbols 구독
  - 수신 데이터를 `collections.deque(maxlen=200)`에 저장
- `async def stop()`: 연결 종료
- `def get_latest(n: int = 50) -> list`: 최신 N건 반환
- `is_connected: bool` 속성

⚠️ KIS WebSocket 인증 헤더/승인키는 기존 kis_client.py에서 취득 패턴 참고  
⚠️ websockets 라이브러리 사용 (requirements.txt에 이미 있을 것, 없으면 추가)

---

### Step 4: `backend/api/routes/realtime.py` 신규 작성

```python
GET  /api/v1/kis/realtime/status   → {"connected": bool, "cache_size": int}
GET  /api/v1/kis/realtime/latest   → query: n=50 → 최신 체결 N건
POST /api/v1/kis/realtime/start    → body: {"symbols": ["005930", ...]}  → 연결 시작
POST /api/v1/kis/realtime/stop     → 연결 종료
```

prefix: `/api/v1/kis/realtime`, tags: `["realtime"]`

---

### Step 5: `backend/main.py` 라우터 등록

기존 라우터 include 패턴을 따라서 universe, realtime 라우터를 추가 등록한다.  
기존 라우터는 절대 수정하지 않는다.

---

## 완료 조건

- 위 파일 5개 생성/수정 완료
- `python -c "from backend.services.kis.domestic import universe_service; print('OK')"` exit 0
- `python -c "from backend.api.routes import universe, realtime; print('OK')"` exit 0
- `OUTBOX_CODEX_trading_hub_backend.md`에 결과 작성:
  - 완료 파일 목록
  - 실제 사용한 KIS TR 코드/endpoint (확인된 것만)
  - 실패/불확실 항목
