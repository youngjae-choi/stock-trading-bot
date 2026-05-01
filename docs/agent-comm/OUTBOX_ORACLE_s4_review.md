# OUTBOX_ORACLE_s4_review — S4 하이브리드 스크리닝 코드 리뷰 결과

**전체 평가: PASS (경미한 WARN 2건)**

---

## 항목별 체크 결과

### 1. LLM 연동 안전성 ✅ PASS

`llm_router.call_llm()`은 모든 provider 실패 시 예외를 발생시키지 않고
`{"ok": False, "provider": "none", ...}` 딕셔너리를 반환한다.

`run_hybrid_screening()`에서 `if llm_result["ok"]:` 분기로 처리하며,
LLM 실패 시에도 `provider="none"`, `candidates=[]`로 DB에 정상 저장된다.
`job_hybrid_screening()`에도 `try/except`가 있어 스케줄러 수준에서도 보호된다.

**결론: 서버는 LLM 실패와 무관하게 계속 실행된다.**

---

### 2. DB 저장 일관성 ✅ PASS

세 경로 모두 DB 저장이 확인됨:

| 경로 | 저장 여부 | provider |
|------|----------|----------|
| S3 결과 없음 (no_universe) | ✅ `INSERT OR REPLACE` | `"none"` |
| LLM 실패 (ok=False) | ✅ 메인 DB 저장 블록 도달 | `"none"` |
| 정상 경로 | ✅ | 실제 provider 이름 |

LLM 실패 시 `provider = llm_result.get("provider", "none")`으로
안전하게 기본값을 처리하며, DB 저장 코드는 `if llm_result["ok"]` 블록 외부에 있다.

---

### 3. 프롬프트 인젝션 위험 ⚠️ WARN

`_build_prompt()`에서 candidates 데이터를 `json.dumps()`로 직렬화한 뒤
`str.format()`으로 프롬프트 템플릿에 삽입한다.

**위험 시나리오**: KIS API 응답 내 종목명(name 필드)에 중괄호(`{`, `}`)가 포함될 경우
`str.format()`이 KeyError 또는 의도치 않은 포맷 치환을 일으킬 수 있다.

**현재 리스크 수준**: 낮음 (한국 주식 종목명에 중괄호는 거의 없음).
그러나 `_SCREENING_PROMPT_TEMPLATE`에서 이미 LLM 출력 JSON 예시의 중괄호를
`{{`, `}}`로 이스케이프하고 있는 것을 보면, 개발자도 이 위험을 인지하고 있음.

**권장 수정**:
```python
# str.format() 대신 f-string 직접 조합 또는 Template 사용
prompt = (
    _SCREENING_PROMPT_TEMPLATE
    .replace("{candidates_json}", candidates_json)
    .replace("{market_tone_json}", market_tone_json)
    .replace("{news_summary}", news_summary)
)
```
`str.replace()`는 중괄호 이스케이프 문제가 없다.

---

### 4. API 응답 포맷 ✅ PASS

`screening.py` 라우터의 두 엔드포인트 모두 envelope 준수:

- `GET /api/v1/screening/today` → `{"ok", "source", "live", "payload"}` ✅
- `POST /api/v1/screening/run` → 성공 시 동일 envelope ✅, 실패 시 JSONResponse로 `{"ok": False, "error", "source", "live"}` ✅

---

### 5. import 오류 가능성 ✅ PASS

| import 경로 | 실제 존재 여부 |
|-------------|--------------|
| `from ..db import get_connection` | ✅ `backend/services/db.py` |
| `from .universe_filter import get_today_universe` | ✅ `universe_filter.py:265` 함수 확인 |
| `from . import llm_router` | ✅ `backend/services/engine/llm_router.py` |
| `from ...api.dependencies import require_console_user` | ✅ `backend/api/dependencies.py` |
| `from ...config import validate_config` | ✅ `backend/config.py` |
| `from ...services.engine import hybrid_screening as screening_svc` | ✅ |

순환 참조 없음. `engine/__init__.py`가 빈 파일이므로 패키지 충돌 없음.

---

### 6. scheduler job 번호 재정렬 ✅ PASS

| Job | 함수 | 로그 메시지 | 확인 |
|-----|------|------------|------|
| Job 1 | `job_refresh_kis_token` | `[Job1] KIS 토큰 선제 갱신` | ✅ |
| Job 2 | `job_market_tone_analysis` | `[Job2] 시장 톤 분석` | ✅ |
| Job 3 | `job_universe_filter` | `[Job3] 유니버스 필터` | ✅ |
| **Job 4** | **`job_hybrid_screening`** | **`[Job4] 하이브리드 스크리닝`** | ✅ |
| **Job 5** | **`job_intraday_liquidation`** | **`[Job5] 당일 청산`** | ✅ (이전 Job4 → Job5로 정상 재정렬) |
| Job 6 | `job_data_backup` | `[Job6] 데이터 백업` | ✅ |
| Job 7 | `job_us_market_watch` | `[Job7] 야간 미국장 관찰` | ✅ |

`main.py`에서 `screening_router` 등록 확인:
```python
from .api.routes.screening import router as screening_router
...
app.include_router(screening_router)  # line 79
```
✅ 정상 등록됨.

---

## 추가 관찰 사항 (WARN)

### ⚠️ `_parse_screening_response` — 이중 JSON 파싱 실패 시 예외 전파

```python
# hybrid_screening.py:150
data = json.loads(text[start:end])  # 이 라인도 실패하면 raise
```

두 번째 파싱도 실패하면 `JSONDecodeError`가 상위로 전파되어
`run_hybrid_screening()`의 `except Exception as parse_exc` 블록에서 포착된다.
포착 후 `candidates=[]`로 계속 진행되므로 **서버에는 영향 없음**.
단, `logger.warning`만 남고 실패 원인 raw 텍스트가 로그에 없어 디버깅이 어려울 수 있다.

**권장**: `logger.warning("...", parse_exc, llm_result.get("raw", "")[:200])` 처럼
원문 일부를 로그에 포함하면 운영 중 디버깅이 쉬워진다. (필수 아님)

---

## 최종 판정

| 항목 | 결과 |
|------|------|
| LLM 연동 안전성 | ✅ PASS |
| DB 저장 일관성 | ✅ PASS |
| 프롬프트 인젝션 위험 | ⚠️ WARN (낮은 리스크, 권장 수정) |
| API 응답 포맷 | ✅ PASS |
| import 오류 가능성 | ✅ PASS |
| scheduler job 번호 재정렬 | ✅ PASS |

**전체 평가: PASS — 즉시 배포 가능. 프롬프트 인젝션 수정은 S4-v2에서 반영 권장.**
