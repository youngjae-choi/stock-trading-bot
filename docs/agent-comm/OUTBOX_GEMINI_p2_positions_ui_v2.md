# OUTBOX_GEMINI_p2_positions_ui_v2

## 작업 결과 요약

`backend/static/console.html` 파일을 수정하여 Positions & Exit 화면의 UI와 편의 기능을 개선했습니다.

1.  **5초 자동 새로고침 도입**:
    *   `var _positionsTimer = null;` 전역 변수 선언.
    *   `showScreen('positions')` 진입 시 5초 간격으로 `loadPositionMonitoring()` 및 `loadTodayOrders()`를 호출하도록 설정.
    *   다른 화면 이동 시 `clearInterval` 처리.
2.  **실시간 포지션 감시 테이블 개선**:
    *   `current_price`가 0 또는 없는 경우 `-` (muted) 표시.
    *   `pnl_pct` 계산 및 색상 적용 (good/bad 클래스).
    *   `stop_loss_price`에 빨간색 (`var(--bad)`) 및 천단위 콤마 적용. 이를 위해 `:root`와 `body.light`에 `--bad: var(--red);` 변수를 추가했습니다.
    *   트레일링 뱃지 문구를 `ON`/`대기`로 변경하고 스타일 적용.
    *   포지션이 없을 때의 안내 문구를 "보유 포지션 없음 (Decision Engine 활성화 후 표시됩니다)"로 구체화.
3.  **주문 내역 상태 뱃지 적용**:
    *   `statusBadgeMap`을 사용하여 `filled`, `submitted`, `failed`, `cancelled`, `preflight_blocked` 상태에 각각 색상 뱃지 적용.
4.  **예수금/총평가금액 만원 단위 표시**:
    *   `_toManwon` 헬퍼 함수를 추가하여 10,000원 이상의 금액은 "만원" 단위로 표시되도록 개선.
5.  **마지막 갱신 시각 추가**:
    *   `screen-positions` 헤더 우측에 `positions-last-updated` 영역을 추가하고, 데이터 로드 시마다 현재 시각을 표시하도록 구현.

## 검증 결과

*   **HTML 파싱**: `HTMLParser`를 통한 구조 검증 완료 (OK).
*   **패턴 매칭**:
    *   `_positionsTimer`: 6회 발견
    *   `positions-last-updated`: 2회 발견
    *   `statusBadgeMap`: 3회 발견
*   모든 체크리스트 항목이 정상 구현되었음을 확인했습니다.
