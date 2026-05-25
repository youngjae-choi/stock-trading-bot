# INBOX: Codex — 화면 재배치 백엔드 API 추가

**우선순위:** HIGH  
**담당:** Codex (Backend Executor)  
**작성:** Sisyphus 2026-05-23

---

## 목표

화면 재배치(Settings Regime SET 수정, Daily Results 확장, Trade Review 레짐 평가)를 위해  
신규 API 2개 추가 + 기존 API 1개 확장.

---

## 1. PUT `/api/v1/regime/sets/{set_id}` — SET 설정 수정

`backend/api/routes/regime_sets.py` 에 추가:

```python
from fastapi import APIRouter, Query, Body, Path, HTTPException
from pydantic import BaseModel

class RegimeSetUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    settings: dict | None = None           # 변경할 설정값 (부분 업데이트 허용)
    trigger_conditions: dict | None = None
    is_active: bool | None = None

@router.put("/sets/{set_id}")
async def update_regime_set(
    set_id: str = Path(...),
    body: RegimeSetUpdateRequest = Body(...)
):
    """
    Regime SET 설정 수정.
    settings는 부분 업데이트: 전달된 키만 덮어씀.
    반환: {ok, set_id, updated_fields}
    """
    from ...services.db import get_connection
    import json
    from datetime import datetime, timezone, timedelta
    KST = timezone(timedelta(hours=9))
    
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM regime_sets WHERE id=?", (set_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Set not found: {set_id}")
        
        updated = []
        now = datetime.now(KST).isoformat()
        
        if body.name is not None:
            conn.execute("UPDATE regime_sets SET name=?, updated_at=? WHERE id=?", (body.name, now, set_id))
            updated.append("name")
        if body.description is not None:
            conn.execute("UPDATE regime_sets SET description=?, updated_at=? WHERE id=?", (body.description, now, set_id))
            updated.append("description")
        if body.is_active is not None:
            conn.execute("UPDATE regime_sets SET is_active=?, updated_at=? WHERE id=?", (int(body.is_active), now, set_id))
            updated.append("is_active")
        if body.trigger_conditions is not None:
            conn.execute("UPDATE regime_sets SET trigger_conditions=?, updated_at=? WHERE id=?", 
                        (json.dumps(body.trigger_conditions), now, set_id))
            updated.append("trigger_conditions")
        if body.settings is not None:
            # 부분 업데이트: 기존 settings에 merge
            existing_settings = json.loads(dict(row)["settings"] or "{}")
            existing_settings.update(body.settings)
            conn.execute("UPDATE regime_sets SET settings=?, updated_at=? WHERE id=?",
                        (json.dumps(existing_settings), now, set_id))
            updated.append("settings")
        
        conn.commit()
    
    return {"ok": True, "set_id": set_id, "updated_fields": updated}
```

---

## 2. GET `/api/v1/regime/day-detail` — 날짜별 레짐 SET + Risk Profile 성과

`backend/api/routes/regime_sets.py` 에 추가:

```python
@router.get("/day-detail")
async def get_day_detail(trade_date: str = Query(...)):
    """
    특정 거래일의 레짐 SET 적용 정보 + Risk Profile별 성과 반환.
    
    반환 구조:
    {
      ok: true,
      trade_date: "2026-05-22",
      regime_application: {
        set_id, set_name, match_reason, match_score,
        applied_settings, regime_label, vix_value, kospi_change_pct,
        is_prebuilt
      } | null,
      profile_breakdown: [
        {profile, trades, win_count, loss_count, total_pnl, win_rate_pct}
      ],
      morning_context: {
        regime, risk_level, vix, kospi_change_pct
      } | null
    }
    """
    from ...services.db import get_connection
    import json
    
    with get_connection() as conn:
        # regime_set_applications
        app_row = conn.execute(
            "SELECT * FROM regime_set_applications WHERE trade_date=?", (trade_date,)
        ).fetchone()
        
        regime_application = None
        if app_row:
            app = dict(app_row)
            # is_prebuilt은 regime_sets에서 JOIN
            set_row = conn.execute(
                "SELECT is_prebuilt FROM regime_sets WHERE id=?", (app["set_id"],)
            ).fetchone()
            app["is_prebuilt"] = bool(set_row["is_prebuilt"]) if set_row else False
            try:
                app["applied_settings"] = json.loads(app.get("applied_settings") or "{}")
            except Exception:
                app["applied_settings"] = {}
            regime_application = app
        
        # Risk Profile별 성과: orders 테이블에서 집계
        # orders 테이블의 실제 컬럼명 확인 후 조정
        # risk_profile 컬럼이 있다고 가정 (없으면 빈 리스트 반환)
        profile_breakdown = []
        try:
            profile_rows = conn.execute("""
                SELECT 
                    COALESCE(risk_profile, 'UNKNOWN') as profile,
                    COUNT(*) as trades,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as win_count,
                    SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) as loss_count,
                    COALESCE(SUM(pnl), 0) as total_pnl
                FROM orders
                WHERE DATE(order_date) = ?
                  AND status IN ('filled', 'completed', 'sold')
                GROUP BY COALESCE(risk_profile, 'UNKNOWN')
                ORDER BY profile
            """, (trade_date,)).fetchall()
            
            for pr in profile_rows:
                p = dict(pr)
                win_rate = round(p["win_count"] / p["trades"] * 100) if p["trades"] > 0 else 0
                p["win_rate_pct"] = win_rate
                profile_breakdown.append(p)
        except Exception:
            profile_breakdown = []
        
        # morning_context
        mc_row = None
        try:
            mc_row = conn.execute(
                "SELECT regime, risk_level, market_data FROM morning_context WHERE trade_date=?",
                (trade_date,)
            ).fetchone()
        except Exception:
            pass
        
        morning_context = None
        if mc_row:
            mc = dict(mc_row)
            try:
                mkt = json.loads(mc.get("market_data") or "{}")
                mc["vix"] = mkt.get("vix", {}).get("price")
                mc["kospi_change_pct"] = mkt.get("kospi", {}).get("change_pct")
            except Exception:
                mc["vix"] = None
                mc["kospi_change_pct"] = None
            morning_context = {
                "regime": mc.get("regime"),
                "risk_level": mc.get("risk_level"),
                "vix": mc.get("vix"),
                "kospi_change_pct": mc.get("kospi_change_pct"),
            }
    
    return {
        "ok": True,
        "trade_date": trade_date,
        "regime_application": regime_application,
        "profile_breakdown": profile_breakdown,
        "morning_context": morning_context,
    }
```

---

## 3. orders 테이블 컬럼 확인 주의사항

`orders` 테이블의 실제 컬럼명을 반드시 확인할 것:
- `pnl` 컬럼이 없을 수 있음 → `realized_pnl` 또는 `profit_loss` 등으로 다를 수 있음
- `risk_profile` 컬럼이 없을 수 있음 → 없으면 profile_breakdown = [] 반환하고 조용히 처리
- `status` 값 확인 후 실제 "완료된 거래"에 맞는 status 조건으로 교체
- `order_date` 컬럼명이 다를 수 있음 → `created_at` 등으로 날짜 필터 교체

반드시 `.schema orders` 또는 `PRAGMA table_info(orders)` 확인 후 구현.

---

## 4. python 문법 검증

완료 후 반드시:
```bash
python -m py_compile backend/api/routes/regime_sets.py
```

---

## 5. OUTBOX 작성

`docs/agent-comm/OUTBOX_CODEX_screen_reorg_backend.md` 에:
- 추가된 endpoint 목록
- orders 테이블 실제 컬럼명 확인 결과
- profile_breakdown 쿼리 결과 (데이터 없으면 [] 반환 확인)
- compile 통과 여부
