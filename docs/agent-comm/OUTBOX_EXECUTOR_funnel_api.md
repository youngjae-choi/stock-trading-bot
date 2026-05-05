# OUTBOX_EXECUTOR_funnel_api

## 처리 상태
- 완료: `GET /api/v1/funnel/summary` 신규 라우트 추가
- 완료: `backend/main.py`에 `funnel_router` import/include 등록
- 완료: `backend/services/db.py`의 `_seed_system_settings()`에 schedule/risk 기본값 추가
- 완료: 문법 검증 및 임시 DB 기반 응답 구조 검증
- 미수행: 실제 서버 재시작 후 curl 검증

## 변경 파일
- `backend/api/routes/funnel.py`
- `backend/main.py`
- `backend/services/db.py`
- `docs/agent-comm/OUTBOX_EXECUTOR_funnel_api.md`

## 구현 내용
1. `backend/api/routes/funnel.py`
   - `/api/v1/funnel/summary` 엔드포인트를 추가했다.
   - KST 기준 오늘 날짜로 S3 Universe Filter, S4 Hybrid Screening, BUY signal, position, Daily Plan profile count를 집계한다.
   - `universe_filter_results`, `hybrid_screening_results`는 엔진 실행 전 테이블이 없을 수 있어 테이블 존재 여부를 확인하고 없으면 0으로 반환하도록 처리했다.
   - 시작/성공/실패 서버 로그를 추가했다.
   - 내부 예외 발생 시 사용자 응답에는 일반 오류 코드 `FUNNEL_SUMMARY_FAILED`만 반환한다.

2. `backend/main.py`
   - `from .api.routes.funnel import router as funnel_router` 추가
   - `app.include_router(funnel_router)` 추가

3. `backend/services/db.py`
   - `INSERT OR IGNORE` 기존 seed 패턴을 유지해 아래 기본 설정을 추가했다.
   - `schedule_s2_time`: `"08:00"`
   - `schedule_s9_time`: `"15:20"`
   - `schedule_s10_time`: `"18:00"`
   - `schedule_s11_time`: `"22:00"`
   - `risk.force_exit_time`: `"15:20"`
   - `risk.new_entry_cutoff_time`: `"15:10"`

## 검증 결과
```bash
.venv/bin/python -m py_compile backend/api/routes/funnel.py backend/main.py backend/services/db.py && echo "py_compile OK"
```
결과:
```text
py_compile OK
```

```bash
APP_DB_PATH=/tmp/funnel_api_test_direct.sqlite3 .venv/bin/python - <<'PY'
import asyncio
from backend.api.routes.funnel import get_funnel_summary
from backend.services.db import initialize_database

initialize_database()
result = asyncio.run(get_funnel_summary())
print('ok', result.get('ok'))
payload = result.get('payload', {})
print('payload_keys', sorted(payload.keys()))
print('layer1_count', payload.get('layer1_count'))
print('profile_counts', payload.get('profile_counts'))
PY
```
결과:
```text
ok True
payload_keys ['layer1_count', 'layer1_raw', 'layer1_rejected', 'layer2_count', 'positions_count', 'profile_counts', 'signals_count', 'total_universe', 'trade_date']
layer1_count 0
profile_counts {'LOW_VOL': 0, 'MID_VOL': 0, 'HIGH_VOL': 0, 'THEME_SPIKE': 0}
```

## 확인 필요 / 잔여 리스크
- 실제 `curl http://127.0.0.1:8000/api/v1/funnel/summary` 검증은 수행하지 않았다. 현재 라우터는 `require_console_user` 인증 의존성을 사용하므로 인증 쿠키 없는 단순 curl은 401이 될 수 있다.
- 작업 시작 시 워크트리에 다수의 기존 수정/신규 파일이 있었다. 본 작업은 위 변경 파일 범위만 수정했고 git commit은 수행하지 않았다.

## 보완: S10/S11 scheduler time 연결
- `backend/services/scheduler.py`의 `schedule_times`에 `s10`, `s11` 키를 추가했다.
- `schedule_s10_time`, `schedule_s11_time` system_settings 값이 각각 `job_review_audit`, `job_learning_memory` CronTrigger에 반영되도록 `_parse_time("s10")`, `_parse_time("s11")`를 연결했다.
- invalid time fallback에 `s10=(18, 0)`, `s11=(22, 0)`을 추가했다.
- 기존 `backup`, `us_watch` 스케줄 키와 job 동작은 유지했다.
