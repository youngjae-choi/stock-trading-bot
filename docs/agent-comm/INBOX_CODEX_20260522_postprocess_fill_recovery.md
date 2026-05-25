# INBOX: S9-S10 Fill 누락 수정 + 오늘 데이터 복구

**날짜:** 2026-05-22  
**우선순위:** CRITICAL  
**대상:** Codex (Backend)

---

## 배경 및 원인

오늘(2026-05-22) 첫 완전 사이클이 돌았으나 매도 체결 결과가 전혀 기록되지 않았다.

**핵심 원인:**  
`job_postprocess_pipeline()` (backend/services/scheduler.py) 안에서:
1. S9 → `run_eod_liquidation()` 실행 (매도주문 4건 접수: kis_order_no 0000032780/0000032798/0000032806/0000032822)
2. S9 → `decision_engine.deactivate()` 호출 → **fill_poller.stop()** 실행 ← 여기서 폴러 중단
3. S10 → `job_review_audit()` 즉시 실행 ← 체결 확인 전에 리뷰 실행

결과:
- `trading_orders` sell 4건: `status='submitted'`, `price=0.0`, `name=''`
- `fills` 테이블: sell fill 없음
- `daily_trade_summary`: 2026-05-22 레코드 없음
- `daily_review_reports`: `pnl_status='unverified'`, `total_pnl=0.0`
- `learning_memories` 오늘: 0건
- False Positive 분석: 0건 (체결 데이터 없어 매도완료 페어 없음)

---

## 작업 1: scheduler.py — S9 후 fill 폴링 삽입

**파일:** `backend/services/scheduler.py`  
**함수:** `job_postprocess_pipeline()`

S9 완료 후, S10 실행 전에 fill 폴링을 1회 실행한다.

```python
# S9 완료 직후 아래 블록 삽입:
logger.info("START: [PostProcess] S9 후 fill 폴링 (30초 대기 후)")
await asyncio.sleep(30)  # KIS 체결 확인 대기
try:
    from zoneinfo import ZoneInfo as _ZI
    _today_pp = datetime.now(_ZI("Asia/Seoul")).strftime("%Y-%m-%d")
    from .engine.fill_poller import poll_once as _poll_once
    _fill_result = await _poll_once(_today_pp)
    logger.info(
        "SUCCESS: [PostProcess] fill 폴링 완료 filled=%d unchanged=%d",
        _fill_result.get("filled", 0),
        _fill_result.get("unchanged", 0),
    )
except Exception as _fill_exc:
    logger.warning("WARN: [PostProcess] fill 폴링 실패 (S10 계속 진행) reason=%s", _fill_exc)
```

**삽입 위치:** S9 결과 audit 완료 직후, `logger.info("START: [PostProcess] S10 Review & Audit")` 바로 전 줄.

`asyncio`와 `datetime`은 이미 scheduler.py 상단에 import되어 있으니 별도 import 불필요.

---

## 작업 2: 수동 복구 API 엔드포인트 추가

**파일:** `backend/api/routes/trading_monitor.py`

아래 엔드포인트를 파일 끝에 추가한다:

```python
@router.post("/admin/recover-fills")
async def recover_fills(trade_date: str = Query(None, description="YYYY-MM-DD (기본값: 오늘)")):
    """오늘 submitted 매도주문 fill 재폴링 + S10 재실행.
    
    장 종료 후 fill_poller가 sell 주문 체결을 놓쳤을 때 수동으로 복구한다.
    """
    from zoneinfo import ZoneInfo
    from ...services.engine.fill_poller import poll_once
    from ...services.scheduler import job_review_audit
    
    today = trade_date or datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    logger.info("START: POST /api/v1/trading/admin/recover-fills date=%s", today)
    
    try:
        fill_result = await poll_once(today)
        logger.info("fill 폴링 완료 filled=%d", fill_result.get("filled", 0))
    except Exception as exc:
        logger.warning("fill 폴링 실패 (S10 계속) reason=%s", exc)
        fill_result = {"filled": 0, "error": str(exc)}
    
    try:
        await job_review_audit()
        logger.info("S10 재실행 완료")
        s10_ok = True
    except Exception as exc:
        logger.error("S10 재실행 실패 reason=%s", exc)
        s10_ok = False
    
    return {
        "ok": True,
        "trade_date": today,
        "fill_result": fill_result,
        "s10_rerun": s10_ok,
    }
```

**주의:** `datetime`이 이미 import되어 있는지 확인 후 없으면 상단에 추가.

---

## 작업 3: sell 주문에 name 필드 채우기

**현상:** sell 주문의 `name=''` — S9 청산 시 종목명 없이 저장됨.

**파일:** `backend/services/engine/eod_liquidation.py` (또는 order_executor.py)

sell 주문 저장 시 `name` 필드를 채우는 방법:
- `trading_orders` INSERT 또는 UPDATE 시 symbol로 `symbols` 테이블에서 name을 조회해 채운다
- 기존 submitted sell 주문들의 name도 아래 쿼리로 일괄 업데이트:
  ```sql
  UPDATE trading_orders t
  SET name = (SELECT name FROM symbols WHERE code = t.symbol LIMIT 1)
  WHERE side = 'sell' AND (name IS NULL OR name = '') AND date(created_at) = '2026-05-22'
  ```
  이 쿼리를 recover-fills 엔드포인트 실행 시 함께 처리한다.

---

## 작업 4: 오늘 데이터 즉시 복구 실행

코드 수정 후 서버를 재시작하고 아래 API를 즉시 호출한다:

```bash
curl -s -X POST "http://127.0.0.1:8000/api/v1/trading/admin/recover-fills?trade_date=2026-05-22" \
  -H "Cookie: [세션 쿠키]" | python3 -m json.tool
```

세션 인증이 필요한 경우 Bearer token 또는 내부 호출 방식 사용.

---

## 작업 5: False Positive 자동 실행 확인

`job_review_audit()` 내부 또는 `daily_summary.py`에서 `generate_false_positives_for_date(trade_date)` 호출이 포함되어 있는지 확인한다.

`backend/services/engine/daily_summary.py` 228-229줄:
```python
from .false_positive import generate_false_positives_for_date
fp_result = generate_false_positives_for_date(trade_date)
```
이미 있으면 S10 재실행 시 자동으로 처리됨. 없으면 추가.

---

## 완료 기준

1. `backend/services/scheduler.py` — S9 후 fill 폴링 코드 삽입 완료
2. `backend/api/routes/trading_monitor.py` — recover-fills 엔드포인트 추가 완료
3. eod_liquidation.py / order_executor.py — sell 주문 name 필드 채우기
4. 서버 재시작 후 `POST /api/v1/trading/admin/recover-fills?trade_date=2026-05-22` 호출
5. `trading_orders` sell 4건 → `status='filled'`, `price > 0` 확인
6. `daily_trade_summary` 2026-05-22 레코드 생성 확인
7. `daily_review_reports` 2026-05-22 `pnl_status='verified'` 확인
8. `false_positive_cases` 2026-05-22 신규 케이스 확인

결과를 `docs/agent-comm/OUTBOX_CODEX_20260522_postprocess_fill_recovery.md` 에 기록하라.
