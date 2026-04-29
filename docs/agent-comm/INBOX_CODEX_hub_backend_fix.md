# INBOX — Codex (Backend Fix)
**완료 후**: `docs/agent-comm/OUTBOX_CODEX_hub_backend_fix.md` 작성

---

## Fix 1: Universe price_rank top_n>30 동작 안 함

### 현상
`GET /api/v1/kis/universe/price-rank?sort_by=change_rate&market_code=J&top_n=40` → count=30만 반환

### 파일
`backend/services/kis/domestic/universe_service.py`

### 원인 분석 지시
`get_price_rank` 함수에서 `limit > 30 and market_code == "J"`이면 `blng_codes = ["1", "2"]`로 코스피+코스닥 개별 호출 후 병합하도록 설계됨.
그런데 실제로 top_n=40 요청 시 30건만 반환됨.

아래 두 가지 가능성 중 실제 원인을 server.log(`logs/server.log`)를 읽거나 코드를 분석해서 파악하고 수정하라:

**가능성 A**: fluctuation 엔드포인트에서 `FID_BLNG_CLS_CODE=1` (코스피) 또는 `=2` (코스닥) 호출 시 KIS가 에러 반환 → 한 콜만 성공해서 30건
**가능성 B**: 코드 로직 오류로 blng_codes가 ["1","2"]로 변경되지 않음

### 수정 방향
- 에러 발생 시 silently skip 하지 말고 에러 로그 남기기
- 코스피/코스닥 개별 호출이 실패하면 fallback으로 `FID_BLNG_CLS_CODE=0` (전체) 단일 호출 유지
- top_n≤30이면 blng=0 단일 호출, top_n>30이면 blng=1+blng=2 병렬 호출 후 병합

---

## Fix 2: WebSocket 실제 체결 구독 안 됨

### 현상
`/api/v1/kis/realtime/latest` → PINGPONG 메시지만 수신, H0STCNT0 체결 데이터 없음

### 파일
`backend/services/kis/realtime_ws.py`

### 지시
1. `logs/server.log` 또는 코드를 읽어서 WebSocket 구독 요청 전송 방식 확인
2. KIS WebSocket 구독 메시지 형식:
```json
{
  "header": {
    "approval_key": "발급받은_웹소켓_승인키",
    "custtype": "P",
    "tr_type": "1",
    "content-type": "utf-8"
  },
  "body": {
    "input": {
      "tr_id": "H0STCNT0",
      "tr_key": "005930"
    }
  }
}
```
3. WebSocket 승인키 발급: `POST /oauth2/Approval` (REST) → `approval_key` 반환
4. 현재 구현에서 승인키 발급 및 구독 메시지 전송이 올바른지 확인하고 수정
5. PINGPONG 응답은 pong으로 응답해야 연결 유지됨 — 현재 구현 확인
6. 수정 후 재연결 시 H0STCNT0 이벤트가 캐시에 저장되어야 함

---

## Fix 3: 재무 데이터 엔드포인트 추가

### 파일 신규
`backend/services/kis/domestic/fundamental_service.py`
`backend/api/routes/fundamental.py`

### 엔드포인트
`GET /api/v1/kis/fundamental/{symbol}`

### KIS TR
- TR ID: `FHKST66430300`
- Path: `/uapi/domestic-stock/v1/finance/financial-statements`
- 주요 params:
  - `fno_bstp_cls_code`: "0" (전체)
  - `qry_tp`: "0"
  - `pdno`: symbol

또는 TR ID `HHKDB669300C0` 사용 가능.
**실제 KIS API 스펙을 backend/services/kis/ 기존 코드 패턴 참고해서 구현**.
응답이 안 되면 `{"ok": false, "error": "재무 API 미지원"}` 반환 (502 금지, 200으로 처리).

### main.py 등록
기존 라우터 패턴 따라 fundamental 라우터 등록.

---

## 완료 조건
- `python -m py_compile backend/services/kis/domestic/universe_service.py` exit 0
- `python -m py_compile backend/services/kis/realtime_ws.py` exit 0
- `python -c "from backend.api.routes import fundamental; print('OK')"` exit 0
- OUTBOX에 수정 파일 목록 + 각 수정 내용 요약 작성
