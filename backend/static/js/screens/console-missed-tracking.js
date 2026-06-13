  // 미진입 추적 화면의 전체 API 병합 결과와 현재 필터 상태를 보관한다.
  var _missedTrackingAll = [];
  var _missedFilter = 'all';
  var _missedRangeFilter = 'today'; // P4 기간검색: today | week | month | range
  // shadow_trades 개선후보 판정 임계치(%) — 장중 최고가 상승률(max_return_eod) 기준.
  var MISSED_SHADOW_CANDIDATE_PCT = 5;

  /* Normalize API responses that may arrive either as an array or as { payload: [...] }. */
  function getPayloadRows(response) {
    if (Array.isArray(response)) return response;
    if (response && Array.isArray(response.payload)) return response.payload;
    return [];
  }

  /* P4 기간검색: 버튼 상태를 갱신하고 해당 범위로 다시 로드한다 (Trade History 패턴 공통화). */
  function setMissedRange(filter) {
    _missedRangeFilter = filter || 'today';
    ['today', 'week', 'month', 'range'].forEach(function(f) {
      var btn = document.getElementById('ms-range-' + f);
      if (btn) btn.className = 'btn' + (f === _missedRangeFilter ? ' primary' : '');
    });
    loadMissedTracking();
  }

  /* Refresh merged missed-tracking data from Shadow Trading and Missed Opportunity endpoints. */
  async function loadMissedTracking() {
    var tbody = document.getElementById('missed-tracking-tbody');
    if (tbody) tbody.innerHTML = '<tr><td colspan="10" class="muted" style="text-align:center;">로딩중...</td></tr>';

    try {
      var fetchJson = function(url) {
        return fetch(url).then(function(r) {
          if (!r.ok) throw new Error(url + ' ' + r.status);
          return r.json();
        });
      };
      var range = computeDateRangeFilter(_missedRangeFilter, 'ms-range-start', 'ms-range-end');
      var qs = '?start=' + encodeURIComponent(range.start) + '&end=' + encodeURIComponent(range.end);
      var results = await Promise.allSettled([
        fetchJson('/api/v1/shadow-trading/today' + qs),
        fetchJson('/api/v1/missed-opportunity/today' + qs),
      ]);
      var shadowRes = results[0].status === 'fulfilled' ? results[0].value : { payload: [] };
      var missedRes = results[1].status === 'fulfilled' ? results[1].value : { payload: [] };
      if (results[0].status === 'rejected') console.warn('[WARN] loadMissedTracking - shadow endpoint failed', results[0].reason.message);
      if (results[1].status === 'rejected') console.warn('[WARN] loadMissedTracking - missed endpoint failed', results[1].reason.message);
      if (results[0].status === 'rejected' && results[1].status === 'rejected') {
        throw new Error('missed tracking endpoints failed');
      }

      // Shadow Trading rows represent S6 candidates that reached monitoring but never emitted a buy signal.
      // intraday_high = 장중 최고가 상승률(%) = max_return_eod, intraday_low = 장중 최저가 상승률(%).
      // P4: 일봉 저가/고가/종가(원)는 intraday_low/intraday_high/close_price 컬럼에서 읽는다.
      var shadowRows = getPayloadRows(shadowRes).map(function(r) {
        var entry = Number(r.entry_price) || 0;
        var lowPct = null;
        if (r.intraday_low != null && entry > 0) {
          lowPct = (Number(r.intraday_low) - entry) / entry * 100;
        }
        var highPct = r.max_return_eod;
        return {
          trade_date: r.trade_date || '',
          symbol: r.symbol || '',
          symbol_name: r.symbol_name || '',
          missed_stage: r.missed_stage || 'S6_NO_SIGNAL',
          missed_reason: r.missed_reason || '신호 조건 미달',
          price_at_missed: entry,
          intraday_high: highPct,
          intraday_low: lowPct,
          close_price: r.close_price,
          improvement_candidate: (highPct != null && Number(highPct) >= MISSED_SHADOW_CANDIDATE_PCT) ? 1 : 0,
        };
      });

      // Missed Opportunity rows represent S3/S4/S5 candidates filtered before live signal monitoring.
      var missedRows = getPayloadRows(missedRes).map(function(r) {
        return {
          trade_date: r.trade_date || '',
          symbol: r.symbol || '',
          symbol_name: r.symbol_name || '',
          missed_stage: r.missed_stage || 'S3_FILTER',
          missed_reason: r.missed_reason || '-',
          price_at_missed: r.price_at_missed || 0,
          intraday_high: r.max_return_until_eod,
          intraday_low: r.intraday_low_return,
          close_price: null, // missed_opportunities 에는 종가 미수집
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
      if (tbody) tbody.innerHTML = '<tr><td colspan="10" class="muted" style="text-align:center;">로드 실패. 새로고침으로 다시 시도해주세요.</td></tr>';
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
      tbody.innerHTML = '<tr><td colspan="10" class="muted" style="text-align:center;">해당 항목 없음</td></tr>';
      return;
    }

    var stageLabel = {
      'S3_FILTER': 'S3 필터탈락', 'S3_UNIVERSE_FILTER': 'S3 필터탈락',
      'S4_SCREENING': 'S4 스크리닝탈락', 'S4_HYBRID_SCREENING': 'S4 스크리닝탈락',
      'S5_NOT_ASSIGNED': 'S5 미배정',
      'S6_NO_SIGNAL': 'S6 신호미발생',
    };

    // 장중 최고/최저 상승률 — 최고는 녹색, 최저는 적색으로 고정 강조.
    var fmtPctFixed = function(v, color) {
      if (v == null) return '-';
      var n = parseFloat(v);
      if (isNaN(n)) return '-';
      return '<span style="color:' + color + ';">' + (n >= 0 ? '+' : '') + n.toFixed(2) + '%</span>';
    };

    tbody.innerHTML = rows.map(function(r) {
      var stage = stageLabel[r.missed_stage] || r.missed_stage;
      var priceNum = Number(r.price_at_missed);
      var price = priceNum ? priceNum.toLocaleString() + '원' : '-';
      var closeNum = Number(r.close_price);
      var closeStr = (r.close_price != null && closeNum) ? closeNum.toLocaleString() + '원' : '-';
      var candiBadge = r.improvement_candidate
        ? '<span style="color:var(--warn); font-size:11px;">개선후보</span>'
        : '-';
      return '<tr>'
        + '<td style="white-space:nowrap; font-size:11px; color:var(--muted);">' + escapeHtml(r.trade_date || '-') + '</td>'
        + '<td>' + escapeHtml(r.symbol) + '</td>'
        + '<td>' + escapeHtml(r.symbol_name) + '</td>'
        + '<td><span style="font-size:11px; color:var(--muted);">' + escapeHtml(stage) + '</span></td>'
        + '<td style="font-size:11px; color:var(--muted);">' + escapeHtml(r.missed_reason || '-') + '</td>'
        + '<td>' + price + '</td>'
        + '<td>' + fmtPctFixed(r.intraday_high, 'var(--green)') + '</td>'
        + '<td>' + fmtPctFixed(r.intraday_low, 'var(--red)') + '</td>'
        + '<td>' + closeStr + '</td>'
        + '<td>' + candiBadge + '</td>'
        + '</tr>';
    }).join('');

    // 모바일 카드 렌더링
    var isMobile = window.innerWidth <= 860;
    var cardContainer = document.getElementById("missedCardList");
    if (cardContainer) {
      cardContainer.style.display = isMobile ? "flex" : "none";
      var tableWrap = cardContainer.previousElementSibling;
      if (tableWrap && tableWrap.classList.contains('table-wrap')) {
        tableWrap.style.display = isMobile ? "none" : "block";
      }
    }
    if (isMobile) {
      renderMissedCards(rows);
    }
  }

  function renderMissedCards(rows) {
    var container = document.getElementById("missedCardList");
    if (!container) return;
    if (!rows || rows.length === 0) {
      container.innerHTML = '<div style="padding:20px; text-align:center; color:var(--muted);">미진입 항목 없음</div>';
      return;
    }

    var fmtPctRaw = function(v, color) {
      if (v == null) return '-';
      var n = parseFloat(v);
      if (isNaN(n)) return '-';
      return '<span style="color:' + color + '; font-weight:700;">' + (n >= 0 ? '+' : '') + n.toFixed(2) + '%</span>';
    };

    container.innerHTML = rows.map(function(r) {
      var priceNum = Number(r.price_at_missed);
      var price = priceNum ? priceNum.toLocaleString() + '원' : '-';
      var closeNum = Number(r.close_price);
      var closeStr = (r.close_price != null && closeNum) ? closeNum.toLocaleString() + '원' : '-';
      var candiBadge = r.improvement_candidate
        ? ' <span style="color:var(--warn); font-size:10px; font-weight:600;">· 개선후보</span>'
        : '';
      return [
        '<div class="missed-card">',
          '<div class="missed-card-top">',
            '<div>',
              '<div class="missed-card-symbol">' + escapeHtml(r.symbol) + candiBadge + '</div>',
              '<div style="font-size:11px; color:var(--muted);">' + escapeHtml(r.symbol_name) + (r.trade_date ? ' · ' + escapeHtml(r.trade_date) : '') + '</div>',
            '</div>',
            '<div class="missed-card-pnl">' + fmtPctRaw(r.intraday_high, '#22c55e') + '</div>',
          '</div>',
          '<div style="font-size:11px; margin-bottom:8px;">',
            '<span style="color:var(--primary); font-weight:600;">' + escapeHtml(r.missed_stage) + '</span> · ',
            '<span>' + escapeHtml(r.missed_reason || '-') + '</span>',
          '</div>',
          '<div style="display:grid; grid-template-columns:1fr 1fr; gap:4px; font-size:11px; color:var(--muted);">',
            '<span>제외가: ' + price + '</span>',
            '<span>장중최저: ' + fmtPctRaw(r.intraday_low, '#ef4444') + '</span>',
            '<span>종가: ' + closeStr + '</span>',
          '</div>',
        '</div>'
      ].join('');
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
