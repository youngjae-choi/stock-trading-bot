# [CODEX] 레짐별 성과 분석 백엔드 구현 결과

## 처리 요약

- `daily_context_snapshot` 테이블과 trade_date 인덱스를 DB 초기화 스키마에 추가했다.
- S6 Decision Engine `activate()` 시점에 오늘 morning context + active/validated RulePack 파라미터를 스냅샷으로 저장하도록 추가했다.
- `rulepack_generation.py`에 `get_active_rulepack(trade_date)`를 추가했다.
  - 실제 테이블 구조 기준으로 `rulepacks.machine_rules`를 사용한다.
  - `active`를 우선하고, 없으면 `validated`를 조회한다.
- 신규 라우트 `backend/api/routes/regime_analytics.py`를 추가했다.
  - `GET /api/v1/analytics/regime-performance`
  - `GET /api/v1/analytics/parameter-history`
  - `GET /api/v1/analytics/regime-recommendation`
- `backend/main.py`에 analytics 라우터를 등록했다.

## 변경 파일

- `backend/services/db.py`
- `backend/services/engine/decision_engine.py`
- `backend/services/engine/rulepack_generation.py`
- `backend/api/routes/regime_analytics.py`
- `backend/main.py`

## 구현 메모

- `daily_review_reports.total_pnl` 컬럼은 실제 스키마에 존재하므로 그대로 사용했다.
- 분석 API는 데이터가 없어도 프론트엔드가 고정 레짐 카드를 그릴 수 있도록 `risk_on`, `neutral`, `risk_off`, `volatile` 4개 레짐 기본값을 반환한다.
- DB 조회 실패 시 `ok: false`와 error를 반환하고 서버 로그에 `FAIL` 로그를 남긴다.
- S6 스냅샷 저장 실패는 거래 흐름을 막지 않는 비치명 경고로 처리했다.

## 검증 결과

### 통과

```bash
python -m py_compile backend/services/engine/decision_engine.py
python -m py_compile backend/api/routes/regime_analytics.py
python -m py_compile backend/services/db.py backend/services/engine/rulepack_generation.py backend/main.py
```

결과: 모두 에러 0개.

### API 로직 직접 검증

```bash
python - <<'PY'
import asyncio
from backend.services.db import initialize_database
from backend.api.routes.regime_analytics import (
    get_regime_performance,
    get_parameter_history,
    get_regime_recommendation,
)

async def main():
    initialize_database()
    for name, fn in [
        ('regime-performance', get_regime_performance),
        ('parameter-history', get_parameter_history),
        ('regime-recommendation', get_regime_recommendation),
    ]:
        payload = await fn(days=90)
        print(name, payload.get('ok'), sorted(payload.keys()))

asyncio.run(main())
PY
```

결과:

```text
regime-performance True ['data_days', 'date_range', 'days', 'ok', 'regimes']
parameter-history True ['ok', 'rows']
regime-recommendation True ['generated_at', 'min_data_days_for_confidence', 'ok', 'recommendations']
```

## 확인 필요 / 제한 사항

- 이 실행 환경에서 `fastapi.testclient.TestClient.get()`이 신규 라우트뿐 아니라 단순 `/x` 테스트 라우트에서도 반환되지 않아, HTTP 200 검증은 직접 라우트 함수 호출로 대체했다.
- 실제 서버 프로세스에서 `curl /api/v1/analytics/*` 200 확인은 Sisyphus 또는 PM 환경에서 추가 확인이 필요하다.
- 전체 E2E 테스트는 이번 백엔드 API 작업 범위에서 실행하지 못했다.

## 다음 추천 작업

1. 실제 서버 기동 후 신규 analytics API 3종을 `curl` 또는 브라우저 Network 탭으로 200 확인.
2. Gemini 프론트엔드 작업 완료 후 `/api/v1/analytics/*` 응답과 레짐 분석 화면 연결 검증.
3. 며칠치 `daily_context_snapshot`이 쌓인 뒤 추천 로직의 신뢰도 기준과 기본값이 PM 의도에 맞는지 조정.
