  // 미진입 추적 화면의 전체 API 병합 결과와 현재 필터 상태를 보관한다.
  var _missedTrackingAll = [];
  var _missedFilter = 'all';

  /* Normalize API responses that may arrive either as an array or as { payload: [...] }. */
  function getPayloadRows(response) {
    if (Array.isArray(response)) return response;
    if (response && Array.isArray(response.payload)) return response.payload;
    return [];
  }

  /* Refresh merged missed-tracking data from Shadow Trading and Missed Opportunity endpoints. */
  async function loadMissedTracking() {
    var tbody = document.getElementById('missed-tracking-tbody');
    if (tbody) tbody.innerHTML = '<tr><td colspan="9" class="muted" style="text-align:center;">로딩중...</td></tr>';

    try {
      var fetchJson = function(url) {
        return fetch(url).then(function(r) {
          if (!r.ok) throw new Error(url + ' ' + r.status);
          return r.json();
        });
      };
      var results = await Promise.allSettled([
        fetchJson('/api/v1/shadow-trading/today'),
        fetchJson('/api/v1/missed-opportunity/today'),
      ]);
      var shadowRes = results[0].status === 'fulfilled' ? results[0].value : { payload: [] };
      var missedRes = results[1].status === 'fulfilled' ? results[1].value : { payload: [] };
      if (results[0].status === 'rejected') console.warn('[WARN] loadMissedTracking - shadow endpoint failed', results[0].reason.message);
      if (results[1].status === 'rejected') console.warn('[WARN] loadMissedTracking - missed endpoint failed', results[1].reason.message);
      if (results[0].status === 'rejected' && results[1].status === 'rejected') {
        throw new Error('missed tracking endpoints failed');
      }

      // Shadow Trading rows represent S6 candidates that reached monitoring but never emitted a buy signal.
      var shadowRows = getPayloadRows(shadowRes).map(function(r) {
        return {
          symbol: r.symbol || '',
          symbol_name: r.symbol_name || '',
          missed_stage: r.missed_stage || 'S6_NO_SIGNAL',
          missed_reason: r.missed_reason || '신호 조건 미달',
          entry_price: r.entry_price || 0,
          ret_10m: r.max_return_10m,
          ret_30m: r.max_return_30m,
          ret_eod: r.max_return_eod,
          improvement_candidate: 0,
        };
      });

      // Missed Opportunity rows represent S3/S4/S5 candidates filtered before live signal monitoring.
      var missedRows = getPayloadRows(missedRes).map(function(r) {
        return {
          symbol: r.symbol || '',
          symbol_name: r.symbol_name || '',
          missed_stage: r.missed_stage || 'S3_FILTER',
          missed_reason: r.missed_reason || '-',
          entry_price: r.price_at_missed || 0,
          ret_10m: r.max_return_after_10m,
          ret_30m: r.max_return_after_30m,
          ret_eod: r.max_return_until_eod,
          improvement_candidate: r.improvement_candidate || 0,
        };
      });

      _missedTrackingAll = shadowRows.concat(missedRows);

      var filterCount = _missedTrackingAll.filter(function(r) {
        return r.missed_stage.indexOf('S3') !== -1 || r.missed_stage.indexOf('S4') !== -1;
      }).length;
      var planCount = _missedTrackingAll.filter(function(r) { return r.missed_stage.indexOf('S5') !== -1; }).length;
      var signalCount = _missedTrackingAll.filter(function(r) { return r.missed_stage.indexOf('S6') !== -1; }).length;
      var candidateCount = _missedTrackingAll.filter(function(r) { return r.improvement_candidate; }).length;

      var setEl = function(id, val) { var el = document.getElementById(id); if (el) el.textContent = val; };
      setEl('ms-filter-count', filterCount);
      setEl('ms-plan-count', planCount);
      setEl('ms-signal-count', signalCount);
      setEl('ms-candidate-count', candidateCount);

      renderMissedTracking();
    } catch (e) {
      console.error('[ERROR] loadMissedTracking - render failed', e.message);
      if (tbody) tbody.innerHTML = '<tr><td colspan="9" class="muted" style="text-align:center;">로드 실패. 새로고침으로 다시 시도해주세요.</td></tr>';
    }
  }

  /* Update the active missed-tracking filter and redraw the merged table. */
  function filterMissedTracking(filter) {
    _missedFilter = filter;
    renderMissedTracking();
  }

  /* Render the merged missed-tracking table using the current filter state. */
  function renderMissedTracking() {
    var tbody = document.getElementById('missed-tracking-tbody');
    if (!tbody) return;

    var rows = _missedTrackingAll;
    if (_missedFilter === 'filter') {
      rows = rows.filter(function(r) { return r.missed_stage.indexOf('S3') !== -1 || r.missed_stage.indexOf('S4') !== -1; });
    } else if (_missedFilter === 'plan') {
      rows = rows.filter(function(r) { return r.missed_stage.indexOf('S5') !== -1; });
    } else if (_missedFilter === 'signal') {
      rows = rows.filter(function(r) { return r.missed_stage.indexOf('S6') !== -1; });
    } else if (_missedFilter === 'candidate') {
      rows = rows.filter(function(r) { return r.improvement_candidate; });
    }

    ['all', 'filter', 's3s4', 's5', 's6', 'candidate'].forEach(function(key) {
      var button = document.getElementById('ms-filter-' + key);
      if (button) button.classList.toggle('primary', key === _missedFilter || (key === 's3s4' && _missedFilter === 'filter') || (key === 's5' && _missedFilter === 'plan') || (key === 's6' && _missedFilter === 'signal'));
    });

    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="9" class="muted" style="text-align:center;">해당 항목 없음</td></tr>';
      return;
    }

    var stageLabel = {
      'S3_FILTER': 'S3 필터탈락', 'S3_UNIVERSE_FILTER': 'S3 필터탈락',
      'S4_SCREENING': 'S4 스크리닝탈락', 'S4_HYBRID_SCREENING': 'S4 스크리닝탈락',
      'S5_NOT_ASSIGNED': 'S5 미배정',
      'S6_NO_SIGNAL': 'S6 신호미발생',
    };

    var fmtPct = function(v) {
      if (v == null) return '-';
      var n = parseFloat(v);
      if (isNaN(n)) return '-';
      var color = n > 0 ? 'var(--green)' : n < 0 ? 'var(--red)' : 'var(--muted)';
      return '<span style="color:' + color + ';">' + (n >= 0 ? '+' : '') + n.toFixed(2) + '%</span>';
    };

    tbody.innerHTML = rows.map(function(r) {
      var stage = stageLabel[r.missed_stage] || r.missed_stage;
      var priceNum = Number(r.entry_price);
      var price = priceNum ? priceNum.toLocaleString() + '원' : '-';
      var candiBadge = r.improvement_candidate
        ? '<span style="color:var(--warn); font-size:11px;">개선후보</span>'
        : '-';
      return '<tr>'
        + '<td>' + escapeHtml(r.symbol) + '</td>'
        + '<td>' + escapeHtml(r.symbol_name) + '</td>'
        + '<td><span style="font-size:11px; color:var(--muted);">' + escapeHtml(stage) + '</span></td>'
        + '<td style="font-size:11px; color:var(--muted);">' + escapeHtml(r.missed_reason || '-') + '</td>'
        + '<td>' + price + '</td>'
        + '<td>' + fmtPct(r.ret_10m) + '</td>'
        + '<td>' + fmtPct(r.ret_30m) + '</td>'
        + '<td>' + fmtPct(r.ret_eod) + '</td>'
        + '<td>' + candiBadge + '</td>'
        + '</tr>';
    }).join('');
  }

  /* Preserve legacy callers by routing the old Shadow Trading refresh into the unified screen. */
  async function loadShadowTrading() {
    await loadMissedTracking();
  }

  /* Preserve legacy callers by routing the removed Missed Opportunity screen into the unified screen. */
  async function loadMissedOpportunity() {
    await loadMissedTracking();
  }
