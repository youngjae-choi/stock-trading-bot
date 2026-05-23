# API_CONTRACT.md — API 계약 단일 소스

REST API 및 실시간 메시지 포맷을 한 곳에 정의한다.
AI 에이전트가 API를 호출하거나 메시지를 설계할 때 이 파일을 먼저 참조한다.

연계 파일: `DATA_MODEL.md` (스키마/타입)

---

## 1. REST API 전체 목록

| 메서드 | 경로 | 인증 | 역할 | 설명 |
|--------|------|------|------|------|
| `GET` | `/health` | 없음 | 시스템 | 서버/KIS/DB 상태 조회 |
| `GET` | `/` | 없음 | 브라우저 | 콘솔 HTML 제공. 미로그인 상태는 로그인 화면 표시 |
| `GET` | `/console` | 없음 | 브라우저 | 콘솔 HTML 제공. 미로그인 상태는 로그인 화면 표시 |
| `POST` | `/api/v1/auth/login` | 없음 | 관리자 | 로그인 후 HTTP-only 세션 쿠키 발급 |
| `GET` | `/api/v1/auth/me` | 세션 쿠키 | 관리자 | 현재 로그인 사용자 확인 |
| `POST` | `/api/v1/auth/logout` | 세션 쿠키 | 관리자 | 세션 삭제 및 쿠키 제거 |
| `GET` | `/api/v1/bot/overview` | 세션 쿠키 | 관리자 | 운영 개요 조회 |
| `GET` | `/api/v1/bot/rulepack/today` | 세션 쿠키 | 관리자 | 당일 RulePack 조회 |
| `GET` | `/api/v1/bot/data-health` | 세션 쿠키 | 관리자 | 데이터/연결 상태 조회 |
| `POST` | `/api/v1/bot/control/halt` | 세션 쿠키 | 관리자 | 긴급정지 실행 |
| `GET` | `/api/v1/bot/api-logs` | 세션 쿠키 | 관리자 | API 호출 감사 로그 조회 |
| `GET` | `/api/v1/settings` | 세션 쿠키 | 관리자 | 시스템 설정값 목록 조회 |
| `PUT` | `/api/v1/settings/{key}` | 세션 쿠키 | 관리자 | 시스템 설정값 저장 |
| `GET` | `/api/v1/trading-data/orders` | 세션 쿠키 | 관리자 | 저장된 주문 데이터 조회 |
| `POST` | `/api/v1/trading-data/orders` | 세션 쿠키 | 관리자 | 주문 데이터 저장 |

---

## 2. 엔드포인트 상세

### POST `/api/v1/auth/login`

**요청 Body:**
```json
{ "username": "admin", "password": "환경변수 APP_ADMIN_PASSWORD 값" }
```

**성공 응답 `200`:**
```json
{
  "ok": true,
  "source": "backend",
  "live": false,
  "payload": { "user": { "username": "admin", "role": "admin" } }
}
```

**실패 응답 `401`:**
```json
{ "detail": "INVALID_CREDENTIALS" }
```

### GET `/api/v1/settings`

시스템 설정값 목록 조회.

**성공 응답 `200`:**
```json
{
  "ok": true,
  "source": "backend",
  "live": false,
  "payload": {
    "items": [
      {
        "key": "risk.daily_loss_limit_percent",
        "value": -2.0,
        "value_type": "number",
        "description": "일일 손실한도(%)",
        "updated_at": "2026-04-29T00:00:00+00:00",
        "updated_by": "system"
      }
    ]
  }
}
```

### PUT `/api/v1/settings/{key}`

**요청 Body:**
```json
{ "value": 5, "value_type": "number", "description": "최대 보유 종목" }
```

### POST `/api/v1/trading-data/orders`

주문 요청 데이터를 저장한다. 실제 KIS 주문과 별개로 분석 가능한 저장 구조를 먼저 제공한다.

**요청 Body:**
```json
{
  "symbol": "005930",
  "side": "buy",
  "quantity": 10,
  "order_type": "market",
  "status": "created",
  "request": { "source": "manual-smoke" }
}
```

**성공 응답 `200`:**
```json
{
  "ok": true,
  "source": "backend",
  "live": false,
  "payload": {
    "id": "uuid",
    "symbol": "005930",
    "side": "buy",
    "quantity": 10,
    "status": "created"
  }
}
```

---

## 3. 인증

- 콘솔 인증은 DB-backed session cookie 방식이다.
- 쿠키 이름: `kairos_session`
- 쿠키에는 opaque session id만 저장한다.
- 비밀번호는 `PBKDF2-SHA256` 해시로만 DB에 저장한다.
- 첫 관리자 계정은 DB `users` 테이블이 비어 있고 `.env`에 `APP_ADMIN_PASSWORD`가 있을 때 자동 생성한다.

---

## 4. 토큰/민감정보 처리

- JWT, 세션, 비밀번호, API 키는 로그에 절대 출력 금지.
- `.env`와 SQLite DB 파일은 Git 커밋 금지.
- 클라이언트 코드에 KIS API 키 하드코딩 금지.

---

## 5. 응답 공통 봉투

기존 FastAPI MVP 호환성을 유지한다.

```ts
type ApiResponse<T> =
  | { ok: true; source: "backend" | "mock"; live: boolean; payload: T }
  | { ok: false; source: "backend" | "mock"; live: boolean; error: string };
```
