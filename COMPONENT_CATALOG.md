# COMPONENT_CATALOG.md — 컴포넌트 카탈로그 단일 소스

기존 컴포넌트·훅을 이 파일에서 먼저 확인한다.
이미 있는 것을 중복 구현하지 않는다. 새 컴포넌트 추가 시 이 파일도 업데이트한다.

---

## 1. 페이지 진입점

<!-- 프로젝트별로 기술한다. 아래는 채우기 예시. -->

| 파일 경로 | 역할 | 비고 |
|-----------|------|------|
| `src/app/dashboard/page.tsx` | 대시보드 메인 페이지 | 인증 필요, SSR |
| `src/app/items/[id]/page.tsx` | 항목 상세 페이지 | 동적 라우트 |
| `src/app/login/page.tsx` | 로그인 페이지 | 비인증 접근 가능 |

---

## 2. 핵심 컴포넌트

<!-- 프로젝트별로 기술한다. 아래는 채우기 예시. -->

### `DataTable` (예시)
**경로:** `src/components/DataTable.tsx`

**역할:** 범용 데이터 테이블. 정렬, 페이지네이션, 빈 상태 처리 포함.

**Props:**
```ts
columns: { key: string; label: string; sortable?: boolean }[]
data: Record<string, unknown>[]
isLoading: boolean
emptyMessage?: string
onSort?: (key: string, direction: "asc" | "desc") => void
```

### `ConfirmModal` (예시)
**경로:** `src/components/ConfirmModal.tsx`

**역할:** 삭제/중요 액션 전 확인 모달.

**Props:**
```ts
isOpen: boolean
title: string
message: string
confirmLabel?: string   // 기본: "확인"
cancelLabel?: string    // 기본: "취소"
onConfirm: () => void
onCancel: () => void
```

### `Toast` (예시)
**경로:** `src/components/Toast.tsx`

**역할:** 성공/실패/경고 알림 토스트. 자동 소멸.

---

## 3. 커스텀 훅 카탈로그

<!-- 프로젝트별로 기술한다. 아래는 채우기 예시. -->

| 훅 | 경로 | 역할 | 핵심 반환값 |
|----|------|------|------------|
| `useToast` | `src/hooks/useToast.ts` | 토스트 메시지 표시 | `{ showToast, message }` |
| `useAuth` | `src/hooks/useAuth.ts` | 인증 상태 관리 | `{ user, isLoading, logout }` |
| `usePagination` | `src/hooks/usePagination.ts` | 페이지네이션 상태 | `{ page, limit, setPage, total }` |

---

## 4. 훅 선택 가이드

| 하고 싶은 것 | 사용할 훅/컴포넌트 |
|------------|------------------|
| 토스트 메시지 표시 | `useToast` |
| 현재 로그인 사용자 확인 | `useAuth` |
| 삭제 전 확인 | `ConfirmModal` |
| 데이터 목록 표시 | `DataTable` |

---

## 5. 중복 구현 금지 목록

<!-- 이미 구현된 기능을 나열한다. 새로 만들지 않는다. -->

아래 기능은 이미 구현되어 있다:
- 토스트: `useToast`
- 인증 상태: `useAuth`
- 데이터 테이블: `DataTable`
- 확인 모달: `ConfirmModal`

---

## 6. 파일 소유권 규칙

동시 수정 충돌 방지를 위해 작업 시작 전 파일 소유권을 먼저 선언한다.
- 공용 컴포넌트 (`src/components/`) — 병렬 수정 가능 (각 파일 독립)
- 페이지 컴포넌트 — 대형 페이지는 단독 작업 권장
