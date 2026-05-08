  async function loadExecutionRisk() {
    try {
      var data = await fetchJson("/api/v1/orders/today");
      var orders = (data.payload && data.payload.orders) || [];

      var ordersCountEl = document.getElementById("risk-orders-count");
      if (ordersCountEl) ordersCountEl.textContent = orders.length;

      var tbody = document.getElementById("risk-orders-tbody");
      if (tbody) {
        if (orders.length === 0) {
          tbody.innerHTML = '<tr><td colspan="7" class="muted" style="text-align:center;">오늘 주문 없음</td></tr>';
        } else {
          tbody.innerHTML = orders.map(function(ord) {
            var sideLabel = ord.side === "buy" ? "매수" : "매도";
            var timeStr = (ord.created_at || "").split("T")[1] || "";
            if (timeStr.includes(".")) timeStr = timeStr.split(".")[0];
            var statusCls = ord.status === "filled" ? "ok" : ord.status === "failed" ? "danger" : "info";
            var statusLabel = { submitted: "제출됨", filled: "전량체결", failed: "실패", cancelled: "취소" }[ord.status] || ord.status || "-";
            return '<tr>'
              + '<td>' + timeStr + '</td>'
              + '<td>' + escapeHtml((ord.symbol || "") + (ord.name ? " " + ord.name : "")) + '</td>'
              + '<td>' + sideLabel + '</td>'
              + '<td>' + (ord.qty || 0).toLocaleString() + '</td>'
              + '<td>' + (ord.price || 0).toLocaleString() + '</td>'
              + '<td>' + escapeHtml(ord.reason || "-") + '</td>'
              + '<td><span class="status ' + statusCls + '">' + statusLabel + '</span></td>'
              + '</tr>';
          }).join("");
        }
      }
    } catch (e) {
      var tbody2 = document.getElementById("risk-orders-tbody");
      if (tbody2) tbody2.innerHTML = '<tr><td colspan="7" class="muted" style="text-align:center;">불러오기 실패: ' + escapeHtml(e.message) + '</td></tr>';
    }
  }

