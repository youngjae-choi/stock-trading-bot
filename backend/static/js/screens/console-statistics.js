  var stAllItems = [];
  var stFilter = "today";

  function setStatsFilter(filter) {
    stFilter = filter;
    ["today", "week", "all", "month", "lastmonth"].forEach(function(f) {
      var btn = document.getElementById("sf-" + f);
      if (btn) btn.className = "btn" + (f === filter ? " primary" : "");
    });
    renderStatsSummary();
    loadAllOrders();
  }

  function filterStItems(items) {
    if (stFilter === "all") return items;
    var now = new Date();
    var year = now.getFullYear();
    var month = String(now.getMonth() + 1).padStart(2, "0");
    var todayStr = year + "-" + month + "-" + String(now.getDate()).padStart(2, "0");
    if (stFilter === "today") {
      return items.filter(function(i) { return (i.trade_date || "") === todayStr; });
    }
    if (stFilter === "week") {
      var day = now.getDay();
      var monday = new Date(now);
      monday.setDate(now.getDate() - (day === 0 ? 6 : day - 1));
      var mondayStr = monday.getFullYear() + "-" + String(monday.getMonth() + 1).padStart(2, "0") + "-" + String(monday.getDate()).padStart(2, "0");
      return items.filter(function(i) { return (i.trade_date || "") >= mondayStr; });
    }
    if (stFilter === "month") {
      var prefix = year + "-" + month;
      return items.filter(function(i) { return (i.trade_date || "").startsWith(prefix); });
    }
    if (stFilter === "lastmonth") {
      var lm = now.getMonth() === 0 ? 12 : now.getMonth();
      var ly = now.getMonth() === 0 ? year - 1 : year;
      var lmStr = ly + "-" + String(lm).padStart(2, "0");
      return items.filter(function(i) { return (i.trade_date || "").startsWith(lmStr); });
    }
    return items;
  }

  async function loadStatistics() {
    try {
      var data = await fetchJson("/api/v1/trades/history?limit=120");
      stAllItems = (data.payload && data.payload.items) || [];
      renderStatsSummary();
    } catch (e) {
      console.error("[ERROR]", "loadStatistics", "-", e.message);
      stAllItems = [];
      renderStatsSummary();
    }
  }

  function renderStatsSummary() {
    var items = filterStItems(stAllItems || []);
    var days = items.length;
    var totalOrders = 0, profitDays = 0, pnlSum = 0;
    items.forEach(function(item) {
      totalOrders += item.total_orders || 0;
      pnlSum += item.realized_pnl_pct || 0;
      if ((item.realized_pnl_pct || 0) > 0) profitDays++;
    });
    var winrate = days > 0 ? Math.round(profitDays / days * 100) : 0;
    var avgPnl = days > 0 ? pnlSum / days : 0;

    function setST(id, text, cls) {
      var el = document.getElementById(id);
      if (el) { el.textContent = text; if (cls) el.className = "metric " + cls; }
    }
    setST("st-days", days + "일");
    setST("st-orders", totalOrders + "건");
    setST("st-winrate", winrate + "%", winrate >= 50 ? "good" : "warn");
    var wd = document.getElementById("st-winrate-detail");
    if (wd) wd.textContent = profitDays + "수익일 / " + days + "거래일";
    setST("st-pnl", (pnlSum >= 0 ? "+" : "") + pnlSum.toFixed(2) + "%", pnlSum >= 0 ? "good" : "bad");
    setST("st-avg-pnl", (avgPnl >= 0 ? "+" : "") + avgPnl.toFixed(2) + "%", avgPnl >= 0 ? "good" : "bad");

  }

  /* Load the Trade History order table for the active period filter. */
  async function loadAllOrders() {
    var tbody = document.getElementById("st-orders-tbody");
    var title = document.getElementById("st-table-title");
    var sourceEl = document.getElementById("st-table-source");
    if (tbody) tbody.innerHTML = '<tr><td colspan="9" class="muted" style="text-align:center;">로딩중...</td></tr>';

    try {
      var orders = [];
      if (stFilter === "today") {
        var todayResponse = await fetchJson("/api/v1/orders/today");
        orders = (todayResponse && todayResponse.payload && todayResponse.payload.orders) || [];
        if (sourceEl) sourceEl.textContent = 'trading_orders 오늘 주문 이벤트';
      } else {
        var now = new Date();
        var todayStr = now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0") + "-" + String(now.getDate()).padStart(2, "0");
        var startStr = todayStr;
        if (stFilter === "week") {
          var day = now.getDay();
          var monday = new Date(now);
          monday.setDate(now.getDate() - (day === 0 ? 6 : day - 1));
          startStr = monday.getFullYear() + "-" + String(monday.getMonth() + 1).padStart(2, "0") + "-" + String(monday.getDate()).padStart(2, "0");
        } else if (stFilter === "month") {
          startStr = now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0") + "-01";
        } else if (stFilter === "lastmonth") {
          var lm = new Date(now.getFullYear(), now.getMonth() - 1, 1);
          var lmEnd = new Date(now.getFullYear(), now.getMonth(), 0);
          startStr = lm.getFullYear() + "-" + String(lm.getMonth() + 1).padStart(2, "0") + "-01";
          todayStr = lmEnd.getFullYear() + "-" + String(lmEnd.getMonth() + 1).padStart(2, "0") + "-" + String(lmEnd.getDate()).padStart(2, "0");
        } else if (stFilter === "all") {
          startStr = "2020-01-01";
        }
        var rangeResponse = await fetchJson("/api/v1/orders/range?start=" + startStr + "&end=" + todayStr + "&limit=500");
        orders = (rangeResponse && rangeResponse.payload && rangeResponse.payload.orders) || [];
        if (sourceEl) sourceEl.textContent = (rangeResponse && rangeResponse.payload && rangeResponse.payload.history_scope === 'all_order_events') ? 'trading_orders 전체 주문 이벤트' : '주문 이력';
      }

      if (stFilter === "today") {
        var now = new Date();
        var todayStr = now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0") + "-" + String(now.getDate()).padStart(2, "0");
        orders = orders.filter(function(o) { return (o.trade_date || (o.created_at || "").slice(0, 10) || todayStr) === todayStr; });
      }

      var filterLabel = { today: "오늘", week: "이번주", month: "이번달", lastmonth: "지난달", all: "전체" };
      if (title) title.textContent = (filterLabel[stFilter] || "") + " 주문 내역";

      renderOrdersTable(orders, "데이터 없음: 해당 기간 주문 이벤트 없음");
    } catch (e) {
      console.error("[ERROR]", "loadAllOrders", "-", e.message);
      if (tbody) tbody.innerHTML = '<tr><td colspan="9" class="muted" style="text-align:center;">실행 실패: 주문 이력 조회 실패 - ' + escapeHtml(e.message || "") + '</td></tr>';
    }
  }

  /* Render order-like records from orders or decision signals into the unified table. */
  function renderOrdersTable(orders, emptyMessage) {
    var tbody = document.getElementById("st-orders-tbody");
    if (!tbody) return;
    if (!orders || orders.length === 0) {
      tbody.innerHTML = '<tr><td colspan="9" class="muted" style="text-align:center;">' + escapeHtml(emptyMessage || "주문 없음") + '</td></tr>';
      return;
    }

    tbody.innerHTML = orders.map(function(o) {
      var rawSide = o.side || o.action || "buy";
      var side = rawSide === "buy" ? '<span class="status ok">매수</span>' : '<span class="status warn">매도</span>';
      var statusMap = { executed: "체결", filled: "체결", completed: "체결", pending: "대기", submitted: "접수", failed: "실패", cancelled: "취소" };
      var rawStatus = o.status || o.signal_status || "pending";
      var statusCls = (rawStatus === "executed" || rawStatus === "filled" || rawStatus === "completed") ? "ok" : (rawStatus === "failed" || rawStatus === "cancelled") ? "danger" : "warn";
      var statusLabel = statusMap[rawStatus] || rawStatus || "-";
      var timeStr = (o.created_at || o.time || "").slice(0, 19).replace("T", " ");
      var price = o.price != null ? o.price : (o.entry_price != null ? o.entry_price : o.target_price);
      var profileColors = {LOW_VOL:'#6cb6ff', MID_VOL:'#3fb950', HIGH_VOL:'#d29922', THEME_SPIKE:'#f85149'};
      var profile = o.risk_profile || o.profile_assigned || '-';
      var profileColor = profileColors[profile] || 'var(--muted)';
      return '<tr>'
        + '<td style="font-size:12px;">' + escapeHtml(timeStr || "-") + '</td>'
        + '<td>' + escapeHtml(o.name || o.symbol_name || "-") + '</td>'
        + '<td style="font-size:12px; color:var(--muted);">' + escapeHtml(o.symbol || "-") + '</td>'
        + '<td>' + side + '</td>'
        + '<td>' + escapeHtml(String(o.qty || o.quantity || "-")) + '</td>'
        + '<td>' + (price ? Number(price).toLocaleString() + "원" : "-") + '</td>'
        + '<td><span class="status ' + statusCls + '">' + escapeHtml(statusLabel) + '</span></td>'
        + '<td style="font-size:11px; color:' + profileColor + '; font-weight:600;">' + escapeHtml(profile) + '</td>'
        + '<td style="font-size:11px; color:var(--muted);">' + escapeHtml(o.exit_reason || '-') + '</td>'
        + '</tr>';
    }).join("");
  }

  async function loadStatisticsDetail(tradeDate) {
    if (!tradeDate) return;
    var sfDate = document.getElementById("sf-date");
    if (sfDate) sfDate.value = tradeDate;
    var tbody = document.getElementById("st-orders-tbody");
    var title = document.getElementById("st-table-title");
    var sourceEl = document.getElementById("st-table-source");
    if (tbody) tbody.innerHTML = '<tr><td colspan="9" class="muted" style="text-align:center;">로딩중...</td></tr>';
    if (title) title.textContent = tradeDate + " 주문 내역";

    try {
      var data = await fetchJson("/api/v1/trades/history/" + tradeDate);
      var p = data.payload || {};
      var orders = p.orders || [];
      var signals = p.signals || [];
      renderOrdersTable(orders.concat(signals), "해당 날짜 주문 없음");
    } catch (e) {
      console.error("[ERROR]", "loadStatisticsDetail", "-", e.message);
      if (tbody) tbody.innerHTML = '<tr><td colspan="9" class="muted" style="text-align:center;">불러오기 실패: ' + escapeHtml(e.message) + '</td></tr>';
    }
  }

  /* ── Today Control: Daily Plan Status ── */
  async function loadTodayPlanStatus() {
    try {
      var r = await fetch('/api/v1/daily-plan/today');
      var d = await r.json();
      var plan = d.payload || {};
      var el;
      el = document.getElementById('tc-daily-plan-id');
    if (el) el.textContent = plan.id || '미수집';
      el = document.getElementById('tc-daily-plan-status');
      if (el) el.textContent = plan.status || '-';
      el = document.getElementById('tc-trading-intensity');
      if (el) el.textContent = plan.trading_intensity || '-';
      var overrides = plan.daily_overrides || {};
      el = document.getElementById('tc-theme-spike-limit');
      if (el) el.textContent = 'THEME_SPIKE 허용 ' + (overrides.max_theme_spike_positions != null ? overrides.max_theme_spike_positions : '-') + '개';
      var assignments = plan.symbol_assignments || [];
      var counts = {LOW_VOL:0, MID_VOL:0, HIGH_VOL:0, THEME_SPIKE:0};
      assignments.forEach(function(a) { if (counts[a.profile] !== undefined) counts[a.profile]++; });
      el = document.getElementById('tc-low-vol-count');
      if (el) el.textContent = counts.LOW_VOL;
      el = document.getElementById('tc-mid-vol-count');
      if (el) el.textContent = counts.MID_VOL;
      el = document.getElementById('tc-high-vol-count');
      if (el) el.textContent = counts.HIGH_VOL;
      el = document.getElementById('tc-theme-spike-count');
      if (el) el.textContent = counts.THEME_SPIKE;
    } catch(e) { /* silent */ }

    try {
      var rb = await fetch('/api/v1/rule/base');
      var db = await rb.json();
      var elb = document.getElementById('tc-base-rulepack-ver');
      if (elb) elb.textContent = db.payload && db.payload.id ? db.payload.id : '-';
    } catch(e) {}

    try {
      var rp = await fetch('/api/v1/rule/profiles');
      var dp = await rp.json();
      var elp = document.getElementById('tc-profile-pack-ver');
      if (elp) elp.textContent = dp.payload && dp.payload.id ? dp.payload.id : '-';
    } catch(e) {}
  }

  /* ── Daily Plan & RulePack screen ── */
