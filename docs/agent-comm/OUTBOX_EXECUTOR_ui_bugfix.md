# OUTBOX_EXECUTOR_ui_bugfix — 3가지 버그 픽스 결과

## 작업 상태

완료.

## 변경 파일

- `backend/static/console.html`
- `backend/api/routes/settings.py`
- `backend/services/engine/position_manager.py`

## 구현 내용

### 버그 1 — S7 STEP_URLS 잘못된 경로

- S7 호출 경로를 `/api/v1/orders/today`로 변경.
- `engineTestRun()`에서 S7과 S8은 `GET`으로 호출하도록 변경.
- KIS System Test S7 버튼 문구를 `▶ 오늘 주문 현황`으로 변경.
- S7 설명 문구를 `09:00~ KST · 오늘 발행된 주문 내역 조회`로 변경.

### 버그 2 — 스케줄러 시간 저장 API 메서드/경로 불일치

- `backend/api/routes/settings.py`에 `POST /api/v1/settings` 호환 엔드포인트 추가.
- 요청 body `{key, value, value_type, description}`를 받아 기존 `upsert_setting()`으로 저장.
- 시작/성공 서버 로그를 추가.

### 버그 3 — 익절/손절 값 변경 UI 없음

- Settings 탭에 `포지션 청산 조건 Override` 섹션 추가.
- 다음 키를 `GET /api/v1/settings`로 로드하고 `POST /api/v1/settings`로 저장하도록 구현.
  - `override_stop_loss_rate`
  - `override_take_profit_rate`
  - `override_trailing_activate_rate`
  - `override_trailing_stop_rate`
- 빈 값은 override 비활성 값으로 저장.
- 숫자 형식이 아닌 값은 클라이언트에서 저장 전 차단.
- `position_manager.py`에서 `system_settings` override 값을 우선 참조하도록 변경.
- override가 비어 있거나 잘못된 값이면 RulePack 값, RulePack 값이 없으면 기본값을 사용.
- 트레일링 활성 기준/손절률도 포지션별 값으로 저장해 청산 판단에 사용.

## 검증 결과

```bash
python -m py_compile backend/api/routes/settings.py && echo "settings OK"
# settings OK

python -m py_compile backend/services/engine/position_manager.py && echo "position_manager OK"
# position_manager OK

python3 -c "from html.parser import HTMLParser; p=HTMLParser(); p.feed(open('backend/static/console.html').read()); print('HTML OK')"
# HTML OK

grep -n "override_stop_loss\|POST.*api/v1/settings\|orders/today.*s7" backend/static/console.html | head -10
# 2627:        s7: "/api/v1/orders/today", // /api/v1/orders/today handles s7 today order status.
# 2724:    { key: "override_stop_loss_rate", label: "손절률 (stop_loss)", placeholder: "-0.015", example: "예: -0.015 = -1.5%" },
# 2809:  /* POST /api/v1/settings saves one exit-rule override value. */
```

추가 확인:

```bash
APP_DB_PATH=/tmp/codex_ui_bugfix_settings_direct.sqlite python - <<'PY'
...
PY
# POST route True override_stop_loss_rate -0.015
# GET route True True -0.015
```

## 잔여 확인 필요

- 브라우저 수동 확인은 실행하지 못함. PM 또는 브라우저 검증 담당자가 Settings 탭에서 override 입력/저장/재로드 표시를 확인해야 함.
- 실제 장중 청산 동작은 실시간 tick과 주문 실행 환경이 필요하므로 로컬 정적 검증 범위 밖임.
- 작업 시작 시 이미 작업트리에 다수의 미커밋 변경과 신규 파일이 있었음. Codex는 commit을 수행하지 않음.
