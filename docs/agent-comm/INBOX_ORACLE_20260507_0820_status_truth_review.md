# INBOX_ORACLE - 2026-05-07 08:20 KST - 상태 표시 진실성 수정 리뷰

## 요청자

Sisyphus

## 담당 페르소나

Oracle

## 배경

Executor가 다음 지시서에 따라 구현을 완료했다.

- `docs/agent-comm/INBOX_EXECUTOR_20260507_0810_status_truth_fix.md`
- 결과 파일: `docs/agent-comm/OUTBOX_EXECUTOR_20260507_0810_status_truth_fix.md`

원 문제:

- Today/System Diagnostics가 `ok: true`만 보고 S2~S5를 완료/성공으로 표시했다.
- 실제 payload는 `null`이었고, S3~S5는 예정 시간 전/미실행이었다.
- PM이 수동 실행한 S2는 정상 payload를 반환했다.

## 리뷰 목표

Executor 수정이 다음 조건을 만족하는지 독립 검토한다.

1. `ok: true`만으로 완료 처리하지 않는다.
2. S2~S5 GET 응답의 null payload는 완료/성공이 아니라 대기/미생성으로 표시된다.
3. S2만 결과가 있으면 S2만 완료되고 S3~S5는 완료가 아니다.
4. `schedule_skip_today=true`이면 S2~S6은 completed가 아니라 skipped로 표시된다.
5. 기존 GET/POST API 하위 호환성을 깨지 않는다.
6. 추가된 `status_envelope.py`와 API route 변경이 타입/스키마/프론트 호출에 회귀를 만들지 않는다.

## 금지 사항

- 파일 수정 금지.
- git commit 금지.
- S1~S11 단계 실행 금지.
- 주문/매수/매도/청산/decision activate API 호출 금지.
- 실계좌/KIS 주문성 API 호출 금지.
- 외부 LLM/KIS 호출 금지.

## 필수 확인

- 변경 diff 리뷰.
- `.venv/bin/python -m compileall -q backend`
- `git diff --check`
- Executor가 추가한 Playwright 테스트 실행 또는 동등한 mock 테스트 확인.
- 가능하면 로컬 화면 mock 기준으로 다음을 확인:
  - S2 null -> 완료 아님
  - S3 null -> 완료 아님
  - S4 null -> 완료 아님
  - S5 payload null -> 완료 아님
  - S2 success + S3~S5 null -> S2만 완료
  - schedule skip true -> skip 표시

## 결과 보고 파일

검토 완료 후 아래 파일을 작성하라.

`docs/agent-comm/OUTBOX_ORACLE_20260507_0820_status_truth_review.md`

포함 항목:

- Findings 우선: P1/P2/P3, 파일/라인, 영향, 수정 제안
- 테스트 결과
- Playwright/mock 검증 결과
- 최종 판단: 배포 가능 / 조건부 가능 / 불가
- 남은 위험
