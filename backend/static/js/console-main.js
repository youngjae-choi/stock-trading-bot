  /* Bind authentication, theme, halt, and navigation event handlers after DOM readiness. */
  function bindEvents() {
    if (loginForm) {
      loginForm.addEventListener("submit", async function (event) {
        event.preventDefault();
        try {
          if (mfaState && (mfaState.mode === "login" || mfaState.mode === "enroll_verify")) {
            await verifyMfaCode();
          } else if (mfaState && mfaState.mode === "enroll") {
            await startMfaEnrollment();
          } else {
            await submitLogin();
          }
        } catch (error) {
          if (mfaState) {
            if (mfaStartBtn && mfaState.mode === "enroll") {
              mfaStartBtn.disabled = false;
              mfaStartBtn.textContent = "선택한 수단 등록";
            }
            if (loginStatus) {
              loginStatus.textContent = "2차 인증 처리 실패: " + error.message;
              loginStatus.classList.add("error");
            }
          } else {
            showLogin(error.message);
          }
        }
      });
    }

    if (mfaStartBtn) {
      mfaStartBtn.addEventListener("click", async function () {
        try {
          await startMfaEnrollment();
        } catch (error) {
          if (mfaStartBtn) {
            mfaStartBtn.disabled = false;
            mfaStartBtn.textContent = "선택한 수단 등록";
          }
          if (loginStatus) {
            loginStatus.textContent = "2차 인증 등록 시작 실패: " + error.message;
            loginStatus.classList.add("error");
          }
        }
      });
    }

    if (mfaVerifyBtn) {
      mfaVerifyBtn.addEventListener("click", async function () {
        try {
          await verifyMfaCode();
        } catch (error) {
          if (loginStatus) {
            loginStatus.textContent = "2차 인증 실패: 코드를 확인하세요.";
            loginStatus.classList.add("error");
          }
        }
      });
    }

    if (logoutBtn) {
      logoutBtn.addEventListener("click", async function () {
        try {
          await logout();
        } catch (error) {
          showLogin("로그아웃 처리 중 오류가 발생했습니다.");
        }
      });
    }

    bindNavigationEvents();

    if (themeBtn) {
      themeBtn.addEventListener("click", function () {
        if (document.body.classList.contains("light")) {
          setTheme("dark");
        } else {
          setTheme("light");
        }
      });
    }

    if (haltBtn) {
      haltBtn.addEventListener("click", async function () {
        if (isHalted) {
          if (!confirm("긴급정지를 해제하고 운영을 재개할까요?")) {
            return;
          }
          try {
            await emergencyResume();
          } catch (error) {
            alert("운영재개 호출에 실패했습니다: " + error.message);
          }
          return;
        }

        if (!confirm("긴급정지를 실행할까요? 신규 자동 주문이 즉시 차단됩니다.")) {
          return;
        }

        try {
          await emergencyHalt();
        } catch (error) {
          alert("긴급정지 호출에 실패했습니다: " + error.message);
        }
      });
    }
  }

  /* Apply the saved console theme before authenticated data loads. */
  function initTheme() {
    var savedTheme = localStorage.getItem("dantabot_theme");
    if (savedTheme === "light") {
      setTheme("light");
      return;
    }
    setTheme("dark");
  }

  /* KIS System Test Handlers */
  async function loadSettingsMap() {
    try {
      var res = await fetchJson("/api/v1/settings");
      var settings = res.payload.items || [];
      var settingsMap = {};
      settings.forEach(function(s) { settingsMap[s.key] = s.value; });
      return settingsMap;
    } catch (e) {
      return {};
    }
  }

  function applyOperationMetadata(settingsMap) {
    OPS_STEPS.forEach(function(step) {
      var titleEl = document.getElementById("et-title-" + step.id);
      var detailEl = document.getElementById("et-detail-" + step.id);
      var displayTime = stepDisplayTime(step, settingsMap || {});
      var timeText = isClockTime(displayTime) ? displayTime + " KST" : displayTime;
      if (titleEl) titleEl.textContent = step.label;
      if (detailEl) detailEl.textContent = timeText + " · " + step.detail;
    });
  }

  async function engineTestLoadTodayResults() {
    applyOperationMetadata(await loadSettingsMap());
    var schedulerResponse = await fetchJson('/api/v1/scheduler/status').catch(() => null);
    var auditResponse = await fetchJson('/api/v1/engine/audit/today').catch(() => null);
    var scheduleSkipped = isScheduleSkipActive(schedulerResponse);
    var steps = [
      { id: 's1', call: () => Promise.resolve(schedulerResponse && schedulerResponse.payload?.last_run ? schedulerResponse : {ok:false, payload: schedulerResponse ? schedulerResponse.payload : null}) },
      { id: 's2', call: () => fetchJson('/api/v1/market-tone/today') },
      { id: 's3', call: () => fetchJson('/api/v1/universe-filter/today') },
      { id: 's4', call: () => fetchJson('/api/v1/screening/today') },
      { id: 's5', call: () => fetchJson('/api/v1/daily-plan/today') },
      { id: 's5v', call: () => fetchJson('/api/v1/daily-plan/today') },
      { id: 's5a', call: () => fetchJson('/api/v1/daily-plan/today') },
      { id: 's6', call: () => fetchJson('/api/v1/decision/status').then(r => r.payload?.active ? r : {ok:false}) },
      { id: 's7', call: () => fetchJson('/api/v1/orders/today').then(r => (r.payload?.orders?.length > 0) ? r : {ok:false}) },
      { id: 's8', call: () => fetchJson('/api/v1/orders/positions').then(r => (r.payload?.positions?.length > 0) ? r : {ok:false}) },
      { id: 's9', call: () => fetchJson('/api/v1/orders/today').then(r => ({ ok: false, payload: r.payload })) },
      { id: 's10', call: () => fetchJson('/api/v1/review-audit/today').then(r => r.payload ? r : {ok:false}).catch(() => ({ok:false})) },
      { id: 's11', call: () => fetchJson('/api/v1/learning-memory/today').then(r => (r.payload?.length > 0) ? r : {ok:false}).catch(() => ({ok:false})) },
    ];

    for (var step of steps) {
      try {
        var res = await step.call();
        if (scheduleSkipped && isScheduleSkippedStep(step.id)) {
          etSetBadge(step.id, 'skipped', '비거래일 스킵');
          if (res && Object.prototype.hasOwnProperty.call(res, 'payload')) {
            etSetResult(step.id, res.payload);
          }
          continue;
        }
        if (res && res.ok) {
          var badge = getDiagnosticsReadBadge(step.id, res, scheduleSkipped);
          etSetBadge(step.id, badge.status, badge.text);
          etSetResult(step.id, res.payload);
        } else {
          etSetBadge(step.id, 'pending', '대기');
        }
      } catch(e) {
        etSetBadge(step.id, 'pending', '대기');
      }
    }
    applyDiagnosticsAudit(auditResponse && auditResponse.payload ? auditResponse.payload.by_step : {});
  }

  /* Update a Diagnostics badge while keeping pending, skipped, and success visually distinct. */
  function etSetBadge(stepId, status, text) {
    var badge = document.getElementById('et-badge-' + stepId);
    if (!badge) return;
    badge.textContent = text;
    badge.className = 'badge ' + (status === 'ok' ? 'ok' : status === 'running' ? 'running' : status === 'skipped' ? 'skipped' : '');
  }

  /* Render raw Diagnostics JSON so null payloads remain visible to operators. */
  function etSetResult(stepId, data) {
    var pre = document.getElementById('et-result-' + stepId);
    if (!pre) return;
    pre.textContent = JSON.stringify(data, null, 2);
    pre.style.display = 'block';
  }

  /* Return a PM-friendly source label for a pipeline audit trigger source. */
  function diagnosticsAuditSourceLabel(source) {
    var labels = {
      auto_scheduler: '자동 실행 결과를 카드에 표시 중',
      console_manual: '수동 확인 실행 결과',
      api_manual: 'API 수동 실행 결과'
    };
    return labels[source] || (source || 'source 미기록');
  }

  /* Render pipeline_run_audit metadata inside a Diagnostics step card. */
  function etSetAudit(stepId, audit) {
    var card = document.getElementById('et-card-' + stepId);
    if (!card) return;
    var auditEl = document.getElementById('et-audit-' + stepId);
    if (!auditEl) {
      auditEl = document.createElement('div');
      auditEl.id = 'et-audit-' + stepId;
      auditEl.className = 'muted';
      auditEl.style.fontSize = '12px';
      auditEl.style.lineHeight = '1.5';
      auditEl.style.margin = '0 0 10px 0';
      var resultEl = document.getElementById('et-result-' + stepId);
      card.insertBefore(auditEl, resultEl || null);
    }
    if (!audit) {
      auditEl.textContent = '오늘 pipeline_run_audit 없음';
      return;
    }
    var when = audit.finished_at_kst || audit.started_at_kst || audit.started_at || '-';
    var sourceLabel = diagnosticsAuditSourceLabel(audit.trigger_source);
    var status = audit.status || 'status 미기록';
    var message = audit.message || audit.result_ref_id || 'summary 없음';
    auditEl.textContent = when + ' · ' + sourceLabel + ' · ' + status + ' · ' + message;
  }

  /* Apply latest pipeline_run_audit rows to all Diagnostics cards. */
  function applyDiagnosticsAudit(byStep) {
    OPS_STEPS.forEach(function(step) {
      etSetAudit(step.id, byStep ? byStep[step.id] : null);
    });
  }

  async function engineTestRun(step) {
    var card = document.getElementById("et-card-" + step);
    var badge = document.getElementById("et-badge-" + step);
    var resultEl = document.getElementById("et-result-" + step);

    if (badge) {
      badge.textContent = "실행중...";
      badge.className = "badge running";
    }
    if (resultEl) {
      resultEl.style.display = "block";
      resultEl.textContent = "서버 응답 대기중...";
    }

    try {
      var STEP_URLS = {
        s1: "/api/v1/engine/token-refresh",
        s2: "/api/v1/market-tone/analyze?trigger_source=console_manual",
        s3: "/api/v1/universe-filter/run?trigger_source=console_manual",
        s4: "/api/v1/screening/run?trigger_source=console_manual",
        s5: "/api/v1/daily-plan/generate?trigger_source=console_manual",
        s5v: "/api/v1/daily-plan/validate?trigger_source=console_manual",
        s5a: "/api/v1/daily-plan/activate?trigger_source=console_manual",
        s6: "/api/v1/decision/activate",
        s7: "/api/v1/orders/today",
        s8: "/api/v1/orders/positions",
        s9: "/api/v1/orders/liquidate-all",
        s10: "/api/v1/review-audit/run",
        s11: "/api/v1/learning-memory/build"
      };
      var stepUrl = STEP_URLS[step];
      if (!stepUrl) {
        if (badge) {
          badge.textContent = "오류";
          badge.className = "badge";
        }
        if (resultEl) {
          resultEl.textContent = "알 수 없는 step: " + step;
        }
        return;
      }
      
      var method = (step === "s8" || step === "s7") ? "GET" : "POST";
      if (step === "s10") method = "POST";

      var res = await fetch(stepUrl, { method: method });
      var data = await res.json();

      if (data.ok && hasManualRunPayload(data.payload)) {
        if (badge) {
          badge.textContent = "성공";
          badge.className = "badge ok";
        }
        if (resultEl) {
          resultEl.textContent = JSON.stringify(data.payload, null, 2);
        }
      } else {
        throw new Error(data.error || "알 수 없는 오류");
      }
    } catch (e) {
      if (badge) {
        badge.textContent = "실패";
        badge.className = "badge";
      }
      if (resultEl) {
        resultEl.textContent = "Error: " + e.message;
      }
    }
    // 실행 후 로그 자동 새로고침
    engineTestLoadLogs("");
  }

  async function engineTestLoadLogs(filter) {
    var logEl = document.getElementById("et-server-log");
    if (!logEl) return;

    try {
      var url = "/api/v1/engine/logs";
      if (filter) url += "?filter=" + encodeURIComponent(filter);
      var res = await fetch(url);
      var data = await res.json();
      if (data.ok) {
        var payload = data.payload || {};
        var logs = payload.logs || (Array.isArray(payload.lines) ? payload.lines.join("\n") : "");
        if (logs) {
          logEl.textContent = "[log_path: " + (payload.log_path || "-") + " | total: " + (payload.total || 0) + "]\n" + logs;
        } else {
          logEl.textContent = payload.message || "서버 로그 파일은 비어 있습니다: " + (payload.log_path || "경로 미확인");
        }
        logEl.scrollTop = logEl.scrollHeight;
      }
    } catch (e) {
      logEl.textContent = "로그를 불러오지 못했습니다: " + e.message;
    }
  }

  function engineTestClearLog() {
    var logEl = document.getElementById("et-server-log");
    if (logEl) logEl.textContent = "로그가 지워졌습니다 (화면만).";
  }

  function engineTestClearAll() {
    OPS_STEPS.forEach(function(opStep) {
      var step = opStep.id;
      var badge = document.getElementById("et-badge-" + step);
      var resultEl = document.getElementById("et-result-" + step);
      if (badge) {
        badge.textContent = "대기";
        badge.className = "badge status info";
      }
      if (resultEl) {
        resultEl.style.display = "none";
        resultEl.textContent = "";
      }
    });
  }

  /* Settings Handlers */
  var _positionsTimer = null;

  /* Write identical text into every element id that exists on the active console page. */
  function setTextForIds(ids, text) {
    for (var i = 0; i < ids.length; i++) {
      var element = document.getElementById(ids[i]);
      if (element) {
        element.textContent = text;
      }
    }
  }

  /* Write identical table HTML into every table body id that exists on the active console page. */
  function setHtmlForIds(ids, html) {
    for (var i = 0; i < ids.length; i++) {
      var element = document.getElementById(ids[i]);
      if (element) {
        element.innerHTML = html;
      }
    }
  }

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

  async function liquidateAll() {
    if (!confirm("전체 포지션을 즉시 청산할까요?")) return;
    try {
      await fetchJson("/api/v1/orders/liquidate-all", { method: "POST" });
      alert("전체 청산 주문이 전송되었습니다.");
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
  var liveRefreshTimer = null;
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
        var setEl = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v || '데이터 확인 필요'; };
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
      + '<div id="' + rowId + '" onclick="toggleCandidateDetail(\'' + c.code + '\')"'
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
          tbody.innerHTML = '<tr><td colspan="7" class="muted" style="text-align:center;">아직 신호 없음</td></tr>';
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
            return '<tr>'
              + '<td>' + escapeHtml(formatSignalTime(sig.created_at || sig.time || "")) + '</td>'
              + '<td>' + escapeHtml(sig.symbol || "") + '</td>'
              + '<td>' + escapeHtml(sig.name || "") + '</td>'
              + '<td>' + formatWonNumber(sig.trigger_price != null ? sig.trigger_price : sig.entry_price) + '</td>'
              + '<td>' + (sig.confidence != null ? escapeHtml(Number(sig.confidence).toFixed(2)) : "-") + '</td>'
              + '<td>' + escapeHtml(sig.status || "대기중") + '</td>'
              + '<td>' + conditionSummary + conditionDetail + '</td>'
              + '</tr>';
          }).join("");
        }
      }
    } catch (e) {
      var tbody3 = document.getElementById("live-signals-tbody");
      if (tbody3) tbody3.innerHTML = '<tr><td colspan="7" class="muted" style="text-align:center;">불러오기 실패: ' + escapeHtml(e.message) + '</td></tr>';
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

  /* ── System Status Health ── */
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

  /* Bootstrap the console after all split classic scripts have loaded. */
  async function init() {
    initTheme();
    bindEvents();
    var isAuthenticated = await checkAuth();
    if (!isAuthenticated) {
      return;
    }
    renderTodayFeed();
    updateLastTime();
    loadConsoleData();

    var savedScreen = sessionStorage.getItem('currentScreen');
    if (savedScreen === 'missed-opportunity') {
      savedScreen = 'shadow-trading';
    }
    if (savedScreen && document.getElementById('screen-' + savedScreen)) {
      showScreen(savedScreen);
    }

    setInterval(function () {
      renderTodayFeed();
      updateLastTime();
    }, 1000);
  }

  document.addEventListener("DOMContentLoaded", init);
