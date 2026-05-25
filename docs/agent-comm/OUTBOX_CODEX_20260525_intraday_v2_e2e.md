# OUTBOX — Codex : 장중 재선별 v2 E2E Playwright 테스트

작성일: 2026-05-25
대상 INBOX: `docs/agent-comm/INBOX_CODEX_20260525_intraday_v2_e2e.md`

---

## 작성된 spec 파일

- `tests/e2e/intraday-v2.spec.cjs`

## 실행 명령

```bash
npx playwright test tests/e2e/intraday-v2.spec.cjs --reporter=list
```

## 실제 실행 결과

현재 Codex 실행 샌드박스에서 위 명령을 실제 실행했다.

결과:

- 총 6개 시나리오 중 1개 PASS, 5개 FAIL
- PASS:
  - Scenario 3: DB 테이블 생성 확인
- FAIL:
  - Scenario 1: API 응답 구조 검증
  - Scenario 2: system_settings 자동 등록 확인
  - Scenario 4: Scheduler 5개 슬롯 등록 확인
  - Scenario 5: Funnel Monitor UI 렌더링
  - Scenario 6: Kill Switch 토글 동작

## 실패 원인

실패 원인은 spec의 assertion 불일치가 아니라 현재 실행 환경의 권한 차단이다.

- Playwright APIRequestContext의 `127.0.0.1:8000` 접속이 `connect EPERM 127.0.0.1:8000`으로 차단됨
- Chromium headless 실행이 `sandbox_host_linux.cc:41 shutdown: Operation not permitted`로 차단됨
- Python socket 생성도 `PermissionError: [Errno 1] Operation not permitted`로 차단되어, 이 샌드박스 안에서는 로컬 백엔드 E2E 네트워크 검증을 완료할 수 없음

## 시나리오별 상태

| 시나리오 | 상태 | 비고 |
|---|---:|---|
| Scenario 1 API 응답 구조 | FAIL | Playwright request가 로컬 네트워크 접속 권한 차단 |
| Scenario 2 settings 기본값 | FAIL | 인증 세션 생성은 가능하나 settings API 접속 권한 차단 |
| Scenario 3 DB 테이블 스키마 | PASS | `initialize_database()` 후 `replacement_signals`, `sector_rotation_log` 필수 컬럼 확인 |
| Scenario 4 Scheduler 슬롯 | FAIL | `/api/v1/scheduler/status` 접속 권한 차단 |
| Scenario 5 Funnel Monitor UI | FAIL | Chromium 실행 권한 차단 |
| Scenario 6 Kill Switch 토글 | FAIL | Chromium 실행 권한 차단 및 settings API 접속 권한 차단 |

## 발견된 이슈 / 수정 필요 사항

- `tests/e2e/intraday-v2.spec.cjs`는 INBOX의 6개 시나리오를 각각 독립 `test()`로 작성했다.
- DB 테이블 검증은 신규 테이블이 없을 수 있는 DB 상태를 고려하여 `initialize_database()`를 먼저 호출하도록 보정했다.
- Kill Switch sub toggle selector는 CSS 표준 selector인 `input.kill-switch-toggle:not([data-kskey="intraday_refresh.master_enabled"])`로 작성했다.
- 현재 환경에서는 스크린샷 생성 불가. Chromium 실행 자체가 권한 차단된다.

## 스크린샷 파일 경로

생성 예정 경로:

- `tests/e2e/img/funnel_intraday_v2_main.png`
- `tests/e2e/img/funnel_intraday_v2_killswitch.png`

현재 Codex 샌드박스 실행에서는 Chromium 권한 차단으로 두 파일 모두 생성되지 않았다.

## Cleanup 상태

- Scenario 6은 실행 전 `intraday_refresh.master_enabled=true`로 보정하고, 테스트 내에서 다시 ON으로 복원하도록 작성했다.
- `test.afterAll`에도 `intraday_refresh.master_enabled=true` 복원 로직을 추가했다.
- 이번 실행에서는 settings API 접속이 `EPERM`으로 차단되어 API 기반 cleanup 확인은 수행되지 않았다.
