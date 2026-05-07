# INBOX_ORACLE - 2026-05-07 17:45 KST - 포지션/청산/체결 정합성 리뷰

## 요청자

Sisyphus

## 담당 페르소나

Oracle

## 배경

Executor가 다음 지시서에 따라 P1 포지션/청산/체결 정합성을 수정했다.

- 지시: `docs/agent-comm/INBOX_EXECUTOR_20260507_1720_position_liquidation_integrity.md`
- 결과: `docs/agent-comm/OUTBOX_EXECUTOR_20260507_1720_position_liquidation_integrity.md`

수정 요약:

- DB-only net position helper 추가
- 재시작 복원을 buy-only에서 buy-sell net 기준으로 변경
- EOD 중복 매도 스킵
- 전일 잔여 포지션 경고
- sell 주문번호 없으면 uncertain 처리
- S10/Review에 pnl_status/pnl_source/integrity warning 추가

## 리뷰 목표

1. 서버 재시작 후 이미 sell submitted/filled 된 종목이 다시 복원되지 않는지 확인.
2. EOD가 같은 종목을 중복 매도하지 않도록 가드가 충분한지 확인.
3. buy/sell net position 계산이 status 처리에서 위험하지 않은지 확인.
4. 주문번호 없는 sell을 success로 숨기지 않는지 확인.
5. S10/Review가 체결 미검증 상태를 명확히 드러내는지 확인.
6. 5/4 잔여 포지션 같은 legacy residual을 탐지/경고하는지 확인.
7. 새 DB migration이 기존 데이터와 하위 호환되는지 확인.
8. 주문성 API/외부 KIS 호출 없이 테스트가 충분한지 확인.

## 금지 사항

- 파일 수정 금지.
- git commit 금지.
- 매수/매도/청산/주문 API 호출 금지.
- `/api/v1/orders/*` POST, `/api/v1/kis/order/*`, `/api/v1/decision/activate` 호출 금지.
- 실제 S1~S11 실행 금지.
- 외부 LLM/KIS 호출 금지.

## 필수 검증

- `.venv/bin/python -m compileall -q backend`
- `git diff --check`
- 외부 호출 없는 temp sqlite/monkeypatch smoke 재확인
- 가능하면 현재 DB read-only로 2026-05-07/05-04 상황에 새 helper가 어떤 net/residual 판단을 낼지 확인하라. 단 DB write 금지.

## 결과 보고 파일

검토 완료 후 아래 파일을 작성하라.

`docs/agent-comm/OUTBOX_ORACLE_20260507_1745_position_liquidation_integrity_review.md`

포함 항목:

- Findings 우선: P1/P2/P3, 파일/라인, 영향, 수정 제안
- 테스트 결과
- 현재 DB 기준 예상 판단
- 최종 판단: 배포 가능 / 조건부 가능 / 불가
- 남은 위험
