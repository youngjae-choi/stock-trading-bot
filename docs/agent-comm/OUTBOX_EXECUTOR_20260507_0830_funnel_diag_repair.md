# OUTBOX_EXECUTOR - 2026-05-07 08:30 KST - Funnel Monitor 및 Diagnostics 신뢰성 복구

## 변경 파일 목록

- `backend/api/routes/funnel.py`
- `backend/api/routes/engine_test.py`
- `backend/main.py`
- `backend/static/console.html`
- `tests/e2e/status-truth.spec.cjs`

## 구현 요약

1. Funnel summary API 보강
   - `total_universe_source`, `layer1_raw`, `layer1_rejected`, `has_s3`, `has_s4`, `has_s5`, `empty_reason`, `last_updated_at`를 응답에 포함했다.
   - `total_universe=2500`은 DB 집계가 아니라 `KRX 기준 universe 값(DB 집계 아님)`으로 명확히 표시한다.
   - S3 filtered_count가 0이면 `S3는 실행됐으나 통과 종목 0개라 S4/S5 미생성`을 내려준다.

2. Funnel Monitor mock/hardcode 제거
   - Layer 1 탈락 사유의 정적 숫자 `1,120`, `830`, `72`, `28`을 제거했다.
   - 실제 breakdown이 없으면 `탈락 사유 상세 집계 없음 / S3 breakdown 미수집`으로 표시한다.
   - Funnel Quality의 정적 “적정/없음/최근 20거래일 평균” 문구를 제거하고, 저장된 S3/S4 상태 기반 문구로 바꿨다.

3. 후보/assignment 키 정규화
   - 후보 코드와 S5 assignment 매칭이 `symbol || ticker || code`를 모두 지원하도록 `funnelSymbolKey()`를 추가했다.
   - S4 후보가 `ticker`, S5 assignment가 `code`를 쓰는 경우에도 후보 테이블에 종목코드와 Profile이 표시된다.

4. Diagnostics 서버 로그 패널 복구
   - backend startup 시 `logs/server.log` FileHandler를 root/backend/uvicorn logger에 연결했다.
   - `/api/v1/engine/logs` 응답에 `log_path`, `exists`, `total`, `lines`, `message`를 포함했다.
   - 파일 없음, 빈 파일, 필터 결과 없음 상태를 UI에서 구분해서 표시한다.

5. Diagnostics 카드와 pipeline_run_audit 연결
   - `GET /api/v1/engine/audit/today` read-only API를 추가했다.
   - Diagnostics 카드에 최신 audit 실행 시각(KST), source, status, message를 표시한다.
   - `auto_scheduler`는 `자동 실행 결과를 카드에 표시 중`, `console_manual`은 `수동 확인 실행 결과`로 표시한다.

## 테스트 결과

- PASS: `.venv/bin/python -m compileall -q backend`
- PASS: `git diff --check`
- PASS: `npx playwright test --config=playwright.config.cjs tests/e2e/status-truth.spec.cjs --workers=1`
  - 7 passed
  - 외부 LLM/KIS/API 호출 없이 `file://` 콘솔과 fetch mock만 사용했다.

## 남은 위험

- `total_universe=2500`은 여전히 실제 KRX 종목 마스터 DB 집계가 아니라 기준값이다. 이번 작업에서는 source 표시로 오해를 줄였고, 실제 종목 마스터 연동은 별도 작업이다.
- Layer 1 탈락 사유별 breakdown은 현재 저장 구조에 없어서 상세 집계를 계산하지 않는다.
- uvicorn access log는 환경별 logger 설정에 따라 중복 또는 누락 가능성이 있다. 최소 backend app logger는 `logs/server.log`에 연결되도록 했다.
- 실제 로그인 세션/운영 서버 브라우저 수동 확인은 수행하지 않았다. 금지 범위 때문에 S1~S11 실행과 주문성 API 호출도 수행하지 않았다.

## Oracle 리뷰 포인트

- `/api/v1/engine/logs`가 자기 자신을 조회할 때 빈 파일 판정을 먼저 수행하도록 START 로그를 늦춘 점이 의도에 맞는지 확인 필요.
- `pipeline_run_audit` step label과 Diagnostics 카드 id 매핑(`S5-V -> s5v`, `S5-A -> s5a`)이 향후 저장되는 모든 step 값과 맞는지 확인 필요.
- `logs/server.log` FileHandler를 root와 uvicorn 계열 logger에 각각 붙인 구성이 운영 로그 중복을 만들지 않는지 확인 필요.
- Funnel Quality를 “최근 N거래일 집계 미구현”으로 표시하는 현재 UX가 PM 기대에 충분한지 확인 필요.
