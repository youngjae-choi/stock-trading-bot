# INBOX_EXECUTOR_ops_refactor_data_support

## 역할
너는 Executor(Codex)다. 1차 운영 화면 개편에 필요한 백엔드 데이터 보강을 수행하라.
완료 후 `docs/agent-comm/OUTBOX_EXECUTOR_ops_refactor_data_support.md`에 결과를 작성하라.

## 공통 규칙
- 작업 전 `ONBOARDING.md`, `AGENTS.md`, `CODEX.md`, `docs/planning/today_control_trading_monitor_refactor_plan_20260505.md`를 확인한다.
- git commit 금지.
- 프론트 파일 `backend/static/console.html`은 수정하지 않는다. Gemini가 담당한다.
- 기존 사용자 변경을 되돌리지 않는다.

## 목적
Today Control / Trading Monitor / Trade History 화면이 실제 데이터로 자연스럽게 표시되도록 API 응답을 보강한다.

## 작업 1 — 최근 주문 API 추가

### 대상
- `backend/services/engine/order_executor.py`
- `backend/api/routes/orders.py`

### 요구사항
1. `order_executor.py`에 최근 주문 조회 함수 추가:
   - 함수명 예: `get_recent_orders(limit: int = 5)`
   - `trading_orders` 테이블에서 `created_at DESC` 기준 조회
   - `limit`은 최소 1, 최대 100 정도로 방어
   - 기존 `_ensure_orders_table()` 사용
   - 반환은 기존 `get_today_orders()`와 같은 dict list

2. `orders.py`에 endpoint 추가:
   - `GET /api/v1/orders/recent?limit=5`
   - 응답:
     ```json
     {
       "ok": true,
       "payload": {
         "orders": [],
         "count": 0,
         "limit": 5
       }
     }
     ```
   - START/SUCCESS/FAIL 로그 추가

## 작업 2 — 계좌 payload 보강

### 대상
- `backend/api/routes/account.py`

### 요구사항
1. `_build_balance_payload()`에 `buyable_cash` 또는 `available_cash` 성격의 필드를 추가한다.
2. KIS `output2`에서 매수가능금액으로 쓰이는 후보 필드를 안전하게 탐색한다.
   - 실제 필드명이 확실하지 않으면 여러 후보를 순서대로 fallback:
     - `nass_amt`
     - `ord_psbl_cash`
     - `dnca_tot_amt`
   - 최종 fallback은 현재 `deposit`
3. 기존 필드 `deposit`, `total_eval`, `purchase_total`, `pnl_total`, `positions`는 유지한다.
4. positions 항목에 매수금액 표시용 필드 추가:
   - `purchase_amount`: `avg_price * qty` fallback
   - KIS 원본에 평가/매입금액 필드가 있으면 그 값을 우선 사용하되, 불확실하면 fallback 계산만 사용해도 된다.

## 작업 3 — Trading Monitor positions 보강

### 대상
- `backend/api/routes/trading_monitor.py`

### 요구사항
1. `/api/v1/trading-monitor/positions` 응답의 각 position에 `purchase_amount` 추가.
   - `entry_price * qty` 기준 fallback
2. 가격/금액 필드는 숫자로 유지하고 프론트가 표시 포맷을 결정하게 한다.
3. 기존 응답 구조는 하위 호환 유지.

## 작업 4 — 오늘 적용 정책 자연어를 위한 payload 보강

### 대상
- `backend/api/routes/trading_monitor.py`

### 요구사항
1. 신규 endpoint 추가:
   - `GET /api/v1/trading-monitor/policy-summary`
2. 오늘의 시장톤, 스크리닝 entry_rules, daily plan overrides/status를 모아서 자연어 표시용 payload 반환.
3. 응답 예:
   ```json
   {
     "ok": true,
     "payload": {
       "trade_date": "YYYY-MM-DD",
       "market_tone": {
         "tone": "mixed",
         "confidence": 0.55,
         "summary": "...",
         "cash_usage_hint": "보수적 현금 사용 권장"
       },
       "entry_rules": {
         "min_ai_confidence": 0.6,
         "min_price_change_pct": 0.5,
         "max_price_change_pct": 8.0
       },
       "daily_plan": {
         "id": "...",
         "status": "active",
         "trading_intensity": "...",
         "new_entry_allowed": true,
         "buy_condition_text": "...",
         "sell_condition_text": "...",
         "cash_usage_text": "..."
       }
     }
   }
   ```
4. DB 테이블/컬럼이 없거나 해당 일자 데이터가 없으면 500이 아니라 `ok: true`와 빈/대체 문구 반환.
5. 자연어 문구는 PM이 읽기 쉽게 한국어로 작성:
   - 매수 조건: AI confidence, 등락률 범위, 신규 진입 허용 여부
   - 매도 조건: 손절/트레일링/당일 청산 시간 중심
   - 현금 사용: 시장톤 confidence, trading_intensity, 신규진입 허용 여부 기반
6. Settings 값 자체가 아니라 오늘 AI 산출물(`market_tone_results`, `hybrid_screening_results`, `daily_trading_plans`)을 우선 사용한다.
   - 단 데이터가 없을 때만 보수적 fallback 문구 사용.

## 검증
아래를 실행하고 결과 기록:
```bash
.venv/bin/python -m py_compile backend/api/routes/orders.py backend/api/routes/account.py backend/api/routes/trading_monitor.py backend/services/engine/order_executor.py
```

서버가 떠 있으면 인증 쿠키로 아래 API를 확인:
```bash
GET /api/v1/orders/recent?limit=5
GET /api/v1/account/balance
GET /api/v1/trading-monitor/positions
GET /api/v1/trading-monitor/policy-summary
```

## 완료 체크리스트
- [ ] 최근 주문 API 추가
- [ ] 계좌 `buyable_cash`/`purchase_amount` 보강
- [ ] Trading Monitor position `purchase_amount` 보강
- [ ] policy-summary API 추가
- [ ] py_compile 통과
- [ ] 가능한 API 호출 검증 기록
