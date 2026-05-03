# OUTBOX_GEMINI_settings_ui — Settings UI: 공휴일 관리 + 스케줄러 시간 설정 완료

## 작업 내용
`backend/static/console.html` 수정을 통해 다음 기능을 구현했습니다:

1.  **공휴일 관리 UI 추가**
    *   `trading-calendar` API 연동 (GET /api/v1/trading-calendar/holidays, POST /api/v1/trading-calendar/holiday, DELETE /api/v1/trading-calendar/holiday/{date})
    *   연도 선택 (현재 연도 ±2년) 및 조회 기능.
    *   공휴일 목록 표시 및 개별 삭제 기능.
    *   신규 공휴일 등록 폼 추가.

2.  **스케줄러 시간 설정 UI 추가**
    *   `system_settings` API 연동 (GET /api/v1/settings, POST /api/v1/settings)
    *   S1~S5, 청산, 백업, 미국장 등 주요 스케줄 키값 표시 및 수정 기능.
    *   변경 시 "재시작 필요" 안내 문구 포함.

3.  **JavaScript 로직 통합**
    *   `showScreen('settings')` 호출 시 `initSettingsUI()`가 트리거되도록 수정하여 탭 전환 시 데이터를 최신화합니다.
    *   입력값 유효성 검사 (날짜 형식 YYYY-MM-DD, 시간 형식 HH:MM)를 포함했습니다.

## 검증 결과
*   HTML 문법 검사: `HTML OK`
*   키워드 확인 (`trading-calendar`, `schedule_s1_time`, `공휴일`): 정상 반영 확인.

## 후속 작업
*   백엔드 API (`/api/v1/trading-calendar/*`, `/api/v1/settings`)의 실제 구현 상태에 따라 데이터가 정상적으로 표시됩니다.
