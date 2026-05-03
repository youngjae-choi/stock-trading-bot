# OUTBOX_GEMINI_s7_s8_s9_ui

S7/S8/S9 UI 구현 및 Positions & Exit 탭 동적화 완료.

## 수행 작업

1.  **`backend/static/console.html` 수정**:
    *   **Positions & Exit 탭**:
        *   "실시간 포지션 감시" 카드 추가: `/api/v1/orders/positions` API 연동.
        *   "오늘 주문내역" 카드 추가: `/api/v1/orders/today` API 연동.
        *   [전체 청산] 버튼 구현: `POST /api/v1/orders/liquidate-all` 연동.
        *   10초 자동 새로고침(setInterval) 로직 추가.
    *   **KIS System Test 페이지**:
        *   S7 (주문 실행), S8 (포지션 조회), S9 (당일 청산) 테스트 카드 추가.
        *   `engineTestRun` 함수에 S7, S8, S9 경로 추가 및 S8 GET 요청 처리.
        *   `STEP_URLS` 상수 업데이트.

## 검증 결과
*   HTML 파싱 테스트: OK
*   주요 API 경로 및 UI ID 포함 확인: 완료

## 특이사항
*   S8(포지션 조회) 단계는 서버 구현상 `GET` 요청이 필요하여 `engineTestRun`에서 예외 처리함.
