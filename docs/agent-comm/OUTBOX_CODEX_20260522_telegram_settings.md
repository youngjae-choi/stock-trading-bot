# OUTBOX: 텔레그램 한국어화 + 매수체결 알림 + AI 설정 반영

**날짜:** 2026-05-22  
**대상:** Sisyphus / PM  
**작업자:** Codex (Backend Executor)

---

## 작업 요약

INBOX 지시 범위에 맞춰 아래 3개 변경을 반영했다.

1. `backend/services/scheduler.py`
   - `_audit_step_finish()` 텔레그램 알림 제목/본문을 한국어 형식으로 변경.
   - S1 토큰/시장 상태, S9 청산 건수, S10 손익, S11 메모리 저장 건수 표시를 한국어로 보강.
   - `_STEP_LABELS`, `_STATUS_KR` 상수를 추가해 단계/상태 라벨을 일관되게 관리.

2. `backend/services/engine/fill_poller.py`
   - 매수 체결 성공 시에만 텔레그램 알림을 예약하는 `_notify_buy_fill()` helper 추가.
   - output1 체결 성공 직후, output2 폴백 체결 성공 직후 모두 `asyncio.create_task(send_telegram_alert(...))` 호출.
   - 매도 체결 알림은 추가하지 않음.

3. `backend/services/engine/review_audit.py`, `backend/api/routes/telegram_webhook.py`
   - S10 액션 플랜 승인 payload에 `settings_changes` 필드 추가.
   - 손실 거래/놓친 기회/수익률 조건에 따라 `engine.min_confidence_floor`, `engine.min_price_change_pct` 변경 후보 계산.
   - 텔레그램 승인 메시지에 "승인 시 설정 자동 변경" 예고 표시.
   - `approve_action_plan_` 콜백 승인 시 `settings_changes`를 읽어 `settings_store.upsert_setting()`으로 실제 `system_settings`에 반영.
   - 적용된 설정이 있으면 텔레그램 callback 응답에 변경 키/값을 포함.

---

## 검증 결과

실행한 검증:

```bash
python -m py_compile backend/services/scheduler.py backend/services/engine/fill_poller.py backend/services/engine/review_audit.py backend/api/routes/telegram_webhook.py
```

결과: 통과.

정적 확인:

- `scheduler.py`: `[매매봇]`, `내용:`, `토큰:`, `시장:`, `청산:`, `오늘 손익:`, `저장된 메모리:` 문자열 반영 확인.
- `fill_poller.py`: `_notify_buy_fill()` 및 매수 체결 알림 `asyncio.create_task(send_telegram_alert(...))` 호출 위치 2곳 확인.
- `review_audit.py`: `payload_json`에 `"settings_changes": settings_changes` 포함 확인.
- `telegram_webhook.py`: 승인 핸들러에서 `upsert_setting()` 호출 및 적용 로그 확인.

---

## 남은 확인 필요

- 실제 텔레그램 발송은 운영 bot token/chat 설정이 필요한 외부 연동이라 로컬에서 실발송 검증은 하지 않았다.
- 기존 작업 트리에 이미 여러 미커밋 변경이 있었고, 이번 작업은 요청된 4개 코드 파일과 이 OUTBOX 문서만 대상으로 진행했다.

