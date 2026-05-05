# OUTBOX_EXECUTOR_s6_tick_ui_tests

## 변경 파일 목록

- `backend/services/kis/realtime_ws.py`
- `backend/services/engine/decision_engine.py`
- `backend/static/console.html`
- `tests/e2e/console-smoke.spec.cjs`
- `tests/e2e/health.spec.ts`

## 구현 요약

### 1. KIS 실시간 tick 등락률 매핑

- 한국투자증권 공식 GitHub 샘플의 `H0STCNT0` 컬럼 순서를 기준으로 실시간 체결 필드를 매핑했다.
- `PRDY_CTRT`를 `change_rate` / `prdy_ctrt`로 tick callback payload에 추가했다.
- `CNTG_VOL`, `ACML_VOL`, `CTTR`, `PRDY_VOL_VRSS_ACML_VOL_RATE`도 추적 가능한 값으로 추가했다.

### 2. S6 거래량 배수 평가 보강

- `decision_engine.py`가 tick의 `prev_volume_ratio` / `prdy_vol_vrss_acml_vol_rate`도 거래량 배수 후보 값으로 읽도록 보강했다.
- 단일 체결량 값만으로 거래량 배수를 임의 계산하지 않는 기존 안전 원칙은 유지했다.

### 3. 조건 추적 UI 표시

- Live Decisions의 오늘 매수 신호 테이블에 `조건 추적` 컬럼을 추가했다.
- `rule_matched.unavailable_conditions`가 있으면 `N개 확인필요`로 표시하고, 등락률/거래량배수/확인 필요 키를 작은 설명으로 보여준다.
- 기존 `/api/v1/decision/signals/today` 응답 구조인 `{trade_date, signals, count}`를 올바르게 읽도록 수정했다.

### 4. E2E 테스트 최신화

- 최근 UI 문구 변경(`Today Control` → `Today's`)과 Bot overview live 응답 구조에 맞춰 smoke 테스트를 수정했다.

## 테스트 결과

### 통과

```bash
. .venv/bin/activate && python -m py_compile backend/services/kis/realtime_ws.py backend/services/engine/decision_engine.py backend/services/engine/rule_resolver.py
```

```bash
. .venv/bin/activate && python - <<'PY'
# H0STCNT0 샘플 frame을 _ingest_message에 넣어 change_rate/volume 필드 추출 확인
PY
```

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/v1/decision/status
curl http://127.0.0.1:8000/api/v1/decision/signals/today
curl "http://127.0.0.1:8000/api/v1/kis/realtime/latest?n=1"
```

```bash
npm run -s _playwright_test_internal
```

결과: 6 passed.

### 부분 실패 / 확인 필요

```bash
. .venv/bin/activate && python -m pytest
```

- `pytest`는 설치 완료.
- 전체 pytest는 `backend/api/routes/engine_test.py`가 pytest 테스트 파일로 오인되어 collection error 발생.
- `python -m pytest tests`는 Python 테스트 파일이 없어 `no tests ran`으로 종료.

```bash
npx playwright test tests/e2e/ --reporter=list
```

- 결과: 50 passed, 24 failed.
- 주요 실패 원인:
  - 여러 Phase 테스트가 오래된 로그인 후 heading `Today Control`을 기대함.
  - 여러 Phase 테스트가 구 UI 이름(`Daily Plan & RulePack`, `KIS System Test`, `Review & Audit`, `Expert Knowledge`)을 기대함.
  - 일부 API 테스트는 현재 DB 상태/권한/외부 KIS 응답 상태에 의존함.
  - 이 실패들은 이번 S6 tick/UI 변경과 직접 관련 없는 기존 테스트 최신화 이슈로 분리 필요.

## 남은 리스크 / 확인 필요

- 실제 장중 KIS WebSocket 프레임으로 `H0STCNT0` 필드 수신을 한 번 더 확인해야 한다.
- `PRDY_VOL_VRSS_ACML_VOL_RATE`는 한국투자증권 샘플 기준 “전일 거래량 대비 등락율”이므로, 현재 RulePack의 `volume_ratio_min`과 의미가 완전히 같은지 PM/전략 기준 확인이 필요하다.
- 전체 E2E 24개 실패는 별도 “E2E 테스트 최신화” 작업으로 분리하는 것이 안전하다.
