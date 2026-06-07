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
          el.textContent = status === "ok" ? "정상" : status === "warn" ? "주의" : "미수집";
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

  /* ISO timestamp → HH:MM (KST) */
  function _toHHMM(isoStr) {
    if (!isoStr) return '-';
    try {
      var d = new Date(isoStr);
      return d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Seoul' });
    } catch (e) { return '-'; }
  }

  /* 장중 재선별 이력 렌더링 */
  function renderIntradayRefreshHistory(history) {
    var tbody = document.getElementById('funnel-intraday-tbody');
    if (!tbody) return;
    var allSlots = ['09:30', '10:30', '11:30'];
    var logMap = {};
    (history || []).forEach(function(h) { if (h.slot) logMap[h.slot] = h; });
    var rows = allSlots.map(function(slot) {
      var h = logMap[slot];
      if (!h) {
        return '<tr><td>' + escapeHtml(slot) + '</td><td><span class="status info">미실행</span></td><td>-</td><td style="text-align:left; color:var(--muted);">-</td><td style="text-align:right;">-</td></tr>';
      }
      var ranBadge = h.ran ? '<span class="status ok">실행</span>' : '<span class="status info">미실행</span>';
      var trigBadge = h.triggered ? '<span class="status warn">재선별</span>' : '<span style="color:var(--muted);">-</span>';
      var avg = h.avg_change != null ? (h.avg_change >= 0 ? '+' : '') + h.avg_change.toFixed(2) + '%' : '-';
      var reason = escapeHtml(h.reason || '-');
      return '<tr>'
        + '<td style="font-weight:600;">' + escapeHtml(slot) + '</td>'
        + '<td>' + ranBadge + '</td>'
        + '<td>' + trigBadge + '</td>'
        + '<td style="text-align:left; font-size:11px; color:var(--muted);">' + reason + '</td>'
        + '<td style="text-align:right; font-size:12px;">' + escapeHtml(avg) + '</td>'
        + '</tr>';
    }).join('');
    tbody.innerHTML = rows;
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
      + '<td>데이터 없음: 탈락 사유 상세 집계 없음</td>'
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
      if (anomalyStatus) anomalyStatus.textContent = '후속 미수집';
      if (anomalyDetail) anomalyDetail.textContent = summary.empty_reason || 'S3 통과 종목이 없어 S4/S5가 생성되지 않았습니다.';
      return;
    }
    if (strengthStatus) strengthStatus.textContent = summary.has_s3 ? 'DB 기준 표시' : 'S3 없음';
    if (strengthDetail) strengthDetail.textContent = '최근 N거래일 품질 집계 미수집: 오늘 저장된 Funnel 결과만 표시합니다.';
    if (anomalyStatus) anomalyStatus.textContent = summary.empty_reason ? '확인 필요' : '저장 결과 기준';
    if (anomalyDetail) anomalyDetail.textContent = summary.empty_reason || '정적 품질 문구를 제거하고 DB 결과만 표시 중입니다.';
  }

  async function loadFunnelData() {
    loadFunnelMemoryCounts();
    loadSelectionFunnel(window._tcTradeDate || null);
    // 신규: Funnel Monitor에 통합된 장중 재선별 v2 카드 갱신
    try {
      var td = window._tcTradeDate || null;
      if (typeof loadIntradayReselectionTimeline === "function") loadIntradayReselectionTimeline(td);
      if (typeof loadReplacementSignals === "function") loadReplacementSignals(td);
      if (typeof loadIntradayKillSwitches === "function") loadIntradayKillSwitches();
    } catch (e) { console.warn("intraday v2 refresh failed", e); }
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
        if (totalEl) totalEl.textContent = (fp.total_universe != null && fp.total_universe > 0) ? fp.total_universe.toLocaleString() : "-";
        if (totalSourceEl) totalSourceEl.textContent = fp.total_universe_source || "출처 미확인";
        if (l1El) l1El.textContent = fp.layer1_count != null ? fp.layer1_count.toLocaleString() : "-";
        if (l1DetailEl) l1DetailEl.textContent = "raw " + (fp.layer1_raw != null ? fp.layer1_raw.toLocaleString() : "-") + " / 탈락 " + (fp.layer1_rejected != null ? fp.layer1_rejected.toLocaleString() : "-");
        if (l2El2 && fp.layer2_count != null) l2El2.textContent = fp.layer2_count.toLocaleString();
        if (l2DetailEl) l2DetailEl.textContent = (fp.has_s4 ? "S4 결과 있음" : "S4 결과 없음") + " / " + (fp.has_s5 ? "S5 결과 있음" : "S5 결과 없음");
        if (candEl2 && fp.signals_count != null) candEl2.textContent = fp.signals_count;
        var candDetailEl = document.getElementById('funnel-candidates-detail');
        if (candDetailEl) candDetailEl.textContent = fp.signals_count > 0 ? 'S4 원본 BUY 신호 수 (Daily Plan 배정 전)' : '데이터 없음: 오늘 BUY 신호 없음';
        if (emptyReasonEl) {
          emptyReasonEl.textContent = fp.empty_reason || "";
          emptyReasonEl.style.display = fp.empty_reason ? "block" : "none";
        }
        if (lastUpdatedEl) lastUpdatedEl.textContent = fp.last_updated_at ? "마지막 Funnel 결과 시각: " + fp.last_updated_at : "오늘 저장된 Funnel 결과 시각 없음";
        renderFunnelLayer1Breakdown(fp);
        renderFunnelQuality(fp);
        renderIntradayRefreshHistory(fp.intraday_refresh_history || []);
        // Risk Profile별 배정 수
        var pc = fp.profile_counts || {};
        var setPC = function(id, key) { var el = document.getElementById(id); if (el) el.textContent = pc[key] || 0; };
        setPC('fn-low-count', 'LOW_VOL');
        setPC('fn-mid-count', 'MID_VOL');
        setPC('fn-high-count', 'HIGH_VOL');
        setPC('fn-spike-count', 'THEME_SPIKE');
      }
    } catch (e) {
      var emptyReasonEl2 = document.getElementById('funnel-empty-reason');
      if (emptyReasonEl2) {
        emptyReasonEl2.textContent = '실행 실패: Funnel summary 조회 실패 - ' + (e.message || 'unknown');
        emptyReasonEl2.style.display = 'block';
      }
    }

    try {
      var screenData = await fetchJson("/api/v1/screening/today");
      var sc = screenData.payload && screenData.payload.screening;
      if (sc) {
        var l2El = document.getElementById("funnel-layer2");
        var candEl = document.getElementById("funnel-candidates");
        if (l2El) l2El.textContent = sc.output_count != null ? sc.output_count : "-";
        if (candEl) candEl.textContent = sc.output_count != null ? sc.output_count : "-";

        var tbody = document.getElementById("funnel-candidates-tbody");
        var batchTime = _toHHMM(sc.created_at);  // S4 배치 실행 시각
        var candidates = sc.candidates;
        if (tbody && Array.isArray(candidates) && candidates.length > 0) {
          tbody.innerHTML = candidates.map(function(c) {
            var score = c.suitability_score != null ? c.suitability_score.toFixed(2) : "-";
            var candidateSymbol = funnelSymbolKey(c);
            var asgn = assignments.find(function(a) { return funnelSymbolKey(a) === candidateSymbol; });
            var profileName = asgn ? asgn.profile : "-";
            var profileReason = asgn ? asgn.reason : "-";
            var memRefs = (c.memory_refs || []).join(', ') || '-';

            // AI 신뢰도(conf) 컬럼은 2026-06-01에 게이트에서 제거되어 표시도 제외.
            return '<tr>'
              + '<td>' + escapeHtml(candidateSymbol) + '</td>'
              + '<td>' + escapeHtml(c.name || "") + '</td>'
              + '<td>' + score + '</td>'
              + '<td>-</td><td>-</td>'
              + '<td>' + score + '</td>'
              + '<td style="font-size:12px; color:var(--accent); text-align:center;">' + escapeHtml(batchTime) + '</td>'
              + '<td><span class="status info">감시중</span></td>'
              + '<td>' + escapeHtml(c.reason || "") + '</td>'
              + '<td>' + escapeHtml(profileName) + '</td>'
              + '<td>' + escapeHtml(profileReason) + '</td>'
              + '<td style="font-size:0.8em;color:var(--accent)">' + escapeHtml(memRefs) + '</td>'
              + '</tr>';
          }).join("");
        } else if (tbody && sc.output_count === 0) {
          tbody.innerHTML = '<tr><td colspan="12" class="muted" style="text-align:center;">데이터 없음: 오늘 스크리닝 통과 후보 없음</td></tr>';
        }
      }
    } catch (e) {
      var tbody2 = document.getElementById("funnel-candidates-tbody");
      if (tbody2) tbody2.innerHTML = '<tr><td colspan="12" class="muted">실행 실패: 후보 선정 결과 조회 실패 - ' + escapeHtml(e.message) + '</td></tr>';
    }
  }

  /* ── 선정 퍼널: 단계별 통과/탈락 종목 (PM 핵심 요청) ── */
  async function loadSelectionFunnel(tradeDate) {
    var box = document.getElementById('funnel-selection');
    if (!box) return;
    try {
      var url = '/api/v1/funnel/selection' + (tradeDate ? ('?trade_date=' + encodeURIComponent(tradeDate)) : '');
      var r = await fetchJson(url);
      var stages = (r && r.payload && r.payload.stages) || [];
      box.innerHTML = renderSelectionFunnel(stages);
      box.querySelectorAll('.sel-stage--expandable .sel-stage__head').forEach(function (h) {
        h.addEventListener('click', function () { h.parentNode.classList.toggle('open'); });
      });
    } catch (e) {
      box.innerHTML = '<div class="muted" style="padding:12px;">선정 퍼널 로드 실패: ' + escapeHtml(e.message) + '</div>';
    }
  }

  function _selItem(it, metaFn) {
    var name = escapeHtml(it.name || '-');
    var code = it.symbol ? '<span class="sel-item__code">' + escapeHtml(it.symbol) + '</span>' : '';
    var metaTxt = metaFn ? metaFn(it) : '';
    var meta = metaTxt ? '<span class="sel-item__meta">' + escapeHtml(metaTxt) + '</span>' : '';
    var reason = it.reason ? '<div class="sel-item__reason">' + escapeHtml(it.reason) + '</div>' : '';
    var badge = (it.selection_source === 'quant_topup')
      ? '<span class="sel-badge-topup" title="LLM이 보류/탈락시켰으나 정량(거래량·TSI) top-up으로 재포함된 종목. 추후 성과(EV)로 강화/제거 판단.">top-up</span>'
      : '';
    return '<div class="sel-item">' + meta + '<span class="sel-item__name">' + name + '</span>' + code + badge + reason + '</div>';
  }

  function _selList(title, cls, items, metaFn) {
    items = items || [];
    var head = '<div class="sel-list__title ' + cls + '">' + title + ' (' + items.length + ')</div>';
    if (!items.length) return '<div>' + head + '<div class="muted" style="font-size:11px;">없음</div></div>';
    var rows = items.map(function (it) { return _selItem(it, metaFn); }).join('');
    return '<div>' + head + '<div class="sel-list">' + rows + '</div></div>';
  }

  function renderSelectionFunnel(stages) {
    if (!stages.length) return '<div class="muted" style="padding:12px;">오늘 선정 데이터가 아직 없습니다.</div>';
    var html = '';
    stages.forEach(function (s, idx) {
      var passN = s.passed_count != null ? s.passed_count : (s.passed ? s.passed.length : 0);
      var dropN = s.dropped_count != null ? s.dropped_count : (s.dropped ? s.dropped.length : 0);
      var expandable = (s.id !== 'raw') && (((s.passed || []).length) || ((s.dropped || []).length));
      var sub = s.subtitle ? '<span class="sel-stage__sub">' + escapeHtml(s.subtitle) + '</span>' : '';
      var counts;
      if (s.id === 'raw') {
        counts = '<span class="sel-pass-n">' + passN + '</span>';
      } else {
        counts = '<span class="sel-pass-n">통과 ' + passN + '</span>'
               + '<span class="sel-drop-n">탈락 ' + dropN + '</span>'
               + (expandable ? '<span class="sel-caret">▶</span>' : '');
      }
      html += '<div class="sel-stage' + (expandable ? ' sel-stage--expandable' : '') + '">'
        + '<div class="sel-stage__head">'
        + '<div><span class="sel-stage__label">' + escapeHtml(s.label) + '</span>' + sub + '</div>'
        + '<div class="sel-stage__counts">' + counts + '</div>'
        + '</div>';
      if (expandable) {
        var passMeta = null;
        if (s.id === 's3') passMeta = function (it) { return (it.score != null ? '점수 ' + it.score : '') + (it.rank != null ? ' · #' + it.rank : ''); };
        else if (s.id === 's4') passMeta = function (it) { return it.score != null ? '적합 ' + it.score : ''; };
        else if (s.id === 's5') passMeta = function (it) { return it.profile || ''; };
        html += '<div class="sel-stage__body"><div class="sel-cols">'
          + _selList('통과', 'pass', s.passed, passMeta)
          + _selList('탈락', 'drop', s.dropped, null)
          + '</div></div>';
      }
      html += '</div>';
      if (idx < stages.length - 1) html += '<div class="sel-arrow">↓</div>';
    });
    return html;
  }

  window.loadSelectionFunnel = loadSelectionFunnel;

  /* ── Execution & Risk ── */
