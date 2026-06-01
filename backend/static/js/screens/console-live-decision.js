  var liveRefreshTimer = null;

  async function loadLiveData() {
    try {
      var statusData = await fetchJson("/api/v1/decision/status");
      if (statusData.ok) {
        var s = statusData.payload;
        var activeEl = document.getElementById("live-engine-active");
        var wsEl = document.getElementById("live-engine-ws");
        var candidatesEl = document.getElementById("live-engine-candidates");
        var signalsSentEl = document.getElementById("live-engine-signals-sent");

        if (activeEl) {
          activeEl.textContent = s.active ? "활성" : "비활성";
          activeEl.className = "status " + (s.active ? "ok" : "warn");
        }
        if (wsEl) {
          wsEl.textContent = s.ws_connected ? "연결됨" : "끊김";
          wsEl.style.color = s.ws_connected ? "var(--green)" : "var(--red)";
        }
        if (candidatesEl) candidatesEl.textContent = (s.candidates != null ? s.candidates : "-") + "개";
        if (signalsSentEl) signalsSentEl.textContent = (s.signals_sent != null ? s.signals_sent : "-") + "건";
      }
    } catch (e) {
      /* ignore status fetch error */
    }

    try {
      var signalsData = await fetchJson("/api/v1/decision/signals/today");
      var tbody = document.getElementById("live-signals-tbody");
      if (tbody && signalsData.ok) {
        var payload = signalsData.payload || {};
        var signals = Array.isArray(payload) ? payload : (payload.signals || []);
        if (signals.length === 0) {
          tbody.innerHTML = '<tr><td colspan="6" class="muted" style="text-align:center;">아직 신호 없음</td></tr>';
        } else {
          tbody.innerHTML = signals.map(function(sig) {
            var matched = parseRuleMatched(sig.rule_matched);
            var unavailable = matched.unavailable_conditions || {};
            var unavailableKeys = Object.keys(unavailable);
            var observed = matched.observed_values || {};
            var conditionSummary = unavailableKeys.length
              ? '<span class="status warn">' + unavailableKeys.length + '개 확인필요</span>'
              : '<span class="status ok">추적 정상</span>';
            var conditionDetail = buildRuleTraceDetail(observed, unavailableKeys);
            // AI 신뢰도 컬럼은 2026-06-01 게이트 분리 후 표시 제외 (observed_values에는 보존).
            return '<tr>'
              + '<td>' + escapeHtml(formatSignalTime(sig.created_at || sig.time || "")) + '</td>'
              + '<td>' + escapeHtml(sig.symbol || "") + '</td>'
              + '<td>' + escapeHtml(sig.name || "") + '</td>'
              + '<td>' + formatWonNumber(sig.trigger_price != null ? sig.trigger_price : sig.entry_price) + '</td>'
              + '<td>' + escapeHtml(sig.status || "대기중") + '</td>'
              + '<td>' + conditionSummary + conditionDetail + '</td>'
              + '</tr>';
          }).join("");
        }
      }
    } catch (e) {
      var tbody3 = document.getElementById("live-signals-tbody");
      if (tbody3) tbody3.innerHTML = '<tr><td colspan="6" class="muted" style="text-align:center;">불러오기 실패: ' + escapeHtml(e.message) + '</td></tr>';
    }
  }

  /* Parse the persisted S6 rule_matched JSON without breaking the live table on legacy rows. */
  function parseRuleMatched(value) {
    if (!value) return {};
    if (typeof value === 'object') return value;
    try {
      return JSON.parse(value);
    } catch (e) {
      return {};
    }
  }

  /* Build compact condition trace text for S6 signal rows. */
  function buildRuleTraceDetail(observed, unavailableKeys) {
    var pieces = [];
    if (observed.change_rate != null) pieces.push('등락률 ' + Number(observed.change_rate).toFixed(2) + '%');
    if (observed.volume_ratio != null) pieces.push('거래량배수 ' + Number(observed.volume_ratio).toFixed(2));
    if (unavailableKeys.length) pieces.push('확인필요: ' + unavailableKeys.join(', '));
    if (!pieces.length) return '';
    return '<div class="muted" style="font-size:10px; margin-top:3px; max-width:220px; white-space:normal;">' + escapeHtml(pieces.join(' · ')) + '</div>';
  }

  /* Format S6 signal timestamp for the compact live table. */
  function formatSignalTime(value) {
    if (!value) return '';
    var d = new Date(value);
    if (Number.isNaN(d.getTime())) return String(value).slice(0, 19);
    return d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }

  /* Format KRW-like numeric values while preserving empty states. */
  function formatWonNumber(value) {
    if (value == null || value === '') return '-';
    var n = Number(value);
    return Number.isNaN(n) ? escapeHtml(value) : escapeHtml(n.toLocaleString());
  }

  async function liveDecisionActivate() {
    if (!confirm("Decision Engine을 수동으로 활성화할까요?")) return;
    try {
      await fetchJson("/api/v1/decision/activate", { method: "POST" });
      loadLiveData();
      loadTradingMonitor();
    } catch (e) {
      alert("활성화 실패: " + e.message);
    }
  }

  async function liveDecisionDeactivate() {
    if (!confirm("Decision Engine을 비활성화할까요?")) return;
    try {
      await fetchJson("/api/v1/decision/deactivate", { method: "POST" });
      loadLiveData();
      loadTradingMonitor();
    } catch (e) {
      alert("비활성화 실패: " + e.message);
    }
  }

