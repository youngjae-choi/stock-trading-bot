# OUTBOX_GEMINI_phase4b_ui

## 작업 결과
Expert Knowledge Base UI 구현을 완료하였습니다.

### 1. 사이드바 및 모바일 메뉴 추가
- `Funnel Monitor` 다음에 `Expert Knowledge` 메뉴를 추가했습니다.
- 모바일용 `mobileMenu` select 드롭다운에도 해당 항목을 추가했습니다.

### 2. Expert Knowledge 화면 추가
- `id="screen-expert-knowledge"` 섹션을 추가하여 지식 등록 폼과 지식 목록 테이블을 구현했습니다.
- 등록 폼: 제목, 내용, 적용 범위(S3/S4/S5/ALL), 카테고리, 우선순위 입력 필드를 포함합니다.
- 목록 테이블: 등록된 지식의 상태(pending/approved/rejected)와 관리 액션(승인/거부)을 제공합니다.

### 3. JavaScript 기능 구현
- `loadExpertKnowledge()`: API를 통해 지식 목록을 불러와 렌더링합니다.
- `renderKnowledgeList(items)`: 불러온 항목들을 테이블 형식으로 출력하며, 상태에 따른 스타일과 액션 버튼을 생성합니다.
- `submitKnowledge()`: 새 지식을 등록하고 목록을 갱신합니다.
- `approveKnowledge(itemId)` / `rejectKnowledge(itemId)`: 지식 항목을 승인하거나 거부합니다.
- `showScreen('expert-knowledge')` 호출 시 `loadExpertKnowledge()`가 실행되도록 전환 로직을 연동했습니다.

### 4. 검증 결과
- 사이드바/모바일 메뉴 노출 확인
- 화면 전환 및 API 연동 코드 확인
- grep 검증 통과:
  - `screen-expert-knowledge|Expert Knowledge|loadExpertKnowledge` 키워드 12건 확인
  - `ek-list-tbody|submitKnowledge|approveKnowledge` 키워드 6건 확인
