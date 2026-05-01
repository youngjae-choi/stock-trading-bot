# INBOX_EXECUTOR_s4_screening — S4 Hybrid Screening 구현

## 작업 목표
S4 하이브리드 스크리닝 (08:30 KST) 구현.
S3에서 DB에 저장한 상위 30종목을 LLM(llm_router)이 정성 평가해 suitability_score를 부여하고
결과를 `hybrid_screening_results` 테이블에 저장한다.

---

## 구현 파일 목록

| 파일 | 유형 | 내용 |
|------|------|------|
| `backend/services/engine/hybrid_screening.py` | 신규 | S4 핵심 로직 |
| `backend/api/routes/screening.py` | 신규 | REST 엔드포인트 2개 |
| `backend/services/scheduler.py` | 수정 | job_hybrid_screening 추가 (08:30 KST) |
| `backend/main.py` | 수정 | screening_router 등록 |

---

## 1. `backend/services/engine/hybrid_screening.py` (신규)

### 모듈 docstring
```python
"""하이브리드 스크리닝 서비스 (S4 — 08:30 KST).

S3 유니버스 필터 결과(top 30)를 LLM에 넘겨 정성 적합도 점수를 받고
hybrid_screening_results 테이블에 저장한다.

뉴스 데이터는 이번 버전에서 제외한다 (S4-v2에서 추가 예정).
LLM 호출 실패 시 provider="none"으로 저장하고 서버는 계속 실행된다.
"""
```

### 임포트
```python
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from ..db import get_connection
from .universe_filter import get_today_universe
from . import llm_router
```

### DB 테이블 생성 (`_ensure_table`)
```sql
CREATE TABLE IF NOT EXISTS hybrid_screening_results (
    id              TEXT PRIMARY KEY,
    trade_date      TEXT NOT NULL,
    candidates      TEXT NOT NULL DEFAULT '[]',
    skipped         TEXT NOT NULL DEFAULT '[]',
    overall_confidence REAL NOT NULL DEFAULT 0.0,
    provider        TEXT NOT NULL DEFAULT '',
    raw_input_count INTEGER NOT NULL DEFAULT 0,
    output_count    INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hybrid_screening_trade_date ON hybrid_screening_results(trade_date);
```

### 프롬프트 빌드 함수 (`_build_prompt`)
- 인자: `candidates_30: list[dict]`, `market_tone: dict | None`
- `backend/prompts/0830_opus_screening.md` 에 정의된 포맷 그대로 사용
- market_tone이 None이면 `{"tone": "neutral", "confidence": 0.5, "summary": "데이터 없음"}` 기본값 사용
- 뉴스 요약은 `{news_summary}` 자리에 `"뉴스 데이터 미제공 — 이번 버전 제외"` 고정 문자열 삽입
- candidates_30은 symbol, name, price, change_rate, trade_amount, score, rank 필드를 JSON으로 직렬화해 삽입

프롬프트 템플릿:
```
# 08:30 Opus — 하이브리드 스크리닝 (정성 점수 부여)

## 역할
시스템이 정량 점수로 좁힌 30종목 후보를 받아, 각 종목의 **정성 적합도 점수**만 매긴다.
"매수해라"가 아니라 "이 종목은 OO 이유로 적합도 X점"이라고만 응답한다.

## 절대 규칙
- 출력은 반드시 아래 JSON 포맷
- 종목별로 매수/매도 지시 금지 (suitability_score만 부여)
- 입력에 없는 종목을 추가하지 않는다
- 점수 근거는 입력 데이터에서만 끌어온다
- 모르는 종목은 suitability_score를 0.3 이하로

## 입력 데이터

### 30종목 후보
{candidates_json}

### 시장 톤
{market_tone_json}

### 뉴스 요약
{news_summary}

## 출력 포맷 (반드시 이대로, 다른 텍스트 없이 JSON만)
{{
  "schema_version": "1.0",
  "generated_at": "YYYY-MM-DDTHH:MM:SS+09:00",
  "model": "llm",
  "candidates": [
    {{
      "ticker": "005930",
      "name": "삼성전자",
      "sector": "기타",
      "suitability_score": 0.72,
      "reason": "한 문장 핵심 근거",
      "matched_themes": ["테마1"],
      "risk_factors": ["리스크1"],
      "data_source": "macro"
    }}
  ],
  "skipped": [
    {{"ticker": "XXXXXX", "reason": "정보 부족"}}
  ],
  "overall_confidence": 0.7
}}

## suitability_score 기준
- 0.8~1.0: 오늘 톤/테마와 강하게 부합, 명확한 재료 있음
- 0.5~0.8: 부분적으로 부합, 일반적 매력
- 0.3~0.5: 약한 근거, 큰 매력 없음
- 0.0~0.3: 부합하지 않거나 정보 부족

시장 톤 confidence < 0.4이면 모든 suitability_score를 0.5 이하로 보수적으로 평가한다.
```

### LLM 응답 파싱 (`_parse_screening_response`)
- market_tone.py의 `_parse_tone_response` 패턴과 동일하게:
  1. 마크다운 코드 블록(```) 제거
  2. `json.loads()` 시도
  3. 실패 시 `{`부터 `}` 사이 추출 후 재시도
- 파싱 성공 시 반환:
  ```python
  {
      "candidates": list,        # 각 항목에 ticker, name, suitability_score, reason, matched_themes, risk_factors, data_source
      "skipped": list,
      "overall_confidence": float,
  }
  ```
- candidates 각 항목에서 suitability_score는 0.0~1.0 범위 강제 (`max(0.0, min(1.0, ...)`)

### 메인 함수 (`run_hybrid_screening`)
```python
async def run_hybrid_screening() -> dict[str, Any]:
    """하이브리드 스크리닝을 실행하고 DB에 저장한 뒤 결과를 반환한다."""
```

흐름:
1. `from zoneinfo import ZoneInfo` → `today` 계산 (KST)
2. `_ensure_table()` 호출
3. `get_today_universe(today)` 호출 → `universe` dict
   - universe가 None이거나 items가 비어있으면:
     - `logger.warning("WARN: HybridScreening S3 결과 없음 — 스크리닝 생략 trade_date=%s", today)`
     - DB에 빈 결과 저장 (provider="none", output_count=0)
     - 결과 반환 (ok=True, skipped_reason="no_universe")
4. `items = universe["items"]` (최대 30개)
5. 시장 톤 조회: `get_connection()` → `market_tone_results` 에서 `SELECT tone, confidence, summary FROM market_tone_results WHERE trade_date=? ORDER BY created_at DESC LIMIT 1`
   - 실패해도 None으로 계속 진행
6. `prompt = _build_prompt(items, market_tone)` 호출
7. `llm_result = await llm_router.call_llm(prompt, task_name="하이브리드 스크리닝")` 호출
8. llm_result["ok"]이면 `_parse_screening_response(llm_result["raw"])` 파싱 시도
   - 파싱 실패 시 logger.warning + 빈 결과 사용
9. provider = llm_result["provider"]
10. DB 저장 (INSERT OR REPLACE)
11. 결과 dict 반환:
```python
{
    "ok": True,
    "trade_date": today,
    "provider": provider,
    "raw_input_count": len(items),
    "output_count": len(candidates),
    "overall_confidence": overall_confidence,
    "candidates": candidates,
    "skipped": skipped,
    "id": record_id,
}
```

### 조회 함수 (`get_today_screening`)
```python
def get_today_screening(trade_date: str) -> dict[str, Any] | None:
    """DB에서 특정 날짜의 하이브리드 스크리닝 결과를 조회한다."""
```
- `_ensure_table()` 호출
- `SELECT * FROM hybrid_screening_results WHERE trade_date=? ORDER BY created_at DESC LIMIT 1`
- 행이 없으면 None 반환
- candidates, skipped 필드가 str이면 `json.loads()` 파싱
- dict 반환

---

## 2. `backend/api/routes/screening.py` (신규)

```python
"""Hybrid Screening API routes (S4)."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ...api.dependencies import require_console_user
from ...config import validate_config
from ...services.engine import hybrid_screening as screening_svc

logger = logging.getLogger("BackendScreeningAPI")

router = APIRouter(
    prefix="/api/v1/screening",
    tags=["screening"],
    dependencies=[Depends(require_console_user)],
)


@router.get("/today", summary="오늘 하이브리드 스크리닝 결과 조회")
async def get_screening_today():
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    logger.info("START: GET /api/v1/screening/today trade_date=%s", today)
    result = screening_svc.get_today_screening(today)
    logger.info("SUCCESS: GET /api/v1/screening/today found=%s", result is not None)
    return {
        "ok": True,
        "source": "backend",
        "live": True,
        "payload": {"screening": result, "trade_date": today},
    }


@router.post("/run", summary="하이브리드 스크리닝 즉시 실행")
async def run_screening_now():
    if not validate_config():
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": "KIS config not set", "source": "backend", "live": True},
        )
    logger.info("START: POST /api/v1/screening/run (manual trigger)")
    try:
        result = await screening_svc.run_hybrid_screening()
        logger.info(
            "SUCCESS: POST /api/v1/screening/run output_count=%d provider=%s",
            result.get("output_count", 0),
            result.get("provider", ""),
        )
        return {"ok": True, "source": "backend", "live": True, "payload": result}
    except Exception as exc:
        logger.error("FAIL: POST /api/v1/screening/run — %s", exc)
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": str(exc), "source": "backend", "live": True},
        )
```

---

## 3. `backend/services/scheduler.py` 수정

`job_universe_filter` 함수 바로 다음에 아래 함수 추가:

```python
async def job_hybrid_screening() -> None:
    """Job 4 (08:30 KST): 하이브리드 스크리닝 (S4 구현).

    LLM이 S3 유니버스 필터 결과를 정성 평가해 suitability_score를 부여한다.
    """
    logger.info("START: [Job4] 하이브리드 스크리닝 (08:30 KST)")
    try:
        from .engine.hybrid_screening import run_hybrid_screening
        result = await run_hybrid_screening()
        logger.info(
            "SUCCESS: [Job4] 하이브리드 스크리닝 완료 output=%d provider=%s confidence=%.2f",
            result.get("output_count", 0),
            result.get("provider", ""),
            result.get("overall_confidence", 0.0),
        )
    except Exception as exc:
        logger.error("FAIL: [Job4] 하이브리드 스크리닝 실패 — reason=%s", exc)
```

기존 job 번호 재정렬 (scheduler.py):
- 기존 Job 4 (`job_intraday_liquidation`) → Job 5로 변경 (함수명·주석·로그 모두)
- 기존 Job 5 (`job_data_backup`) → Job 6
- 기존 Job 6 (`job_us_market_watch`) → Job 7

`_build_scheduler()` 함수에 아래 job 추가 (job_universe_filter 등록 바로 다음):
```python
scheduler.add_job(
    job_hybrid_screening,
    CronTrigger(hour=8, minute=30, timezone="Asia/Seoul"),
    id="job_hybrid_screening",
    name="하이브리드 스크리닝",
    replace_existing=True,
)
```

---

## 4. `backend/main.py` 수정

기존 imports에 추가:
```python
from .api.routes.screening import router as screening_router
```

`app.include_router` 목록에 추가 (universe_filter_router 바로 다음):
```python
app.include_router(screening_router)
```

---

## 참조 파일 (읽기 전용, 수정 금지)

- `backend/services/engine/market_tone.py` — LLM 호출 패턴, `_parse_tone_response` 패턴
- `backend/services/engine/llm_router.py` — `call_llm(prompt, task_name)` 인터페이스
- `backend/services/engine/universe_filter.py` — `get_today_universe(trade_date)` 함수
- `backend/api/routes/universe.py` — router 패턴, `require_console_user` 의존성 사용법
- `backend/prompts/0830_opus_screening.md` — 프롬프트 포맷 참조 (직접 파일 로딩 불필요, 위 템플릿 사용)
- `backend/api/dependencies.py` — `require_console_user` 위치 확인

---

## 완료 기준

작업 완료 후 다음을 확인하고 OUTBOX에 결과 작성:

1. py_compile 검증:
```bash
python -m py_compile backend/services/engine/hybrid_screening.py && echo "OK"
python -m py_compile backend/api/routes/screening.py && echo "OK"
python -m py_compile backend/services/scheduler.py && echo "OK"
python -m py_compile backend/main.py && echo "OK"
```

2. OUTBOX(`docs/agent-comm/OUTBOX_EXECUTOR_s4_screening.md`)에 작성:
   - 생성/수정한 파일 목록
   - py_compile 결과 (OK / 에러 메시지)
   - 특이사항 또는 주의사항
