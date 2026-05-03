# OUTBOX_EXECUTOR_trading_day_check — 완료 보고

## 상태: SUCCESS

---

## 변경 파일

| 파일 | 변경 유형 | 내용 |
|------|-----------|------|
| `backend/services/kis/domestic/service.py` | 함수 추가 | `check_trading_day(date_str)` — KIS `CTCA0903R` API 호출, `tr_day_yn == "Y"` 이면 True, 실패 시 False |
| `backend/services/settings_store.py` | 함수 추가 | `get_setting(key, default=None)` — 단일 키 조회, 없으면 default 반환 |
| `backend/services/scheduler.py` | 로직 추가 | S1 끝에 거래일 확인 + `schedule_skip_today` 플래그 upsert; S2~S5 진입부에 스킵 체크 |

---

## 구현 상세

### `check_trading_day()` (service.py)
- 엔드포인트: `GET /uapi/domestic-stock/v1/quotations/chk-holiday`
- `tr_id = "CTCA0903R"`, params `{"BASS_DT": date_str}`
- `output[0]["tr_day_yn"] == "Y"` → True
- 예외/응답 없음 → False (보수적 처리)

### `get_setting()` (settings_store.py)
- `system_settings` 테이블에서 단건 SELECT
- 없으면 `default` 반환

### `scheduler.py` — S1 추가 로직
- `job_refresh_kis_token()` 기존 토큰 갱신 완료 후 실행
- `datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")`로 오늘 날짜 계산
- `check_trading_day()` 호출 → `schedule_skip_today = "true" / "false"` upsert
- 실패 시 플래그 세팅 없음 → S2~S5 정상 실행 (fail-open)

### `scheduler.py` — S2~S5 스킵 체크
- 각 job 시작부에 `get_setting("schedule_skip_today") == "true"` 확인
- 해당하면 SKIP 로그 후 `return`
- `get_setting` 예외 시 `pass` → 정상 실행 (fail-open)

---

## 완료 기준 검증

```
python -m py_compile backend/services/kis/domestic/service.py  → OK
python -m py_compile backend/services/settings_store.py        → OK
python -m py_compile backend/services/scheduler.py             → OK
from backend.services.kis.domestic.service import check_trading_day → OK
from backend.services.settings_store import get_setting             → OK
```
