# OUTBOX_ORACLE_funnel_review

## 리뷰 범위
- `backend/api/routes/funnel.py`
- `backend/main.py`의 `funnel_router` import/include
- `backend/services/db.py`의 `_seed_system_settings()` schedule/risk seed
- `backend/static/console.html`의 settings API 경로, `OPS_STEPS`, funnel summary 연동

## Critical findings
- 없음.

## Major findings
1. `backend/static/console.html:2812-2814`, `backend/static/console.html:3797-3799`
   - `/api/v1/settings` 응답 형식과 프론트 사용 방식이 불일치한다.
   - 실제 settings API는 `backend/services/settings_store.py:27-35`에서 `value_json`이 아니라 파싱된 `value`만 내려준다.
   - 그런데 Today Control timeline과 Buy Conditions는 `s.value_json`을 `JSON.parse()`하려고 하며, 실패 시에도 `settingsMap[s.key] = s.value_json`으로 `undefined`를 저장한다.
   - 영향:
     - `backend/static/console.html:2856`, `backend/static/console.html:2866`의 schedule 표시/실행중 판단이 저장된 system_settings 값을 반영하지 못하고 항상 기본값 fallback에 의존할 수 있다.
     - Buy Conditions의 guardrail 표시도 저장값 대신 `-` 또는 빈 값으로 보일 수 있다.
   - 수정 필요: 해당 코드들은 `s.value`를 사용해야 한다. 기존 `loadSchedulerSettings()`와 `loadExitOverrideSettings()`는 이미 `s.value`를 사용하고 있어 그 패턴과 맞추면 된다.

2. `backend/services/db.py:116-117`, `backend/services/scheduler.py:311-334`, `backend/services/scheduler.py:429-441`
   - `schedule_s10_time`, `schedule_s11_time` seed가 실제 스케줄러 실행 시간에 연결되지 않는다.
   - 스케줄러가 동적으로 읽는 키는 `schedule_{key}_time`이며, 현재 `schedule_times`의 키는 `backup`, `us_watch` 등이다. 또한 S10 Review & Audit과 S11 Learning Memory는 `backend/services/scheduler.py:429-441`에서 각각 `16:00`, `16:30`으로 하드코딩되어 있다.
   - 영향:
     - Settings 화면에서 `schedule_s10_time`, `schedule_s11_time`을 저장/표시해도 실제 S10/S11 job 시간은 바뀌지 않는다.
     - seed 설명도 `schedule_s10_time`은 "데이터 백업", `schedule_s11_time`은 "Learning Memory"인데, UI에는 별도 `schedule_backup_time`, `schedule_usmarket_time`도 있어 PM이 보는 설정과 실제 실행이 어긋날 수 있다.
   - 수정 필요: S10/S11 job이 system_settings 키를 실제로 읽도록 연결하거나, UI/seed 키를 스케줄러가 사용하는 키 체계로 정리해야 한다.

## Minor findings
1. `backend/api/routes/funnel.py:108`, `backend/static/console.html:4583`
   - `total_universe`는 여전히 `2500` 상수에 의존한다.
   - Executor 지시서에는 KOSPI+KOSDAQ 고정값으로 명시되어 있어 현재 구현 자체는 지시 범위와 일치한다. 다만 리뷰 요청의 "숫자 하드코딩 제거 여부"를 엄격히 적용하면 전체 종목 수만은 아직 동적 데이터가 아니다.
   - 권고: PM이 "전체 종목"도 실데이터를 원하면 KRX/KIS 유니버스 원천 또는 최신 S3 raw_count를 기준으로 바꾸는 후속 결정을 해야 한다.

2. `backend/static/console.html:4583`
   - `fp.total_universe || 2500` fallback은 API 실패/누락 시 다시 하드코딩 값을 표시한다.
   - API payload가 없으면 `-`로 두는 편이 "실데이터 미확인" 상태를 더 명확히 보여준다.

## 확인 결과
- 인증 의존성: `backend/api/routes/funnel.py:17-21`에서 router-level `Depends(require_console_user)`가 적용되어 누락 없음.
- 라우터 등록: `backend/main.py`에 `funnel_router` import 및 `app.include_router(funnel_router)`가 존재한다.
- DB 테이블/컬럼:
  - `universe_filter_results`, `hybrid_screening_results`는 존재 확인 후 조회해 초기 500 위험을 줄였다.
  - `trading_signals`, `position_stop_states`, `daily_trading_plans`는 기본 schema에 존재하므로 정상 startup 이후 500 위험은 낮다.
- Funnel Monitor/Today Control:
  - S3/S4/signals/positions/profile 숫자는 `/api/v1/funnel/summary` payload를 통해 연동된다.
  - 단, 위 Major 1 때문에 Today Control schedule 표시/상태는 settings 저장값을 반영하지 못할 수 있다.

## 수정 필요 여부
- 수정 필요.
- 배포 전 최소 Major 1은 반드시 수정해야 한다. Settings API 응답 불일치라 화면 표시가 실제 저장값과 다르게 보이는 사용자 체감 버그다.
- Major 2는 스케줄러 운영 설정 신뢰성 문제이므로, S10/S11 시간을 PM이 UI에서 제어할 계획이라면 같이 수정해야 한다.

## 추가 테스트 권고
- 인증 세션으로 `GET /api/v1/settings` 응답을 확인하고, 콘솔 JS가 `value` 필드를 사용해 `schedule_s2_time`, `schedule_s9_time`을 실제 표시하는지 브라우저에서 확인.
- `POST /api/v1/settings`로 `schedule_s2_time`을 기본값이 아닌 값으로 저장한 뒤 Today Control timeline 시간이 즉시 반영되는지 확인.
- `schedule_s10_time`, `schedule_s11_time` 저장 후 스케줄러 job trigger 시간이 실제로 변경되는지 `/api/v1/scheduler/status` 또는 서버 로그로 확인.
- 인증 세션으로 `GET /api/v1/funnel/summary`를 호출해 S3/S4 테이블이 없는 DB와 있는 DB 양쪽에서 200 응답을 확인.
- Funnel Monitor에서 S4 결과와 funnel summary를 동시에 로드했을 때 `funnel-candidates`가 의도한 값(`signals_count`인지 `layer2_count`인지)으로 최종 표시되는지 브라우저에서 확인.
