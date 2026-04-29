# DOC_HIERARCHY.md

이 문서는 프로젝트의 Markdown 문서 계층(우선순위/책임 범위) 기준이다.
문서가 많아도 충돌 없이 운영하기 위해, 아래 순서로 해석한다.

## 1) 우선순위 계층

| 레벨 | 문서 | 역할 |
|---|---|---|
| L0 | `ONBOARDING.md` | 세션 시작 진입점(필독 체크리스트) |
| L1 | `AGENTS.md` | 프로젝트 헌법(프로세스/게이트/완료 정의) |
| L2 | `CLAUDE.md`, `CODEX.md`, `GEMINI.md` | 도구/페르소나별 실행 가이드 |
| L3 | `FEATURE_TEMPLATE.md`, `UI_BASELINE.md`, `ERROR_HANDLING.md`, `IMPLEMENTATION_RULES.md`, `TEST_RULES.md` | 품질/요구/구현/테스트 기준 |
| L4 | `docs/agent-comm/*.md` | 실행 단위 지시/결과/핸드오프 로그 |
| L5 | `docs/planning`, `docs/testing`, `docs/manual`, `docs/reference`, `docs/prompts` | 계획/결과/참고 아카이브 |

## 2) 세션 시작 시 문서 읽기 순서 (단일 기준)

모든 Agent/Assistant는 이 순서를 따른다. 다른 문서에서 읽기 순서를 별도로 정의하지 않는다.

```
ONBOARDING.md → AGENTS.md → 역할 가이드(CLAUDE.md / CODEX.md / GEMINI.md) → 품질 기준(L3)
```

## 3) 충돌 해결 규칙

1. 같은 주제의 규칙이 충돌하면 높은 레벨 문서를 우선한다.
2. 같은 레벨끼리 충돌하면 최신 수정 시점 문서를 우선한다.
3. `docs/reference/*`는 참고 자료이며 강제 규칙이 아니다.
4. `docs/agent-comm/*`는 작업 지시/결과 기록이며, 정책 문서(L0~L3)를 덮어쓰지 않는다.
5. **"개별 기능 명세"**란 `FEATURE_TEMPLATE.md` 형식으로 작성된 기능별 요청서를 말한다. L3 문서에 "개별 기능 명세보다 우선하지 않는다"고 기술된 경우, 이 기능별 요청서의 지시를 L3 기본값보다 우선 적용한다.

## 4) 각 문서 책임(단일 책임 원칙)

- `ONBOARDING.md`: 새 세션 시작 절차와 필수 체크만 정의
- `AGENTS.md`: 조직 운영 규칙, 게이트, 역할 책임
- `CLAUDE.md`: 지휘/기획/승인 게이트 운영 방법
- `CODEX.md`: 구현/통합/테스트 실행 기준
- `GEMINI.md`: 프론트엔드 UI 구현 기준
- `FEATURE_TEMPLATE.md`: 요청서 템플릿(입력 품질)
- `UI_BASELINE.md`: 화면 상태/레이아웃/접근성 기준
- `ERROR_HANDLING.md`: 오류 분류/메시지/로그/복구 기준
- `IMPLEMENTATION_RULES.md`: 구현 방식/수정 전략/코드 변경 원칙
- `TEST_RULES.md`: 검증 수준/시나리오/완료 보고 기준

## 5) 운영 규칙 요약

- 새 세션 읽기 순서: 위 2) 항목을 따른다.
- 구현 요청은 먼저 `FEATURE_TEMPLATE.md` 형식으로 정리한다.
- 완료 보고 전 `TEST_RULES.md` 기준 검증을 수행한다.
- 문서 추가 시 중복 규칙을 새로 쓰지 말고, 해당 기준 문서 링크를 건다.
