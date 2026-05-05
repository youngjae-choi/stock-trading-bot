# INBOX_EXECUTOR_review_audit_redesign

## 역할
너는 Executor(Codex)다. Review & Audit 화면 재설계 + Confidence Calibration 제거를 수행한다.
완료 후 `docs/agent-comm/OUTBOX_EXECUTOR_review_audit_redesign.md`에 결과를 작성하라.

수정 대상: `backend/static/console.html` 단일 파일
(백엔드 수정 불필요, 기존 API 그대로 사용)

---

## 작업 1 — Review & Audit 화면 재설계

### 개념
기존: 복잡한 테이블 다수
목표: "OO월 OO일 시스템 점검 보고서" — 날짜별 카드 요약 + "자세히 보기" 팝업

기존 API:
- `GET /api/v1/review-audit/today` → 오늘 보고서
- `GET /api/v1/review-audit/{date}` → 특정 날짜 보고서

보고서 payload 주요 필드:
```
trade_date, total_orders, buy_orders, sell_orders, failed_orders,
realized_pnl, realized_pnl_pct, market_tone, rulepack_id,
profile_summary {}, exit_summary {}, trailing_quality {}
profile_performance [], exit_reason_performance []
```

### 섹션 교체 — `id="screen-review"` 전체 교체

```html
<section class="screen" id="screen-review">
  <div class="page-head">
    <div>
      <h1 class="page-title">Review & Audit</h1>
      <p class="page-desc">일별 매매 결과 점검 보고서입니다.</p>
    </div>
    <div style="display:flex; gap:8px; align-items:center;">
      <input type="date" id="ra-date-input" style="padding:5px; border-radius:5px; background:var(--panel-2); color:var(--text); border:1px solid var(--border);" onchange="loadReviewByDate(this.value)">
      <button class="btn" onclick="loadReviewAuditScreen()">오늘</button>
    </div>
  </div>

  <!-- 보고서 없음 상태 -->
  <div id="ra-empty" style="display:none;">
    <div class="card" style="text-align:center; padding:40px;">
      <div class="muted">해당 날짜의 점검 보고서가 없습니다.</div>
      <div class="muted" style="margin-top:8px; font-size:12px;">S10 Review & Audit이 실행되면 보고서가 생성됩니다.</div>
      <button class="btn" style="margin-top:16px;" onclick="runReviewAudit()">지금 생성</button>
    </div>
  </div>

  <!-- 보고서 있음 -->
  <div id="ra-report" style="display:none;">
    <!-- 헤더 -->
    <div class="card" style="margin-bottom:16px; background:var(--panel-2);">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <div>
          <div style="font-size:18px; font-weight:700;" id="ra-report-title">OO월 OO일 시스템 점검 보고서</div>
          <div style="font-size:12px; color:var(--muted); margin-top:4px;" id="ra-report-subtitle">시장톤: - | RulePack: -</div>
        </div>
        <button class="btn" onclick="openReviewDetailModal()">자세히 보기 ↗</button>
      </div>
    </div>

    <!-- 요약 지표 -->
    <div class="grid cols-4" style="margin-bottom:16px;">
      <div class="card compact">
        <div class="card-title">총 주문</div>
        <div class="metric" id="ra-total-orders">-</div>
        <div class="muted" id="ra-orders-detail">매수- / 매도- / 실패-</div>
      </div>
      <div class="card compact">
        <div class="card-title">실현 손익</div>
        <div class="metric" id="ra-pnl">-</div>
        <div class="muted" id="ra-pnl-pct">수익률 -</div>
      </div>
      <div class="card compact">
        <div class="card-title">청산 방식</div>
        <div class="metric" id="ra-top-exit">-</div>
        <div class="muted">가장 많은 청산 사유</div>
      </div>
      <div class="card compact">
        <div class="card-title">트레일링 품질</div>
        <div class="metric" id="ra-trailing">-</div>
        <div class="muted" id="ra-trailing-detail">조기청산율 -</div>
      </div>
    </div>

    <!-- Risk Profile별 성과 -->
    <div class="card" style="margin-bottom:16px;">
      <div class="card-title">Risk Profile별 성과</div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>Profile</th><th>주문수</th><th>체결율</th><th>평균 손익률</th><th>평가</th></tr>
          </thead>
          <tbody id="ra-profile-tbody">
            <tr><td colspan="5" class="muted" style="text-align:center;">데이터 없음</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 청산 사유별 성과 -->
    <div class="card">
      <div class="card-title">청산 사유별 성과</div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>청산 사유</th><th>건수</th><th>평균 손익률</th></tr>
          </thead>
          <tbody id="ra-exit-tbody">
            <tr><td colspan="3" class="muted" style="text-align:center;">데이터 없음</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- 자세히 보기 팝업 -->
  <div id="ra-detail-modal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.7); z-index:1000; overflow:auto; padding:20px;">
    <div style="max-width:800px; margin:0 auto; background:var(--bg); border-radius:12px; padding:24px; position:relative;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
        <div style="font-size:16px; font-weight:700;" id="ra-modal-title">점검 보고서 전문</div>
        <button class="btn" onclick="closeReviewDetailModal()">닫기 ✕</button>
      </div>
      <pre id="ra-detail-content" style="font-size:12px; line-height:1.6; white-space:pre-wrap; color:var(--text); background:var(--panel-2); padding:16px; border-radius:8px; max-height:70vh; overflow-y:auto;"></pre>
    </div>
  </div>
</section>
```

---

## 작업 2 — Review & Audit JS 함수 추가/교체

기존 `loadReviewData()`, `loadReviewAuditData()` 함수 아래에 새 함수를 추가한다.
(기존 함수는 삭제하지 말고 남겨둔다)

```javascript
var _raCurrentReport = null;

async function loadReviewAuditScreen() {
  var today = new Date();
  var todayStr = today.getFullYear() + '-' + String(today.getMonth() + 1).padStart(2, '0') + '-' + String(today.getDate()).padStart(2, '0');
  var input = document.getElementById('ra-date-input');
  if (input) input.value = todayStr;
  await loadReviewByDate(todayStr);
}

async function loadReviewByDate(dateStr) {
  var emptyEl = document.getElementById('ra-empty');
  var reportEl = document.getElementById('ra-report');
  if (emptyEl) emptyEl.style.display = 'none';
  if (reportEl) reportEl.style.display = 'none';

  try {
    var url = dateStr ? '/api/v1/review-audit/' + dateStr : '/api/v1/review-audit/today';
    var res = await fetch(url);
    var data = await res.json();
    var report = data.payload || (data.ok ? data : null);

    if (!report || !report.trade_date) {
      if (emptyEl) emptyEl.style.display = '';
      return;
    }

    _raCurrentReport = report;
    renderReviewReport(report);
    if (reportEl) reportEl.style.display = '';
  } catch (e) {
    if (emptyEl) { emptyEl.style.display = ''; }
  }
}

function renderReviewReport(r) {
  var setEl = function(id, val) { var el = document.getElementById(id); if (el) el.textContent = val != null ? val : '-'; };
  var setHtml = function(id, html) { var el = document.getElementById(id); if (el) el.innerHTML = html; };

  // 날짜 헤더
  var d = new Date(r.trade_date + 'T00:00:00');
  var title = (d.getMonth() + 1) + '월 ' + d.getDate() + '일 시스템 점검 보고서';
  setEl('ra-report-title', title);
  setEl('ra-report-subtitle', '시장톤: ' + (r.market_tone || '-') + ' | RulePack: ' + (r.rulepack_id || '-'));

  // 요약 지표
  setEl('ra-total-orders', (r.total_orders || 0) + '건');
  setEl('ra-orders-detail', '매수' + (r.buy_orders || 0) + ' / 매도' + (r.sell_orders || 0) + ' / 실패' + (r.failed_orders || 0));

  var pnl = r.realized_pnl;
  var pnlEl = document.getElementById('ra-pnl');
  if (pnlEl) {
    pnlEl.textContent = pnl != null ? Number(pnl).toLocaleString() + '원' : '-';
    pnlEl.className = 'metric ' + (pnl > 0 ? 'good' : pnl < 0 ? 'bad' : '');
  }
  var pct = r.realized_pnl_pct;
  setEl('ra-pnl-pct', pct != null ? (pct >= 0 ? '+' : '') + Number(pct).toFixed(2) + '%' : '-');

  // 청산 사유 최다
  var exitSummary = r.exit_summary || {};
  var topExit = Object.entries(exitSummary).sort(function(a, b) { return (b[1] || 0) - (a[1] || 0); })[0];
  setEl('ra-top-exit', topExit ? topExit[0].replace('_', ' ') + ' (' + topExit[1] + ')' : '-');

  // 트레일링 품질
  var tq = r.trailing_quality || {};
  setEl('ra-trailing', tq.quality_grade || '-');
  setEl('ra-trailing-detail', tq.early_exit_rate != null ? '조기청산 ' + Number(tq.early_exit_rate * 100).toFixed(0) + '%' : '-');

  // Profile 테이블
  var profiles = r.profile_performance || [];
  if (profiles.length) {
    setHtml('ra-profile-tbody', profiles.map(function(p) {
      var fillRate = p.total_orders > 0 ? Math.round((p.filled_orders || 0) / p.total_orders * 100) : 0;
      var pnlPct = p.avg_pnl_pct != null ? (p.avg_pnl_pct >= 0 ? '+' : '') + Number(p.avg_pnl_pct).toFixed(2) + '%' : '-';
      var color = (p.avg_pnl_pct || 0) >= 0 ? 'var(--green)' : 'var(--red, #f85149)';
      return '<tr>'
        + '<td><strong>' + escapeHtml(p.profile || '') + '</strong></td>'
        + '<td>' + (p.total_orders || 0) + '건</td>'
        + '<td>' + fillRate + '%</td>'
        + '<td style="color:' + color + ';">' + pnlPct + '</td>'
        + '<td>' + escapeHtml(p.evaluation || '-') + '</td>'
        + '</tr>';
    }).join(''));
  } else {
    setHtml('ra-profile-tbody', '<tr><td colspan="5" class="muted" style="text-align:center;">데이터 없음</td></tr>');
  }

  // Exit reason 테이블
  var exits = r.exit_reason_performance || [];
  if (exits.length) {
    setHtml('ra-exit-tbody', exits.map(function(e) {
      var pnlPct = e.avg_pnl_pct != null ? (e.avg_pnl_pct >= 0 ? '+' : '') + Number(e.avg_pnl_pct).toFixed(2) + '%' : '-';
      var color = (e.avg_pnl_pct || 0) >= 0 ? 'var(--green)' : 'var(--red, #f85149)';
      return '<tr>'
        + '<td>' + escapeHtml((e.exit_reason || '').replace(/_/g, ' ')) + '</td>'
        + '<td>' + (e.count || 0) + '건</td>'
        + '<td style="color:' + color + ';">' + pnlPct + '</td>'
        + '</tr>';
    }).join(''));
  } else {
    setHtml('ra-exit-tbody', '<tr><td colspan="3" class="muted" style="text-align:center;">데이터 없음</td></tr>');
  }
}

function openReviewDetailModal() {
  if (!_raCurrentReport) return;
  var modal = document.getElementById('ra-detail-modal');
  var content = document.getElementById('ra-detail-content');
  var title = document.getElementById('ra-modal-title');
  if (!modal || !content) return;

  var r = _raCurrentReport;
  var d = new Date(r.trade_date + 'T00:00:00');
  if (title) title.textContent = (d.getMonth() + 1) + '월 ' + d.getDate() + '일 점검 보고서 전문';

  // 전문 텍스트 생성
  var lines = [];
  lines.push('═══════════════════════════════════');
  lines.push('  ' + (d.getMonth() + 1) + '월 ' + d.getDate() + '일 시스템 점검 보고서');
  lines.push('═══════════════════════════════════');
  lines.push('');
  lines.push('● 기본 정보');
  lines.push('  거래일     : ' + (r.trade_date || '-'));
  lines.push('  시장 톤    : ' + (r.market_tone || '-'));
  lines.push('  RulePack   : ' + (r.rulepack_id || '-'));
  lines.push('');
  lines.push('● 주문 요약');
  lines.push('  총 주문    : ' + (r.total_orders || 0) + '건');
  lines.push('  매수       : ' + (r.buy_orders || 0) + '건');
  lines.push('  매도       : ' + (r.sell_orders || 0) + '건');
  lines.push('  실패       : ' + (r.failed_orders || 0) + '건');
  lines.push('');
  lines.push('● 손익');
  lines.push('  실현 손익  : ' + (r.realized_pnl != null ? Number(r.realized_pnl).toLocaleString() + '원' : '-'));
  lines.push('  손익률     : ' + (r.realized_pnl_pct != null ? (r.realized_pnl_pct >= 0 ? '+' : '') + Number(r.realized_pnl_pct).toFixed(2) + '%' : '-'));
  lines.push('');
  lines.push('● Risk Profile별 성과');
  var profiles = r.profile_performance || [];
  if (profiles.length) {
    profiles.forEach(function(p) {
      lines.push('  ' + (p.profile || '-').padEnd(16) + ' | 주문 ' + (p.total_orders || 0) + '건 | 평균 손익 ' + (p.avg_pnl_pct != null ? (p.avg_pnl_pct >= 0 ? '+' : '') + Number(p.avg_pnl_pct).toFixed(2) + '%' : '-'));
    });
  } else {
    lines.push('  데이터 없음');
  }
  lines.push('');
  lines.push('● 청산 사유별 성과');
  var exits = r.exit_reason_performance || [];
  if (exits.length) {
    exits.forEach(function(e) {
      lines.push('  ' + (e.exit_reason || '-').replace(/_/g, ' ').padEnd(20) + ' | ' + (e.count || 0) + '건 | ' + (e.avg_pnl_pct != null ? (e.avg_pnl_pct >= 0 ? '+' : '') + Number(e.avg_pnl_pct).toFixed(2) + '%' : '-'));
    });
  } else {
    lines.push('  데이터 없음');
  }
  lines.push('');
  lines.push('● 트레일링 품질');
  var tq = r.trailing_quality || {};
  lines.push('  등급       : ' + (tq.quality_grade || '-'));
  lines.push('  조기청산율 : ' + (tq.early_exit_rate != null ? (tq.early_exit_rate * 100).toFixed(0) + '%' : '-'));
  lines.push('');
  lines.push('─────────────────────────────────── 끝');

  content.textContent = lines.join('\n');
  modal.style.display = '';
}

function closeReviewDetailModal() {
  var modal = document.getElementById('ra-detail-modal');
  if (modal) modal.style.display = 'none';
}

async function runReviewAudit() {
  try {
    var today = new Date();
    var todayStr = today.getFullYear() + '-' + String(today.getMonth() + 1).padStart(2, '0') + '-' + String(today.getDate()).padStart(2, '0');
    await fetch('/api/v1/review-audit/run', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({date: todayStr})});
    await loadReviewAuditScreen();
  } catch (e) {
    alert('생성 실패: ' + e.message);
  }
}
```

---

## 작업 3 — showScreen 진입 핸들러 수정

`showScreen()` 내에서 `name === "review"` 분기를 찾아:

**현재:**
```javascript
if (name === "review") {
  loadReviewData();
  loadReviewAuditData();
}
```

**수정 후:**
```javascript
if (name === "review") {
  loadReviewAuditScreen();
}
```

---

## 작업 4 — Confidence Calibration 메뉴 숨김

사이드바와 모바일 메뉴에서 Confidence Cal. 항목을 숨긴다:

```html
<!-- 사이드바 -->
<button data-screen="confidence-cal" style="display:none">Confidence Cal. <small>conf-cal</small></button>

<!-- 모바일 -->
<option value="confidence-cal" style="display:none">Confidence Cal.</option>
```

기존 `screen-confidence-cal` 섹션과 JS 함수는 **삭제하지 말고 그대로 유지**한다.
(나중에 통계 화면 만들 때 재활용)

---

## 검증

```bash
python3 -c "
from html.parser import HTMLParser
with open('backend/static/console.html', encoding='utf-8') as f:
    HTMLParser().feed(f.read())
print('HTML parse OK')
"

echo "=== confidence-cal 버튼 숨김 확인 ==="
grep 'data-screen="confidence-cal"' backend/static/console.html

echo "=== ra-report-title 존재 확인 ==="
grep -c "ra-report-title" backend/static/console.html

echo "=== ra-detail-modal 존재 확인 ==="
grep -c "ra-detail-modal" backend/static/console.html
```

---

## 완료 체크리스트

- [ ] `screen-review` 화면 재설계 (날짜 선택 + 요약 카드 + 상세 팝업)
- [ ] `loadReviewAuditScreen()`, `loadReviewByDate()`, `renderReviewReport()` 추가
- [ ] `openReviewDetailModal()`, `closeReviewDetailModal()` 추가
- [ ] `runReviewAudit()` 추가
- [ ] showScreen "review" 분기 → `loadReviewAuditScreen()` 호출
- [ ] Confidence Cal. 사이드바/모바일 숨김 (섹션/함수는 유지)
- [ ] HTML parse OK

결과는 `docs/agent-comm/OUTBOX_EXECUTOR_review_audit_redesign.md`에 작성하라.
