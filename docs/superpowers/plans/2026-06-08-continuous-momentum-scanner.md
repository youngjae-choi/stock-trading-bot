# 상시 모멘텀 스캐너 — 개발계획서

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use `- [ ]` checkboxes.

**Goal:** exploration_mode(모의)에서 3분마다 현재 등락률·거래량급증 상위 종목을 스캔해, 신규 적격 종목을 S6 watchlist에 누적 추가하고 WS 구독시켜 하루 종일 활발한 종목을 발굴·매수한다.

**Architecture:** 신규 `momentum_scanner.py`가 경량 movers 조회(rank API, persist/LLM 없음)+필터 → `decision_engine.add_momentum_candidates`로 **병합 추가**(교체 아님)+WS 재구독(≤40). 스케줄러 `job_momentum_scan`이 */3분 구동. 기존 레짐 재선별·매수/사이징 경로는 그대로.

**Tech Stack:** Python/FastAPI/SQLite, pytest. 설계서: `docs/superpowers/specs/2026-06-08-continuous-momentum-scanner-design.md`.

**확정 정책(PM):** 3분 주기, WS 구독 상한 40, LLM 미사용, exploration 전용, 신규매수 금지시간(15:10) 준수.

---

## File Structure
| 파일 | 변경 | 책임 |
|------|------|------|
| `backend/services/engine/momentum_scanner.py` | Create | 경량 movers 스캔+필터+신규 발굴 |
| `backend/services/engine/decision_engine.py` | Modify | `add_momentum_candidates` 병합 추가 진입점 |
| `backend/services/db.py` | Modify | momentum_scan 설정 시드 |
| `backend/services/scheduler.py` | Modify | `job_momentum_scan` (*/3분, 가드) |
| `tests/unit/test_momentum_scanner.py` 등 | Create | TDD |

---

## Task 1: momentum_scanner — 경량 movers 스캔 + 신규 발굴 판정

**Files:** Create `backend/services/engine/momentum_scanner.py`; Test `tests/unit/test_momentum_scanner.py`

- [ ] **Step 1: 먼저 universe_filter 재사용 지점 확인** (구현자 필수 선행)

Run: `grep -nE "^def |^async def |_merge_and_deduplicate|def .*filter|def .*score" backend/services/engine/universe_filter.py`
목표: movers 병합/스코어/필터 헬퍼 이름 확정. 스캐너는 `get_price_rank`/`get_volume_rank`(universe_service) 직접 호출 후, universe_filter의 merge+필터 헬퍼를 재사용(import)해 **persist 없이** 적격 movers 리스트를 만든다. 헬퍼가 모듈-private라 재사용 곤란하면, 같은 정량 기준(거래량>0 sanity + 등락률/거래량급증 상위)으로 최소 필터를 스캐너 내에 구현한다.

- [ ] **Step 2: 실패 테스트 작성**

```python
# tests/unit/test_momentum_scanner.py
import backend.services.engine.momentum_scanner as ms

def test_pick_new_symbols_excludes_existing_held_cooldown(monkeypatch):
    movers = [{"symbol":"111","change_rate":20,"volume":1000},
              {"symbol":"222","change_rate":15,"volume":2000},
              {"symbol":"333","change_rate":12,"volume":3000}]
    existing = {"111"}          # 이미 감시중
    held = {"222"}              # 보유중
    monkeypatch.setattr(ms, "_in_cooldown", lambda s: s == "333")  # 333 쿨다운
    new = ms._pick_new_symbols(movers, existing=existing, held=held)
    assert [m["symbol"] for m in new] == []  # 셋 다 제외

def test_pick_new_symbols_returns_fresh(monkeypatch):
    movers = [{"symbol":"444","change_rate":18,"volume":5000}]
    monkeypatch.setattr(ms, "_in_cooldown", lambda s: False)
    new = ms._pick_new_symbols(movers, existing=set(), held=set())
    assert [m["symbol"] for m in new] == ["444"]
```

- [ ] **Step 3: 실패 확인** — Run: `cd /home/young/repos/stock-trading-bot && source .venv/bin/activate && python -m pytest tests/unit/test_momentum_scanner.py -v` → FAIL(모듈 없음)

- [ ] **Step 4: 구현**

```python
# backend/services/engine/momentum_scanner.py
"""상시 모멘텀 스캐너 — 3분마다 현재 movers 스캔 → 신규 적격 종목 발굴(LLM 없음).

발굴된 신규 종목은 decision_engine watchlist에 병합 추가되어 S6가 매수 판정한다.
exploration_mode 전용. 레짐 재선별(intraday_refresh)과 별개로 상시 동작.
설계서: docs/superpowers/specs/2026-06-08-continuous-momentum-scanner-design.md
"""
from __future__ import annotations

import logging
import time
from typing import Any

from ..settings_store import get_setting
from .exploration_gate import is_exploration_allowed

logger = logging.getLogger("MomentumScanner")
_recent_exit_at: dict[str, float] = {}  # symbol -> epoch (당일 청산 쿨다운)
_COOLDOWN_MIN = 10


def _now_ts() -> float:
    return time.time()


def _in_cooldown(symbol: str) -> bool:
    t = _recent_exit_at.get(symbol)
    return t is not None and (_now_ts() - t) < _COOLDOWN_MIN * 60


def note_exit(symbol: str) -> None:
    """포지션 청산 시 호출 — 당일 즉시 재편입 churn 방지(쿨다운 등록)."""
    _recent_exit_at[symbol] = _now_ts()


def _pick_new_symbols(movers: list[dict[str, Any]], existing: set[str], held: set[str]) -> list[dict[str, Any]]:
    """현재 movers 중 신규(미감시·미보유·쿨다운 외) 적격 종목만 반환."""
    out: list[dict[str, Any]] = []
    for m in movers:
        sym = str(m.get("symbol") or "").strip()
        if not sym or sym in existing or sym in held or _in_cooldown(sym):
            continue
        if float(m.get("volume") or 0) <= 0:   # sanity: 거래 없는 종목 제외
            continue
        out.append(m)
    return out


async def _fetch_current_movers() -> list[dict[str, Any]]:
    """현재 등락률·거래량급증 상위 movers를 경량 조회(persist/LLM 없음).

    universe_filter의 merge/필터 헬퍼를 재사용한다(Step 1에서 확정한 이름 사용).
    """
    from ..kis.domestic.universe_service import get_price_rank, get_volume_rank
    from .universe_filter import _merge_and_deduplicate  # Step1에서 실제 이름 확인
    import asyncio
    _MAX = 60
    volume_items, change_items = await asyncio.gather(
        get_volume_rank(market_code="J", top_n=_MAX),
        get_price_rank(sort_by="change_rate", market_code="J", top_n=_MAX),
    )
    merged = _merge_and_deduplicate(volume_items, change_items)
    items = list(merged.values()) if isinstance(merged, dict) else list(merged)
    return items


async def run_momentum_scan() -> dict[str, Any]:
    """3분 틱 진입점. exploration 전용. 신규 적격 종목을 decision_engine에 추가."""
    if not is_exploration_allowed():
        return {"ok": True, "enabled": False, "reason": "exploration_off", "added": 0}
    if not _setting_bool("momentum_scan.enabled", True):
        return {"ok": True, "enabled": False, "reason": "disabled", "added": 0}
    try:
        movers = await _fetch_current_movers()
    except Exception as exc:
        logger.warning("WARN: [MomentumScan] movers 조회 실패 — %s", exc)
        return {"ok": False, "reason": str(exc), "added": 0}

    from .decision_engine import decision_engine
    from .position_manager import position_manager
    existing = set(getattr(decision_engine, "_candidates", {}).keys())
    held = {str(p.get("symbol") or "").strip() for p in position_manager.get_positions()}
    fresh = _pick_new_symbols(movers, existing=existing, held=held)
    if not fresh:
        logger.info("INFO: [MomentumScan] 신규 적격 0 (movers=%d existing=%d held=%d)", len(movers), len(existing), len(held))
        return {"ok": True, "enabled": True, "added": 0, "movers": len(movers)}

    result = await decision_engine.add_momentum_candidates(fresh)
    logger.info("INFO: [MomentumScan] movers=%d 신규편입=%s 구독=%s",
                len(movers), result.get("added"), result.get("subscribed"))
    return {"ok": True, "enabled": True, "added": result.get("added", 0),
            "subscribed": result.get("subscribed"), "movers": len(movers)}


def _setting_bool(key: str, default: bool) -> bool:
    v = get_setting(key, default)
    return v if isinstance(v, bool) else str(v).lower() in ("true", "1", "yes")
```

- [ ] **Step 5: 통과 확인** — Run: `python -m pytest tests/unit/test_momentum_scanner.py -v` → PASS(2)
- [ ] **Step 6: 커밋**

```bash
git add backend/services/engine/momentum_scanner.py tests/unit/test_momentum_scanner.py
git commit -m "feat(scanner): 상시 모멘텀 스캐너 — 경량 movers 스캔+신규 발굴(LLM 없음)"
```

---

## Task 2: decision_engine.add_momentum_candidates — 병합 추가 + WS 재구독(≤40)

**Files:** Modify `backend/services/engine/decision_engine.py`; Test `tests/unit/test_add_momentum_candidates.py`

- [ ] **Step 1: 선행 확인** — Run: `sed -n '984,1025p' backend/services/engine/decision_engine.py` 로 refresh_candidates의 self._candidates·load_daily_rules·WS 재구독(realtime_ws_manager.start) 패턴을 확인. add_momentum_candidates는 그 패턴을 **교체가 아닌 병합**으로 재사용한다.

- [ ] **Step 2: 실패 테스트 작성**

```python
# tests/unit/test_add_momentum_candidates.py
import asyncio
import backend.services.engine.decision_engine as de

def test_add_merges_and_caps(monkeypatch):
    eng = de.decision_engine
    eng._candidates = {"A": {"symbol": "A"}}
    monkeypatch.setattr(de, "load_daily_rules", lambda today, syms: len(syms))
    captured = {}
    async def fake_start(symbols): captured["symbols"] = symbols
    monkeypatch.setattr(de.realtime_ws_manager, "start", fake_start)
    monkeypatch.setattr(de.position_manager, "get_positions", lambda: [])
    monkeypatch.setattr(de, "get_setting", lambda k, d=None: 40 if "max_sub" in k else d, raising=False)
    new = [{"symbol": "B"}, {"symbol": "C"}, {"symbol": "A"}]  # A 중복
    out = asyncio.run(eng.add_momentum_candidates(new))
    assert set(eng._candidates.keys()) == {"A", "B", "C"}
    assert out["added"] == 2  # B, C
    assert "A" in captured["symbols"] and "B" in captured["symbols"]
```

- [ ] **Step 3: 실패 확인** — Run: `python -m pytest tests/unit/test_add_momentum_candidates.py -v` → FAIL

- [ ] **Step 4: 구현** — `decision_engine.py`의 DecisionEngine 클래스에 메서드 추가(refresh_candidates 근처):

```python
    async def add_momentum_candidates(self, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        """모멘텀 스캐너가 발굴한 신규 종목을 watchlist에 병합 추가 + WS 재구독(상한 가드).

        기존 _candidates/보유는 유지하고 신규만 추가한다(교체 아님). 상한 초과 시 추가분을 자른다.
        """
        from .momentum_scanner import _setting_bool  # noqa: F401 (순환 회피용 아님 — 필요시 직접 get_setting)
        today = _today_kst()
        max_sub = int(get_setting("momentum_scan.max_subscriptions", 40) or 40)
        added = 0
        for c in candidates:
            sym = _candidate_symbol(c)
            if not sym or sym in self._candidates:
                continue
            self._candidates[sym] = c
            added += 1
        if added == 0:
            return {"ok": True, "added": 0, "subscribed": len(self._candidates)}
        # 보유 + 후보 합집합, 상한 40 cap
        managed = [str(p.get("symbol") or "") for p in position_manager.get_positions()]
        all_symbols = list(dict.fromkeys([*managed, *self._candidates.keys()]))
        if len(all_symbols) > max_sub:
            all_symbols = all_symbols[:max_sub]
        load_daily_rules(today, list(self._candidates.keys()))
        try:
            await realtime_ws_manager.start(all_symbols)
        except Exception as exc:
            logger.warning("WARN: [S6] 모멘텀 후보 WS 재구독 실패 — %s", exc)
        logger.info("INFO: [S6] 모멘텀 신규편입 added=%d total_candidates=%d subscribed=%d",
                    added, len(self._candidates), len(all_symbols))
        return {"ok": True, "added": added, "subscribed": len(all_symbols)}
```

> 구현자 주의: `get_setting`, `_today_kst`, `_candidate_symbol`, `load_daily_rules`, `realtime_ws_manager`, `position_manager`, `logger`가 decision_engine.py에 이미 import/정의돼 있는지 Step 1에서 확인하고 그대로 재사용한다. `_setting_bool` import는 불필요하면 제거.

- [ ] **Step 5: 통과 확인** — Run: `python -m pytest tests/unit/test_add_momentum_candidates.py -v` → PASS
- [ ] **Step 6: 회귀 + 커밋**

```bash
python -m pytest tests/unit/ -q   # 전체 PASS
git add backend/services/engine/decision_engine.py tests/unit/test_add_momentum_candidates.py
git commit -m "feat(scanner): decision_engine.add_momentum_candidates 병합 추가+WS 재구독(≤40)"
```

---

## Task 3: 설정 시드

**Files:** Modify `backend/services/db.py`; Test `tests/unit/test_momentum_scan_settings.py`

- [ ] **Step 1: 실패 테스트**

```python
# tests/unit/test_momentum_scan_settings.py
from backend.config import settings
from backend.services import db as db_mod
from backend.services.settings_store import get_setting

def test_momentum_scan_seeds(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "APP_DB_PATH", str(tmp_path / "s.sqlite3"))
    db_mod.initialize_database()
    assert get_setting("momentum_scan.enabled", None) is True
    assert int(get_setting("momentum_scan.interval_min", 0)) == 3
    assert int(get_setting("momentum_scan.max_subscriptions", 0)) == 40
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/unit/test_momentum_scan_settings.py -v` → FAIL
- [ ] **Step 3: 시드 추가** — db.py 설정 시드 리스트에 추가(기존 boolean 시드 포맷 확인 후 동일하게):

```python
        ("momentum_scan.enabled", True, "boolean", "상시 모멘텀 스캐너 활성(모의 전용)"),
        ("momentum_scan.interval_min", 3, "number", "모멘텀 스캔 주기(분)"),
        ("momentum_scan.max_subscriptions", 40, "number", "WS 동시 구독 상한 가드"),
```

- [ ] **Step 4: 통과 확인** — PASS
- [ ] **Step 5: 커밋**

```bash
git add backend/services/db.py tests/unit/test_momentum_scan_settings.py
git commit -m "feat(scanner): momentum_scan 설정 시드(enabled/interval/max_subscriptions)"
```

---

## Task 4: 스케줄러 job_momentum_scan (*/3분, 가드)

**Files:** Modify `backend/services/scheduler.py`; Test `tests/unit/test_momentum_scan_job.py`

- [ ] **Step 1: 선행 확인** — Run: `grep -nE "job_intraday_refresh|_non_trading_day_today|CronTrigger.*9-15|new_entry_cutoff" backend/services/scheduler.py | head` 로 잡 등록 패턴·거래일 가드·컷오프 확인.

- [ ] **Step 2: 실패 테스트**

```python
# tests/unit/test_momentum_scan_job.py
import asyncio
import backend.services.scheduler as sched

def test_job_skips_non_trading_day(monkeypatch):
    monkeypatch.setattr(sched, "_non_trading_day_today", lambda: "weekend")
    called = {"n": 0}
    async def fake_run(): called["n"] += 1; return {"ok": True}
    import backend.services.engine.momentum_scanner as ms
    monkeypatch.setattr(ms, "run_momentum_scan", fake_run)
    asyncio.run(sched.job_momentum_scan())
    assert called["n"] == 0  # 비거래일 스킵

def test_job_runs_on_trading_day(monkeypatch):
    monkeypatch.setattr(sched, "_non_trading_day_today", lambda: None)
    called = {"n": 0}
    async def fake_run(): called["n"] += 1; return {"ok": True, "added": 0}
    import backend.services.engine.momentum_scanner as ms
    monkeypatch.setattr(ms, "run_momentum_scan", fake_run)
    asyncio.run(sched.job_momentum_scan())
    assert called["n"] == 1
```

- [ ] **Step 3: 실패 확인** — FAIL(job_momentum_scan 없음)

- [ ] **Step 4: 구현** — scheduler.py에 잡 함수 추가(job_intraday_refresh 근처):

```python
async def job_momentum_scan() -> None:
    """상시 모멘텀 스캐너 — 3분마다 현재 movers 발굴(09~15시). 비거래일·exploration 가드는 내부에서도 처리."""
    if _non_trading_day_today():
        return
    try:
        from .engine.momentum_scanner import run_momentum_scan
        result = await run_momentum_scan()
        if result.get("added"):
            logger.info("INFO: [MomentumScan] 신규편입 %d", result["added"])
    except Exception as exc:
        logger.error("FAIL: [MomentumScan] 실패 — reason=%s", exc)
```

등록부(다른 add_job 근처)에 추가 — 09:05~15:10 사이 3분 간격(신규매수 금지시간 전):

```python
    scheduler.add_job(
        job_momentum_scan,
        CronTrigger(hour="9-15", minute="*/3", timezone="Asia/Seoul"),
        id="job_momentum_scan",
        name="상시 모멘텀 스캐너 (3분)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
```

> 컷오프(15:10) 이후 매수는 preflight가 차단하므로 잡은 15시대도 돌되 매수만 안 됨 — 안전. 09:00~09:05 데이터 불안정 구간은 run_momentum_scan 내 movers sanity 필터(volume>0)로 자연 배제.

- [ ] **Step 5: 통과 확인** — `python -m pytest tests/unit/test_momentum_scan_job.py -v` → PASS
- [ ] **Step 6: 회귀 + 커밋**

```bash
python -m pytest tests/unit/ -q   # 전체 PASS
git add backend/services/scheduler.py tests/unit/test_momentum_scan_job.py
git commit -m "feat(scanner): job_momentum_scan 등록(*/3분, 거래일 가드)"
```

---

## Task 5: 청산 쿨다운 wiring (churn 방지) + 통합 검증

**Files:** Modify `backend/services/engine/eod_liquidation.py` 또는 매도 경로(`order_executor.execute_sell`); 검증

- [ ] **Step 1: 선행 확인** — 매도 체결 지점에서 `momentum_scanner.note_exit(symbol)` 호출 위치 결정. Run: `grep -nE "execute_sell|체결|filled|매도" backend/services/engine/order_executor.py | head`. execute_sell 성공 직후 `from .momentum_scanner import note_exit; note_exit(symbol)` 추가(즉시 재편입 churn 방지).
- [ ] **Step 2: 구현** — execute_sell 성공 분기에 note_exit 호출 추가.
- [ ] **Step 3: 회귀** — `python -m pytest tests/unit/ -q` 전체 PASS.
- [ ] **Step 4: 커밋**

```bash
git add backend/services/engine/order_executor.py backend/services/engine/momentum_scanner.py
git commit -m "feat(scanner): 매도 시 청산 쿨다운 등록(note_exit)으로 즉시 재편입 churn 방지"
```

- [ ] **Step 5: 통합 검증(운영 — 컨트롤러)** — 서버 재시작(다음 장 시작 전 또는 보유0 창) 후 09시대 로그에서 `[MomentumScan] movers=.. 신규편입=..` 확인. WS 구독 수 ≤40 확인. 매수 발생 시 Profile 사이징 적용 확인.

---

## 요구사항 대조표
| 요구사항 | 태스크 |
|----------|--------|
| 3분마다 상시 발굴 | Task 4 (*/3분) |
| 현재 활발한 종목(movers) | Task 1 (rank API) |
| 신규만 추가(중복 제외) | Task 1·2 |
| WS 구독 상한 40 | Task 2·3 |
| LLM 미사용 | Task 1 (rank+필터만) |
| 모의 전용·컷오프 준수 | Task 1·4 |
| churn 방지 | Task 5 (쿨다운) |

## Self-Review
- Task 1 `_fetch_current_movers`는 universe_filter `_merge_and_deduplicate` 재사용 — Step 1에서 실제 이름/시그니처 확인 필수(private 헬퍼면 적응).
- Task 2 add_momentum_candidates는 decision_engine 기존 심볼/메서드(get_setting·_today_kst·_candidate_symbol·load_daily_rules·realtime_ws_manager·position_manager) 재사용 — Step 1 확인.
- 타입 일관: `run_momentum_scan()→{added,subscribed,movers}`, `add_momentum_candidates(list[dict])→{added,subscribed}`, `note_exit(symbol)`, `_pick_new_symbols(movers,existing,held)`.
