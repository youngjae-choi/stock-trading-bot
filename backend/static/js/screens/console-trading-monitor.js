  var tmEventSource = null;
  var tmRealtimeRefreshTimer = null;
  var tmLastRealtimeRefresh = 0;
  var tmBalanceTimer = null;
  var tmLastBalanceRefresh = 0;
  var TM_BALANCE_INTERVAL = 15000; // 15초마다 예수금 갱신

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

    // 계좌 정보 로드 (초기 + 주기적 갱신은 refreshTradingMonitorBalance()로 위임)
    await refreshTradingMonitorBalance();

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

    // 장중 재선별 상태 로드
    await loadIntradayRefreshStatus();
    // 매수 대기 후보 로드
    await loadTradingCandidates();
    // 보유 포지션 로드
    await loadTradingPositions();
  }

  async function loadIntradayRefreshStatus() {
    var el = document.getElementById('tm-intraday-refresh-status');
    if (!el) return;
    try {
      var d = await fetchJson('/api/v1/trading-monitor/intraday-refresh-status');
      var logs = (d && d.payload) ? d.payload : [];
      if (logs.length === 0) {
        el.innerHTML = '<span style="color:var(--muted); font-size:12px;">재선별 없음</span>';
        return;
      }
      var parts = logs.map(function(log) {
        var slot = escapeHtml(log.slot || '?');
        if (log.triggered) {
          var avgStr = log.avg_change != null ? (log.avg_change >= 0 ? '+' : '') + log.avg_change.toFixed(1) + '%' : '';
          var newCount = (log.reselection && log.reselection.s6) ? (log.reselection.s6.new_count || '?') : '?';
          return '<span class="status ok" title="' + escapeHtml(log.reason || '') + '">♻️ ' + slot + ' ' + avgStr + ' →' + newCount + '종목</span>';
        } else if (log.ran) {
          return '<span class="status" style="color:var(--muted); font-size:11px;" title="' + escapeHtml(log.reason || '') + '">' + slot + ' 스킵</span>';
        }
        return '';
      }).filter(Boolean);
      el.innerHTML = parts.join(' ');
    } catch(e) {
      el.innerHTML = '';
    }
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

      // 현재 열려 있는 detail 목록 저장 (갱신 후 복원용)
      var openDetails = {};
      container.querySelectorAll('[id^="cand-detail-"]').forEach(function(el) {
        if (el.style.display !== 'none') {
          openDetails[el.id] = true;
        }
      });

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

      // 열려 있던 detail 복원
      Object.keys(openDetails).forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.style.display = 'block';
      });
    } catch(e) {
      console.warn("loadTradingCandidates error", e);
    }
  }

  /* 후보 선정사유 한 줄 요약 (sources · llm_note) */
  function _candidateSelectionText(c) {
    var sr = c.selection_reason || {};
    var sources = (sr.sources || []).map(function(s) { return String(s); }).join(" · ");
    var note = (sr.llm_note || "").trim();
    if (sources && note) return sources + " · " + note;
    return sources || note || "";
  }

  /* Legacy flat-conditions render (back-compat when readiness.mode !== "or_groups"). */
  function _renderCandidateRowLegacy(c) {
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
      + (function() {
          var selText = _candidateSelectionText(c);
          return selText
            ? '<div style="padding:4px 10px; font-size:11px; color:var(--muted); background:var(--panel);">'
              + '<span style="color:var(--accent);">선정사유</span> ' + escapeHtml(selText) + '</div>'
            : '';
        })()
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

  /* OR-group readiness render: per-GROUP rows + overall "매수 가능(OR)" badge. */
  function renderCandidateRow(c) {
    var readiness = c.buy_readiness || {};
    // back-compat: 옛 평면 조건 응답이면 레거시 렌더로 폴백.
    if (readiness.mode !== 'or_groups') {
      return _renderCandidateRowLegacy(c);
    }

    var groups = readiness.groups || [];
    var anyMet = Boolean(readiness.any_met);
    var pct = readiness.overall_pct || 0;

    var profileColors = {LOW_VOL:'#6cb6ff', MID_VOL:'#3fb950', HIGH_VOL:'#d29922', THEME_SPIKE:'#f85149'};
    var profileColor = profileColors[c.profile] || '#aaa';

    var badgeColor = anyMet ? '#3fb950' : '#f85149';
    var badgeBg = anyMet ? '#12351f' : '#3b1d1d';
    var badgeText = anyMet ? '매수 가능(OR)' : '조건 미달';

    // 헤더에 보이는 그룹 요약 행 (그룹명 + met_count/total + ✓/✗)
    var groupSummaryHtml = groups.map(function(g) {
      var gColor = g.met ? '#3fb950' : 'var(--muted)';
      var gIcon = g.met ? '✓' : '✗';
      return '<div style="display:flex; justify-content:space-between; align-items:center; font-size:10px; padding:1px 0;">'
        + '<span style="color:' + (g.met ? '#3fb950' : 'var(--muted)') + ';">' + gIcon + ' ' + escapeHtml(g.name || '') + '</span>'
        + '<span style="color:' + gColor + '; font-weight:600;">' + (g.met_count || 0) + '/' + (g.total || 0) + '</span>'
        + '</div>';
    }).join('');

    // 상세: 각 그룹별 조건표 (조건명·현재값·기준·충족)
    var detailHtml = groups.map(function(g) {
      var gColor = g.met ? '#3fb950' : '#f85149';
      var condRows = (g.conditions || []).map(function(cond) {
        var cColor = cond.met ? '#3fb950' : '#f85149';
        var cIcon = cond.met ? '✓' : '✗';
        return '<tr>'
          + '<td style="padding:3px 6px; font-size:11px; color:var(--muted);">' + escapeHtml(cond.label || cond.name || '') + '</td>'
          + '<td style="padding:3px 6px; font-size:11px;">' + escapeHtml(String(cond.current_value != null ? cond.current_value : '')) + '</td>'
          + '<td style="padding:3px 6px; font-size:11px; color:var(--muted);">' + escapeHtml(cond.threshold_label || '') + '</td>'
          + '<td style="padding:3px 6px; text-align:center; color:' + cColor + '; font-size:11px;">' + cIcon + '</td>'
          + '</tr>';
      }).join('');
      return '<div style="margin-bottom:8px;">'
        + '<div style="display:flex; justify-content:space-between; align-items:center; font-size:11px; font-weight:600; margin-bottom:3px;">'
        + '<span style="color:' + gColor + ';">' + (g.met ? '✓' : '✗') + ' ' + escapeHtml(g.name || '') + ' 그룹</span>'
        + '<span style="color:' + gColor + ';">' + (g.met_count || 0) + '/' + (g.total || 0) + (g.met ? ' · 충족' : '') + '</span>'
        + '</div>'
        + '<table style="width:100%; border-collapse:collapse;">'
        + '<thead><tr style="font-size:10px; color:var(--muted);">'
        + '<th style="text-align:left; padding:2px 6px;">조건</th>'
        + '<th style="text-align:left; padding:2px 6px;">현재값</th>'
        + '<th style="text-align:left; padding:2px 6px;">기준</th>'
        + '<th style="padding:2px 6px;">충족</th>'
        + '</tr></thead>'
        + '<tbody>' + condRows + '</tbody>'
        + '</table>'
        + '</div>';
    }).join('');

    var rowId = 'cand-' + c.code;
    var detailId = 'cand-detail-' + c.code;

    return '<div style="border:1px solid var(--line); border-radius:6px; overflow:hidden;">'
      + '<div id="' + rowId + '" data-action="toggleCandidateDetail" data-code="' + escapeHtml(c.code) + '"'
      + ' style="display:flex; align-items:flex-start; gap:10px; padding:8px 10px; cursor:pointer; background:var(--panel-2);">'
      + '<div style="min-width:80px;">'
      + '<div style="font-size:13px; font-weight:600;">' + escapeHtml(c.name || c.code) + '</div>'
      + '<div style="font-size:10px; color:' + profileColor + '; font-weight:600;">' + escapeHtml(c.profile || '') + '</div>'
      + '<div style="font-size:10px; color:var(--muted); margin-top:3px;">현재가 ' + (c.latest_price ? Number(c.latest_price).toLocaleString() : '-') + '</div>'
      + '</div>'
      + '<div style="flex:1;">'
      + '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">'
      + '<span style="font-size:10px; font-weight:700; color:' + badgeColor + '; background:' + badgeBg + '; border:1px solid ' + badgeColor + '; border-radius:3px; padding:1px 6px;">' + badgeText + '</span>'
      + '<span style="font-size:10px; color:var(--muted);">근접 ' + pct + '%</span>'
      + '</div>'
      + groupSummaryHtml
      + '</div>'
      + '<div style="font-size:11px; color:' + (c.ws_subscribed ? '#3fb950' : 'var(--muted)') + '; min-width:34px; text-align:right;">'
      + (c.ws_subscribed ? '● WS' : '○ WS')
      + '</div>'
      + '</div>'
      + (function() {
          var selText = _candidateSelectionText(c);
          return selText
            ? '<div style="padding:4px 10px; font-size:11px; color:var(--muted); background:var(--panel);">'
              + '<span style="color:var(--accent);">선정사유</span> ' + escapeHtml(selText) + '</div>'
            : '';
        })()
      + '<div id="' + detailId + '" style="display:none; padding:8px 10px; background:var(--panel);">'
      + detailHtml
      + '<div style="margin-top:4px; font-size:11px; font-weight:600; color:' + badgeColor + '; text-align:right;">'
      + (anyMet ? '한 그룹 이상 충족 — 매수 가능(OR)' : '충족 그룹 없음 — 조건 미달')
      + '</div>'
      + '</div>'
      + '</div>';
  }

  function toggleCandidateDetail(code) {
    var detailEl = document.getElementById('cand-detail-' + code);
    if (!detailEl) return;
    detailEl.style.display = detailEl.style.display === 'none' ? 'block' : 'none';
  }

  /* 계좌 잔고(예수금) 갱신 — 초기 로드 및 15초 타이머에서 호출 */
  async function refreshTradingMonitorBalance() {
    var _setSyncStatus = function(ok, msg) {
      var el = document.getElementById('tm-sync-status');
      var timeEl = document.getElementById('tm-sync-time');
      if (el) {
        el.textContent = ok ? '● KIS 연결됨' : '✕ ' + (msg || '연결 실패');
        el.style.background = ok ? 'rgba(63,185,80,0.15)' : 'rgba(248,81,73,0.15)';
        el.style.color = ok ? 'var(--green)' : 'var(--red, #f85149)';
      }
      if (timeEl) {
        var now = new Date();
        timeEl.textContent = now.getHours().toString().padStart(2,'0') + ':' +
          now.getMinutes().toString().padStart(2,'0') + ':' +
          now.getSeconds().toString().padStart(2,'0');
      }
    };
    try {
      var accountData = await fetchJson("/api/v1/account/balance");
      if (accountData && accountData.ok && accountData.payload) {
        var acct = accountData.payload;
        var setEl = function(id, v) { var el = document.getElementById(id); if (el) el.textContent = v; };
        var fmtWon = function(v) { return v != null ? Number(v).toLocaleString() + '원' : '-'; };

        _setSyncStatus(true);
        setEl('tm-account-no', acct.account_no ? '· ' + acct.account_no : '');

        // 주문가능 예수금 (nxdy_excc_amt 기반, buyable_cash)
        var buyable = acct.buyable_cash != null ? acct.buyable_cash : acct.available_cash;
        setEl('tm-buyable-cash', fmtWon(buyable));
        setEl('tm-deposit-limit', '한도 ' + fmtWon(acct.deposit));

        // 정산예정금 (모의투자 가수도 정산분) — 주문가능이 예수금보다 큰 차이를 따로 표기
        var settleEl = document.getElementById('tm-settlement');
        if (settleEl) {
          var settle = acct.settlement_pending != null ? Number(acct.settlement_pending) : 0;
          if (settle !== 0) {
            settleEl.textContent = '정산예정 ' + (settle > 0 ? '+' : '') + Number(settle).toLocaleString() + '원';
            settleEl.style.display = '';
          } else {
            settleEl.textContent = '';
            settleEl.style.display = 'none';
          }
        }

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

        tmLastBalanceRefresh = Date.now();
      } else {
        _setSyncStatus(false, accountData && accountData.error ? accountData.error : 'API 오류');
      }
    } catch(e) {
      _setSyncStatus(false, 'KIS 연결 오류');
      console.warn("refreshTradingMonitorBalance error", e);
    }
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
    if (tmBalanceTimer) {
      clearInterval(tmBalanceTimer);
      tmBalanceTimer = null;
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
    // 예수금 15초 주기 갱신 타이머 (SSE tick과 독립)
    tmBalanceTimer = setInterval(function() {
      refreshTradingMonitorBalance();
    }, TM_BALANCE_INTERVAL);

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

      // 모바일이면 카드 표시, 아니면 숨김
      var isMobile = window.innerWidth <= 860;
      var cardList = document.getElementById('tmCardList');
      if (cardList) {
        cardList.style.display = isMobile ? 'flex' : 'none';
        // 기존 리스트는 모바일에서 숨김
        container.style.display = isMobile ? 'none' : 'flex';
      }
      if (isMobile) renderPositionCards(positions);

    } catch(e) {
      console.warn("loadTradingPositions error", e);
    }
  }

  /**
   * 모바일 카드 렌더 — 860px 이하에서만 표시
   */
  function renderPositionCards(positions) {
    var container = document.getElementById('tmCardList');
    if (!container) return;

    if (!positions || positions.length === 0) {
      container.innerHTML = '<div style="padding:24px;text-align:center;color:var(--muted);font-size:13px;">보유 포지션 없음</div>';
      return;
    }

    container.innerHTML = positions.map(function(p) {
      // 데이터 매핑
      var entry = p.entry_price || 0;
      var current = p.market_price || entry;
      var pnlPct = entry > 0 ? ((current - entry) / entry) : 0;
      var stopLoss = p.active_stop_price || p.stop_loss_price || 0;
      var qty = p.qty || 0;

      var pnlPctDisp = pnlPct * 100;
      var pnlClass = pnlPctDisp >= 0 ? 'positive' : 'negative';
      var pnlSign = pnlPctDisp >= 0 ? '+' : '';

      // 손절 게이지: current 가 entry 에서 stop_loss 까지 얼마나 왔는지
      var stopFillPct = 0;
      var stopClass = 'safe';
      if (entry && stopLoss && current) {
        var range = entry - stopLoss;
        var gone = entry - current;
        stopFillPct = range > 0 ? Math.min(100, Math.max(0, (gone / range) * 100)) : 0;
        stopClass = stopFillPct > 80 ? 'danger' : stopFillPct > 50 ? 'warn' : 'safe';
      }

      var badgeClass = (p.status === 'sell' || p.status === 'closing') ? 'sell' : 'hold';
      var badgeLabel = badgeClass === 'sell' ? '매도중' : '보유';

      return [
        '<div class="tm-card">',
          '<div class="tm-card-header">',
            '<div>',
              '<div class="tm-card-symbol">' + (p.symbol || '') + '</div>',
              '<div class="tm-card-name">' + (p.name || '') + '</div>',
            '</div>',
            '<div class="tm-card-pnl ' + pnlClass + '">' + pnlSign + pnlPctDisp.toFixed(2) + '%</div>',
          '</div>',
          '<span class="tm-card-badge ' + badgeClass + '">' + badgeLabel + '</span>',
          '<div class="tm-card-meta">',
            '<span>평균가 <strong>' + fmtPrice(entry) + '</strong></span>',
            '<span>현재가 <strong>' + fmtPrice(current) + '</strong></span>',
            '<span>수량 <strong>' + (qty || 0) + '주</strong></span>',
            '<span>손절가 <strong>' + fmtPrice(stopLoss) + '</strong></span>',
          '</div>',
          '<div class="tm-stop-bar-wrap">',
            '<div class="tm-stop-bar-label">',
              '<span>손절 여유</span>',
              '<span>' + (100 - stopFillPct).toFixed(0) + '%</span>',
            '</div>',
            '<div class="tm-stop-bar">',
              '<div class="tm-stop-bar-fill ' + stopClass + '" style="width:' + stopFillPct.toFixed(1) + '%"></div>',
            '</div>',
          '</div>',
        '</div>'
      ].join('');
    }).join('');
  }

  function fmtPrice(v) {
    if (v == null) return '-';
    return Number(v).toLocaleString('ko-KR') + '원';
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
    var monitoringStatus = p.monitoring_status || (p.auto_monitoring ? '자동감시중' : '미감시');
    var monitoringDetail = p.monitoring_detail || '';
    var monitoringOk = monitoringStatus === '자동감시중';
    var monitoringBg = monitoringOk ? '#12351f' : '#3b1d1d';
    var monitoringColor = monitoringOk ? '#3fb950' : '#f85149';
    var monitoringBorder = monitoringOk ? 'rgba(63,185,80,.45)' : 'rgba(248,81,73,.45)';
    var monitoringTitle = monitoringDetail
      + (p.ws_subscribed === false ? ' · 실시간 미구독' : '')
      + (p.position_manager_registered === false ? ' · S8 미등록' : '')
      + (p.stop_state_source === 'fallback' ? ' · fallback 손절선' : '');
    var timedStatus = p.timed_liquidation_status || (p.timed_liquidation_target ? '시간청산 대상' : '시간청산 제외');

    return '<div style="border:1px solid var(--line); border-radius:6px; padding:10px 12px; background:var(--panel-2);">'
      + '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">'
      + '<div>'
      + '<span style="font-size:13px; font-weight:600;">' + escapeHtml(p.name || p.symbol || '') + '</span>'
      + '<span style="font-size:10px; color:' + profileColor + '; font-weight:600; margin-left:6px;">' + escapeHtml(profile) + '</span>'
      + (trailingActive ? '<span style="font-size:10px; background:#1c3a1c; color:#3fb950; border-radius:3px; padding:1px 5px; margin-left:4px;">Trailing ON</span>' : '')
      + '<span title="' + escapeHtml(monitoringTitle) + '" style="font-size:10px; background:' + monitoringBg + '; color:' + monitoringColor + '; border:1px solid ' + monitoringBorder + '; border-radius:3px; padding:1px 5px; margin-left:4px; font-weight:700;">' + escapeHtml(monitoringStatus) + '</span>'
      + '<span title="관리자 지정 청산 시간에는 계좌 실보유 전체 시장가 매도 대상" style="font-size:10px; background:#2f260c; color:#f0b429; border:1px solid rgba(240,180,41,.45); border-radius:3px; padding:1px 5px; margin-left:4px; font-weight:700;">' + escapeHtml(timedStatus) + '</span>'
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
      + '<div><span style="color:var(--muted);">S8등록</span> ' + (p.position_manager_registered ? '예' : '아니오') + '</div>'
      + '<div><span style="color:var(--muted);">실시간</span> ' + (p.ws_subscribed ? '구독중' : '미구독') + '</div>'
      + '<div><span style="color:var(--muted);">상태원천</span> ' + escapeHtml(p.stop_state_source || '-') + '</div>'
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
