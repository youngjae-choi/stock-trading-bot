# OUTBOX_EXECUTOR_halt_resume_and_health

## 작업 결과

완료.

## 변경 파일

- `backend/services/console_state.py`
  - `trigger_resume()` 추가
  - `/api/v1/bot/control/resume` API 로그 메타데이터 추가
  - `get_data_health()`를 `metrics` 기반 응답으로 교체
  - KIS REST 상태는 `backend.services.kis.common.client.kis_client._token_is_valid()` 기준으로 확인
  - KIS WebSocket은 `미구현` 상태로 명시
  - SQLite DB 상태는 `database_status()` 기준으로 확인

- `backend/api/routes/bot.py`
  - `trigger_resume` import 추가
  - `POST /api/v1/bot/control/resume` 엔드포인트 추가

- `backend/static/console.html`
  - 긴급정지 상태에서 버튼을 `운영재개`로 전환
  - `applyResumeState()` 추가
  - `emergencyResume()` 추가
  - `haltBtn` 클릭 시 정지/재개 분기 처리
  - Data & API 화면의 `loadDataHealth()`를 `payload.metrics` 기반으로 수정
  - DB 카드 상세 텍스트에 `dh-dbDetail` id 추가

## 검증 결과

```bash
python -m py_compile backend/services/console_state.py && echo "console_state OK"
```

결과: `console_state OK`

```bash
python -m py_compile backend/api/routes/bot.py && echo "bot OK"
```

결과: `bot OK`

```bash
python3 - <<'PY'
content = open('backend/static/console.html', encoding='utf-8').read()
checks = [
    ('control/resume endpoint in HTML', 'control/resume'),
    ('emergencyResume function', 'emergencyResume'),
    ('applyResumeState function', 'applyResumeState'),
    ('운영재개 confirm text', '운영을 재개할까요'),
    ('loadDataHealth with metrics', 'applyMetricCard'),
]
for name, pattern in checks:
    found = pattern in content
    print(f'{name}: {"OK" if found else "MISSING"}')
PY
```

결과:

```text
control/resume endpoint in HTML: OK
emergencyResume function: OK
applyResumeState function: OK
운영재개 confirm text: OK
loadDataHealth with metrics: OK
```

추가 확인:

```bash
node - <<'NODE'
const fs = require('fs');
const content = fs.readFileSync('backend/static/console.html', 'utf8');
const scripts = [...content.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/gi)].map((m) => m[1]);
for (const [index, script] of scripts.entries()) {
  new Function(script);
  console.log(`script ${index + 1}: OK`);
}
NODE
```

결과:

```text
script 1: OK
```

```bash
python3 - <<'PY'
from backend.services.console_state import get_data_health, trigger_emergency_halt, trigger_resume
print(get_data_health()['metrics'].keys())
print(trigger_emergency_halt()['halted'])
print(trigger_resume()['halted'])
PY
```

결과:

```text
dict_keys(['kis_rest', 'kis_ws', 'llm_router', 'db'])
True
False
```

## 참고 사항

- KIS 클라이언트 singleton은 인박스 예시의 `_kis_client`가 아니라 `kis_client`로 확인되어 실제 코드에 맞게 반영했다.
- 브라우저 수동 확인은 수행하지 않았다.
