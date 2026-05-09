# DOC_HIERARCHY.md

이 문서는 프로젝트 문서의 읽기 순서, 우선순위, 충돌 해결 기준을 정한다. 모든 Agent는 작업 전에 이 문서를 기준으로 필요한 문서를 확인한다.

## 1. 최상위 원칙

- PM은 요구사항과 우선순위를 결정한다.
- Sisyphus는 PM의 단일 창구이며, 요청 해석, Agent 위임, 승인 게이트, 최종 보고를 담당한다.
- 구현 Agent는 승인된 작업계획서 범위 안에서만 작업한다.
- 문서 간 충돌이 있으면 이 문서의 우선순위 순서로 판단한다.
- 확인하지 않은 코드, API, 설정을 추측해서 구현하지 않는다.

## 2. 세션 시작 시 읽기 순서

1. `DOC_HIERARCHY.md` — 문서 우선순위와 읽기 순서 확인
2. `ONBOARDING.md` — 공통 작업 흐름과 세션 체크리스트 확인
3. `AGENTS.md` — 프로젝트 헌법, 역할 경계, 필수 프로세스 확인
4. 역할별 문서
   - `CLAUDE.md` — Sisyphus / Planner / Orchestrator 기준
   - `CODEX.md` — Executor / Integrator 기준
   - `GEMINI.md` — Frontend 기준
5. 작업 성격별 기준 문서
   - `FEATURE_TEMPLATE.md` — 기능 요청, 범위, 완료 기준
   - `IMPLEMENTATION_RULES.md` — 구현 방식과 변경 원칙
   - `TEST_RULES.md` — 검증 수준과 테스트 보고 기준
   - `UI_BASELINE.md` — UI 상태, 레이아웃, 접근성 기준
   - `ERROR_HANDLING.md` — 오류 메시지, 로그, 복구 기준
6. 참조 문서
   - `API_CONTRACT.md` — API 계약
   - `DATA_MODEL.md` — 데이터 모델과 타입
   - `COMPONENT_CATALOG.md` — 기존 컴포넌트와 훅
   - `DESIGN_TOKENS.md` — 디자인 토큰
   - `GLOSSARY.md` — 용어 정의
   - `DECISION_LOG.md` — 아키텍처 결정 기록
   - `RELEASE_CHECKLIST.md` — 배포 전 점검

## 3. 문서 우선순위

문서 내용이 서로 다르면 아래 순서를 따른다.

1. 현재 세션에서 PM이 명시적으로 승인한 지시
2. `DOC_HIERARCHY.md`
3. `AGENTS.md`
4. `ONBOARDING.md`
5. 역할별 문서: `CLAUDE.md`, `CODEX.md`, `GEMINI.md`
6. 작업 성격별 기준 문서: `FEATURE_TEMPLATE.md`, `IMPLEMENTATION_RULES.md`, `TEST_RULES.md`, `UI_BASELINE.md`, `ERROR_HANDLING.md`
7. 참조 문서: API, 데이터 모델, 컴포넌트, 디자인, 용어, 결정 기록
8. 과거 `docs/agent-comm/INBOX_*`, `OUTBOX_*`, 세션 인계 문서

보안 규칙, 승인 전 구현 금지, 허위 완료 보고 금지, 기존 기능 파괴 금지는 어떤 문서보다 우선한다.

## 4. Agent 역할 경계

| 역할 | 주 책임 | 기본 모델/도구 기준 |
|------|---------|--------------------|
| Sisyphus | PM 단일 창구, 요청 해석, 위임, 승인 게이트, 최종 보고 | OpenCode, 고성능 모델 |
| Prometheus | 작업계획서, 테스트계획서, 결과서, 매뉴얼/WBS 문서화 | 중간 비용 문서 모델 |
| Explore | 코드베이스 구조, 활성 코드 경로, 기존 패턴 조사 | 저비용 탐색 모델 |
| Librarian | 공식 문서, API 스펙, 외부 레퍼런스 확인 | 저비용 탐색 모델 |
| Executor / Hephaestus | 승인된 비프론트엔드/풀스택 구현 | 고성능 구현 모델 |
| Frontend | UI, CSS, 화면 상호작용 구현 | UI 특화 모델 |
| Oracle | 아키텍처, 보안, 성능, 회귀 위험 검토 | 고성능 리뷰 모델 |
| Multimodal Looker | 스크린샷, PDF, 이미지, 다이어그램 해석 | 멀티모달 모델 |

PM은 Sisyphus에게만 요청한다. Sisyphus가 필요에 따라 적절한 Agent를 호출하고 결과를 PM이 이해할 수 있는 말로 요약한다.

## 5. 표준 작업 절차

1. PM 요청 수신
2. Sisyphus가 의도, 누락, 대안, 리스크를 요약
3. 새 개발/수정 작업이면 현재 상태 커밋 여부 확인
4. Prometheus가 작업계획서와 테스트계획서 작성
5. PM 승인
6. Executor 또는 Frontend가 승인 범위 안에서 구현
7. Oracle 리뷰와 테스트 수행
8. Prometheus가 테스트결과서, 매뉴얼, WBS 업데이트
9. Sisyphus가 최종 보고와 다음 추천 작업을 제시

긴급 장애 대응은 원인 파악과 복구를 우선할 수 있지만, 완료 보고 전에는 검증 결과와 사후 문서 정리를 남긴다.

## 6. 토큰/비용 운영 기준

- PM 대화, 요구사항 해석, 최종 판단은 Sisyphus가 담당한다.
- 단순 검색, 파일 위치 파악, 문서 초안은 저비용 Agent를 우선 사용한다.
- 아키텍처, 보안, 성능, 복잡한 구현, 회귀 위험 검토는 고성능 Agent를 사용한다.
- 여러 Agent가 같은 범위를 중복 조사하지 않도록 Sisyphus가 작업 목표와 출력 형식을 좁혀서 위임한다.
- 무료/저비용 모델의 쿼터가 막히면 Sisyphus가 PM에게 대체 모델과 비용 영향도를 설명하고 선택을 요청한다.

## 7. 커밋과 변경 관리

- 새 작업 시작 전 Sisyphus가 커밋 여부를 확인한다.
- 커밋 실행 권한은 Sisyphus만 가진다.
- Executor, Frontend, Explore, Librarian, Oracle은 git commit을 실행하지 않는다.
- 기존 미커밋 변경이 있으면 작업 목적과 관련된 파일만 선별해 커밋한다.
- `.env`, `.env.local`, API 키, 토큰, 로컬 DB, 로그 파일은 커밋하지 않는다.

## 8. 완료 보고 기준

완료 보고에는 최소 아래 항목이 포함되어야 한다.

- 무엇이 바뀌었는지
- 어떤 Agent가 어떤 역할을 했는지
- 어떤 테스트와 검증을 실제로 수행했는지
- 남은 리스크 또는 PM 확인 필요 사항
- 다음 추천 작업 3가지
