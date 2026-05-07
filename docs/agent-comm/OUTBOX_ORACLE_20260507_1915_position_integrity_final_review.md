# OUTBOX_ORACLE - 2026-05-07 19:15 KST - Position Integrity 최종 리뷰

## 담당

- Oracle / Codex CLI

## 준수 사항

- 코드/설정 파일 수정 안 함.
- git commit 실행 안 함.
- 매수/매도/청산/주문 API 호출 안 함.
- `/api/v1/orders/*` POST, `/api/v1/kis/order/*`, `/api/v1/decision/activate` 호출 안 함.
- 실제 S1~S11 실행 안 함.
- 외부 LLM/KIS 호출 안 함.
- 단, 요청된 결과 보고 파일만 작성함.

## Findings

### P1/P2 배포 차단 이슈 없음

- 이전 P1: `submitted` buy가 자동 청산/복원 대상에 포함되던 문제는 닫힘.
  - `backend/services/engine/position_integrity.py:205`에서 submitted buy를 `pending_buy_qty/count`로 분리하고 포지션 수량에 더하지 않는다.
  - `backend/services/engine/position_integrity.py:217`의 DB fallback 수량 계산은 `filled` 또는 fill-backed `partial_fill`만 사용한다.
  - `backend/services/engine/position_integrity.py:408`의 `load_db_open_positions()`는 submitted-only buy를 open position으로 반환하지 않는다.
  - `backend/services/engine/decision_engine.py:398`의 복원 경로도 `should_restore=False`면 스킵한다.

- 이전 P1: 오늘 주문과 무관한 fills 때문에 Review PnL이 `verified`가 되던 문제는 닫힘.
  - `backend/services/engine/position_integrity.py:94`가 supplied `trading_orders.id` 목록으로 fills를 제한한다.
  - `backend/services/engine/position_integrity.py:576`에서 현재 trade_date 주문만 조회하고, `backend/services/engine/position_integrity.py:613`부터 `filled/partial_fill` 주문별 fill 누락/수량 불일치를 검사한다.
  - temp sqlite smoke에서 오늘 filled 주문에 fill이 없고 전일 fill만 있는 경우 `pnl_status=unverified`, `pnl_source=fills_incomplete`로 확인했다.

- 이전 P2: net negative / duplicate sell / sell qty exceeds buy qty anomaly 노출 부족은 닫힘.
  - `backend/services/engine/position_integrity.py:644`부터 세 anomaly를 구조화한다.
  - `backend/services/engine/position_integrity.py:694`부터 PM이 볼 수 있는 warning 문구로 노출한다.
  - `backend/services/engine/review_audit.py:314`와 `backend/services/engine/review_audit.py:334`에서 fill_missing/risk_guard system alert 생성 경로가 있다.
  - `backend/services/engine/daily_summary.py:122`와 `backend/services/engine/review_audit.py:490`에서 integrity warning/PnL 상태를 저장한다.

## 테스트 결과

- PASS: `.venv/bin/python -m compileall -q backend`
- PASS: `git diff --check`
- PASS: 외부 호출 없는 temp sqlite smoke
  - submitted buy only: `load_db_open_positions()` 0개.
  - submitted buy warning: "체결 미검증 상태라 자동청산 대상에서 제외" 문구 확인.
  - filled buy only: open position 반환.
  - filled buy 10 / sell filled 4: net 6 반환.
  - 오늘 filled order에 fill이 없고 전일 fill만 있음: `pnl_status=unverified`, `pnl_source=fills_incomplete`.
  - 오늘 filled order에 matching fill 있음: `pnl_status=verified`, `pnl_source=fills`.
  - buy 18 / sell 36 형태: `net_negative_positions`, `duplicate_sell_orders`, `sell_qty_exceeds_buy_qty` 생성.
- PASS: temp sqlite legacy migration smoke
  - 기존 `daily_review_reports`에 `pnl_status`, `pnl_source`, `integrity_warnings`, `legacy_residual_positions` 추가 확인.
  - 기존 `daily_trade_summary`에 `pnl_status`, `pnl_source`, `integrity_warnings` 추가 확인.

## 현재 DB read-only 확인

`data/stock_trading_bot.sqlite3`는 먼저 SQLite `mode=ro`로 원본을 조회했고, helper 동작 확인은 원본 DB를 temp sqlite로 복사해 수행했다. 원본 DB에는 쓰지 않았다.

### 2026-05-04

- 원본 read-only 집계: buy submitted 11건 qty 9441, buy failed 9건 qty 0, fills table 존재, completed order 0건.
- helper 결과: `pnl_status=unverified`, `pnl_source=incomplete_orders`.
- warning: submitted 매수 11건이 "체결 미검증, 자동청산 제외"로 표시됨.
- `load_db_open_positions('2026-05-04')`: open position 0개.
- `build_restore_position_plan('2026-05-04')`: submitted-only 종목들은 `should_restore=false`, 주로 `skipped_reason=no_active_buy`.

### 2026-05-07

- 원본 read-only 집계: buy submitted 2건 qty 140, sell submitted 4건 qty 280, completed order 0건.
- helper 결과: `pnl_status=unverified`, `pnl_source=incomplete_orders`.
- warning:
  - submitted 매수 자동청산 제외: `050890(122)`, `036930(18)`.
  - 주문번호 없는 제출 기록 KIS 대조 필요.
  - 순매도 음수 이상: `036930(buy 18 / sell 36)`, `050890(buy 122 / sell 244)`.
  - 중복 매도 이상: 두 종목 모두 `sell_count=2`.
  - 매도 수량 초과: 두 종목 모두 명확히 표시.
- `load_db_open_positions('2026-05-07')`: open position 0개.
- `build_restore_position_plan('2026-05-07')`: 두 submitted-only 종목 모두 `should_restore=false`.

## 최종 판단

- 배포 가능 여부: **배포 가능**
- 이유:
  - P1/P2 배포 차단 이슈가 재현되지 않았다.
  - submitted-only buy가 S9 DB fallback 또는 S6 restart restore의 자동 sell 대상이 되지 않는다.
  - PnL `verified`는 현재 거래일 `trading_orders.id`에 연결된 fills가 완전할 때만 나온다.
  - 현재 DB의 2026-05-07 중복 sell/net negative 상태가 Review/Daily warning에 명확히 드러난다.

## 남은 위험

- KIS read-only 잔고/미체결 대조는 금지 조건 때문에 수행하지 않았다. 실제 계좌의 보유/미체결/접수 여부는 운영자가 KIS 화면 또는 read-only 절차로 별도 확인해야 한다.
- `filled` 상태 주문은 DB 상태를 신뢰해 DB fallback net position 계산에 포함한다. 다만 Review/Daily PnL 확정은 fills 완전성 검증을 별도로 요구하므로 손익 verified 허위 판단 위험은 낮아졌다.
- 이미 DB에 남아 있는 2026-05-07 중복 sell 기록 자체를 정정하지는 않았다. 이번 변경은 추가 자동 청산 방지와 Review 노출을 보장하는 범위다.
