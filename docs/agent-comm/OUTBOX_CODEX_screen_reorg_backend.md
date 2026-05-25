# OUTBOX: Codex — 화면 재배치 백엔드 API 추가 결과

**작성:** Codex 2026-05-23  
**대상 INBOX:** `docs/agent-comm/INBOX_CODEX_screen_reorg_backend.md`

---

## 1. 추가/확장된 endpoint

수정 파일:
- `backend/api/routes/regime_sets.py`

추가:
- `PUT /api/v1/regime/sets/{set_id}`
  - Regime SET의 `name`, `description`, `trigger_conditions`, `is_active` 수정
  - `settings`는 기존 JSON에 전달된 키만 merge하는 부분 업데이트
  - 반환: `{ok, set_id, updated_fields}`
  - 없는 SET은 `404 Set not found`

- `GET /api/v1/regime/day-detail?trade_date=YYYY-MM-DD`
  - 특정 거래일의 `regime_set_applications` 적용 정보
  - `regime_sets.is_prebuilt` 보강
  - `applied_settings` JSON 파싱
  - `profile_breakdown`
  - `morning_context`의 `regime`, `risk_level`, `vix`, `kospi_change_pct`

---

## 2. orders 테이블 실제 컬럼 확인 결과

`PRAGMA table_info(orders)` 확인 결과:

| column | type |
|---|---|
| id | TEXT |
| strategy_run_id | TEXT |
| signal_id | TEXT |
| broker_order_id | TEXT |
| symbol | TEXT |
| side | TEXT |
| order_type | TEXT |
| quantity | REAL |
| limit_price | REAL |
| status | TEXT |
| requested_at | TEXT |
| updated_at | TEXT |
| request_json | TEXT |
| response_json | TEXT |

확인 결과:
- `risk_profile` 컬럼 없음
- `pnl` 컬럼 없음
- `order_date` 컬럼 없음
- 날짜 필터로 사용할 수 있는 컬럼은 `requested_at`
- 현재 status 값: `filled` 37건, `created` 16건

따라서 INBOX 지시대로 `orders` 기반 Risk Profile 집계는 필수 컬럼이 없을 때 조용히 `[]`를 반환하도록 처리했다.

---

## 3. profile_breakdown 쿼리 결과

직접 호출 검증:

```text
day_detail.ok= True
day_detail.trade_date= 2026-05-22
day_detail.profile_breakdown= []
day_detail.has_regime_application= False
day_detail.morning_context= None
```

서버 로그 방어 동작:

```text
WARN: GET /api/v1/regime/day-detail profile_breakdown unavailable missing_columns=['pnl', 'risk_profile']
```

없는 SET 수정 검증:

```text
put_missing.status_code= 404
put_missing.detail= Set not found: SET-NOT-FOUND-SMOKE
```

---

## 4. 검증 결과

통과:
- `python -m py_compile backend/api/routes/regime_sets.py`
- 라우터 함수 직접 호출:
  - `get_day_detail("2026-05-22")`
  - `update_regime_set("SET-NOT-FOUND-SMOKE", ...)` 404 확인

제한:
- `FastAPI TestClient`로 앱 전체를 import한 호출은 앱 초기화/스케줄러 초기화 로그 이후 완료되지 않아 라우터 직접 호출로 대체했다.
- 실제 기존 SET 값을 변경하는 PUT 성공 케이스는 운영 DB 변형을 피하기 위해 수행하지 않았다.

---

## 5. 남은 확인 필요

- 프론트엔드가 `profile_breakdown=[]`일 때 빈 상태 UI를 정상 표시해야 한다.
- Risk Profile별 실적이 화면에 반드시 필요하면, `orders`에 `risk_profile/pnl`을 추가할지 또는 기존 `profile_performance_daily`/`daily_review_reports.profile_summary`를 API 소스로 사용할지 PM 결정이 필요하다.
