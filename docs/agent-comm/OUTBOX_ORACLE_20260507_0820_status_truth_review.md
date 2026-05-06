# OUTBOX_ORACLE - 2026-05-07 08:20 KST - 상태 표시 진실성 수정 리뷰

## Findings

### P1

- 없음.

### P2

- 없음.

### P3 - 테스트 고정 커버리지 보강 권장

- 위치: `tests/e2e/status-truth.spec.cjs:94`, `tests/e2e/status-truth.spec.cjs:105`, `tests/e2e/status-truth.spec.cjs:124`
- 영향: 추가된 Playwright 테스트는 Diagnostics의 null/skip 표시와 Today의 "S2만 완료" 케이스를 검증한다. 다만 Today 화면의 "S2~S5 null이면 완료 아님" 및 "schedule_skip_today=true이면 Today S2~S6 skip" 케이스는 테스트 파일에 직접 assertion으로 고정되어 있지 않다.
- 검토 결과: 일회성 Playwright mock으로 두 케이스를 별도 확인했고 현재 구현은 정상이다.
- 수정 제안: `status-truth.spec.cjs`에 Today null 및 Today skip assertion을 추가해 향후 회귀를 자동으로 잡도록 보강한다.

## 코드 리뷰 결과

- `backend/static/console.html:2805`의 `hasTodayPipelineResult()`는 `ok: true`만으로 완료 처리하지 않고, `has_result`, 실제 result 객체, KST 오늘 `trade_date`를 함께 확인한다.
- `backend/static/console.html:2817`의 `getPipelineReadState()`는 S2~S5 null 결과를 `completed`가 아닌 `pending`/`missing`으로 분리한다.
- `backend/static/console.html:2915`~`2921`에서 Today timeline은 S2~S6 skip을 completed/running과 분리한다.
- `backend/static/console.html:3838`~`3848`에서 System Diagnostics는 schedule skip, 완료, 대기, 미생성을 구분하고 null payload도 JSON 박스에 표시한다.
- `backend/api/routes/status_envelope.py:13`의 공통 envelope는 기존 `payload`를 유지하면서 `status`, `has_result`, `result`, `trade_date`를 추가한다.
- S2/S3/S4/S5 GET route 변경은 기존 payload shape을 유지하는 additive 변경으로 보이며, 기존 프론트 호출과 E2E payload 기대값을 깨는 회귀는 발견하지 못했다.

## 테스트 결과

- PASS: `.venv/bin/python -m compileall -q backend`
- PASS: `git diff --check`
- PASS: `npx playwright test --config=playwright.config.cjs tests/e2e/status-truth.spec.cjs --workers=1`
  - 3 passed.

## Playwright / Mock 검증 결과

- Executor 추가 테스트:
  - S2/S3/S4 null GET은 Diagnostics에서 `대기`.
  - S5 null GET은 Diagnostics에서 `미생성`, JSON 결과는 `null`.
  - S2만 결과가 있으면 S2만 `완료`, S3/S4는 `대기`, S5는 `미생성`.
  - `schedule_skip_today=true`이면 Diagnostics S2/S3/S4/S5/S5-V/S5-A/S6가 `비거래일 스킵`.
- Oracle 추가 일회성 mock 확인:
  - Today null: S2 `대기`, S3 `대기`, S4 `대기`, S5 `미생성`, S5-V/S5-A `대기`.
  - Today skip: S2/S3/S4/S5/S5-V/S5-A/S6 모두 `스킵`.

## 최종 판단

- 배포 가능.
- P1/P2 배포 차단 결함은 발견하지 못했다.
- P3 테스트 보강은 권장하지만 현재 배포를 막을 수준은 아니다.

## 남은 위험

- 실제 로그인 세션/운영 브라우저에서의 수동 확인은 수행하지 않았다. 금지 조건에 따라 모든 화면 검증은 local file + mocked fetch로 제한했다.
- 실제 백엔드 서버 GET API를 호출하지 않았다. S1~S11 실행, decision activate, 주문성/KIS/LLM 호출 위험을 피하기 위해 compile 및 mock 화면 검증으로 한정했다.
- `schedule_skip_today=true`일 때 수동 산출물이 이미 있어도 UI는 skip을 우선 표시한다. 이번 요구사항에는 부합하지만, 운영 정책상 "수동 결과 우선"이 필요하면 별도 PM 결정이 필요하다.
