  var tmEventSource = null;
  var tmRealtimeRefreshTimer = null;
  var tmLastRealtimeRefresh = 0;

  /* Render one Trading Monitor approach bar for a symbol with a 0-100 proximity rate. */
  function _tmApproachBar(label, code, rate, colorFn) {
    var pct = Math.min(100, Math.max(0, Number(rate) || 0));
    var color = colorFn(pct);
    return ''
      + '<div style="display:flex; flex-direction:column; gap:4px;">'
      + '  <div style="display:flex; justify-content:space-between; align-items:baseline;">'
      + '    <span style="font-size:13px; font-weight:600;">' + escapeHtml(label || "-") + '</span>'
      + '    <span style="font-size:11px; color:var(--muted);">' + escapeHtml(code || "") + '</span>'
      + '  </div>'
      + '  <div style="display:flex; align-items:center; gap:8px;">'
      + '    <div style="flex:1; background:var(--bg2); border-radius:4px; height:10px; overflow:hidden;">'
      + '      <div style="width:' + pct + '%; height:100%; background:' + color + '; border-radius:4px; transition:width 0.8s ease;"></div>'
      + '    </div>'
      + '    <span style="font-size:12px; font-weight:700; min-width:36px; text-align:right; color:' + color + ';">' + pct.toFixed(0) + '%</span>'
      + '  </div>'
      + '</div>';
  }

  /* Choose the buy-side approach color by proximity rate. */
  function _buyColor(pct) {
    if (pct >= 80) return "var(--green, #22c55e)";
    if (pct >= 50) return "var(--yellow, #eab308)";
    return "var(--muted, #888)";
  }

  /* Choose the sell-side approach color by proximity rate. */
  function _sellColor(pct) {
    if (pct >= 80) return "var(--red, #ef4444)";
    if (pct >= 50) return "var(--yellow, #eab308)";
    return "var(--muted, #888)";
  }

  /* Load Trading Monitor - policy info, buy candidates, sell positions */
  async function loadTradingMonitor() {
    // DE 상태 로드
    try {
      var statusData = await fetchJson("/api/v1/decision/status");
      if (statusData && statusData.ok && statusData.payload) {
        var active = Boolean(statusData.payload.active);
        var btn = document.getElementById("tm-de-toggle");
        var lbl = document.getElementById("tm-de-label");
        if (btn && lbl) {
          lbl.textContent = active ? "● DE 활성" : "○ DE 비활성";
          btn.className = "btn " + (active ? "primary" : "");
          btn._deActive = active;
        }
      }
    } catch(e) { console.warn("loadTradingMonitor status error", e); }

    // 계좌 정보 로드
    try {
      var accountData = await fetchJson("/api/v1/account/balance");
      if (accountData && accountData.ok && accountData.payload) {
        var acct = accountData.payload;
        var setEl = function(id, v) { var el = document.getElementById(id); if (el) el.textContent = v; };
        var fmtWon = function(v) { return v != null ? Number(v).toLocaleString() + '원' : '-'; };

        setEl('tm-account-no', acct.account_no ? '· ' + acct.account_no : '');

        // 주문가능 예수금 (nxdy_excc_amt 기반, buyable_cash)
        var buyable = acct.buyable_cash != null ? acct.buyable_cash : acct.available_cash;
        setEl('tm-buyable-cash', fmtWon(buyable));
        setEl('tm-deposit-limit', '한도 ' + fmtWon(acct.deposit));

        // 주식 평가금액
        setEl('tm-stock-eval', fmtWon(acct.stock_eval != null ? acct.stock_eval : acct.purchase_total));
        var holdings = acct.positions || acct.holdings || [];
        setEl('tm-holdings-count', '보유 ' + holdings.length + '종목');

        // 총평가금액
        setEl('tm-total-eval', fmtWon(acct.total_eval));

        // 평가손익 / 수익률
        var pnlEl = document.getElementById('tm-pnl-today');
        var pnlRateEl = document.getElementById('tm-pnl-rate');
        var pnlVal = acct.pnl_total;
        if (pnlEl) {
          pnlEl.textContent = fmtWon(pnlVal);
          pnlEl.style.color = pnlVal > 0 ? 'var(--green)' : pnlVal < 0 ? 'var(--red, #f85149)' : '';
        }
        if (pnlRateEl && acct.pnl_rate != null) {
          var rate = Number(acct.pnl_rate);
          pnlRateEl.textContent = (rate >= 0 ? '+' : '') + rate.toFixed(2) + '%';
          pnlRateEl.style.color = rate > 0 ? 'var(--green)' : rate < 0 ? 'var(--red, #f85149)' : 'var(--muted)';
        }

        // 당일 매수/매도
        setEl('tm-today-buy', fmtWon(acct.today_buy_amt));
        setEl('tm-today-sell', fmtWon(acct.today_sell_amt));
      }
    } catch(e) { console.warn("loadTradingMonitor account error", e); }

    // 오늘 적용 정책 로드
    try {
      var res = await fetch('/api/v1/trading-monitor/policy-summary');
      if (res.ok) {
        var data = await res.json();
        var p = data.payload || {};
        var dp = p.daily_plan || {};
        var setEl = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v || '미수집'; };
        setEl('tm-policy-buy-desc', dp.buy_condition_text);
        setEl('tm-policy-sell-desc', dp.sell_condition_text);
        setEl('tm-policy-risk-desc', dp.cash_usage_text);
      } else {
        // Fallback
        var rb = await fetch('/api/v1/rule/base').catch(() => null);
        if (rb && rb.ok) {
           var db = await rb.json();
           var el = document.getElementById('tm-policy-buy-desc');
           if (el) el.textContent = 'Base RulePack: ' + (db.payload?.id || '-');
        }
      }
    } catch(e) { console.warn("loadPolicySummary error", e); }

    // 매수 대기 후보 로드
    await loadTradingCandidates();
    // 보유 포지션 로드
    await loadTradingPositions();
  }

  async function loadTradingCandidates() {
    var container = document.getElementById('tm-buy-list');
    if (!container) return;
    try {
      var r = await fetch('/api/v1/trading-monitor/candidates');
      var d = await r.json();
      var candidates = d.payload && d.payload.candidates ? d.payload.candidates : [];
      
      if (!candidates.length) {
        container.innerHTML = '<div style="color:var(--muted); text-align:center; padding:20px 0; font-size:13px;">매수 대기 종목 없음</div>';
        return;
      }

      // Flicker reduction: row-by-row update
      var currentCodes = Array.from(container.querySelectorAll('[data-code]')).map(el => el.getAttribute('data-code'));
      var newCodes = candidates.map(c => c.code);

      // Remove gone
      currentCodes.forEach(code => {
        if (!newCodes.includes(code)) {
          var el = container.querySelector('[data-code="' + code + '"]');
          if (el) el.remove();
        }
      });

      // Update or Add
      candidates.forEach(c => {
        var html = renderCandidateRow(c);
        var existing = container.querySelector('[data-code="' + c.code + '"]');
        if (existing) {
          if (existing.innerHTML !== html) {
             existing.innerHTML = html;
          }
        } else {
          var div = document.createElement('div');
          div.setAttribute('data-code', c.code);
          div.innerHTML = html;
          container.appendChild(div);
        }
      });
    } catch(e) {
      console.warn("loadTradingCandidates error", e);
    }
  }

  function renderCandidateRow(c) {
    var readiness = c.buy_readiness || {};
    var pct = readiness.overall_pct || 0;
    var metCount = readiness.met_count || 0;
    var totalCount = readiness.total_count || 0;
    var conditions = readiness.conditions || [];

    var barColor = pct >= 70 ? '#3fb950' : pct >= 50 ? '#d29922' : '#f85149';
    var profileColors = {LOW_VOL:'#6cb6ff', MID_VOL:'#3fb950', HIGH_VOL:'#d29922', THEME_SPIKE:'#f85149'};
    var profileColor = profileColors[c.profile] || '#aaa';

    var conditionsHtml = conditions.map(function(cond) {
      var cColor = cond.met ? '#3fb950' : '#f85149';
      var cIcon = cond.met ? '✓' : '✗';
      var barW = Math.round(cond.score_pct);
      return '<tr>'
        + '<td style="padding:3px 6px; font-size:11px; color:var(--muted);">' + escapeHtml(cond.label || '') + '</td>'
        + '<td style="padding:3px 6px; font-size:11px;">' + escapeHtml(String(cond.current_value || '')) + '</td>'
        + '<td style="padding:3px 6px; font-size:11px; color:var(--muted);">' + escapeHtml(cond.threshold_label || '') + '</td>'
        + '<td style="padding:3px 6px; text-align:center; color:' + cColor + '; font-size:11px;">' + cIcon + '</td>'
        + '<td style="padding:3px 6px; min-width:80px;">'
        + '<div style="background:var(--panel-3); border-radius:3px; height:6px; width:100%; overflow:hidden;">'
        + '<div style="background:' + cColor + '; height:100%; width:' + barW + '%; transition:width 0.3s;"></div>'
        + '</div>'
        + '<span style="font-size:9px; color:var(--muted);">' + cond.score_pct + '%</span>'
        + '</td>'
        + '</tr>';
    }).join('');

    var rowId = 'cand-' + c.code;
    var detailId = 'cand-detail-' + c.code;

    return '<div style="border:1px solid var(--line); border-radius:6px; overflow:hidden;">'
      + '<div id="' + rowId + '" data-action="toggleCandidateDetail" data-code="' + escapeHtml(c.code) + '"'
      + ' style="display:flex; align-items:center; gap:10px; padding:8px 10px; cursor:pointer; background:var(--panel-2);">'
      + '<div style="min-width:80px;">'
      + '<div style="font-size:13px; font-weight:600;">' + escapeHtml(c.name || c.code) + '</div>'
      + '<div style="font-size:10px; color:' + profileColor + '; font-weight:600;">' + escapeHtml(c.profile || '') + '</div>'
      + '</div>'
      + '<div style="flex:1;">'
      + '<div style="display:flex; justify-content:space-between; font-size:10px; color:var(--muted); margin-bottom:2px;">'
      + '<span>매수 준비도</span>'
      + '<span style="font-weight:700; color:' + barColor + ';">' + pct + '%</span>'
      + '</div>'
      + '<div style="background:var(--bg,#0f141b); border-radius:4px; height:8px; overflow:hidden;">'
      + '<div style="background:' + barColor + '; height:100%; width:' + Math.round(pct) + '%; transition:width 0.5s;"></div>'
      + '</div>'
      + '<div style="display:flex; justify-content:space-between; font-size:10px; color:var(--muted); margin-top:3px;">'
      + '<span>현재가 ' + (c.latest_price ? Number(c.latest_price).toLocaleString() : '-') + '</span>'
      + '<span>' + escapeHtml(c.latest_trade_time || '') + '</span>'
      + '</div>'
      + '</div>'
      + '<div style="min-width:36px; text-align:center;">'
      + '<div style="font-size:11px; font-weight:700; color:' + barColor + ';">' + metCount + '/' + totalCount + '</div>'
      + '<div style="font-size:9px; color:var(--muted);">조건</div>'
      + '</div>'
      + '<div style="font-size:11px; color:' + (c.ws_subscribed ? '#3fb950' : 'var(--muted)') + ';">'
      + (c.ws_subscribed ? '● WS' : '○ WS')
      + '</div>'
      + '</div>'
      + '<div id="' + detailId + '" style="display:none; padding:8px 10px; background:var(--panel);">'
      + '<table style="width:100%; border-collapse:collapse;">'
      + '<thead><tr style="font-size:10px; color:var(--muted);">'
      + '<th style="text-align:left; padding:2px 6px;">조건</th>'
      + '<th style="text-align:left; padding:2px 6px;">현재값</th>'
      + '<th style="text-align:left; padding:2px 6px;">기준</th>'
      + '<th style="padding:2px 6px;">충족</th>'
      + '<th style="padding:2px 6px;">근접도</th>'
      + '</tr></thead>'
      + '<tbody>' + conditionsHtml + '</tbody>'
      + '</table>'
      + '<div style="margin-top:8px; font-size:11px; font-weight:600; color:' + barColor + '; text-align:right;">'
      + '종합 준비도 ' + pct + '% — ' + (pct >= 70 ? '매수 가능' : pct >= 50 ? '접근 중' : '조건 미달')
      + '</div>'
      + '</div>'
      + '</div>';
  }

  function toggleCandidateDetail(code) {
    var detailEl = document.getElementById('cand-detail-' + code);
    if (!detailEl) return;
    detailEl.style.display = detailEl.style.display === 'none' ? 'block' : 'none';
  }

  function stopTradingMonitorStream() {
    if (tmEventSource) {
      tmEventSource.close();
      tmEventSource = null;
    }
    if (tmRealtimeRefreshTimer) {
      clearTimeout(tmRealtimeRefreshTimer);
      tmRealtimeRefreshTimer = null;
    }
  }

  function scheduleTradingMonitorRealtimeRefresh() {
    var now = Date.now();
    var delay = Math.max(0, 500 - (now - tmLastRealtimeRefresh));
    if (tmRealtimeRefreshTimer) return;
    tmRealtimeRefreshTimer = setTimeout(function() {
      tmRealtimeRefreshTimer = null;
      tmLastRealtimeRefresh = Date.now();
      loadTradingCandidates();
      loadTradingPositions();
      loadLiveData();
    }, delay);
  }

  function startTradingMonitorStream() {
    stopTradingMonitorStream();
    if (!window.EventSource) {
      if (window._tmRefreshInterval) clearInterval(window._tmRefreshInterval);
      window._tmRefreshInterval = setInterval(function() {
        loadTradingCandidates();
        loadTradingPositions();
      }, 1000);
      return;
    }
    tmEventSource = new EventSource('/api/v1/trading-monitor/stream');
    tmEventSource.addEventListener('tick', scheduleTradingMonitorRealtimeRefresh);
    tmEventSource.addEventListener('heartbeat', function() {
      var b = document.getElementById("tm-buy-refresh-countdown");
      var s = document.getElementById("tm-sell-refresh-countdown");
      if (b) b.textContent = "LIVE";
      if (s) s.textContent = "LIVE";
    });
    tmEventSource.onerror = function() {
      var b = document.getElementById("tm-buy-refresh-countdown");
      var s = document.getElementById("tm-sell-refresh-countdown");
      if (b) b.textContent = "재연결";
      if (s) s.textContent = "재연결";
    };
  }

  async function loadTradingPositions() {
    var container = document.getElementById('tm-sell-list');
    if (!container) return;
    try {
      var r = await fetch('/api/v1/trading-monitor/positions');
      var d = await r.json();
      var positions = d.payload && d.payload.positions ? d.payload.positions : [];

      if (!positions.length) {
        container.innerHTML = '<div style="color:var(--muted); text-align:center; padding:20px 0; font-size:13px;">보유 포지션 없음</div>';
        return;
      }

      // Flicker reduction: row-by-row update
      Array.from(container.children).forEach(el => {
        if (!el.hasAttribute('data-symbol')) el.remove();
      });
      var currentSymbols = Array.from(container.querySelectorAll('[data-symbol]')).map(el => el.getAttribute('data-symbol'));
      var newSymbols = positions.map(p => p.symbol);

      // Remove gone
      currentSymbols.forEach(symbol => {
        if (!newSymbols.includes(symbol)) {
          var el = container.querySelector('[data-symbol="' + symbol + '"]');
          if (el) el.remove();
        }
      });

      // Update or Add
      positions.forEach(p => {
        var html = renderPositionRow(p);
        var existing = container.querySelector('[data-symbol="' + p.symbol + '"]');
        if (existing) {
          if (existing.innerHTML !== html) {
             existing.innerHTML = html;
          }
        } else {
          var div = document.createElement('div');
          div.setAttribute('data-symbol', p.symbol);
          div.style.marginBottom = "6px";
          div.innerHTML = html;
          container.appendChild(div);
        }
      });
    } catch(e) {
      console.warn("loadTradingPositions error", e);
    }
  }

  function renderPositionRow(p) {
    var entry = p.entry_price || 0;
    var current = p.market_price || entry;
    var pnlPct = entry > 0 ? ((current - entry) / entry * 100) : 0;
    var activeStop = p.active_stop_price || p.stop_loss_price || 0;
    var stopDistPct = current > 0 && activeStop > 0 ? ((current - activeStop) / current * 100) : 0;
    var highSince = p.highest_price_since_entry || entry;
    var trailingActive = p.trailing_active;
    var profile = p.profile_assigned || 'MID_VOL';
    var qty = p.qty || 0;
    var purchaseAmount = entry * qty;

    var pnlColor = pnlPct >= 0 ? '#3fb950' : '#f85149';
    var stopColor = stopDistPct < 1.0 ? '#f85149' : stopDistPct < 2.0 ? '#d29922' : '#3fb950';
    var stopBarW = Math.min(Math.max((stopDistPct / 5.0) * 100, 0), 100);
    var profileColors = {LOW_VOL:'#6cb6ff', MID_VOL:'#3fb950', HIGH_VOL:'#d29922', THEME_SPIKE:'#f85149'};
    var profileColor = profileColors[profile] || '#aaa';

    return '<div style="border:1px solid var(--line); border-radius:6px; padding:10px 12px; background:var(--panel-2);">'
      + '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">'
      + '<div>'
      + '<span style="font-size:13px; font-weight:600;">' + escapeHtml(p.name || p.symbol || '') + '</span>'
      + '<span style="font-size:10px; color:' + profileColor + '; font-weight:600; margin-left:6px;">' + escapeHtml(profile) + '</span>'
      + (trailingActive ? '<span style="font-size:10px; background:#1c3a1c; color:#3fb950; border-radius:3px; padding:1px 5px; margin-left:4px;">Trailing ON</span>' : '')
      + '</div>'
      + '<div style="font-size:13px; font-weight:700; color:' + pnlColor + ';">' + (pnlPct >= 0 ? '+' : '') + Math.round(pnlPct) + '%</div>'
      + '</div>'
      + '<div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:4px; font-size:11px; margin-bottom:8px;">'
      + '<div><span style="color:var(--muted);">진입가</span> ' + Math.round(entry).toLocaleString() + '</div>'
      + '<div><span style="color:var(--muted);">현재가</span> ' + Math.round(current).toLocaleString() + '</div>'
      + '<div><span style="color:var(--muted);">최고가</span> ' + Math.round(highSince).toLocaleString() + '</div>'
      + '<div><span style="color:var(--muted);">손절선</span> <span style="color:' + stopColor + '; font-weight:600;">' + Math.round(activeStop).toLocaleString() + '</span></div>'
      + '<div><span style="color:var(--muted);">수량</span> ' + qty.toLocaleString() + '주</div>'
      + '<div><span style="color:var(--muted);">매수금액</span> ' + Math.round(purchaseAmount).toLocaleString() + '원</div>'
      + '</div>'
      + '<div>'
      + '<div style="display:flex; justify-content:space-between; font-size:10px; color:var(--muted); margin-bottom:2px;">'
      + '<span>손절선까지 여유</span>'
      + '<span style="color:' + stopColor + '; font-weight:700;">' + stopDistPct.toFixed(1) + '%</span>'
      + '</div>'
      + '<div style="background:var(--panel-3); border-radius:4px; height:6px; overflow:hidden;">'
      + '<div style="background:' + stopColor + '; height:100%; width:' + stopBarW.toFixed(0) + '%; transition:width 0.5s;"></div>'
      + '</div>'
      + '</div>'
      + '</div>';
  }

  /* Toggle the Decision Engine from the Trading Monitor header and refresh status. */
  async function toggleDecisionEngine() {
    var btn = document.getElementById("tm-de-toggle");
    var isActive = btn && btn._deActive;
    if (isActive) {
      await liveDecisionDeactivate();
    } else {
      await liveDecisionActivate();
    }
    setTimeout(loadTradingMonitor, 500);
  }
