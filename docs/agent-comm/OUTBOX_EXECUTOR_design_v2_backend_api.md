# OUTBOX_EXECUTOR_design_v2_backend_api

## 결과: 성공

모든 Task 완료. py_compile 전부 통과.

---

## 완료 항목

### Task 1: `backend/api/routes/rule.py` — 신규 생성
- GET /api/v1/rule/base — 활성 Base RulePack 조회
- GET /api/v1/rule/base/list — Base RulePack 목록
- GET /api/v1/rule/profiles — 활성 Risk Profile Pack 조회
- GET /api/v1/rule/profiles/list — Profile Pack 목록
- PUT /api/v1/rule/profiles — 프로필 수정 (새 버전 자동 생성 + 활성화)
- GET /api/v1/rule/composition/today — 오늘 캐시된 전체 종목 룰
- GET /api/v1/rule/composition/{symbol_code} — 특정 종목 룰 즉시 계산

### Task 2: `backend/api/routes/daily_plan.py` — 신규 생성
- GET /api/v1/daily-plan/today — 오늘 plan 조회
- GET /api/v1/daily-plan/{date} — 날짜별 plan 조회
- POST /api/v1/daily-plan/generate — S5 수동 즉시 실행
- POST /api/v1/daily-plan/validate — draft plan 검증 (활성화 없음)
- POST /api/v1/daily-plan/activate — validated plan → active 전환
- `_validate_plan` 함수가 daily_plan.py에 그대로 존재함을 확인 후 직접 import

### Task 3: `backend/api/routes/symbol_override.py` — 신규 생성
- GET /api/v1/symbol-overrides — 전체 override 목록
- PUT /api/v1/symbol-overrides/{symbol_code} — upsert (INSERT OR UPDATE)
- DELETE /api/v1/symbol-overrides/{symbol_code} — 삭제

### Task 4: `backend/api/routes/trading_monitor.py` — 신규 생성
- GET /api/v1/trading-monitor/candidates — 매수 후보 + 매수 준비도
- GET /api/v1/trading-monitor/positions — 보유 포지션 + trailing stop 상태
- `_compute_buy_readiness()`: candidate dict에서 동적으로 조건 구성 (ai_confidence, volume_ratio, change_rate, vwap_position)

### Task 5: `backend/main.py` — 수정
- 4개 router import 추가 (rule, daily_plan, symbol_override, trading_monitor)
- 4개 app.include_router() 추가

### Task 6: `backend/services/scheduler.py` — 수정
- `job_rulepack_generation` 함수를 `job_daily_plan`으로 교체
- import: `from .engine.daily_plan import run_daily_plan_generation` (내부 lazy import 방식 사용)
- job id: `job_daily_plan`, 시간: 기존 s5 시간(08:45 KST) 유지

---

## py_compile 결과

```
rule.py OK
daily_plan.py OK
symbol_override.py OK
trading_monitor.py OK
main.py OK
scheduler.py OK
```

---

## 주요 확인 사항

- `_validate_plan` 함수명은 OUTBOX_EXECUTOR_design_v2_backend_core 경고와 달리 실제 `daily_plan.py`에 그대로 존재함 (이름 변경 없음)
- `get_rule` 은 rule_cache.py에서 export되나 trading_monitor.py에서 import 선언만 하고 실제 사용은 `get_all_cached()` 직접 조회 방식으로 구현 (INBOX 원본 코드 그대로)
- scheduler.py의 S5 job: `job_rulepack_generation` → `job_daily_plan` 교체 완료, 비거래일 스킵 로직 유지
