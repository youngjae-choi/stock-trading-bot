# INBOX_EXECUTOR_ui_bugfix — 3가지 버그 픽스

## 수정 대상
`backend/static/console.html` (UI 버그 3건)
`backend/api/routes/settings.py` (API 버그 1건)

---

## 버그 1 — S7 STEP_URLS 잘못된 경로

### 현재 (약 2600라인)
```javascript
s7: "/api/v1/autotrade/signals/execute-pending",
```

### 수정 후
S7은 오늘 pending 신호를 주문 실행하는 기능인데, 현재 `/api/v1/orders/execute-pending` 엔드포인트가 없다.
`/api/v1/orders/today` (GET)로 대신 오늘 주문 현황을 확인하는 것으로 변경하고,
S7 버튼 레이블도 "▶ 오늘 주문 현황"으로 변경한다.

```javascript
s7: "/api/v1/orders/today",
```

그리고 `engineTestRun()` 함수에서 s7은 GET으로 호출하도록 처리 (s8과 동일하게):
```javascript
var method = (step === "s8" || step === "s7") ? "GET" : "POST";
var res = await fetch(stepUrl, { method: method });
```

KIS System Test 페이지에서 S7 카드 버튼 텍스트도 "▶ 오늘 주문 현황"으로 변경:
```html
<button class="btn" style="width:100%; margin-bottom:10px;" onclick="engineTestRun('s7')">▶ 오늘 주문 현황</button>
```
S7 카드 설명도 수정:
```
09:00~ KST · 오늘 발행된 주문 내역 조회
```

---

## 버그 2 — 스케줄러 시간 저장 API 메서드/경로 불일치

### 문제
프론트엔드: `POST /api/v1/settings` + body `{key, value}`
실제 API: `PUT /api/v1/settings/{key}` + body `{value, value_type, description}`

### 수정 1 — `backend/api/routes/settings.py` 에 POST 엔드포인트 추가

```python
class SettingPostRequest(BaseModel):
    key: str
    value: Any
    value_type: str = "string"
    description: str = ""

@router.post("")
async def post_setting(request: SettingPostRequest, user: dict = Depends(require_console_user)):
    """POST /api/v1/settings — key/value를 body로 받아 저장 (프론트 호환용)"""
    logger.info("START: POST /api/v1/settings key=%s", request.key)
    payload = upsert_setting(request.key, request.value, request.value_type, request.description, user["username"])
    logger.info("SUCCESS: POST /api/v1/settings key=%s", request.key)
    return {"ok": True, "source": "backend", "live": False, "payload": payload}
```

---

## 버그 3 — 익절/손절 값 변경 UI 없음

### 배경
`position_manager.py`는 RulePack의 `machine_rules` 안 exit_rules에서 손절/익절 값을 읽는다:
- `exit_rules.stop_loss_rate` (예: -0.015 = -1.5%)
- `exit_rules.take_profit_rate` (예: 0.03 = 3%)
- `exit_rules.trailing_activate_profit_rate` (예: 0.02 = 2%)
- `exit_rules.trailing_stop_rate` (예: 0.01 = 1%)

오늘 활성 RulePack을 수정하는 API: `GET /api/v1/rulepack` (목록) → `PUT /api/v1/rulepack/{id}/activate`

현실적으로 UI에서 RulePack machine_rules를 직접 수정하기보다는
**오늘 활성 RulePack의 exit_rules 값만 간단히 오버라이드**할 수 있는 섹션을 Settings 탭에 추가한다.

단, 실제 RulePack DB 수정은 복잡하므로 이번엔 `system_settings`에 override 값을 저장하고
position_manager가 이 값을 우선 참조하도록 한다.

### Settings DB 키
| 키 | 기본값 | 설명 |
|----|--------|------|
| `override_stop_loss_rate` | `` (빈값=비활성) | 손절률 override (예: -0.015) |
| `override_take_profit_rate` | `` | 익절률 override (예: 0.03) |
| `override_trailing_activate_rate` | `` | 트레일링 활성 기준 override |
| `override_trailing_stop_rate` | `` | 트레일링 손절 override |

빈값이면 RulePack 값 사용, 값이 있으면 override.

### console.html 수정 — Settings 탭에 섹션 추가

스케줄러 시간 설정 섹션 아래에 추가:

```
[포지션 청산 조건 Override]
⚠️ RulePack 자동 생성값 대신 수동으로 청산 조건을 지정합니다. 비워두면 RulePack 값 사용.

  항목                   현재값    새 값        저장
  손절률 (stop_loss)      -        [-0.015]    [저장]  예: -0.015 = -1.5%
  익절률 (take_profit)    -        [0.03  ]    [저장]  예: 0.03 = 3%
  트레일링 활성기준        -        [0.02  ]    [저장]  예: 0.02 = +2% 도달 시 활성화
  트레일링 손절률          -        [0.01  ]    [저장]  예: 0.01 = 고점 -1% 시 청산
```

저장 버튼 → `POST /api/v1/settings` key=`override_*`, value=입력값 (빈값이면 "" 저장)
로드 시 `GET /api/v1/settings` 에서 해당 키 값 표시

### position_manager.py 수정

`add_position()` 에서 exit_rules 값을 결정할 때:
```python
from ..settings_store import get_setting

def _get_exit_param(key: str, rulepack_val: float, default: float) -> float:
    override = get_setting(key, "")
    if override:
        try:
            return float(override)
        except ValueError:
            pass
    return rulepack_val if rulepack_val is not None else default
```

사용:
```python
stop_loss_rate = _get_exit_param("override_stop_loss_rate", exit_rules.get("stop_loss_rate"), -0.015)
take_profit_rate = _get_exit_param("override_take_profit_rate", exit_rules.get("take_profit_rate"), 0.03)
trailing_activate = _get_exit_param("override_trailing_activate_rate", exit_rules.get("trailing_activate_profit_rate"), 0.02)
trailing_stop = _get_exit_param("override_trailing_stop_rate", exit_rules.get("trailing_stop_rate"), 0.01)
```

---

## 완료 기준

```bash
python -m py_compile backend/api/routes/settings.py && echo "settings OK"
python -m py_compile backend/services/engine/position_manager.py && echo "position_manager OK"
python3 -c "from html.parser import HTMLParser; p=HTMLParser(); p.feed(open('backend/static/console.html').read()); print('HTML OK')"
grep -n "override_stop_loss\|POST.*api/v1/settings\|orders/today.*s7" backend/static/console.html | head -10
```

OUTBOX(`docs/agent-comm/OUTBOX_EXECUTOR_ui_bugfix.md`)에 결과 작성.
