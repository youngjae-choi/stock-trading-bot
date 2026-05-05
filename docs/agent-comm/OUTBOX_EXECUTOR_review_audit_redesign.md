# OUTBOX_EXECUTOR_review_audit_redesign

## 작업 결과

- `backend/static/console.html`의 `screen-review` 섹션을 날짜 선택 기반 일별 점검 보고서 UI로 교체했다.
- 보고서 없음 상태(`ra-empty`), 보고서 요약 상태(`ra-report`), 상세 전문 팝업(`ra-detail-modal`)을 추가했다.
- 기존 `loadReviewData()`, `loadReviewAuditData()` 함수는 삭제하지 않고 유지했다.
- 새 Review & Audit 로더/렌더러 함수를 추가했다.
  - `loadReviewAuditScreen()`
  - `loadReviewByDate(dateStr)`
  - `renderReviewReport(r)`
  - `openReviewDetailModal()`
  - `closeReviewDetailModal()`
  - `runReviewAudit()`
- `showScreen("review")` 진입 시 기존 `loadReviewData()` + `loadReviewAuditData()` 대신 `loadReviewAuditScreen()`만 호출하도록 변경했다.
- Confidence Calibration 사이드바 버튼과 모바일 옵션을 `display:none`으로 숨겼다.
- `screen-confidence-cal` 섹션과 관련 JS 함수는 삭제하지 않고 유지했다.

## 변경 파일

- `backend/static/console.html`
- `docs/agent-comm/OUTBOX_EXECUTOR_review_audit_redesign.md`

## 검증 결과

```bash
python3 -c "
from html.parser import HTMLParser
with open('backend/static/console.html', encoding='utf-8') as f:
    HTMLParser().feed(f.read())
print('HTML parse OK')
"
```

결과: `HTML parse OK`

```bash
grep 'data-screen="confidence-cal"' backend/static/console.html
```

결과: 사이드바 버튼에 `style="display:none"` 적용 확인

```bash
grep -c "ra-report-title" backend/static/console.html
grep -c "ra-detail-modal" backend/static/console.html
```

결과:
- `ra-report-title`: `2`
- `ra-detail-modal`: `3`

추가 검증:

```bash
node - <<'NODE'
const fs = require('fs');
const html = fs.readFileSync('backend/static/console.html', 'utf8');
const scripts = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/gi)].map(m => m[1]);
for (const [i, script] of scripts.entries()) {
  new Function(script);
  console.log(`script ${i + 1} syntax OK`);
}
NODE
```

결과: `script 1 syntax OK`

## 완료 체크리스트

- [x] `screen-review` 화면 재설계 (날짜 선택 + 요약 카드 + 상세 팝업)
- [x] `loadReviewAuditScreen()`, `loadReviewByDate()`, `renderReviewReport()` 추가
- [x] `openReviewDetailModal()`, `closeReviewDetailModal()` 추가
- [x] `runReviewAudit()` 추가
- [x] `showScreen`의 `review` 분기에서 `loadReviewAuditScreen()` 호출
- [x] Confidence Cal. 사이드바/모바일 숨김
- [x] 기존 `screen-confidence-cal` 섹션/JS 유지
- [x] HTML parse OK

## 확인 필요

- 실제 `/api/v1/review-audit/today`, `/api/v1/review-audit/{date}`, `/api/v1/review-audit/run` 응답을 사용하는 브라우저 동작 확인은 수행하지 않았다.
- 현재 작업 전부터 `backend/static/console.html`에는 다른 변경사항이 포함된 상태였으므로, 이번 작업은 요청 범위인 Review & Audit 및 Confidence Cal. 숨김에 한정했다.
