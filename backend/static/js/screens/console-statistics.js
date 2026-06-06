  var stFilter = "today";
  var stCurrentPairs = [];
  var stCurrentPage = 1;
  var ST_PAGE_SIZE = 20;
  var stExpandedRows = new Set();

  /* ── 필터 버튼 활성화 ── */
  function setStatsFilter(filter) {
    stFilter = filter;
    ["today", "week", "all", "month", "lastmonth", "range"].forEach(function(f) {
      var btn = document.getElementById("sf-" + f);
      if (btn) btn.className = "btn" + (f === filter ? " primary" : "");
    });
    stExpandedRows.clear();
    loadTradePairs();
  }

  /* ── 날짜 범위 계산 ── */
  function _getDateRange() {
    var now = new Date();
    var pad = function(n) { return String(n).padStart(2, "0"); };
    var fmt = function(d) { return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()); };
    var today = fmt(now);

    if (stFilter === "today") return { start: today, end: today };
    if (stFilter === "week") {
      var day = now.getDay();
      var mon = new Date(now);
      mon.setDate(now.getDate() - (day === 0 ? 6 : day - 1));
      return { start: fmt(mon), end: today };
    }
    if (stFilter === "month") {
      return { start: now.getFullYear() + "-" + pad(now.getMonth() + 1) + "-01", end: today };
    }
    if (stFilter === "lastmonth") {
      var lm = new Date(now.getFullYear(), now.getMonth() - 1, 1);
      var lmEnd = new Date(now.getFullYear(), now.getMonth(), 0);
      return { start: fmt(lm), end: fmt(lmEnd) };
    }
    if (stFilter === "range") {
      var rsEl = document.getElementById("sf-range-start");
      var reEl = document.getElementById("sf-range-end");
      return {
        start: (rsEl && rsEl.value) ? rsEl.value : "2020-01-01",
        end: (reEl && reEl.value) ? reEl.value : today,
      };
    }
    return { start: "2020-01-01", end: today }; // all
  }

  /* ── 거래 페어 로드 ── */
  async function loadTradePairs() {
    var tbody = document.getElementById("st-orders-tbody");
    var title = document.getElementById("st-table-title");
    if (tbody) tbody.innerHTML = '<tr><td colspan="12" class="muted" style="text-align:center;">로딩중...</td></tr>';

    var filterLabel = { today: "오늘", week: "이번주", month: "이번달", lastmonth: "지난달", all: "전체", range: "기간검색" };
    if (title) title.textContent = (filterLabel[stFilter] || "") + " 거래 결과";

    try {
      var range = _getDateRange();
      var data = await fetchJson("/api/v1/trades/pairs?start=" + range.start + "&end=" + range.end);
      stCurrentPairs = (data.payload && data.payload.pairs) || [];
      stCurrentPage = 1;
      renderSummaryBar(stCurrentPairs);
      renderTradePairs(stCurrentPairs);
    } catch (e) {
      console.error("[ERROR]", "loadTradePairs", "-", e.message);
      if (tbody) tbody.innerHTML = '<tr><td colspan="12" class="muted" style="text-align:center;">조회 실패: ' + escapeHtml(e.message) + '</td></tr>';
    }
  }

  /* ── 요약 바 ── */
  function renderSummaryBar(pairs) {
    var total = pairs.length;
    var withResult = pairs.filter(function(p) { return p.pnl_amount != null; });
    var profit = withResult.filter(function(p) { return p.pnl_amount > 0; }).length;
    var loss = withResult.filter(function(p) { return p.pnl_amount < 0; }).length;
    var totalPnl = withResult.reduce(function(acc, p) { return acc + (p.pnl_amount || 0); }, 0);
    var winrate = withResult.length > 0 ? Math.round(profit / withResult.length * 100) : 0;

    function setST(id, text, cls) {
      var el = document.getElementById(id);
      if (el) { el.textContent = text; if (cls) el.className = "metric " + cls; }
    }
    setST("st-days", total + "건");
    setST("st-orders", withResult.length + "건");
    setST("st-winrate", winrate + "%", winrate >= 50 ? "good" : "warn");
    var wd = document.getElementById("st-winrate-detail");
    if (wd) wd.textContent = profit + "수익 / " + loss + "손실";
    setST("st-pnl", (totalPnl >= 0 ? "+" : "") + totalPnl.toLocaleString() + "원", totalPnl >= 0 ? "good" : "bad");
    setST("st-avg-pnl", "-");
  }

  /* ── 거래 결과 테이블 렌더 ── */
  function renderTradePairs(pairs) {
    var tbody = document.getElementById("st-orders-tbody");
    if (!tbody) return;
    if (!pairs || pairs.length === 0) {
      tbody.innerHTML = '<tr><td colspan="12" class="muted" style="text-align:center;">해당 기간 거래 내역 없음</td></tr>';
      renderPagination(0);
      return;
    }

    var totalPages = Math.ceil(pairs.length / ST_PAGE_SIZE);
    if (stCurrentPage > totalPages) stCurrentPage = totalPages;
    if (stCurrentPage < 1) stCurrentPage = 1;
    var start = (stCurrentPage - 1) * ST_PAGE_SIZE;
    var pagePairs = pairs.slice(start, start + ST_PAGE_SIZE);

    var statusStyles = {
      "매수주문": "warn",
      "매수완료": "ok",
      "매도주문": "warn",
      "매도완료": "ok",
    };

    var html = pagePairs.map(function(p) {
      var rowKey = p.trade_date + "_" + p.symbol;
      var isExpanded = stExpandedRows.has(rowKey);

      var pnlHtml = "-";
      if (p.pnl_amount != null) {
        var pnlCls = p.pnl_amount > 0 ? "good" : p.pnl_amount < 0 ? "bad" : "";
        var pnlSign = p.pnl_amount >= 0 ? "+" : "";
        pnlHtml = '<span class="' + pnlCls + '">' + pnlSign + p.pnl_amount.toLocaleString() + "원</span>";
      }

      var pnlPctHtml = "-";
      if (p.pnl_pct != null) {
        var pctCls = p.pnl_pct > 0 ? "good" : p.pnl_pct < 0 ? "bad" : "";
        var pctSign = p.pnl_pct >= 0 ? "+" : "";
        pnlPctHtml = '<span class="' + pctCls + '">' + pctSign + p.pnl_pct.toFixed(2) + "%</span>";
      }

      var statusCls = statusStyles[p.status] || "warn";

      var mainRow = '<tr class="pair-row" style="cursor:pointer;" onclick="stToggleDetail(\'' + escapeHtml(rowKey) + '\')">'
        + '<td style="font-size:12px;">' + escapeHtml(p.trade_date) + '</td>'
        + '<td><strong class="pair-name" style="color:var(--accent);">' + escapeHtml(p.name || p.symbol) + '</strong>'
        + ' <span style="font-size:11px; color:var(--muted);">' + escapeHtml(p.symbol) + '</span></td>'
        + '<td style="text-align:right;">' + (p.buy_price != null ? p.buy_price.toLocaleString() + "원" : "-") + '</td>'
        + '<td style="text-align:right;">' + (p.buy_qty != null ? p.buy_qty + "주" : "-") + '</td>'
        + '<td style="text-align:right;">' + (p.sell_price != null ? p.sell_price.toLocaleString() + "원" : "-") + '</td>'
        + '<td style="text-align:right;">' + (p.sell_qty != null ? p.sell_qty + "주" : "-") + '</td>'
        + '<td style="text-align:right;">' + pnlHtml + '</td>'
        + '<td style="text-align:right;">' + pnlPctHtml + '</td>'
        + '<td style="font-size:11px; color:var(--muted); max-width:160px;">' + escapeHtml(p.selection_summary || "-") + '</td>'
        + '<td style="font-size:11px; color:var(--accent);">' + escapeHtml(p.buy_reason_summary || "-") + '</td>'
        + '<td style="font-size:11px; color:var(--muted);">' + escapeHtml(p.exit_reason || "-") + '</td>'
        + '<td><span class="status ' + statusCls + '">' + escapeHtml(p.status) + '</span></td>'
        + '</tr>';

      var detailRow = '<tr class="pair-detail-row" id="detail-' + escapeHtml(rowKey) + '" style="display:' + (isExpanded ? "table-row" : "none") + ';">'
        + '<td colspan="12" style="padding:0; background:var(--panel-2);">'
        + renderEntryTagDetail(p.entry_tag)
        + renderOrderDetail(p.orders)
        + '</td></tr>';

      return mainRow + detailRow;
    }).join("");

    tbody.innerHTML = html;
    renderPagination(pairs.length);
  }

  /* ── 태깅 상세 (선정·조건상태·맥락·결과) ── */
  function renderEntryTagDetail(tag) {
    if (!tag) {
      return '<div style="padding:8px 16px; color:var(--muted); font-size:12px;">태깅 데이터 없음 (탐색엔진 비활성 시점 거래)</div>';
    }
    var sr = tag.selection_reason || {};
    var sources = (sr.sources || []).map(function(s) { return escapeHtml(String(s)); }).join(", ") || "-";
    var note = escapeHtml(sr.llm_note || "-");
    var fired = (tag.fired_groups || []).map(function(g) { return escapeHtml(String(g)); }).join(", ") || "-";

    function kvBlock(title, obj) {
      var keys = Object.keys(obj || {});
      if (!keys.length) return '';
      var cells = keys.map(function(k) {
        var v = obj[k];
        var vs = (typeof v === "boolean") ? (v ? "✓" : "✗") : String(v);
        return '<span style="display:inline-block; margin:2px 8px 2px 0; font-size:11px;">'
          + '<span style="color:var(--muted);">' + escapeHtml(k) + '</span> '
          + '<strong>' + escapeHtml(vs) + '</strong></span>';
      }).join("");
      return '<div style="margin-top:6px;"><div style="font-size:10px; color:var(--muted); margin-bottom:2px;">' + title + '</div>' + cells + '</div>';
    }

    return '<div style="padding:10px 16px; border-bottom:1px solid var(--line);">'
      + '<div style="font-size:11px; color:var(--muted); font-weight:600; margin-bottom:4px;">탐색엔진 태깅</div>'
      + '<div style="font-size:12px;"><span style="color:var(--muted);">선정사유</span> ' + sources + '</div>'
      + '<div style="font-size:12px;"><span style="color:var(--muted);">LLM 메모</span> ' + note + '</div>'
      + '<div style="font-size:12px;"><span style="color:var(--muted);">매수사유(발화그룹)</span> <strong style="color:var(--accent);">' + fired + '</strong></div>'
      + kvBlock("진입 조건상태", tag.condition_states)
      + kvBlock("시장맥락", tag.market_context)
      + kvBlock("결과", tag.outcome)
      + '</div>';
  }

  /* ── 주문 상세 (accordion 내부) ── */
  function renderOrderDetail(orders) {
    if (!orders || orders.length === 0) {
      return '<div style="padding:12px 20px; color:var(--muted); font-size:13px;">주문 이력 없음</div>';
    }

    var statusMap = { filled: "체결", completed: "체결", executed: "체결", submitted: "접수", submitted_without_order_no: "접수중", submit_uncertain: "불확실", partial_fill: "부분체결", failed: "실패", cancelled: "취소", preflight_blocked: "차단" };

    var rows = orders.map(function(o) {
      var sideCls = o.side === "buy" ? "ok" : "warn";
      var sideLabel = o.side === "buy" ? "매수" : "매도";
      var rawStatus = o.status || "submitted";
      var statusCls = (rawStatus === "filled" || rawStatus === "completed" || rawStatus === "executed") ? "ok"
        : (rawStatus === "failed" || rawStatus === "cancelled" || rawStatus === "preflight_blocked") ? "danger" : "warn";
      var statusLabel = statusMap[rawStatus] || rawStatus;
      var timeStr = (o.created_at || "").slice(0, 19).replace("T", " ");
      var orderPrice = o.fill_price != null ? o.fill_price.toLocaleString() + "원 (체결)" : (o.price ? Number(o.price).toLocaleString() + "원" : "-");
      var orderQty = o.fill_qty != null ? o.fill_qty + "주 (체결)" : (o.qty ? o.qty + "주" : "-");

      return '<tr>'
        + '<td style="font-size:11px; color:var(--muted); padding:6px 12px;">' + escapeHtml(timeStr) + '</td>'
        + '<td style="padding:6px 12px;"><span class="status ' + sideCls + '">' + sideLabel + '</span></td>'
        + '<td style="text-align:right; padding:6px 12px;">' + escapeHtml(orderQty) + '</td>'
        + '<td style="text-align:right; padding:6px 12px;">' + escapeHtml(orderPrice) + '</td>'
        + '<td style="padding:6px 12px;"><span class="status ' + statusCls + '">' + escapeHtml(statusLabel) + '</span></td>'
        + '<td style="font-size:11px; color:var(--muted); padding:6px 12px;">' + escapeHtml(o.reason || "-") + '</td>'
        + '<td style="font-size:11px; color:var(--muted); padding:6px 12px;">' + escapeHtml(o.kis_order_no || "-") + '</td>'
        + '</tr>';
    }).join("");

    return '<div style="padding:8px 16px;">'
      + '<div style="font-size:11px; color:var(--muted); margin-bottom:6px; font-weight:600;">주문 이력</div>'
      + '<table style="width:100%; font-size:12px;">'
      + '<thead><tr style="color:var(--muted);">'
      + '<th style="text-align:left; padding:4px 12px; font-weight:400;">시간</th>'
      + '<th style="text-align:left; padding:4px 12px; font-weight:400;">구분</th>'
      + '<th style="text-align:right; padding:4px 12px; font-weight:400;">수량</th>'
      + '<th style="text-align:right; padding:4px 12px; font-weight:400;">가격</th>'
      + '<th style="text-align:left; padding:4px 12px; font-weight:400;">상태</th>'
      + '<th style="text-align:left; padding:4px 12px; font-weight:400;">사유</th>'
      + '<th style="text-align:left; padding:4px 12px; font-weight:400;">KIS 주문번호</th>'
      + '</tr></thead>'
      + '<tbody>' + rows + '</tbody>'
      + '</table></div>';
  }

  /* ── 종목 row 펼치기/접기 ── */
  function stToggleDetail(rowKey) {
    var detailRow = document.getElementById("detail-" + rowKey);
    if (!detailRow) return;
    if (stExpandedRows.has(rowKey)) {
      stExpandedRows.delete(rowKey);
      detailRow.style.display = "none";
    } else {
      stExpandedRows.add(rowKey);
      detailRow.style.display = "table-row";
    }
  }

  /* ── 페이지네이션 ── */
  function renderPagination(totalCount) {
    var container = document.getElementById("st-pagination");
    if (!container) return;
    if (totalCount <= ST_PAGE_SIZE) { container.innerHTML = ""; return; }
    var totalPages = Math.ceil(totalCount / ST_PAGE_SIZE);
    container.innerHTML = '<div style="display:flex; gap:6px; align-items:center; justify-content:center; padding:12px 0;">'
      + '<button type="button" class="btn" ' + (stCurrentPage <= 1 ? "disabled" : "") + ' onclick="stGoPage(' + (stCurrentPage - 1) + ')">이전</button>'
      + '<span style="color:var(--muted); font-size:13px;">' + stCurrentPage + " / " + totalPages + "페이지 (총 " + totalCount + "건)</span>"
      + '<button type="button" class="btn" ' + (stCurrentPage >= totalPages ? "disabled" : "") + ' onclick="stGoPage(' + (stCurrentPage + 1) + ')">다음</button>'
      + '</div>';
  }

  function stGoPage(page) {
    stCurrentPage = page;
    stExpandedRows.clear();
    renderTradePairs(stCurrentPairs);
  }

  /* ── 초기 로드 (screen 진입 시 호출) ── */
  async function loadStatistics() {
    await loadTradePairs();
  }

  /* ── 하위 호환: 기존 loadAllOrders 호출부 대응 ── */
  async function loadAllOrders() {
    await loadTradePairs();
  }

  /* ── Today Control: Daily Plan Status ── */
  async function loadTodayPlanStatus(tradeDate) {
    try {
      var planUrl = tradeDate ? '/api/v1/daily-plan/today?trade_date=' + tradeDate : '/api/v1/daily-plan/today';
      var r = await fetch(planUrl);
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
