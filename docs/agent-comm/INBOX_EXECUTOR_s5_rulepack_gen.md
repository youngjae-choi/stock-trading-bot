# INBOX_EXECUTOR_s5_rulepack_gen — S5 RulePack 자동 생성 구현

## 작업 목표
S5 (08:45 KST): S4 스크리닝 결과 + 시장 톤 + 어제 RulePack을 LLM에 넘겨
오늘의 RulePack JSON을 생성하고 L1 캡 적용 후 DB에 저장한다.

---

## 구현 파일 목록

| 파일 | 유형 | 내용 |
|------|------|------|
| `backend/services/engine/rulepack_generation.py` | 신규 | S5 핵심 로직 |
| `backend/api/routes/rulepack_gen.py` | 신규 | 수동 실행 엔드포인트 |
| `backend/services/scheduler.py` | 수정 | job_rulepack_generation 추가 (08:45 KST) |
| `backend/main.py` | 수정 | rulepack_gen_router 등록 |

---

## 참조 파일 (읽기 전용, 절대 수정 금지)

- `backend/prompts/0845_gpt_rulepack_generation.md` — LLM 프롬프트 템플릿
- `backend/services/engine/hybrid_screening.py` — `get_today_screening(trade_date)` 함수
- `backend/services/engine/rulepack_store.py` — `create_rulepack()`, `get_active_rulepack_for_date()`, `activate_rulepack()`, `update_rulepack_validation()`, `list_rulepacks()`
- `backend/config/risk_constants.py` — `apply_all_caps(rulepack, pm_settings)` 함수
- `backend/services/settings_store.py` — `list_settings()` (key/value 구조)
- `backend/services/engine/llm_router.py` — `call_llm(prompt, task_name)` 인터페이스
- `backend/services/engine/market_tone.py` — LLM 호출 / JSON 파싱 패턴 참조
- `backend/api/routes/screening.py` — 라우터 패턴 참조

---

## 1. `backend/services/engine/rulepack_generation.py` (신규)

### 모듈 docstring
```python
"""RulePack 자동 생성 서비스 (S5 — 08:45 KST).

S4 하이브리드 스크리닝 결과, 시장 톤, 어제 RulePack을 조합해
LLM에 RulePack JSON 생성을 요청한다.

결과에 L1 절대한도(risk_constants) + PM Settings 캐스케이딩 캡을 적용하고
rulepacks 테이블에 저장한 뒤 자동 활성화한다.

RulePack 스키마: backend/prompts/0845_gpt_rulepack_generation.md 참조.
machine_rules 컬럼에 GPT 생성 전체 JSON을 저장한다.
"""
```

### 임포트
```python
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from ..db import get_connection
from ..settings_store import list_settings
from . import llm_router
from .hybrid_screening import get_today_screening
from .rulepack_store import (
    create_rulepack,
    activate_rulepack,
    get_active_rulepack_for_date,
    update_rulepack_validation,
)
from ...config.risk_constants import apply_all_caps

logger = logging.getLogger("RulePackGenerationService")
```

### PM Settings 로드 함수 (`_load_pm_settings`)
system_settings 테이블에서 risk 관련 키를 로드한다.
키가 없으면 L1 상수를 기본값으로 사용한다.

```python
def _load_pm_settings() -> dict[str, Any]:
    """system_settings에서 PM 설정값을 로드한다.
    
    키가 없으면 L1 상수를 기본값으로 사용한다.
    apply_all_caps()에 넘길 pm_settings 딕셔너리를 반환한다.
    """
    from ...config.risk_constants import (
        DAILY_LOSS_LIMIT_RATE_L1, MAX_POSITIONS_L1,
        STOP_LOSS_RATE_L1, MAX_POSITION_SIZE_RATE_L1,
        TAKE_PROFIT_RATE_L1, MAX_HOLDING_MINUTES_L1,
    )
    defaults = {
        "daily_loss_limit_rate": DAILY_LOSS_LIMIT_RATE_L1,
        "max_positions": MAX_POSITIONS_L1,
        "stop_loss_rate": STOP_LOSS_RATE_L1,
        "max_position_size_rate": MAX_POSITION_SIZE_RATE_L1,
        "take_profit_rate": TAKE_PROFIT_RATE_L1,
        "max_holding_minutes": MAX_HOLDING_MINUTES_L1,
    }
    try:
        settings = list_settings()  # [{key, value, ...}, ...]
        loaded = {s["key"]: s["value"] for s in settings}
        for k in defaults:
            if k in loaded:
                defaults[k] = loaded[k]
    except Exception as exc:
        logger.warning("WARN: RulePackGen PM settings 로드 실패 — L1 기본값 사용 %s", exc)
    return defaults
```

### 시장 톤 조회 함수 (`_get_market_tone`)
```python
def _get_market_tone(trade_date: str) -> dict[str, Any] | None:
    """market_tone_results에서 오늘 톤을 조회한다."""
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT tone, confidence, summary FROM market_tone_results WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
                (trade_date,),
            ).fetchone()
        if row:
            return {"tone": row["tone"], "confidence": row["confidence"], "summary": row["summary"]}
    except Exception as exc:
        logger.warning("WARN: RulePackGen 시장 톤 조회 실패 — %s", exc)
    return None
```

### 어제 RulePack 조회 함수 (`_get_yesterday_rulepack`)
```python
def _get_yesterday_rulepack(today: str) -> dict[str, Any] | None:
    """어제 날짜의 활성 RulePack을 조회한다. 없으면 None."""
    from datetime import date, timedelta
    yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    try:
        return get_active_rulepack_for_date(yesterday)
    except Exception as exc:
        logger.warning("WARN: RulePackGen 어제 RulePack 조회 실패 — %s", exc)
        return None
```

### 프롬프트 빌드 함수 (`_build_prompt`)
0845_gpt_rulepack_generation.md의 템플릿 구조를 인라인으로 사용한다.
str.replace()로 플레이스홀더를 치환한다 (str.format() 사용 금지).

```python
def _build_prompt(
    market_tone: dict | None,
    screening: dict | None,
    yesterday_rulepack: dict | None,
) -> str:
    """0845_gpt_rulepack_generation.md 기반 프롬프트 빌드."""
    # market_tone 직렬화
    if market_tone:
        market_tone_str = json.dumps(market_tone, ensure_ascii=False, indent=2)
    else:
        market_tone_str = '{"tone": "neutral", "confidence": 0.5, "summary": "데이터 없음"}'

    # screening candidates 직렬화
    if screening and screening.get("candidates"):
        candidates = screening["candidates"]
        screening_str = json.dumps(candidates, ensure_ascii=False, indent=2)
    else:
        screening_str = "[]"

    # 어제 rulepack 직렬화
    if yesterday_rulepack and yesterday_rulepack.get("machine_rules"):
        mr = yesterday_rulepack["machine_rules"]
        if isinstance(mr, str):
            yesterday_str = mr
        else:
            yesterday_str = json.dumps(mr, ensure_ascii=False, indent=2)
    else:
        yesterday_str = "{}"

    # 프롬프트 템플릿 (0845_gpt_rulepack_generation.md 내용 기반)
    _TEMPLATE = """너는 JSON 변환기다. Opus의 정성 판단 결과를 시스템이 실행 가능한 RulePack JSON으로 변환한다.
새로운 매매 전략을 발명하지 않는다. 입력된 분석 결과를 정해진 스키마에 채워넣기만 한다.

## 절대 규칙
- 출력은 순수 JSON 한 덩어리만 (마크다운 코드블록 금지, 설명 텍스트 금지)
- 아래 스키마의 필드명/타입을 정확히 지킨다
- 시스템 한도를 절대 초과하지 않는다 (초과해도 자동 덮어쓰기되지만 reject 카운트가 올라감)
- Top 10 종목은 Opus 산출물의 suitability_score 상위에서만 선택
- 입력에 없는 종목 추가 금지

## 시스템 한도 (절대 변경 불가)
- daily_loss_limit_rate: -0.10보다 큰 음수 금지
- max_positions: 30 초과 금지
- stop_loss_rate: -0.05보다 느슨한 값 금지
- max_position_size_rate: 0.30 초과 금지
- take_profit_rate: 0.30 초과 금지

## 출력 스키마 (이 구조 그대로)
{"schema_version":"1.0","rulepack_id":"RP_YYYYMMDD_HHMM","generated_at":"YYYY-MM-DDTHH:MM:SS+09:00","valid_for_date":"YYYY-MM-DD","ai_source":{"global_brief":"gemini","market_tone":"llm","screening":"llm","rulepack_structuring":"llm","validation":"system"},"market_context":{"tone_score":0.0,"tone_label":"neutral","confidence":0.0},"risk_limits":{"daily_loss_limit_rate":-0.03,"max_positions":7,"stop_loss_rate":-0.02,"take_profit_rate":0.05,"max_position_size_rate":0.10,"max_holding_minutes":360},"entry_rules":{"buy_signal_priority":["volume_surge","price_breakout","news_match"],"min_volume_multiple_5d":1.5,"min_price_change_pct":1.0,"max_price_change_pct":5.0,"exclude_market_open_minutes":5,"exclude_market_close_minutes":30},"exit_rules":{"stop_loss_trigger":"rate_based","take_profit_trigger":"rate_based","force_close_at":"15:20","max_concurrent_trades_per_ticker":1},"candidates":[{"ticker":"000000","name":"종목명","rank":1,"suitability_score":0.7,"max_buy_amount_krw":0,"reason_short":"한 줄 사유"}],"fallback_policy":{"if_market_data_unavailable":"skip_trading_today","if_loss_limit_hit":"close_all_block_new","if_api_error_count_exceeds":5},"notes":""}

## 변환 규칙
- tone_score >= 0.5 (risk_on): max_positions = 10
- tone_score >= 0.0 (neutral): max_positions = 7
- tone_score < 0.0 (risk_off): max_positions = 5
- candidates: suitability_score >= 0.5인 것만, 상위 10개, max_buy_amount_krw=0 (시스템이 채움)
- 어제 RulePack 대비 candidates 70% 이상 교체 시 notes에 "후보 대폭 교체" 명시

## 절대 출력 금지
- 마크다운 코드블록 (```json)
- 설명 텍스트
- 주석 (//)
첫 글자는 반드시 '{', 마지막 글자는 '}' 이어야 한다.

## 입력 자료

### 시장 톤
{market_tone}

### Opus 스크리닝 결과 (candidates)
{screening_output}

### 어제 RulePack
{yesterday_rulepack}
"""
    return (
        _TEMPLATE
        .replace("{market_tone}", market_tone_str)
        .replace("{screening_output}", screening_str)
        .replace("{yesterday_rulepack}", yesterday_str)
    )
```

### LLM 응답 파싱 (`_parse_rulepack_response`)
```python
def _parse_rulepack_response(raw: str) -> dict[str, Any]:
    """LLM 응답에서 순수 JSON을 추출해 파싱한다.
    
    market_tone.py의 _parse_tone_response 패턴과 동일.
    """
    text = raw.strip()
    # 마크다운 코드블록 제거
    if "```" in text:
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    
    # JSON 파싱 시도
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # { } 범위 추출 후 재시도
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            data = json.loads(text[start:end])
        else:
            raise
    
    # 필수 필드 확인
    if "risk_limits" not in data:
        raise ValueError("LLM 응답에 risk_limits 없음")
    
    return data
```

### L1 캡 적용 및 검증 결과 빌드 (`_apply_caps_and_build_validation`)
```python
def _apply_caps_and_build_validation(
    rulepack_data: dict, pm_settings: dict
) -> tuple[dict, dict]:
    """L1 캐스케이딩 캡을 적용하고 validation dict를 반환한다.
    
    Returns:
        (capped_rulepack, validation_dict)
    """
    capped, cap_results = apply_all_caps(rulepack_data, pm_settings)
    
    capped_fields = [r for r in cap_results if r.capped_by != "none"]
    
    validation = {
        "schema": "pass",
        "risk_policy": "pass",
        "runtime": "pending",
        "cap_applied": [
            {
                "field": r.field,
                "original": r.original,
                "capped": r.capped,
                "capped_by": r.capped_by,
                "reason": r.reason,
            }
            for r in capped_fields
        ],
    }
    
    return capped, validation
```

### 메인 함수 (`run_rulepack_generation`)
```python
async def run_rulepack_generation() -> dict[str, Any]:
    """RulePack을 자동 생성하고 DB에 저장한 뒤 활성화한다."""
```

흐름:
1. `from zoneinfo import ZoneInfo` → `today` 계산 (KST)
2. S4 스크리닝 결과 조회: `get_today_screening(today)`
   - None이면 logger.warning 후 `{"ok": True, "skipped_reason": "no_screening", ...}` 반환 (DB 저장 생략)
3. 시장 톤 조회: `_get_market_tone(today)`
4. 어제 RulePack 조회: `_get_yesterday_rulepack(today)`
5. PM Settings 로드: `_load_pm_settings()`
6. 프롬프트 빌드: `_build_prompt(market_tone, screening, yesterday_rulepack)`
7. LLM 호출: `await llm_router.call_llm(prompt, task_name="RulePack 생성")`
8. LLM 실패 시:
   - 어제 RulePack이 있으면 복제 후 저장 (valid_for_date = today, notes = "전일 RulePack 복제")
   - 없으면 fallback_reason="llm_failed" 반환
9. LLM 성공 시:
   - `_parse_rulepack_response(llm_result["raw"])` 파싱
   - 파싱 실패 시 logger.warning + raw[:200] 로그 → 어제 RulePack 복제 fallback
10. L1 캡 적용: `_apply_caps_and_build_validation(rulepack_data, pm_settings)`
11. DB 저장: `create_rulepack(trade_date=today, machine_rules=capped_rulepack, mode="auto", summary=..., validation=validation)`
12. validation 업데이트: `update_rulepack_validation(rulepack_id, validation)`
13. 자동 활성화: `activate_rulepack(rulepack_id)` (ValueError 시 logger.error, status는 validated로 남음)
14. 결과 반환:
```python
{
    "ok": True,
    "trade_date": today,
    "provider": provider,
    "rulepack_id": rulepack_id,
    "cap_applied_count": len(validation.get("cap_applied", [])),
    "candidates_count": len(rulepack_data.get("candidates", [])),
    "status": "active" | "validated",
}
```

### 조회 함수 (`get_today_rulepack`)
```python
def get_today_rulepack(trade_date: str) -> dict[str, Any] | None:
    """오늘 활성 RulePack을 반환한다."""
    return get_active_rulepack_for_date(trade_date)
```

---

## 2. `backend/api/routes/rulepack_gen.py` (신규)

```python
"""RulePack 자동 생성 API routes (S5)."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ...api.dependencies import require_console_user
from ...config import validate_config
from ...services.engine import rulepack_generation as gen_svc

logger = logging.getLogger("BackendRulePackGenAPI")

router = APIRouter(
    prefix="/api/v1/rulepack-gen",
    tags=["rulepack-gen"],
    dependencies=[Depends(require_console_user)],
)


@router.get("/today", summary="오늘 활성 RulePack 조회 (생성 결과)")
async def get_rulepack_gen_today():
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    logger.info("START: GET /api/v1/rulepack-gen/today trade_date=%s", today)
    result = gen_svc.get_today_rulepack(today)
    logger.info("SUCCESS: GET /api/v1/rulepack-gen/today found=%s", result is not None)
    return {
        "ok": True,
        "source": "backend",
        "live": True,
        "payload": {"rulepack": result, "trade_date": today},
    }


@router.post("/run", summary="RulePack 자동 생성 즉시 실행")
async def run_rulepack_gen_now():
    logger.info("START: POST /api/v1/rulepack-gen/run (manual trigger)")
    try:
        result = await gen_svc.run_rulepack_generation()
        logger.info(
            "SUCCESS: POST /api/v1/rulepack-gen/run rulepack_id=%s provider=%s",
            result.get("rulepack_id", ""),
            result.get("provider", ""),
        )
        return {"ok": True, "source": "backend", "live": True, "payload": result}
    except Exception as exc:
        logger.error("FAIL: POST /api/v1/rulepack-gen/run — %s", exc)
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": str(exc), "source": "backend", "live": True},
        )
```

---

## 3. `backend/services/scheduler.py` 수정

`job_hybrid_screening` 함수 바로 다음에 추가:

```python
async def job_rulepack_generation() -> None:
    """Job 5 (08:45 KST): RulePack 자동 생성 (S5 구현).

    S4 스크리닝 결과를 LLM에 넘겨 오늘의 RulePack JSON을 생성하고 자동 활성화한다.
    """
    logger.info("START: [Job5] RulePack 자동 생성 (08:45 KST)")
    try:
        from .engine.rulepack_generation import run_rulepack_generation
        result = await run_rulepack_generation()
        logger.info(
            "SUCCESS: [Job5] RulePack 생성 완료 rulepack_id=%s provider=%s caps=%d",
            result.get("rulepack_id", ""),
            result.get("provider", ""),
            result.get("cap_applied_count", 0),
        )
    except Exception as exc:
        logger.error("FAIL: [Job5] RulePack 생성 실패 — reason=%s", exc)
```

기존 job 번호 재정렬 (아래 함수명과 로그 메시지 모두 수정):
- 기존 Job 5 (`job_intraday_liquidation`) → Job 6
- 기존 Job 6 (`job_data_backup`) → Job 7
- 기존 Job 7 (`job_us_market_watch`) → Job 8

`_build_scheduler()`에 추가 (job_hybrid_screening 바로 다음):
```python
scheduler.add_job(
    job_rulepack_generation,
    CronTrigger(hour=8, minute=45, timezone="Asia/Seoul"),
    id="job_rulepack_generation",
    name="RulePack 자동 생성",
    replace_existing=True,
)
```

---

## 4. `backend/main.py` 수정

imports에 추가:
```python
from .api.routes.rulepack_gen import router as rulepack_gen_router
```

`app.include_router` 목록에 추가 (screening_router 바로 다음):
```python
app.include_router(rulepack_gen_router)
```

---

## 주의사항

1. `apply_all_caps()` 함수는 `rulepack["risk_limits"]` 키가 있어야 한다. 없으면 KeyError → 호출 전 확인 필요.
2. `activate_rulepack()` 내부에서 validation.risk_policy == "fail"이면 ValueError를 던진다. 우리는 항상 "pass"로 설정하므로 문제없다.
3. `create_rulepack()` 함수 파라미터: `trade_date`, `machine_rules`(dict), `summary`, `changes`, `mode`, `validation`

---

## 완료 기준

```bash
python -m py_compile backend/services/engine/rulepack_generation.py && echo "OK"
python -m py_compile backend/api/routes/rulepack_gen.py && echo "OK"
python -m py_compile backend/services/scheduler.py && echo "OK"
python -m py_compile backend/main.py && echo "OK"
```

OUTBOX(`docs/agent-comm/OUTBOX_EXECUTOR_s5_rulepack_gen.md`)에 결과 작성.
