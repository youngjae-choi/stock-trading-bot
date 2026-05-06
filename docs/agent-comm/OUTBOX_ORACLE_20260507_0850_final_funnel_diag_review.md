# OUTBOX_ORACLE - 2026-05-07 08:50 KST - Funnel/Diagnostics 최종 리뷰

## Findings

P1/P2 없음.

## 확인 결과

- Funnel Monitor 정적/mock성 수치 제거 유지 확인.
  - `backend/static/console.html`의 Layer 1 탈락 사유 정적 숫자 `1,120`, `830`, `72`, `28`은 대상 UI 영역에서 제거되어 있으며, breakdown 미수집 상태는 `S3 breakdown 미수집`으로 표시된다.
  - Funnel Quality의 실제 집계처럼 보이는 "적정 / 없음 / 최근 20거래일 평균" 문구는 제거되고, 저장된 S3/S4 상태 또는 집계 미구현 안내로 표시된다.
- Funnel S3 0개 통과 설명 유지 확인.
  - `backend/api/routes/funnel.py`는 S3 결과 존재 + `filtered_count=0` 상태에서 `S3는 실행됐으나 통과 종목 0개라 S4/S5 미생성`을 반환한다.
  - 콘솔은 `empty_reason`, `layer1_raw`, `layer1_rejected`, `has_s4`, `has_s5`, `last_updated_at`를 표시한다.
- 후보/assignment dedupe 및 key 정규화 결과 유지 확인.
  - `backend/static/console.html`의 `funnelSymbolKey()`가 `symbol || ticker || code` 순서로 후보와 assignment를 매칭한다.
- Diagnostics 로그 패널 개선 유지 확인.
  - `/api/v1/engine/logs`는 `log_path`, `exists`, `total`, `lines`, `message`를 반환한다.
  - 로그 파일 없음, 빈 파일, 필터 결과 없음 상태가 구분된다.
- `backend/main.py` FileHandler 중복 가능성 해소 확인.
  - `logs/server.log` FileHandler는 root logger에만 추가된다.
  - `uvicorn`, `uvicorn.error`, `uvicorn.access` logger에는 같은 파일 핸들러를 직접 추가하지 않는다.
- audit source/time/status 표시 유지 확인.
  - `/api/v1/engine/audit/today`는 `pipeline_run_audit` 최신 행을 조회해 `step_id`, `started_at_kst`, `finished_at_kst`를 보강한다.
  - Diagnostics 카드는 source label, KST 시각, status, message/result ref를 표시한다.
- 인증 경계 유지 확인.
  - `/api/v1/engine/*`와 `/api/v1/funnel/*` 라우터 모두 `Depends(require_console_user)` 의존성을 유지한다.

## 테스트 결과

- PASS: `.venv/bin/python -m compileall -q backend`
- PASS: `git diff --check`
- PASS: `npx playwright test --config=playwright.config.cjs tests/e2e/status-truth.spec.cjs --workers=1`
  - 7 passed
- PASS: FileHandler 중복 snippet
  - `root_server_log_handlers=1`
  - `uvicorn_server_log_handlers=0`

## 최종 판단

배포 가능.

08:40 리뷰의 P2였던 uvicorn 계열 `logs/server.log` 중복 기록 위험은 root logger 단일 FileHandler 구성으로 정리되었다. 현재 검토 범위에서 새 P1/P2 회귀는 없다.

## 남은 위험

- `total_universe=2500`은 실제 DB 집계가 아니라 기준값이며, 현재는 `KRX 기준 universe 값(DB 집계 아님)` 문구로 오해를 줄이는 상태다.
- Layer 1 탈락 사유별 breakdown은 저장 구조가 없어 상세 집계가 아니라 `S3 breakdown 미수집`으로 표시된다.
- S5 존재 여부는 `daily_trading_plans.status IN ('active', 'validated')` 기준이다. generated/draft/validation_failed 상태를 "S5 결과 존재"로 볼지는 별도 정책 결정이 필요하다.
- 실제 운영 서버 브라우저 수동 확인 및 실 로그 유입 확인은 수행하지 않았다.
- 금지 범위에 따라 S1~S11 단계 실행, 주문/매수/매도/청산/decision activate API, 실계좌/KIS 주문성 API, 외부 LLM/KIS 호출은 수행하지 않았다.
