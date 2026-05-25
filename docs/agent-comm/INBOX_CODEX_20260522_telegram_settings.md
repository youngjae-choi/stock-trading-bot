# INBOX: 텔레그램 한국어화 + 매수체결 알림 + AI→설정 반영 파이프라인

**날짜:** 2026-05-22  
**우선순위:** HIGH  
**대상:** Codex (Backend)

---

## 변경 1: 텔레그램 알림 메시지 한국어화 (`scheduler.py`)

### 현황
`backend/services/scheduler.py` 내 `_audit_step_finish()` 함수 (약 line 165~182):
```python
emoji = "✅" if status == "success" else "⚠️" if status == "skipped" else "❌"
title = f"BOT {step} {status.upper()} {emoji}"
body = f"Message: {message}\nDate: {_today_kst()}"
if step == "S1" and metadata and "s1" in metadata:
    s1 = metadata["s1"]
    body += f"\nToken: {s1.get('token_status')}\nMarket: {s1.get('trading_day_status')}"
elif step == "S9" and metadata and "s9" in metadata:
    s9 = metadata["s9"]
    body += f"\nLiquidated: {s9.get('liquidation', {}).get('liquidated', 0)} items"
```

### 수정 내용
아래와 같이 한국어 메시지로 교체한다:

```python
# 단계별 한국어 레이블
_STEP_LABELS = {
    "S1": "S1 토큰/시장 확인",
    "S2": "S2 시장 시황 분석",
    "S3": "S3 유니버스 필터",
    "S4": "S4 하이브리드 스크리닝",
    "S5": "S5 데일리 플랜 생성",
    "S5-A": "S5-A 플랜 활성화",
    "S6": "S6 Decision Engine",
    "S9": "S9 당일 청산",
    "S10": "S10 Review & Audit",
    "S11": "S11 Learning Memory",
    "POSTPROCESS": "후처리 파이프라인",
}
_STATUS_KR = {"success": "완료", "failed": "실패", "skipped": "스킵", "blocked": "차단"}

emoji = "✅" if status == "success" else "⚠️" if status == "skipped" else "❌"
step_label = _STEP_LABELS.get(step, step)
status_kr = _STATUS_KR.get(status, status)
title = f"[매매봇] {step_label} {status_kr} {emoji}"
body = f"내용: {message}\n날짜: {_today_kst()}"

if step == "S1" and metadata and "s1" in metadata:
    s1 = metadata["s1"]
    token_kr = {"ok": "정상", "renewed": "갱신됨", "error": "오류"}.get(
        str(s1.get("token_status", "")), s1.get("token_status", "-")
    )
    market_kr = {"trading_day": "거래일", "holiday": "휴장일", "unknown": "확인불가"}.get(
        str(s1.get("trading_day_status", "")), s1.get("trading_day_status", "-")
    )
    body += f"\n토큰: {token_kr}\n시장: {market_kr}"
elif step == "S9" and metadata and "s9" in metadata:
    s9 = metadata["s9"]
    liq_count = s9.get("liquidation", {}).get("liquidated", 0)
    body += f"\n청산: {liq_count}건"
elif step == "S10" and metadata:
    pnl = metadata.get("total_pnl") or metadata.get("realized_pnl")
    if pnl is not None:
        body += f"\n오늘 손익: {'+' if float(pnl) >= 0 else ''}{float(pnl):,.0f}원"
elif step == "S11" and metadata:
    mem_count = metadata.get("memory_count") or metadata.get("saved_count")
    if mem_count is not None:
        body += f"\n저장된 메모리: {mem_count}건"
```

딕셔너리 `_STEP_LABELS`, `_STATUS_KR`는 함수 내 지역 변수로 정의하거나 모듈 최상단에 상수로 정의한다.

---

## 변경 2: 매수 체결 시 텔레그램 알림 (`fill_poller.py`)

### 현황
`backend/services/engine/fill_poller.py`의 `poll_once()` 함수:
- output1 체결 성공 시 (line ~395): `_mark_order_filled(order, kis_data)` 후 logger만 출력
- output2 체결 성공 시 (line ~437): 마찬가지

### 수정 내용
`_mark_order_filled()` 호출 직후, **매수(side == 'buy') 체결**일 때만 텔레그램 알림 발송:

```python
# output1 체결 성공 후 (기존 logger.info 아래에 추가):
if str(order.get("side", "")) == "buy":
    try:
        from ..alert_service import send_telegram_alert
        import asyncio
        _sym = str(_kis_value(kis_data, "pdno") or order.get("symbol") or "")
        _qty = ccld_qty
        _price = _to_float(_kis_value(kis_data, "avg_prvs", "avg_prc") or order.get("price"))
        _total = round(_price * _qty)
        asyncio.create_task(send_telegram_alert(
            f"[매매봇] 매수 체결 ✅",
            f"종목: {_sym}\n수량: {_qty:,}주\n체결가: {_price:,.0f}원\n체결금액: {_total:,}원\n날짜: {_today_kst() if hasattr(...)}"
        ))
    except Exception as _ta_exc:
        logger.warning("WARN: [FillPoller] 매수 텔레그램 알림 실패 reason=%s", _ta_exc)
```

`_today_kst()` 함수가 fill_poller에 없으면 `datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M")` 로 대체한다.

output2 폴백 체결 성공 후에도 동일한 로직 추가 (side 확인 후 알림).

**매도 체결은 알림 불필요** (현재도 없음, 추가하지 않는다).

---

## 변경 3: AI 리뷰→설정 반영 파이프라인

### 현황 (Gap 분석)
- `review_audit.py`의 `_send_action_plan_for_approval()`:
  - `payload_json`에 텍스트 추천만 저장 (`recommendations` 리스트)
  - `settings_changes` 필드 없음
- `telegram_webhook.py`의 `approve_action_plan_` 핸들러:
  - `human_approval_queue.status = 'approved'`만 저장
  - `system_settings` 업데이트 로직 없음
- 결과: PM이 텔레그램에서 "승인"을 눌러도 아무 설정도 바뀌지 않음

### 수정 A: `review_audit.py` — payload에 settings_changes 추가

`_send_action_plan_for_approval()` 함수 내 `approval_id = str(uuid.uuid4())` 바로 위에 아래 로직 삽입:

```python
# 승인 시 자동 적용할 설정 변경 계산
from ..settings_store import get_setting
settings_changes: dict[str, dict] = {}

current_conf_floor = float(get_setting("engine.min_confidence_floor") or 0.60)
current_price_change = float(get_setting("engine.min_price_change_pct") or 2.0)

if fp_count >= 2:
    # 손실 거래 2건 이상 → confidence floor 0.05 상향 (최대 0.80)
    new_val = round(min(current_conf_floor + 0.05, 0.80), 2)
    if new_val != current_conf_floor:
        settings_changes["engine.min_confidence_floor"] = {
            "old": current_conf_floor,
            "new": new_val,
            "reason": f"손실 거래 {fp_count}건 — confidence 임계값 상향",
        }
elif fp_count == 0 and realized_pnl_pct >= 3.0:
    # 손실 없고 수익 3% 이상 → confidence floor 0.03 하향 (최소 0.50)
    new_val = round(max(current_conf_floor - 0.03, 0.50), 2)
    if new_val != current_conf_floor:
        settings_changes["engine.min_confidence_floor"] = {
            "old": current_conf_floor,
            "new": new_val,
            "reason": f"손실 없음, 수익 {realized_pnl_pct:.1f}% — confidence 임계값 소폭 하향",
        }

if missed_count > 3 and realized_pnl_pct >= 0:
    # 놓친 기회 3건 초과, 손실 없음 → 최소 등락률 0.2 하향 (최소 1.0)
    new_val = round(max(current_price_change - 0.2, 1.0), 1)
    if new_val != current_price_change:
        settings_changes["engine.min_price_change_pct"] = {
            "old": current_price_change,
            "new": new_val,
            "reason": f"놓친 기회 {missed_count}건 — 최소 등락률 조건 소폭 완화",
        }
```

그리고 `payload_json` 딕셔너리에 `"settings_changes": settings_changes` 추가:
```python
payload_json = json.dumps(
    {
        "trade_date": trade_date,
        "recommendations": recommendations,
        "realized_pnl": realized_pnl,
        "realized_pnl_pct": realized_pnl_pct,
        "fp_count": fp_count,
        "missed_count": missed_count,
        "settings_changes": settings_changes,   # ← 추가
    },
    ...
)
```

텔레그램 메시지에도 settings_changes가 있을 경우 설정 변경 예고 추가:
```python
if settings_changes:
    changes_text = "\n".join(
        f"  • {k}: {v['old']} → {v['new']} ({v['reason']})"
        for k, v in settings_changes.items()
    )
    message += f"\n\n<b>승인 시 설정 자동 변경:</b>\n{changes_text}"
else:
    message += "\n\n(설정 변경 없음 — 현재 파라미터 유지)"
```

### 수정 B: `telegram_webhook.py` — 승인 시 settings 적용

`approve_action_plan_` 핸들러에서 `status = 'approved'` 업데이트 후:

```python
# payload_json 읽어서 settings_changes 적용
import json as _json
row = conn.execute(
    "SELECT payload_json FROM human_approval_queue WHERE id = ?",
    (approval_id,),
).fetchone()
applied_settings = []
if row:
    try:
        payload = _json.loads(row["payload_json"] or "{}")
        settings_changes = payload.get("settings_changes") or {}
        if settings_changes:
            from ...services.settings_store import upsert_setting
            for key, change in settings_changes.items():
                new_val = change.get("new")
                reason = change.get("reason", "PM 텔레그램 승인")
                if new_val is not None:
                    upsert_setting(
                        key=key,
                        value=new_val,
                        value_type="number",
                        description=reason,
                        actor="telegram_approval",
                    )
                    applied_settings.append(f"{key}={new_val}")
                    logger.info(
                        "INFO: telegram_webhook approved setting key=%s new=%s",
                        key, new_val,
                    )
    except Exception as apply_exc:
        logger.warning("WARN: telegram_webhook settings apply failed reason=%s", apply_exc)

# 응답 메시지에 적용 내용 포함
if applied_settings:
    await answer_telegram_callback(
        callback_id,
        f"✅ 액션 플랜 승인 완료. 설정 변경: {', '.join(applied_settings)}"
    )
else:
    await answer_telegram_callback(callback_id, "✅ 액션 플랜이 승인되었습니다.")
```

`get_connection()` with 블록 안에서 읽기 때문에, 읽기는 별도 `with get_connection() as conn:` 블록으로 분리하거나 같은 블록 내에서 처리한다.

---

## 완료 기준

1. `py_compile` 통과 (scheduler.py, fill_poller.py, review_audit.py, telegram_webhook.py)
2. 텔레그램 메시지 형식 확인 — `_audit_step_finish()` 모든 step에서 한국어 title/body
3. fill_poller.py — 매수 체결 시 `asyncio.create_task(send_telegram_alert(...))` 호출 확인
4. review_audit.py — `payload_json`에 `settings_changes` 필드 있음 확인
5. telegram_webhook.py — 승인 핸들러에서 `upsert_setting()` 호출 코드 존재 확인

결과를 `docs/agent-comm/OUTBOX_CODEX_20260522_telegram_settings.md`에 기록하라.
