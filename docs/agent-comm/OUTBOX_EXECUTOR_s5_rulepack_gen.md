# OUTBOX_EXECUTOR_s5_rulepack_gen — S5 RulePack 자동 생성 구현 결과

## 작업 요약

S5 (08:45 KST) RulePack 자동 생성 흐름을 구현했다.

- S4 하이브리드 스크리닝 결과, 시장 톤, 전일 활성 RulePack을 입력으로 LLM 프롬프트 생성
- LLM 응답 JSON 파싱
- L1/PM Settings 캐스케이딩 캡 적용
- `rulepacks` 테이블 저장 및 자동 활성화
- LLM 실패/파싱 실패 시 전일 RulePack 복제 fallback
- 수동 실행/조회 API 추가
- APScheduler 08:45 KST job 추가
- FastAPI 라우터 등록

## 변경 파일

- `backend/services/engine/rulepack_generation.py` 신규
- `backend/api/routes/rulepack_gen.py` 신규
- `backend/services/scheduler.py` 수정
- `backend/main.py` 수정

## 구현 상세

### `backend/services/engine/rulepack_generation.py`

- `_load_pm_settings()` 추가
- `_get_market_tone()` 추가
- `_get_yesterday_rulepack()` 추가
- `_build_prompt()` 추가
- `_parse_rulepack_response()` 추가
- `_apply_caps_and_build_validation()` 추가
- `_clone_yesterday_rulepack()` 추가
- `run_rulepack_generation()` 추가
- `get_today_rulepack()` 추가

주의:
- 현재 저장소에는 `backend/config.py`와 `backend/config/risk_constants.py`가 동시에 있어 일반 import 경로 `backend.config.risk_constants`가 동작하지 않는다.
- 기존 `backend.config` 모듈을 건드리지 않기 위해 S5 서비스 내부에서만 `risk_constants.py`를 파일 경로 기반으로 로드하도록 처리했다.

### `backend/api/routes/rulepack_gen.py`

- `GET /api/v1/rulepack-gen/today`
- `POST /api/v1/rulepack-gen/run`
- 콘솔 인증 dependency 적용
- START/SUCCESS/FAIL 로그 추가

### `backend/services/scheduler.py`

- `job_rulepack_generation()` 추가
- 08:45 KST CronTrigger 등록
- 기존 placeholder job 번호 재정렬
  - 당일 청산: Job6
  - 데이터 백업: Job7
  - 야간 미국장 관찰: Job8

### `backend/main.py`

- `rulepack_gen_router` import 추가
- `screening_router` 다음에 `app.include_router(rulepack_gen_router)` 추가

## 검증 결과

아래 명령 통과:

```bash
python -m py_compile backend/services/engine/rulepack_generation.py && echo OK
python -m py_compile backend/api/routes/rulepack_gen.py && echo OK
python -m py_compile backend/services/scheduler.py && echo OK
python -m py_compile backend/main.py && echo OK
```

추가 확인:

```bash
python -m py_compile backend/api/routes/rulepack_gen.py backend/services/scheduler.py backend/main.py && echo OK
```

결과: `OK`

캡 적용 단위 확인:

```bash
_parse_rulepack_response() + _apply_caps_and_build_validation() 샘플 실행
```

결과:

```text
{'daily_loss_limit_rate': -0.03, 'max_positions': 7, 'stop_loss_rate': -0.02, 'take_profit_rate': 0.05, 'max_position_size_rate': 0.1, 'max_holding_minutes': 360}
6
```

API 라우트 직접 호출 확인:

```bash
APP_DB_PATH=/tmp/rulepack_gen_direct.sqlite3 python - <<'PY'
from backend.services.db import initialize_database
initialize_database()
from backend.api.routes.rulepack_gen import get_rulepack_gen_today
import asyncio
print(asyncio.run(get_rulepack_gen_today()))
PY
```

결과:

```text
{'ok': True, 'source': 'backend', 'live': True, 'payload': {'rulepack': None, 'trade_date': '2026-05-02'}}
```

## 미확인 / 남은 리스크

- 실제 LLM 호출 기반 `POST /api/v1/rulepack-gen/run`은 API 키와 S4 스크리닝 데이터가 필요해 실행하지 않았다.
- FastAPI `TestClient` 기반 전체 앱 HTTP 호출은 현재 환경에서 응답 없이 대기해 완료하지 못했다. 직접 라우트 함수 호출과 py_compile로 import/문법 검증은 완료했다.
- 현재 작업 전부터 worktree에 다수의 수정/신규 파일이 존재한다. 본 작업은 요청된 S5 관련 파일만 수정했다.

