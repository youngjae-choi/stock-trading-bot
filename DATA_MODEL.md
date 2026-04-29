# DATA_MODEL.md — 데이터 모델 단일 소스

AI 에이전트가 필드명·타입을 추론하지 않고 이 파일을 먼저 참조한다.
여기에 없는 필드를 임의로 만들지 않는다. 변경은 이 파일 먼저 수정 후 코드 반영.

---

## 1. DB 스키마

<!-- 프로젝트별로 테이블 스키마를 기술한다. 아래는 채우기 예시. -->

```sql
users (
  id            UUID          PRIMARY KEY,
  email         VARCHAR       NOT NULL UNIQUE,
  name          VARCHAR       NOT NULL,
  role          VARCHAR       NOT NULL DEFAULT 'member',  -- 'admin' | 'member'
  created_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW()
)

items (
  id            UUID          PRIMARY KEY,
  owner_id      UUID          NOT NULL REFERENCES users(id),
  title         VARCHAR       NOT NULL,
  status        VARCHAR       NOT NULL DEFAULT 'active',  -- 'active' | 'archived'
  created_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW()
)
```

---

## 2. 도메인 타입 (TypeScript)

<!-- 프로젝트별로 TypeScript 타입을 기술한다. 아래는 채우기 예시. -->

```ts
type UserRole = "admin" | "member";

type User = {
  id: string;
  email: string;
  name: string;
  role: UserRole;
  createdAt: Date;
  updatedAt: Date;
};

type ItemStatus = "active" | "archived";

type Item = {
  id: string;
  ownerId: string;
  title: string;
  status: ItemStatus;
  createdAt: Date;
};
```

---

## 3. API 응답 공통 봉투

```ts
type ApiResponse<T> =
  | { ok: true;  featureKey: string; version: string; data: T }
  | { ok: false; featureKey: string; version: string; code: string; message: string };
```

**성공 예시:**
```json
{ "ok": true, "featureKey": "item.create", "version": "1.0.0", "data": { "id": "...", "title": "..." } }
```

**실패 예시:**
```json
{ "ok": false, "featureKey": "item.create", "version": "1.0.0", "code": "VALIDATION_ERROR", "message": "제목은 필수 항목입니다." }
```

---

## 4. 에러 코드 목록

<!-- 프로젝트별로 에러 코드를 기술한다. 아래는 채우기 예시. -->

| 코드 | HTTP | 의미 |
|------|------|------|
| `UNAUTHORIZED` | 401 | 인증 없음 |
| `FORBIDDEN` | 403 | 권한 부족 |
| `NOT_FOUND` | 404 | 대상 없음 |
| `VALIDATION_ERROR` | 400 | 입력값 오류 |
| `CONFLICT` | 409 | 상태 충돌 (이미 처리됨 등) |
| `RUNTIME_ERROR` | 500 | 서버 내부 오류 |

---

## 5. 네이밍 규칙

| 영역 | 규칙 | 예시 |
|------|------|------|
| DB 컬럼 | `snake_case` | `created_at`, `owner_id` |
| TypeScript | `camelCase` | `createdAt`, `ownerId` |
| API 요청/응답 | `camelCase` | `featureKey`, `itemId` |
| 에러 코드 | `UPPER_SNAKE_CASE` | `NOT_FOUND`, `VALIDATION_ERROR` |

---

## 6. 주요 비즈니스 규칙

<!-- 프로젝트별로 비즈니스 규칙을 기술한다. 아래는 채우기 예시. -->

- `email`: 고유 식별자. 변경 불가.
- `role`: 관리자만 다른 사용자의 role을 변경할 수 있다.
- `status`: archived 상태의 항목은 수정 불가. 목록 조회 시 기본 필터에서 제외.
