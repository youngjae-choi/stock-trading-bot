# DATA_MODEL.md — 데이터 모델 단일 소스

AI 에이전트가 필드명·타입을 추론하지 않고 이 파일을 먼저 참조한다.
여기에 없는 필드를 임의로 만들지 않는다. 변경은 이 파일 먼저 수정 후 코드 반영.

---

## 1. DB 스키마

MVP 기본 DB는 로컬 `SQLite`이며, 운영 확장 시 PostgreSQL로 이전하기 쉽도록 `snake_case`, 명확한 PK/FK, ISO timestamp를 사용한다.

```sql
users (
  id             TEXT PRIMARY KEY,
  username       TEXT NOT NULL UNIQUE,
  password_hash  TEXT NOT NULL,
  role           TEXT NOT NULL DEFAULT 'admin',
  is_active      INTEGER NOT NULL DEFAULT 1,
  created_at     TEXT NOT NULL,
  updated_at     TEXT NOT NULL
)

sessions (
  id             TEXT PRIMARY KEY,
  user_id        TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at     TEXT NOT NULL,
  expires_at     TEXT NOT NULL,
  last_seen_at   TEXT NOT NULL
)

system_settings (
  key            TEXT PRIMARY KEY,
  value_json     TEXT NOT NULL,
  value_type     TEXT NOT NULL DEFAULT 'json',
  description    TEXT NOT NULL DEFAULT '',
  updated_at     TEXT NOT NULL,
  updated_by     TEXT NOT NULL DEFAULT 'system'
)

symbols (
  symbol         TEXT PRIMARY KEY,
  market         TEXT NOT NULL DEFAULT '',
  name           TEXT NOT NULL DEFAULT '',
  sector         TEXT NOT NULL DEFAULT '',
  is_active      INTEGER NOT NULL DEFAULT 1,
  metadata_json  TEXT NOT NULL DEFAULT '{}',
  updated_at     TEXT NOT NULL
)

strategy_runs (
  id             TEXT PRIMARY KEY,
  strategy_key   TEXT NOT NULL,
  rulepack_id    TEXT NOT NULL DEFAULT '',
  mode           TEXT NOT NULL DEFAULT 'monitor',
  status         TEXT NOT NULL DEFAULT 'started',
  started_at     TEXT NOT NULL,
  finished_at    TEXT,
  input_json     TEXT NOT NULL DEFAULT '{}',
  result_json    TEXT NOT NULL DEFAULT '{}',
  note           TEXT NOT NULL DEFAULT ''
)

signals (
  id               TEXT PRIMARY KEY,
  strategy_run_id  TEXT REFERENCES strategy_runs(id) ON DELETE SET NULL,
  symbol           TEXT NOT NULL,
  side             TEXT NOT NULL,
  signal_type      TEXT NOT NULL DEFAULT 'entry',
  confidence       REAL,
  price            REAL,
  reason_json      TEXT NOT NULL DEFAULT '{}',
  created_at       TEXT NOT NULL
)

orders (
  id               TEXT PRIMARY KEY,
  strategy_run_id  TEXT REFERENCES strategy_runs(id) ON DELETE SET NULL,
  signal_id        TEXT REFERENCES signals(id) ON DELETE SET NULL,
  broker_order_id  TEXT NOT NULL DEFAULT '',
  symbol           TEXT NOT NULL,
  side             TEXT NOT NULL,
  order_type       TEXT NOT NULL DEFAULT 'market',
  quantity         REAL NOT NULL,
  limit_price      REAL,
  status           TEXT NOT NULL DEFAULT 'created',
  requested_at     TEXT NOT NULL,
  updated_at       TEXT NOT NULL,
  request_json     TEXT NOT NULL DEFAULT '{}',
  response_json    TEXT NOT NULL DEFAULT '{}'
)

fills (
  id              TEXT PRIMARY KEY,
  order_id        TEXT REFERENCES orders(id) ON DELETE SET NULL,
  broker_fill_id  TEXT NOT NULL DEFAULT '',
  symbol          TEXT NOT NULL,
  side            TEXT NOT NULL,
  quantity        REAL NOT NULL,
  price           REAL NOT NULL,
  fee             REAL NOT NULL DEFAULT 0,
  tax             REAL NOT NULL DEFAULT 0,
  filled_at       TEXT NOT NULL,
  raw_json        TEXT NOT NULL DEFAULT '{}'
)

positions (
  id              TEXT PRIMARY KEY,
  symbol          TEXT NOT NULL,
  quantity        REAL NOT NULL,
  avg_price       REAL NOT NULL,
  market_price    REAL,
  realized_pnl    REAL NOT NULL DEFAULT 0,
  unrealized_pnl  REAL NOT NULL DEFAULT 0,
  source          TEXT NOT NULL DEFAULT 'system',
  captured_at     TEXT NOT NULL,
  raw_json        TEXT NOT NULL DEFAULT '{}'
)

account_snapshots (
  id             TEXT PRIMARY KEY,
  cash           REAL,
  equity         REAL,
  buying_power   REAL,
  day_pnl        REAL,
  total_pnl      REAL,
  captured_at    TEXT NOT NULL,
  raw_json       TEXT NOT NULL DEFAULT '{}'
)

market_snapshots (
  id             TEXT PRIMARY KEY,
  symbol         TEXT NOT NULL,
  price          REAL,
  volume         REAL,
  change_rate    REAL,
  source         TEXT NOT NULL DEFAULT 'kis',
  captured_at    TEXT NOT NULL,
  raw_json       TEXT NOT NULL DEFAULT '{}'
)

audit_events (
  id             TEXT PRIMARY KEY,
  event_type     TEXT NOT NULL,
  actor          TEXT NOT NULL DEFAULT 'system',
  severity       TEXT NOT NULL DEFAULT 'info',
  message        TEXT NOT NULL,
  metadata_json  TEXT NOT NULL DEFAULT '{}',
  created_at     TEXT NOT NULL
)
```

---

## 2. 도메인 타입

```ts
type UserRole = "admin" | "member";
type TradeSide = "buy" | "sell";
type OrderStatus = "created" | "sent" | "partial" | "filled" | "cancelled" | "rejected";

type SystemSetting = {
  key: string;
  value: unknown;
  valueType: "string" | "number" | "boolean" | "json";
  description: string;
  updatedAt: string;
  updatedBy: string;
};

type OrderRecord = {
  id: string;
  strategyRunId?: string;
  signalId?: string;
  brokerOrderId?: string;
  symbol: string;
  side: TradeSide;
  orderType: string;
  quantity: number;
  limitPrice?: number;
  status: OrderStatus;
  requestedAt: string;
  updatedAt: string;
};
```

---

## 3. API 응답 공통 봉투

현재 FastAPI MVP는 기존 응답 호환성을 위해 아래 형태를 사용한다.

```ts
type ApiResponse<T> =
  | { ok: true; source: "backend" | "mock"; live: boolean; payload: T }
  | { ok: false; source: "backend" | "mock"; live: boolean; error: string };
```

---

## 4. 에러 코드 목록

| 코드 | HTTP | 의미 |
|------|------|------|
| `LOGIN_REQUIRED` | 401 | 로그인 세션 없음 |
| `INVALID_CREDENTIALS` | 401 | 아이디/비밀번호 오류 |
| `FORBIDDEN` | 403 | 권한 부족 |
| `NOT_FOUND` | 404 | 대상 없음 |
| `VALIDATION_ERROR` | 400 | 입력값 오류 |
| `CONFLICT` | 409 | 상태 충돌 |
| `RUNTIME_ERROR` | 500 | 서버 내부 오류 |

---

## 5. 네이밍 규칙

| 영역 | 규칙 | 예시 |
|------|------|------|
| DB 컬럼 | `snake_case` | `created_at`, `strategy_run_id` |
| JavaScript | `camelCase` | `createdAt`, `strategyRunId` |
| API 요청/응답 | 기존 FastAPI 호환으로 `snake_case` 유지 | `strategy_run_id` |
| 에러 코드 | `UPPER_SNAKE_CASE` | `LOGIN_REQUIRED` |

---

## 6. 주요 비즈니스 규칙

- 비밀번호는 평문 저장 금지. `PBKDF2-SHA256` 해시만 저장한다.
- 세션은 서버 DB에 저장하고 쿠키에는 opaque session id만 저장한다.
- `orders`는 주문 요청, `fills`는 실제 체결을 분리한다. 부분 체결 분석을 위해 1:N 관계를 유지한다.
- `positions`, `account_snapshots`, `market_snapshots`는 시점 스냅샷이다. 덮어쓰지 않고 시간축 분석을 위해 누적 저장한다.
- `strategy_runs` → `signals` → `orders` → `fills` 순서로 추적 가능해야 한다.
