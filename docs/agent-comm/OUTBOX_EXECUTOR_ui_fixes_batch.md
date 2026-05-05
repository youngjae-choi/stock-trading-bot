# OUTBOX_EXECUTOR_ui_fixes_batch

## 처리 상태

- 상태: 구현 및 지정 검증 완료
- 담당: Executor(Codex)
- 대상 파일:
  - `backend/static/console.html`
  - `backend/api/routes/orders.py`
  - `backend/services/engine/order_executor.py`
  - `backend/api/routes/account.py`

## 구현 결과

### 버그 1 — Trade History 기간 조회 수정

- `backend/services/engine/order_executor.py`
  - `get_orders_by_range(start_date, end_date, limit)` 추가
  - `trading_orders.trade_date` 기준 inclusive 범위 조회
  - `limit` 1..1000 클램프 적용

- `backend/api/routes/orders.py`
  - `GET /api/v1/orders/range` 추가
  - START / SUCCESS / FAIL 서버 로그 추가
  - 응답 형식: `{"ok": true, "payload": {"orders": [...], "count": n}}`

- `backend/static/console.html`
  - `loadAllOrders()`의 `week/month/lastmonth/all` 분기를 `/api/v1/orders/range` 호출로 변경
  - 기존 `today` 분기는 유지
  - 기간 필터 후처리 중 `week/month/lastmonth` 재필터링 블록 제거

### 버그 2 — Trading Monitor 예수금 표시 수정

- `backend/api/routes/account.py`
  - `_build_balance_payload()`의 `buyable_cash` 계산 우선순위를 `ord_psbl_cash -> dnca_tot_amt`로 변경
  - `nass_amt`는 순자산이므로 `buyable_cash` 계산에서 제외

### 버그 3 — Alert Center 메뉴 복원

- `backend/static/console.html`
  - 모바일 메뉴의 Alert Center option 노출 복원
  - 사이드바 Alert Center 버튼 노출 복원
  - Approval Queue는 숨김 유지

### 버그 4 — Data & API 화면 UI 통일

- `backend/static/console.html`
  - Rule System을 compact card grid로 변경
  - KIS REST / KIS WebSocket / LLM Router / SQLite DB / Telegram을 5개 통합 grid로 변경
  - Data Quality Guard를 compact card 2개로 변경
  - System Health를 compact card 4개로 변경
  - API 호출 로그 카드는 구조 유지
  - `natural-card` 클래스 정의 및 사용 제거

## 검증 결과

```bash
python3 -m py_compile backend/api/routes/orders.py backend/api/routes/account.py backend/services/engine/order_executor.py
# PASS: py_compile OK
```

```bash
python3 -c "from html.parser import HTMLParser; HTMLParser().feed(open('backend/static/console.html', encoding='utf-8').read()); print('HTML parse OK')"
# PASS: HTML parse OK
```

```bash
grep "data-screen=\"alerts\"" backend/static/console.html | grep -v "display:none"
# PASS: Alert Center 사이드바 버튼 노출 확인
```

```bash
grep "nass_amt" backend/api/routes/account.py | grep -v "#"
# PASS: nass_amt buyable_cash 계산 경로 제거 확인
```

```bash
grep "orders/range" backend/static/console.html | head -3
# PASS: Trade History range API 호출 확인
```

```bash
grep -c "natural-card" backend/static/console.html
# PASS: 0
```

```bash
python3 - <<'PY'
import asyncio
from backend.api.routes.orders import get_orders_range_api
result = asyncio.run(get_orders_range_api(start='2020-01-01', end='2020-01-02', limit=1))
print(result)
PY
# PASS: {'ok': True, 'payload': {'orders': [], 'count': 0}}
```

```bash
python3 - <<'PY'
from backend.api.routes.account import _build_balance_payload
payload = _build_balance_payload({
    'output1': [],
    'output2': [{'dnca_tot_amt': '1000', 'ord_psbl_cash': '700', 'nass_amt': '999999'}],
})
print({'deposit': payload['deposit'], 'buyable_cash': payload['buyable_cash'], 'available_cash': payload['available_cash']})
PY
# PASS: {'deposit': 1000, 'buyable_cash': 700, 'available_cash': 700}
```

## 확인 필요 / 제한

- 전체 FastAPI 앱 `TestClient`를 통한 `/api/v1/orders/range` 호출은 앱 초기화 과정에서 응답 없이 대기하여 라우터 함수 직접 호출로 대체했다.
- 브라우저 수동 확인 및 Playwright E2E는 이번 실행에서 수행하지 않았다.

## 완료 체크리스트

- [x] `get_orders_by_range()` 함수 추가
- [x] `GET /api/v1/orders/range` 엔드포인트 추가
- [x] `loadAllOrders()` 기간 필터 수정
- [x] `_build_balance_payload()` buyable_cash 필드 순서 수정
- [x] Alert Center 사이드바 버튼 노출 복원
- [x] Alert Center 모바일 option 노출 복원
- [x] Data & API Rule System 섹션 compact card 통일
- [x] Data & API Data Quality Guard compact card 통일
- [x] Data & API System Health compact card 통일
- [x] Data & API KIS/LLM/DB/Telegram 5개 통합 grid
- [x] py_compile OK
- [x] HTML parse OK
