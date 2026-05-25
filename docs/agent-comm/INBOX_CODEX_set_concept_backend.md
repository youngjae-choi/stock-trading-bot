# INBOX: Codex — Set 개념 백엔드 구현

**우선순위:** HIGH  
**담당:** Codex (Backend Executor)  
**작성:** Sisyphus 2026-05-23

---

## 목표

"Regime Set" 개념을 DB + 서비스 레이어 + API에 구현한다.  
Set = 특정 시장 조건(trigger_conditions) + 그에 맞는 설정값(settings)의 묶음이다.  
매일 아침 morning_context에서 레짐을 읽어 가장 잘 맞는 Set을 선택(or 자동생성)한다.

**추가 요청:** 다음 주 월요일(2026-05-26) 거래일을 대비한 예측 Set 3종을 미리 DB에 생성한다.  
월요일에 실제 시장 데이터가 들어왔을 때, 미리 만든 Set 중 조건이 맞으면 그것을 사용하고,  
없으면 새 Set을 자동생성한다.

---

## 1. DB 스키마 — `backend/services/db.py`

`ensure_tables()` 함수 끝에 아래 두 테이블을 추가한다:

```sql
CREATE TABLE IF NOT EXISTS regime_sets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    trigger_conditions TEXT NOT NULL DEFAULT '{}',
    -- JSON: {"regime_label": "risk_on", "vix_max": 20, "vix_min": null,
    --        "kospi_change_min": null, "kospi_change_max": null}
    -- regime_label이 null이면 "어떤 레짐에도 매칭 가능"
    settings TEXT NOT NULL DEFAULT '{}',
    -- JSON: {"max_positions": 10, "stop_loss_rate": -0.02,
    --        "take_profit_rate": 0.05, "new_entry_allowed": true,
    --        "trailing_activate_profit": 0.03, "trailing_stop_rate": 0.015}
    is_active INTEGER NOT NULL DEFAULT 1,
    is_prebuilt INTEGER NOT NULL DEFAULT 0,   -- 예측 Set 플래그
    prebuilt_target_date TEXT,               -- 예측 Set이면 대상 날짜 e.g. "2026-05-26"
    priority INTEGER NOT NULL DEFAULT 0,     -- 높을수록 먼저 매칭
    total_applications INTEGER NOT NULL DEFAULT 0,
    win_count INTEGER NOT NULL DEFAULT 0,
    total_pnl REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS regime_set_applications (
    id TEXT PRIMARY KEY,
    trade_date TEXT NOT NULL UNIQUE,
    set_id TEXT NOT NULL,
    set_name TEXT NOT NULL DEFAULT '',
    match_reason TEXT NOT NULL DEFAULT '',   -- 매칭 이유 설명 (자연어)
    match_score REAL NOT NULL DEFAULT 0.0,   -- 0.0 ~ 1.0
    applied_settings TEXT NOT NULL DEFAULT '{}',
    regime_label TEXT,
    vix_value REAL,
    kospi_change_pct REAL,
    total_trades INTEGER,
    win_count INTEGER,
    total_pnl REAL,
    result_updated_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(set_id) REFERENCES regime_sets(id)
);
```

---

## 2. 기본 Set 4종 + 예측 Set 3종 자동 생성

`backend/services/db.py` 안에 `ensure_default_regime_sets()` 함수를 추가하고  
`ensure_tables()` 마지막에서 호출한다.

### 기본 4종 (항상 존재)
```python
DEFAULT_SETS = [
    {
        "id": "SET-RISK_ON",
        "name": "Risk On 일반형",
        "description": "VIX 낮고 상승 모멘텀 — 공격적 포지션",
        "trigger_conditions": {"regime_label": "risk_on", "vix_max": 22},
        "settings": {
            "max_positions": 10,
            "stop_loss_rate": -0.02,
            "take_profit_rate": 0.05,
            "new_entry_allowed": True,
            "trailing_activate_profit": 0.03,
            "trailing_stop_rate": 0.015
        },
        "priority": 10
    },
    {
        "id": "SET-NEUTRAL",
        "name": "중립형",
        "description": "방향성 불명확 — 표준 설정",
        "trigger_conditions": {"regime_label": "neutral"},
        "settings": {
            "max_positions": 7,
            "stop_loss_rate": -0.02,
            "take_profit_rate": 0.04,
            "new_entry_allowed": True,
            "trailing_activate_profit": 0.025,
            "trailing_stop_rate": 0.012
        },
        "priority": 10
    },
    {
        "id": "SET-RISK_OFF",
        "name": "리스크 오프형",
        "description": "방어적 장세 — 포지션 최소화",
        "trigger_conditions": {"regime_label": "risk_off"},
        "settings": {
            "max_positions": 5,
            "stop_loss_rate": -0.015,
            "take_profit_rate": 0.03,
            "new_entry_allowed": True,
            "trailing_activate_profit": 0.02,
            "trailing_stop_rate": 0.01
        },
        "priority": 10
    },
    {
        "id": "SET-VOLATILE",
        "name": "변동성 장세형",
        "description": "고변동성 — 포지션 축소, 타이트 손절",
        "trigger_conditions": {"regime_label": "volatile", "vix_min": 25},
        "settings": {
            "max_positions": 3,
            "stop_loss_rate": -0.015,
            "take_profit_rate": 0.04,
            "new_entry_allowed": False,
            "trailing_activate_profit": 0.025,
            "trailing_stop_rate": 0.012
        },
        "priority": 10
    }
]
```

### 예측 Set 3종 — 다음 주 월요일 2026-05-26 대비
```python
PREBUILT_SETS_0526 = [
    {
        "id": "SET-PRE-0526-RECOVERY",
        "name": "2026-05-26 반등 예측형",
        "description": "주말 긍정 뉴스로 반등 시나리오 (VIX 하락, KOSPI +0.5% 이상)",
        "trigger_conditions": {
            "regime_label": "risk_on",
            "vix_max": 20,
            "kospi_change_min": 0.5
        },
        "settings": {
            "max_positions": 10,
            "stop_loss_rate": -0.022,
            "take_profit_rate": 0.055,
            "new_entry_allowed": True,
            "trailing_activate_profit": 0.03,
            "trailing_stop_rate": 0.015
        },
        "is_prebuilt": True,
        "prebuilt_target_date": "2026-05-26",
        "priority": 20
    },
    {
        "id": "SET-PRE-0526-SIDEWAYS",
        "name": "2026-05-26 횡보 예측형",
        "description": "관망 심리 — KOSPI ±0.3% 범위 횡보 예상",
        "trigger_conditions": {
            "regime_label": "neutral",
            "kospi_change_min": -0.5,
            "kospi_change_max": 0.5
        },
        "settings": {
            "max_positions": 6,
            "stop_loss_rate": -0.018,
            "take_profit_rate": 0.035,
            "new_entry_allowed": True,
            "trailing_activate_profit": 0.022,
            "trailing_stop_rate": 0.011
        },
        "is_prebuilt": True,
        "prebuilt_target_date": "2026-05-26",
        "priority": 20
    },
    {
        "id": "SET-PRE-0526-SELLOFF",
        "name": "2026-05-26 하락 대비형",
        "description": "지정학적 리스크 or 美증시 급락 반영 — 방어 모드",
        "trigger_conditions": {
            "regime_label": "risk_off",
            "vix_min": 22,
            "kospi_change_max": -0.5
        },
        "settings": {
            "max_positions": 3,
            "stop_loss_rate": -0.015,
            "take_profit_rate": 0.03,
            "new_entry_allowed": False,
            "trailing_activate_profit": 0.02,
            "trailing_stop_rate": 0.01
        },
        "is_prebuilt": True,
        "prebuilt_target_date": "2026-05-26",
        "priority": 20
    }
]
```

`ensure_default_regime_sets()` 구현:
- 기본 4종은 `INSERT OR IGNORE` (이미 있으면 건너뜀)
- 예측 3종도 `INSERT OR IGNORE`
- `created_at`, `updated_at`은 현재 KST 시각

---

## 3. `backend/services/regime_set_service.py` 신규 작성

```python
"""
Regime Set 매칭 서비스.
morning_context 데이터로 가장 잘 맞는 Set을 찾거나 자동생성.
"""
import json, uuid
from datetime import datetime, timezone, timedelta
from .db import get_connection

KST = timezone(timedelta(hours=9))

def get_all_sets(active_only: bool = True) -> list:
    """모든 Set 목록 반환"""

def get_today_application(trade_date: str) -> dict | None:
    """오늘 이미 적용된 Set 반환"""

def match_set(regime_label: str, vix: float | None, kospi_change_pct: float | None,
              trade_date: str) -> dict:
    """
    가장 잘 맞는 Set을 찾아 today_application에 기록하고 반환.
    반환: {set_id, set_name, match_reason, match_score, applied_settings, is_new}
    
    매칭 우선순위:
    1. is_prebuilt=1 AND prebuilt_target_date=trade_date 인 Set부터 검사
    2. 기본 Set 검사
    3. 아무것도 없으면 → auto-create 새 Set
    
    조건 체크:
    - trigger_conditions.regime_label 일치 여부
    - vix_max: vix <= vix_max
    - vix_min: vix >= vix_min  
    - kospi_change_min: kospi_change_pct >= kospi_change_min
    - kospi_change_max: kospi_change_pct <= kospi_change_max
    
    match_score 계산:
    - 기본 점수: regime_label 일치 = 0.5
    - vix 조건 추가 충족 = +0.2
    - kospi 조건 추가 충족 = +0.2
    - prebuilt Set이면 priority 가중치 적용
    """

def auto_create_set(regime_label: str, vix: float | None,
                    kospi_change_pct: float | None) -> dict:
    """
    기존 Set이 없을 때 새 Set을 자동생성하고 DB에 저장.
    regime_label에 따라 기본 파라미터 결정.
    """

def record_application(trade_date: str, matched_set: dict,
                        regime_label: str, vix: float | None,
                        kospi_change_pct: float | None) -> None:
    """매칭 결과를 regime_set_applications에 기록 (UPSERT)"""

def update_set_result(trade_date: str, total_trades: int,
                      win_count: int, total_pnl: float) -> None:
    """당일 거래 결과로 Set 통계 업데이트"""

def get_set_history(days: int = 30) -> list:
    """최근 N일 적용 이력"""

def get_match_preview(regime_label: str, vix: float | None,
                      kospi_change_pct: float | None,
                      trade_date: str = None) -> dict:
    """실제 적용 없이 어떤 Set이 매칭될지 미리보기"""
```

---

## 4. `backend/services/engine/decision_engine.py` 수정

`_save_daily_context_snapshot(today)` 함수 안에서  
morning_context를 읽은 뒤, `regime_set_service.match_set()` 을 호출한다.

```python
from ..regime_set_service import match_set as match_regime_set

# _save_daily_context_snapshot 내부 끝에 추가:
try:
    mc = conn.execute(
        "SELECT regime, vix FROM morning_context WHERE trade_date=?", (today,)
    ).fetchone()
    if mc:
        regime_label = mc["regime"] or "neutral"
        vix = mc.get("vix")
        # kospi_change_pct도 morning_context에서 읽기 (있는 경우)
        try:
            mkt = json.loads(mc.get("market_data_json") or "{}")
            kospi = mkt.get("kospi", {})
            kospi_change = kospi.get("change_pct")
        except Exception:
            kospi_change = None
        match_regime_set(regime_label, vix, kospi_change, today)
except Exception as e:
    logger.warning(f"regime set matching failed: {e}")
```

morning_context 테이블 컬럼 구조를 먼저 확인하고 실제 컬럼명에 맞게 조정할 것.

---

## 5. API routes — `backend/api/routes/regime_sets.py` 신규 작성

```python
from fastapi import APIRouter, Query, Body
from ...services.regime_set_service import (
    get_all_sets, get_today_application, get_set_history,
    match_set, get_match_preview
)

router = APIRouter(prefix="/api/v1/regime", tags=["regime-sets"])

@router.get("/sets")
async def list_sets(active_only: bool = True):
    """모든 Set 목록"""

@router.get("/today")
async def get_today_regime(trade_date: str = Query(default=None)):
    """
    오늘 적용된 Set + 추론 체인 반환.
    trade_date 없으면 오늘 KST 날짜 사용.
    반환: {ok, date, application: {set_id, set_name, match_reason, match_score,
           applied_settings, regime_label, vix_value, kospi_change_pct}}
    """

@router.get("/history")
async def get_regime_history(days: int = Query(default=30)):
    """최근 N일 Set 적용 이력"""

@router.get("/preview")
async def preview_match(
    regime_label: str = Query(default="neutral"),
    vix: float = Query(default=None),
    kospi_change_pct: float = Query(default=None),
    trade_date: str = Query(default=None)
):
    """조건 입력 시 어떤 Set이 매칭될지 시뮬레이션 (DB 기록 없음)"""
```

---

## 6. `backend/main.py` 수정

```python
from .api.routes.regime_sets import router as regime_sets_router
app.include_router(regime_sets_router)
```

---

## 7. 완료 후 OUTBOX 작성

`docs/agent-comm/OUTBOX_CODEX_set_concept_backend.md` 에 결과를 작성:
- 생성/수정된 파일 목록
- DB 테이블 생성 확인
- 기본 Set 7종 INSERT 확인
- API route 동작 확인 (`curl` 결과)
- 오류 및 해결 내용

---

## 주의사항

- `morning_context` 테이블의 실제 컬럼명 확인 후 코드 작성
- DB migration은 `ensure_tables()` 내 `CREATE TABLE IF NOT EXISTS`로 처리 (자동)
- 기존 코드 패턴(`get_connection()`, `row_factory`) 동일하게 사용
- `regime_set_service.py`는 `backend/services/` 에 위치
