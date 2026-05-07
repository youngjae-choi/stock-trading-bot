# INBOX_ORACLE - 2026-05-07 19:15 KST - Position Integrity 최종 리뷰

## 요청자

Sisyphus

## 담당 페르소나

Oracle

## 배경

포지션/청산/체결 정합성 수정이 두 차례 진행되었다.

- 감사: `docs/agent-comm/OUTBOX_ORACLE_20260507_1706_liquidation_and_performance_audit.md`
- 1차 지시: `docs/agent-comm/INBOX_EXECUTOR_20260507_1720_position_liquidation_integrity.md`
- 1차 결과: `docs/agent-comm/OUTBOX_EXECUTOR_20260507_1720_position_liquidation_integrity.md`
- 1차 Oracle 리뷰: `docs/agent-comm/OUTBOX_ORACLE_20260507_1745_position_liquidation_integrity_review.md`
- P1 재수정 지시: `docs/agent-comm/INBOX_EXECUTOR_20260507_1800_position_integrity_p1_fixes.md`
- P1 재수정 결과: `docs/agent-comm/OUTBOX_EXECUTOR_20260507_1800_position_integrity_p1_fixes.md`

현재 목표는 포지션/청산 정합성 작업을 프론트 구조개편 전에 독립적으로 닫을 수 있는지 확인하는 것이다.

## 리뷰 목표

1. submitted buy가 자동 청산 대상/복원 대상에서 제외됐는지 확인.
2. filled/partial_fill/fill 기반 net position 계산이 안전한지 확인.
3. 오늘 order_id와 연결되지 않은 fills가 PnL verified를 만들지 않는지 확인.
4. net negative / duplicate sell / sell qty exceeds buy qty anomaly가 Review/Daily summary warning에 드러나는지 확인.
5. DB migration 하위 호환성 확인.
6. P1/P2 배포 차단 이슈가 남았는지 확인.

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
- 외부 호출 없는 temp sqlite/monkeypatch smoke
- 가능하면 현재 DB read-only로 2026-05-04/2026-05-07 anomaly 예상 출력 확인

## 결과 보고 파일

검토 완료 후 아래 파일을 작성하라.

`docs/agent-comm/OUTBOX_ORACLE_20260507_1915_position_integrity_final_review.md`

포함 항목:

- Findings 우선
- 테스트 결과
- 최종 판단: 배포 가능 / 조건부 가능 / 불가
- 남은 위험
