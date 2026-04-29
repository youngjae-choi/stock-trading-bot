# OUTBOX — Codex (Hub Backend Fix)

## 1) 완료 파일 목록
- `backend/services/kis/domestic/universe_service.py` (수정)
- `backend/services/kis/realtime_ws.py` (수정)
- `backend/services/kis/domestic/fundamental_service.py` (신규)
- `backend/api/routes/fundamental.py` (신규)
- `backend/main.py` (수정: fundamental 라우터 등록)

## 2) Fix 1 결과 — Universe `price-rank` top_n>30

### 원인 분석 결론
- **가능성 B(로직 미적용)** 아님: 기존 코드에서 `top_n>30 and market_code=="J"`일 때 `blng=["1","2"]` 분기 자체는 존재/동작.
- 실제 리스크는 **가능성 A 계열(분할 호출 실패)**: `logs/server.log`에서 KIS 랭킹/유니버스 호출이 간헐적으로 `500 EGW00201(초당 거래건수 초과)`를 반환하는 패턴이 확인됨.
- 기존 구현은 분할 호출 실패 시 **fallback(0 전체 호출) 정책이 없어** 케이스에 따라 결과 수가 줄거나 API가 실패할 수 있는 구조였음.

### 수정 내용
- `top_n<=30`: `FID_BLNG_CLS_CODE=0` 단일 호출 유지.
- `top_n>30 and market_code=J`: `blng=1`, `blng=2`를 `asyncio.gather`로 **병렬 호출**.
- 분할 호출 중 하나라도 실패하면:
  - 실패 건을 `logger.error`로 명시 기록
  - `FID_BLNG_CLS_CODE=0` 단일 호출로 **fallback**
- 병합 시 중복 심볼 제거 + 기존 정렬/슬라이싱 로직 유지.

## 3) Fix 2 결과 — Realtime WebSocket 체결 미수신

### 확인된 문제점
- 승인키 발급(`POST /oauth2/Approval`)과 구독 메시지 기본 포맷은 구현되어 있었음.
- 다만 다음 누락/취약점이 있었음:
  - KIS 앱 레벨 `PINGPONG` 수신 시 **응답 전송 처리 없음**
  - 모의환경(`openapivts`)에서도 WS URL이 `21000`으로 고정되어 있음
  - 구독 전송/제어 메시지 로깅이 부족해 운영 시 원인 추적이 어려움

### 수정 내용
- `PINGPONG` 메시지 수신 시 동일 raw payload를 즉시 `ws.send(raw)`로 회신하도록 추가.
- 구독 전송 성공 로그(`tr_id=H0STCNT0`, symbol) 추가.
- 제어 메시지(`header.tr_id`) 파싱/로그 추가.
- WS URL 분기 수정:
  - demo(`openapivts`) -> `ws://ops.koreainvestment.com:31000`
  - real -> `ws://ops.koreainvestment.com:21000`
- 수신 메시지는 기존처럼 캐시에 적재되며, PINGPONG 처리 여부(`pong_sent`)도 캐시에 남김.

## 4) Fix 3 결과 — 재무 데이터 엔드포인트 추가

### 신규 구현
- 서비스: `backend/services/kis/domestic/fundamental_service.py`
  - 경로: `/uapi/domestic-stock/v1/finance/financial-statements`
  - 파라미터: `fno_bstp_cls_code=0`, `qry_tp=0`, `pdno=symbol`
  - TR 우선순위: `FHKST66430300` -> 실패 시 `HHKDB669300C0` 재시도
  - 두 TR 모두 실패 시 `{"ok": false, "symbol": ..., "error": "재무 API 미지원"}` 반환(HTTP 200용 payload)
- 라우터: `backend/api/routes/fundamental.py`
  - `GET /api/v1/kis/fundamental/{symbol}`
  - config 검증 + 시작/성공/경고/실패 로그 추가
- 등록: `backend/main.py`에 `fundamental_router` include

## 5) 완료 조건 검증
- `python -m py_compile backend/services/kis/domestic/universe_service.py` -> **exit 0**
- `python -m py_compile backend/services/kis/realtime_ws.py` -> **exit 0**
- `python -c "from backend.api.routes import fundamental; print('OK')"` -> **OK / exit 0**

추가 확인:
- `python -m py_compile backend/services/kis/domestic/fundamental_service.py` -> exit 0
- `python -m py_compile backend/api/routes/fundamental.py` -> exit 0
- `python -m py_compile backend/main.py` -> exit 0

## 6) 잔여 리스크 / 보류
- 본 세션 샌드박스에서 `127.0.0.1:8000/8501` 직접 curl 연결이 실패하여(연결 거부) 런타임 헬스체크는 **이 환경에서 확정 불가**.
- 실거래/모의 계정 환경에서 `/api/v1/kis/realtime/start` 후 `latest`에 `H0STCNT0` 프레임 유입 여부를 최종 확인 필요.
- 재무 TR은 계정/상품/환경별로 미지원 가능성이 있어, 이 경우 의도대로 200 + `재무 API 미지원`으로 응답함.
