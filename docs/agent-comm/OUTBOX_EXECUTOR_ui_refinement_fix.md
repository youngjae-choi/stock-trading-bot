# OUTBOX_EXECUTOR_ui_refinement_fix

## 처리 상태
완료

## 수정 파일
- `backend/static/console.html`

## 구현 내용
- Task 1-C: `trades-executed-tbody`, `trades-pending-tbody` 잔여 참조 제거
  - HTML 카드 블록은 이미 제거되어 있었고, 미사용 `loadTodayTrades()` 함수에 남은 tbody 참조를 제거했습니다.
- Task 3: `loadApiLogs()`에 당일 `date` 파라미터 추가 및 클라이언트 fallback 필터 적용
- Task 4-A: Settings 화면의 `Notification` 카드 제거
- Task 4-B: `리스크 & 청산 설정` 카드 내용을 포트폴리오 위험 한도와 포지션별 청산 기준 구조로 교체
- Task 5: Data & API 화면의 LLM Provider 상태 카드 아래에 Telegram 알림 연동 상태 카드 추가
  - `loadDataHealth()`에서 `telegram-status`를 `활성` 상태로 갱신하도록 추가했습니다.

## 검증 결과

### INBOX 지정 검증
```text
✅ 오늘 체결 내역 카드 제거
✅ 거래중 미체결 카드 제거
✅ API Logs 당일 필터
✅ Notification 카드 제거
✅ 포트폴리오 위험 한도 라벨
✅ 포지션별 청산 기준 라벨
✅ Telegram Data&API 이동
```

### JS 문법 검증
```text
script syntax ok
```

## 잔여 리스크 / 확인 필요
- 이번 작업은 INBOX 지시대로 `backend/static/console.html`만 수정했습니다.
- 브라우저 수동 확인은 수행하지 않았습니다. 화면 배치 확인은 PM 브라우저 확인이 필요합니다.
- 작업 시작 전부터 저장소에 다수의 미커밋 변경이 존재했습니다. Codex는 커밋 권한이 없어 커밋하지 않았습니다.
