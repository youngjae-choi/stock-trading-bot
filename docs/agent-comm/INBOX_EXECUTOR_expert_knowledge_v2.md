# INBOX_EXECUTOR_expert_knowledge_v2

## 역할
너는 Executor(Codex)다. Expert Knowledge 화면을 PDF 업로드 → LLM 분석 → 승인 → Settings 반영 흐름으로 재설계한다.
완료 후 `docs/agent-comm/OUTBOX_EXECUTOR_expert_knowledge_v2.md`에 결과를 작성하라.

Gemini가 quota 소진 상태라 backend + frontend 모두 Codex가 담당한다.

수정 대상:
- `backend/api/routes/expert_knowledge.py`
- `backend/services/engine/expert_knowledge.py`
- `backend/static/console.html` (Expert Knowledge 섹션만)

기존 `strategy_knowledge_items` 테이블과 기존 CRUD API는 그대로 유지하되, 신규 PDF 플로우를 **추가**한다.

---

## 배경

현재 Expert Knowledge는 운영자가 텍스트를 수동 입력해서 knowledge item을 만드는 구조다.
이를 다음 흐름으로 개편한다:

```
운영자 PDF 업로드
  → 서버에서 텍스트 추출
  → LLM(Claude Opus or Gemini)에 전략 분석 요청
  → 전략 후보 목록 반환
  → 운영자가 목록 확인 후 "승인 및 적용" 클릭
  → 시스템이 각 항목을 Settings 키에 매핑해 저장
  → 매핑 불가능한 항목은 메시지 출력
```

---

## 작업 1 — PDF 텍스트 추출 라이브러리 설치 + 유틸

`pypdf` 라이브러리를 사용한다 (pip install pypdf).

`backend/services/engine/expert_knowledge.py`에 함수 추가:

```python
def extract_pdf_text(file_bytes: bytes) -> str:
    """PDF bytes에서 전체 텍스트를 추출한다."""
    import io
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError("pypdf 라이브러리가 없습니다. pip install pypdf")
    reader = PdfReader(io.BytesIO(file_bytes))
    pages = []
    for page in reader.pages:
        text = page.extract_text() or ""
        pages.append(text)
    return "\n".join(pages).strip()
```

`requirements.txt`에 `pypdf>=4.0.0` 추가.

---

## 작업 2 — LLM 전략 분석 함수 추가

`backend/services/engine/expert_knowledge.py`에 함수 추가:

```python
async def analyze_strategy_with_llm(text: str) -> dict:
    """PDF 텍스트를 LLM에 보내 전략 후보 목록을 JSON으로 반환한다.
    
    반환 형식:
    {
      "strategy_candidates": [
        {
          "label": "AI 신뢰도 최소값",
          "value": "0.65",
          "setting_key": "engine.min_confidence_floor",
          "value_type": "number",
          "reason": "문서 3페이지: '60% 이상의 신뢰도' 언급"
        },
        ...
      ],
      "unmappable": [
        {
          "label": "뉴스 기반 감성 필터",
          "description": "현재 Settings에 해당 키 없음",
          "raw_text": "..."
        }
      ],
      "summary": "LLM이 요약한 전략 핵심 1~3문장"
    }
    """
```

LLM 호출 구현:
- `backend/services/engine/market_tone.py`의 Anthropic SDK 패턴을 참고해 재사용한다.
- 모델: `claude-opus-4-6` (fallback: groq → openai → none)
- provider="none"이면 빈 candidates 반환 + `error` 필드 포함

**매핑 가능한 Settings 키 목록** (이 목록에 있는 것만 `setting_key`를 채운다):

```python
MAPPABLE_SETTINGS = {
    # 키: (label, value_type)
    "engine.min_confidence_floor": ("AI 신뢰도 하한선", "number"),
    "engine.min_ai_confidence": ("AI 신뢰도 기본값", "number"),
    "engine.min_price_change_pct": ("최소 등락률 %", "number"),
    "engine.max_price_change_pct": ("최대 등락률 %", "number"),
    "risk.daily_loss_limit_percent": ("일일 손실한도 %", "number"),
    "risk.max_positions": ("최대 동시 보유 종목 수", "number"),
    "risk.max_position_rate_per_stock": ("종목당 최대 비중", "number"),
    "risk.force_exit_time": ("강제청산 시간 (HH:MM)", "string"),
    "risk.new_entry_cutoff_time": ("신규 매수 금지 시간 (HH:MM)", "string"),
}
```

**LLM 프롬프트 (시스템 메시지):**
```
당신은 주식 자동매매 시스템의 매매전략 파싱 전문가입니다.
아래 매핑 가능한 Settings 키 목록을 참고해서 PDF 문서에서 전략 항목을 추출해주세요.

매핑 가능한 키 목록:
{MAPPABLE_SETTINGS_JSON}

규칙:
1. PDF 내용에서 수치 기반 매매 조건을 찾는다
2. 매핑 가능한 키와 대응되면 setting_key에 해당 키를 넣는다
3. 매핑 불가능한 내용은 unmappable 배열에 넣는다
4. value는 항상 문자열로 반환한다
5. 반드시 JSON만 반환하고 다른 텍스트는 절대 포함하지 않는다

출력 형식:
{
  "strategy_candidates": [...],
  "unmappable": [...],
  "summary": "전략 핵심 요약"
}
```

---

## 작업 3 — 새 API 엔드포인트 추가

`backend/api/routes/expert_knowledge.py`에 3개 엔드포인트 추가:

### 3-A: PDF 업로드 + 분석

```python
from fastapi import UploadFile, File

@router.post("/upload-pdf")
async def upload_pdf_for_analysis(
    file: UploadFile = File(...),
    user: dict = Depends(require_console_user),
):
    """PDF 업로드 → 텍스트 추출 → LLM 분석 → 전략 후보 반환."""
```

- `file.content_type`이 `application/pdf`가 아니면 400 반환: `{"ok": false, "error": "PDF 파일만 업로드 가능합니다"}`
- 파일 크기 10MB 초과 시 400 반환
- `extract_pdf_text(await file.read())` 호출
- `analyze_strategy_with_llm(text)` 호출
- 추출된 텍스트와 분석 결과를 `pdf_analyses` 테이블에 저장 (아래 스키마)
- 응답: `{"ok": true, "payload": {"analysis_id": "...", "candidates": [...], "unmappable": [...], "summary": "..."}}`

### 3-B: 전략 후보 승인 및 Settings 적용

```python
@router.post("/apply-strategy/{analysis_id}")
async def apply_strategy(
    analysis_id: str,
    body: StrategyApplyRequest,
    user: dict = Depends(require_console_user),
):
    """승인된 전략 후보를 Settings에 적용한다."""
```

`StrategyApplyRequest`:
```python
class StrategyApplyRequest(BaseModel):
    approved_keys: list[str]  # 적용할 setting_key 목록
```

처리 로직:
1. `pdf_analyses` 테이블에서 analysis_id 조회
2. `approved_keys`에 포함된 candidate만 처리
3. 각 candidate의 `setting_key`가 `MAPPABLE_SETTINGS`에 있으면 → `upsert_setting()` 호출
4. 없으면 → unmappable 목록에 추가
5. 결과 반환:
```json
{
  "ok": true,
  "payload": {
    "applied": [{"setting_key": "engine.min_confidence_floor", "value": "0.65"}],
    "skipped": [],
    "messages": ["engine.min_confidence_floor: 0.65 적용 완료"]
  }
}
```

### 3-C: 분석 이력 조회

```python
@router.get("/analyses")
async def list_analyses(user: dict = Depends(require_console_user)):
    """PDF 분석 이력 목록 반환 (최신 10건)."""
```

---

## 작업 4 — DB 스키마 추가

`backend/services/db.py`의 `_create_tables()` 내에 추가:

```sql
CREATE TABLE IF NOT EXISTS pdf_analyses (
    analysis_id   TEXT PRIMARY KEY,
    filename      TEXT NOT NULL,
    extracted_text TEXT NOT NULL,
    candidates    TEXT NOT NULL DEFAULT '[]',   -- JSON
    unmappable    TEXT NOT NULL DEFAULT '[]',   -- JSON
    summary       TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'pending', -- pending | applied
    created_at    TEXT NOT NULL,
    applied_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_pdf_analyses_created ON pdf_analyses(created_at DESC);
```

---

## 작업 5 — Expert Knowledge 화면 재설계

`backend/static/console.html`에서 `id="screen-expert-knowledge"` 섹션을 찾아 교체한다.

### 새 HTML 구조:

```html
<section class="screen" id="screen-expert-knowledge">
  <div class="page-head">
    <div>
      <h1 class="page-title">Expert Knowledge</h1>
      <p class="page-desc">PDF 전략 문서를 업로드하면 AI가 매매 조건을 추출해 Settings에 반영합니다.</p>
    </div>
  </div>

  <!-- PDF 업로드 영역 -->
  <div class="card" style="margin-bottom:16px;">
    <div class="card-title">PDF 전략 문서 업로드</div>
    <div style="display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin-top:8px;">
      <input type="file" id="ek-pdf-input" accept=".pdf" style="flex:1; padding:8px; background:var(--panel-2); border:1px solid var(--border); border-radius:6px; color:var(--text);">
      <button class="btn primary" onclick="ekUploadPdf()">업로드 및 분석</button>
    </div>
    <div id="ek-upload-status" style="margin-top:8px; font-size:12px; color:var(--muted);"></div>
  </div>

  <!-- 분석 결과 -->
  <div class="card" id="ek-result-card" style="display:none; margin-bottom:16px;">
    <div class="card-title">AI 분석 결과</div>
    <div id="ek-summary" style="font-size:13px; color:var(--muted); margin-bottom:12px;"></div>

    <table style="width:100%; border-collapse:collapse; font-size:13px;">
      <thead>
        <tr style="border-bottom:1px solid var(--border);">
          <th style="padding:6px 8px; text-align:left;">적용</th>
          <th style="padding:6px 8px; text-align:left;">항목</th>
          <th style="padding:6px 8px; text-align:left;">추출값</th>
          <th style="padding:6px 8px; text-align:left;">Settings 키</th>
          <th style="padding:6px 8px; text-align:left;">근거</th>
        </tr>
      </thead>
      <tbody id="ek-candidates-tbody"></tbody>
    </table>

    <div id="ek-unmappable" style="margin-top:12px; display:none;">
      <div style="font-size:12px; color:var(--muted); margin-bottom:4px;">⚠ 아래 항목은 현재 Settings에 키가 없어 적용 불가:</div>
      <div id="ek-unmappable-list" style="font-size:12px; color:var(--warn);"></div>
    </div>

    <div style="margin-top:16px; display:flex; gap:8px;">
      <button class="btn primary" onclick="ekApplyStrategy()">승인 및 Settings 적용</button>
      <button class="btn" onclick="ekReset()">취소</button>
    </div>
    <div id="ek-apply-result" style="margin-top:8px; font-size:12px;"></div>
  </div>

  <!-- 분석 이력 -->
  <div class="card">
    <div class="card-title">분석 이력</div>
    <div id="ek-history-list" style="font-size:13px; color:var(--muted);">로딩중...</div>
  </div>
</section>
```

### JavaScript 함수 (기존 `loadExpertKnowledge()` 아래에 추가):

```javascript
var _ekCurrentAnalysisId = null;

async function ekUploadPdf() {
  var input = document.getElementById('ek-pdf-input');
  var statusEl = document.getElementById('ek-upload-status');
  var resultCard = document.getElementById('ek-result-card');
  if (!input.files || !input.files[0]) {
    statusEl.textContent = 'PDF 파일을 선택해주세요.';
    return;
  }
  var file = input.files[0];
  if (!file.name.toLowerCase().endsWith('.pdf')) {
    statusEl.textContent = 'PDF 파일만 업로드 가능합니다.';
    return;
  }
  statusEl.textContent = '업로드 중... (LLM 분석에 30~60초 소요될 수 있습니다)';
  resultCard.style.display = 'none';
  _ekCurrentAnalysisId = null;

  try {
    var formData = new FormData();
    formData.append('file', file);
    var res = await fetch('/api/v1/expert-knowledge/upload-pdf', {
      method: 'POST',
      body: formData
    });
    var data = await res.json();
    if (!data.ok) {
      statusEl.textContent = '분석 실패: ' + (data.error || '알 수 없는 오류');
      return;
    }
    _ekCurrentAnalysisId = data.payload.analysis_id;
    statusEl.textContent = '분석 완료. 아래 결과를 확인하세요.';
    ekRenderResult(data.payload);
    ekLoadHistory();
  } catch(e) {
    statusEl.textContent = '오류: ' + e.message;
  }
}

function ekRenderResult(payload) {
  var resultCard = document.getElementById('ek-result-card');
  var summaryEl = document.getElementById('ek-summary');
  var tbody = document.getElementById('ek-candidates-tbody');
  var unmappableEl = document.getElementById('ek-unmappable');
  var unmappableList = document.getElementById('ek-unmappable-list');
  var applyResult = document.getElementById('ek-apply-result');

  resultCard.style.display = '';
  summaryEl.textContent = payload.summary || '';
  applyResult.textContent = '';

  var candidates = payload.candidates || [];
  tbody.innerHTML = candidates.length === 0
    ? '<tr><td colspan="5" class="muted" style="padding:12px; text-align:center;">추출된 전략 항목 없음</td></tr>'
    : candidates.map(function(c, i) {
        return '<tr style="border-bottom:1px solid var(--border);">'
          + '<td style="padding:6px 8px; text-align:center;"><input type="checkbox" id="ek-chk-' + i + '" data-key="' + escapeHtml(c.setting_key || '') + '" checked' + (c.setting_key ? '' : ' disabled') + '></td>'
          + '<td style="padding:6px 8px;">' + escapeHtml(c.label || '') + '</td>'
          + '<td style="padding:6px 8px; font-weight:600; color:var(--blue);">' + escapeHtml(String(c.value || '')) + '</td>'
          + '<td style="padding:6px 8px; font-size:11px; color:var(--muted);">' + escapeHtml(c.setting_key || '매핑 불가') + '</td>'
          + '<td style="padding:6px 8px; font-size:11px; color:var(--muted);">' + escapeHtml(c.reason || '') + '</td>'
          + '</tr>';
      }).join('');

  var unmappable = payload.unmappable || [];
  if (unmappable.length > 0) {
    unmappableEl.style.display = '';
    unmappableList.innerHTML = unmappable.map(function(u) {
      return '<div style="margin-bottom:4px;">• <strong>' + escapeHtml(u.label || '') + '</strong>: '
        + escapeHtml(u.description || '') + ' — '
        + '<em>OOO 기능을 Setting 화면에 추가하여야 합니다. 개발 후 재 요청해주세요.</em></div>';
    }).join('');
  } else {
    unmappableEl.style.display = 'none';
  }
}

async function ekApplyStrategy() {
  if (!_ekCurrentAnalysisId) return;
  var checkboxes = document.querySelectorAll('#ek-candidates-tbody input[type=checkbox]:checked');
  var approvedKeys = Array.from(checkboxes).map(function(cb) { return cb.getAttribute('data-key'); }).filter(Boolean);
  if (!approvedKeys.length) {
    document.getElementById('ek-apply-result').textContent = '적용할 항목을 선택해주세요.';
    return;
  }
  try {
    var res = await fetch('/api/v1/expert-knowledge/apply-strategy/' + encodeURIComponent(_ekCurrentAnalysisId), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({approved_keys: approvedKeys})
    });
    var data = await res.json();
    if (!data.ok) {
      document.getElementById('ek-apply-result').textContent = '적용 실패: ' + (data.error || '');
      return;
    }
    var msgs = (data.payload.messages || []).join('\n');
    document.getElementById('ek-apply-result').style.color = 'var(--green)';
    document.getElementById('ek-apply-result').textContent = msgs || '적용 완료';
  } catch(e) {
    document.getElementById('ek-apply-result').textContent = '오류: ' + e.message;
  }
}

function ekReset() {
  _ekCurrentAnalysisId = null;
  document.getElementById('ek-result-card').style.display = 'none';
  document.getElementById('ek-pdf-input').value = '';
  document.getElementById('ek-upload-status').textContent = '';
}

async function ekLoadHistory() {
  var el = document.getElementById('ek-history-list');
  try {
    var res = await fetch('/api/v1/expert-knowledge/analyses');
    var data = await res.json();
    var items = data.payload || [];
    if (!items.length) { el.textContent = '분석 이력 없음'; return; }
    el.innerHTML = items.map(function(item) {
      var ts = item.created_at ? item.created_at.substring(0, 16).replace('T', ' ') : '-';
      var status = item.status === 'applied' ? '<span style="color:var(--green);">적용됨</span>' : '대기';
      return '<div style="padding:6px 0; border-bottom:1px solid var(--border); display:flex; gap:8px; align-items:center;">'
        + '<span style="color:var(--muted); font-size:11px;">' + ts + '</span>'
        + '<span>' + escapeHtml(item.filename || '') + '</span>'
        + '<span>' + status + '</span>'
        + '</div>';
    }).join('');
  } catch(e) {
    el.textContent = '이력 로드 실패: ' + e.message;
  }
}
```

### 화면 진입 시 자동 로드 수정

`showScreen()` 함수 내 `if (name === "expert-knowledge")` 블록을:
```javascript
if (name === "expert-knowledge") {
  ekLoadHistory();
}
```
으로 교체한다 (기존 `loadExpertKnowledge()` 호출을 교체).

---

## 작업 6 — require_console_user 추가

`backend/api/routes/expert_knowledge.py`의 router 정의에
`dependencies=[Depends(require_console_user)]`가 없으면 추가한다.

```python
from ...api.dependencies import require_console_user

router = APIRouter(
    prefix="/api/v1/expert-knowledge",
    tags=["expert-knowledge"],
    dependencies=[Depends(require_console_user)],
)
```

---

## 검증

```bash
# 1. py_compile
python3 -m py_compile backend/api/routes/expert_knowledge.py backend/services/engine/expert_knowledge.py backend/services/db.py && echo "py_compile OK"

# 2. HTML parse
python3 -c "
from html.parser import HTMLParser
with open('backend/static/console.html', encoding='utf-8') as f:
    HTMLParser().feed(f.read())
print('HTML parse OK')
"

# 3. pypdf import
python3 -c "from pypdf import PdfReader; print('pypdf OK')"

# 4. DB 스키마 확인
python3 - <<'PY'
import os
os.environ.setdefault("APP_ENV", "development")
from backend.services.db import initialize_database, get_connection
initialize_database()
with get_connection() as conn:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='pdf_analyses'").fetchone()
    print("pdf_analyses table:", "OK" if row else "MISSING")
PY
```

---

## 완료 체크리스트

- [ ] `pypdf` 설치 + `requirements.txt` 추가
- [ ] `extract_pdf_text()` 함수 추가
- [ ] `analyze_strategy_with_llm()` 함수 추가 (LLM 연동 + MAPPABLE_SETTINGS 매핑)
- [ ] `pdf_analyses` DB 테이블 추가
- [ ] `POST /api/v1/expert-knowledge/upload-pdf` 엔드포인트 추가
- [ ] `POST /api/v1/expert-knowledge/apply-strategy/{analysis_id}` 엔드포인트 추가
- [ ] `GET /api/v1/expert-knowledge/analyses` 엔드포인트 추가
- [ ] Expert Knowledge 화면 HTML 재설계
- [ ] JS 함수 추가 (ekUploadPdf, ekRenderResult, ekApplyStrategy, ekReset, ekLoadHistory)
- [ ] showScreen에서 ekLoadHistory() 호출로 교체
- [ ] require_console_user 추가
- [ ] py_compile OK
- [ ] HTML parse OK
- [ ] pypdf import OK
- [ ] pdf_analyses 테이블 생성 확인

결과는 `docs/agent-comm/OUTBOX_EXECUTOR_expert_knowledge_v2.md`에 작성하라.
