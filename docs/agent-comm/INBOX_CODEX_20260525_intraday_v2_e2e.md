# INBOX — Codex : 장중 재선별 v2 E2E Playwright 테스트

작성일: 2026-05-25
요청자: Sisyphus (Claude Code)
선행 조건: ✅ Backend 구현 완료 (OUTBOX_CODEX_20260525_intraday_reselection_v2.md)
선행 조건: ✅ Frontend 통합 완료 (OUTBOX_GEMINI_20260525_intraday_reselection_v2.md)

---

## 배경

장중 재선별 v2 시스템(Feature 1+2+3 + Additional 4)이 backend + frontend 모두 구현되었다.
이제 **E2E Playwright 테스트**로 통합 동작을 검증해야 한다.

UI는 **Funnel Monitor** 화면에 통합됨:
- `tc-intraday-reselection-card` — 재선별 타임라인
- `tc-replacement-signal-card` — 교체 신호
- `tc-kill-switch-card` — Kill Switch 토글

---

## 작업 범위

### 신규 spec 파일 작성

**파일**: `tests/e2e/intraday-v2.spec.cjs`

기존 `tests/e2e/intraday-regime.spec.cjs` 패턴을 참고 (세션 생성, BASE 상수, describe 그룹화).

---

## 테스트 시나리오 (필수 6개)

### Scenario 1: API 응답 구조 검증
- `GET /api/v1/trading-monitor/reselection-stats?trade_date=2099-01-01` → 200 OK, `payload.slots` 배열 존재
- `GET /api/v1/trading-monitor/replacement-signals?trade_date=2099-01-01` → 200 OK, `payload.signals` 배열 존재
- (빈 데이터여도 정상 응답해야 함)

### Scenario 2: system_settings 자동 등록 확인
- `GET /api/v1/settings` → 8개 신규 키 모두 존재 확인:
  - `intraday_refresh.master_enabled`
  - `intraday_refresh.lunch_slots_enabled`
  - `intraday_refresh.sector_rotation_enabled`
  - `intraday_refresh.sector_rotation_threshold` (값 = 3.0)
  - `intraday_refresh.replacement_signal_enabled`
  - `intraday_refresh.replacement_score_gap` (값 = 0.15)
  - `intraday_refresh.max_replacement_per_symbol` (값 = 1)
  - `intraday_refresh.max_replacement_per_day` (값 = 5)

### Scenario 3: DB 테이블 생성 확인
- Python subprocess로 SQLite 직접 조회
- `replacement_signals` 테이블 schema 확인 (필수 컬럼 11개)
- `sector_rotation_log` 테이블 schema 확인 (필수 컬럼 7개)

### Scenario 4: Scheduler 5개 슬롯 등록 확인
- `GET /api/v1/system/jobs` 또는 동등 endpoint로 cron job 조회
- `job_intraday_refresh_0930`, `_1030`, `_1130`, **_1300**, **_1400** 5개 모두 등록 확인
- 만약 API가 없으면 Python subprocess로 scheduler 직접 검사

### Scenario 5: Funnel Monitor UI 렌더링 (브라우저)
- `/static/console.html` 접속 (또는 로그인 후 리다이렉트)
- 로그인 후 사이드바 "Funnel Monitor" 클릭
- 다음 3개 DOM ID 모두 존재 확인:
  - `#tc-intraday-reselection-card`
  - `#tc-replacement-signal-card`
  - `#tc-kill-switch-card`
- Kill Switch 카드는 항상 표시되어야 함 (display !== 'none')
- 스크린샷 저장: `tests/e2e/img/funnel_intraday_v2_main.png`

### Scenario 6: Kill Switch 토글 동작
- 마스터 토글 (`intraday_refresh.master_enabled`) 클릭 → OFF
- `GET /api/v1/settings` 재호출하여 값 false 확인
- sub 토글들이 disabled 상태인지 DOM 확인
- 다시 마스터 ON → sub 토글 활성화 확인
- 스크린샷 저장: `tests/e2e/img/funnel_intraday_v2_killswitch.png`
- **반드시 테스트 종료 시 마스터를 다시 ON으로 복원** (cleanup)

---

## 구현 요구사항

### 세션 생성
기존 `createTestSession()` 헬퍼 패턴 그대로 재사용 (`tests/e2e/intraday-regime.spec.cjs` line 14-27 참고).

### 인증 쿠키
Playwright `page.context().addCookies([...])` 로 세션 쿠키 주입 후 페이지 접근.

### 스크린샷 디렉토리
`tests/e2e/img/` (이미 존재). 파일명 prefix: `funnel_intraday_v2_`

### 클린업
Scenario 6에서 변경한 설정은 **반드시 원복**. `test.afterAll` hook 또는 `try/finally` 사용.

---

## 실행 명령

```bash
npx playwright test tests/e2e/intraday-v2.spec.cjs --reporter=list
```

---

## 절대 금지

- 실제 매수/매도 주문 발생시키는 테스트 작성 금지
- 운영 DB 데이터 변경 금지 (system_settings는 변경 후 원복 OK)
- 다른 spec 파일 수정 금지

---

## 출력 (OUTBOX) 요구사항

작업 완료 후 `docs/agent-comm/OUTBOX_CODEX_20260525_intraday_v2_e2e.md` 에:
- 작성된 spec 파일 경로
- 6개 시나리오 각각 통과/실패 결과
- 발견된 이슈 / API 응답 구조 불일치 / 수정 필요 사항
- 스크린샷 파일 경로 2장

---

## 완료 기준

- [ ] `npx playwright test tests/e2e/intraday-v2.spec.cjs` → **6개 시나리오 모두 PASS**
- [ ] 스크린샷 2장 생성 확인
- [ ] 시스템 설정 원복 확인
- [ ] OUTBOX 작성
