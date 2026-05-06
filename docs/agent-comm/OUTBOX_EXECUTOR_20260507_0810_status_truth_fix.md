# OUTBOX_EXECUTOR - 2026-05-07 08:10 KST - 상태 표시 진실성 수정

## 변경 파일 목록

- `backend/static/console.html`
- `backend/api/routes/status_envelope.py`
- `backend/api/routes/market_tone.py`
- `backend/api/routes/universe.py`
- `backend/api/routes/screening.py`
- `backend/api/routes/daily_plan.py`
- `tests/e2e/status-truth.spec.cjs`

## 구현 요약

- Today 타임라인이 S2~S5를 `ok: true`만으로 완료 처리하지 않도록 수정했다.
- S2/S3/S4는 오늘 KST `trade_date`의 실제 결과 객체가 있을 때만 완료로 표시한다.
- S5는 오늘 KST `trade_date`의 Daily Plan이 있고 `id`와 `status`가 있을 때만 완료로 표시한다.
- S5 결과가 없으면 `미생성`, S2~S4 결과가 없으면 `대기`로 표시한다.
- `schedule_skip_today=true`이면 Today와 System Diagnostics에서 S2~S6 계열을 완료가 아니라 `스킵`/`비거래일 스킵`으로 표시한다.
- System Diagnostics GET 조회 결과는 성공 배지 판정과 JSON 표시를 분리했다. null payload도 검은 JSON 박스에 그대로 표시한다.
- S5-V/S5-A는 기존 `payload.plan.status` 가정 대신 실제 Daily Plan payload/status 구조를 함께 처리한다.
- S2~S5 GET API 응답에 하위 호환을 유지하면서 `status`, `has_result`, `result`, `trade_date`를 추가했다.

## 테스트 결과

- PASS: `.venv/bin/python -m compileall -q backend`
- PASS: `git diff --check`
- PASS: `npx playwright test --config=playwright.config.cjs tests/e2e/status-truth.spec.cjs --workers=1`
  - 3 tests passed.

## Playwright/mock 확인 결과

- S2 GET `{ ok: true, payload: { market_tone: null, trade_date: today }, has_result: false }`는 `대기`로 표시됨.
- S3/S4 null 결과는 `대기`로 표시됨.
- S5 GET `{ ok: true, payload: null, has_result: false }`는 `미생성`으로 표시되고 JSON 박스에 `null`이 표시됨.
- S2만 실제 결과가 있는 경우 S2만 `완료`, S3~S4는 `대기`, S5는 `미생성`으로 표시됨.
- `schedule_skip_today=true`인 경우 S2/S3/S4/S5/S5-V/S5-A/S6가 `비거래일 스킵`으로 표시됨.

## 남은 위험

- 실제 로그인 세션을 통한 운영 브라우저 수동 확인은 수행하지 않았다. 외부 LLM/KIS 호출 금지 조건 때문에 Playwright fetch mock으로 판정 로직만 검증했다.
- 전체 E2E는 실행하지 않았다. 기존 시나리오 중 일부가 실서버 또는 외부 연동을 유발할 수 있어 이번 지시 범위에서는 targeted mock test만 실행했다.
- API envelope는 하위 호환 방식으로 추가했지만, 외부 소비자가 top-level `status`를 별도 의미로 이미 사용 중인지 여부는 확인 필요하다.

## Oracle 리뷰 포인트

- `backend/static/console.html`의 S2~S6 상태 우선순위가 운영 의도와 맞는지 확인 필요: `schedule_skip_today=true`일 때 실제 수동 결과가 있어도 UI는 skip을 우선 표시한다.
- `backend/api/routes/status_envelope.py`가 GET 조회 성공과 산출물 존재 상태를 충분히 분리하는지 확인 필요.
- S5-V/S5-A 판정이 현재 Daily Plan 상태 전이(`validated`, `active`)와 맞는지 확인 필요.
