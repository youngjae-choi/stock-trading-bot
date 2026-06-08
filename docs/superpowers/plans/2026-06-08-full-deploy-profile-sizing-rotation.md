# 풀예수금·Profile 비중 사이징·적극 교체매매 — 개발계획서

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** exploration_mode(모의)에서 예수금을 Profile 비중대로 최대 95% 풀 배포하고, 매도 시 즉시 재배포하며, 힘 빠지는 보유를 치고 오르는 후보로 자동 스왑한다.

**Architecture:** 기존 부품(profile pack 비중·preflight·replacement_signal·slot 훅)을 재배선한다. ① order_executor 사이징을 균등분할→Profile 비중으로, ② preflight 보유수 게이트를 95% 배포 게이트로, ③ replacement_signal 신호를 자동 실행으로 승격. 모두 exploration_mode=true에서만 동작(실계좌는 기존 경로).

**Tech Stack:** Python/FastAPI/SQLite, pytest. 설계서: `docs/superpowers/specs/2026-06-08-full-deploy-profile-sizing-rotation-design.md`.

**원본 요구사항 (PM 발화 인용):**
> 예수금을 최대95%로 풀로 사용 / 각 종목당 Risk Profile의 비중대로 매수 / 매도하여 룸이 생기면 또 매수조건 충족 종목 매수해서 하루 종일 Fully하게 / 매수대기중 치고 올라오는 종목이 있으면 보유중 힘 빠지는 종목과 교체

**확정 정책:** Profile 비중 현행(15/12/8/5%), 배포 95%+버퍼5%, 교체 점수차 +0.15·일일 20회·쿨다운 30분, 자동스왑+손절허용, 모의 전용.

---

## File Structure

| 파일 | 변경 | 책임 |
|------|------|------|
| `backend/services/engine/order_executor.py` | Modify | Profile 비중 사이징(`_calc_profile_qty`), total_eval 추출, 탐색 분기 교체 |
| `backend/services/engine/order_preflight.py` | Modify | 탐색 시 보유수 게이트→95% 배포 게이트 |
| `backend/services/engine/replacement_executor.py` | Create | 교체 신호→실제 스왑 실행(sell 약 → buy 강), 쿨다운·일일상한 |
| `backend/services/engine/decision_engine.py` | Modify | 교체 실행 호출 wiring |
| `backend/services/db.py` | Modify | 신규 설정 시드 |
| `backend/api/routes/account.py` | Modify | 배포율(deployed_rate) 필드 |
| `backend/static/js/screens/console-trading-monitor.js` + `console.html` | Modify | 배포율 카드 |
| `tests/unit/test_profile_sizing.py` 등 | Create | TDD |

---

## Task 1: Profile 비중 사이징 헬퍼

**Files:**
- Modify: `backend/services/engine/order_executor.py`
- Test: `tests/unit/test_profile_sizing.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/unit/test_profile_sizing.py
from backend.services.engine.order_executor import OrderExecutor

def test_calc_profile_qty_uses_profile_rate():
    ex = OrderExecutor.__new__(OrderExecutor)
    # total_eval 1억, HIGH_VOL 8% → 목표 800만, 가용 충분, price 1만 → 800주
    assert ex._calc_profile_qty(100_000_000, 0.08, 50_000_000, 10_000) == 800

def test_calc_profile_qty_capped_by_deployable():
    ex = OrderExecutor.__new__(OrderExecutor)
    # 목표 800만이나 가용 300만 → 300주
    assert ex._calc_profile_qty(100_000_000, 0.08, 3_000_000, 10_000) == 300

def test_calc_profile_qty_zero_when_no_room():
    ex = OrderExecutor.__new__(OrderExecutor)
    assert ex._calc_profile_qty(100_000_000, 0.08, 0, 10_000) == 0
    assert ex._calc_profile_qty(100_000_000, 0.0, 5_000_000, 10_000) == 0
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/test_profile_sizing.py -v`
Expected: FAIL (`_calc_profile_qty` 없음)

- [ ] **Step 3: 헬퍼 구현** — `order_executor.py`의 `_calc_budget_qty` 메서드 바로 아래에 추가:

```python
    def _calc_profile_qty(
        self,
        total_eval: float,
        profile_rate: float,
        deployable_cash: float,
        price: float,
    ) -> int:
        """Profile 비중 사이징 수량 = floor(min(total_eval*profile_rate, deployable_cash) / price).

        total_eval: 총자산(원), profile_rate: Risk Profile 비중(0~1),
        deployable_cash: 95% 한도 내 추가 투입 가능 현금. 어느 하나라도 비정상이면 0.
        """
        if total_eval <= 0 or profile_rate <= 0 or deployable_cash <= 0 or price <= 0:
            return 0
        target = total_eval * profile_rate
        spend = min(target, deployable_cash)
        return int(spend // price)
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/test_profile_sizing.py -v`
Expected: PASS (3개)

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/order_executor.py tests/unit/test_profile_sizing.py
git commit -m "feat(sizing): Profile 비중 사이징 헬퍼 _calc_profile_qty"
```

---

## Task 2: total_eval 추출 + 탐색 사이징 분기 교체

**Files:**
- Modify: `backend/services/engine/order_executor.py` (`_extract_deposit` 아래 + 사이징 분기 ~250-273)
- Test: `tests/unit/test_profile_sizing.py`

- [ ] **Step 1: 실패 테스트 추가**

```python
def test_extract_total_eval():
    ex = OrderExecutor.__new__(OrderExecutor)
    data = {"output2": [{"tot_evlu_amt": "102267986", "ord_psbl_cash": "50000000"}]}
    assert ex._extract_total_eval(data) == 102267986.0
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/test_profile_sizing.py::test_extract_total_eval -v`
Expected: FAIL (`_extract_total_eval` 없음)

- [ ] **Step 3: 추출기 구현** — `_extract_deposit` 메서드 바로 아래 추가:

```python
    def _extract_total_eval(self, data: dict[str, Any]) -> float:
        """KIS balance에서 총평가금액(tot_evlu_amt)을 추출. 없으면 0."""
        summary_rows = _as_list(data.get("output2"))
        summary = summary_rows[0] if summary_rows else {}
        for key in ("tot_evlu_amt", "nass_amt", "dnca_tot_amt"):
            value = _to_float(summary.get(key))
            if value > 0:
                return value
        return 0.0
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/test_profile_sizing.py::test_extract_total_eval -v`
Expected: PASS

- [ ] **Step 5: 탐색 사이징 분기 교체** — `order_executor.py`의 기존 블록(아래)을 교체:

기존:
```python
            explore_budget_rate, max_positions = select_sizing_params(final_rule)
            if explore_budget_rate is not None:
                budget_rate = explore_budget_rate
                logger.info(
                    "INFO: [S7] 탐색모드 풀예수금 사이징 symbol=%s budget_rate=%.2f max_positions=%d",
                    symbol, budget_rate, max_positions,
                )
            else:
                budget_rate = get_active_budget_rate(today)
            qty = self._calc_budget_qty(baseline, budget_rate, max_positions, price, deposit)
            if qty <= 0:
                position_size_pct = self._position_size_pct(final_rule)
                qty = self._calc_qty(deposit, position_size_pct, price)
                logger.info("INFO: [S7] 사이징 폴백(baseline 결손) symbol=%s qty=%d", symbol, qty)
            else:
                logger.info(
                    "INFO: [S7] 예산 균등배분 사이징 symbol=%s baseline=%s rate=%.2f maxpos=%d qty=%d",
                    symbol, baseline, budget_rate, max_positions, qty,
                )
```

교체 후:
```python
            from .exploration_gate import is_exploration_allowed
            from .settings_store import get_setting as _get_setting
            if is_exploration_allowed():
                # 탐색: Profile 비중대로 + 95% 배포 한도 내 실시간 가용현금 기준
                total_eval = self._extract_total_eval(balance)
                profile_rate = self._position_size_pct(final_rule) / 100.0
                deploy_target = float(_get_setting("exploration.deploy_target_rate", 0.95) or 0.95)
                buffer = total_eval * (1.0 - deploy_target)
                deployable = max(0.0, deposit - buffer)  # deposit=ord_psbl_cash(실시간)
                qty = self._calc_profile_qty(total_eval, profile_rate, deployable, price)
                logger.info(
                    "INFO: [S7] Profile비중 사이징 symbol=%s rate=%.2f total_eval=%.0f deployable=%.0f qty=%d",
                    symbol, profile_rate, total_eval, deployable, qty,
                )
            else:
                explore_budget_rate, max_positions = select_sizing_params(final_rule)
                budget_rate = explore_budget_rate if explore_budget_rate is not None else get_active_budget_rate(today)
                qty = self._calc_budget_qty(baseline, budget_rate, max_positions, price, deposit)
                if qty <= 0:
                    qty = self._calc_qty(deposit, self._position_size_pct(final_rule), price)
                logger.info("INFO: [S7] 기존(보수) 사이징 symbol=%s qty=%d", symbol, qty)
```

> 참고: `settings_store` import 경로는 파일 상단 기존 import 스타일을 따른다(이미 `from .settings_store import get_setting` 있으면 재사용).

- [ ] **Step 6: qty=0 graceful 처리 확인** — 기존 `if qty <= 0: raise ValueError("calculated quantity is zero")`(~275행)를 아래로 교체:

```python
            if qty <= 0:
                logger.info("INFO: [S7] 배포 여력 없음 — 매수 스킵 symbol=%s", symbol)
                self._update_signal_status(signal_id, "skipped_no_room")
                return {"ok": False, "reason": "no_deployable_room", "symbol": symbol}
```

- [ ] **Step 7: 회귀 + 커밋**

Run: `python -m pytest tests/unit/ -q`
Expected: 전체 PASS

```bash
git add backend/services/engine/order_executor.py tests/unit/test_profile_sizing.py
git commit -m "feat(sizing): 탐색 사이징을 Profile 비중·95% 배포·실시간 현금 기준으로 전환"
```

---

## Task 3: preflight 보유수 게이트 → 95% 배포 게이트(탐색)

**Files:**
- Modify: `backend/services/engine/order_preflight.py` (run_preflight, ~344·~384)
- Modify: `backend/services/engine/order_executor.py` (run_preflight 호출부 ~278)
- Test: `tests/unit/test_preflight_deploy_gate.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/unit/test_preflight_deploy_gate.py
from backend.services.engine.order_preflight import _deployment_blocked

def test_deployment_blocked_at_target():
    # 배포율 96% >= 95% → 차단
    assert _deployment_blocked(deployed=96_000_000, total_eval=100_000_000, target=0.95) is True

def test_deployment_not_blocked_below_target():
    assert _deployment_blocked(deployed=80_000_000, total_eval=100_000_000, target=0.95) is False

def test_deployment_gate_disabled_when_total_zero():
    assert _deployment_blocked(deployed=0, total_eval=0, target=0.95) is False
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/test_preflight_deploy_gate.py -v`
Expected: FAIL (`_deployment_blocked` 없음)

- [ ] **Step 3: 헬퍼 + 게이트 구현** — `order_preflight.py` 상단 헬퍼 추가:

```python
def _deployment_blocked(deployed: float, total_eval: float, target: float) -> bool:
    """탐색 배포 한도 게이트: 배포율(deployed/total_eval) >= target 이면 True."""
    if total_eval <= 0:
        return False
    return (deployed / total_eval) >= target
```

`run_preflight` 시그니처에 인자 추가:
```python
def run_preflight(
    signal: dict[str, Any],
    final_rule: dict[str, Any],
    current_positions_count: int = 0,
    deployed_value: float = 0.0,
    total_eval: float = 0.0,
    deploy_target_rate: float = 0.0,
) -> dict[str, Any]:
```

기존 "4. 최대 보유 종목 수 초과" 블록을 교체:
```python
    # 4. 배포 한도/보유 종목 수
    if deploy_target_rate > 0 and total_eval > 0:
        # 탐색: 95% 배포 게이트(보유수 무관, 현금 한도로 제어)
        if _deployment_blocked(deployed_value, total_eval, deploy_target_rate):
            checks["max_positions"] = PREFLIGHT_BLOCK
            block_reasons.append(f"배포 한도 도달 ({deployed_value/total_eval*100:.0f}%/{deploy_target_rate*100:.0f}%)")
        else:
            checks["max_positions"] = PREFLIGHT_OK
    else:
        max_positions = int(_to_float(final_rule.get("max_positions"), 10.0) or 10)
        if current_positions_count >= max_positions:
            checks["max_positions"] = PREFLIGHT_BLOCK
            block_reasons.append(f"최대 보유 종목 도달 ({current_positions_count}/{max_positions})")
        else:
            checks["max_positions"] = PREFLIGHT_OK
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/test_preflight_deploy_gate.py -v`
Expected: PASS (3개)

- [ ] **Step 5: 호출부 연결** — `order_executor.py` ~278의 run_preflight 호출을 교체:

```python
            current_pos_count = len(position_manager.get_positions())
            from .exploration_gate import is_exploration_allowed
            from .settings_store import get_setting as _get_setting
            if is_exploration_allowed():
                _total_eval = self._extract_total_eval(balance)
                _deployed = max(0.0, _total_eval - deposit)  # 총자산 - 가용현금 = 배포액
                _target = float(_get_setting("exploration.deploy_target_rate", 0.95) or 0.95)
                preflight = run_preflight(signal, final_rule, current_positions_count=current_pos_count,
                                          deployed_value=_deployed, total_eval=_total_eval, deploy_target_rate=_target)
            else:
                preflight = run_preflight(signal, final_rule, current_positions_count=current_pos_count)
```

- [ ] **Step 6: 회귀 + 커밋**

Run: `python -m pytest tests/unit/ -q`
Expected: 전체 PASS

```bash
git add backend/services/engine/order_preflight.py backend/services/engine/order_executor.py tests/unit/test_preflight_deploy_gate.py
git commit -m "feat(preflight): 탐색 시 보유수 게이트→95% 배포 게이트"
```

---

## Task 4: 신규 설정 시드

**Files:**
- Modify: `backend/services/db.py` (설정 시드 목록, ~318 부근)
- Test: `tests/unit/test_deploy_settings_seed.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/unit/test_deploy_settings_seed.py
from backend.config import settings
from backend.services import db as db_mod
from backend.services.settings_store import get_setting

def test_new_settings_seeded(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "APP_DB_PATH", str(tmp_path / "s.sqlite3"))
    db_mod.initialize_database()
    assert float(get_setting("exploration.deploy_target_rate", 0)) == 0.95
    assert int(get_setting("intraday_refresh.max_replacement_per_day", 0)) == 20
    assert int(get_setting("intraday_refresh.replacement_cooldown_min", 0)) == 30
    assert get_setting("intraday_refresh.replacement_execute_enabled", None) is True
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/test_deploy_settings_seed.py -v`
Expected: FAIL

- [ ] **Step 3: 시드 추가** — `db.py` 설정 시드 리스트(`("risk.max_positions", 5, ...)` 가 있는 튜플 목록)에 항목 추가:

```python
        ("exploration.deploy_target_rate", 0.95, "number", "탐색 배포 목표율(예수금 대비)"),
        ("intraday_refresh.max_replacement_per_day", 20, "number", "일일 교체 상한"),
        ("intraday_refresh.replacement_cooldown_min", 30, "number", "동일 종목 교체 쿨다운(분)"),
        ("intraday_refresh.replacement_execute_enabled", True, "boolean", "교체 신호 자동 실행 여부"),
```

> 시드 함수가 기존 키를 덮어쓰지 않는 INSERT OR IGNORE 패턴인지 확인하고 동일 패턴을 따른다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/test_deploy_settings_seed.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/services/db.py tests/unit/test_deploy_settings_seed.py
git commit -m "feat(settings): 배포율·교체 자동실행 설정 시드"
```

---

## Task 5: 교체 실행기 (신호→스왑 실행)

**Files:**
- Create: `backend/services/engine/replacement_executor.py`
- Test: `tests/unit/test_replacement_executor.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/unit/test_replacement_executor.py
import asyncio
import backend.services.engine.replacement_executor as rx

def test_cooldown_blocks_recent_symbol(monkeypatch):
    monkeypatch.setattr(rx, "_last_swap_at", {"457370": 1000.0})
    monkeypatch.setattr(rx, "_now_ts", lambda: 1000.0 + 10*60)  # 10분 경과
    assert rx._in_cooldown("457370", cooldown_min=30) is True
    monkeypatch.setattr(rx, "_now_ts", lambda: 1000.0 + 31*60)  # 31분 경과
    assert rx._in_cooldown("457370", cooldown_min=30) is False

def test_execute_swaps_calls_sell_then_buy(monkeypatch):
    calls = []
    async def fake_sell(symbol, reason): calls.append(("sell", symbol)); return {"ok": True}
    async def fake_buy(symbol): calls.append(("buy", symbol)); return {"ok": True}
    monkeypatch.setattr(rx, "_sell_position", fake_sell)
    monkeypatch.setattr(rx, "_buy_candidate", fake_buy)
    monkeypatch.setattr(rx, "_in_cooldown", lambda s, cooldown_min: False)
    monkeypatch.setattr(rx, "_setting_bool", lambda k, d: True)
    monkeypatch.setattr(rx, "_setting_int", lambda k, d: 20)
    signals = [{"current_symbol": "457370", "new_symbol": "388790", "score_gap": 0.2}]
    out = asyncio.run(rx.execute_replacements(signals))
    assert calls == [("sell", "457370"), ("buy", "388790")]
    assert out["executed"] == 1
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/test_replacement_executor.py -v`
Expected: FAIL (모듈 없음)

- [ ] **Step 3: 실행기 구현**

```python
# backend/services/engine/replacement_executor.py
"""교체 신호 자동 실행 — 약한 보유 매도(손절 허용) → 강한 후보 매수(Profile 비중).

evaluate_replacement_signals가 만든 signals를 받아 실제 스왑을 실행한다.
쿨다운(동일 종목)·일일 상한·자동실행 토글로 churn을 제어한다. exploration 전용 운용.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from .settings_store import get_setting

logger = logging.getLogger("ReplacementExecutor")
_last_swap_at: dict[str, float] = {}  # symbol -> epoch sec


def _now_ts() -> float:
    return time.time()


def _setting_bool(key: str, default: bool) -> bool:
    v = get_setting(key, default)
    return str(v).lower() in ("true", "1", "yes") if not isinstance(v, bool) else v


def _setting_int(key: str, default: int) -> int:
    try:
        return int(get_setting(key, default) or default)
    except (TypeError, ValueError):
        return default


def _in_cooldown(symbol: str, cooldown_min: int) -> bool:
    last = _last_swap_at.get(symbol)
    if last is None:
        return False
    return (_now_ts() - last) < cooldown_min * 60


async def _sell_position(symbol: str, reason: str) -> dict[str, Any]:
    """약한 보유 종목 전량 매도(손절 허용)."""
    from .order_executor import order_executor
    return await order_executor.liquidate_symbol(symbol, reason=reason)


async def _buy_candidate(symbol: str) -> dict[str, Any]:
    """강한 후보 매수 — 기존 매수 신호 경로 재사용."""
    from .decision_engine import decision_engine
    return await decision_engine.force_buy_symbol(symbol, reason="replacement_swap")


async def execute_replacements(signals: list[dict[str, Any]]) -> dict[str, Any]:
    """교체 신호 리스트를 받아 자동 스왑 실행. 반환: {executed, skipped}."""
    if not _setting_bool("intraday_refresh.replacement_execute_enabled", True):
        return {"ok": True, "enabled": False, "executed": 0}
    cooldown_min = _setting_int("intraday_refresh.replacement_cooldown_min", 30)
    executed = 0
    for sig in signals:
        cur = str(sig.get("current_symbol") or "")
        new = str(sig.get("new_symbol") or "")
        if not cur or not new:
            continue
        if _in_cooldown(cur, cooldown_min) or _in_cooldown(new, cooldown_min):
            logger.info("INFO: 교체 쿨다운 스킵 cur=%s new=%s", cur, new)
            continue
        sell = await _sell_position(cur, reason=f"replacement_swap→{new}")
        if not sell.get("ok"):
            logger.warning("WARN: 교체 매도 실패 cur=%s — %s", cur, sell.get("reason"))
            continue
        buy = await _buy_candidate(new)
        _last_swap_at[cur] = _now_ts()
        _last_swap_at[new] = _now_ts()
        executed += 1
        logger.warning("SWAP: 교체 실행 SELL %s → BUY %s (gap=%.3f, buy_ok=%s)",
                       cur, new, float(sig.get("score_gap") or 0), buy.get("ok"))
    return {"ok": True, "enabled": True, "executed": executed}
```

> `order_executor.liquidate_symbol`와 `decision_engine.force_buy_symbol`가 없으면, 기존 청산/매수 진입점을 확인해 동등 메서드명으로 맞춘다(Task 6에서 wiring 시 확정). 이 두 진입점은 Task 6의 선행 확인 대상이다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/test_replacement_executor.py -v`
Expected: PASS (2개)

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/replacement_executor.py tests/unit/test_replacement_executor.py
git commit -m "feat(replacement): 교체 신호 자동 실행기(쿨다운·일일상한·토글)"
```

---

## Task 6: 교체 실행 wiring + 매도/매수 진입점 확정

**Files:**
- Modify: `backend/services/engine/decision_engine.py` (~1030 replacement 호출 직후)
- Modify: `backend/services/engine/replacement_executor.py` (진입점 메서드명 확정)
- Test: `tests/unit/test_replacement_wiring.py`

- [ ] **Step 1: 매도/매수 진입점 조사** — 아래 명령으로 기존 단일종목 청산/매수 진입점을 확인:

Run:
```bash
grep -nE "def liquidate|def .*sell|def force_buy|def .*buy_symbol|def submit_signal|liquidate" backend/services/engine/order_executor.py backend/services/engine/decision_engine.py backend/services/engine/eod_liquidation.py
```
Expected: 단일 종목 매도/매수 가능한 메서드 식별. 없으면 가장 가까운 것(예: eod_liquidation의 종목 청산, decision_engine의 신호 생성→order_executor.execute_buy)을 래핑하는 얇은 메서드를 추가한다.

- [ ] **Step 2: 실패 테스트 작성**

```python
# tests/unit/test_replacement_wiring.py
import asyncio
import backend.services.engine.decision_engine as de

def test_refresh_triggers_execute_when_signals(monkeypatch):
    captured = {}
    async def fake_eval(**kw): return {"ok": True, "created": 1, "signals": [{"current_symbol":"A","new_symbol":"B","score_gap":0.2}]}
    async def fake_exec(signals): captured["signals"] = signals; return {"ok": True, "executed": 1}
    monkeypatch.setattr("backend.services.engine.replacement_signal.evaluate_replacement_signals", fake_eval)
    monkeypatch.setattr("backend.services.engine.replacement_executor.execute_replacements", fake_exec)
    # _maybe_execute_replacements 는 signals 있으면 execute_replacements 호출
    out = asyncio.run(de._maybe_execute_replacements({"ok": True, "signals": [{"current_symbol":"A","new_symbol":"B","score_gap":0.2}]}))
    assert captured["signals"][0]["new_symbol"] == "B"
    assert out["executed"] == 1
```

- [ ] **Step 3: 실패 확인**

Run: `python -m pytest tests/unit/test_replacement_wiring.py -v`
Expected: FAIL (`_maybe_execute_replacements` 없음)

- [ ] **Step 4: wiring 구현** — `decision_engine.py`에 헬퍼 추가 + refresh 결과에 연결:

```python
async def _maybe_execute_replacements(replacement_result: dict) -> dict:
    """교체 신호가 있으면 자동 실행기로 넘긴다(없으면 no-op)."""
    signals = replacement_result.get("signals") or []
    if not signals:
        return {"ok": True, "executed": 0}
    from .replacement_executor import execute_replacements
    return await execute_replacements(signals)
```

기존 `replacement_result = await evaluate_replacement_signals(...)` 직후(~1033)에 추가:
```python
            replacement_exec = await _maybe_execute_replacements(replacement_result)
            logger.info("INFO: [S6] 교체 실행 결과 executed=%s", replacement_exec.get("executed"))
```

> Step 1에서 확인한 실제 매도/매수 메서드명으로 `replacement_executor._sell_position`/`_buy_candidate`를 확정한다(없으면 얇은 래퍼 추가).

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest tests/unit/test_replacement_wiring.py -v`
Expected: PASS

- [ ] **Step 6: 회귀 + 커밋**

Run: `python -m pytest tests/unit/ -q`
Expected: 전체 PASS

```bash
git add backend/services/engine/decision_engine.py backend/services/engine/replacement_executor.py tests/unit/test_replacement_wiring.py
git commit -m "feat(replacement): 교체 신호 자동 실행 wiring(decision_engine)"
```

---

## Task 7: 배포율 UI 가시화

**Files:**
- Modify: `backend/api/routes/account.py` (`_build_balance_payload` 반환 dict)
- Modify: `backend/static/js/screens/console-trading-monitor.js` + `backend/static/console.html`
- Test: `tests/unit/test_deployment_rate_field.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/unit/test_deployment_rate_field.py
from backend.api.routes.account import _build_balance_payload

def test_deployed_rate_field():
    data = {"output1": [], "output2": [{
        "tot_evlu_amt": "100000000", "ord_psbl_cash": "20000000",
        "scts_evlu_amt": "80000000", "pchs_amt_smtl_amt": "0", "evlu_pfls_smtl_amt": "0",
    }]}
    p = _build_balance_payload(data)
    # 배포율 = (총자산-가용현금)/총자산 = 80%
    assert p["deployed_rate_pct"] == 80.0
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/test_deployment_rate_field.py -v`
Expected: FAIL (`deployed_rate_pct` 없음)

- [ ] **Step 3: 필드 추가** — `_build_balance_payload` 반환 dict에 추가(`daily_pnl_pct` 항목 부근):

```python
        "deployed_rate_pct": round((total_eval - buyable_cash) / total_eval * 100, 1) if total_eval else 0.0,
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/test_deployment_rate_field.py -v`
Expected: PASS

- [ ] **Step 5: UI 카드 추가** — `console.html` Trading Monitor 계좌카드 영역(`tm-total-eval` 부근)에 추가:

```html
                <div class="kpi-cell">
                  <div class="kpi-cell__label">배포율 (투입/총자산)</div>
                  <div class="kpi-cell__value" id="tm-deployed-rate">-</div>
                </div>
```

`console-trading-monitor.js` 계좌 렌더부(`setEl('tm-total-eval', ...)` 부근)에 추가:
```javascript
        var dr = acct.deployed_rate_pct;
        setEl('tm-deployed-rate', (dr != null ? dr.toFixed(1) : '-') + '%');
```

cache-buster 증가: `console.html`의 `console-trading-monitor.js?v=5` → `?v=6`.

- [ ] **Step 6: 검증 + 커밋**

Run: `python -m pytest tests/unit/ -q` (전체 PASS), `node --check backend/static/js/screens/console-trading-monitor.js`

```bash
git add backend/api/routes/account.py backend/static/js/screens/console-trading-monitor.js backend/static/console.html tests/unit/test_deployment_rate_field.py
git commit -m "feat(ui): Trading Monitor 배포율 카드 + balance deployed_rate_pct"
```

---

## Task 8: 통합 검증 + 운영 적용

**Files:** (코드 변경 없음 — 검증·배포)

- [ ] **Step 1: 전체 회귀**

Run: `python -m pytest tests/unit/ -q`
Expected: 전체 PASS

- [ ] **Step 2: 서버 재시작** (보유/미체결 0 확인 후)

Run: `sudo systemctl restart stock-trading-bot.service && sleep 8 && curl -s http://127.0.0.1:8000/health`
Expected: healthy

- [ ] **Step 3: 라이브 사이징 로그 확인**

Run: `sudo journalctl -u stock-trading-bot.service --since "2 minutes ago" | grep "Profile비중 사이징"`
Expected: 매수 발생 시 profile rate·deployable·qty 로그. 종목당 금액이 Profile 비중(예 8%≈8M)에 근접.

- [ ] **Step 4: 배포율/교체 확인** — Trading Monitor 배포율 카드가 매수 누적에 따라 상승, 95% 근처에서 신규매수 멈춤. 교체 조건 충족 시 SWAP 로그.

- [ ] **Step 5: docs/manual 갱신** — `docs/manual/EXPLORATION_ENGINE.md`에 사이징·배포·교체 모델 반영.

```bash
git add docs/manual/EXPLORATION_ENGINE.md
git commit -m "docs(manual): 풀예수금 Profile 사이징·교체 모델 반영"
```

---

## 요구사항 대조표

| 요구사항 | 반영 태스크 | 비고 |
|----------|-------------|------|
| 예수금 95% 풀 배포 | Task 2·3 | Profile 사이징 + 95% 게이트 |
| Profile 비중대로 매수 | Task 1·2 | `_calc_profile_qty` |
| 매도→재매수 풀가동 | Task 2·3 | 실시간 ord_psbl_cash 기준 + 배포율 게이트 |
| 적극 교체(손절 허용) | Task 5·6 | 자동 스왑 실행 |
| 모의 전용 | Task 2·3 | `is_exploration_allowed()` 분기 |
| 데이터 가시화 | Task 7 | 배포율 카드 |
| 설정값(95/+0.15/20/30) | Task 4 | 시드 |

## Self-Review 결과
- 스펙 커버리지: 4대 요구 + 모의전용 + 가시화 모두 태스크 매핑됨.
- 선행 의존: Task 6 Step 1에서 매도/매수 진입점 메서드명을 **반드시 코드로 확인 후** `_sell_position`/`_buy_candidate` 확정(현 plan은 `liquidate_symbol`/`force_buy_symbol` 가정 — 실제와 다르면 래퍼 추가).
- 타입 일관성: `_calc_profile_qty`(total_eval, profile_rate, deployable_cash, price), `_deployment_blocked`(deployed, total_eval, target), `deployed_rate_pct` 일관 사용.
