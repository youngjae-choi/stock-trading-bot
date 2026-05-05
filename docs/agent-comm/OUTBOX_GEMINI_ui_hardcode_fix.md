# OUTBOX_GEMINI_ui_hardcode_fix

## 작업 요약
`backend/static/console.html` 파일 내의 하드코딩된 API 경로, 응답 필드명, 스케줄 시간 및 Funnel 데이터를 동적으로 로드하도록 수정하였습니다.

## 주요 수정 사항

1.  **설정(Settings) API 경로 및 필드 수정**
    *   `renderTodayFeed()` 및 `loadBuyConditions()`: `/api/v1/settings/list` → `/api/v1/settings`로 수정.
    *   응답 필드: `payload.settings` → `payload.items`로 수정.
    *   `saveGuardrail()`: `/api/v1/settings/set` → `/api/v1/settings`로 수정하고, `value_json` 대신 `value` 필드에 숫자로 전송하도록 변경.

2.  **OPS_STEPS 기본 시간 수정**
    *   S3 유니버스: `09:05` → `08:15`
    *   S4 스크리닝: `09:20` → `08:30`
    *   S5 Daily Plan: `09:35` → `08:45`
    *   S6 엔진: `09:45` → `실시간` (settingKey 제거)

3.  **Today Control Funnel Progress 동적화**
    *   정적 HTML의 하드코딩된 숫자를 `-`로 초기화하고 `fp-total`, `fp-layer1` 등 ID 부여.
    *   `renderFunnel()` 함수가 신규 `/api/v1/funnel/summary` 포맷과 기존 `overview` 포맷을 모두 지원하도록 개선.
    *   `renderTodayFeed()`에서 `/api/v1/funnel/summary`를 병렬 호출하고 결과를 렌더링하도록 추가.

4.  **Funnel Monitor 개선**
    *   `loadFunnelData()`에서 `overview` API 대신 `/api/v1/funnel/summary`를 사용하여 정확한 누적 통계 및 Profile별 배정 현황을 표시하도록 수정.

## 검증 결과
*   **HTML Syntax**: `HTMLParser`를 통한 구문 분석 통과.
*   **Grep 검증**:
    *   `settings/list`, `settings/set` 경로 완전 제거 확인 (0개).
    *   `OPS_STEPS` 수정된 시간 확인 (08:15, 08:30, 08:45).
    *   `funnel/summary` 호출 및 처리 로직 추가 확인.

## 파일 변경 목록
*   `backend/static/console.html`
보완: funnel-total/funnel-layer1 초기값을 -로 변경
보완: settings payload.value 사용으로 수정
