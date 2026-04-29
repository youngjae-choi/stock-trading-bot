# API_CONTRACT.md — API 계약 단일 소스

REST API 및 실시간 메시지 포맷을 한 곳에 정의한다.
AI 에이전트가 API를 호출하거나 메시지를 설계할 때 이 파일을 먼저 참조한다.

연계 파일: `DATA_MODEL.md` (스키마/타입)

---

## 1. REST API 전체 목록

<!-- 프로젝트별로 아래 표를 채운다. 예시 행을 참고해 작성. -->

| 메서드 | 경로 | 인증 | 역할 | 설명 |
|--------|------|------|------|------|
| `GET`  | `/api/v1/items` | JWT | 사용자 | 항목 목록 조회 |
| `POST` | `/api/v1/items` | JWT | 사용자 | 항목 생성 |
| `GET`  | `/api/v1/items/[id]` | JWT | 사용자 | 항목 상세 조회 |
| `PATCH`| `/api/v1/items/[id]` | JWT | 사용자 | 항목 수정 |
| `DELETE`| `/api/v1/items/[id]` | JWT | 관리자 | 항목 삭제 |

---

## 2. 엔드포인트 상세

<!-- 각 엔드포인트마다 아래 형식으로 기술한다. -->

### GET `/api/v1/items` (예시)
항목 목록 조회.

**쿼리 파라미터:**
```
status   string (optional)  "active" | "archived" | "all" (기본 all)
keyword  string (optional)  검색어
page     number (optional)  페이지 번호 (기본 1)
```

**성공 응답 `200`:**
```json
{
  "ok": true,
  "featureKey": "item.list",
  "version": "1.0.0",
  "data": { "items": [], "total": 42, "page": 1 }
}
```

### POST `/api/v1/items` (예시)
항목 생성.

**요청 Body:**
```json
{ "name": "항목명", "description": "설명" }
```

**성공 응답 `201`:**
```json
{ "ok": true, "featureKey": "item.create", "version": "1.0.0", "data": { "id": "uuid", "name": "항목명" } }
```

**실패 응답 `400`:**
```json
{ "ok": false, "featureKey": "item.create", "version": "1.0.0", "code": "VALIDATION_ERROR", "message": "이름은 필수 항목입니다." }
```

---

## 3. 실시간 메시지 포맷

<!-- 프로젝트에 WebSocket/DataChannel 등이 있으면 아래 형식으로 기술한다. -->

```ts
// 채팅 메시지 예시
{ type: "CHAT", sender: string, text: string, timestamp: string }

// 상태 동기화 예시
{ type: "STATE_SYNC", payload: Record<string, unknown> }
```

---

## 4. 공통 규칙

### 인증
<!-- 프로젝트 인증 방식을 기술한다 -->
- 예: JWT Bearer Token — `Authorization: Bearer <token>`
- 예: 쿠키 기반 세션 — 브라우저 자동 포함

### 토큰/민감정보 처리
- JWT, 토큰, 비밀번호, API 키는 로그에 절대 출력 금지

### 응답 공통 봉투
모든 API 응답은 `DATA_MODEL.md`에 정의된 봉투 형식을 따른다.

### 로그 접두사 패턴
```
[FeatureName][INFO] START/SUCCESS/FAILED — message {tags}
```
