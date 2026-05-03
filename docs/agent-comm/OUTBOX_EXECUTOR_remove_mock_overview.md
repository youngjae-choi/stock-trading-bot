# OUTBOX_EXECUTOR_remove_mock_overview — /api/v1/bot/overview mock 제거 결과

## 작업 요약

`/api/v1/bot/overview` 응답을 하드코딩 mock overview에서 실 DB 및 런타임 상태 기반 응답으로 교체했다.
`universe_filter_results` 실제 스키마에는 `result_json` 컬럼이 없고 `items` 컬럼이 있어 Layer 1 집계는 `items` JSON을 기준으로 조정했다.

## 변경 파일

- `backend/services/console_state.py`
  - `get_console_overview()`가 `_CONSOLE_STATE["overview"]`를 반환하지 않도록 교체
  - KIS 토큰, WebSocket, RulePack, Decision Engine, 포지션, 신호, 손익, funnel, timeline, 운영 로그를 DB/런타임 상태에서 구성
  - `from .db import get_connection` 추가
  - overview API 로그 기본 summary를 실 DB 기반 문구로 수정
- `backend/api/routes/bot.py`
  - `/api/v1/bot/overview` 응답을 `source="backend"`, `mock=False`로 변경
  - message/result_summary를 실 데이터 기반 문구로 변경

## 스키마 확인 결과

- `universe_filter_results`: `id`, `trade_date`, `items`, `raw_count`, `filtered_count`, `created_at`
- `daily_trade_summary`: 현재 로컬 DB에는 없음. 구현은 예외 처리로 `pnl_percent=0.0` fallback 처리됨.
- `trading_signals`, `hybrid_screening_results`, `market_tone_results`, `symbols`: 조회 대상 테이블 존재 확인
- `kis_client` singleton: `backend/services/kis/common/client.py`의 `kis_client = KISClient()` 확인

## 검증 결과

```bash
python -m py_compile backend/services/console_state.py && echo "console_state OK"
# console_state OK

python -m py_compile backend/api/routes/bot.py && echo "bot OK"
# bot OK
```

```bash
python3 -c "
from backend.services.console_state import get_console_overview
result = get_console_overview()
print('trade_date:', result.get('trade_date'))
print('mock_mode:', result.get('mock_mode'))
print('health keys:', list(result.get('health', {}).keys()))
print('funnel:', result.get('funnel'))
print('OK' if result.get('mock_mode') == False else 'STILL MOCK')
"
# trade_date: 2026-05-03
# mock_mode: False
# health keys: ['kis_rest', 'websocket', 'rulepack', 'risk_guard']
# funnel: {'market_total': 0, 'layer1': 30, 'layer2': 21, 'entry_waiting': 0, 'holding': 0}
# OK
```

추가 라우트 직접 호출:

```bash
python3 - <<'PY'
import asyncio
from backend.api.routes.bot import get_bot_overview

async def main():
    result = await get_bot_overview()
    print('ok:', result.get('ok'))
    print('mock:', result.get('mock'))
    print('source:', result.get('source'))
    print('live:', result.get('live'))
    payload = result.get('payload', {})
    print('payload.mock_mode:', payload.get('mock_mode'))
    print('payload.health keys:', list(payload.get('health', {}).keys()))

asyncio.run(main())
PY
# ok: True
# mock: False
# source: backend
# live: True
# payload.mock_mode: False
# payload.health keys: ['kis_rest', 'websocket', 'rulepack', 'risk_guard']
```

## 남은 리스크 / 확인 필요

- 로컬 DB에 `daily_trade_summary` 테이블이 없어 검증 중 `pnl summary unavailable - no such table: daily_trade_summary` 경고가 발생했다. 요구사항대로 예외 처리되어 overview 응답은 정상 반환된다.
- 브라우저 수동 확인과 전체 E2E는 실행하지 않았다.
- 작업 시작 전부터 `backend/services/console_state.py`, `backend/api/routes/bot.py`에 다른 변경사항이 존재했다. 이번 작업은 overview mock 제거 범위만 추가 수정했다.
