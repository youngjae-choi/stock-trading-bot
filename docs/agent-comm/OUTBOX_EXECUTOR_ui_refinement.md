# OUTBOX_EXECUTOR_ui_refinement — UI 세부 수정 결과

## 작업 상태

✅ 완료 (13/13 항목 전체 통과)

## 변경 파일

- `backend/static/console.html`

## 구현 내용

### Task 1 — Trade History 개선
- nav 버튼 / mobile select `거래내역` → `Trade History` 변경
- 화면 제목 `Trade History`, 설명 문구 갱신
- 상단 "오늘 체결 내역", "거래중 (미체결)" 카드 2개 완전 제거
- 기간 필터는 5개 요약 지표 카드 바로 위에 유지
- `일별 거래 이력` + 상세 카드 → `전체 주문 내역` 단일 테이블(`st-orders-tbody`)로 교체
- `loadAllOrders()` 함수 추가 (오늘: `/api/v1/orders/today`, 기간별: `/api/v1/trades/history`)
- `showScreen('statistics')` 진입 시 `loadAllOrders()` 호출

### Task 2 — Today Control 세로 통합 피드
- 가로 타임라인 + 최근 이벤트 2열 구조 → `today-ops-feed` 단일 세로 피드로 교체
- `renderTimeline()` → `renderTodayFeed()` 전면 교체
- 기존 `id="timeline"`, `id="todayLogs"` 요소 제거

### Task 3 — API Logs 당일 필터
- `loadApiLogs()` 에 `dateStr` 기반 오늘 날짜 필터 추가
- 백엔드 미지원 시 클라이언트에서 `called_at` / `timestamp` 기준으로 필터링

### Task 4 — Settings 개선
- Notification 카드 (Telegram + 권한 정책) 완전 제거
- 리스크 & 청산 설정 카드를 두 섹션으로 명확히 분리:
  - **포트폴리오 위험 한도** (전체 계좌 기준)
  - **포지션별 청산 기준** (개별 종목 기준)
- `.split` 구조 해제 후 단일 컬럼 레이아웃

### Task 5 — Data & API: Telegram 상태 카드 추가
- LLM Provider 상태 카드 아래 "알림 연동 상태" 카드 삽입 (`id="telegram-status"`)
- `loadDataHealth()` 내에서 telegram 상태 "활성" 표시 추가

## 검증 결과

```
✅ Trade History 메뉴명
✅ 오늘 체결 내역 카드 제거
✅ 거래중 미체결 카드 제거
✅ st-orders-tbody 통합 테이블
✅ loadAllOrders 함수
✅ today-ops-feed
✅ renderTodayFeed 함수
✅ renderTimeline 제거
✅ API Logs 당일 필터
✅ Notification 카드 제거
✅ 포트폴리오 위험 한도 라벨
✅ 포지션별 청산 기준 라벨
✅ Telegram Data&API 이동
```

JS 문법 검증 통과.

## 다음 권장 작업

1. `bash scripts/deploy.sh` 로 서버 배포 후 브라우저에서 수동 확인
2. Trade History 기간별 조회 — 현재 오늘 신호만 반환되므로 백엔드 히스토리 API 보완 검토
