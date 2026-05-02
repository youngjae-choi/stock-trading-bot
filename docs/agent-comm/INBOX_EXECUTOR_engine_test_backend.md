# INBOX_EXECUTOR_engine_test_backend — Engine Test 백엔드 API 구현

## 작업 목표
S1~S5 수동 테스트를 위한 백엔드 API 2개를 추가한다.

1. `POST /api/v1/engine/token-refresh` — S1 KIS 토큰 수동 갱신 트리거
2. `GET /api/v1/engine/logs` — 서버 로그 최근 N줄 조회 (스텝 필터 지원)

---

## 구현 파일 목록

| 파일 | 유형 | 내용 |
|------|------|------|
| `backend/api/routes/engine_test.py` | 신규 | 위 2개 엔드포인트 |
| `backend/main.py` | 수정 | engine_test_router 등록 |

---

## 참조 파일 (읽기 전용)

- `backend/services/kis/common/client.py` — `kis_client` 싱글턴, `get_token()` 메서드
- `backend/api/dependencies.py` — `require_console_user` 의존성
- `backend/api/routes/market_tone.py` — 라우터 패턴 참조
- `backend/main.py` — router 등록 패턴

---

## 1. `backend/api/routes/engine_test.py` (신규)

```python
"""Engine Test API — S1~S5 수동 실행 및 로그 조회."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ...api.dependencies import require_console_user

logger = logging.getLogger("BackendEngineTestAPI")

router = APIRouter(
    prefix="/api/v1/engine",
    tags=["engine-test"],
    dependencies=[Depends(require_console_user)],
)

# 로그 파일 경로 (프로젝트 루트 기준)
_LOG_FILE = Path(__file__).resolve().parents[3] / "logs" / "server.log"


@router.post("/token-refresh", summary="S1: KIS 토큰 수동 갱신")
async def token_refresh():
    """KIS 액세스 토큰을 강제 재발급한다 (캐시 무효화 후 호출)."""
    logger.info("START: POST /api/v1/engine/token-refresh (manual)")
    try:
        from ...services.kis.common.client import kis_client
        kis_client.token = None
        kis_client.token_expires_at = 0.0
        token = await kis_client.get_token()
        logger.info("SUCCESS: POST /api/v1/engine/token-refresh")
        return {
            "ok": True,
            "source": "backend",
            "live": True,
            "payload": {
                "step": "S1",
                "result": "KIS 토큰 갱신 완료",
                "token_preview": f"{str(token)[:8]}..." if token else "none",
            },
        }
    except Exception as exc:
        logger.error("FAIL: POST /api/v1/engine/token-refresh — %s", exc)
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": str(exc), "source": "backend", "live": True},
        )


@router.get("/logs", summary="서버 로그 최근 N줄 조회")
async def get_engine_logs(
    lines: int = Query(default=80, ge=10, le=500),
    filter: str = Query(default="", description="포함할 키워드 (빈 문자열이면 전체)"),
):
    """server.log에서 최근 N줄을 읽어 반환한다. filter 키워드가 있으면 해당 줄만 반환."""
    logger.info("START: GET /api/v1/engine/logs lines=%d filter=%s", lines, filter)
    try:
        if not _LOG_FILE.exists():
            return {
                "ok": True,
                "source": "backend",
                "live": True,
                "payload": {"lines": [], "total": 0, "log_path": str(_LOG_FILE)},
            }

        # 전체 읽기 (최대 10000줄)
        with open(_LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()

        # 최근 N줄 우선 추출 후 필터
        recent = all_lines[-min(len(all_lines), lines * 5):]  # 여유있게 가져온 뒤 필터
        if filter:
            kw = filter.lower()
            recent = [l for l in recent if kw in l.lower()]

        result_lines = [l.rstrip("\n") for l in recent[-lines:]]

        logger.info("SUCCESS: GET /api/v1/engine/logs returned=%d", len(result_lines))
        return {
            "ok": True,
            "source": "backend",
            "live": True,
            "payload": {
                "lines": result_lines,
                "total": len(result_lines),
                "log_path": str(_LOG_FILE),
            },
        }
    except Exception as exc:
        logger.error("FAIL: GET /api/v1/engine/logs — %s", exc)
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": str(exc), "source": "backend", "live": True},
        )
```

---

## 2. `backend/main.py` 수정

imports에 추가:
```python
from .api.routes.engine_test import router as engine_test_router
```

`app.include_router` 목록에 추가 (rulepack_gen_router 바로 다음):
```python
app.include_router(engine_test_router)
```

---

## 완료 기준

```bash
python -m py_compile backend/api/routes/engine_test.py && echo "OK"
python -m py_compile backend/main.py && echo "OK"
```

OUTBOX(`docs/agent-comm/OUTBOX_EXECUTOR_engine_test_backend.md`)에 결과 작성.
