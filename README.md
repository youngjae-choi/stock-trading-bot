# 바이브코딩 표준 문서 세트 (Vibe Coding Standard)

비개발자 PM이 AI 에이전트를 오케스트레이터로 활용해 프로젝트를 개발하기 위한 **범용 문서 프레임워크**다.

## 사용법

1. 이 폴더를 새 프로젝트 루트에 복사한다.
2. `<!-- 프로젝트별로 -->` 또는 `[프로젝트명]` 으로 표시된 부분을 프로젝트에 맞게 수정한다.
3. 불필요한 문서는 삭제해도 되지만 `DOC_HIERARCHY.md`에서 해당 항목도 함께 제거한다.

## 문서 계층

```
L0  ONBOARDING.md          ← 세션 시작 진입점
L1  AGENTS.md              ← 프로젝트 헌법 (프로세스/게이트/완료 기준)
L2  CLAUDE.md              ← 역할: Planner/Orchestrator (기본 도구: Claude)
    CODEX.md               ← 역할: Integrator/Executor (기본 도구: Codex)
    GEMINI.md              ← 역할: Frontend (기본 도구: Gemini)
L3  FEATURE_TEMPLATE.md    ← 기능 요청 템플릿
    UI_BASELINE.md         ← UI 상태/레이아웃/접근성 기준
    ERROR_HANDLING.md      ← 오류 분류/메시지/로그/복구 기준
    IMPLEMENTATION_RULES.md← 구현 방식/코드 변경 원칙
    TEST_RULES.md          ← 검증 수준/시나리오/완료 보고 기준
참조 DESIGN_TOKENS.md      ← 디자인 토큰 (색상/타이포/레이아웃)
    DATA_MODEL.md          ← DB 스키마 / TypeScript 타입 / API 봉투
    API_CONTRACT.md        ← REST API + 실시간 메시지 포맷
    COMPONENT_CATALOG.md   ← 기존 컴포넌트/훅 카탈로그
    GLOSSARY.md            ← 프로젝트 용어 사전
    DECISION_LOG.md        ← 아키텍처 결정 기록 (ADR)
    RELEASE_CHECKLIST.md   ← 배포 전 체크리스트
    DOC_HIERARCHY.md       ← 문서 우선순위/충돌 해결 규칙
```

## 핵심 원칙

- **PM이 방향을 결정하고, AI가 구현한다**
- **계획 → 승인 → 구현 → 검증** 순서를 반드시 지킨다
- **상상 코드 금지** — 공식 문서 확인 후 구현
- **허위 완료 보고 금지** — 실제 검증 후 보고
- **기존 기능 파괴 금지** — 영향 범위 파악 선행

## AI 에이전트 역할 분담

역할은 기본 도구에 매핑되어 있지만, **어떤 모델이든 해당 역할을 수행할 수 있다.** L2 문서(CLAUDE.md/CODEX.md/GEMINI.md)는 도구가 아닌 역할을 정의한다.

| 역할 | 기본 도구 | 책임 |
|------|-----------|------|
| Sisyphus (Planner) | Claude | 지휘, 계획, 게이트 관리 |
| Prometheus (Documenter) | Claude | 문서화, 계획서/결과서 |
| Executor (Implementer) | Codex | 비프론트엔드 구현 |
| Oracle (Integrator) | Codex | 코드 리뷰, 통합, 테스트 |
| Frontend (UI Builder) | Gemini | UI 구현 |

## CLI 실행 플래그

| 도구 | 자동 실행 플래그 |
|------|-----------------|
| Claude Code | `--dangerously-skip-permissions` |
| Codex | `--dangerously-bypass-approvals-and-sandbox` |
| Gemini | `--yolo` |

## 프로젝트 적용 체크리스트

- [ ] `AGENTS.md` — 프로젝트 목표, 기술 스택, 개발 환경 수정
- [ ] `CLAUDE.md` — 프로젝트 컨셉, 기획서 출력 형식 커스텀
- [ ] `DESIGN_TOKENS.md` — 브랜드 팔레트, 레이아웃 구조 작성
- [ ] `DATA_MODEL.md` — DB 스키마, 도메인 타입, 에러 코드 작성
- [ ] `API_CONTRACT.md` — API 엔드포인트 목록 작성
- [ ] `COMPONENT_CATALOG.md` — 기존 컴포넌트/훅 등록
- [ ] `GLOSSARY.md` — 도메인 용어 정의
- [ ] `DECISION_LOG.md` — 초기 아키텍처 결정 기록
- [ ] `UI_BASELINE.md` — 프로젝트 특화 UI 기준 추가
- [ ] `ERROR_HANDLING.md` — 프로젝트 특화 에러 규약 추가
