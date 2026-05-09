  function setTheme(mode) {
    if (mode === "light") {
      document.body.classList.add("light");
      if (themeBtn) {
        themeBtn.textContent = "Dark";
      }
      localStorage.setItem("dantabot_theme", "light");
      return;
    }

    document.body.classList.remove("light");
    if (themeBtn) {
      themeBtn.textContent = "Light";
    }
    localStorage.setItem("dantabot_theme", "dark");
  }

  function isClockTime(timeText) {
    return /^\d{2}:\d{2}$/.test(String(timeText || ""));
  }

  function minutesOf(timeText) {
    var parts = timeText.split(":");
    return Number(parts[0]) * 60 + Number(parts[1]);
  }

  function stepDisplayTime(step, settingsMap) {
    return (settingsMap && settingsMap[step.settingKey]) || step.defaultTime;
  }

  function getScheduledTimeline(settingsMap) {
    return SCHEDULED_OPERATIONS
      .map(function(step) {
        return { time: stepDisplayTime(step, settingsMap), name: step.label };
      })
      .filter(function(item) { return isClockTime(item.time); })
      .sort(function(a, b) { return minutesOf(a.time) - minutesOf(b.time); });
  }

  function getCurrentPhase(settingsMap) {
    var currentTimeline = getScheduledTimeline(settingsMap);
    var now = new Date();
    var current = now.getHours() * 60 + now.getMinutes();
    var active = currentTimeline[0] || { time: "-", name: "-" };
    var next = currentTimeline[1] || active;

    for (var i = 0; i < currentTimeline.length; i++) {
      if (current >= minutesOf(currentTimeline[i].time)) {
        active = currentTimeline[i];
        next = currentTimeline[i + 1] || currentTimeline[0];
      }
    }

    return {
      active: active,
      next: next,
      currentMinutes: current
    };
  }

  /* Return today's date in the exchange-facing KST calendar. */
  function getKstDateString(date) {
    var parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Seoul",
      year: "numeric",
      month: "2-digit",
      day: "2-digit"
    }).formatToParts(date || new Date());
    var byType = {};
    parts.forEach(function(part) {
      byType[part.type] = part.value;
    });
    return byType.year + "-" + byType.month + "-" + byType.day;
  }

  /* Check whether a pipeline trade_date belongs to the current KST day. */
  function isTodayTradeDate(value) {
    return String(value || "") === getKstDateString();
  }

  /* Read the scheduler skip flag from the Scheduler status envelope. */
  function isScheduleSkipActive(response) {
    var skipValue = response && response.payload ? response.payload.schedule_skip_today : null;
    if (skipValue && typeof skipValue === "object") {
      return skipValue.skip === true;
    }
    return skipValue === true || String(skipValue).toLowerCase() === "true";
  }

  /* Decide whether a step belongs to the S2~S6 auto-skip window. */
  function isScheduleSkippedStep(stepId) {
    return ["s2", "s3", "s4", "s5", "s5v", "s5a", "s6"].indexOf(stepId) >= 0;
  }

  /* Extract the persisted result object from old and new GET response shapes. */
  function getPipelineResult(stepId, response) {
    if (!response || response.ok !== true) return null;
    if (response.result) return response.result;
    var payload = response.payload;
    if (!payload) return null;
    if (stepId === "s2") return payload.market_tone || null;
    if (stepId === "s3") return payload.universe || payload.filter_result || null;
    if (stepId === "s4") return payload.screening || payload.screening_result || null;
    if (stepId === "s5" || stepId === "s5v" || stepId === "s5a") return payload.plan || payload;
    return payload;
  }

  /* Extract the trade date attached to a pipeline GET response. */
  function getPipelineTradeDate(stepId, response) {
    var result = getPipelineResult(stepId, response);
    return (result && result.trade_date) || (response && response.trade_date) || (response && response.payload && response.payload.trade_date);
  }

  /* Determine if a persisted S2~S5 result really exists for today. */
  function hasTodayPipelineResult(stepId, response) {
    if (!response || response.ok !== true || response.has_result === false) return false;
    var result = getPipelineResult(stepId, response);
    if (!result || typeof result !== "object") return false;
    if (!isTodayTradeDate(getPipelineTradeDate(stepId, response))) return false;
    if (stepId === "s5") {
      return Boolean(result.id && result.status);
    }
    return true;
  }

  /* Map a read-only response to the UI state used by the Today timeline. */
  function getPipelineReadState(stepId, response, scheduleSkipped) {
    if (scheduleSkipped && isScheduleSkippedStep(stepId)) return "skipped";
    if (response && response.status === "skipped" && !hasTodayPipelineResult(stepId, response)) return "skipped";
    if (hasTodayPipelineResult(stepId, response)) return "completed";
    return stepId === "s5" ? "missing" : "pending";
  }

  /* Check Daily Plan validation/activation state without assuming payload nesting. */
  function hasDailyPlanStatus(response, allowedStatuses) {
    var plan = getPipelineResult("s5", response);
    return Boolean(
      plan &&
      plan.id &&
      isTodayTradeDate(plan.trade_date || (response && response.trade_date)) &&
      allowedStatuses.indexOf(plan.status) >= 0
    );
  }

  /* Build a Diagnostics badge from a read-only GET response. */
  function getDiagnosticsReadBadge(stepId, response, scheduleSkipped) {
    if (scheduleSkipped && isScheduleSkippedStep(stepId)) {
      return { status: "skipped", text: "비거래일 스킵" };
    }
    if (["s2", "s3", "s4", "s5"].indexOf(stepId) >= 0) {
      var readState = getPipelineReadState(stepId, response, false);
      if (readState === "completed") return { status: "ok", text: "완료" };
      if (readState === "skipped") return { status: "skipped", text: "스킵" };
      return { status: "pending", text: stepId === "s5" ? "미생성" : "대기" };
    }
    if (stepId === "s5v") {
      return hasDailyPlanStatus(response, ["validated", "active"])
        ? { status: "ok", text: "완료" }
        : { status: "pending", text: "대기" };
    }
    if (stepId === "s5a") {
      return hasDailyPlanStatus(response, ["active"])
        ? { status: "ok", text: "완료" }
        : { status: "pending", text: "대기" };
    }
    return response && response.ok ? { status: "ok", text: "완료" } : { status: "pending", text: "대기" };
  }

  /* Ensure manual POST success is based on a real response body, not ok alone. */
  function hasManualRunPayload(payload) {
    return payload !== null && payload !== undefined;
  }

  /* Render today's operations as a horizontal timeline with dynamic status logic. */
  async function renderTodayFeed() {
    var feed = todayOpsFeed || document.getElementById("today-ops-feed");
    if (!feed) return;

    try {
      // 1. Fetch settings for dynamic times
      var settingsData = await fetchJson('/api/v1/settings').catch(() => null);
      var settingsMap = {};
      if (settingsData && settingsData.payload && settingsData.payload.items) {
        settingsData.payload.items.forEach(s => {
          settingsMap[s.key] = s.value;
        });
      }
      var phase = getCurrentPhase(settingsMap);
      if (phaseText && phase.active) {
        phaseText.textContent = "현재 단계: " + phase.active.name;
      }
      if (nextJobMetric && phase.next) {
        nextJobMetric.textContent = phase.next.time;
      }
      if (nextJobText && phase.next) {
        nextJobText.textContent = phase.next.name;
      }

      // 2. Fetch statuses in parallel
      var statusResults = await Promise.allSettled([
        fetchJson('/api/v1/scheduler/status'),
        fetchJson('/api/v1/market-tone/today'),
        fetchJson('/api/v1/universe-filter/today'),
        fetchJson('/api/v1/screening/today'),
        fetchJson('/api/v1/daily-plan/today'),
        fetchJson('/api/v1/decision/status'),
        fetchJson('/api/v1/orders/today'),
        fetchJson('/api/v1/orders/positions'),
        fetchJson('/api/v1/funnel/summary'),  // index 8
      ]);

      // Funnel summary 렌더링
      if (statusResults[8].status === 'fulfilled' && statusResults[8].value.ok) {
        renderFunnel(statusResults[8].value.payload);
      }

      function isOk(idx) { return statusResults[idx].status === 'fulfilled' && statusResults[idx].value.ok; }
      function getValue(idx) { return statusResults[idx].status === 'fulfilled' ? statusResults[idx].value : null; }

      var scheduleSkipped = isScheduleSkipActive(getValue(0));

      var stepStates = {
        s1: isOk(0) && statusResults[0].value.payload.last_run ? 'completed' : 'pending',
        s2: getPipelineReadState('s2', getValue(1), scheduleSkipped),
        s3: getPipelineReadState('s3', getValue(2), scheduleSkipped),
        s4: getPipelineReadState('s4', getValue(3), scheduleSkipped),
        s5: getPipelineReadState('s5', getValue(4), scheduleSkipped),
        s5v: scheduleSkipped ? 'skipped' : (hasDailyPlanStatus(getValue(4), ['validated', 'active']) ? 'completed' : 'pending'),
        s5a: scheduleSkipped ? 'skipped' : (hasDailyPlanStatus(getValue(4), ['active']) ? 'completed' : 'pending'),
        s6: scheduleSkipped ? 'skipped' : (isOk(5) && statusResults[5].value.payload.active ? 'running' : 'pending'),
        s7: isOk(6) && statusResults[6].value.payload.orders && statusResults[6].value.payload.orders.length > 0 ? 'completed' : 'pending',
        s8: isOk(7) && statusResults[7].value.payload.positions && statusResults[7].value.payload.positions.length > 0 ? 'completed' : 'pending',
        s9: 'pending',
        s10: 'pending',
        s11: 'pending',
      };

      // Special logic for Running state if not already set
      if (stepStates.s6 !== 'running') {
        var nowMin = phase.currentMinutes;
        OPS_STEPS.forEach(step => {
          if (stepStates[step.id] === 'pending' && ["s2", "s3", "s4", "s5", "s5v", "s5a", "s6"].indexOf(step.id) < 0) {
            var sTime = stepDisplayTime(step, settingsMap);
            if (isClockTime(sTime) && nowMin >= minutesOf(sTime) && nowMin < minutesOf(sTime) + 15) {
              stepStates[step.id] = 'running';
            }
          }
        });
      }

      var html = '';
      OPS_STEPS.forEach((step, index) => {
        var sTime = stepDisplayTime(step, settingsMap);
        var state = stepStates[step.id];
        
        var bgColor = 'var(--panel-2)';
        var borderColor = 'var(--border)';
        var statusText = '대기';
        
        if (state === 'completed') {
          bgColor = 'var(--green-soft)';
          borderColor = 'var(--green)';
          statusText = '완료';
        } else if (state === 'running') {
          bgColor = 'var(--blue-soft)';
          borderColor = 'var(--blue)';
          statusText = '실행중';
        } else if (state === 'skipped') {
          bgColor = 'var(--yellow-soft)';
          borderColor = 'var(--yellow)';
          statusText = '스킵';
        } else if (state === 'missing') {
          statusText = '미생성';
        }

        html += '<div style="flex:0 0 90px; text-align:center;">'
          + '<div style="font-size:10px; color:var(--muted); margin-bottom:4px;">' + sTime + '</div>'
          + '<div style="padding:6px 4px; border-radius:6px; font-size:11px; font-weight:600; background:' + bgColor + '; border: 1px solid ' + borderColor + ';">'
          + step.label
          + '</div>'
          + '<div style="font-size:10px; margin-top:4px; color:var(--muted)">' + statusText + '</div>'
          + '</div>';
        
        if (index < OPS_STEPS.length - 1) {
          html += '<div style="flex:0 0 16px; display:flex; align-items:center; color:var(--muted); justify-content:center;">→</div>';
        }
      });
      feed.innerHTML = html;

    } catch(e) {
      console.error("renderTodayFeed error", e);
      feed.innerHTML = '<div class="muted">타임라인 로드 실패</div>';
    }
  }

  function updateLastTime() {
    if (!lastUpdate) {
      return;
    }

    var now = new Date();
    var yyyy = now.getFullYear();
    var mm = String(now.getMonth() + 1).padStart(2, "0");
    var dd = String(now.getDate()).padStart(2, "0");
    var hh = String(now.getHours()).padStart(2, "0");
    var mi = String(now.getMinutes()).padStart(2, "0");
    var ss = String(now.getSeconds()).padStart(2, "0");
    lastUpdate.textContent = yyyy + "-" + mm + "-" + dd + " " + hh + ":" + mi + ":" + ss;
  }

  function setStatusChip(element, kind, text) {
    if (!element) {
      return;
    }
    element.className = "status " + kind;
    element.textContent = text;
  }

  /* Escape dynamic table values before writing HTML strings. */
  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function setDotStatus(element, kind) {
    if (!element) {
      return;
    }

    element.classList.remove("green", "yellow", "red", "blue");

    if (kind === "ok") {
      element.classList.add("green");
    } else if (kind === "warn") {
      element.classList.add("yellow");
    } else if (kind === "halted" || kind === "danger") {
      element.classList.add("red");
    } else {
      element.classList.add("blue");
    }
  }

  function formatPercent(value) {
    var numeric = Number(value || 0);
    var prefix = numeric > 0 ? "+" : "";
    return prefix + numeric.toFixed(2) + "%";
  }

  function renderFunnel(funnel) {
    if (!funnelProgress || !funnel) {
      return;
    }
    // renderFunnel은 overview payload.funnel 포맷(market_total/layer1/layer2)을 지원
    // 새로운 /api/v1/funnel/summary 포맷도 지원 (total_universe/layer1_count/layer2_count)
    var total = funnel.total_universe || funnel.market_total || '-';
    var l1 = funnel.layer1_count || funnel.layer1 || '-';
    var l2 = funnel.layer2_count || funnel.layer2 || '-';
    var sig = funnel.signals_count != null ? funnel.signals_count : (funnel.entry_waiting || '-');
    var pos = funnel.positions_count != null ? funnel.positions_count : (funnel.holding || '-');

    var setEl = function(id, val) { var el = document.getElementById(id); if (el) el.textContent = val; };
    setEl('fp-total', typeof total === 'number' ? total.toLocaleString() : total);
    setEl('fp-layer1', typeof l1 === 'number' ? l1.toLocaleString() : l1);
    setEl('fp-layer2', typeof l2 === 'number' ? l2.toLocaleString() : l2);
    setEl('fp-signals', sig);
    setEl('fp-positions', pos);
  }

  /* Update the common header so every screen shows the current display data basis date. */
  function renderDataBasis(dataBasis, fallbackDate) {
    var basis = dataBasis || {};
    var displayDate = basis.display_date || basis.basis_date || fallbackDate || getKstDateString();
    var isToday = basis.is_today;
    if (typeof isToday !== "boolean") {
      isToday = displayDate === getKstDateString();
    }
    var message = basis.message || (isToday ? "오늘 데이터 기준입니다." : "마지막으로 저장된 데이터 기준입니다.");

    if (dataBasisDate) {
      dataBasisDate.textContent = displayDate || "-";
    }
    if (dataBasisNote) {
      dataBasisNote.textContent = message;
      dataBasisNote.title = message;
    }
    if (dataBasisPill) {
      dataBasisPill.classList.remove("good", "warn", "info");
      dataBasisPill.classList.add(isToday ? "good" : "warn");
    }
  }

  function renderOverview(payload) {
    if (!payload) {
      return;
    }

    overviewData = payload;
    renderDataBasis(payload.data_basis, payload.trade_date);
    timeline = payload.timeline || timeline;
    sampleLogs = (payload.logs || []).map(function (entry) {
      return [entry.time, entry.text];
    });
    isHalted = Boolean(payload.emergency_halt);

    if (engineText) {
      engineText.textContent = isHalted ? "Auto Engine HALTED" : "Auto Engine RUNNING";
    }
    setDotStatus(engineDot, isHalted ? "halted" : "ok");
    setDotStatus(restDot, payload.health.kis_rest.status);
    setDotStatus(socketDot, payload.health.websocket.status);

    if (restStatusText) {
      restStatusText.textContent = "KIS REST " + payload.health.kis_rest.detail;
    }
    if (socketStatusText) {
      socketStatusText.textContent = "WebSocket " + payload.health.websocket.detail;
    }
    if (modeMetric) {
      modeMetric.textContent = payload.mode || "AUTO";
      modeMetric.classList.remove("good", "bad", "warn", "info");
      modeMetric.classList.add(isHalted ? "bad" : "good");
    }
    if (modeDetail) {
      modeDetail.textContent = payload.mock_mode ? "실거래 엔진 미구현 · 콘솔 mock 상태" : "Daily Plan 활성";
    }
    if (pnlMetric) {
      pnlMetric.textContent = formatPercent(payload.pnl_percent);
      pnlMetric.classList.remove("good", "bad");
      pnlMetric.classList.add(Number(payload.pnl_percent) >= 0 ? "good" : "bad");
    }
    if (pnlDetail) {
      pnlDetail.textContent = "일일 손실한도 " + formatPercent(payload.daily_loss_limit_percent);
    }
    if (positionsMetric) {
      positionsMetric.innerHTML = String(payload.open_positions) + ' <small>/ ' + String(payload.max_positions) + '</small>';
    }
    if (positionsDetail) {
      positionsDetail.textContent = isHalted ? "신규 주문 차단" : "신규 주문 허용";
    }
    if (kisTokenDetail) {
      kisTokenDetail.textContent = payload.updated_at || "-";
    }
    if (rulepackDetail) {
      rulepackDetail.textContent = payload.health.rulepack.detail;
    }
    if (websocketDetail) {
      websocketDetail.textContent = payload.health.websocket.detail;
    }
    if (riskDetail) {
      riskDetail.textContent = payload.health.risk_guard.detail;
    }

    setStatusChip(kisTokenStatus, "ok", "정상");
    setStatusChip(rulepackStatus, payload.health.rulepack.status === "ok" ? "ok" : "info", payload.health.rulepack.detail);
    setStatusChip(websocketStatus, payload.health.websocket.status === "ok" ? "ok" : "info", payload.health.websocket.detail);
    setStatusChip(riskStatus, isHalted ? "danger" : "ok", isHalted ? "차단" : "허용");

    if (isHalted) {
      applyHaltState({
        mode: payload.mode || "HALT"
      });
    } else if (haltBtn) {
      haltBtn.textContent = "긴급정지";
      haltBtn.disabled = false;
      haltBtn.style.opacity = "1";
      haltBtn.style.cursor = "pointer";
    }

    renderFunnel(payload.funnel);
    renderTodayFeed();
  }

  function renderFallbackOverview(reason) {
    isHalted = false;
    overviewData = { timeline: timeline, logs: sampleLogs.map(function(log) { return { time: log[0], text: log[1] }; }) };
    renderDataBasis({
      display_date: getKstDateString(),
      is_today: true,
      message: "overview API 실패로 기준일 확인 필요"
    });

    if (engineText) {
      engineText.textContent = "Auto Engine MOCK";
    }
    if (modeMetric) {
      modeMetric.textContent = "MOCK";
      modeMetric.classList.remove("good", "bad", "warn", "info");
      modeMetric.classList.add("warn");
    }
    if (modeDetail) {
      modeDetail.textContent = "백엔드 overview 연결 실패 · 정적 mock 상태";
    }
    if (positionsDetail) {
      positionsDetail.textContent = "실주문 차단 · mock 표시";
    }
    if (restStatusText) {
      restStatusText.textContent = "KIS REST overview API 실패";
    }
    if (socketStatusText) {
      socketStatusText.textContent = "WebSocket mock 상태";
    }
    if (riskDetail) {
      riskDetail.textContent = reason;
    }

    setDotStatus(engineDot, "warn");
    setDotStatus(restDot, "warn");
    setDotStatus(socketDot, "info");
    setStatusChip(kisTokenStatus, "warn", "mock");
    setStatusChip(rulepackStatus, "warn", "fallback");
    setStatusChip(websocketStatus, "info", "mock");
    setStatusChip(riskStatus, "warn", "확인 필요");
    renderTodayFeed();
  }

  function renderRulepack(payload) {
    if (!payload) {
      return;
    }

    if (rulepackBadge) {
      rulepackBadge.textContent = payload.rulepack_id + " " + (payload.status === "mock" ? "mock 적용" : "적용");
      rulepackBadge.className = "status " + (payload.status === "mock" ? "info" : "ok");
    }
    if (rulepackSummary) {
      rulepackSummary.textContent = payload.summary;
    }
    if (rulepackChanges) {
      rulepackChanges.innerHTML = (payload.changes || []).map(function (text) {
        return "<li>" + text + "</li>";
      }).join("");
    }
    if (rulepackJson) {
      rulepackJson.textContent = JSON.stringify(payload, null, 2);
    }
  }

  function renderDataHealth(payload) {
    if (consoleFooterNote && payload && payload.note) {
      consoleFooterNote.textContent = payload.note;
    }
  }

  function getStatusClass(kind) {
    if (kind === "success" || kind === "ok" || kind === "live") {
      return "ok";
    }
    if (kind === "error" || kind === "danger") {
      return "danger";
    }
    if (kind === "mock") {
      return "warn";
    }
    return "info";
  }

  function getSourceLabel(source) {
    if (source === "live") {
      return "LIVE";
    }
    if (source === "backend") {
      return "BACKEND";
    }
    return "MOCK";
  }

  /* Render admin audit logs so PM can distinguish mock-safe data from real backend actions. */
  function renderApiLogs(payload) {
    if (!payload || !apiLogsTableBody) {
      return;
    }

    var items = payload.items || [];

    if (apiLogsCount) {
      apiLogsCount.textContent = String(items.length) + "건";
      apiLogsCount.className = "status " + (payload.mock_mode ? "warn" : "info");
    }
    if (apiLogsMetric) {
      apiLogsMetric.textContent = String(items.length);
    }
    if (apiLogsLastUpdate) {
      apiLogsLastUpdate.textContent = payload.updated_at || "-";
    }
    if (apiLogsMode) {
      apiLogsMode.textContent = payload.mock_mode ? "MOCK SAFE" : "LIVE";
      apiLogsMode.className = "metric " + (payload.mock_mode ? "warn" : "good");
    }
    if (apiLogsNote) {
      apiLogsNote.textContent = payload.note || "관리 로그 설명이 없습니다.";
    }

    if (items.length === 0) {
      apiLogsTableBody.innerHTML = '<tr><td colspan="8" class="muted">기록된 관리 로그가 없습니다.</td></tr>';
      return;
    }

    apiLogsTableBody.innerHTML = items.map(function (entry) {
      var source = getSourceLabel(entry.source);
      var apiLabel = entry.api_name_or_path || ((entry.method || '-') + ' ' + (entry.endpoint || '-'));
      var rawTime = entry.called_at || entry.timestamp || '';
      var calledAt = '-';
      if (rawTime && rawTime.length >= 19) {
        calledAt = rawTime.slice(2, 10) + ' ' + rawTime.slice(11, 19);
      } else if (rawTime) {
        calledAt = rawTime;
      }
      return ''
        + '<tr>'
        + '<td>' + (entry.feature_name || '-') + '</td>'
        + '<td>' + (entry.purpose || '-') + '</td>'
        + '<td>' + (entry.result_summary || entry.message || '-') + '</td>'
        + '<td>' + calledAt + '</td>'
        + '<td>' + apiLabel + '</td>'
        + '<td><span class="status ' + getStatusClass(entry.status) + '">' + (entry.status || '-') + '</span></td>'
        + '<td><span class="status ' + getStatusClass(entry.source) + '">' + source + '</span></td>'
        + '<td><span class="status ' + (entry.live ? 'ok' : 'warn') + '">' + (entry.live ? 'LIVE' : 'NO') + '</span></td>'
        + '</tr>';
    }).join("");
  }

  async function loadApiLogs() {
    var today = new Date();
    var dateStr = today.getFullYear() + '-'
      + String(today.getMonth()+1).padStart(2,'0') + '-'
      + String(today.getDate()).padStart(2,'0');
    var result = await fetchJson('/api/v1/bot/api-logs?date=' + dateStr);
    // 백엔드가 date 파라미터 미지원 시 클라이언트에서 필터
    if (result && result.payload && Array.isArray(result.payload)) {
      result.payload = result.payload.filter(function(e) {
        var ts = e.called_at || e.timestamp || '';
        return ts.startsWith(dateStr);
      });
    }
    renderApiLogs(result && result.payload);
  }

  function applyHaltState(payload) {
    isHalted = true;
    if (engineText) {
      engineText.textContent = "Auto Engine HALTED";
    }
    setDotStatus(engineDot, "halted");
    if (modeMetric) {
      modeMetric.textContent = payload && payload.mode ? payload.mode : "HALT";
      modeMetric.classList.remove("good", "warn", "info");
      modeMetric.classList.add("bad");
    }
    if (modeDetail) {
      modeDetail.textContent = "긴급정지 적용됨";
    }
    if (positionsDetail) {
      positionsDetail.textContent = "신규 주문 차단";
    }
    setStatusChip(riskStatus, "danger", "차단");
    if (riskDetail) {
      riskDetail.textContent = "긴급정지 요청으로 신규 진입 차단";
    }
    if (haltBtn) {
      haltBtn.textContent = "운영재개";
      haltBtn.classList.remove("danger");
      haltBtn.classList.add("warn");
      haltBtn.disabled = false;
      haltBtn.style.opacity = "1";
      haltBtn.style.cursor = "pointer";
    }
  }

  function applyResumeState(payload) {
    isHalted = false;
    if (engineText) {
      engineText.textContent = "Auto Engine RUNNING";
    }
    setDotStatus(engineDot, "ok");
    if (modeMetric) {
      modeMetric.textContent = payload && payload.mode ? payload.mode : "AUTO";
      modeMetric.classList.remove("bad");
      modeMetric.classList.add("good");
    }
    if (modeDetail) {
      modeDetail.textContent = "운영 재개됨";
    }
    if (positionsDetail) {
      positionsDetail.textContent = "신규 주문 허용";
    }
    setStatusChip(riskStatus, "ok", "정상");
    if (riskDetail) {
      riskDetail.textContent = "신규 주문 허용";
    }
    if (haltBtn) {
      haltBtn.textContent = "긴급정지";
      haltBtn.classList.remove("warn");
      haltBtn.classList.add("danger");
    }
  }


  function showToast(message) {
    alert(message); // Simple alert as fallback if showToast is not defined
  }

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
