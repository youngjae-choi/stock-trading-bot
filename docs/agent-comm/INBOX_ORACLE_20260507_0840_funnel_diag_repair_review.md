# INBOX_ORACLE - 2026-05-07 08:40 KST - Funnel/Diagnostics 복구 리뷰

## 요청자

Sisyphus

## 담당 페르소나

Oracle

## 배경

Executor가 다음 지시서에 따라 구현을 완료했다.

- `docs/agent-comm/INBOX_EXECUTOR_20260507_0830_funnel_diag_repair.md`
- 결과 파일: `docs/agent-comm/OUTBOX_EXECUTOR_20260507_0830_funnel_diag_repair.md`

구현 요약:

- Funnel Monitor의 정적 Layer 1 탈락 숫자와 Funnel Quality mock 문구 제거
- S3 filtered_count=0일 때 “S3는 실행됐으나 통과 종목 0개라 S4/S5 미생성” 표시
- `symbol || ticker || code` 후보/assignment 매칭 지원
- `logs/server.log` FileHandler 연결 및 `/api/v1/engine/logs` 응답/빈 로그 메시지 개선
- Diagnostics 카드에 `pipeline_run_audit` 실행 시각/source/status/message 표시
- `tests/e2e/status-truth.spec.cjs` 확장, Playwright 7 passed

## 리뷰 목표

1. Funnel Monitor에서 하드코딩/mock 값이 실제 데이터처럼 보이지 않는지 확인.
2. 2026-05-07처럼 S3 raw 존재 + filtered 0 + S4/S5 없음 상태가 화면에서 설명되는지 확인.
3. Diagnostics 로그 패널이 실제 backend logging과 연결되는지 확인.
4. Python logging FileHandler가 중복 추가되거나 로그 폭증/경로 문제를 만들지 않는지 확인.
5. Diagnostics 카드와 `pipeline_run_audit` step/source/status 매핑이 정확한지 확인.
6. 후보/assignment `symbol/ticker/code` 정규화가 기존 표시를 깨지 않는지 확인.
7. 기존 status truth 수정과 충돌하지 않는지 확인.

## 금지 사항

- 파일 수정 금지.
- git commit 금지.
- S1~S11 단계 실행 금지.
- 주문/매수/매도/청산/decision activate API 호출 금지.
- 실계좌/KIS 주문성 API 호출 금지.
- 외부 LLM/KIS 호출 금지.

## 필수 검증

- `.venv/bin/python -m compileall -q backend`
- `git diff --check`
- `npx playwright test --config=playwright.config.cjs tests/e2e/status-truth.spec.cjs --workers=1`
- 가능하면 read-only/mock으로 `/api/v1/engine/logs` response shape 확인

## 결과 보고 파일

검토 완료 후 아래 파일을 작성하라.

`docs/agent-comm/OUTBOX_ORACLE_20260507_0840_funnel_diag_repair_review.md`

포함 항목:

- Findings 우선: P1/P2/P3, 파일/라인, 영향, 수정 제안
- 테스트 결과
- Playwright/mock 검증 결과
- 최종 판단: 배포 가능 / 조건부 가능 / 불가
- 남은 위험
