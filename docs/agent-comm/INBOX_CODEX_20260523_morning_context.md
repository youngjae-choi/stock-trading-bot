# INBOX — Codex Backend: Morning Market Context 강화

**날짜**: 2026-05-23  
**우선순위**: High  
**작업 범위**: 백엔드 전용 (프론트엔드 변경 없음)

---

## 배경 및 목적

현재 S2 단계(시장 톤 분석)에서 Yahoo Finance로 시장 데이터를 수집하지만,
LLM을 거친 후 `tone` 단어 하나와 텍스트 요약만 DB에 저장된다.
수치 원본 데이터는 버려지고, S4 스크리닝과 S5 RulePack 생성 시 "neutral" 같은 단어만 전달된다.

**목표**: 수집 데이터를 확장하고, 수치 원본과 LLM 구조화 판단을 `morning_context` 테이블에 저장한다.
이후 S4, S5가 단어 대신 정량 데이터 + LLM 판단을 인풋으로 받는다.

---

## 작업 1 — `backend/services/db.py`에 `morning_context` 테이블 추가

`_create_tables()` 또는 테이블 생성 블록에 다음을 추가한다:

```python
conn.execute("""
    CREATE TABLE IF NOT EXISTS morning_context (
        id            TEXT PRIMARY KEY,
        trade_date    TEXT NOT NULL UNIQUE,
        market_data   TEXT NOT NULL DEFAULT '{}',
        regime        TEXT NOT NULL DEFAULT 'neutral',
        risk_level    TEXT NOT NULL DEFAULT 'normal',
        stock_character TEXT NOT NULL DEFAULT '',
        rulepack_hint TEXT NOT NULL DEFAULT '',
        key_factors   TEXT NOT NULL DEFAULT '[]',
        risk_factors  TEXT NOT NULL DEFAULT '[]',
        raw_response  TEXT NOT NULL DEFAULT '',
        provider      TEXT NOT NULL DEFAULT 'none',
        created_at    TEXT NOT NULL
    )
""")
conn.execute(
    "CREATE INDEX IF NOT EXISTS idx_morning_context_trade_date ON morning_context(trade_date)"
)
```

---

## 작업 2 — `backend/services/engine/market_data_fetcher.py` 수집 심볼 확장

`_SYMBOLS` dict에 다음을 추가한다:

```python
_SYMBOLS = {
    # 기존 유지
    "sp500":        "^GSPC",
    "nasdaq":       "^IXIC",
    "ftse100":      "^FTSE",
    "dax":          "^GDAXI",
    "oil_wti":      "CL=F",
    "usdkrw":       "USDKRW=X",
    "us_10y_yield": "^TNX",
    # 신규 추가
    "vix":          "^VIX",
    "nikkei":       "^N225",
    "hangseng":     "^HSI",
    "shanghai":     "000001.SS",
    "kospi":        "^KS11",
    # 미국 섹터 ETF
    "sector_tech":    "XLK",
    "sector_finance": "XLF",
    "sector_energy":  "XLE",
    "sector_health":  "XLV",
    "sector_industry":"XLI",
    # 한국 업종 (코스피 업종지수 — Yahoo에서 가능하면 수집, 실패 시 None 허용)
    "kr_semiconductor": "005930.KS",   # 삼성전자 (반도체 프록시)
    "kr_battery":       "373220.KS",   # LG에너지솔루션 (배터리 프록시)
}
```

`format_for_prompt()` 함수도 새 심볼들의 레이블을 추가한다:

```python
labels = {
    # 기존 유지
    "sp500":        "S&P 500",
    "nasdaq":       "NASDAQ",
    "ftse100":      "FTSE 100",
    "dax":          "DAX",
    "oil_wti":      "WTI 원유",
    "usdkrw":       "USD/KRW",
    "us_10y_yield": "미국 10년 국채금리(%)",
    # 신규
    "vix":          "VIX 공포지수",
    "nikkei":       "닛케이",
    "hangseng":     "항셍",
    "shanghai":     "상하이종합",
    "kospi":        "KOSPI",
    "sector_tech":  "미국 기술섹터 XLK",
    "sector_finance":"미국 금융섹터 XLF",
    "sector_energy": "미국 에너지섹터 XLE",
    "sector_health": "미국 헬스케어 XLV",
    "sector_industry":"미국 산업섹터 XLI",
    "kr_semiconductor": "삼성전자(반도체 프록시)",
    "kr_battery":   "LG에너지솔루션(배터리 프록시)",
}
```

---

## 작업 3 — `backend/prompts/0805_opus_market_tone.md` 프롬프트 업데이트

파일 전체를 다음으로 교체한다:

```markdown
# Opus — 시장 컨텍스트 분석 (아침 브리핑)

## 역할
너는 자동매매 시스템의 시장 컨텍스트 분석 AI다.
장 시작 전 수집된 글로벌 시장 데이터를 분석해 오늘 한국 단타 전략에 필요한 판단을 구조화된 JSON으로 출력한다.
매수/매도 지시, 특정 종목 추천, 리스크 한도 수치 직접 변경은 하지 않는다.

## 절대 규칙
- 출력은 반드시 순수 JSON 하나만 작성한다. 마크다운 코드블록 금지.
- 입력에 없는 사실을 만들지 않는다.
- 데이터가 부족하면 confidence를 낮추고 regime을 "neutral"로 설정한다.

## 입력
오늘 날짜: {date}
분석 시각: 장 시작 전

{market_data}

## 분석 작업

**1. 시장 레짐 분류** (regime)
- `risk_on`: 주요 지수 상승 + VIX 낮음(≤18) + 달러 약세 → 공격적 매수 환경
- `risk_off`: 주요 지수 하락 + VIX 높음(≥25) + 달러 강세 → 방어적 환경
- `neutral`: 혼조 또는 데이터 부족
- `volatile`: VIX 급등(≥30) 또는 지수 간 방향 불일치

**2. 리스크 레벨** (risk_level)
- `low`: VIX < 18, 주요 지수 +1% 이상, 아시아 동조 상승
- `normal`: 혼조 또는 소폭 등락
- `high`: VIX > 22 또는 주요 지수 -1% 이하
- `extreme`: VIX > 30 또는 주요 지수 -2% 이하

**3. 오늘 주도 가능 종목 성격** (stock_character)
어떤 성격의 종목이 오늘 움직일 가능성이 높은지 한 문장으로.
예: "기술·반도체 약세, 에너지·방어주 유리", "테마 무관 대형주 따라가기 장세"

**4. RulePack 힌트** (rulepack_hint)
리스크 한도 수치는 쓰지 않는다. 방향성만 한 문장.
예: "포지션 축소·타이트한 손절 권장", "평소 설정 유지 가능"

## 출력 JSON
{
  "schema_version": "2.0",
  "generated_at": "YYYY-MM-DDTHH:MM:SS+09:00",
  "tone": "positive|neutral|negative|mixed",
  "regime": "risk_on|neutral|risk_off|volatile",
  "confidence": 0.0,
  "risk_level": "low|normal|high|extreme",
  "summary": "한 줄 요약 (60자 이내)",
  "stock_character": "오늘 주도 가능 종목 성격 (60자 이내)",
  "rulepack_hint": "RulePack 방향 힌트 (60자 이내)",
  "key_factors": ["요인1", "요인2", "요인3"],
  "risk_factors": ["리스크1", "리스크2"],
  "data_note": "활용한 데이터 출처 및 누락 항목 메모"
}

## 실패 시
- 데이터가 거의 없으면 tone="neutral", regime="neutral", risk_level="normal", confidence=0.3 이하
- 불확실성은 risk_factors와 data_note에 명확히 남긴다.
```

---

## 작업 4 — `backend/services/engine/market_tone.py` 업데이트

### 4-A. `_parse_tone_response()` 함수 확장

현재 파싱 결과에 새 필드를 추가한다 (기존 필드는 그대로 유지):

```python
def _parse_tone_response(raw: str) -> dict[str, Any]:
    # ... 기존 JSON 파싱 로직 유지 ...
    
    # 기존 필드
    tone = str(data.get("tone", "neutral")).lower()
    if tone not in ("positive", "neutral", "negative", "mixed"):
        tone = "neutral"
    
    regime = str(data.get("regime", "neutral")).lower()
    if regime not in ("risk_on", "neutral", "risk_off", "volatile"):
        regime = "neutral"
    
    risk_level = str(data.get("risk_level", "normal")).lower()
    if risk_level not in ("low", "normal", "high", "extreme"):
        risk_level = "normal"
    
    return {
        "tone": tone,
        "confidence": float(data.get("confidence", 0.0)),
        "summary": str(data.get("summary", ""))[:200],
        "key_factors": data.get("key_factors", []),
        "risk_factors": data.get("risk_factors", []),
        "data_note": str(data.get("data_note", "")),
        # 신규
        "regime": regime,
        "risk_level": risk_level,
        "stock_character": str(data.get("stock_character", ""))[:200],
        "rulepack_hint": str(data.get("rulepack_hint", ""))[:200],
    }
```

### 4-B. `run_market_tone_analysis()` 함수 — `morning_context` 저장 추가

기존 `market_tone_results` INSERT 바로 아래에 `morning_context` upsert를 추가한다.

`market_data` 변수(fetch_overnight_market_summary()의 결과 dict)를 함수 스코프에서 보존해야 하므로,
except 블록에서도 `market_data = {}` 로 초기화해둔다.

```python
# market_data 초기화 (fetch 실패 시 빈 dict)
market_data: dict[str, Any] = {}
try:
    from .market_data_fetcher import fetch_overnight_market_summary, format_for_prompt
    market_data = await fetch_overnight_market_summary()
    market_data_text = format_for_prompt(market_data)
except Exception as exc:
    # ... 기존 fallback 로직 유지 ...
    pass

# ... LLM 호출 및 파싱 기존 로직 ...

# 기존 market_tone_results INSERT (유지)
with get_connection() as conn:
    conn.execute("""INSERT OR REPLACE INTO market_tone_results ...""", (...))

# 신규: morning_context upsert
morning_id = str(uuid.uuid4())
# market_data에서 수치만 추출 (fetched_at, errors 제외)
raw_numbers = {k: v for k, v in market_data.items() if k not in ("fetched_at", "errors") and isinstance(v, dict)}
try:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO morning_context
                (id, trade_date, market_data, regime, risk_level,
                 stock_character, rulepack_hint, key_factors, risk_factors,
                 raw_response, provider, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                morning_id,
                today,
                json.dumps(raw_numbers, ensure_ascii=False),
                parsed.get("regime", "neutral"),
                parsed.get("risk_level", "normal"),
                parsed.get("stock_character", ""),
                parsed.get("rulepack_hint", ""),
                json.dumps(parsed["key_factors"], ensure_ascii=False),
                json.dumps(parsed["risk_factors"], ensure_ascii=False),
                llm_result.get("raw", ""),
                llm_result.get("provider", "none"),
                now,
            ),
        )
except Exception as exc:
    logger.warning("WARN: morning_context 저장 실패 (비치명) — %s", exc)
    # morning_context 저장 실패는 비치명적 — 기존 흐름 계속 진행
```

### 4-C. 반환값에 새 필드 추가

```python
result = {
    "ok": True,
    "trade_date": today,
    "tone": parsed["tone"],
    "confidence": parsed["confidence"],
    "summary": parsed["summary"],
    "key_factors": parsed["key_factors"],
    "risk_factors": parsed["risk_factors"],
    "provider": llm_result.get("provider", "none"),
    "id": record_id,
    # 신규
    "regime": parsed.get("regime", "neutral"),
    "risk_level": parsed.get("risk_level", "normal"),
    "stock_character": parsed.get("stock_character", ""),
    "rulepack_hint": parsed.get("rulepack_hint", ""),
}
```

### 4-D. `get_today_market_tone()` 반환 시 morning_context 조인 (선택적 개선)

기존 함수는 market_tone_results에서만 읽으므로 그대로 두고,
별도 헬퍼 `get_today_morning_context(trade_date)` 함수를 추가한다:

```python
def get_today_morning_context(trade_date: str) -> dict[str, Any] | None:
    """DB에서 morning_context를 조회한다."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM morning_context WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
            (trade_date,),
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    for field in ("market_data", "key_factors", "risk_factors"):
        if isinstance(d.get(field), str):
            try:
                d[field] = json.loads(d[field])
            except Exception:
                d[field] = {} if field == "market_data" else []
    return d
```

---

## 작업 5 — `backend/services/engine/rulepack_generation.py` 업데이트

### 5-A. morning_context 로드 함수 추가

`_get_market_tone()` 함수 아래에 추가:

```python
def _get_morning_context(trade_date: str) -> dict[str, Any]:
    """오늘 morning_context를 로드한다. 없으면 빈 dict 반환."""
    try:
        from .market_tone import get_today_morning_context
        ctx = get_today_morning_context(trade_date)
        return ctx if ctx else {}
    except Exception as exc:
        logger.warning("WARN: morning_context 로드 실패 — %s", exc)
        return {}
```

### 5-B. `_build_prompt()` 함수에 morning_context 인풋 추가

현재 프롬프트 템플릿에 `{morning_context}` 변수를 추가해서 전달한다.
`_build_prompt()` 또는 `run_rulepack_generation()` 내 render_prompt 호출 부분에서:

```python
morning_ctx = _get_morning_context(today)

# morning_context를 LLM에게 보낼 텍스트로 변환
ctx_lines = []
if morning_ctx:
    ctx_lines.append(f"시장 레짐: {morning_ctx.get('regime', 'N/A')}")
    ctx_lines.append(f"리스크 레벨: {morning_ctx.get('risk_level', 'N/A')}")
    ctx_lines.append(f"주도 종목 성격: {morning_ctx.get('stock_character', 'N/A')}")
    ctx_lines.append(f"RulePack 힌트: {morning_ctx.get('rulepack_hint', 'N/A')}")
    # 주요 수치
    mdata = morning_ctx.get("market_data", {})
    for k in ("nasdaq", "sp500", "vix", "nikkei", "hangseng", "usdkrw"):
        item = mdata.get(k)
        if item:
            ctx_lines.append(f"  {k}: {item.get('price')} ({item.get('change_pct'):+.2f}%)")
    ctx_lines.append(f"핵심 요인: {', '.join(morning_ctx.get('key_factors', []))}")
    ctx_lines.append(f"리스크 요인: {', '.join(morning_ctx.get('risk_factors', []))}")
morning_context_text = "\n".join(ctx_lines) if ctx_lines else "데이터 없음"

# render_prompt 호출 시 변수로 전달
prompt = render_prompt(
    "0845_gpt_rulepack_generation.md",
    {
        "market_tone": ...,      # 기존
        "screening": ...,        # 기존
        "yesterday_rulepack": ..., # 기존
        "morning_context": morning_context_text,  # 신규
    },
)
```

---

## 작업 6 — `backend/prompts/0845_gpt_rulepack_generation.md` 업데이트

`## 입력` 섹션에 morning_context 항목을 추가한다:

```markdown
## 입력
1. 오늘의 시장 컨텍스트 (아침 브리핑)
{morning_context}

2. 오늘의 시장 톤 (`market_tone_*.json`)
3. Opus 스크리닝 결과 (`screening_*.json`)
4. 어제의 RulePack (`rulepack_active_YYYYMMDD-1.json`) — 변동폭 비교용
```

`market_context` 출력 필드도 업데이트:

```json
"market_context": {
  "tone_score": 0.0,
  "tone_label": "risk_on | neutral | risk_off | volatile",
  "regime": "risk_on | neutral | risk_off | volatile",
  "risk_level": "low | normal | high | extreme",
  "confidence": 0.0
}
```

---

## 작업 7 — `backend/services/engine/hybrid_screening.py` 업데이트

스크리닝 프롬프트를 빌드하는 `_build_prompt()` 또는 관련 함수에서
market_tone 데이터를 로드할 때 morning_context도 함께 로드해서 전달한다.

```python
from .market_tone import get_today_morning_context

morning_ctx = get_today_morning_context(trade_date) or {}
regime = morning_ctx.get("regime", "neutral")
risk_level = morning_ctx.get("risk_level", "normal")
stock_character = morning_ctx.get("stock_character", "")
```

이 값들을 스크리닝 프롬프트 변수로 전달하고, 스크리닝 프롬프트 파일에 해당 섹션을 추가한다.
(스크리닝 프롬프트 파일명 확인 후 해당 파일에 `{regime}`, `{risk_level}`, `{stock_character}` 변수를 추가)

---

## 작업 8 — `backend/api/routes/morning_context.py` 신규 생성

```python
"""Morning Context API routes."""
from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import APIRouter
from ..dependencies import require_auth

router = APIRouter(prefix="/api/v1/morning-context", tags=["morning-context"])

@router.get("/today")
async def get_today_morning_context_api(user=Depends(require_auth)):
    from ...services.engine.market_tone import get_today_morning_context
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    ctx = get_today_morning_context(today)
    if ctx is None:
        return {"ok": False, "data": None, "message": "오늘 morning context 없음"}
    return {"ok": True, "data": ctx}

@router.get("/{trade_date}")
async def get_morning_context_by_date(trade_date: str, user=Depends(require_auth)):
    from ...services.engine.market_tone import get_today_morning_context
    ctx = get_today_morning_context(trade_date)
    if ctx is None:
        return {"ok": False, "data": None}
    return {"ok": True, "data": ctx}
```

---

## 작업 9 — `backend/main.py`에 라우터 등록

기존 router include 블록에 추가:

```python
from .api.routes.morning_context import router as morning_context_router
app.include_router(morning_context_router)
```

---

## 완료 기준

1. `python -c "from backend.services.db import get_connection"` — 에러 없음
2. `python -m py_compile backend/services/engine/market_tone.py` — 에러 없음
3. `python -m py_compile backend/services/engine/rulepack_generation.py` — 에러 없음
4. `python -m py_compile backend/api/routes/morning_context.py` — 에러 없음
5. 서버 재시작 후 `curl http://127.0.0.1:8000/api/v1/morning-context/today` — 200 또는 401 응답 (서버 기동 확인)
6. `morning_context` 테이블이 DB에 존재하는지 확인

## 작업 완료 후

결과를 `docs/agent-comm/OUTBOX_CODEX_20260523_morning_context.md`에 작성하라.
형식: 완료 항목 체크리스트 + 변경된 파일 목록 + 발생한 이슈 요약
