  async function loadReviewData() {
    try {
      var data = await fetchJson("/api/v1/trades/history?limit=31");
      var items = (data.payload && data.payload.items) || [];

      var tradeDays = items.length;
      var totalOrders = 0;
      var profitDays = 0;
      var pnlSum = 0;
      items.forEach(function(item) {
        totalOrders += item.total_orders || 0;
        pnlSum += item.realized_pnl_pct || 0;
        if ((item.realized_pnl_pct || 0) > 0) profitDays++;
      });
      var winrate = tradeDays > 0 ? Math.round(profitDays / tradeDays * 100) : 0;

      function setRV(id, text, cls) {
        var el = document.getElementById(id);
        if (el) { el.textContent = text; if (cls) el.className = "metric " + cls; }
      }

      setRV("review-trade-days", tradeDays + "일");
      setRV("review-total-orders", totalOrders + "건");
      var pnlCls = pnlSum >= 0 ? "good" : "bad";
      setRV("review-pnl", (pnlSum >= 0 ? "+" : "") + pnlSum.toFixed(2) + "%", pnlCls);
      setRV("review-winrate", winrate + "%", winrate >= 50 ? "good" : "warn");
      var wrDetail = document.getElementById("review-winrate-detail");
      if (wrDetail) wrDetail.textContent = profitDays + "수익일 / " + tradeDays + "거래일";

      if (items.length > 0) {
        var latest = items[0];
        var summEl = document.getElementById("review-latest-summary");
        var toneEl = document.getElementById("review-latest-tone");
        var rpEl = document.getElementById("review-latest-rulepack");
        if (summEl) summEl.textContent = latest.trade_date + " · 주문 " + (latest.total_orders || 0) + "건 · 손익 " + (latest.realized_pnl_pct || 0).toFixed(2) + "%";
        if (toneEl) toneEl.textContent = latest.market_tone || "(없음)";
        if (rpEl) rpEl.textContent = latest.rulepack_id || "(없음)";
      }

      var tbody = document.getElementById("review-history-tbody");
      if (tbody) {
        if (items.length === 0) {
          tbody.innerHTML = '<tr><td colspan="6" class="muted" style="text-align:center;">데이터 없음: 최근 31일 거래 요약 없음</td></tr>';
        } else {
          tbody.innerHTML = items.map(function(item) {
            var pnl = item.realized_pnl_pct || 0;
            var pnlStr = (pnl >= 0 ? "+" : "") + pnl.toFixed(2) + "%";
            return '<tr style="cursor:pointer;" data-action="showScreen" data-screen="statistics">'
              + '<td>' + (item.trade_date || "") + '</td>'
              + '<td>' + (item.total_orders || 0) + '</td>'
              + '<td>' + (item.buy_orders || 0) + '</td>'
              + '<td>' + (item.sell_orders || 0) + '</td>'
              + '<td class="' + (pnl >= 0 ? "good" : "bad") + '">' + pnlStr + '</td>'
              + '<td>' + escapeHtml(item.market_tone || "-") + '</td>'
              + '</tr>';
          }).join("");
        }
      }
    } catch (e) {
      var tbody3 = document.getElementById("review-history-tbody");
      if (tbody3) tbody3.innerHTML = '<tr><td colspan="6" class="muted">실행 실패: 거래 요약을 불러오지 못했습니다 - ' + escapeHtml(e.message) + '</td></tr>';
    }
  }

  async function runDailySummary() {
    if (!confirm("오늘 거래를 집계하고 DB를 백업할까요? (S10 실행)")) return;
    try {
      await fetchJson("/api/v1/trades/run-summary", { method: "POST" });
      alert("일일 요약 생성 완료. 새로고침합니다.");
      loadReviewData();
    } catch (e) {
      alert("실패: " + e.message);
    }
  }

  // Review & Audit — 데이터 로드
  async function loadReviewAuditData() {
    try {
      const today = new Date().toISOString().slice(0, 10);
      // S10 리뷰 결과
      const reviewRes = await fetch('/api/v1/review-audit/today');
      if (reviewRes.ok) {
        const reviewData = await reviewRes.json();
        const p = reviewData.payload || {};
        if (p.profile_summary) renderProfilePerformance(p.profile_summary);
        if (p.exit_summary) renderExitReason(p.exit_summary);
        if (p.trailing_quality) renderTrailingQuality(p.trailing_quality);
        
        // Update Rule Context if available
        if (p.base_rulepack_ver) document.getElementById('ra-rulepack-ver').textContent = p.base_rulepack_ver;
        if (p.risk_profile_pack_ver) document.getElementById('ra-profile-pack-ver').textContent = p.risk_profile_pack_ver;
        if (p.daily_plan_id) document.getElementById('ra-daily-plan-id').textContent = p.daily_plan_id;
      }
      // S11 메모리 결과
      const memRes = await fetch('/api/v1/learning-memory/today');
      if (memRes.ok) {
        const memData = await memRes.json();
        const memories = memData.payload || [];
        renderLearningMemory(memories);
      }
    } catch (e) {
      console.warn('loadReviewAuditData error', e);
    }
  }

  var _raCurrentReport = null;

  /* Show the Review/Audit empty panel with the operator-facing status category and detail. */
  function setReviewAuditEmptyState(statusText, detailText) {
    var emptyEl = document.getElementById('ra-empty');
    if (!emptyEl) return;
    var statusEl = document.getElementById('ra-empty-status');
    var detailEl = document.getElementById('ra-empty-detail');
    if (statusEl) statusEl.textContent = statusText;
    if (detailEl) detailEl.textContent = detailText;
    emptyEl.style.display = '';
  }

  /* Load today's Review & Audit report and keep the date picker aligned with the selected report date. */
  async function loadReviewAuditScreen() {
    var today = new Date();
    var todayStr = today.getFullYear() + '-' + String(today.getMonth() + 1).padStart(2, '0') + '-' + String(today.getDate()).padStart(2, '0');
    var input = document.getElementById('ra-date-input');
    if (input) input.value = todayStr;
    await loadReviewByDate();
  }

  /* Fetch a Review & Audit report for a specific YYYY-MM-DD date and route empty/error states to the empty panel. */
  async function loadReviewByDate(dateStr) {
    var emptyEl = document.getElementById('ra-empty');
    var reportEl = document.getElementById('ra-report');
    if (emptyEl) emptyEl.style.display = 'none';
    if (reportEl) reportEl.style.display = 'none';

    console.info('[INFO] ReviewAudit - load start', dateStr || 'today');
    try {
      var url = dateStr ? '/api/v1/review-audit/' + encodeURIComponent(dateStr) : '/api/v1/review-audit/today';
      var res = await fetch(url);
      var data = await res.json();
      var report = (data.payload && typeof data.payload === 'object') ? data.payload : null;

      if (!res.ok || !report) {
        _raCurrentReport = null;
        setReviewAuditEmptyState(
          res.ok ? '미수집·대기: S10 Review & Audit 미실행' : '데이터 없음: 해당 날짜 보고서 없음',
          res.ok ? 'Backend audit 기준으로 아직 오늘 S10 결과가 없습니다. 실행 후 DB 원본과 MD 백업이 생성됩니다.' : '선택한 날짜에 저장된 Review/Audit DB 원본 또는 MD 백업이 없습니다.'
        );
        console.warn('[WARN] ReviewAudit - report empty', dateStr || 'today');
        return;
      }

      _raCurrentReport = report;
      // md_content만 있고 DB 보고서 없는 경우: 카드는 숨기고 팝업 직접 오픈 버튼만 표시
      if (!report.trade_date && report.md_content) {
        if (reportEl) {
          reportEl.style.display = '';
          // 요약 카드는 데이터 없음으로 처리
          document.getElementById('ra-report-title') && (document.getElementById('ra-report-title').textContent = dateStr ? new Date(dateStr+'T00:00:00').toLocaleDateString('ko-KR',{month:'long',day:'numeric'}) + ' 시스템 점검 보고서' : '점검 보고서');
          document.getElementById('ra-report-subtitle') && (document.getElementById('ra-report-subtitle').textContent = '수동 작성 MD 파일 — 자세히 보기를 클릭하세요');
        }
      } else {
        renderReviewReport(report);
        if (reportEl) reportEl.style.display = '';
      }
      console.info('[INFO] ReviewAudit - load complete', report.trade_date);
    } catch (e) {
      _raCurrentReport = null;
      setReviewAuditEmptyState('실행 실패: Review/Audit 조회 실패', '서버 응답 또는 네트워크 오류로 감사 보고서를 불러오지 못했습니다: ' + (e.message || 'unknown'));
      console.error('[ERROR] ReviewAudit - load failed', e.message);
    }
  }

  /* Render the selected Review & Audit payload into summary cards and the two performance tables. */
  function renderReviewReport(r) {
    var setEl = function(id, val) {
      var el = document.getElementById(id);
      if (el) el.textContent = val != null ? val : '-';
    };
    var setHtml = function(id, html) {
      var el = document.getElementById(id);
      if (el) el.innerHTML = html;
    };
    var num = function(value, fallback) {
      var parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : (fallback || 0);
    };
    var countOf = function(row) {
      return num(row.total_orders != null ? row.total_orders : (row.trade_count != null ? row.trade_count : row.count), 0);
    };
    var avgPnlOf = function(row) {
      if (row.avg_pnl_pct != null) return num(row.avg_pnl_pct, 0);
      if (row.avg_pnl != null) return num(row.avg_pnl, 0);
      return null;
    };

    var d = new Date(r.trade_date + 'T00:00:00');
    var title = (d.getMonth() + 1) + '월 ' + d.getDate() + '일 시스템 점검 보고서';
    setEl('ra-report-title', title);
    setEl('ra-report-subtitle', '시장톤: ' + (r.market_tone || '-') + ' | RulePack: ' + (r.rulepack_id || '-'));

    setEl('ra-total-orders', num(r.total_orders, r.total_trades || 0) + '건');
    setEl('ra-orders-detail', '매수' + num(r.buy_orders, 0) + ' / 매도' + num(r.sell_orders, 0) + ' / 실패' + num(r.failed_orders, 0));

    var pnl = r.realized_pnl;
    var pnlEl = document.getElementById('ra-pnl');
    if (pnlEl) {
      pnlEl.textContent = pnl != null ? Number(pnl).toLocaleString() + '원' : '-';
      pnlEl.className = 'metric ' + (pnl > 0 ? 'good' : pnl < 0 ? 'bad' : '');
    }
    var pct = r.realized_pnl_pct;
    setEl('ra-pnl-pct', pct != null ? (pct >= 0 ? '+' : '') + Number(pct).toFixed(2) + '%' : '-');

    var exitSummary = r.exit_summary || {};
    var topExit = Object.entries(exitSummary).sort(function(a, b) {
      return num((b[1] || {}).count, 0) - num((a[1] || {}).count, 0);
    })[0];
    setEl('ra-top-exit', topExit ? topExit[0].replace(/_/g, ' ') + ' (' + num((topExit[1] || {}).count, 0) + '건)' : '-');

    var tq = r.trailing_quality || {};
    setEl('ra-trailing', tq.quality_grade || '-');
    setEl('ra-trailing-detail', tq.early_exit_rate != null ? '조기청산 ' + Number(tq.early_exit_rate * 100).toFixed(0) + '%' : '-');

    var profiles = r.profile_performance || [];
    if (profiles.length) {
      setHtml('ra-profile-tbody', profiles.map(function(p) {
        var total = countOf(p);
        var filled = num(p.filled_orders != null ? p.filled_orders : p.win_count, 0);
        var fillRate = total > 0 ? Math.round(filled / total * 100) : 0;
        var avgPnl = avgPnlOf(p);
        var pnlPct = avgPnl != null ? (avgPnl >= 0 ? '+' : '') + Number(avgPnl).toFixed(2) + '%' : '-';
        var color = (avgPnl || 0) >= 0 ? 'var(--green)' : 'var(--red)';
        return '<tr>'
          + '<td><strong>' + escapeHtml(p.profile || '') + '</strong></td>'
          + '<td>' + total + '건</td>'
          + '<td>' + fillRate + '%</td>'
          + '<td style="color:' + color + ';">' + pnlPct + '</td>'
          + '<td>' + escapeHtml(p.evaluation || '-') + '</td>'
          + '</tr>';
      }).join(''));
    } else {
      setHtml('ra-profile-tbody', '<tr><td colspan="5" class="muted" style="text-align:center;">데이터 없음</td></tr>');
    }

    var exits = r.exit_reason_performance || [];
    if (exits.length) {
      setHtml('ra-exit-tbody', exits.map(function(e) {
        var avgPnl = avgPnlOf(e);
        var pnlPct = avgPnl != null ? (avgPnl >= 0 ? '+' : '') + Number(avgPnl).toFixed(2) + '%' : '-';
        var color = (avgPnl || 0) >= 0 ? 'var(--green)' : 'var(--red)';
        return '<tr>'
          + '<td>' + escapeHtml((e.exit_reason || '').replace(/_/g, ' ')) + '</td>'
          + '<td>' + countOf(e) + '건</td>'
          + '<td style="color:' + color + ';">' + pnlPct + '</td>'
          + '</tr>';
      }).join(''));
    } else {
      setHtml('ra-exit-tbody', '<tr><td colspan="3" class="muted" style="text-align:center;">데이터 없음</td></tr>');
    }
  }

  /* Open the Review & Audit detail modal.
     MD 파일이 있으면 그 내용을 우선 표시하고, 없으면 DB 기반 요약 텍스트를 생성한다. */
  function openReviewDetailModal() {
    if (!_raCurrentReport) return;
    var modal = document.getElementById('ra-detail-modal');
    var content = document.getElementById('ra-detail-content');
    var title = document.getElementById('ra-modal-title');
    if (!modal || !content) return;

    var r = _raCurrentReport;
    var d = new Date((r.trade_date || '') + 'T00:00:00');
    var dateLabel = r.trade_date ? ((d.getMonth() + 1) + '월 ' + d.getDate() + '일') : '-';
    if (title) title.textContent = dateLabel + ' 점검 보고서 전문';

    // MD 파일 내용이 있으면 그대로 표시
    if (r.md_content) {
      content.textContent = r.md_content;
      modal.style.display = '';
      return;
    }

    // DB 기반 요약 텍스트 생성 (MD 없을 때 fallback)
    var lines = [];
    var countOf = function(row) {
      var value = row.total_orders != null ? row.total_orders : (row.trade_count != null ? row.trade_count : row.count);
      var parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : 0;
    };
    var avgPnlOf = function(row) {
      var value = row.avg_pnl_pct != null ? row.avg_pnl_pct : row.avg_pnl;
      var parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : null;
    };
    lines.push('===================================');
    lines.push('  ' + dateLabel + ' 시스템 점검 보고서');
    lines.push('  (DB 자동 생성 — 수동 점검 파일 없음)');
    lines.push('===================================');
    lines.push('');
    lines.push('[기본 정보]');
    lines.push('  거래일     : ' + (r.trade_date || '-'));
    lines.push('  시장 톤    : ' + (r.market_tone || '-'));
    lines.push('  RulePack   : ' + (r.rulepack_id || '-'));
    lines.push('');
    lines.push('[주문 요약]');
    lines.push('  총 주문    : ' + (r.total_orders || 0) + '건');
    lines.push('  매수       : ' + (r.buy_orders || 0) + '건');
    lines.push('  매도       : ' + (r.sell_orders || 0) + '건');
    lines.push('  실패       : ' + (r.failed_orders || 0) + '건');
    lines.push('');
    lines.push('[손익]');
    lines.push('  실현 손익  : ' + (r.realized_pnl != null ? Number(r.realized_pnl).toLocaleString() + '원' : '-'));
    lines.push('  손익률     : ' + (r.realized_pnl_pct != null ? (r.realized_pnl_pct >= 0 ? '+' : '') + Number(r.realized_pnl_pct).toFixed(2) + '%' : '-'));
    lines.push('');
    lines.push('[Risk Profile별 성과]');
    var profiles = r.profile_performance || [];
    if (profiles.length) {
      profiles.forEach(function(p) {
        var avgPnl = avgPnlOf(p);
        lines.push('  ' + (p.profile || '-').padEnd(16) + ' | 주문 ' + countOf(p) + '건 | 평균 손익 ' + (avgPnl != null ? (avgPnl >= 0 ? '+' : '') + avgPnl.toFixed(2) + '%' : '-'));
      });
    } else {
      lines.push('  데이터 없음');
    }
    lines.push('');
    lines.push('[청산 사유별 성과]');
    var exits = r.exit_reason_performance || [];
    if (exits.length) {
      exits.forEach(function(e) {
        var avgPnl = avgPnlOf(e);
        lines.push('  ' + (e.exit_reason || '-').replace(/_/g, ' ').padEnd(20) + ' | ' + countOf(e) + '건 | ' + (avgPnl != null ? (avgPnl >= 0 ? '+' : '') + avgPnl.toFixed(2) + '%' : '-'));
      });
    } else {
      lines.push('  데이터 없음');
    }
    lines.push('');
    lines.push('[트레일링 품질]');
    var tq = r.trailing_quality || {};
    lines.push('  등급       : ' + (tq.quality_grade || '-'));
    lines.push('  조기청산율 : ' + (tq.early_exit_rate != null ? (tq.early_exit_rate * 100).toFixed(0) + '%' : '-'));
    lines.push('');
    lines.push('----------------------------------- 끝');

    content.textContent = lines.join('\n');
    modal.style.display = '';
  }

  /* Close the Review & Audit detail modal without mutating the loaded report. */
  function closeReviewDetailModal() {
    var modal = document.getElementById('ra-detail-modal');
    if (modal) modal.style.display = 'none';
  }

  /* Request Review & Audit generation for the selected date, then reload the Review screen state. */
  async function runReviewAudit() {
    console.info('[INFO] ReviewAudit - generate start');
    try {
      var today = new Date();
      var defaultDate = today.getFullYear() + '-' + String(today.getMonth() + 1).padStart(2, '0') + '-' + String(today.getDate()).padStart(2, '0');
      var input = document.getElementById('ra-date-input');
      var targetDate = input && input.value ? input.value : defaultDate;
      await fetch('/api/v1/review-audit/run', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({date: targetDate})});
      await loadReviewByDate(targetDate);
      console.info('[INFO] ReviewAudit - generate complete', targetDate);
    } catch (e) {
      console.error('[ERROR] ReviewAudit - generate failed', e.message);
      alert('생성 실패: ' + e.message);
    }
  }

  function renderProfilePerformance(summary) {
    const tbody = document.getElementById('ra-profile-tbody');
    if (!tbody) return;
    const entries = Object.entries(summary);
    if (!entries.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="muted">데이터 없음</td></tr>';
      return;
    }
    tbody.innerHTML = entries.map(([profile, data]) => {
      const wr = data.win_count && data.trade_count
        ? ((data.win_count / data.trade_count) * 100).toFixed(0) + '%'
        : '—';
      const pnl = data.avg_pnl != null ? (data.avg_pnl * 100).toFixed(2) + '%' : '—';
      return `<tr><td>${profile}</td><td>${data.trade_count || 0}</td><td>${wr}</td><td>${pnl}</td></tr>`;
    }).join('');
  }

  function renderExitReason(summary) {
    const tbody = document.getElementById('ra-exit-tbody');
    if (!tbody) return;
    const entries = Object.entries(summary);
    if (!entries.length) {
      tbody.innerHTML = '<tr><td colspan="3" class="muted">데이터 없음</td></tr>';
      return;
    }
    tbody.innerHTML = entries.map(([reason, data]) => {
      const pnl = data.avg_pnl != null ? (data.avg_pnl * 100).toFixed(2) + '%' : '—';
      return `<tr><td>${reason}</td><td>${data.count || 0}</td><td>${pnl}</td></tr>`;
    }).join('');
  }

  function renderTrailingQuality(tq) {
    const r = document.getElementById('ra-trailing-recovery');
    const e = document.getElementById('ra-trailing-early');
    const c = document.getElementById('ra-trailing-count');
    if (r) r.textContent = tq.avg_recovery_rate != null ? (tq.avg_recovery_rate * 100).toFixed(1) + '%' : '—';
    if (e) e.textContent = tq.early_exit_rate != null ? (tq.early_exit_rate * 100).toFixed(1) + '%' : '—';
    if (c) c.textContent = tq.total_trailing_exits ?? '—';
  }

  function renderLearningMemory(memories) {
    const total = memories.length;
    const auto = memories.filter(m => m.auto_apply_allowed).length;
    const approval = memories.filter(m => m.requires_approval).length;
    const s3 = memories.filter(m => m.scope === 'S3_UNIVERSE_FILTER').length;
    const s4 = memories.filter(m => m.scope === 'S4_HYBRID_SCREENING').length;
    const s5 = memories.filter(m => m.scope === 'S5_DAILY_PLAN').length;

    const setEl = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    setEl('ra-mem-total', total);
    setEl('ra-mem-auto', auto);
    setEl('ra-mem-approval', approval);
    setEl('ra-mem-s3', `S3: ${s3}건`);
    setEl('ra-mem-s4', `S4: ${s4}건`);
    setEl('ra-mem-s5', `S5: ${s5}건`);

    const list = document.getElementById('ra-mem-list');
    if (!list) return;
    if (!total) { list.innerHTML = '<p class="muted">생성된 메모리 없음</p>'; return; }
    list.innerHTML = memories.map(m => `
      <div class="memory-item" style="border-left:3px solid var(--accent);padding:8px 12px;margin-bottom:8px">
        <div><strong>[${m.scope}]</strong> ${m.summary}</div>
        <div class="muted" style="font-size:0.85em">
          auto: ${m.auto_apply_allowed ? 'Yes' : 'No'} |
          approval: ${m.requires_approval ? 'Yes' : 'No'} |
          status: ${m.status}
        </div>
      </div>
    `).join('');
  }

  async function buildLearningMemory() {
    const btn = document.getElementById('ra-build-memory-btn');
    if (btn) { btn.disabled = true; btn.textContent = '생성 중...'; }
    try {
      const res = await fetch('/api/v1/learning-memory/build', { method: 'POST' });
      const data = await res.json();
      if (res.ok && data.ok) {
        showToast('Learning Memory 생성 완료');
        await loadReviewAuditData();
      } else {
        showToast('생성 실패: ' + (data.detail || data.payload?.reason || 'unknown'), 'error');
      }
    } catch (e) {
      showToast('오류: ' + e.message, 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = 'S11 Learning Memory 생성'; }
    }
  }

  async function runTestS11() {
    const result = document.getElementById('test-s11-result');
    if (result) { result.style.display = 'block'; result.textContent = '실행 중...'; }
    try {
      const res = await fetch('/api/v1/learning-memory/build', { method: 'POST' });
      const data = await res.json();
      if (result) result.textContent = JSON.stringify(data.payload || data, null, 2);
    } catch (e) {
      if (result) result.textContent = '오류: ' + e.message;
    }
  }

  /* ── Statistics ── */
