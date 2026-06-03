# 매수 적극성 향상 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 매수 후보를 WS 한도(고정 40)까지 채우고, 등락률 하한을 1.5%로 낮추되, 일봉 TSI(25/13)>0 추세 필터를 게이트·랭킹에 추가해 "넓게 보고·일찍·추세종목만·과열회피" 매수를 구현한다.

**Architecture:** 순수 TSI 계산(`tsi.py`) → technical_indicators가 종목별 TSI 산출 → hybrid_screening이 유니버스 후보에 TSI 부착 + 블렌드 점수로 40까지 top-up → decision_engine 게이트에 `tsi_positive`(없으면 통과) 추가 → realtime_ws가 41 하드 가드. 설정 1.5% + 화면 TSI 행.

**Tech Stack:** Python 3 / FastAPI / SQLite / pykrx / pytest / Vanilla JS

**Scope (v1):** 일봉 TSI(장전 계산). 실시간 분봉 TSI는 v2(범위 외).

---

## File Structure

- **Create** `backend/services/engine/tsi.py` — 순수 TSI 계산. 단일 책임.
- **Create** `tests/unit/test_tsi.py`.
- **Modify** `backend/services/engine/technical_indicators.py` — TSI 산출 추가(closes 재사용).
- **Modify** `backend/services/engine/hybrid_screening.py` — `[:30]` 캡 확대 + TSI 부착 + 블렌드 top-up 40.
- **Modify** `backend/services/engine/decision_engine.py` — 게이트에 `tsi_positive` 조건.
- **Modify** `backend/services/kis/realtime_ws.py` — 구독 41 하드 가드.
- **Modify** `backend/static/js/screens/console-trading-monitor.js` — 준비도 조건표 TSI 행.
- **설정(DB)** `engine.min_price_change_pct` 3.0→1.5, 신규 `screening.candidate_max`=40, `realtime.ws_max`=41.

---

## Task 1: TSI 순수 계산 (tsi.py)

**Files:**
- Create: `backend/services/engine/tsi.py`
- Test: `tests/unit/test_tsi.py`

- [ ] **Step 1: 실패 테스트**

```python
# tests/unit/test_tsi.py
import unittest
from backend.services.engine import tsi


class TsiTest(unittest.TestCase):
    def test_uptrend_positive(self):
        closes = [100 + i for i in range(40)]  # 꾸준한 상승
        v = tsi.compute_tsi(closes)
        self.assertIsNotNone(v)
        self.assertGreater(v, 0)

    def test_downtrend_negative(self):
        closes = [100 - i for i in range(40)]  # 꾸준한 하락
        v = tsi.compute_tsi(closes)
        self.assertLess(v, 0)

    def test_insufficient_data_returns_none(self):
        self.assertIsNone(tsi.compute_tsi([100, 101, 102]))

    def test_bounded_range(self):
        closes = [100 + (i % 3) for i in range(50)]
        v = tsi.compute_tsi(closes)
        self.assertGreaterEqual(v, -100.0)
        self.assertLessEqual(v, 100.0)
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_tsi.py -q`
Expected: FAIL (module 없음)

- [ ] **Step 3: 구현**

```python
# backend/services/engine/tsi.py
"""True Strength Index (TSI) 계산 — 이중 평활 모멘텀 추세 지표.

TSI = 100 * EMA(EMA(Δclose, r), s) / EMA(EMA(|Δclose|, r), s)
v1: 일봉 종가, 표준 r=25, s=13. 상승추세>0 / 하락추세<0.
"""
from __future__ import annotations


def _ema(values: list[float], period: int) -> list[float]:
    """단순 EMA 시계열. 첫 값은 시드(첫 원소)로 시작."""
    if not values:
        return []
    k = 2.0 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(out[-1] + k * (v - out[-1]))
    return out


def compute_tsi(closes: list[float], r: int = 25, s: int = 13) -> float | None:
    """종가 리스트(오래된→최신)로 최신 TSI 값을 반환. 데이터 부족 시 None."""
    if not closes or len(closes) < r + s + 1:
        return None
    mtm = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    abs_mtm = [abs(x) for x in mtm]
    double_mtm = _ema(_ema(mtm, r), s)
    double_abs = _ema(_ema(abs_mtm, r), s)
    denom = double_abs[-1]
    if denom == 0:
        return 0.0
    return max(-100.0, min(100.0, 100.0 * double_mtm[-1] / denom))
```

- [ ] **Step 4: 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_tsi.py -q`
Expected: 4 passed

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/tsi.py tests/unit/test_tsi.py
git commit -m "feat: TSI(True Strength Index) 순수 계산 함수"
```

---

## Task 2: 종목별 TSI 산출 헬퍼 (technical_indicators.py)

`calculate_indicators`가 이미 pykrx로 `closes`를 만든다. 같은 closes로 TSI를 산출하는 공개 헬퍼를 추가한다.

**Files:**
- Modify: `backend/services/engine/technical_indicators.py`
- Test: `tests/unit/test_tsi.py` (append)

- [ ] **Step 1: 실패 테스트 추가**

```python
class SymbolTsiTest(unittest.TestCase):
    def test_tsi_from_closes_helper(self):
        from backend.services.engine import tsi as tsi_mod
        # tsi_for_closes는 compute_tsi 래퍼 — None 안전
        self.assertIsNone(tsi_mod.tsi_for_closes([]))
        self.assertIsNotNone(tsi_mod.tsi_for_closes([100 + i for i in range(45)]))
```

- [ ] **Step 2: 실패 확인 → Step 3: 구현 (tsi.py에 추가)**

```python
def tsi_for_closes(closes: list[float]) -> float | None:
    """closes 시계열로 TSI 계산(round 2). 예외/부족 시 None."""
    try:
        v = compute_tsi([float(c) for c in closes if c is not None])
        return round(v, 2) if v is not None else None
    except Exception:
        return None
```

그리고 `technical_indicators.calculate_indicators` 내 closes 계산 직후(`closes = _safe_float_series(...)` 아래)에 추가:

```python
            from .tsi import tsi_for_closes
            result["tsi"] = tsi_for_closes(closes)
```
저장 스키마(`CREATE TABLE ... technical_indicators`)와 INSERT에 `tsi REAL` 컬럼을 추가한다(기존 `momentum5d_pct` 패턴 동일). 컬럼 추가 시 `_ensure_*`/ALTER 패턴이 있으면 따른다.

- [ ] **Step 4: 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_tsi.py -q` → 5 passed
Run: `PYTHONPATH=. .venv/bin/python -m py_compile backend/services/engine/technical_indicators.py` → OK

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/tsi.py backend/services/engine/technical_indicators.py tests/unit/test_tsi.py
git commit -m "feat: technical_indicators에 TSI 산출 추가"
```

---

## Task 3: 등락률 하한 1.5% + 신규 설정 (DB)

**Files:** 없음(설정 변경만). 별도 검증 스크립트.

- [ ] **Step 1: 설정 적용**

```bash
PYTHONPATH=. .venv/bin/python - <<'PY'
from backend.services.settings_store import upsert_setting, get_setting
upsert_setting("engine.min_price_change_pct", 1.5, "number", "초기 모멘텀 진입(매수 적극성, TSI로 품질보전)", actor="PM")
upsert_setting("screening.candidate_max", 40, "integer", "WS 모니터링 후보 고정 상한", actor="PM")
upsert_setting("realtime.ws_max", 41, "integer", "KIS WS 1세션 등록 한도", actor="PM")
print("min_price_change_pct:", get_setting("engine.min_price_change_pct", None))
print("candidate_max:", get_setting("screening.candidate_max", None))
print("ws_max:", get_setting("realtime.ws_max", None))
PY
```
Expected: `1.5 / 40 / 41`

- [ ] **Step 2: 커밋** (코드 변경 없음 — 다음 태스크와 함께 커밋)

---

## Task 4: 게이트에 tsi_positive 조건 (decision_engine.py)

`_evaluate_rules`의 rsi_range 패턴을 미러링. **TSI 데이터 없으면 통과(차단 금지).** core_keys에 추가해 필수화.

**Files:**
- Modify: `backend/services/engine/decision_engine.py` (rsi_range 블록 뒤 + core_keys)
- Test: `tests/unit/test_decision_engine_tsi.py`

- [ ] **Step 1: 실패 테스트**

```python
# tests/unit/test_decision_engine_tsi.py
import unittest
from backend.services.engine import decision_engine as de


class TsiGateTest(unittest.TestCase):
    def test_rules_allow_blocks_when_tsi_negative(self):
        matched = {"volume_ratio": True, "price_change": True, "time_window": True, "tsi_positive": False}
        self.assertFalse(de._rules_allow_signal(matched))

    def test_rules_allow_passes_when_tsi_positive(self):
        matched = {"volume_ratio": True, "price_change": True, "time_window": True, "tsi_positive": True}
        self.assertTrue(de._rules_allow_signal(matched))

    def test_rules_allow_passes_when_tsi_missing_treated_true(self):
        # tsi 데이터 없으면 _evaluate_rules가 tsi_positive=True로 채워 통과시킨다
        matched = {"volume_ratio": True, "price_change": True, "time_window": True, "tsi_positive": True}
        self.assertTrue(de._rules_allow_signal(matched))
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_decision_engine_tsi.py -q`
Expected: FAIL (tsi_positive가 core_keys에 없어 무시됨 → 첫 테스트 실패)

- [ ] **Step 3: 구현**

(a) `_rules_allow_signal`의 `core_keys`에 `"tsi_positive"` 추가:
```python
    core_keys = ["volume_ratio", "price_change", "time_window", "tsi_positive"]
```

(b) `_evaluate_rules`의 `matched` 딕셔너리 구성부(volume_ratio/price_change/time_window 세팅하는 곳)에 추가:
```python
        # TSI 추세 필터: 상승추세(tsi>0)만 매수. 데이터 없으면 통과(차단 금지).
        tsi_val = _first_float(
            tick.get("tsi"), candidate.get("tsi"), candidate.get("tsi_value"),
        )
        matched["tsi_positive"] = True if tsi_val is None else (tsi_val > 0)
        observed_values["tsi"] = tsi_val
```
(`_first_float`는 이미 존재. 없으면 candidate.get만 사용.)

- [ ] **Step 4: 통과 확인**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_decision_engine_tsi.py -q` → 3 passed
Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_decision_engine_watchdog.py -q` (회귀) → pass

- [ ] **Step 5: 커밋**

```bash
git add backend/services/engine/decision_engine.py tests/unit/test_decision_engine_tsi.py
git commit -m "feat: 매수 게이트에 TSI>0 추세 필터(데이터 없으면 통과)"
```

---

## Task 5: 후보를 40까지 채우기 + TSI 부착 (hybrid_screening.py)

**Files:**
- Modify: `backend/services/engine/hybrid_screening.py`

- [ ] **Step 1: `[:30]` 캡 확대**

`items = universe["items"][:30]` 을 설정 기반으로:
```python
    from ..settings_store import get_setting
    _llm_input_cap = int(get_setting("screening.llm_input_cap", 60) or 60)
    items = universe["items"][:_llm_input_cap]
```

- [ ] **Step 2: 최종 후보에 TSI 부착 + 블렌드 top-up**

LLM 후보 확정 후(비용 필터 통과한 `candidates` 리스트가 만들어진 직후), 다음을 추가한다:

```python
    # --- TSI 부착 + WS 한도까지 블렌드 top-up ---
    from ..settings_store import get_setting
    from .tsi import tsi_for_closes
    from .technical_indicators import _pykrx_ohlcv  # closes 소스 재사용
    from datetime import datetime, timedelta

    def _symbol_tsi(sym: str) -> float | None:
        try:
            end = datetime.now().strftime("%Y%m%d")
            start = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")
            df = _pykrx_ohlcv(sym, start, end)
            if df is None or "종가" not in df:
                return None
            return tsi_for_closes([float(x) for x in df["종가"].tolist()])
        except Exception:
            return None

    candidate_max = int(get_setting("screening.candidate_max", 40) or 40)
    ws_max = int(get_setting("realtime.ws_max", 41) or 41)
    # 보유 포지션 수만큼 WS 슬롯 예약
    try:
        from .position_manager import position_manager
        held = len(position_manager.get_positions())
    except Exception:
        held = 0
    target = max(0, min(candidate_max, ws_max - held))

    chosen = {str(c.get("symbol") or c.get("ticker")): c for c in candidates if (c.get("symbol") or c.get("ticker"))}
    # LLM 후보에 TSI 부착
    for sym, c in chosen.items():
        c["tsi"] = _symbol_tsi(sym)
    # 부족분: 유니버스 점수 상위 중 TSI>0 종목으로 블렌드 top-up
    if len(chosen) < target:
        for it in sorted(items, key=lambda x: x.get("score", 0.0), reverse=True):
            sym = str(it.get("symbol") or "")
            if not sym or sym in chosen:
                continue
            t = _symbol_tsi(sym)
            if t is None or t <= 0:   # 추세 안 살아있으면 자리 채우려 넣지 않음
                continue
            chosen[sym] = {**it, "tsi": t, "suitability_score": it.get("suitability_score", 0.0)}
            if len(chosen) >= target:
                break
    candidates = list(chosen.values())
    logger.info("INFO: HybridScreening 후보 확장 target=%d held=%d final=%d", target, held, len(candidates))
```

- [ ] **Step 3: 검증(수동)**

서버 재기동 후 다음 거래일 S4 로그에서 `후보 확장 ... final=` 가 LLM 단독보다 커지는지 확인. (장전 실행이라 즉시 검증은 로그 기준)
Run: `PYTHONPATH=. .venv/bin/python -m py_compile backend/services/engine/hybrid_screening.py` → OK

- [ ] **Step 4: 커밋**

```bash
git add backend/services/engine/hybrid_screening.py
git commit -m "feat: S4 후보를 WS 한도(40)까지 TSI>0 블렌드 top-up 확장"
```

---

## Task 6: WS 구독 41 하드 가드 (realtime_ws.py)

**Files:**
- Modify: `backend/services/kis/realtime_ws.py` (`start` 메서드)

- [ ] **Step 1: 구독 상한 가드 추가**

`async def start(self, symbols)` 의 `unique_symbols = list(dict.fromkeys(safe_symbols))` 직후:
```python
        from ..settings_store import get_setting
        ws_max = int(get_setting("realtime.ws_max", 41) or 41)
        if len(unique_symbols) > ws_max:
            logger.warning("WARN: WS 구독 %d개 > 한도 %d — 상위 %d개만 구독", len(unique_symbols), ws_max, ws_max)
            unique_symbols = unique_symbols[:ws_max]
```
(import 경로는 파일 기준 상대경로로 맞춘다. settings_store는 `backend.services.settings_store`.)

- [ ] **Step 2: 검증**

Run: `PYTHONPATH=. .venv/bin/python -m py_compile backend/services/kis/realtime_ws.py` → OK
Run: `PYTHONPATH=. .venv/bin/python -c "import backend.main; print('import ok')"` → import ok

- [ ] **Step 3: 커밋**

```bash
git add backend/services/kis/realtime_ws.py
git commit -m "feat: WS 구독 종목 수 41 하드 가드"
```

---

## Task 7: 매수 준비도 조건표에 TSI 행 (프런트)

**Files:**
- Modify: `backend/api/routes/trading_monitor.py` (`_compute_buy_readiness`)
- Modify: `backend/static/js/screens/console-trading-monitor.js` (제네릭 렌더라 백엔드만으로 표시됨)

- [ ] **Step 1: 준비도 조건에 TSI 추가**

`_compute_buy_readiness`의 conditions 빌드부(거래량/등락률 append 사이)에 추가:
```python
    tsi_val = candidate.get("tsi")
    if tsi_val is not None:
        conditions.append({
            "name": "tsi",
            "label": "TSI 추세",
            "current_value": round(float(tsi_val), 1),
            "threshold_label": "> 0 (상승추세)",
            "score_pct": 100.0 if float(tsi_val) > 0 else 0.0,
            "met": float(tsi_val) > 0,
        })
```
(프런트 조건표는 conditions 배열을 제네릭 렌더하므로 추가 JS 불필요.)

- [ ] **Step 2: 검증**

Run: `PYTHONPATH=. .venv/bin/python -m py_compile backend/api/routes/trading_monitor.py` → OK

- [ ] **Step 3: 커밋**

```bash
git add backend/api/routes/trading_monitor.py
git commit -m "feat: 매수 준비도 조건표에 TSI 추세 행 추가"
```

---

## Self-Review

- **Spec coverage:** ① 후보 40 채우기(T5)+WS가드(T6) · ② 등락률 1.5%(T3) · ③ TSI 계산(T1,T2)+게이트(T4)+랭킹 블렌드(T5)+화면(T7). 모두 태스크 존재. ✓
- **Placeholder scan:** 모든 코드 스텝에 실제 코드. 통합부(T5)는 정확한 함수·필드(`_pykrx_ohlcv`/`score`/`suitability_score`/`position_manager.get_positions`) 명시. ✓
- **Type consistency:** `compute_tsi`/`tsi_for_closes` 시그니처, candidate `tsi` 필드, matched `tsi_positive` 키가 T1·T2·T4·T5·T7 일관. ✓
- **주의:** T2의 technical_indicators 컬럼 추가는 실제 테이블 스키마(`_ensure_*` 패턴)를 보고 ALTER/CREATE에 맞춰 적용할 것. T5의 pykrx 호출은 장전(08:xx)이라 지연 허용.
