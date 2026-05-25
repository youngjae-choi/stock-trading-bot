# OUTBOX: S9-S10 Fill 누락 수정 + 오늘 데이터 복구 결과

**날짜:** 2026-05-22  
**담당:** Codex / Backend  
**상태:** PARTIAL — 코드 수정 완료, 로컬 검증 일부 완료, KIS 외부 통신 실패로 체결 복구 미완료

---

## 1. 코드 변경 결과

### 완료

- `backend/services/scheduler.py`
  - `job_postprocess_pipeline()`에서 S9 종료 직후 S10 Review & Audit 전에 30초 대기 후 `fill_poller.poll_once()`를 1회 실행하도록 추가했다.
  - fill 폴링 이후 `run_daily_summary()`를 실행해 `daily_trade_summary`가 S10 Review 전에 생성/갱신되도록 보강했다.
  - fill 폴링 또는 Daily Summary 실패 시에도 Review & Audit은 계속 진행하도록 `WARN` 로그를 남긴다.

- `backend/api/routes/trading_monitor.py`
  - 수동 복구 엔드포인트를 추가했다.
  - 등록 URL:
    - `POST /api/v1/trading/admin/recover-fills`
    - `POST /api/v1/trading-monitor/admin/recover-fills`
  - 복구 순서:
    1. `sell` 주문명 보정
    2. `poll_once(trade_date)` 실행
    3. `run_daily_summary(trade_date)` 실행
    4. `job_review_audit()` 실행
  - 응답에 `names_updated`, `fill_result`, `daily_summary`, `s10_rerun`을 포함한다.

- `backend/main.py`
  - 복구 전용 `admin_router`를 FastAPI 앱에 등록했다.

- `backend/services/engine/order_executor.py`
  - `sell` 주문 저장 시 `name`이 비어 있으면 아래 순서로 종목명을 보정한다.
    1. `symbols` 테이블
    2. 같은 거래일의 기존 `trading_orders` 이름
    3. 최신 `trading_signals` 이름
  - `execute_sell(..., name="")` 파라미터를 추가했다.

- `backend/services/engine/eod_liquidation.py`
  - S9 청산 시 KIS 보유 종목명(`pos.name`)을 `execute_sell()`에 전달하도록 변경했다.

---

## 2. 오늘 데이터 복구 실행 결과

### 실행한 복구

- 서버 기동 시도:
  - `python3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000`
  - `python3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8001`
  - 결과: 둘 다 `could not bind on any address`로 실패했다.

- 대체 실행:
  - FastAPI 함수 `recover_fills("2026-05-22")`를 직접 호출했다.

### KIS 체결 조회 결과

- `poll_once("2026-05-22")` 실행 중 KIS 토큰 발급 실패:
  - 원인: `[Errno -3] Temporary failure in name resolution`
  - 이 Codex 샌드박스의 네트워크/DNS 제한으로 판단된다.
- 결과:
  - `filled=0`
  - `unchanged=4`
  - `sell` 체결 복구는 완료되지 못했다.

### DB 확인 결과

`trading_orders` 2026-05-22 `sell` 4건:

| symbol | name | status | qty | price | kis_order_no |
|---|---|---:|---:|---:|---|
| 006400 | 삼성SDI | submitted | 12 | 0.0 | 0000032780 |
| 009150 | 삼성전기 | submitted | 8 | 0.0 | 0000032798 |
| 034020 | 두산에너빌리티 | submitted | 90 | 0.0 | 0000032806 |
| 373220 | LG에너지솔루션 | submitted | 24 | 0.0 | 0000032822 |

`daily_trade_summary`:

| trade_date | total_orders | buy_orders | sell_orders | realized_pnl | pnl_status | pnl_source |
|---|---:|---:|---:|---:|---|---|
| 2026-05-22 | 8 | 4 | 4 | 0.0 | unverified | incomplete_orders |

`daily_review_reports`:

| trade_date | pnl_status | total_pnl | false_positive_count |
|---|---|---:|---:|
| 2026-05-22 | unverified | 0.0 | 0 |

기타:

- `fills` sell count: 0
- `false_positive_cases` count: 0

---

## 3. 검증 결과

- `python3 -m py_compile backend/services/scheduler.py backend/services/engine/order_executor.py backend/services/engine/eod_liquidation.py backend/api/routes/trading_monitor.py backend/main.py`
  - 통과
- FastAPI route 등록 확인:
  - `/api/v1/trading/admin/recover-fills`
  - `/api/v1/trading-monitor/admin/recover-fills`
- `job_review_audit()`의 False Positive 자동 생성 확인:
  - 이미 `generate_false_positives_for_date(today)` 호출 포함
  - `daily_summary.py`에도 `generate_false_positives_for_date(trade_date)` 호출 포함

---

## 4. 남은 작업 / PM 확인 필요

1. 네트워크가 가능한 실제 서버 환경에서 아래 API를 다시 실행해야 한다.

   ```bash
   curl -s -X POST "http://127.0.0.1:8000/api/v1/trading/admin/recover-fills?trade_date=2026-05-22" | python3 -m json.tool
   ```

2. 실행 후 아래 항목을 다시 확인해야 한다.

   - `trading_orders` sell 4건이 `status='filled'`, `price > 0`으로 변경되는지
   - `fills` 테이블에 sell fill 4건이 생성되는지
   - `daily_trade_summary.pnl_status='verified'`로 바뀌는지
   - `daily_review_reports.pnl_status='verified'`로 바뀌는지
   - 손실 거래가 있으면 `false_positive_cases`가 생성되는지

3. 현재 Codex 환경에서는 KIS DNS 실패로 체결 가격 복구를 완료할 수 없었다. 코드 수정은 완료됐지만 운영 데이터 복구 완료 판정은 실제 서버에서 재실행 후 가능하다.
