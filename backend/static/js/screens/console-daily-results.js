  /* ── Daily Results screen ── */

  var _dailyResultsAll = [];   // 전체 데이터 캐시 (날짜 필터는 클라이언트에서)

  /* 오늘로부터 n일 전 YYYY-MM-DD 반환 */
  function _daysAgo(n) {
    var d = new Date();
    d.setDate(d.getDate() - n);
    return d.toISOString().slice(0, 10);
  }

  /* 날짜 범위 picker 초기화 (첫 로드 시 1회) */
  function _initDailyResultsFilter() {
    var s = document.getElementById('dr-start-date');
    var e = document.getElementById('dr-end-date');
    if (!s || !e || s.dataset.init) return;
    s.value = _daysAgo(29);
    e.value = new Date().toISOString().slice(0, 10);
    s.dataset.init = '1';
  }

  /* 전체 데이터를 API에서 가져와 캐시 */
  async function loadDailyResults() {
    var container = document.getElementById('daily-results-container');
    if (!container) return;
    container.innerHTML = '<div style="color:var(--muted); padding:20px 0; text-align:center;">Loading…</div>';
    try {
      var r = await fetch('/api/v1/trading-monitor/daily-results');
      var d = await r.json();
      _dailyResultsAll = d.payload || [];
      _initDailyResultsFilter();
      _applyDailyResultsFilter();
    } catch (e) {
      container.innerHTML = '<div style="color:var(--muted); padding:20px 0; text-align:center;">Load failed: ' + escapeHtml(e.message) + '</div>';
    }
  }

  /* 날짜 범위 필터 적용 후 렌더 */
  function _applyDailyResultsFilter() {
    var container = document.getElementById('daily-results-container');
    if (!container) return;

    var s = document.getElementById('dr-start-date');
    var e = document.getElementById('dr-end-date');
    var start = s ? s.value : '';
    var end   = e ? e.value : '';

    var rows = _dailyResultsAll;
    if (start) rows = rows.filter(function(r) { return r.trade_date >= start; });
    if (end)   rows = rows.filter(function(r) { return r.trade_date <= end; });

    if (rows.length === 0) {
      container.innerHTML = '<div style="color:var(--muted); padding:20px 0; text-align:center;">No results for the selected range.</div>';
      return;
    }
    container.innerHTML = _renderDailyResultsSummary(rows, start, end) + _renderDailyResultsTable(rows);

    // 모바일 카드 렌더링
    var isMobile = window.innerWidth <= 860;
    var cardContainer = document.getElementById("dailyResultList");
    if (cardContainer) {
      cardContainer.style.display = isMobile ? "flex" : "none";
      // 모바일이면 테이블 컨테이너 내부의 테이블 래퍼 숨김
      var tableWrap = container.querySelector('.table-wrap');
      if (tableWrap) {
        tableWrap.style.display = isMobile ? "none" : "block";
      }
      if (isMobile) {
        renderDailyResultCards(rows);
      }
    }
  }

  function renderDailyResultCards(rows) {
    var container = document.getElementById("dailyResultList");
    if (!container) return;

    container.innerHTML = rows.map(function(row) {
      if (row.non_trading) {
        return '<div class="daily-result-item" style="opacity:0.5;">'
          + '<div><div class="daily-result-date">' + escapeHtml(row.trade_date) + '</div>'
          + '<div class="daily-result-trades">휴장 · ' + escapeHtml(row.non_trading_reason || '비거래일') + '</div></div>'
          + '</div>';
      }
      var pnl = row.total_pnl || 0;
      var pnlCls = pnl > 0 ? 'pos' : pnl < 0 ? 'neg' : '';
      var pnlSign = pnl >= 0 ? '+' : '';

      return [
        '<div class="daily-result-item" onclick="dailyResultsGoToReview(\'' + escapeHtml(row.trade_date) + '\')">',
          '<div>',
            '<div class="daily-result-date">' + escapeHtml(row.trade_date) + '</div>',
            '<div class="daily-result-trades">' + (row.trade_count || 0) + ' trades · ' + (row.win_count || 0) + 'W ' + (row.loss_count || 0) + 'L</div>',
          '</div>',
          '<div class="daily-result-pnl ' + pnlCls + '">' + pnlSign + Math.round(pnl).toLocaleString() + '원</div>',
        '</div>'
      ].join('');
    }).join('');
  }


  /* 날짜 범위를 "최근 30일" 등 preset으로 설정 */
  function setDailyResultsPreset(days) {
    var s = document.getElementById('dr-start-date');
    var e = document.getElementById('dr-end-date');
    if (!s || !e) return;
    /* 9999 = All: start를 비워 필터 없이 전체 표시 */
    s.value = days >= 9999 ? '' : _daysAgo(days - 1);
    e.value = days >= 9999 ? '' : new Date().toISOString().slice(0, 10);
    /* preset 버튼 활성 표시 */
    document.querySelectorAll('.dr-preset-btn').forEach(function(b) {
      b.classList.toggle('primary', b.dataset.days == days);
    });
    _applyDailyResultsFilter();
  }

  /* 시장톤 배지 HTML */
  function _toneBadge(tone) {
    var cfg = {
      positive: { label: '상승장', color: 'var(--green)', bg: 'rgba(31,138,101,0.12)' },
      negative: { label: '하락장', color: 'var(--red)',   bg: 'rgba(207,45,86,0.12)' },
      neutral:  { label: '보합',   color: 'var(--muted)', bg: 'var(--panel-3)' },
      mixed:    { label: '혼조',   color: '#d29922',      bg: 'rgba(210,153,34,0.12)' },
    };
    var c = cfg[tone] || { label: tone || '-', color: 'var(--muted)', bg: 'var(--panel-3)' };
    return '<span style="display:inline-block; padding:2px 7px; border-radius:10px; font-size:11px; font-weight:600;'
      + ' background:' + c.bg + '; color:' + c.color + ';">' + c.label + '</span>';
  }

  /* 톤별 승률 통계 계산 */
  function _toneStats(rows) {
    var tones = ['positive', 'negative', 'neutral', 'mixed'];
    var stats = {};
    tones.forEach(function(t) { stats[t] = { wins: 0, total: 0, days: 0, pnl: 0 }; });
    rows.forEach(function(r) {
      var t = r.market_tone;
      if (!t || !stats[t]) return;
      stats[t].days++;
      stats[t].pnl += r.total_pnl || 0;
      var w = r.win_count || 0, l = r.loss_count || 0;
      stats[t].wins += w;
      stats[t].total += w + l;
    });
    return stats;
  }

  function _renderDailyResultsSummary(rows, start, end) {
    var totalPnl    = rows.reduce(function(acc, r) { return acc + (r.total_pnl || 0); }, 0);
    var totalNetPnl = rows.reduce(function(acc, r) { return acc + (r.net_pnl != null ? r.net_pnl : (r.total_pnl || 0)); }, 0);
    var hasNetData  = rows.some(function(r) { return r.net_pnl != null; });
    var tradingDays = rows.filter(function(r) { return !r.non_trading; }).length;
    var totalWins  = rows.reduce(function(acc, r) { return acc + (r.win_count || 0); }, 0);
    var totalLosses= rows.reduce(function(acc, r) { return acc + (r.loss_count || 0); }, 0);
    var totalTrades = totalWins + totalLosses;
    var avgWinRate = totalTrades > 0 ? Math.round(totalWins / totalTrades * 100) : 0;

    var pnlCls  = totalPnl > 0 ? 'good' : totalPnl < 0 ? 'bad' : '';
    var pnlSign = totalPnl >= 0 ? '+' : '';
    var netCls  = totalNetPnl > 0 ? 'good' : totalNetPnl < 0 ? 'bad' : '';
    var netSign = totalNetPnl >= 0 ? '+' : '';
    var rangeLabel = (start && end) ? (start + ' ~ ' + end) : 'All';

    // 톤별 승률 통계 카드
    var toneStats = _toneStats(rows);
    var toneLabels = { positive: '상승장', negative: '하락장', neutral: '보합', mixed: '혼조' };
    var toneColors = { positive: 'var(--green)', negative: 'var(--red)', neutral: 'var(--muted)', mixed: '#d29922' };
    var toneBgs    = { positive: 'rgba(31,138,101,0.08)', negative: 'rgba(207,45,86,0.08)', neutral: 'var(--panel-3)', mixed: 'rgba(210,153,34,0.08)' };

    var toneHtml = Object.keys(toneLabels).map(function(t) {
      var s = toneStats[t];
      if (s.days === 0) return '';
      var wr = s.total > 0 ? Math.round(s.wins / s.total * 100) : null;
      var wrStr = wr !== null ? wr + '%' : '-';
      var wrCls = wr === null ? 'color:var(--muted)' : (wr >= 50 ? 'color:var(--green)' : 'color:var(--red)');
      var pnlStr = (s.pnl >= 0 ? '+' : '') + Math.round(s.pnl).toLocaleString() + '원';
      var pnlStyle = s.pnl > 0 ? 'color:var(--green)' : s.pnl < 0 ? 'color:var(--red)' : 'color:var(--muted)';
      return '<div style="flex:1; min-width:120px; background:' + toneBgs[t] + '; border-radius:8px; padding:10px 12px;">'
        + '<div style="font-size:11px; font-weight:700; color:' + toneColors[t] + '; margin-bottom:4px;">' + toneLabels[t] + '</div>'
        + '<div style="font-size:20px; font-weight:700; ' + wrCls + ';">' + wrStr + '</div>'
        + '<div style="font-size:11px; color:var(--muted); margin-top:2px;">'
          + s.days + '일 · ' + s.total + '건</div>'
        + '<div style="font-size:11px; margin-top:2px; ' + pnlStyle + ';">' + pnlStr + '</div>'
        + '</div>';
    }).join('');

    return '<div class="grid cols-3" style="margin-bottom:12px;">'
      + '<div class="card compact">'
      + '<div class="card-title">Total P&L (Gross) <span style="font-weight:400; color:var(--muted);">' + escapeHtml(rangeLabel) + '</span></div>'
      + '<div class="metric ' + pnlCls + '">' + pnlSign + Math.round(totalPnl).toLocaleString() + '원</div>'
      + (hasNetData
        ? '<div style="font-size:11px; margin-top:4px;">'
          + 'Net: <span class="' + netCls + '">' + netSign + Math.round(totalNetPnl).toLocaleString() + '원</span>'
          + ' <span style="color:var(--muted); font-size:10px;">(비용 차감)</span></div>'
        : '')
      + '</div>'
      + '<div class="card compact">'
      + '<div class="card-title">Trading Days <span>days</span></div>'
      + '<div class="metric">' + tradingDays + '</div>'
      + '</div>'
      + '<div class="card compact">'
      + '<div class="card-title">Avg Win Rate <span>win rate</span></div>'
      + '<div class="metric ' + (avgWinRate >= 50 ? 'good' : 'warn') + '">' + avgWinRate + '%</div>'
      + '</div>'
      + '</div>'
      + (toneHtml
        ? '<div class="card" style="margin-bottom:16px; padding:12px 16px;">'
          + '<div style="font-size:11px; font-weight:600; color:var(--muted); margin-bottom:10px; letter-spacing:.05em;">시장톤별 승률</div>'
          + '<div style="display:flex; gap:8px; flex-wrap:wrap;">' + toneHtml + '</div>'
          + '</div>'
        : '');
  }

  function _renderDailyResultsTable(rows) {
    var headerRow = '<thead><tr>'
      + '<th style="text-align:left;">Date</th>'
      + '<th style="text-align:center;">Market</th>'
      + '<th style="text-align:right;">P&L (₩)</th>'
      + '<th style="text-align:right;">Return</th>'
      + '<th style="text-align:right;">Trades</th>'
      + '<th style="text-align:right;">W / L</th>'
      + '<th style="text-align:right;">Win Rate</th>'
      + '<th style="text-align:right;">Missed</th>'
      + '<th style="text-align:center;">Integrity</th>'
      + '</tr></thead>';

    var bodyRows = rows.map(function(row) {
      // 비거래일(주말·공휴일)은 "휴장" 한 줄로 표시 — missed/integrity 등 노이즈 미표시
      if (row.non_trading) {
        return '<tr style="opacity:0.5;">'
          + '<td style="font-size:13px; color:var(--muted);">' + escapeHtml(row.trade_date)
          + ' <span class="status" style="font-size:10px; background:rgba(139,148,158,0.15); color:var(--muted);">휴장</span></td>'
          + '<td colspan="8" style="color:var(--muted); font-size:12px;">' + escapeHtml(row.non_trading_reason || '비거래일') + '</td>'
          + '</tr>';
      }
      var pnl = row.total_pnl || 0;
      var pnlCls  = pnl > 0 ? 'good' : pnl < 0 ? 'bad' : '';
      var pnlSign = pnl >= 0 ? '+' : '';
      var pnlHtml = '<span class="' + pnlCls + '">' + pnlSign + Math.round(pnl).toLocaleString() + '원</span>';

      var totalTrades = (row.win_count || 0) + (row.loss_count || 0);
      var winRate = row.win_rate != null ? row.win_rate : (totalTrades > 0 ? Math.round((row.win_count || 0) / totalTrades * 100) : 0);
      var winRateCls = winRate >= 50 ? 'good' : totalTrades > 0 ? 'warn' : '';
      var winRateHtml = totalTrades > 0
        ? '<span class="' + winRateCls + '">' + winRate + '%</span>'
        : '<span style="color:var(--muted);">-</span>';

      var integrityWarnings = [];
      try { integrityWarnings = JSON.parse(row.integrity_warnings || '[]'); } catch(e) {}
      var integrityHtml;
      if (integrityWarnings.length === 0) {
        integrityHtml = '<span class="status ok">OK</span>';
      } else {
        integrityHtml = '<span class="status danger" title="' + escapeHtml(integrityWarnings.join(', ')) + '">'
          + integrityWarnings.length + ' warn</span>';
      }

      var pnlStatusBadge = '';
      if (row.pnl_status && row.pnl_status !== 'unverified') {
        var statusCls = row.pnl_status === 'verified' ? 'ok' : 'warn';
        pnlStatusBadge = ' <span class="status ' + statusCls + '" style="font-size:10px;">' + escapeHtml(row.pnl_status) + '</span>';
      }

      var toneCell = '<td style="text-align:center;">' + _toneBadge(row.market_tone) + '</td>';

      return '<tr style="cursor:pointer;" data-action="toggleDayReview" data-date="' + escapeHtml(row.trade_date) + '">'
        + '<td style="font-size:13px; color:var(--accent);">' + escapeHtml(row.trade_date) + pnlStatusBadge + '</td>'
        + toneCell
        + '<td style="text-align:right;">' + pnlHtml + '</td>'
        + '<td style="text-align:right; font-size:12px;">'
          + (row.pnl_rate != null
            ? '<span class="' + pnlCls + '">' + (row.pnl_rate >= 0 ? '+' : '') + (row.pnl_rate || 0).toFixed(2) + '%</span>'
            : '<span style="color:var(--muted);">-</span>')
        + '</td>'
        + '<td style="text-align:right;">' + (row.trade_count || 0) + '</td>'
        + '<td style="text-align:right; font-size:12px;">'
          + '<span style="color:var(--green);">' + (row.win_count || 0) + '</span>'
          + ' / '
          + '<span style="color:var(--red);">' + (row.loss_count || 0) + '</span>'
        + '</td>'
        + '<td style="text-align:right;">' + winRateHtml + '</td>'
        + '<td style="text-align:right; color:var(--muted); font-size:12px;">' + (row.missed_entries_count || 0) + '</td>'
        + '<td style="text-align:center;">' + integrityHtml + '</td>'
        + '</tr>'
        + '<tr id="dr-detail-' + escapeHtml(row.trade_date) + '" style="display:none;">'
        + '<td colspan="9" style="padding:0; background:var(--bg2);">'
        + '<div id="dr-detail-content-' + escapeHtml(row.trade_date) + '" style="padding:12px 16px;">'
        + '<div class="muted" style="font-size:12px;">로딩 중...</div>'
        + '</div>'
        + '<div id="day-review-' + escapeHtml(row.trade_date) + '" style="padding:0 16px 16px;"></div>'
        + '</td>'
        + '</tr>';
    }).join('');

    return '<div class="card" style="padding:0; overflow:hidden;">'
      + '<div class="table-wrap">'
      + '<table>'
      + headerRow
      + '<tbody>' + bodyRows + '</tbody>'
      + '</table>'
      + '</div>'
      + '</div>';
  }

  var _drDetailCache = {};
  var _drOpenDate = null;   // 현재 펼쳐진 날짜 (한 번에 하나만)

  /* 공유 Trade Review 호스트(#ra-report / #ra-empty)를 원래 위치(#screen-review)로 되돌림.
     fixed-id 재사용을 위해 항상 하나의 호스트만 DOM에 둔다(중복 id 방지). */
  function _detachDayReviewHost() {
    var screen = document.getElementById('screen-review');
    var report = document.getElementById('ra-report');
    var empty  = document.getElementById('ra-empty');
    if (screen) {
      if (empty)  { empty.style.display = 'none';  screen.appendChild(empty); }
      if (report) { report.style.display = 'none'; screen.appendChild(report); }
    }
  }

  /* 날짜 행을 클릭하면 그 날짜의 복기(Trade Review)를 인라인으로 펼친다.
     레짐 day-detail 요약 + 공유 Trade Review 렌더(_loadReviewByDateStr 재사용)를 함께 표시. */
  async function toggleDayReview(tradeDate) {
    var detailRow = document.getElementById('dr-detail-' + tradeDate);
    if (!detailRow) return;

    // 이미 열린 행을 다시 클릭 → 접기
    if (_drOpenDate === tradeDate && detailRow.style.display !== 'none') {
      detailRow.style.display = 'none';
      _detachDayReviewHost();
      _drOpenDate = null;
      return;
    }

    // 다른 행이 열려 있으면 먼저 접기 (한 번에 하나만)
    if (_drOpenDate && _drOpenDate !== tradeDate) {
      var prev = document.getElementById('dr-detail-' + _drOpenDate);
      if (prev) prev.style.display = 'none';
    }
    _detachDayReviewHost();

    detailRow.style.display = 'table-row';
    _drOpenDate = tradeDate;

    // 1) 레짐 day-detail 요약 (기존 동작 유지, 캐시)
    var summaryEl = document.getElementById('dr-detail-content-' + tradeDate);
    if (_drDetailCache[tradeDate]) {
      if (summaryEl) summaryEl.innerHTML = _drDetailCache[tradeDate];
    } else {
      try {
        var r = await fetch('/api/v1/regime/day-detail?trade_date=' + encodeURIComponent(tradeDate));
        var d = await r.json();
        var html = _renderDayDetail(d);
        _drDetailCache[tradeDate] = html;
        if (summaryEl) summaryEl.innerHTML = html;
      } catch(e) {
        if (summaryEl) summaryEl.innerHTML = '<div class="muted">조회 실패</div>';
      }
    }

    // 2) 공유 Trade Review 호스트를 이 행으로 이동 후 렌더 재사용
    var host = document.getElementById('day-review-' + tradeDate);
    var report = document.getElementById('ra-report');
    var empty  = document.getElementById('ra-empty');
    if (host) {
      if (empty)  host.appendChild(empty);
      if (report) host.appendChild(report);
      if (typeof _loadReviewByDateStr === 'function') {
        await _loadReviewByDateStr(tradeDate);
      }
    }
  }

  function _renderDayDetail(d) {
    var parts = [];
    
    // 레짐 SET 정보
    var app = d.regime_application;
    if (app) {
      var REGIME_COLORS = {risk_on:'#3fb950', neutral:'#8b9bb4', risk_off:'#f85149', volatile:'#d29922'};
      var rc = REGIME_COLORS[app.regime_label] || '#8b9bb4';
      parts.push(
        '<div style="display:flex; gap:12px; flex-wrap:wrap; align-items:center; margin-bottom:10px;">'
        + '<span style="font-size:11px; color:var(--muted);">레짐 SET</span>'
        + '<span style="font-weight:700; font-size:13px;">' + escapeHtml(app.set_name || '-') + '</span>'
        + (app.is_prebuilt ? '<span style="font-size:10px; background:#d29922; color:#000; border-radius:3px; padding:1px 5px;">예측 SET</span>' : '')
        + '<span style="color:' + rc + '; font-size:12px;">' + escapeHtml(app.regime_label || '-') + '</span>'
        + '<span style="font-size:11px; color:var(--muted);">매칭 ' + Math.round((app.match_score || 0) * 100) + '%</span>'
        + '</div>'
        + '<div style="font-size:12px; color:var(--muted); margin-bottom:10px;">' + escapeHtml(app.match_reason || '') + '</div>'
      );
    } else {
      parts.push('<div style="font-size:12px; color:var(--muted); margin-bottom:10px;">레짐 SET 기록 없음 (이전 거래일)</div>');
    }
    
    // Risk Profile별 성과
    var profiles = d.profile_breakdown || [];
    if (profiles.length > 0) {
      var PROFILE_COLORS = {LOW_VOL:'#6cb6ff', MID_VOL:'#3fb950', HIGH_VOL:'#d29922', THEME_SPIKE:'#f85149'};
      parts.push(
        '<div style="display:flex; gap:8px; flex-wrap:wrap;">'
        + profiles.map(function(p) {
            var pc = PROFILE_COLORS[p.profile] || '#8b9bb4';
            var pnlSign = (p.total_pnl || 0) >= 0 ? '+' : '';
            var pnlCls = (p.total_pnl || 0) > 0 ? 'color:var(--green)' : (p.total_pnl || 0) < 0 ? 'color:var(--red)' : 'color:var(--muted)';
            return '<div style="background:var(--panel-2); border-radius:6px; padding:8px 12px; min-width:120px;">'
              + '<div style="font-size:11px; font-weight:700; color:' + pc + '; margin-bottom:4px;">' + escapeHtml(p.profile) + '</div>'
              + '<div style="font-size:13px; font-weight:700;">' + (p.win_rate_pct || 0) + '% <span style="font-size:11px; color:var(--muted);">승률</span></div>'
              + '<div style="font-size:11px; color:var(--muted);">' + (p.trades || 0) + '건 (' + (p.win_count || 0) + '승)</div>'
              + '<div style="font-size:11px; ' + pnlCls + ';">' + pnlSign + Math.round(p.total_pnl || 0).toLocaleString() + '원</div>'
              + '</div>';
          }).join('')
        + '</div>'
      );
    } else {
      parts.push('<div style="font-size:12px; color:var(--muted);">Risk Profile별 성과 데이터 없음</div>');
    }
    
    return '<div style="padding:4px 0;">' + parts.join('') + '</div>';
  }

  /* 모바일 카드 클릭 → 데스크톱과 동일하게 인라인 복기 토글 (드릴다운 통합 후 전용 화면 없음) */
  function dailyResultsGoToReview(date) {
    if (typeof toggleDayReview === 'function') toggleDayReview(date);
  }

  function applyDailyResultsFilter() { _applyDailyResultsFilter(); }

  window.loadDailyResults = loadDailyResults;
  window.setDailyResultsPreset = setDailyResultsPreset;
  window.applyDailyResultsFilter = applyDailyResultsFilter;
  window.dailyResultsGoToReview = dailyResultsGoToReview;
  window.toggleDayReview = toggleDayReview;
