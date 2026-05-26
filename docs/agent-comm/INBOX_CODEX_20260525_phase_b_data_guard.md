# Phase B — 데이터 결손 가드 강화

**발신: Sisyphus | 수신: Codex (Backend Executor)**
**날짜: 2026-05-25**
**우선순위: P0 — 즉시 착수**

---

## 배경

4영역 점검 결과 P1 위험으로 분류된 항목들을 즉시 수정한다.
데이터 결손이 발생해도 매수 주문이 통과되는 false-pass 경로가 존재하며,
KIS 웹소켓 단절 시 자동 감지 없이 조용히 실패한다.

---

## 구현 범위

### B1 — decision_engine None-pass 차단

**파일:** `backend/services/engine/decision_engine.py`

**문제:**
- line ~908: `price_ok = ... if change_rate is not None else price_min_pct <= 0`
  → change_rate가 None이면 `price_min_pct <= 0` 조건으로 통과 (디폴트값 0 이하이므로 항상 True)
- line ~944: `volume_ok = volume_ratio >= volume_ratio_min if volume_ratio is not None else volume_ratio_min <= 1.0`
  → volume_ratio가 None이면 `volume_ratio_min <= 1.0` 조건으로 통과 (디폴트 1.0이라 항상 True)

**수정:**
```python
# 변경 전 (line ~908)
price_ok = (
    price_min_pct <= change_rate <= price_max_pct
    if change_rate is not None
    else price_min_pct <= 0
)

# 변경 후
price_ok = (
    price_min_pct <= change_rate <= price_max_pct
    if change_rate is not None
    else False  # 데이터 결손 시 진입 차단
)
```

```python
# 변경 전 (line ~944)
volume_ok = volume_ratio >= volume_ratio_min if volume_ratio is not None else volume_ratio_min <= 1.0

# 변경 후
volume_ok = volume_ratio >= volume_ratio_min if volume_ratio is not None else False  # 데이터 결손 시 진입 차단
```

**주의:** `unavailable_conditions` 딕셔너리 기록 로직(`if change_rate is None and price_min_pct > 0:` 등)은 그대로 유지한다. 이미 결손 기록은 하고 있으므로 차단만 추가.

---

### B2 — data_quality_guard 발행처 통합 확인 및 보완

**파일:** `backend/services/engine/data_quality_guard.py`

현재 `publish_event()` 함수가 존재하고 일부 컴포넌트에서 호출 중.
아래 사항을 확인하고 누락된 발행처가 있으면 추가:

1. `publish_event()` 함수 시그니처와 severity 레벨 확인
   - 허용 레벨: `INFO`, `WARNING`, `DEGRADED`, `BLOCK_NEW_ENTRY`, `EMERGENCY`
2. B3, B4, B5에서 추가될 발행 호출이 동일 `publish_event()` 함수를 통하도록 보장
3. `get_current_status()` 함수가 없으면 추가:
   ```python
   def get_current_status() -> str:
       """최근 1시간 이내 DQ 이벤트 기준 overall_status 반환."""
       # 기존 _compute_overall_status 로직 재사용 또는 호출
   ```

---

### B3 — order_preflight 8번째 체크: DEGRADED부터 신규 차단

**파일:** `backend/services/engine/order_preflight.py`

현재 7개 체크(emergency_halt, market_hours, position_size, max_positions, price_valid, ai_confidence, daily_loss_limit)가 있다.
**8번째 체크를 추가한다 — DQ 상태 확인.**

`run_preflight()` 함수 내 daily_loss_limit 체크 바로 다음에 추가:

```python
# 8. 데이터 품질 상태 확인 (DEGRADED 이상 시 신규 BUY 차단)
try:
    from ..engine.data_quality_guard import get_current_status as dq_get_status
    dq_status = dq_get_status()
    # DEGRADED(2), BLOCK_NEW_ENTRY(3), EMERGENCY(4) → 차단
    # INFO(0), WARNING(1) → 통과
    DQ_BLOCK_LEVELS = {"DEGRADED", "BLOCK_NEW_ENTRY", "EMERGENCY"}
    if dq_status in DQ_BLOCK_LEVELS:
        checks["data_quality"] = PREFLIGHT_BLOCK
        block_reasons.append(f"데이터 품질 저하 ({dq_status}) — 신규 주문 차단")
    else:
        checks["data_quality"] = PREFLIGHT_OK
except Exception as exc:
    logger.warning("WARN: [S6-P] DQ status check failed; fail-open reason=%s", exc)
    checks["data_quality"] = PREFLIGHT_OK  # DQ 조회 실패는 통과 (주문 막지 않음)
```

**근거:** DQ 조회 자체가 실패하면 fail-open (주문 허용). DQ 상태가 DEGRADED로 확인된 경우만 차단. 불확실성은 막지 않는다.

---

### B4 — position_manager price≤0 시 DQ 이벤트 발행 (DB만, 텔레그램 제외)

**파일:** `backend/services/engine/position_manager.py`

**현재 코드 (line ~183):**
```python
price = _to_float(tick.get("price"))
if price <= 0:
    return
```

**수정 후:**
```python
price = _to_float(tick.get("price"))
if price <= 0:
    try:
        from .data_quality_guard import publish_event as dq_publish
        dq_publish(
            source="position_manager",
            event_type="price_zero_or_negative",
            severity="DEGRADED",
            detail={"symbol": symbol, "price": price},
            notify_telegram=False,  # 텔레그램 알람 제외, DB 기록만
        )
    except Exception:
        pass
    return
```

**주의:**
- `notify_telegram=False` 파라미터가 `publish_event()`에 없으면 추가하거나, 기존 파라미터 중 알람 발송 여부를 제어하는 것을 사용
- Telegram 알람은 발송하지 않는다 (포지션 관리 중 가격 결손은 빈번할 수 있음)

---

### B5 — KIS WS 단절 자동 감지: 연속 3회 실패 → BLOCK_NEW_ENTRY

**파일:** `backend/services/kis/realtime_ws.py`

현재 `is_connected: bool`만 있고 연속 실패 카운터가 없다.

**추가 내용:**

클래스 `__init__` 또는 속성 초기화 위치에 추가:
```python
self._consecutive_fail_count: int = 0
self._ws_block_published: bool = False  # 중복 발행 방지
```

연결 성공 시 (메시지 정상 수신 또는 `is_connected = True` 위치):
```python
self._consecutive_fail_count = 0
self._ws_block_published = False
```

연결 실패/단절 시 (`is_connected = False` 위치, 예외 catch 블록):
```python
self._consecutive_fail_count += 1
if self._consecutive_fail_count >= 3 and not self._ws_block_published:
    try:
        from ..engine.data_quality_guard import publish_event as dq_publish
        dq_publish(
            source="realtime_ws",
            event_type="ws_consecutive_disconnect",
            severity="BLOCK_NEW_ENTRY",
            detail={"fail_count": self._consecutive_fail_count},
            notify_telegram=True,  # WS 단절은 텔레그램 알람 발송
        )
        self._ws_block_published = True
    except Exception as exc:
        logger.warning("WARN: [WS] DQ publish failed reason=%s", exc)
```

**임계값:** 3회 연속 실패 (PM 승인됨)
**효과:** 3회 연속 실패 → DQ에 BLOCK_NEW_ENTRY 기록 → preflight 8번째 체크(B3)에서 자동 차단

---

## publish_event() 파라미터 정의 (B2에서 확인 후 없으면 추가)

`data_quality_guard.publish_event()` 가 아래 시그니처를 지원해야 한다:

```python
def publish_event(
    source: str,           # 발행 컴포넌트 ("position_manager", "realtime_ws" 등)
    event_type: str,       # 이벤트 종류 ("price_zero_or_negative", "ws_consecutive_disconnect" 등)
    severity: str,         # "INFO" | "WARNING" | "DEGRADED" | "BLOCK_NEW_ENTRY" | "EMERGENCY"
    detail: dict,          # 추가 컨텍스트
    notify_telegram: bool = False,  # 텔레그램 알람 여부
) -> None:
```

기존 시그니처가 다르면 파라미터를 추가(하위 호환)하되 기존 호출은 변경하지 않는다.

---

## 변경 파일 목록

| 파일 | 변경 유형 | 내용 |
|------|----------|------|
| `backend/services/engine/decision_engine.py` | 수정 | None-pass → False 차단 (B1) |
| `backend/services/engine/data_quality_guard.py` | 수정/보완 | get_current_status(), publish_event() 시그니처 확인 및 보완 (B2) |
| `backend/services/engine/order_preflight.py` | 수정 | 8번째 체크 추가 — DQ 상태 (B3) |
| `backend/services/engine/position_manager.py` | 수정 | price≤0 DQ 발행 (B4) |
| `backend/services/kis/realtime_ws.py` | 수정 | 연속 실패 카운터 + BLOCK_NEW_ENTRY 발행 (B5) |

---

## 완료 기준

- [ ] `decision_engine` None-pass 수정 확인 — change_rate=None, volume_ratio=None 케이스 단위 테스트
- [ ] `order_preflight` 8번째 체크 존재 확인 — checks 딕셔너리에 "data_quality" 키 포함
- [ ] `position_manager` price≤0 시 DQ 이벤트 DB 저장 확인
- [ ] `realtime_ws` 연속 실패 3회 시 DQ BLOCK_NEW_ENTRY 기록 확인
- [ ] 빌드 에러 0개

## 완료 보고

완료 후 `docs/agent-comm/OUTBOX_CODEX_20260525_phase_b_data_guard.md` 에 작성:
- 수정된 파일 및 라인 번호
- 기존 `publish_event()` 시그니처 (B2 확인 결과)
- 단위 테스트 결과 (있다면)
- 이슈/특이사항
