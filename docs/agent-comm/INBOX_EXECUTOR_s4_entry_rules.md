# INBOX_EXECUTOR_s4_entry_rules

## 역할
너는 Executor다. 아래 두 작업을 수행하라.
완료 후 `docs/agent-comm/OUTBOX_EXECUTOR_s4_entry_rules.md`에 결과를 작성하라.

---

## 작업 1 — S4 Hybrid Screening에서 매수 entry_rules 자동 생성

### 배경
현재 S4 Opus는 종목별 suitability_score만 반환한다.
이 작업에서는 오늘 시장 톤에 맞는 **매수 진입 조건(entry_rules)** 도 함께 생성하도록 확장한다.
생성된 entry_rules는 `rulepacks` 테이블에 오늘 날짜의 활성 RulePack으로 저장되어
Decision Engine이 실시간으로 읽어 매수 조건에 적용한다.

### 1a — `hybrid_screening.py` 프롬프트 템플릿 확장

파일: `backend/services/engine/hybrid_screening.py`

`_SCREENING_PROMPT_TEMPLATE` 문자열 내 출력 포맷 JSON에 아래 `entry_rules` 블록을 추가한다:

```
## 출력 포맷 (반드시 이대로, 다른 텍스트 없이 JSON만)
{
  "schema_version": "1.0",
  "generated_at": "YYYY-MM-DDTHH:MM:SS+09:00",
  "model": "llm",
  "entry_rules": {
    "min_ai_confidence": 0.65,
    "min_price_change_pct": 1.0,
    "max_price_change_pct": 5.0,
    "entry_rule_reason": "한 문장 근거"
  },
  "candidates": [...],
  "skipped": [...],
  "overall_confidence": 0.7
}
```

`entry_rules` 설정 기준 설명을 프롬프트에 추가:

```
## entry_rules 설정 기준

오늘 시장 톤을 보고 아래 기준으로 매수 진입 조건을 설정한다:

| 시장톤 | min_ai_confidence | min_price_change_pct | max_price_change_pct |
|--------|-------------------|----------------------|----------------------|
| positive | 0.60 | 0.8 | 6.0 |
| neutral  | 0.65 | 1.0 | 5.0 |
| negative | 0.72 | 1.5 | 4.0 |
| mixed    | 0.65 | 1.0 | 5.0 |

- 시장 톤 confidence < 0.4이면 모든 임계값을 보수적으로 +10% 조정
- 위 표는 참고값이며, 오늘 시장 상황에 맞게 조정 가능
- 절대 한도: min_ai_confidence는 0.40~0.85 사이만 허용
- entry_rule_reason: 왜 이 임계값을 설정했는지 한 문장
```

### 1b — `run_hybrid_screening()` 함수에서 entry_rules 저장

파일: `backend/services/engine/hybrid_screening.py`

`run_hybrid_screening()` 함수 내, Opus 응답 파싱 후 `candidates`를 추출하는 부분에서
`entry_rules`도 함께 추출하여 `rulepacks` 테이블에 저장한다.

아래 헬퍼 함수를 추가:

```python
def _save_daily_rulepack_from_screening(
    trade_date: str,
    entry_rules: dict[str, Any],
    ai_source: str,
    overall_confidence: float,
) -> None:
    """S4 Opus가 생성한 entry_rules를 오늘 날짜의 활성 RulePack으로 저장한다."""
    if not entry_rules:
        return

    # 기존 오늘 날짜 active rulepack이 있으면 entry_rules만 업데이트
    # 없으면 신규 생성
    import uuid
    now = datetime.now(timezone.utc).isoformat()

    machine_rules = {
        "schema_version": "1.1",
        "rulepack_id": f"RP-S4-{trade_date.replace('-','')}",
        "generated_at": now,
        "valid_for_date": trade_date,
        "ai_source": ai_source,
        "market_context": {"overall_confidence": overall_confidence},
        "entry_rules": entry_rules,
        "risk_limits": {},
        "notes": "S4 Hybrid Screening에서 자동 생성된 매수 진입 조건"
    }

    with get_connection() as conn:
        # 오늘 날짜 기존 rulepack 확인
        existing = conn.execute(
            "SELECT rulepack_id FROM rulepacks WHERE trade_date = ? AND status = 'active' LIMIT 1",
            (trade_date,)
        ).fetchone()

        if existing:
            # 기존 것의 machine_rules.entry_rules만 업데이트
            row = conn.execute(
                "SELECT machine_rules FROM rulepacks WHERE rulepack_id = ?",
                (existing["rulepack_id"],)
            ).fetchone()
            try:
                mr = json.loads(row["machine_rules"] or "{}")
            except Exception:
                mr = {}
            mr["entry_rules"] = entry_rules
            mr["generated_at"] = now
            conn.execute(
                "UPDATE rulepacks SET machine_rules = ?, activated_at = ? WHERE rulepack_id = ?",
                (json.dumps(mr, ensure_ascii=False), now, existing["rulepack_id"])
            )
            logger.info(
                "SUCCESS: [S4] 기존 RulePack entry_rules 업데이트 rulepack_id=%s",
                existing["rulepack_id"]
            )
        else:
            # 신규 생성
            rulepack_id = f"RP-S4-{trade_date.replace('-','')}-{str(uuid.uuid4())[:6].upper()}"
            conn.execute(
                """
                INSERT INTO rulepacks
                    (rulepack_id, trade_date, mode, status, machine_rules, summary,
                     changes, validation, created_at, activated_at)
                VALUES (?, ?, 'auto', 'active', ?, ?, '', '{}', ?, ?)
                """,
                (
                    rulepack_id,
                    trade_date,
                    json.dumps(machine_rules, ensure_ascii=False),
                    f"S4 자동 생성 — min_confidence={entry_rules.get('min_ai_confidence', 0.65)}",
                    now,
                    now,
                )
            )
            logger.info(
                "SUCCESS: [S4] 신규 RulePack 생성 rulepack_id=%s entry_rules=%s",
                rulepack_id, entry_rules
            )
```

`run_hybrid_screening()` 함수 내 결과 저장 직후에 아래를 추가:

```python
# entry_rules가 있으면 RulePack으로 저장
entry_rules = parsed.get("entry_rules", {})
if entry_rules and isinstance(entry_rules, dict):
    _save_daily_rulepack_from_screening(
        trade_date=today,
        entry_rules=entry_rules,
        ai_source=provider,
        overall_confidence=overall_confidence,
    )
```

---

## 작업 2 — Settings에 매수조건 가드레일 seed 추가

파일: `backend/services/db.py`

`_seed_system_settings()` 함수에 아래 3개 항목을 추가한다:

```python
(
    "engine.min_confidence_floor",
    "0.40",
    "number",
    "AI 매수 신호 confidence 절대 하한선 (AI가 이 값 이하로 설정 불가)"
),
(
    "engine.min_price_change_pct",
    "0.5",
    "number",
    "매수 진입 최소 등락률 % (AI가 이 값 이하로 설정 불가)"
),
(
    "engine.max_price_change_pct",
    "8.0",
    "number",
    "매수 진입 최대 등락률 % (AI가 이 값 이상으로 설정 불가)"
),
```

그리고 `decision_engine.py`의 `_evaluate_rules()`에서 entry_rules 적용 시
가드레일 검사를 추가한다:

`_get_setting_float` 헬퍼가 이미 있으므로 아래 로직을 `_evaluate_rules()` 시작 부분에 추가:

```python
# AI가 설정한 임계값에 가드레일 적용
floor = _get_setting_float("engine.min_confidence_floor", 0.40)
ai_conf_min = max(ai_conf_min, floor)  # 절대 하한선 적용

price_floor = _get_setting_float("engine.min_price_change_pct", 0.5)
price_ceil = _get_setting_float("engine.max_price_change_pct", 8.0)
price_min_pct = max(price_min_pct, price_floor)
price_max_pct = min(price_max_pct, price_ceil)
```

---

## 검증

```bash
python3 -m py_compile \
  backend/services/engine/hybrid_screening.py \
  backend/services/db.py \
  backend/services/engine/decision_engine.py
echo "py_compile OK"
```

아래 검증 스크립트 실행:

```bash
python3 - <<'EOF'
import sys, os
sys.path.insert(0, '.')
os.environ.setdefault("APP_ENV", "development")

# entry_rules 파싱 검증
from backend.services.engine.hybrid_screening import _save_daily_rulepack_from_screening
print("_save_daily_rulepack_from_screening import OK")

# guardrail 확인
from backend.services.engine.decision_engine import _get_setting_float
floor = _get_setting_float("engine.min_confidence_floor", 0.40)
print(f"min_confidence_floor: {floor}")

print("PASS")
EOF
```

---

## 완료 체크리스트

- [ ] `_SCREENING_PROMPT_TEMPLATE`에 `entry_rules` 블록 + 기준표 추가
- [ ] `_save_daily_rulepack_from_screening()` 함수 추가
- [ ] `run_hybrid_screening()`에서 entry_rules 파싱 후 저장 호출
- [ ] `db.py` seed에 3개 가드레일 항목 추가
- [ ] `decision_engine.py _evaluate_rules()`에 가드레일 적용
- [ ] py_compile 통과
- [ ] 검증 스크립트 통과

결과는 `docs/agent-comm/OUTBOX_EXECUTOR_s4_entry_rules.md`에 작성하라.
