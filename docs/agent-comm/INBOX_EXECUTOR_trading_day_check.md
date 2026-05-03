# INBOX_EXECUTOR_trading_day_check — S1에서 KIS 거래일 확인 후 S2~S5 자동 스킵

## 개요

S1 (job_refresh_kis_token)에서 KIS API로 오늘 주식장이 열리는지 확인한다.
비거래일이면 `system_settings`에 `schedule_skip_today=true` 플래그를 세팅한다.
S2~S5 job은 이 플래그를 보고 스킵한다.

S1은 비거래일에도 항상 실행 (토큰 갱신은 필요).

---

## 참조 파일 (읽기 전용)

- `backend/services/kis/domestic/service.py` — KIS API 호출 패턴 확인
- `backend/services/kis/common/` — kis_client 확인
- `backend/services/settings_store.py` — `upsert_setting()`, `list_settings()` 함수
- `backend/services/scheduler.py` — 수정 대상

---

## 구현 상세

### 1. KIS 거래일 확인 API

KIS 엔드포인트: `GET /uapi/domestic-stock/v1/quotations/chk-holiday`

파라미터:
```
BASS_DT: 조회할 날짜 (YYYYMMDD)
```

응답 예시 (output1 배열):
```json
{
  "output": [
    {
      "bass_dt": "20260505",
      "wday_dvsn_cd": "02",   // 01=월,02=화,...,07=일
      "bzdy_yn": "N",          // Y=영업일, N=휴장일
      "tr_day_yn": "N",        // Y=거래일, N=비거래일
      "opnd_yn": "N",          // Y=개장, N=휴장
      "sttl_day_yn": "N"
    }
  ]
}
```

`tr_day_yn == "Y"` 이면 거래일.

헤더: `tr_id = "CTCA0903R"` (조회)

### 2. `backend/services/kis/domestic/service.py` 에 함수 추가

```python
async def check_trading_day(date_str: str) -> bool:
    """KIS API로 해당 날짜가 주식 거래일인지 확인한다.
    
    Args:
        date_str: YYYYMMDD 형식
    Returns:
        True = 거래일, False = 비거래일/조회실패
    """
```

호출 패턴은 기존 `get_current_price()` 등과 동일하게 kis_client 사용.

tr_id: `"CTCA0903R"`
params: `{"BASS_DT": date_str}`

응답에서 `output[0]["tr_day_yn"] == "Y"` 이면 True 반환.
실패 또는 예외 시 False 반환 (보수적 처리 — 불확실하면 스킵).

### 3. `backend/services/settings_store.py` 에 헬퍼 함수 추가

```python
def get_setting(key: str, default: Any = None) -> Any:
    """단일 키 조회. 없으면 default 반환."""
```

기존 `list_settings()` 패턴을 재사용해 단건 조회.

### 4. `backend/services/scheduler.py` 수정

#### A. `job_refresh_kis_token()` 끝에 거래일 확인 + 플래그 세팅 추가

```python
async def job_refresh_kis_token() -> None:
    # ... 기존 토큰 갱신 로직 유지 ...
    
    # 오늘 거래일 여부 확인 → system_settings에 플래그 저장
    try:
        from .kis.domestic.service import check_trading_day
        from .settings_store import upsert_setting
        from datetime import datetime
        from zoneinfo import ZoneInfo
        
        today_yyyymmdd = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")
        is_trading = await check_trading_day(today_yyyymmdd)
        
        upsert_setting(
            key="schedule_skip_today",
            value=str(not is_trading).lower(),   # "true" or "false"
            value_type="string",
            description="오늘 비거래일 여부 (S1이 매일 갱신)",
            actor="scheduler_s1",
        )
        if not is_trading:
            logger.info("INFO: [Job1] 오늘(%s)은 비거래일 — S2~S5 스킵 플래그 세팅", today_yyyymmdd)
        else:
            logger.info("INFO: [Job1] 오늘(%s)은 거래일 — 정상 진행", today_yyyymmdd)
    except Exception as exc:
        logger.error("FAIL: [Job1] 거래일 확인 실패 — S2~S5는 정상 실행 reason=%s", exc)
        # 실패 시 플래그 세팅 안 함 → 나머지 job은 정상 실행
```

#### B. `job_market_tone_analysis()` (S2) 앞에 스킵 체크 추가

```python
async def job_market_tone_analysis() -> None:
    logger.info("START: [Job2] 시장 톤 분석 (08:00 KST)")
    
    # 비거래일 스킵 체크
    try:
        from .settings_store import get_setting
        if get_setting("schedule_skip_today") == "true":
            logger.info("SKIP: [Job2] 비거래일 — 시장 톤 분석 스킵")
            return
    except Exception:
        pass  # 조회 실패 시 정상 실행
    
    # ... 기존 로직 유지 ...
```

동일 패턴을 **S3 (job_universe_filter), S4 (job_hybrid_screening), S5 (job_rulepack_generation)** 에도 적용.
각각 "Job3", "Job4", "Job5" 레이블로 로그.

---

## 완료 기준

```bash
python -m py_compile backend/services/kis/domestic/service.py && echo "service OK"
python -m py_compile backend/services/settings_store.py && echo "settings_store OK"
python -m py_compile backend/services/scheduler.py && echo "scheduler OK"
python -c "from backend.services.kis.domestic.service import check_trading_day; print('import OK')"
python -c "from backend.services.settings_store import get_setting; print('get_setting OK')"
```

OUTBOX(`docs/agent-comm/OUTBOX_EXECUTOR_trading_day_check.md`)에 결과 작성.
