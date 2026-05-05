# OUTBOX_EXECUTOR_phase5a_backend

## 역할
Executor

## 작업 결과 요약
Phase 5A 운영 안정화 백엔드 구현을 완료했다.

## 변경 파일
- `backend/services/db.py`
- `backend/services/engine/data_quality_guard.py`
- `backend/services/engine/alert_center.py`
- `backend/services/engine/human_approval.py`
- `backend/api/routes/data_quality.py`
- `backend/api/routes/alert_center.py`
- `backend/api/routes/human_approval.py`
- `backend/main.py`
- `docs/agent-comm/OUTBOX_EXECUTOR_phase5a_backend.md`

## 구현 내용

### 작업 1 — DB 테이블 추가
- `data_quality_events`
- `data_quality_snapshots`
- `system_alerts`
- 각 지시 인덱스 추가

추가 확인 사항:
- INBOX에는 `human_approval_queue`, `approval_decision_logs`가 Phase 4B에서 이미 생성됐다고 되어 있었지만 실제 `backend/services/db.py`에는 존재하지 않았다.
- 실제 활성 스키마 기준으로 Human Approval 서비스가 즉시 실패하지 않도록 아래 2개 테이블도 `CREATE TABLE IF NOT EXISTS`로 보강했다.
  - `human_approval_queue`
  - `approval_decision_logs`

### 작업 2 — Data Quality Guard 서비스
신규 파일: `backend/services/engine/data_quality_guard.py`

구현 함수:
- `record_dq_event(...)`
- `get_today_dq_status(trade_date)`
- `take_dq_snapshot(trade_date)`
- `get_latest_dq_snapshot(trade_date)`

추가 처리:
- event_type/severity 검증
- severity 우선순위 기반 worst_severity 계산
- overall_status 판단 로직 구현
- START/SUCCESS/WARN 로그 추가

### 작업 3 — Alert Center 서비스
신규 파일: `backend/services/engine/alert_center.py`

구현 함수:
- `create_alert(...)`
- `get_today_alerts(trade_date, unacknowledged_only=False)`
- `acknowledge_alert(alert_id)`
- `get_alert_summary(trade_date)`

추가 처리:
- alert_type/severity 검증
- acknowledged boolean 변환
- severity별 카운트 및 미확인 수 집계
- START/SUCCESS 로그 추가

### 작업 4 — Human Approval Queue 서비스
신규 파일: `backend/services/engine/human_approval.py`

구현 함수:
- `create_approval_request(...)`
- `list_approval_requests(status=None)`
- `approve_request(request_id, reason='')`
- `reject_request(request_id, reason='')`
- `defer_request(request_id, reason='')`

추가 처리:
- change_type/status 검증
- payload_json JSON 검증 및 compact 저장
- 승인/거부/보류 결정 로그 기록
- 없는 request_id는 `KeyError`로 라우터에서 404 처리 가능하게 구성

### 작업 5 — REST API 3세트
신규 파일:
- `backend/api/routes/data_quality.py`
- `backend/api/routes/alert_center.py`
- `backend/api/routes/human_approval.py`

등록 엔드포인트:
- `GET /api/v1/data-quality/status`
- `GET /api/v1/data-quality/snapshot`
- `POST /api/v1/data-quality/snapshot`
- `POST /api/v1/data-quality/event`
- `GET /api/v1/alerts/`
- `POST /api/v1/alerts/`
- `POST /api/v1/alerts/{alert_id}/acknowledge`
- `GET /api/v1/alerts/summary`
- `POST /api/v1/approval/`
- `GET /api/v1/approval/`
- `POST /api/v1/approval/{request_id}/approve`
- `POST /api/v1/approval/{request_id}/reject`
- `POST /api/v1/approval/{request_id}/defer`

추가 처리:
- Pydantic request body 검증
- 서비스 검증 오류는 400
- 없는 alert/request는 404
- 서버 예외는 내부 로그 후 500

### 작업 6 — main.py 라우터 등록
- `data_quality_router`
- `alert_center_router`
- `human_approval_router`

## 검증 결과

### py_compile
명령:
```bash
python3 -m py_compile \
  backend/services/db.py \
  backend/services/engine/data_quality_guard.py \
  backend/services/engine/alert_center.py \
  backend/services/engine/human_approval.py \
  backend/api/routes/data_quality.py \
  backend/api/routes/alert_center.py \
  backend/api/routes/human_approval.py \
  backend/main.py
```

결과:
- 통과

### DB 초기화 및 테이블 확인
명령:
```bash
python3 -c "from backend.services.db import initialize_database; initialize_database()"
python3 -c "
import sqlite3
conn = sqlite3.connect('data/stock_trading_bot.sqlite3')
tables = conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()
print(sorted([t[0] for t in tables]))
conn.close()
"
```

결과:
- `data_quality_events` 포함 확인
- `data_quality_snapshots` 포함 확인
- `system_alerts` 포함 확인
- 실제 누락되어 있던 `human_approval_queue`, `approval_decision_logs`도 포함 확인

### 서비스 단위 검증
임시 DB(`/tmp/phase5a_backend_test.sqlite3`)에서 다음 흐름 확인:
- DQ 이벤트 생성 → 상태 조회 → 스냅샷 생성 → 최신 스냅샷 조회
- Alert 생성 → 목록 조회 → acknowledge → summary 조회
- Approval 요청 3건 생성 → approve/reject/defer 결정

결과:
```text
dq True NORMAL 1 True
alerts 1 True 1 0
approval_create 3
approval_decisions approved rejected deferred
```

### 라우터 함수 직접 호출 검증
임시 DB(`/tmp/phase5a_route_test.sqlite3`)에서 다음 라우터 함수 직접 호출 흐름 확인:
- `create_event`, `get_status`, `create_snapshot`, `get_snapshot`
- `post_alert`, `list_alerts`, `acknowledge`, `summary`
- `create_request`, `list_requests`, `approve`, `reject`, `defer`

결과:
```text
dq_routes True DEGRADED True
alert_routes 1 True 1
approval_routes 3 approved rejected deferred
```

### FastAPI 라우터 등록 확인
명령:
```bash
python3 - <<'PY'
from backend.main import app
paths = sorted(route.path for route in app.routes if hasattr(route, 'path'))
for p in paths:
    if p.startswith('/api/v1/data-quality') or p.startswith('/api/v1/alerts') or p.startswith('/api/v1/approval'):
        print(p)
PY
```

결과:
- Phase 5A 신규 data-quality, alerts, approval 라우트 등록 확인

### E2E 확인
명령:
```bash
npm run test:e2e
```

결과:
- 실패
- 원인: `npm install --save-dev @playwright/test` 단계에서 샌드박스 네트워크 제한으로 DNS 실패
- 대표 오류: `getaddrinfo EAI_AGAIN registry.npmjs.org`

추가 명령:
```bash
npm run -s _playwright_test_internal
```

결과:
- 실패
- 원인: 샌드박스 로컬 네트워크/브라우저 실행 제한
- 대표 오류:
  - `connect EPERM 127.0.0.1:8000`
  - Chromium `sandbox_host_linux.cc:41 ... Operation not permitted`

### 빌드 검증
- `package.json`에 별도 build 스크립트가 없어 빌드 명령은 실행하지 못했다.
- Python 백엔드 파일은 `py_compile`로 문법 검증했다.

## 완료 체크리스트
- [x] 작업 1 — DB 3개 테이블
- [x] 작업 2 — data_quality_guard.py
- [x] 작업 3 — alert_center.py
- [x] 작업 4 — human_approval.py
- [x] 작업 5 — REST API 3세트
- [x] 작업 6 — main.py 라우터 등록
- [x] py_compile 전부 통과
- [x] DB 테이블 확인
- [x] 서비스 단위 검증
- [x] 라우터 함수 직접 호출 검증
- [ ] E2E 전체 통과 — 현재 Codex 샌드박스 네트워크/로컬 소켓/Chromium 권한 제한으로 실패

## 리스크 및 확인 필요
- 실제 HTTP API 호출은 로컬 바인딩 권한이 있는 개발 서버에서 재확인해야 한다.
- 기존 `backend/api/routes/alerts.py`도 `/api/v1/alerts` prefix를 사용한다. 새 `alert_center.py`는 같은 prefix 아래 `/`, `/summary`, `/{alert_id}/acknowledge`를 추가했고 기존 `/telegram/test`와 경로 충돌은 없다.
- `human_approval_queue`, `approval_decision_logs`는 문서 가정과 달리 실제 스키마에 없어 이번 작업에서 보강했다. PM/Claude가 Phase 4B 산출물 기준과 문서 정합성을 확인하는 것이 좋다.
- 기존 작업 트리에 이미 다수의 미커밋 수정/신규 파일이 있어 커밋은 수행하지 않았다. Codex는 프로젝트 규칙상 git commit 권한이 없다.
