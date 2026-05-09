  var _positionsTimer = null;

  async function loadPositionMonitoring() {
    try {
      var data = await fetchJson("/api/v1/orders/positions");
      var hasLegacyTbody = Boolean(document.getElementById("positions-monitor-tbody"));
      if (!hasLegacyTbody) return;

      var positions = data.payload.positions || [];
      var legacyRowsHtml = "";
      if (positions.length === 0) {
        legacyRowsHtml = '<tr><td colspan="10" class="muted" style="text-align:center;">보유 포지션 없음 (Decision Engine 활성화 후 표시됩니다)</td></tr>';
      } else {
        var now = new Date();
        legacyRowsHtml = positions.map(function(pos) {
          var curPriceHtml = (pos.current_price && pos.current_price > 0)
            ? pos.current_price.toLocaleString()
            : '<span class="muted">-</span>';

          var pnlHtml;
          if (pos.current_price && pos.current_price > 0) {
            var pnl = pos.pnl_pct || 0;
            var pnlClass = pnl >= 0 ? "good" : "bad";
            pnlHtml = '<span class="' + pnlClass + '">' + (pnl >= 0 ? "+" : "") + pnl.toFixed(2) + "%</span>";
          } else {
            pnlHtml = '<span class="muted">-</span>';
          }

          var stopHtml = (pos.stop_loss_price && pos.stop_loss_price > 0)
            ? '<span style="color:var(--bad)">' + Math.round(pos.stop_loss_price).toLocaleString() + '</span>'
            : '<span class="muted">-</span>';
          
          var trailingHtml = pos.trailing_active 
            ? '<span class="status ok">ON</span>' 
            : '<span class="status">대기</span>';

          var entryTime = new Date(pos.entry_time);
          var durationMinutes = Math.floor((now - entryTime) / (1000 * 60));
          var durationStr = durationMinutes + "분";

          return '<tr>'
            + '<td>' + (pos.symbol || "") + '</td>'
            + '<td>' + (pos.name || "") + '</td>'
            + '<td>' + (pos.qty || 0).toLocaleString() + '</td>'
            + '<td>' + (pos.entry_price || 0).toLocaleString() + '</td>'
            + '<td>' + curPriceHtml + '</td>'
            + '<td>' + pnlHtml + '</td>'
            + '<td>' + stopHtml + '</td>'
            + '<td>' + (pos.take_profit_price || 0).toLocaleString() + '</td>'
            + '<td>' + trailingHtml + '</td>'
            + '<td>' + durationStr + '</td>'
            + '</tr>';
        }).join("");
      }
      setHtmlForIds(["positions-monitor-tbody"], legacyRowsHtml);

      var el = document.getElementById('positions-last-updated');
      if (el) {
        el.textContent = new Date().toLocaleTimeString('ko-KR', {hour:'2-digit', minute:'2-digit', second:'2-digit'});
      }
    } catch (e) {
      setHtmlForIds(
        ["positions-monitor-tbody"],
        '<tr><td colspan="10" class="muted" style="text-align:center;">불러오기 실패: ' + escapeHtml(e.message) + '</td></tr>'
      );
    }
  }


  async function liquidateAll() {
    if (!confirm("보유 포지션 전량을 즉시 시장가로 청산할까요? (일괄매도)")) return;
    try {
      await fetchJson("/api/v1/orders/liquidate-all", { method: "POST" });
      alert("전량 청산(일괄매도) 주문이 전송되었습니다.");
      loadPositionMonitoring();
      loadTodayOrders();
    } catch (e) {
      alert("청산 실패: " + e.message);
    }
  }

  /* ── Positions & Exit: Account Balance ── */
  async function loadAccountBalance() {
    try {
      var data = await fetchJson("/api/v1/account/balance");
      if (!data.ok) throw new Error(data.message || "API 오류");
      var p = data.payload;

      function _toManwon(v) {
        var n = Number(v) || 0;
        if (n >= 10000) return (n / 10000).toFixed(0) + "만원";
        return n.toLocaleString() + "원";
      }

      setTextForIds(["positions-account-no"], "계좌번호: " + (p.account_no || "-"));
      // buyable_cash = 주문가능 예수금 (nxdy_excc_amt 기반)
      setTextForIds(["positions-deposit"], _toManwon(p.buyable_cash != null ? p.buyable_cash : p.deposit));
      setTextForIds(["positions-total-eval"], _toManwon(p.total_eval));

      if (document.getElementById("positions-holdings-tbody")) {
        var positions = p.positions || [];
        var rowsHtml = "";
        if (positions.length === 0) {
          rowsHtml = '<tr><td colspan="6" class="muted" style="text-align:center;">보유 종목 없음</td></tr>';
        } else {
          rowsHtml = positions.map(function(pos) {
            var pnl = pos.pnl_pct || 0;
            var pnlClass = pnl >= 0 ? "good" : "bad";
            var pnlStr = (pnl >= 0 ? "+" : "") + pnl.toFixed(2) + "%";
            return '<tr>'
              + '<td>' + (pos.symbol || "") + '</td>'
              + '<td>' + (pos.name || "") + '</td>'
              + '<td>' + (pos.qty || 0).toLocaleString() + '</td>'
              + '<td>' + (pos.avg_price || 0).toLocaleString() + '</td>'
              + '<td>' + (pos.current_price || 0).toLocaleString() + '</td>'
              + '<td class="' + pnlClass + '">' + pnlStr + '</td>'
              + '</tr>';
          }).join("");
        }
        setHtmlForIds(["positions-holdings-tbody"], rowsHtml);
      }
    } catch (e) {
      setHtmlForIds(
        ["positions-holdings-tbody"],
        '<tr><td colspan="6" class="muted" style="text-align:center;">불러오기 실패: ' + escapeHtml(e.message) + '</td></tr>'
      );
    }
  }

  /* ── Live Decisions: Decision Engine ── */
