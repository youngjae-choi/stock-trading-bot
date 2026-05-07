# INBOX_EXECUTOR - 2026-05-07 17:20 KST - 포지션/청산/체결 정합성 P1 수정

## 요청자

Sisyphus

## 담당 페르소나

Executor

## 선행 감사

반드시 먼저 읽을 것:

- `docs/agent-comm/OUTBOX_ORACLE_20260507_1706_liquidation_and_performance_audit.md`

## 배경

Oracle 감사 결과:

1. 2026-05-07 S9는 실행됐고 오늘 포지션 2개는 EOD 매도 제출됐다.
2. 계좌에 남은 10종목은 대부분 2026-05-04 매수 후 청산되지 않은 잔여 포지션이다.
3. 더 심각한 P1은 서버 재시작 후 이미 트레일링 스탑 매도된 `036930`, `050890`이 다시 인메모리 포지션으로 복원되어 15:20 EOD 중복 매도가 발생한 점이다.
4. 주문 상태와 체결 상태가 분리되지 않아 S10 손익과 계좌 손익이 분리되어 있다.

## 금지 사항

- git commit 금지.
- 사용자 변경사항 되돌리지 말 것.
- 매수/매도/청산/주문 API 호출 금지.
- `/api/v1/orders/*` POST, `/api/v1/kis/order/*`, `/api/v1/decision/activate`, `/api/v1/trades/run-summary`, `/api/v1/review-audit/run` 호출 금지.
- 실제 S1~S11 실행 금지.
- 외부 LLM 호출 금지.
- KIS 주문성 API 호출 금지.

## 구현 목표

실제 주문을 실행하지 않고 코드/DB 로직을 고쳐 다음 사고를 막는다.

### 1. 재시작 포지션 복원 net position화

대상 후보:

- `backend/services/engine/decision_engine.py`
- `backend/services/engine/order_executor.py`
- DB helper 필요 시 `backend/services/db.py`

요구:

- `_restore_positions_from_db()`가 오늘 buy 주문만 보고 복원하지 않게 한다.
- 같은 symbol에 대해 buy submitted/filled 수량에서 sell submitted/filled 수량을 차감한 net qty를 계산한다.
- net qty <= 0이면 복원하지 않는다.
- 이미 sell submitted/filled/cancelled? 정책을 분리하라.
  - 최소 안전: sell `submitted`가 존재하면 재복원/EOD 중복매도 대상에서 제외한다.
  - 더 정확한 설계는 fill poller가 filled를 확정해야 하지만, 중복매도 방지는 우선 submitted sell도 차감/제외한다.
- 복원 로그에 buy_qty, sell_qty, net_qty, skipped_reason을 남긴다.

### 2. S9 청산 대상 소스 보강

대상 후보:

- `backend/services/engine/eod_liquidation.py`
- `backend/services/engine/order_executor.py`

요구:

- 인메모리 포지션이 있더라도 중복 sell submitted가 있는 종목은 EOD 매도 대상에서 제외한다.
- 인메모리 포지션 0건이어도 DB net position 또는 KIS read-only 잔고와 전략 주문 이력을 대조할 수 있는 구조를 준비한다.
- 이번 구현에서 실제 KIS 잔고 청산까지 자동화가 위험하면, 최소한 `orphan_positions`/`legacy_residual_positions`로 탐지하고 Alert/Review에 남긴다.
- 5/4 잔여 포지션처럼 전일 전략 잔여가 있으면 S9/Review가 “청산 대상 외 잔여 포지션 있음”으로 경고해야 한다.

### 3. EOD 매도 성공 조건 강화

대상 후보:

- `backend/services/engine/eod_liquidation.py`
- `backend/services/engine/order_executor.py`

요구:

- sell 주문 결과에 `kis_order_no` 또는 주문 식별자가 없으면 완전 성공으로 취급하지 않는다.
- `submitted_without_order_no` 또는 `submit_uncertain` 같은 상태/로그를 남긴다.
- S9 결과 summary에 `submitted`, `uncertain`, `skipped_duplicate`, `failed` count를 포함한다.

### 4. 체결/손익 파이프라인 최소 보강

대상 후보:

- `backend/services/engine/review_audit.py`
- `backend/services/engine/daily_summary.py`
- 관련 order/fill helper

요구:

- S10이 `trading_signals.realized_pnl`만 보고 pnl=0이라고 판단하지 않도록 최소 개선한다.
- 체결 데이터가 아직 없으면 `pnl_status=unverified` 또는 `pnl_source=incomplete_orders`를 명확히 남긴다.
- submitted 주문만 있고 filled가 없으면 Review에 “체결/손익 검증 미완료” 경고를 포함한다.
- KIS 실제 잔고와 DB orders가 불일치할 가능성을 Review/Audit에 남긴다.

### 5. 테스트

외부 호출 없는 테스트/스모크만 수행한다.

필수:

- `.venv/bin/python -m compileall -q backend`
- `git diff --check`
- sqlite temp DB 또는 monkeypatch smoke:
  - buy 10, sell submitted 10이면 restore 안 됨
  - buy 10, sell submitted 4이면 net 6만 restore 또는 안전 정책상 sell 존재로 skip/경고
  - 인메모리 포지션이 있어도 sell submitted 있으면 EOD 중복매도 스킵
  - sell 결과 order_no 없음이면 uncertain으로 집계
  - Review가 submitted-only 주문에서 pnl verified처럼 표시하지 않음

## 완료 기준

- 서버 재시작 후 이미 매도 제출된 종목이 다시 인메모리 포지션으로 살아나지 않는다.
- EOD가 같은 종목을 중복 매도하지 않는다.
- 전일 잔여 포지션은 “청산 대상 외 잔여”로 탐지/경고된다.
- S10/Review는 체결 미검증 상태를 숨기지 않는다.
- 결과는 OUTBOX로 보고된다.

## 결과 보고 파일

작업 완료 후 아래 파일을 작성하라.

`docs/agent-comm/OUTBOX_EXECUTOR_20260507_1720_position_liquidation_integrity.md`

포함 항목:

- 변경 파일 목록
- 구현 요약
- 테스트 결과
- 남은 위험
- Oracle 리뷰 포인트
