# INBOX_EXECUTOR_funnel_api

## 역할
너는 Executor다. 아래 작업을 수행하라.
완료 후 `docs/agent-comm/OUTBOX_EXECUTOR_funnel_api.md`에 결과를 작성하라.

---

## 작업 1 — `GET /api/v1/funnel/summary` 엔드포인트 신규 추가

### 목적
Today Control, Funnel Monitor 화면의 Funnel Progress 숫자들을 실제 DB 데이터로 표시하기 위한 집계 API.

### 신규 파일: `backend/api/routes/funnel.py`

```python
"""Funnel summary API — S3/S4/Signal/Position 단계별 집계."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ...api.dependencies import require_console_user
from ...services.db import get_connection

logger = logging.getLogger("BackendFunnelAPI")
router = APIRouter(
    prefix="/api/v1/funnel",
    tags=["funnel"],
    dependencies=[Depends(require_console_user)],
)


def _today_kst() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


@router.get("/summary")
async def get_funnel_summary():
    """오늘 Funnel 단계별 집계 반환.
    
    - total_universe: 전체 종목 (KOSPI+KOSDAQ 고정값 2500)
    - layer1_count: 유니버스 필터 통과 종목수 (S3 결과)
    - layer2_count: 하이브리드 스크리닝 통과 종목수 (S4 결과)
    - signals_count: 오늘 발생한 매수 신호 수
    - positions_count: 현재 보유 포지션 수
    - profile_counts: Risk Profile별 배정 종목 수
    - layer1_raw: S3 입력 종목 수 (필터 전)
    - layer1_rejected: 필터 탈락 수
    """
    today = _today_kst()
    endpoint = "/api/v1/funnel/summary"
    logger.info("START: GET %s trade_date=%s", endpoint, today)
    try:
        with get_connection() as conn:
            # S3 Universe Filter
            uf_row = conn.execute(
                "SELECT raw_count, filtered_count FROM universe_filter_results"
                " WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
                (today,),
            ).fetchone()

            # S4 Hybrid Screening
            sc_row = conn.execute(
                "SELECT raw_input_count, output_count FROM hybrid_screening_results"
                " WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
                (today,),
            ).fetchone()

            # Signals today
            sig_count = conn.execute(
                "SELECT COUNT(*) FROM trading_signals WHERE trade_date = ? AND signal_type = 'BUY'",
                (today,),
            ).fetchone()[0]

            # Positions (position_stop_states updated today)
            pos_count = conn.execute(
                "SELECT COUNT(*) FROM position_stop_states"
                " WHERE date(last_updated_at) = ?",
                (today,),
            ).fetchone()[0]

            # Profile counts from daily_trading_plans
            plan_row = conn.execute(
                "SELECT symbol_assignments FROM daily_trading_plans"
                " WHERE trade_date = ? AND status IN ('active', 'validated')"
                " ORDER BY created_at DESC LIMIT 1",
                (today,),
            ).fetchone()

        profile_counts = {"LOW_VOL": 0, "MID_VOL": 0, "HIGH_VOL": 0, "THEME_SPIKE": 0}
        if plan_row:
            try:
                assignments = json.loads(plan_row["symbol_assignments"] or "[]")
                for a in assignments:
                    p = a.get("profile", "MID_VOL")
                    if p in profile_counts:
                        profile_counts[p] += 1
            except Exception:
                pass

        layer1_raw = int(uf_row["raw_count"]) if uf_row else 0
        layer1_count = int(uf_row["filtered_count"]) if uf_row else 0
        layer2_count = int(sc_row["output_count"]) if sc_row else 0

        payload = {
            "trade_date": today,
            "total_universe": 2500,          # KOSPI+KOSDAQ 상장 종목 상수
            "layer1_raw": layer1_raw,
            "layer1_count": layer1_count,
            "layer1_rejected": max(0, layer1_raw - layer1_count),
            "layer2_count": layer2_count,
            "signals_count": sig_count,
            "positions_count": pos_count,
            "profile_counts": profile_counts,
        }
        logger.info("SUCCESS: GET %s payload=%s", endpoint, payload)
        return {"ok": True, "payload": payload}
    except Exception as exc:
        logger.error("FAIL: GET %s — %s", endpoint, exc)
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})
```

### `backend/main.py` 수정 — funnel router 등록

기존 router import 목록에 추가:
```python
from .api.routes.funnel import router as funnel_router
```

`app.include_router(funnel_router)` 추가 (다른 router include 라인 옆에).

---

## 작업 2 — Settings API에 schedule_s2_time, schedule_s9_time seed 추가

현재 `system_settings`에 `schedule_s2_time`, `schedule_s9_time`이 없어서
프론트엔드에서 조회 시 기본값 fallback이 발생한다.

파일: `backend/services/db.py`의 `_seed_system_settings()`에 아래 추가:

```python
("schedule_s2_time", '"08:00"', "string", "S2 시장톤 분석 실행 시간 (HH:MM)"),
("schedule_s9_time", '"15:20"', "string", "S9 당일 청산 실행 시간 (HH:MM)"),
("schedule_s10_time", '"18:00"', "string", "S10 데이터 백업 실행 시간 (HH:MM)"),
("schedule_s11_time", '"22:00"', "string", "S11 Learning Memory Builder 실행 시간 (HH:MM)"),
("risk.force_exit_time", '"15:20"', "string", "당일 강제청산 시작 시간 (HH:MM)"),
("risk.new_entry_cutoff_time", '"15:10"', "string", "신규 매수 금지 시작 시간 (HH:MM)"),
```

단, `INSERT OR IGNORE` 패턴을 사용해 기존 값 보존.

---

## 검증

```bash
python3 -m py_compile backend/api/routes/funnel.py backend/main.py backend/services/db.py
echo "py_compile OK"
```

서버 재시작 후:
```bash
# 인증 없이 테스트 (로컬)
curl -s http://127.0.0.1:8000/api/v1/funnel/summary | python3 -m json.tool
```

응답에 `ok: true`와 `payload.layer1_count` 등 포함 여부 확인.

---

## 완료 체크리스트

- [ ] `backend/api/routes/funnel.py` 신규 생성
- [ ] `backend/main.py`에 funnel_router 등록
- [ ] `db.py` seed에 누락된 schedule/risk 설정 추가
- [ ] py_compile 통과
- [ ] curl 응답 확인

결과는 `docs/agent-comm/OUTBOX_EXECUTOR_funnel_api.md`에 작성하라.
