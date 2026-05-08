  async function refreshTodayControl() {
    await Promise.allSettled([
      loadConsoleData(),
      loadTodayAlertSummary(),
      loadTodayOrders(5)
    ]);
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
      setEl('tc-alert-critical', 'CRITICAL ' + critical);
      setEl('tc-alert-warning', 'WARNING ' + warning);
      setEl('tc-alert-unack', '미확인 ' + unack);
    } catch (e) { console.warn('loadTodayAlertSummary error', e); }
  }

  async function loadTodayOrders(limit) {
    try {
      var url = limit ? "/api/v1/orders/recent?limit=" + limit : "/api/v1/orders/today";
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

