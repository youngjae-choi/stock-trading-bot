  async function loadDataHealth() {
    try {
      var r = await fetchJson("/api/v1/bot/data-health");
      var m = (r.payload && r.payload.metrics) ? r.payload.metrics : {};

      function applyMetricCard(idVal, idDetail, key) {
        var s = m[key] || {};
        var el = document.getElementById(idVal);
        var eld = document.getElementById(idDetail);
        var status = s.status || "info";
        if (el) {
          el.textContent = status === "ok" ? "정상" : status === "warn" ? "주의" : "미구현";
          el.className = "metric " + (status === "ok" ? "good" : status === "warn" ? "warn" : "info");
        }
        if (eld) {
          eld.textContent = s.detail || "-";
        }
      }

      applyMetricCard("dh-kisRest", "dh-kisRestDetail", "kis_rest");
      applyMetricCard("dh-kisWs", "dh-kisWsDetail", "kis_ws");
      applyMetricCard("dh-llm", "dh-llmDetail", "llm_router");
      applyMetricCard("dh-db", "dh-dbDetail", "db");
      var skipMetric = m.schedule_skip || {};
      var skipStatus = document.getElementById("scheduleSkipStatus");
      var skipDetail = document.getElementById("scheduleSkipDetail");
      if (skipStatus) {
        var skipWarn = skipMetric.status === "warn";
        skipStatus.textContent = skipWarn ? "스킵 가능" : "정상";
        skipStatus.className = "status " + (skipWarn ? "warn" : "ok");
      }
      if (skipDetail) skipDetail.textContent = skipMetric.detail || "schedule_skip_today=false";
    } catch(e) {
      console.warn("loadDataHealth error", e);
    }

    try {
      var r2 = await fetchJson("/api/v1/market-tone/providers");
      var providers = (r2.payload && r2.payload.providers) ? r2.payload.providers : (Array.isArray(r2.payload) ? r2.payload : []);
      var tbody = document.getElementById("llmProvidersTableBody");
      if (tbody) {
        if (providers.length === 0) {
          tbody.innerHTML = "<tr><td colspan='4' class='muted'>Provider 없음</td></tr>";
        } else {
          tbody.innerHTML = providers.map(function(p) {
            var statusCls = p.enabled ? "ok" : "warn";
            var statusTxt = p.enabled ? "활성" : "비활성";
            return '<tr>'
              + '<td>' + escapeHtml(p.name || "-") + '</td>'
              + '<td>' + escapeHtml(p.role || "-") + '</td>'
              + '<td>' + escapeHtml(p.model || "-") + '</td>'
              + '<td><span class="status ' + statusCls + '">' + statusTxt + '</span></td>'
              + '</tr>';
          }).join("");
        }
      }
    } catch (e) {
      console.warn("loadDataHealth providers error", e);
      var tbody2 = document.getElementById("llmProvidersTableBody");
      if (tbody2) tbody2.innerHTML = '<tr><td colspan="4" class="muted">불러오기 실패: ' + escapeHtml(e.message) + '</td></tr>';
    }

    var telegramEl = document.getElementById('telegram-status');
    if (telegramEl) {
      telegramEl.textContent = '활성';
      telegramEl.className = 'status ok';
    }
  }

  /* ── Funnel Monitor ── */
  async function loadFunnelMemoryCounts() {
    const scopes = [
      { id: 'funnel-mem-s3', path: '/api/v1/pipeline/S3/context-preview' },
      { id: 'funnel-mem-s4', path: '/api/v1/pipeline/S4/context-preview' },
      { id: 'funnel-mem-s5', path: '/api/v1/pipeline/S5/context-preview' },
    ];
    for (const { id, path } of scopes) {
      try {
        const res = await fetch(path);
        if (res.ok) {
          const data = await res.json();
          const el = document.getElementById(id);
          if (el) el.textContent = (data.payload && data.payload.count) != null ? data.payload.count : 0;
        }
      } catch (_) {}
    }
  }

  /* Return the canonical stock code used by Funnel candidate and assignment payloads. */
  function funnelSymbolKey(item) {
    return item ? (item.symbol || item.ticker || item.code || '') : '';
  }

  /* Update Layer 1 rejection details without inventing unavailable breakdowns. */
  function renderFunnelLayer1Breakdown(summary) {
    var tbody = document.getElementById('funnel-layer1-reasons-tbody');
    if (!tbody) return;
    var breakdown = summary.layer1_rejection_breakdown || [];
    if (Array.isArray(breakdown) && breakdown.length > 0) {
      tbody.innerHTML = breakdown.map(function(row) {
        return '<tr>'
          + '<td>' + escapeHtml(row.condition || '-') + '</td>'
          + '<td>' + escapeHtml(String(row.count != null ? row.count : '-')) + '</td>'
          + '<td>' + escapeHtml(row.ratio || '-') + '</td>'
          + '<td><span class="status info">' + escapeHtml(row.status || '집계') + '</span></td>'
          + '</tr>';
      }).join('');
      return;
    }
    var rejected = summary.layer1_rejected != null ? summary.layer1_rejected.toLocaleString() : '-';
    tbody.innerHTML = '<tr>'
      + '<td>탈락 사유 상세 집계 없음</td>'
      + '<td>' + rejected + '</td>'
      + '<td>-</td>'
      + '<td><span class="status info">S3 breakdown 미수집</span></td>'
      + '</tr>';
  }

  /* Render Funnel quality from known persisted state only. */
  function renderFunnelQuality(summary) {
    var strengthStatus = document.getElementById('funnel-quality-strength-status');
    var strengthDetail = document.getElementById('funnel-quality-strength-detail');
    var anomalyStatus = document.getElementById('funnel-quality-anomaly-status');
    var anomalyDetail = document.getElementById('funnel-quality-anomaly-detail');
    if (summary.has_s3 && summary.layer1_count === 0) {
      if (strengthStatus) strengthStatus.textContent = '후보 없음';
      if (strengthDetail) strengthDetail.textContent = '후보 없음: S3 통과 0';
      if (anomalyStatus) anomalyStatus.textContent = '후속 미생성';
      if (anomalyDetail) anomalyDetail.textContent = summary.empty_reason || 'S3 통과 종목이 없어 S4/S5가 생성되지 않았습니다.';
      return;
    }
    if (strengthStatus) strengthStatus.textContent = summary.has_s3 ? 'DB 기준 표시' : 'S3 없음';
    if (strengthDetail) strengthDetail.textContent = '최근 N거래일 품질 집계 미구현: 오늘 저장된 Funnel 결과만 표시합니다.';
    if (anomalyStatus) anomalyStatus.textContent = summary.empty_reason ? '확인 필요' : '저장 결과 기준';
    if (anomalyDetail) anomalyDetail.textContent = summary.empty_reason || '정적 품질 문구를 제거하고 DB 결과만 표시 중입니다.';
  }

  async function loadFunnelData() {
    loadFunnelMemoryCounts();
    // Load Daily Plan profile assignments
    var assignments = [];
    try {
      var rp = await fetch('/api/v1/daily-plan/today');
      var dp = await rp.json();
      assignments = dp.payload && dp.payload.symbol_assignments ? dp.payload.symbol_assignments : [];
      var counts = {LOW_VOL:0, MID_VOL:0, HIGH_VOL:0, THEME_SPIKE:0};
      assignments.forEach(function(a) { if (counts[a.profile] !== undefined) counts[a.profile]++; });
      var el;
      el = document.getElementById('fn-low-count'); if (el) el.textContent = counts.LOW_VOL;
      el = document.getElementById('fn-mid-count'); if (el) el.textContent = counts.MID_VOL;
      el = document.getElementById('fn-high-count'); if (el) el.textContent = counts.HIGH_VOL;
      el = document.getElementById('fn-spike-count'); if (el) el.textContent = counts.THEME_SPIKE;
    } catch(e) {}

    try {
      var funnelSummary = await fetchJson("/api/v1/funnel/summary");
      if (funnelSummary.ok && funnelSummary.payload) {
        var fp = funnelSummary.payload;
        var totalEl = document.getElementById("funnel-total");
        var l1El = document.getElementById("funnel-layer1");
        var l2El2 = document.getElementById("funnel-layer2");
        var candEl2 = document.getElementById("funnel-candidates");
        var totalSourceEl = document.getElementById("funnel-total-source");
        var l1DetailEl = document.getElementById("funnel-layer1-detail");
        var l2DetailEl = document.getElementById("funnel-layer2-detail");
        var emptyReasonEl = document.getElementById("funnel-empty-reason");
        var lastUpdatedEl = document.getElementById("funnel-last-updated");
        if (totalEl) totalEl.textContent = fp.total_universe != null ? fp.total_universe.toLocaleString() : "-";
        if (totalSourceEl) totalSourceEl.textContent = fp.total_universe_source || "출처 미확인";
        if (l1El) l1El.textContent = fp.layer1_count != null ? fp.layer1_count.toLocaleString() : "-";
        if (l1DetailEl) l1DetailEl.textContent = "raw " + (fp.layer1_raw != null ? fp.layer1_raw.toLocaleString() : "-") + " / 탈락 " + (fp.layer1_rejected != null ? fp.layer1_rejected.toLocaleString() : "-");
        if (l2El2 && fp.layer2_count != null) l2El2.textContent = fp.layer2_count.toLocaleString();
        if (l2DetailEl) l2DetailEl.textContent = (fp.has_s4 ? "S4 결과 있음" : "S4 결과 없음") + " / " + (fp.has_s5 ? "S5 결과 있음" : "S5 결과 없음");
        if (candEl2 && fp.signals_count != null) candEl2.textContent = fp.signals_count;
        if (emptyReasonEl) {
          emptyReasonEl.textContent = fp.empty_reason || "";
          emptyReasonEl.style.display = fp.empty_reason ? "block" : "none";
        }
        if (lastUpdatedEl) lastUpdatedEl.textContent = fp.last_updated_at ? "마지막 Funnel 결과 시각: " + fp.last_updated_at : "오늘 저장된 Funnel 결과 시각 없음";
        renderFunnelLayer1Breakdown(fp);
        renderFunnelQuality(fp);
        // Risk Profile별 배정 수
        var pc = fp.profile_counts || {};
        var setPC = function(id, key) { var el = document.getElementById(id); if (el) el.textContent = pc[key] || 0; };
        setPC('fn-low-count', 'LOW_VOL');
        setPC('fn-mid-count', 'MID_VOL');
        setPC('fn-high-count', 'HIGH_VOL');
        setPC('fn-spike-count', 'THEME_SPIKE');
      }
    } catch (e) { /* ignore funnel summary fail */ }

    try {
      var screenData = await fetchJson("/api/v1/screening/today");
      var sc = screenData.payload && screenData.payload.screening;
      if (sc) {
        var l2El = document.getElementById("funnel-layer2");
        var candEl = document.getElementById("funnel-candidates");
        if (l2El) l2El.textContent = sc.output_count != null ? sc.output_count : "-";
        if (candEl) candEl.textContent = sc.output_count != null ? sc.output_count : "-";

        var tbody = document.getElementById("funnel-candidates-tbody");
        var candidates = sc.candidates;
        if (tbody && Array.isArray(candidates) && candidates.length > 0) {
          tbody.innerHTML = candidates.map(function(c) {
            var score = c.suitability_score != null ? c.suitability_score.toFixed(2) : "-";
            var conf = c.confidence != null ? c.confidence.toFixed(2) : "-";
            var candidateSymbol = funnelSymbolKey(c);
            var asgn = assignments.find(function(a) { return funnelSymbolKey(a) === candidateSymbol; });
            var profileName = asgn ? asgn.profile : "-";
            var profileReason = asgn ? asgn.reason : "-";
            var memRefs = (c.memory_refs || []).join(', ') || '-';

            return '<tr>'
              + '<td>' + escapeHtml(candidateSymbol) + '</td>'
              + '<td>' + escapeHtml(c.name || "") + '</td>'
              + '<td>' + score + '</td>'
              + '<td>-</td><td>-</td>'
              + '<td>' + score + '</td>'
              + '<td>' + conf + '</td>'
              + '<td><span class="status info">감시중</span></td>'
              + '<td>' + escapeHtml(c.reason || "") + '</td>'
              + '<td>' + escapeHtml(profileName) + '</td>'
              + '<td>' + escapeHtml(profileReason) + '</td>'
              + '<td style="font-size:0.8em;color:var(--accent)">' + escapeHtml(memRefs) + '</td>'
              + '</tr>';
          }).join("");
        } else if (tbody && sc.output_count === 0) {
          tbody.innerHTML = '<tr><td colspan="12" class="muted" style="text-align:center;">오늘 스크리닝 후보 없음</td></tr>';
        }
      }
    } catch (e) {
      var tbody2 = document.getElementById("funnel-candidates-tbody");
      if (tbody2) tbody2.innerHTML = '<tr><td colspan="12" class="muted">불러오기 실패: ' + escapeHtml(e.message) + '</td></tr>';
    }
  }

  /* ── Execution & Risk ── */
