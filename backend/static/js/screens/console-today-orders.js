  async function refreshTodayControl() {
    window._lastConsoleDataTs = Date.now();  // 수동 새로고침은 debounce 무시
    await Promise.allSettled([
      loadConsoleData(),
      loadTodayAlertSummary(),
      loadTodayOrders(5),
      loadKrIndexLive(),
      loadCumulativeReturn()
    ]);
  }

  // 라이브 국내지수(KOSPI/KOSDAQ) — Today Control 카드 2개
  async function loadKrIndexLive() {
    try {
      const res = await fetch('/api/v1/market/kr-index-live');
      if (!res.ok) return;
      const data = await res.json();
      if (!data.ok || !data.payload) return;
      const p = data.payload;
      const marketOpen = p.market_open === true;

      function renderCard(idx, priceId, changeId, badgeId) {
        const priceEl = document.getElementById(priceId);
        const changeEl = document.getElementById(changeId);
        const badgeEl = document.getElementById(badgeId);

        const price = idx ? idx.price : null;
        const rate = idx ? idx.change_rate : null;

        if (priceEl) {
          priceEl.textContent = (price != null)
            ? Number(price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
            : '-';
        }

        if (changeEl) {
          if (rate != null) {
            const sign = rate > 0 ? '+' : '';
            changeEl.textContent = sign + Number(rate).toFixed(2) + '%';
            // 상승=녹색, 하락=적색 (라이브 카드 — PM 지시)
            if (marketOpen) {
              changeEl.style.color = rate > 0 ? 'var(--good, #3fb950)' : (rate < 0 ? 'var(--bad, #f85149)' : '');
            } else {
              changeEl.style.color = '';
            }
          } else {
            changeEl.textContent = '-';
            changeEl.style.color = '';
          }
        }

        // 개장전 '장전' 배지, 장중 'LIVE' 배지
        if (badgeEl) {
          if (marketOpen) {
            badgeEl.textContent = 'LIVE';
            badgeEl.style.display = '';
          } else {
            badgeEl.textContent = '장전';
            badgeEl.style.display = '';
          }
        }
      }

      renderCard(p.kospi, 'tc-kospi-price', 'tc-kospi-change', 'tc-kospi-badge');
      renderCard(p.kosdaq, 'tc-kosdaq-price', 'tc-kosdaq-change', 'tc-kosdaq-badge');
    } catch (e) { console.warn('loadKrIndexLive error', e); }
  }

  // 누적 수익률 — Today Control 카드 (계좌 balance 기반)
  async function loadCumulativeReturn() {
    try {
      const res = await fetch('/api/v1/account/balance');
      if (!res.ok) return;
      const data = await res.json();
      const p = (data && data.payload) || {};
      const pnl = p.cumulative_pnl;
      const rate = p.cumulative_return_pct;

      const pnlEl = document.getElementById('tc-cum-pnl');
      const rateEl = document.getElementById('tc-cum-rate');

      if (pnlEl) {
        if (pnl != null && !isNaN(pnl)) {
          const sign = pnl >= 0 ? '+' : '';
          pnlEl.textContent = sign + Number(pnl).toLocaleString('en-US') + '원';
          pnlEl.style.color = pnl >= 0 ? 'var(--good, #3fb950)' : 'var(--bad, #f85149)';
        } else {
          pnlEl.textContent = '-';
          pnlEl.style.color = '';
        }
      }
      if (rateEl) {
        if (rate != null && !isNaN(rate)) {
          const sign = rate >= 0 ? '+' : '';
          rateEl.textContent = sign + Number(rate).toFixed(2) + '%';
          rateEl.style.color = rate >= 0 ? 'var(--good, #3fb950)' : 'var(--bad, #f85149)';
        } else {
          rateEl.textContent = '-';
          rateEl.style.color = '';
        }
      }
    } catch (e) { console.warn('loadCumulativeReturn error', e); }
  }

  async function loadTodayAlertSummary() {
    try {
      const res = await fetch('/api/v1/alerts/summary');
      if (!res.ok) return;
      const data = await res.json();
      const s = data.payload || {};
      
      // 실제 API 필드명 기준: total_count, severity_counts.CRITICAL, severity_counts.WARNING, unacknowledged_count
      const total = s.total_count ?? 0;
      const critical = s.severity_counts?.CRITICAL ?? 0;
      const warning = s.severity_counts?.WARNING ?? 0;
      const unack = s.unacknowledged_count ?? 0;

      const setEl = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
      setEl('tc-alert-count', total);
      setEl('tc-alert-detail', '위험 ' + critical + ' · 경고 ' + warning + ' · 미확인 ' + unack);
      // 위험(CRITICAL) 알림이 있을 때만 숫자 강조(빨강), 없으면 기본색
      const cntEl = document.getElementById('tc-alert-count');
      if (cntEl) cntEl.style.color = critical > 0 ? 'var(--bad, #f85149)' : '';
    } catch (e) { console.warn('loadTodayAlertSummary error', e); }
  }

  async function loadTodayOrders(limit, tradeDate) {
    try {
      var url;
      if (limit) {
        url = "/api/v1/orders/recent?limit=" + limit;
      } else if (tradeDate) {
        url = "/api/v1/orders/today?trade_date=" + tradeDate;
      } else {
        url = "/api/v1/orders/today";
      }
      var data = await fetchJson(url);
      var hasLegacyTbody = Boolean(document.getElementById("orders-today-tbody"));
      var hasTradingTbody = Boolean(document.getElementById("tm-orders-tbody"));
      if (!hasLegacyTbody && !hasTradingTbody) return;

      var orders = data.payload.orders || [];
      var legacyRowsHtml = "";
      var tradingRowsHtml = "";
      if (orders.length === 0) {
        legacyRowsHtml = '<tr><td colspan="7" class="muted" style="text-align:center;">오늘 주문 없음</td></tr>';
        tradingRowsHtml = '<tr><td colspan="6" class="muted" style="text-align:center;">오늘 주문 없음</td></tr>';
      } else {
        var statusBadgeMap = {
          "filled":    '<span class="status ok">체결</span>',
          "submitted": '<span class="status warn">대기중</span>',
          "failed":    '<span class="status bad">실패</span>',
          "cancelled": '<span class="muted" style="font-size:11px;">취소</span>',
          "preflight_blocked": '<span class="status bad">차단</span>'
        };
        legacyRowsHtml = orders.map(function(ord) {
          var sideLabel = ord.side === "buy" ? "매수" : "매도";
          var statusHtml = statusBadgeMap[ord.status] || '<span class="muted">' + escapeHtml(ord.status) + '</span>';
          var timeStr = (ord.created_at || "").split("T")[1] || "";
          if (timeStr.includes(".")) timeStr = timeStr.split(".")[0];

          return '<tr>'
            + '<td>' + timeStr + '</td>'
            + '<td>' + (ord.symbol || "") + (ord.name ? " (" + ord.name + ")" : "") + '</td>'
            + '<td>' + sideLabel + '</td>'
            + '<td>' + (ord.qty || 0).toLocaleString() + '</td>'
            + '<td>' + (ord.price || 0).toLocaleString() + '</td>'
            + '<td>' + (ord.kis_order_no || "-") + '</td>'
            + '<td>' + statusHtml + '</td>'
            + '</tr>';
        }).join("");
        tradingRowsHtml = orders.map(function(ord) {
          var sideLabel = ord.side === "buy" ? "매수" : "매도";
          var statusHtml = statusBadgeMap[ord.status] || '<span class="muted">' + escapeHtml(ord.status) + '</span>';
          var timeStr = (ord.created_at || "").split("T")[1] || "";
          if (timeStr.includes(".")) timeStr = timeStr.split(".")[0];

          return '<tr>'
            + '<td>' + escapeHtml(timeStr) + '</td>'
            + '<td>' + escapeHtml(ord.symbol || "") + (ord.name ? '<br><span class="muted" style="font-size:11px;">' + escapeHtml(ord.name) + '</span>' : '') + '</td>'
            + '<td>' + escapeHtml(sideLabel) + '</td>'
            + '<td>' + (ord.qty || 0).toLocaleString() + '</td>'
            + '<td>' + (ord.price || 0).toLocaleString() + '</td>'
            + '<td>' + statusHtml + '</td>'
            + '</tr>';
        }).join("");
      }
      setHtmlForIds(["orders-today-tbody"], legacyRowsHtml);
      setHtmlForIds(["tm-orders-tbody"], tradingRowsHtml);

      // 모바일 주문 카드 렌더링
      var isMobile = window.innerWidth <= 860;
      var cardContainer = document.getElementById("todayOrderCards");
      if (cardContainer) {
        cardContainer.style.display = isMobile ? "grid" : "none";
        // 테이블 래퍼 숨김/표시 (CSS가 display:none 처리하지만 JS에서도 확실히 함)
        var tableWrap = cardContainer.previousElementSibling;
        if (tableWrap && tableWrap.classList.contains('table-wrap')) {
          tableWrap.style.display = isMobile ? "none" : "block";
        }
      }
      if (isMobile) {
        renderTodayOrderCards(orders);
      }
    } catch (e) {
      setHtmlForIds(
        ["orders-today-tbody"],
        '<tr><td colspan="7" class="muted" style="text-align:center;">불러오기 실패: ' + escapeHtml(e.message) + '</td></tr>'
      );
      setHtmlForIds(
        ["tm-orders-tbody"],
        '<tr><td colspan="6" class="muted" style="text-align:center;">불러오기 실패: ' + escapeHtml(e.message) + '</td></tr>'
      );
    }
  }

  function renderTodayOrderCards(orders) {
    var container = document.getElementById("todayOrderCards");
    if (!container) return;
    if (!orders || orders.length === 0) {
      container.innerHTML = '<div style="grid-column: 1 / -1; padding:20px; text-align:center; color:var(--muted);">오늘 주문 없음</div>';
      return;
    }
    container.innerHTML = orders.map(function(ord) {
      var sideLabel = ord.side === "buy" ? "매수" : "매도";
      var sideClass = ord.side === "buy" ? "toc-side-buy" : "toc-side-sell";
      var timeStr = (ord.created_at || "").split("T")[1] || "";
      if (timeStr.includes(".")) timeStr = timeStr.split(".")[0];
      return [
        '<div class="today-order-card">',
          '<div class="toc-symbol">' + escapeHtml(ord.symbol) + '</div>',
          '<div style="font-size:11px; margin-bottom:6px;">' + escapeHtml(ord.name || '') + '</div>',
          '<div class="toc-meta">',
            '<div class="' + sideClass + '" style="font-weight:700;">' + sideLabel + '</div>',
            '<div>수량 ' + (ord.qty || 0).toLocaleString() + '</div>',
            '<div>가격 ' + (ord.price || 0).toLocaleString() + '</div>',
            '<div style="margin-top:4px; font-weight:600;">' + escapeHtml(ord.status) + '</div>',
            '<div style="font-size:10px;">' + timeStr + '</div>',
          '</div>',
        '</div>'
      ].join('');
    }).join('');
  }


