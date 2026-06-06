# 탐색 엔진 Phase 1d — S6 OR 통합·등락률 소스·모의전용 게이트·풀예수금 사이징 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Phase 1a~1c 산출물(조건 프레임워크 OR 평가기 · BarEngine state · 통짜 태깅)을 S6 실거래 경로에 결선해, **모의계좌일 때만** 탐색모드(모든 그룹 OR 매수 + 풀예수금·다종목 사이징)를 켜고, S3 유니버스에 **등락률(상승률) 순위 소스를 추가**해 강세주를 합류시키며, 매수 발생 시 선정사유·발화그룹·조건상태·시장맥락을 한 행으로 태깅한다.

**Architecture:** 두 개의 순수 헬퍼 모듈을 새로 만들고(`exploration_gate.py` — 모의전용 게이트 + 사이징 파라미터 선택, `exploration_decision.py` — `_on_tick`이 호출하는 결정 헬퍼), 기존 3개 파일(`universe_filter.py`·`order_executor.py`·`decision_engine.py`)에 최소 결선을 가한다. 모든 신규 로직은 KIS/WS/DB 없이 mock·합성 입력으로 단위테스트 가능한 순수 함수로 격리하고, 기존 게이트(`_evaluate_rules`/`_rules_allow_signal`)·중복가드(`managed_symbols`/`_signal_sent`/`_block_cooldown`)는 그대로 보존한다.

**Tech Stack:** Python 3, SQLite(`backend/services/settings_store.get_setting`), pytest(unittest.mock). 실행: `PYTHONPATH=. .venv/bin/python -m pytest`.

**설계서:** `docs/superpowers/specs/2026-06-06-exploration-buy-strategy-engine-design.md`

**선행 계획(인터페이스 고정 — 본 계획은 그대로 사용):**
- Phase 1a `docs/superpowers/plans/2026-06-06-exploration-engine-phase1a-condition-framework.md`
  - `buy_condition_framework.evaluate_groups_or(groups, conditions_by_id, state) -> {"any": bool, "fired": [group_names]}`
  - `buy_condition_framework.load_conditions() -> {id: {...}}`, `buy_condition_framework.load_groups() -> [{...}]`
  - `state` dict 키: `change_rate, 체결강도, tick_vol_mult, tsi, vwap_position, day_high_breakout, pullback_rebound, rising_bars, time_hhmm`
- Phase 1b `docs/superpowers/plans/2026-06-06-exploration-engine-phase1b-ws-bars-signals.md`
  - `intraday_bar_engine.BarEngine.compute_signal_state(symbol) -> state dict`
- Phase 1c `docs/superpowers/plans/2026-06-06-exploration-engine-phase1c-trade-tagging.md`
  - `trade_tagging.record_entry_tag(*, order_id, symbol, trade_date, selection_reason, fired_groups, condition_states, market_context) -> id` (키워드 전용)
  - `trade_tagging.build_selection_reason(candidate) -> {"sources": [...], "scores": {...}, "llm_note": "..."}`

---

## 확정 사실 (코드 확인 완료 — 추측 아님)

- **가상(모의)계좌 판별:** `backend/services/kis/common/client.py` 의 `KISClient._is_virtual_trading()` →
  `return "openapivts" in self.base_url.lower()`. 모듈 전역 인스턴스는 `kis_client`(같은 파일 끝).
  Phase 1d 게이트는 이 메서드를 통해 모의 여부를 판정한다.
- **신규 설정 키(모두 `settings_store.get_setting(key, default)` 로 읽음):**
  - `engine.exploration_mode` (bool, 기본 `False`) — 탐색모드 ON/OFF 마스터 스위치.
  - `exploration.max_positions` (int, 기본 `40`) — 탐색모드 슬롯 수(풀예수금 다종목).
  - `exploration.budget_rate` (float, 기본 `0.95`) — 탐색모드 예산률(풀예수금).
- **기존 사이징:** `order_executor._calc_budget_qty(baseline, budget_rate, max_positions, price, available_cash)` 는
  `_execute_signal_inner` 에서 `budget_rate = daily_capital.get_active_budget_rate(today)`,
  `max_positions = int(final_rule.get("max_positions") or 7)` 로 호출된다. Phase 1d는 탐색 허용 시 이 두 입력만 교체한다.
- **기존 S3 소스:** `universe_filter.run_universe_filter` 는 `get_volume_rank(...)` + `get_price_rank(sort_by="trade_amount")` 2소스를
  `_merge_and_deduplicate(volume_items, trade_items)` 로 병합한다. Phase 1d는 `get_price_rank(sort_by="change_rate")` 를 3번째 소스로 추가한다.
- **기존 매수 게이트:** `decision_engine._on_tick` 는 `_evaluate_rules` → `_rules_allow_signal(matched)` 통과 시 `_emit_signal`.
  중복가드: `managed_symbols`(보유 제외), `symbol not in self._candidates`, `symbol in self._signal_sent`, `_block_cooldown`.
  Phase 1d는 이 게이트를 **대체하지 않고**, 탐색 허용 시 OR 발화를 **추가 매수 트리거**로 얹는다(가드는 전부 유지).

---

## File Structure

| 파일 | 책임 | 생성/수정 |
|---|---|---|
| `backend/services/engine/exploration_gate.py` | `is_exploration_allowed()`(설정 AND 모의) + `select_sizing_params(final_rule)`(탐색이면 풀예수금 파라미터, 아니면 기존) — 순수·mock 테스트 | 생성 |
| `backend/services/engine/exploration_decision.py` | `evaluate_exploration_buy(symbol, bar_engine, ...)` — compute_signal_state → evaluate_groups_or → {fired, condition_states, any} 조립(순수 함수, 가드는 호출부) | 생성 |
| `backend/services/engine/universe_filter.py` | 등락률 순위 소스 3번째로 추가 + `_merge_and_deduplicate` 가 change_rate_rank 부여 | 수정 |
| `backend/services/engine/order_executor.py` | `_execute_signal_inner` 사이징 파라미터를 `select_sizing_params` 결과로 교체 | 수정 |
| `backend/services/engine/decision_engine.py` | `_on_tick` 에 탐색 OR 분기 + 매수·태깅 결선(BarEngine 보유, prior 게이트/가드 유지) | 수정 |
| `tests/unit/test_exploration_gate.py` | 게이트·사이징 셀렉터 단위테스트 | 생성 |
| `tests/unit/test_exploration_decision.py` | OR 결정 헬퍼 단위테스트 | 생성 |
| `tests/unit/test_universe_filter_change_rate_source.py` | 등락률 소스 병합/점수 단위테스트 | 생성 |

---

## Task 1: 모의전용 게이트 `is_exploration_allowed()`

설정 `engine.exploration_mode` 가 켜져 있고 **AND** KIS가 모의(`openapivts`)일 때만 `True`. 실계좌면 설정과 무관하게 `False`(하드 차단).

**Files:**
- Create: `backend/services/engine/exploration_gate.py`
- Test: `tests/unit/test_exploration_gate.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/test_exploration_gate.py`:
```python
from unittest.mock import patch

import backend.services.engine.exploration_gate as eg


def test_allowed_when_setting_on_and_virtual():
    with patch.object(eg, "get_setting", return_value=True), \
         patch.object(eg, "_is_virtual", return_value=True):
        assert eg.is_exploration_allowed() is True


def test_blocked_when_setting_on_but_real_account():
    # 실계좌면 설정이 켜져 있어도 하드 차단
    with patch.object(eg, "get_setting", return_value=True), \
         patch.object(eg, "_is_virtual", return_value=False):
        assert eg.is_exploration_allowed() is False


def test_blocked_when_setting_off_even_if_virtual():
    with patch.object(eg, "get_setting", return_value=False), \
         patch.object(eg, "_is_virtual", return_value=True):
        assert eg.is_exploration_allowed() is False


def test_blocked_when_both_off():
    with patch.object(eg, "get_setting", return_value=False), \
         patch.object(eg, "_is_virtual", return_value=False):
        assert eg.is_exploration_allowed() is False


def test_setting_string_truthy_is_coerced():
    # system_settings JSON 이 "true"/"1" 문자열로 와도 켜진 것으로 본다
    with patch.object(eg, "_is_virtual", return_value=True):
        with patch.object(eg, "get_setting", return_value="true"):
            assert eg.is_exploration_allowed() is True
        with patch.object(eg, "get_setting", return_value="0"):
            assert eg.is_exploration_allowed() is False
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_exploration_gate.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.services.engine.exploration_gate'`.

- [ ] **Step 3: 구현**

`backend/services/engine/exploration_gate.py`:
```python
"""탐색모드(OR 폭증·풀예수금) 안전 게이트 + 사이징 파라미터 선택.

🔒 탐색모드는 KIS 모의(openapivts)일 때만 허용한다. 실계좌면 설정이 켜져 있어도 하드 차단해
실수로 80패가 실손실이 되는 것을 막는다(설계서 "안전장치" 모의 전용 게이트).

순수 헬퍼 — KIS/WS/DB 부작용 없음. get_setting/_is_virtual 을 패치해 단위테스트한다.
"""

from __future__ import annotations

import logging
from typing import Any

from ..settings_store import get_setting

logger = logging.getLogger("ExplorationGate")

# 탐색모드 사이징 기본값(설계서 §자본·포지션: max_positions↑·예산률↑)
_DEFAULT_MAX_POSITIONS = 40
_DEFAULT_BUDGET_RATE = 0.95


def _is_virtual() -> bool:
    """KIS 클라이언트가 모의투자(openapivts) 환경인지 반환한다.

    별도 함수로 분리해 단위테스트에서 패치 가능하게 한다.
    """
    from ..kis.common.client import kis_client

    return kis_client._is_virtual_trading()


def _coerce_bool(value: Any) -> bool:
    """system_settings 값(bool/str/int)을 불리언으로 강제한다."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def is_exploration_allowed() -> bool:
    """탐색모드 허용 여부 = engine.exploration_mode 켜짐 AND KIS 모의계좌.

    실계좌면 무조건 False(하드 차단).
    """
    if not _is_virtual():
        return False
    return _coerce_bool(get_setting("engine.exploration_mode", False))


def select_sizing_params(final_rule: dict[str, Any]) -> tuple[float | None, int]:
    """사이징 파라미터 (budget_rate, max_positions) 를 반환한다.

    탐색 허용 시 풀예수금 파라미터(exploration.budget_rate / exploration.max_positions),
    아니면 (None, 기존 final_rule.max_positions) 를 반환한다. budget_rate=None 은
    "탐색 아님 → 호출부가 기존 daily_capital.get_active_budget_rate 를 쓰라"는 신호다.

    Args:
        final_rule: rule_cache.get_rule(symbol) 결과(기존 max_positions 소스).
    """
    if is_exploration_allowed():
        budget_rate = float(get_setting("exploration.budget_rate", _DEFAULT_BUDGET_RATE) or _DEFAULT_BUDGET_RATE)
        max_positions = int(get_setting("exploration.max_positions", _DEFAULT_MAX_POSITIONS) or _DEFAULT_MAX_POSITIONS)
        logger.info(
            "INFO: [탐색] 풀예수금 사이징 적용 budget_rate=%.2f max_positions=%d", budget_rate, max_positions
        )
        return budget_rate, max_positions
    try:
        existing_max = int(float(final_rule.get("max_positions") or 7))
    except (TypeError, ValueError):
        existing_max = 7
    return None, existing_max
```

- [ ] **Step 4: 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_exploration_gate.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/exploration_gate.py tests/unit/test_exploration_gate.py
git commit -m "feat: 탐색모드 모의전용 게이트 is_exploration_allowed (설정 AND openapivts, 실계좌 하드차단)"
```

---

## Task 2: 사이징 파라미터 셀렉터 `select_sizing_params`

Task 1에서 `select_sizing_params` 를 이미 구현했다. 이 Task는 그 동작을 별도 테스트로 고정한다(탐색 ON → 풀예수금 파라미터, 탐색 OFF → budget_rate None + 기존 max_positions).

**Files:**
- Test: `tests/unit/test_exploration_gate.py` (추가)

- [ ] **Step 1: 실패 테스트 추가**

`tests/unit/test_exploration_gate.py` 끝에 추가:
```python
def test_sizing_params_exploration_uses_full_deposit_params():
    def _fake_setting(key, default=None):
        return {
            "engine.exploration_mode": True,
            "exploration.budget_rate": 0.95,
            "exploration.max_positions": 40,
        }.get(key, default)

    with patch.object(eg, "_is_virtual", return_value=True), \
         patch.object(eg, "get_setting", side_effect=_fake_setting):
        budget_rate, max_positions = eg.select_sizing_params({"max_positions": 7})
    assert budget_rate == 0.95
    assert max_positions == 40


def test_sizing_params_non_exploration_keeps_existing_max_and_none_rate():
    with patch.object(eg, "_is_virtual", return_value=False), \
         patch.object(eg, "get_setting", return_value=True):
        budget_rate, max_positions = eg.select_sizing_params({"max_positions": 5})
    assert budget_rate is None   # 호출부가 기존 get_active_budget_rate 사용
    assert max_positions == 5


def test_sizing_params_non_exploration_defaults_max_to_7_when_missing():
    with patch.object(eg, "_is_virtual", return_value=False), \
         patch.object(eg, "get_setting", return_value=True):
        budget_rate, max_positions = eg.select_sizing_params({})
    assert budget_rate is None
    assert max_positions == 7
```

- [ ] **Step 2: 실패 확인 후 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_exploration_gate.py -q`
Expected: 새 3개 테스트 PASS (Task 1 구현이 이미 충족 — 회귀 없이 8 PASS). 만약 실패하면 `select_sizing_params` 구현을 위 테스트에 맞춰 수정.

- [ ] **Step 3: 커밋**

```bash
git add tests/unit/test_exploration_gate.py
git commit -m "test: select_sizing_params 풀예수금/기존 분기 고정"
```

---

## Task 3: order_executor 사이징 결선 (탐색 허용 시 풀예수금 파라미터)

`_execute_signal_inner` 의 사이징 입력을 `select_sizing_params` 결과로 교체한다. 탐색 OFF면 기존과 100% 동일(budget_rate=None → `get_active_budget_rate`, max_positions=기존). 탐색 ON이면 풀예수금 파라미터.

**Files:**
- Modify: `backend/services/engine/order_executor.py:249-265`

- [ ] **Step 1: 현재 사이징 블록 확인**

`backend/services/engine/order_executor.py` 의 `_execute_signal_inner` 안, 현재 코드:
```python
            balance = await self._get_cached_balance()
            deposit = self._extract_deposit(balance)
            from .daily_capital import get_baseline, get_active_budget_rate
            baseline = get_baseline(today)
            budget_rate = get_active_budget_rate(today)
            max_positions = int(_to_float(final_rule.get("max_positions"), 7.0) or 7)
            qty = self._calc_budget_qty(baseline, budget_rate, max_positions, price, deposit)
```

- [ ] **Step 2: 구현 — 사이징 파라미터를 셀렉터로 교체**

위 블록을 아래로 교체:
```python
            balance = await self._get_cached_balance()
            deposit = self._extract_deposit(balance)
            from .daily_capital import get_baseline, get_active_budget_rate
            from .exploration_gate import select_sizing_params
            baseline = get_baseline(today)
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
```

> `_calc_budget_qty`·폴백(`_calc_qty`)·preflight 등 이후 로직은 변경 없음. 탐색 OFF면 `explore_budget_rate is None` → 기존 흐름 그대로.

- [ ] **Step 3: import 회귀 확인**

Run: `PYTHONPATH=. .venv/bin/python -c "import backend.services.engine.order_executor as oe; print('import ok')"`
Expected: `import ok`.

기존 사이징 테스트 회귀 없음:
Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_budget_sizing.py -q`
Expected: PASS (기존 전부 — 탐색 OFF 기본값에서 동작 불변).

- [ ] **Step 4: 커밋**

```bash
git add backend/services/engine/order_executor.py
git commit -m "feat: S7 사이징을 select_sizing_params 로 결선 — 탐색 ON 시 풀예수금(0.95/40), OFF 시 기존 불변"
```

---

## Task 4: 등락률 순위 소스를 S3 3번째 소스로 추가 (`_merge_and_deduplicate`)

`_merge_and_deduplicate` 를 등락률 순위 리스트까지 받아 `change_rate_rank` 를 부여하도록 확장하고, 이미 병합된 종목에는 rank만 추가한다. 기존 호출(2-인자)도 깨지지 않게 3번째 인자는 기본값 `None`.

**Files:**
- Modify: `backend/services/engine/universe_filter.py`
- Test: `tests/unit/test_universe_filter_change_rate_source.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/test_universe_filter_change_rate_source.py`:
```python
import backend.services.engine.universe_filter as uf


def test_merge_adds_change_rate_rank_to_existing_symbol():
    volume_items = [{"symbol": "005930", "name": "삼성전자", "price": 1000,
                     "change_rate": 2.3, "volume": 100}]
    trade_items = [{"symbol": "005930", "trade_amount": 5000}]
    change_items = [{"symbol": "005930", "change_rate": 2.3}]
    merged = uf._merge_and_deduplicate(volume_items, trade_items, change_items)
    row = {r["symbol"]: r for r in merged}["005930"]
    assert row["volume_rank"] == 1
    assert row["trade_rank"] == 1
    assert row["change_rate_rank"] == 1


def test_merge_change_rate_only_symbol_is_surfaced():
    # 거래량/거래대금엔 없고 등락률 순위에만 있는 강세주도 유니버스에 합류
    merged = uf._merge_and_deduplicate(
        [],
        [],
        [{"symbol": "111111", "name": "급등주", "price": 500, "change_rate": 12.0}],
    )
    row = {r["symbol"]: r for r in merged}["111111"]
    assert row["change_rate_rank"] == 1
    assert row["volume_rank"] == 9999
    assert row["trade_rank"] == 9999
    assert row["change_rate"] == 12.0


def test_merge_change_rate_rank_sentinel_when_absent():
    # 등락률 소스 미제공(None) 시 모든 종목 change_rate_rank=9999
    merged = uf._merge_and_deduplicate(
        [{"symbol": "005930", "name": "삼성전자", "price": 1000, "change_rate": 2.3, "volume": 100}],
        [],
        None,
    )
    row = {r["symbol"]: r for r in merged}["005930"]
    assert row["change_rate_rank"] == 9999


def test_merge_two_arg_call_still_works():
    # 하위호환: 기존 2-인자 호출(등락률 소스 없음)도 동작
    merged = uf._merge_and_deduplicate(
        [{"symbol": "005930", "name": "삼성전자", "price": 1000, "change_rate": 2.3, "volume": 100}],
        [{"symbol": "005930", "trade_amount": 5000}],
    )
    row = {r["symbol"]: r for r in merged}["005930"]
    assert row["change_rate_rank"] == 9999
    assert row["trade_rank"] == 1
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_universe_filter_change_rate_source.py -q`
Expected: FAIL — `TypeError: _merge_and_deduplicate() takes 2 positional arguments but 3 were given` (3-인자 테스트) / `KeyError: 'change_rate_rank'`.

- [ ] **Step 3: 구현 — `_merge_and_deduplicate` 확장**

`backend/services/engine/universe_filter.py` 의 `_merge_and_deduplicate` 전체를 아래로 교체:
```python
def _merge_and_deduplicate(
    volume_items: list[dict[str, Any]],
    trade_items: list[dict[str, Any]],
    change_items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """거래량·거래대금·등락률 순위를 병합하고 중복을 제거한다.

    Args:
        volume_items: 거래량 순위 리스트(순서=순위).
        trade_items: 거래대금 순위 리스트(순서=순위).
        change_items: 등락률(상승률) 순위 리스트(순서=순위). None이면 등락률 소스 미사용.
    """
    merged: dict[str, dict[str, Any]] = {}

    for idx, item in enumerate(volume_items):
        sym = item.get("symbol", "")
        if not sym:
            continue
        merged[sym] = {
            "symbol": sym,
            "name": item.get("name", ""),
            "price": item.get("price", 0),
            "change_rate": item.get("change_rate", 0.0),
            "volume": item.get("volume", 0),
            "trade_amount": 0,
            "volume_rank": idx + 1,
            "trade_rank": 9999,
            "change_rate_rank": 9999,
        }

    for idx, item in enumerate(trade_items):
        sym = item.get("symbol", "")
        if not sym:
            continue
        if sym in merged:
            merged[sym]["trade_amount"] = item.get("trade_amount", 0)
            merged[sym]["trade_rank"] = idx + 1
        else:
            merged[sym] = {
                "symbol": sym,
                "name": item.get("name", ""),
                "price": item.get("price", 0),
                "change_rate": item.get("change_rate", 0.0),
                "volume": 0,
                "trade_amount": item.get("trade_amount", 0),
                "volume_rank": 9999,
                "trade_rank": idx + 1,
                "change_rate_rank": 9999,
            }

    for idx, item in enumerate(change_items or []):
        sym = item.get("symbol", "")
        if not sym:
            continue
        if sym in merged:
            merged[sym]["change_rate_rank"] = idx + 1
            if not merged[sym].get("change_rate"):
                merged[sym]["change_rate"] = item.get("change_rate", 0.0)
        else:
            merged[sym] = {
                "symbol": sym,
                "name": item.get("name", ""),
                "price": item.get("price", 0),
                "change_rate": item.get("change_rate", 0.0),
                "volume": 0,
                "trade_amount": 0,
                "volume_rank": 9999,
                "trade_rank": 9999,
                "change_rate_rank": idx + 1,
            }

    return list(merged.values())
```

- [ ] **Step 4: 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_universe_filter_change_rate_source.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/universe_filter.py tests/unit/test_universe_filter_change_rate_source.py
git commit -m "feat: S3 _merge_and_deduplicate 등락률 순위 소스 합류 + change_rate_rank 부여"
```

---

## Task 5: 등락률 순위 점수 반영 (`_score_and_rank` change_rate_rank 가산)

병합된 `change_rate_rank` 를 점수에 반영해 등락률 상위 강세주가 surfacing 되도록 한다. 기존 가중치(trade/volume/change)는 보존하고, 등락률 순위 점수를 등락률 정규화 점수와 **둘 다** 합산하지 않도록, 기존 `change` 가중을 "등락률 순위 점수"로 정의한다(순위가 있으면 순위 점수, 없으면 기존 등락률 정규화 점수로 폴백).

**Files:**
- Modify: `backend/services/engine/universe_filter.py`
- Test: `tests/unit/test_universe_filter_change_rate_source.py`

- [ ] **Step 1: 실패 테스트 추가**

`tests/unit/test_universe_filter_change_rate_source.py` 끝에 추가:
```python
def test_score_uses_change_rate_rank_when_present():
    weights = {"trade": 0.5, "volume": 0.3, "change": 0.2}
    items = [
        {"symbol": "A", "change_rate": 1.0, "trade_rank": 9999, "volume_rank": 9999, "change_rate_rank": 1},
        {"symbol": "B", "change_rate": 1.0, "trade_rank": 9999, "volume_rank": 9999, "change_rate_rank": 5},
    ]
    ranked = uf._score_and_rank(items, total=5, weights=weights)
    by_sym = {r["symbol"]: r for r in ranked}
    # 등락률 순위 1위가 5위보다 높은 점수
    assert by_sym["A"]["score"] > by_sym["B"]["score"]


def test_score_falls_back_to_change_rate_normalized_when_no_rank():
    weights = {"trade": 0.5, "volume": 0.3, "change": 0.2}
    items = [
        {"symbol": "A", "change_rate": 20.0, "trade_rank": 9999, "volume_rank": 9999, "change_rate_rank": 9999},
        {"symbol": "B", "change_rate": -10.0, "trade_rank": 9999, "volume_rank": 9999, "change_rate_rank": 9999},
    ]
    ranked = uf._score_and_rank(items, total=5, weights=weights)
    by_sym = {r["symbol"]: r for r in ranked}
    # 순위 없을 땐 등락률 정규화로 폴백 — +20%가 -10%보다 높은 점수
    assert by_sym["A"]["score"] > by_sym["B"]["score"]
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_universe_filter_change_rate_source.py -k score -q`
Expected: FAIL — 등락률 순위가 점수에 반영 안 돼 A==B(현재 change_normalized만 사용).

- [ ] **Step 3: 구현 — `_score_and_rank` 의 change 점수 산식 교체**

`backend/services/engine/universe_filter.py` 의 `_score_and_rank` 내부 루프에서 아래 블록:
```python
        raw_volume_rank = item.get("volume_rank", total)
        volume_score = (total - raw_volume_rank + 1) / total if raw_volume_rank <= total else 0.0
        change_normalized = (item.get("change_rate", 0.0) + 30.0) / 60.0
        change_normalized = max(0.0, min(1.0, change_normalized))

        total_score = (
            trade_w * trade_score +
            volume_w * volume_score +
            change_w * change_normalized
        )
```
을 아래로 교체:
```python
        raw_volume_rank = item.get("volume_rank", total)
        volume_score = (total - raw_volume_rank + 1) / total if raw_volume_rank <= total else 0.0
        # 등락률 순위가 있으면 순위 점수, 없으면(=9999 sentinel) 등락률 정규화 점수로 폴백
        raw_change_rank = item.get("change_rate_rank", 9999)
        if raw_change_rank <= total:
            change_score = (total - raw_change_rank + 1) / total
        else:
            change_score = (item.get("change_rate", 0.0) + 30.0) / 60.0
        change_score = max(0.0, min(1.0, change_score))

        total_score = (
            trade_w * trade_score +
            volume_w * volume_score +
            change_w * change_score
        )
```

- [ ] **Step 4: 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_universe_filter_change_rate_source.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/universe_filter.py tests/unit/test_universe_filter_change_rate_source.py
git commit -m "feat: S3 점수에 등락률 순위 반영(순위 점수, 미수신 시 등락률 정규화 폴백)"
```

---

## Task 6: 등락률 소스 fetch + selection_reason 태깅 결선 (`run_universe_filter`)

`run_universe_filter` 의 KIS 병렬 호출에 `get_price_rank(sort_by="change_rate")` 를 추가하고, `_merge_and_deduplicate` 에 3번째 인자로 전달한다. 또한 결과 항목에 `change_rate_rank` 가 남으므로 Phase 1c `build_selection_reason` 이 "등락률순위#N" 을 surfacing 할 수 있도록 `build_selection_reason` 에 등락률 소스를 추가한다.

**Files:**
- Modify: `backend/services/engine/universe_filter.py:399-422`
- Modify: `backend/services/engine/trade_tagging.py` (`build_selection_reason` 에 change_rate_rank 소스 추가)
- Test: `tests/unit/test_universe_filter_change_rate_source.py` (build_selection_reason 등락률 소스)

- [ ] **Step 1: 실패 테스트 추가**

`tests/unit/test_universe_filter_change_rate_source.py` 끝에 추가:
```python
import backend.services.engine.trade_tagging as tt


def test_build_selection_reason_includes_change_rate_rank():
    candidate = {"symbol": "005930", "change_rate_rank": 3, "trade_rank": 5, "volume_rank": 9999}
    sr = tt.build_selection_reason(candidate)
    assert "등락률순위#3" in sr["sources"]
    assert "거래대금순위#5" in sr["sources"]


def test_build_selection_reason_ignores_sentinel_change_rate_rank():
    candidate = {"symbol": "005930", "change_rate_rank": 9999, "volume_rank": 2}
    sr = tt.build_selection_reason(candidate)
    assert all("등락률순위" not in s for s in sr["sources"])
    assert "거래량순위#2" in sr["sources"]
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_universe_filter_change_rate_source.py -k build_selection_reason -q`
Expected: FAIL — `build_selection_reason` 에 등락률 소스 없음 → "등락률순위#3" not in sources.

- [ ] **Step 3a: `build_selection_reason` 에 등락률 소스 추가**

`backend/services/engine/trade_tagging.py` 의 `build_selection_reason` 안, `sources` 구성 블록:
```python
    sources: list[str] = []
    trade_rank = candidate.get("trade_rank")
    if isinstance(trade_rank, (int, float)) and 0 < trade_rank <= 100:
        sources.append(f"거래대금순위#{int(trade_rank)}")
    volume_rank = candidate.get("volume_rank")
    if isinstance(volume_rank, (int, float)) and 0 < volume_rank <= 100:
        sources.append(f"거래량순위#{int(volume_rank)}")
```
바로 뒤에 등락률 순위 소스를 추가(같은 들여쓰기, `scores` 구성 앞):
```python
    change_rate_rank = candidate.get("change_rate_rank")
    if isinstance(change_rate_rank, (int, float)) and 0 < change_rate_rank <= 100:
        sources.append(f"등락률순위#{int(change_rate_rank)}")
```

- [ ] **Step 3b: `run_universe_filter` 에 등락률 소스 fetch + 전달**

`backend/services/engine/universe_filter.py` 의 병렬 호출 블록:
```python
        volume_result, trade_result = await asyncio.gather(
            get_volume_rank(market_code="J", top_n=_MAX_UNIVERSE),
            get_price_rank(sort_by="trade_amount", market_code="J", top_n=_MAX_UNIVERSE),
        )
        volume_items = volume_result.get("items", [])
        trade_items = trade_result.get("items", [])
```
을 아래로 교체:
```python
        volume_result, trade_result, change_result = await asyncio.gather(
            get_volume_rank(market_code="J", top_n=_MAX_UNIVERSE),
            get_price_rank(sort_by="trade_amount", market_code="J", top_n=_MAX_UNIVERSE),
            get_price_rank(sort_by="change_rate", market_code="J", top_n=_MAX_UNIVERSE),
        )
        volume_items = volume_result.get("items", [])
        trade_items = trade_result.get("items", [])
        change_items = change_result.get("items", [])
```

같은 함수 아래쪽의 병합 호출:
```python
    raw_split_counts = {"volume": len(volume_items), "trade_amount": len(trade_items)}
    raw_count = raw_split_counts["volume"] + raw_split_counts["trade_amount"]
    merged = _merge_and_deduplicate(volume_items, trade_items)
```
을 아래로 교체:
```python
    raw_split_counts = {
        "volume": len(volume_items),
        "trade_amount": len(trade_items),
        "change_rate": len(change_items),
    }
    raw_count = raw_split_counts["volume"] + raw_split_counts["trade_amount"] + raw_split_counts["change_rate"]
    merged = _merge_and_deduplicate(volume_items, trade_items, change_items)
```

> `diagnostic_context["sample_symbols"]` 의 키들은 변경하지 않는다(기존 audit 호환). `raw_split_counts` 에 `change_rate` 키만 추가된다.

- [ ] **Step 4: 통과 + import 회귀 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_universe_filter_change_rate_source.py tests/unit/test_trade_tagging.py -q`
Expected: PASS (전부 — 기존 trade_tagging 테스트 포함 회귀 없음).

Run: `PYTHONPATH=. .venv/bin/python -c "import backend.services.engine.universe_filter as uf; print('import ok')"`
Expected: `import ok`.

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/universe_filter.py backend/services/engine/trade_tagging.py tests/unit/test_universe_filter_change_rate_source.py
git commit -m "feat: S3 등락률 순위 소스 fetch 결선 + build_selection_reason 등락률순위#N 태깅"
```

---

## Task 7: OR 결정 헬퍼 `evaluate_exploration_buy` (순수 함수)

`_on_tick` 이 호출할 순수 결정 헬퍼를 만든다. BarEngine `compute_signal_state(symbol)` → 일봉 TSI 주입 → `evaluate_groups_or(groups, conditions, state)` → `{"any", "fired", "condition_states"}` 반환. 가드(보유/중복/쿨다운)는 호출부(`_on_tick`)가 책임지고, 이 함수는 순수 평가만 한다.

**Files:**
- Create: `backend/services/engine/exploration_decision.py`
- Test: `tests/unit/test_exploration_decision.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/test_exploration_decision.py`:
```python
import backend.services.engine.exploration_decision as ed


class _FakeBarEngine:
    def __init__(self, state):
        self._state = state

    def compute_signal_state(self, symbol):
        return dict(self._state)


_STATE_FIRES = {
    "change_rate": 2.3, "체결강도": 0.62, "tick_vol_mult": 2.3, "tsi": None,
    "vwap_position": "above", "day_high_breakout": True, "pullback_rebound": False,
    "rising_bars": 3, "time_hhmm": "10:30",
}


def test_evaluate_returns_fired_groups_and_states():
    conds = {
        "c1": {"id": "c1", "ctype": "day_high_breakout", "params": {}},
        "c2": {"id": "c2", "ctype": "chegyeol_gangdo_min", "params": {"min": 0.55}},
    }
    groups = [{"id": "g1", "name": "돌파전략", "condition_ids": ["c1", "c2"]}]
    eng = _FakeBarEngine(_STATE_FIRES)
    out = ed.evaluate_exploration_buy(
        symbol="005930", bar_engine=eng, groups=groups, conditions=conds, tsi=11.0,
    )
    assert out["any"] is True
    assert out["fired"] == ["돌파전략"]
    # condition_states 는 진입 스냅샷 — 주입된 tsi 가 반영됨
    assert out["condition_states"]["tsi"] == 11.0
    assert out["condition_states"]["체결강도"] == 0.62


def test_evaluate_no_fire_returns_any_false():
    conds = {"c1": {"id": "c1", "ctype": "day_high_breakout", "params": {}}}
    groups = [{"id": "g1", "name": "돌파전략", "condition_ids": ["c1"]}]
    state = {**_STATE_FIRES, "day_high_breakout": False}
    eng = _FakeBarEngine(state)
    out = ed.evaluate_exploration_buy(
        symbol="005930", bar_engine=eng, groups=groups, conditions=conds, tsi=None,
    )
    assert out["any"] is False
    assert out["fired"] == []


def test_evaluate_injects_tsi_into_state_for_evaluation():
    # state.tsi=None 이지만 tsi=-5 주입 시 tsi_positive 그룹은 발화하지 않아야 한다
    conds = {"c1": {"id": "c1", "ctype": "tsi_positive", "params": {}}}
    groups = [{"id": "g1", "name": "추세", "condition_ids": ["c1"]}]
    eng = _FakeBarEngine(_STATE_FIRES)
    out = ed.evaluate_exploration_buy(
        symbol="005930", bar_engine=eng, groups=groups, conditions=conds, tsi=-5.0,
    )
    assert out["any"] is False
    assert out["condition_states"]["tsi"] == -5.0


def test_evaluate_keeps_tsi_none_when_not_injected():
    conds = {"c1": {"id": "c1", "ctype": "tsi_positive", "params": {}}}
    groups = [{"id": "g1", "name": "추세", "condition_ids": ["c1"]}]
    eng = _FakeBarEngine(_STATE_FIRES)
    out = ed.evaluate_exploration_buy(
        symbol="005930", bar_engine=eng, groups=groups, conditions=conds, tsi=None,
    )
    # tsi None → tsi_positive 통과(결손 차단 금지) → 발화
    assert out["any"] is True
    assert out["condition_states"]["tsi"] is None
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_exploration_decision.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.services.engine.exploration_decision'`.

- [ ] **Step 3: 구현**

`backend/services/engine/exploration_decision.py`:
```python
"""탐색모드 OR 매수 결정 헬퍼 — _on_tick 이 호출하는 순수 평가 함수.

BarEngine.compute_signal_state(symbol) 로 라이브 state 를 만들고, 일봉 TSI(외부 주입)를
state["tsi"] 에 채운 뒤 buy_condition_framework.evaluate_groups_or 로 그룹들 OR 을 평가한다.

가드(보유/중복/쿨다운)는 호출부(_on_tick) 책임 — 이 함수는 순수 평가만 한다.
"""

from __future__ import annotations

import logging
from typing import Any

from .buy_condition_framework import evaluate_groups_or

logger = logging.getLogger("ExplorationDecision")


def evaluate_exploration_buy(
    *,
    symbol: str,
    bar_engine: Any,
    groups: list[dict[str, Any]],
    conditions: dict[str, dict[str, Any]],
    tsi: float | None,
) -> dict[str, Any]:
    """탐색 OR 매수 평가 결과를 반환한다.

    Args:
        symbol: 평가 대상 종목 코드.
        bar_engine: compute_signal_state(symbol) 를 제공하는 BarEngine(또는 호환 객체).
        groups: load_groups() 결과(활성 그룹).
        conditions: load_conditions() 결과({id: condition}).
        tsi: 일봉 TSI(외부 주입). None 이면 state 의 None 유지(결손은 차단 금지).

    Returns:
        {"any": bool, "fired": [group_names], "condition_states": state_snapshot}.
    """
    state = bar_engine.compute_signal_state(symbol)
    if tsi is not None:
        state["tsi"] = tsi
    result = evaluate_groups_or(groups, conditions, state)
    return {
        "any": bool(result.get("any")),
        "fired": list(result.get("fired") or []),
        "condition_states": state,
    }
```

- [ ] **Step 4: 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_exploration_decision.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/exploration_decision.py tests/unit/test_exploration_decision.py
git commit -m "feat: exploration_decision.evaluate_exploration_buy — compute_signal_state→TSI주입→OR 평가(순수)"
```

---

## Task 8: `_on_tick` 결선 — 탐색 OR 분기 + 매수·태깅 (가드 유지)

`decision_engine.DecisionEngine` 에 BarEngine 인스턴스를 보유하고, `activate` 에서 WS 틱 콜백으로 `bar_engine.ingest_tick` 을 등록(state 누적)한다. `_on_tick` 에서 기존 게이트 통과 분기는 그대로 두고, **탐색 허용 시** OR 발화를 추가 매수 트리거로 얹는다. 모든 기존 가드(보유/`_signal_sent`/쿨다운/price>0)는 분기 진입 전에 그대로 적용된다. OR 발화 시 `_emit_signal` 로 매수하고, 발화그룹·조건상태·선정사유·시장맥락을 `record_entry_tag` 로 태깅한다.

**Files:**
- Modify: `backend/services/engine/decision_engine.py` (`__init__`, `activate`, `deactivate`, `_on_tick`)
- Test: `tests/unit/test_exploration_decision.py` (`_emit_and_tag_exploration` 헬퍼 단위테스트)

- [ ] **Step 1: 실패 테스트 추가 (태깅 호출 헬퍼)**

`_on_tick` 의 async/WS 결선은 통합 영역이라 단위테스트가 무겁다. 대신 매수 확정 후 "태깅 페이로드 조립"을 별도 동기 헬퍼 `build_exploration_tag_payload` 로 분리해 단위테스트한다.

`tests/unit/test_exploration_decision.py` 끝에 추가:
```python
def test_build_exploration_tag_payload_shapes_record_entry_tag_kwargs():
    candidate = {"symbol": "005930", "name": "삼성전자", "score": 0.36,
                 "suitability_score": 0.72, "change_rate_rank": 3, "trade_rank": 5,
                 "tsi": 42.0, "llm_note": "반도체 강세"}
    decision = {"any": True, "fired": ["돌파전략"],
                "condition_states": {"체결강도": 0.62, "tsi": 11.0}}
    market_context = {"regime": "neutral", "market_tone": "negative",
                      "time_bucket": "10:30", "vix": 18.2}
    payload = ed.build_exploration_tag_payload(
        order_id="ord-1", symbol="005930", trade_date="2099-03-01",
        candidate=candidate, decision=decision, market_context=market_context,
    )
    # record_entry_tag 키워드 시그니처와 1:1 매칭
    assert payload["order_id"] == "ord-1"
    assert payload["symbol"] == "005930"
    assert payload["trade_date"] == "2099-03-01"
    assert payload["fired_groups"] == ["돌파전략"]
    assert payload["condition_states"]["체결강도"] == 0.62
    assert payload["market_context"]["regime"] == "neutral"
    # selection_reason 은 build_selection_reason 산출 — 등락률순위 포함
    assert "등락률순위#3" in payload["selection_reason"]["sources"]
    assert payload["selection_reason"]["scores"]["llm_suitability"] == 0.72
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_exploration_decision.py -k build_exploration_tag_payload -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'build_exploration_tag_payload'`.

- [ ] **Step 3a: `build_exploration_tag_payload` 추가**

`backend/services/engine/exploration_decision.py` 끝에 추가:
```python
def build_exploration_tag_payload(
    *,
    order_id: str,
    symbol: str,
    trade_date: str,
    candidate: dict[str, Any],
    decision: dict[str, Any],
    market_context: dict[str, Any],
) -> dict[str, Any]:
    """record_entry_tag 키워드 인자 dict 를 조립한다(태깅 페이로드).

    Args:
        order_id: 매수 주문 로컬 id(없으면 빈 문자열).
        symbol: 종목 코드.
        trade_date: YYYY-MM-DD 거래일.
        candidate: S4 후보 dict(선정사유 추출 원천).
        decision: evaluate_exploration_buy 결과({any, fired, condition_states}).
        market_context: {"regime","market_tone","time_bucket","vix"} dict.
    """
    from .trade_tagging import build_selection_reason

    return {
        "order_id": str(order_id or ""),
        "symbol": str(symbol or ""),
        "trade_date": str(trade_date or ""),
        "selection_reason": build_selection_reason(candidate or {}),
        "fired_groups": list(decision.get("fired") or []),
        "condition_states": dict(decision.get("condition_states") or {}),
        "market_context": dict(market_context or {}),
    }
```

- [ ] **Step 3b: 통과 확인 (헬퍼)**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_exploration_decision.py -q`
Expected: PASS (5 tests).

- [ ] **Step 3c: `DecisionEngine.__init__` 에 BarEngine 보유**

`backend/services/engine/decision_engine.py` 의 `DecisionEngine.__init__` 끝(`self._account_sync_rate_limit_hits = deque()` 뒤)에 추가:
```python
        from .intraday_bar_engine import BarEngine

        self._bar_engine = BarEngine()
```

- [ ] **Step 3d: `activate` 에서 BarEngine ingest 콜백 등록**

`activate` 안, 기존 `realtime_ws_manager.register_tick_callback(self._on_tick)` 바로 뒤에 추가:
```python
        realtime_ws_manager.register_tick_callback(self._bar_engine.ingest_tick)
```

`deactivate` 안, 기존 `realtime_ws_manager.unregister_tick_callback(self._on_tick)` 바로 뒤에 추가:
```python
        realtime_ws_manager.unregister_tick_callback(self._bar_engine.ingest_tick)
```

- [ ] **Step 3e: `_on_tick` 탐색 분기 결선**

`_on_tick` 의 기존 게이트 분기:
```python
        candidate = self._candidates[symbol]
        final_rule = get_rule(symbol) or {}
        matched = self._evaluate_rules(candidate=candidate, final_rule=final_rule, tick=tick)

        if _rules_allow_signal(matched):
            await self._emit_signal(symbol, candidate, price, matched)
```
을 아래로 교체:
```python
        candidate = self._candidates[symbol]
        final_rule = get_rule(symbol) or {}
        matched = self._evaluate_rules(candidate=candidate, final_rule=final_rule, tick=tick)

        if _rules_allow_signal(matched):
            await self._emit_signal(symbol, candidate, price, matched)
            return

        # 탐색모드: 기존 게이트 미통과여도 OR 그룹이 발화하면 추가 매수 트리거(모의 전용)
        await self._maybe_exploration_buy(symbol, candidate, price)

    async def _maybe_exploration_buy(
        self, symbol: str, candidate: dict[str, Any], price: float
    ) -> None:
        """탐색 허용 시 OR 그룹 발화를 평가해 매수 신호를 추가 발행한다.

        가드(보유/중복/쿨다운/price>0)는 호출부 _on_tick 에서 이미 통과한 상태다.
        실계좌·탐색 OFF면 즉시 반환(하드 차단).

        Args:
            symbol: 평가 대상 종목.
            candidate: S4 후보 dict.
            price: 트리거 가격.
        """
        from .exploration_gate import is_exploration_allowed

        if not is_exploration_allowed():
            return
        try:
            from .buy_condition_framework import load_conditions, load_groups
            from .exploration_decision import evaluate_exploration_buy

            groups = load_groups()
            conditions = load_conditions()
            if not groups or not conditions:
                return
            tsi = _first_float(candidate.get("tsi"), candidate.get("tsi_value"))
            decision = evaluate_exploration_buy(
                symbol=symbol,
                bar_engine=self._bar_engine,
                groups=groups,
                conditions=conditions,
                tsi=tsi,
            )
        except Exception as exc:
            logger.warning("WARN: [S6/탐색] OR 평가 실패 symbol=%s reason=%s", symbol, exc)
            return

        if not decision.get("any"):
            return

        logger.info(
            "SIGNAL: [S6/탐색] OR 발화 symbol=%s fired=%s", symbol, decision.get("fired")
        )
        await self._emit_signal(symbol, candidate, price, {"exploration": True, "fired_groups": decision["fired"]})
        self._record_exploration_tag(symbol, candidate, decision)

    def _record_exploration_tag(
        self, symbol: str, candidate: dict[str, Any], decision: dict[str, Any]
    ) -> None:
        """OR 발화 매수의 선정사유·발화그룹·조건상태·시장맥락을 태깅한다.

        order_id 는 비동기 주문 제출 전이라 알 수 없으므로 빈 문자열로 기록하고,
        Phase 1c set_outcome(order_id)는 별도 결선(범위 밖)에서 채운다.

        Args:
            symbol: 매수 종목.
            candidate: S4 후보 dict.
            decision: evaluate_exploration_buy 결과.
        """
        try:
            from .exploration_decision import build_exploration_tag_payload
            from .trade_tagging import record_entry_tag

            today = _today_kst()
            market_context = self._build_market_context(today)
            payload = build_exploration_tag_payload(
                order_id="",
                symbol=symbol,
                trade_date=today,
                candidate=candidate,
                decision=decision,
                market_context=market_context,
            )
            record_entry_tag(**payload)
        except Exception as exc:
            logger.warning("WARN: [S6/탐색] 태깅 실패 symbol=%s reason=%s", symbol, exc)

    def _build_market_context(self, today: str) -> dict[str, Any]:
        """태깅용 시장맥락 dict 를 daily_context_snapshot / market_tone_results 에서 조립한다.

        Args:
            today: YYYY-MM-DD 거래일.
        """
        regime = "neutral"
        market_tone = "neutral"
        vix: float | None = None
        try:
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT regime FROM daily_context_snapshot WHERE trade_date = ? "
                    "ORDER BY created_at DESC LIMIT 1",
                    (today,),
                ).fetchone()
                if row and row["regime"]:
                    regime = str(row["regime"])
                tone_row = conn.execute(
                    "SELECT tone FROM market_tone_results WHERE trade_date = ? "
                    "ORDER BY created_at DESC LIMIT 1",
                    (today,),
                ).fetchone()
                if tone_row and tone_row["tone"]:
                    market_tone = str(tone_row["tone"])
        except Exception as exc:
            logger.warning("WARN: [S6/탐색] market_context 조회 실패 reason=%s", exc)
        return {
            "regime": regime,
            "market_tone": market_tone,
            "time_bucket": _now_kst().strftime("%H:%M"),
            "vix": vix,
        }
```

> `_emit_signal` 의 `matched` 인자는 JSON 직렬화돼 `trading_signals.rule_matched` 에 저장된다(기존 동작). 탐색 매수는 `{"exploration": True, "fired_groups": [...]}` 를 전달해 신호 출처를 구분한다.

- [ ] **Step 4: import + 회귀 확인**

Run: `PYTHONPATH=. .venv/bin/python -c "import backend.services.engine.decision_engine as de; de.DecisionEngine(); print('init ok')"`
Expected: `init ok` (BarEngine 보유 import 정상).

기존 S6 게이트 테스트 회귀 없음:
Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_decision_engine_tsi.py tests/unit/test_decision_engine_watchdog.py -q`
Expected: PASS (전부 — `_rules_allow_signal` 게이트 불변, 탐색 분기는 게이트 통과 시 `return` 으로 진입 안 함).

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/decision_engine.py backend/services/engine/exploration_decision.py tests/unit/test_exploration_decision.py
git commit -m "feat: S6 _on_tick 탐색 OR 분기 결선 — BarEngine ingest + OR 매수 + 통짜 태깅(가드/게이트 유지)"
```

---

## Task 9: 전체 회귀 + import 스모크

**Files:** (없음 — 검증 전용)

- [ ] **Step 1: 신규 단위테스트 전체**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_exploration_gate.py tests/unit/test_exploration_decision.py tests/unit/test_universe_filter_change_rate_source.py -q`
Expected: PASS (전부).

- [ ] **Step 2: 관련 기존 테스트 회귀**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_budget_sizing.py tests/unit/test_daily_capital.py tests/unit/test_decision_engine_tsi.py tests/unit/test_decision_engine_watchdog.py tests/unit/test_trade_tagging.py -q`
Expected: PASS (전부 — 사이징/태깅/게이트 불변).

- [ ] **Step 3: backend import 스모크**

Run: `PYTHONPATH=. .venv/bin/python -c "import backend.main; print('import ok')"`
Expected: `import ok`.

- [ ] **Step 4: 커밋 (회귀 통과 기록, 변경 없으면 생략)**

회귀에서 코드 수정이 발생했을 때만:
```bash
git add -A
git commit -m "fix: 탐색엔진 Phase 1d 회귀 수정"
```

---

## 완료 기준 (Phase 1d)

- [ ] `is_exploration_allowed()` — 설정 ON **AND** KIS 모의(openapivts)일 때만 True, 실계좌 하드 차단 (5 테스트 PASS).
- [ ] `select_sizing_params` — 탐색 ON 시 풀예수금(`exploration.budget_rate`/`exploration.max_positions`), OFF 시 기존 (3 테스트 PASS).
- [ ] order_executor `_execute_signal_inner` 사이징이 셀렉터 결선 — 탐색 OFF 시 동작 불변(`test_budget_sizing` 회귀 PASS).
- [ ] S3 `_merge_and_deduplicate` 등락률 순위 합류 + `change_rate_rank` (4 테스트) + `_score_and_rank` 순위 점수 (2 테스트) + `run_universe_filter` 3소스 fetch.
- [ ] `build_selection_reason` 등락률순위#N 소스 (2 테스트, 기존 trade_tagging 회귀 없음).
- [ ] `evaluate_exploration_buy` (compute_signal_state→TSI 주입→OR) + `build_exploration_tag_payload` (5 테스트 PASS).
- [ ] `_on_tick` 탐색 OR 분기 — 기존 게이트 통과 시 `return`(중복 진입 없음), 미통과 시 탐색 평가, 모든 가드 유지, OR 발화 시 `_emit_signal` + `record_entry_tag`.
- [ ] `import backend.main` 정상, 관련 기존 단위테스트 전체 회귀 PASS.

## 신규 설정 키 (운영 반영 필요)

| 키 | 타입 | 기본값 | 의미 |
|---|---|---|---|
| `engine.exploration_mode` | bool | `False` | 탐색모드 마스터 스위치 (모의계좌에서만 효력) |
| `exploration.max_positions` | int | `40` | 탐색 사이징 슬롯 수(풀예수금 다종목) |
| `exploration.budget_rate` | float | `0.95` | 탐색 사이징 예산률(풀예수금) |

## 후속 (이 계획 범위 밖)

- **Phase 2:** Trade History/Monitoring 선정·매수·손절 사유 UI 표기, Settings 조건·그룹·할당 편집.
- **Phase 3:** 그룹/조건/맥락별 EV 집계·가지치기·자동 weight.
- **태깅 order_id 결선:** 비동기 주문 제출 후 실제 `order_id` 를 태그에 채우는 결선(현재는 빈 문자열 기록 + Phase 1c `set_outcome` 청산 결선)은 Phase 2 통합 영역.

---

## Self-Review

**1. Spec coverage (의뢰서 SCOPE 4항목 + 설계서):**
- ① `is_exploration_allowed()` 모의전용 게이트 → Task 1 (`openapivts` 확인된 체크, 실계좌 하드차단). ✓ (설계서 "안전장치 모의 전용 게이트")
- ② 사이징 셀렉터(탐색 시 max_positions=40·budget_rate=0.95) → Task 2 + order_executor 결선 Task 3. ✓ (설계서 "자본·포지션 풀예수금")
- ③ 등락률 소스 S3 3번째 + selection_reason "등락률순위#N" → Task 4(병합)/5(점수)/6(fetch+태깅). ✓ (설계서 "net-new: 등락률 순위 API S3 추가")
- ④ `_on_tick` OR 결선(compute_signal_state→evaluate_groups_or→매수+record_entry_tag, 가드 유지) → Task 7(순수 평가)/8(결선). ✓ (설계서 "전체 매수 판정 OR")
- 고정 인터페이스 verbatim 사용: `evaluate_groups_or(groups, conditions_by_id, state)` (Task 7), `load_conditions()`/`load_groups()` (Task 8), `compute_signal_state(symbol)` (Task 7), `record_entry_tag(*, ...)` 키워드 (Task 8), `build_selection_reason(candidate)` (Task 6/8). ✓

**2. Placeholder scan:** TBD/TODO/"적절히 처리"/"위와 유사" 없음. 모든 코드 스텝에 완전한 실제 코드 포함. "handle edge cases" 류 없음. ✓

**3. Type consistency:**
- `select_sizing_params` 반환 `(float|None, int)` — Task 1 정의, Task 2 테스트(`budget_rate is None`/값), Task 3 결선(`if explore_budget_rate is not None`) 모두 일치. ✓
- `_merge_and_deduplicate(volume, trade, change=None)` — Task 4 정의, Task 6 호출(3-인자) 일치. `change_rate_rank` 키 Task 4 생성 → Task 5 점수 사용 → Task 6 `build_selection_reason` 소비, 동일 키. ✓
- `evaluate_exploration_buy(*, symbol, bar_engine, groups, conditions, tsi)` 반환 `{any, fired, condition_states}` — Task 7 정의/테스트, Task 8 `_maybe_exploration_buy` 호출(키워드) 일치. ✓
- `build_exploration_tag_payload(*, order_id, symbol, trade_date, candidate, decision, market_context)` 반환 키 = `record_entry_tag` 키워드 시그니처(order_id/symbol/trade_date/selection_reason/fired_groups/condition_states/market_context)와 1:1 — Task 8 `record_entry_tag(**payload)` 직접 언팩 호환. ✓
- `_is_virtual`/`get_setting` 은 Task 1에서 모듈 전역으로 import/정의 → 테스트가 `patch.object(eg, ...)` 로 패치(이름 일치). ✓
- decision_engine 신규 메서드(`_maybe_exploration_buy`/`_record_exploration_tag`/`_build_market_context`)는 모두 `DecisionEngine` 인스턴스 메서드로 정의·호출 일치, `self._bar_engine` Task 3c 보유 후 Task 3e 사용. ✓

수정 사항 없음 — 계획 일관성 확인됨.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-06-exploration-engine-phase1d-integration-source-gate-sizing.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — 태스크마다 새 subagent 디스패치, 태스크 간 리뷰, 빠른 반복.

**2. Inline Execution** — 이 세션에서 executing-plans 로 체크포인트 단위 일괄 실행.

**Which approach?**
