# OUTBOX_EXECUTOR_shadow_missed_merge

## 처리 상태
- 상태: 구현 완료, 제한 검증 완료
- 담당 역할: Executor(Codex)
- 완료 시각: 2026-05-05

## 변경 파일
- `backend/static/console.html`

## 구현 내용
- 모바일 메뉴에서 `Missed Opportunity` option을 제거하고 `Shadow Trading` option을 `미진입 추적`으로 변경했다.
- 사이드바 `판단 검증` 메뉴에서 `Missed Opportunity` 버튼을 제거하고 `Shadow Trading` 버튼을 `미진입 추적 <small>missed</small>`로 변경했다.
- `screen-shadow-trading` 섹션을 통합 `미진입 추적` 화면으로 교체했다.
  - S3/S4 필터 탈락, S5 미배정, S6 신호 미발생, 개선 후보 요약 카드 추가
  - 전체/필터탈락/미배정/신호미발생/개선후보 필터 버튼 추가
  - Shadow Trading과 Missed Opportunity 데이터를 한 테이블에 표시
- `screen-missed-opportunity` 섹션 전체를 삭제했다.
- `loadMissedTracking()`, `filterMissedTracking()`, `renderMissedTracking()`를 추가했다.
  - `/api/v1/shadow-trading/today`
  - `/api/v1/missed-opportunity/today`
  - 두 응답을 병합하고, 응답 형태가 배열 또는 `{ payload: [...] }`인 경우를 모두 처리한다.
- 기존 저장 세션 또는 레거시 호출이 `missed-opportunity`를 가리켜도 `shadow-trading` 통합 화면으로 이동하도록 보정했다.
- 기존 `loadShadowTrading()` / `loadMissedOpportunity()` 호출자는 통합 함수로 라우팅되도록 유지했다.

## 검증 결과
- PASS: `node --check`로 `console.html` 내부 `<script>` 문법 검사 통과
- PASS: Node VM 기반 단위 검증
  - Shadow 응답 1건 + Missed 응답 1건 병합 확인
  - 요약 카드 카운트 확인
  - `signal` 필터 적용 시 S6 행만 남는 것 확인
- PASS: 정적 참조 확인
  - `screen-missed-opportunity`, `mo-all-tbody`, `mo-candidate-tbody`, `st-list-tbody`, `st-total` 제거 확인
  - `loadMissedTracking()` 연결 확인

## 제한 / 확인 필요
- 로컬 FastAPI 서버 바인딩 검증은 샌드박스 제한으로 실패했다.
  - `python -m backend.main`: startup 성공 후 `could not bind on any address out of [('0.0.0.0', 8000)]`
  - `uvicorn backend.main:app --host 127.0.0.1 --port 8010`: startup 성공 후 동일한 bind 실패
- Playwright Chromium 실행은 샌드박스 제한으로 실패했다.
  - Chromium launch 중 `sandbox_host_linux.cc:41` fatal error 발생
- 따라서 실제 브라우저 수동 확인과 전체 E2E는 PM/상위 에이전트 환경에서 재확인 필요하다.

## 잔여 리스크
- API가 두 endpoint 모두 실패하면 사용자에게 `로드 실패. 새로고침으로 다시 시도해주세요.`를 표시한다.
- 한 endpoint만 실패하면 나머지 데이터는 표시하고 개발자 콘솔에 WARN 로그를 남긴다.
- 서버 API 계약은 변경하지 않았다.
