# OUTBOX_ORACLE - 2026-05-07 08:40 KST - Funnel/Diagnostics 복구 리뷰

## Findings

### P2 - uvicorn 계열 로그가 `logs/server.log`에 중복 기록될 수 있음

- 위치: `backend/main.py:87-99`
- 영향:
  - `_configure_server_file_logging()`이 root, `uvicorn`, `uvicorn.error`, `uvicorn.access` 각각에 같은 `logs/server.log` FileHandler를 붙인다.
  - 같은 logger에 같은 FileHandler를 반복 추가하지 않도록 막는 처리는 있으나, logger 전파 구조상 `uvicorn.error` 레코드는 자기 handler와 부모 `uvicorn` handler를 모두 탈 수 있다.
  - 실행 환경의 uvicorn logging config/propagate 설정에 따라 access/error log가 2회 이상 기록되거나, 반대로 uvicorn logging config가 handler를 재구성하면 일부 uvicorn 파일 기록이 누락될 여지가 있다.
- 수정 제안:
  - 우선순위는 "backend app logger가 반드시 파일에 기록"이다. root FileHandler 1개를 기본으로 두고, uvicorn 전용 캡처가 꼭 필요하면 `uvicorn` 또는 `uvicorn.access` 중 필요한 logger에만 붙인 뒤 `propagate` 정책을 명시한다.
  - 대안으로 `run.sh`/systemd에서 stdout/stderr를 `logs/server.log`로 리다이렉트해 uvicorn access log는 프로세스 로그로 수집하고, Python app log만 FileHandler로 남긴다.

## 확인 결과

- P1 없음.
- Funnel Monitor의 정적 Layer 1 탈락 숫자 `1,120`, `830`, `72`, `28`은 대상 영역에서 제거됐다.
- Funnel Quality의 "적정 / 없음 / 최근 20거래일 평균" 류 문구는 실제 데이터처럼 보이는 형태에서 제거됐고, 저장된 S3/S4 상태 또는 "품질 집계 미구현" 안내로 대체됐다.
- S3 raw 존재 + filtered_count=0 + S4/S5 없음 상태는 `backend/api/routes/funnel.py:65-74`, `backend/static/console.html:5248-5254` 경로에서 `S3는 실행됐으나 통과 종목 0개라 S4/S5 미생성`으로 표시된다.
- 후보/assignment 키 정규화는 `backend/static/console.html:5162-5165`, `backend/static/console.html:5280-5281`에서 `symbol || ticker || code` 순서로 적용된다.
- audit step 매핑은 현재 실제 저장 step 기준으로 `S2/S3/S4/S5/S5-V/S5-A`가 Diagnostics DOM id와 맞는다. `S5-V -> s5v`, `S5-A -> s5a` 특수 매핑도 맞다.

## 테스트 결과

- PASS: `.venv/bin/python -m compileall -q backend`
- PASS: `git diff --check`
- PASS: `npx playwright test --config=playwright.config.cjs tests/e2e/status-truth.spec.cjs --workers=1`
  - 7 passed

## Playwright/mock 검증 결과

- null GET payload가 완료로 오인되지 않는 기존 status truth 유지 확인.
- S2 수동 성공이 S3-S5 완료로 전파되지 않는 기존 status truth 유지 확인.
- 비거래일 skip 표시 유지 확인.
- Funnel S3 0개 통과 상태 설명, 정적 탈락 숫자 미노출 확인.
- `ticker`/`code` 후보와 assignment 매칭 확인.
- Diagnostics 로그 패널의 빈 로그 파일 메시지 확인.
- Diagnostics 카드의 `pipeline_run_audit` 시각/source/status/message 표시 확인.

## `/api/v1/engine/logs` read-only/mock 확인

- 라우트 함수를 직접 호출해 외부 API/서버 실행 없이 응답 shape를 확인했다.
- 확인 payload keys: `exists`, `lines`, `log_path`, `message`, `total`
- 현재 로컬 `logs/server.log`는 빈 파일로 인식됐고, message는 `서버 로그 파일은 비어 있습니다: /home/young/repos/stock-trading-bot/logs/server.log` 형태였다.

## 최종 판단

조건부 가능.

Funnel mock 제거, S3 filtered_count=0 설명, audit 매핑, 후보 키 정규화는 요청 의도에 맞게 동작한다. 다만 `logs/server.log` FileHandler 구성은 운영에서 중복 로그/환경별 누락 가능성이 있어 배포 전 P2를 정리하는 편이 안전하다.

## 남은 위험

- `total_universe=2500`은 여전히 실제 DB 집계가 아니라 기준값이며, source 문구로만 구분된다.
- Layer 1 탈락 사유 breakdown은 저장 구조가 없어 상세 집계가 아니라 "S3 breakdown 미수집"으로 표시된다.
- S5 존재 여부는 active/validated plan 기준이다. generated/draft/validation_failed 상태까지 "S5 결과 존재"로 볼지 여부는 별도 정책 확인이 필요하다.
- 실제 운영 서버 브라우저 확인 및 실 로그 유입 확인은 수행하지 않았다. 금지 범위에 따라 S1~S11 실행, 주문성 API, KIS/외부 LLM 호출은 수행하지 않았다.
