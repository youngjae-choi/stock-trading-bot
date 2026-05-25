# INBOX: Codex — S10 복기 LLM화 + 레짐 피드백 학습 + S11 us_market_watch 제거

**우선순위:** HIGH  
**담당:** Codex (Backend Executor)  
**작성:** Sisyphus 2026-05-23

---

## 목표

1. S10 `review_audit.py`: 기존 하드코딩 규칙 추천을 **LLM 분석 기반**으로 교체
2. 프롬프트 `1600_opus_review.md` 재작성 (레짐 평가 + 구조화 JSON 응답 포함)
3. `regime_set_feedback` 테이블 추가 + `match_set()` 스코어 반영
4. `job_us_market_watch` (22:00 S11) 완전 제거

---

## 작업 1: `1600_opus_review.md` 재작성

`backend/prompts/1600_opus_review.md` 를 아래 내용으로 **완전 교체**한다.

```markdown
# S10 복기 분석 — Opus

## 역할
오늘 매매 결과, 시장 상황, 레짐 선택을 종합 분석한다.
분석 결과를 바탕으로 내일 거래에 반영할 구체적 설정값을 JSON으로 제시한다.

## 절대 규칙
- 출력은 반드시 아래 JSON 포맷 (다른 텍스트 없이 JSON만)
- 입력 데이터에 없는 사실 추론 금지
- 결과를 미화하거나 정당화하지 않는다
- 손실 거래도 솔직하게 분석한다
- settings_overrides는 실제로 변경할 항목만 포함 (변경 불필요시 빈 객체)

## 입력 데이터
{context_md}

## 출력 포맷 (JSON만, 다른 텍스트 없음)
```json
{
  "schema_version": "2.0",
  "trade_date": "YYYY-MM-DD",
  "regime_evaluation": {
    "evaluation": "good | neutral | bad",
    "reason": "레짐 선택이 결과와 맞았는지 2~3문장",
    "next_regime_hint": "risk_on | neutral | risk_off | volatile | same",
    "hint_reason": "내일 같은 시장 상황이면 어떤 레짐이 나을지 이유"
  },
  "settings_overrides": {
    "engine.min_confidence_floor": 0.65,
    "engine.max_positions": 7
  },
  "settings_reasoning": {
    "engine.min_confidence_floor": "변경 이유",
    "engine.max_positions": "변경 이유"
  },
  "narrative": "오늘 매매 전체 복기 서술 (마크다운, 500자 이내)",
  "patterns": {
    "winning": ["승리 패턴 1", "승리 패턴 2"],
    "losing": ["손실 패턴 1", "손실 패턴 2"],
    "missed": ["놓친 기회 관찰"]
  },
  "confidence": 0.0
}
```
```

---

## 작업 2: `review_audit.py` LLM 호출 추가

`run_review_audit()` 함수 마지막에 다음을 추가한다.

### 2-A. 컨텍스트 MD 조립 함수 추가

`review_audit.py`에 `_build_review_context_md(result, trade_date)` 함수 추가:

```python
def _build_review_context_md(result: dict, trade_date: str) -> str:
    """LLM에게 전달할 오늘 매매 컨텍스트 MD를 조립한다."""
    lines = []
    
    # 시장 상황 + 레짐
    with get_connection() as conn:
        mc = conn.execute(
            "SELECT regime, risk_level, market_data FROM morning_context WHERE trade_date=?",
            (trade_date,)
        ).fetchone()
        app = conn.execute(
            "SELECT set_name, set_id, regime_label, vix_value, kospi_change_pct, match_reason, applied_settings FROM regime_set_applications WHERE trade_date=? AND current_flag=1 ORDER BY applied_at DESC LIMIT 1",
            (trade_date,)
        ).fetchone()
    
    lines.append(f"# {trade_date} 매매 복기")
    lines.append(f"\n## 시장 상황")
    if mc:
        mc = dict(mc)
        lines.append(f"- 레짐: {mc.get('regime')} / 리스크레벨: {mc.get('risk_level')}")
        md = _json_loads(mc.get('market_data'), {})
        vix = (md.get('vix') or {}).get('price')
        kospi = (md.get('kospi') or {}).get('change_pct')
        if vix: lines.append(f"- VIX: {vix}")
        if kospi: lines.append(f"- KOSPI 등락: {kospi}%")
    
    lines.append(f"\n## 선택된 레짐 SET")
    if app:
        app = dict(app)
        lines.append(f"- SET: {app.get('set_name')} ({app.get('set_id')})")
        lines.append(f"- 레짐 라벨: {app.get('regime_label')}")
        lines.append(f"- 선택 이유: {app.get('match_reason', '-')}")
        settings = _json_loads(app.get('applied_settings'), {})
        if settings:
            lines.append(f"- 적용 파라미터: max_positions={settings.get('max_positions')}, stop_loss={settings.get('stop_loss_rate')}, take_profit={settings.get('take_profit_rate')}")
    
    lines.append(f"\n## 매매 결과")
    lines.append(f"- 총 거래: {result.get('total_trades', 0)}건")
    lines.append(f"- 승/패: {result.get('win_count', 0)}/{result.get('loss_count', 0)}")
    pnl = result.get('total_pnl', 0)
    pnl_pct = result.get('realized_pnl_pct', 0)
    lines.append(f"- 총 손익: {pnl:.0f}원 ({pnl_pct:+.2f}%)")
    
    ps = result.get('profile_summary') or {}
    if ps:
        lines.append(f"\n## Risk Profile별 성과")
        for profile, data in ps.items():
            win_rate = data['win'] / data['count'] * 100 if data['count'] else 0
            lines.append(f"- {profile}: {data['count']}건, 승률 {win_rate:.0f}%, PnL {data['pnl']:+.0f}원")
    
    fps = result.get('false_positives') or []
    if fps:
        lines.append(f"\n## 손실 종목 ({len(fps)}건)")
        for fp in fps[:5]:
            lines.append(f"- {fp.get('symbol', '-')}: {fp.get('pnl_pct', 0):+.2f}% / 진입이유: {fp.get('entry_reason', '-')}")
    
    missed = result.get('missed_entries') or []
    if missed:
        lines.append(f"\n## 걸러낸 종목 중 상승 ({len(missed)}건)")
        for m in missed[:5]:
            lines.append(f"- {m.get('symbol', '-')}: {m.get('filtered_at_stage', '-')} 단계 탈락, 실제 등락 {m.get('actual_change_pct', 0):+.2f}%")
    
    return "\n".join(lines)
```

### 2-B. LLM 호출 및 자동 반영 함수 교체

기존 `_send_action_plan_for_approval()` 함수를 아래로 **교체**한다:

```python
async def _send_action_plan_for_approval(result: dict[str, Any]) -> None:
    """LLM으로 복기 분석 후 Settings 자동 반영 + 텔레그램 통보."""
    from .llm_router import call_llm
    from ..settings_store import upsert_setting
    
    trade_date = str(result.get("trade_date") or "")
    now_iso = _now_kst_iso()
    
    # 1. 컨텍스트 MD 조립
    context_md = _build_review_context_md(result, trade_date)
    
    # 2. 프롬프트 로드 + 컨텍스트 삽입
    try:
        from .prompt_loader import load_prompt
        template = load_prompt("1600_opus_review.md")
    except Exception:
        prompt_path = pathlib.Path(__file__).parent.parent.parent / "prompts" / "1600_opus_review.md"
        template = prompt_path.read_text(encoding="utf-8")
    
    prompt = template.replace("{context_md}", context_md)
    
    # 3. LLM 호출
    llm_result = {"ok": False, "raw": ""}
    llm_response: dict = {}
    try:
        llm_result = await call_llm(prompt, task_name="s10_review")
        raw = llm_result.get("response", "")
        # JSON 파싱 (마크다운 코드블록 제거)
        import re
        json_match = re.search(r'\{[\s\S]*\}', raw)
        if json_match:
            llm_response = json.loads(json_match.group())
        logger.info("INFO: [S10-LLM] 복기 분석 완료 regime_eval=%s", 
                    llm_response.get("regime_evaluation", {}).get("evaluation"))
    except Exception as exc:
        logger.warning("WARN: [S10-LLM] LLM 호출 실패 — fallback to empty reason=%s", exc)
    
    # 4. 레짐 피드백 DB 저장
    regime_eval = llm_response.get("regime_evaluation") or {}
    evaluation = regime_eval.get("evaluation", "neutral")
    try:
        with get_connection() as conn:
            # regime_set_feedback 테이블 존재 확인
            tbl = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='regime_set_feedback'"
            ).fetchone()
            if tbl:
                app_row = conn.execute(
                    "SELECT set_id, regime_label, vix_value, kospi_change_pct FROM regime_set_applications WHERE trade_date=? AND current_flag=1 ORDER BY applied_at DESC LIMIT 1",
                    (trade_date,)
                ).fetchone()
                if app_row:
                    app = dict(app_row)
                    total = result.get("total_trades", 0)
                    win = result.get("win_count", 0)
                    win_rate = win / total if total else 0.0
                    conn.execute("""
                        INSERT INTO regime_set_feedback
                        (id, trade_date, set_id, regime_label, vix_value, kospi_change_pct,
                         win_rate, total_pnl, trades_count, evaluation, reason, next_action, created_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        str(uuid.uuid4()), trade_date,
                        app["set_id"], app["regime_label"],
                        app.get("vix_value"), app.get("kospi_change_pct"),
                        win_rate, result.get("total_pnl", 0), total,
                        evaluation,
                        regime_eval.get("reason", ""),
                        regime_eval.get("next_regime_hint", "same"),
                        now_iso
                    ))
                    conn.commit()
    except Exception as exc:
        logger.warning("WARN: [S10-LLM] regime_set_feedback 저장 실패 reason=%s", exc)
    
    # 5. Settings 자동 반영
    settings_overrides = llm_response.get("settings_overrides") or {}
    settings_reasoning = llm_response.get("settings_reasoning") or {}
    applied_settings: list[str] = []
    for key, new_val in settings_overrides.items():
        reason = settings_reasoning.get(key, "S10 LLM 자동 반영")
        try:
            upsert_setting(key=key, value=new_val, value_type="number", description=reason, actor="s10_llm")
            applied_settings.append(f"{key} → {new_val} ({reason})")
            logger.info("INFO: [S10-LLM] setting applied key=%s value=%s", key, new_val)
        except Exception as exc:
            logger.warning("WARN: [S10-LLM] setting apply failed key=%s reason=%s", key, exc)
    
    # 6. human_approval_queue 감사 로그 (auto_applied)
    narrative = llm_response.get("narrative", "")
    payload_json = json.dumps({
        "trade_date": trade_date,
        "regime_evaluation": regime_eval,
        "settings_overrides": settings_overrides,
        "applied_settings": applied_settings,
        "narrative": narrative,
        "llm_confidence": llm_response.get("confidence", 0),
    }, ensure_ascii=False, separators=(",", ":"))
    
    with get_connection() as conn:
        tbl = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='human_approval_queue'"
        ).fetchone()
        if tbl:
            conn.execute("""
                INSERT INTO human_approval_queue
                (id, change_type, title, description, payload_json, status, created_at)
                VALUES (?, 'next_day_action_plan', ?, ?, ?, 'auto_applied', ?)
            """, (
                str(uuid.uuid4()),
                f"[{trade_date}] 다음 거래일 액션 플랜",
                narrative[:200] if narrative else "LLM 복기 완료",
                payload_json,
                now_iso
            ))
            conn.commit()
    
    # 7. 결과를 result에 저장 (API 응답에 포함)
    result["llm_review"] = {
        "narrative": narrative,
        "regime_evaluation": regime_eval,
        "settings_overrides": settings_overrides,
        "applied_settings": applied_settings,
        "patterns": llm_response.get("patterns", {}),
        "applied_at": now_iso,
    }
    
    # 8. 텔레그램 통보 (승인 버튼 없이)
    try:
        from ..alert_service import send_telegram_message
        pnl_pct = result.get("realized_pnl_pct", 0) or 0
        sign = "+" if pnl_pct >= 0 else ""
        eval_emoji = {"good": "✅", "neutral": "📊", "bad": "⚠️"}.get(evaluation, "📊")
        msg = (
            f"📋 *S10 복기 완료* [{trade_date}]\n"
            f"손익: *{sign}{pnl_pct:.2f}%* | 레짐: {eval_emoji} {evaluation}\n"
        )
        if applied_settings:
            msg += "설정 자동 반영:\n" + "\n".join(f"  • {s}" for s in applied_settings[:3])
        else:
            msg += "설정 변경 없음"
        await send_telegram_message(msg)
    except Exception as exc:
        logger.warning("WARN: [S10-LLM] 텔레그램 통보 실패 reason=%s", exc)
```

### 2-C. `run_review_audit()` 반환값에 `llm_review` 포함

`run_review_audit()` 결과 dict에 `"llm_review": result.get("llm_review", {})`를 추가한다.  
`get_review_report()` 함수에서도 `human_approval_queue`에서 해당 날짜의 최신 `next_day_action_plan` row를 읽어 `llm_review`로 반환하도록 추가:

```python
# get_review_report() 마지막 부분에 추가
with get_connection() as conn:
    aq_row = conn.execute(
        """SELECT payload_json, created_at FROM human_approval_queue
           WHERE change_type='next_day_action_plan' AND title LIKE ?
           ORDER BY created_at DESC LIMIT 1""",
        (f"[{trade_date}]%",)
    ).fetchone()
if aq_row:
    llm_payload = _json_loads(dict(aq_row)["payload_json"], {})
    payload["llm_review"] = {
        "narrative": llm_payload.get("narrative", ""),
        "regime_evaluation": llm_payload.get("regime_evaluation", {}),
        "settings_overrides": llm_payload.get("settings_overrides", {}),
        "applied_settings": llm_payload.get("applied_settings", []),
        "applied_at": dict(aq_row).get("created_at", ""),
    }
else:
    payload["llm_review"] = {}
```

---

## 작업 3: `db.py` — `regime_set_feedback` 테이블 추가

`initialize_database()` 내 테이블 생성 블록에 추가:

```python
conn.execute("""
    CREATE TABLE IF NOT EXISTS regime_set_feedback (
        id TEXT PRIMARY KEY,
        trade_date TEXT NOT NULL,
        set_id TEXT NOT NULL,
        regime_label TEXT NOT NULL,
        vix_value REAL,
        kospi_change_pct REAL,
        win_rate REAL,
        total_pnl REAL,
        trades_count INTEGER,
        evaluation TEXT NOT NULL DEFAULT 'neutral',
        reason TEXT,
        next_action TEXT,
        created_at TEXT NOT NULL
    )
""")
conn.execute("CREATE INDEX IF NOT EXISTS idx_regime_set_feedback_set_id ON regime_set_feedback(set_id)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_regime_set_feedback_trade_date ON regime_set_feedback(trade_date)")
```

기존 DB에도 적용되도록 `initialize_database()` 안에서 `CREATE TABLE IF NOT EXISTS` 방식으로 추가한다.

---

## 작업 4: `regime_set_service.py` — `match_set()` 피드백 스코어 반영

`match_set()` 내 SET 매칭 후 최종 SET 선택 직전에 피드백 스코어를 반영한다:

```python
# 레짐 피드백 스코어 반영
def _apply_feedback_scores(candidates: list[dict], conn) -> list[dict]:
    """regime_set_feedback bad 누적 → 스코어 감점."""
    for c in candidates:
        set_id = c.get("id")
        bad_count = conn.execute(
            "SELECT COUNT(*) FROM regime_set_feedback WHERE set_id=? AND evaluation='bad'",
            (set_id,)
        ).fetchone()[0]
        good_count = conn.execute(
            "SELECT COUNT(*) FROM regime_set_feedback WHERE set_id=? AND evaluation='good'",
            (set_id,)
        ).fetchone()[0]
        c["score"] = c.get("score", 0) - (bad_count * 5) + (good_count * 3)
    return candidates
```

`match_set()` 내에서 후보 정렬 전에 호출:
```python
candidates = _apply_feedback_scores(candidates, conn)
candidates.sort(key=lambda x: x.get("score", 0), reverse=True)
```

`regime_set_feedback` 테이블이 없으면 스킵 (try/except로 보호).

---

## 작업 5: `job_us_market_watch` 완전 제거

`backend/services/scheduler.py`에서:
1. `job_us_market_watch` 함수 정의 제거
2. `scheduler.add_job(job_us_market_watch, ...)` 호출 제거
3. `"us_watch": "22:00"` 스케줄 설정 항목 제거
4. `"s11"` 키가 `us_market_watch`를 가리키는 경우 제거

`backend/services/engine/us_market_watch.py` 파일 자체는 삭제하지 않고 유지 (import 참조가 있을 수 있음).

---

## 검증

```bash
python -m py_compile \
  backend/services/db.py \
  backend/services/engine/review_audit.py \
  backend/services/regime_set_service.py \
  backend/services/scheduler.py

# DB 마이그레이션 확인
python3 -c "
import sys; sys.path.insert(0,'.')
from backend.services.db import initialize_database, get_connection
initialize_database()
with get_connection() as conn:
    cols = [dict(r)['name'] for r in conn.execute('PRAGMA table_info(regime_set_feedback)')]
    print('regime_set_feedback cols:', cols)
print('OK')
"
```

## 완료 후 OUTBOX

`docs/agent-comm/OUTBOX_CODEX_review_llm_regime_feedback.md` 에 결과 작성
