  /* Console bootstrap uses FastAPI mock endpoints until live trading is implemented. */
  var API_BASE = window.location.origin;
  var screens = document.querySelectorAll(".screen");
  var navButtons = document.querySelectorAll("#nav button");
  var mobileMenu = document.getElementById("mobileMenu");
  var loginForm = document.getElementById("loginForm");
  var loginUsername = document.getElementById("loginUsername");
  var loginPassword = document.getElementById("loginPassword");
  var loginStatus = document.getElementById("loginStatus");
  var loginSubmitBtn = document.getElementById("loginSubmitBtn");
  var mfaPanel = document.getElementById("mfaPanel");
  var mfaMethodField = document.getElementById("mfaMethodField");
  var mfaMethodSelect = document.getElementById("mfaMethodSelect");
  var mfaStartBtn = document.getElementById("mfaStartBtn");
  var mfaSetupBox = document.getElementById("mfaSetupBox");
  var mfaCodeField = document.getElementById("mfaCodeField");
  var mfaCode = document.getElementById("mfaCode");
  var mfaVerifyBtn = document.getElementById("mfaVerifyBtn");
  var themeBtn = document.getElementById("themeBtn");
  var logoutBtn = document.getElementById("logoutBtn");
  var haltBtn = document.getElementById("haltBtn");
  var engineDot = document.getElementById("engineDot");
  var engineText = document.getElementById("engineText");
  var restDot = document.getElementById("restDot");
  var restStatusText = document.getElementById("restStatusText");
  var socketDot = document.getElementById("socketDot");
  var socketStatusText = document.getElementById("socketStatusText");
  var modeMetric = document.getElementById("modeMetric");
  var modeDetail = document.getElementById("modeDetail");
  var pnlMetric = document.getElementById("pnlMetric");
  var pnlDetail = document.getElementById("pnlDetail");
  var positionsMetric = document.getElementById("positionsMetric");
  var positionsDetail = document.getElementById("positionsDetail");
  var phaseText = document.getElementById("phaseText");
  var nextJobMetric = document.getElementById("nextJobMetric");
  var nextJobText = document.getElementById("nextJobText");
  var lastUpdate = document.getElementById("lastUpdate");
  var todayOpsFeed = document.getElementById("today-ops-feed");
  var funnelProgress = document.getElementById("funnelProgress");
  var kisTokenStatus = document.getElementById("kisTokenStatus");
  var kisTokenDetail = document.getElementById("kisTokenDetail");
  var rulepackStatus = document.getElementById("rulepackStatus");
  var rulepackDetail = document.getElementById("rulepackDetail");
  var websocketStatus = document.getElementById("websocketStatus");
  var websocketDetail = document.getElementById("websocketDetail");
  var riskStatus = document.getElementById("riskStatus");
  var riskDetail = document.getElementById("riskDetail");
  var consoleFooterNote = document.getElementById("consoleFooterNote");
  var apiLogsCount = document.getElementById("apiLogsCount");
  var apiLogsMetric = document.getElementById("apiLogsMetric");
  var apiLogsLastUpdate = document.getElementById("apiLogsLastUpdate");
  var apiLogsMode = document.getElementById("apiLogsMode");
  var apiLogsNote = document.getElementById("apiLogsNote");
  var apiLogsTableBody = document.getElementById("apiLogsTableBody");

  var isHalted = false;
  var currentUser = null;
  var mfaState = null;
  var overviewData = null;
  var OPS_STEPS = [
    { id: 's1', label: 'S1 토큰 갱신', defaultTime: '07:45', settingKey: 'schedule_trade_prep_time', detail: '거래준비 프로세스 하위 단계 · KIS token-refresh' },
    { id: 's2', label: 'S2 시장톤 분석', defaultTime: '07:45', settingKey: 'schedule_trade_prep_time', detail: '거래준비 프로세스 하위 단계 · LLM -> market_tone_results' },
    { id: 's3', label: 'S3 유니버스 필터', defaultTime: '07:45', settingKey: 'schedule_trade_prep_time', detail: '거래준비 프로세스 하위 단계 · KIS -> universe_filter_results' },
    { id: 's4', label: 'S4 하이브리드 스크리닝', defaultTime: '07:45', settingKey: 'schedule_trade_prep_time', detail: '거래준비 프로세스 하위 단계 · LLM 정성 평가 -> hybrid_screening_results' },
    { id: 's5', label: 'S5 Daily Plan 생성', defaultTime: '07:45', settingKey: 'schedule_trade_prep_time', detail: '거래준비 프로세스 하위 단계 · Scheduler -> daily_trading_plans' },
    { id: 's5v', label: 'S5-V Daily Plan 검증', defaultTime: '07:45', settingKey: 'schedule_trade_prep_time', detail: '거래준비 프로세스 하위 단계 · Schema/Risk Guard 검증' },
    { id: 's5a', label: 'S5-A Daily Plan 활성화 확인', defaultTime: '07:45', settingKey: 'schedule_trade_prep_time', detail: '거래준비 프로세스 하위 단계 · active plan 상태 확인' },
    { id: 's6', label: 'S6 Decision Engine 활성화', defaultTime: '09:45', settingKey: 'schedule_s6_time', detail: 'WS 연결 + RulePack + Risk Profile + Daily Plan 조건 감시' },
    { id: 's7', label: 'S7 주문 실행', defaultTime: '실시간', settingKey: 'schedule_s7_time', detail: '오늘 발행된 주문 내역 조회' },
    { id: 's8', label: 'S8 Position Manager', defaultTime: '실시간', settingKey: 'schedule_s8_time', detail: 'WS tick -> 손절/트레일링/강제청산 감시' },
    { id: 's9', label: 'S9 당일 청산', defaultTime: '15:20', settingKey: 'schedule_postprocess_time', detail: '후처리 프로세스 하위 단계 · 전량 시장가 청산' },
    { id: 's10', label: 'S10 Review & Audit', defaultTime: '15:20', settingKey: 'schedule_postprocess_time', detail: '후처리 프로세스 하위 단계 · review_audit -> daily_review_reports' },
    { id: 's11', label: 'S11 Learning Memory Builder', defaultTime: '22:00', settingKey: 'schedule_s11_time', detail: 'Trade Review -> Learning Memory' },
  ];
  var SCHEDULED_OPERATIONS = [
    { id: 'trade-prep', label: '거래준비 프로세스 시작 (S1~S5-A 순차 실행)', defaultTime: '07:45', settingKey: 'schedule_trade_prep_time' },
    { id: 's6', label: 'S6 Decision Engine 시간', defaultTime: '09:45', settingKey: 'schedule_s6_time' },
    { id: 'postprocess', label: '후처리 프로세스 시작 (S9~S10 순차 실행)', defaultTime: '15:20', settingKey: 'schedule_postprocess_time' },
    { id: 's11', label: 'S11 Learning Memory 시간', defaultTime: '22:00', settingKey: 'schedule_s11_time' },
  ];
  var timeline = SCHEDULED_OPERATIONS
    .filter(function(step) { return /^\d{2}:\d{2}$/.test(step.defaultTime); })
    .map(function(step) { return { time: step.defaultTime, name: step.label }; });
  var sampleLogs = [
    ["07:45", "KIS 토큰 갱신 완료. Access token 유효성 확인."],
    ["08:00", "AI 시장 톤 분석 완료. 코스닥 상대 강세, 리스크 중간."],
    ["08:15", "Layer 1 Universe 생성 완료. 2,500개 중 200개 통과."]
  ];

  /* Switch visible console screen and trigger the screen-specific data refresh. */
  function showScreen(name) {
    if (name === "missed-opportunity") {
      name = "shadow-trading";
    }
    sessionStorage.setItem('currentScreen', name);
    if (window._tmRefreshInterval) {
      clearInterval(window._tmRefreshInterval);
      window._tmRefreshInterval = null;
    }
    stopTradingMonitorStream();

    for (var i = 0; i < screens.length; i++) {
      screens[i].classList.remove("active");
    }

    var target = document.getElementById("screen-" + name);
    if (target) {
      target.classList.add("active");
    }

    for (var j = 0; j < navButtons.length; j++) {
      navButtons[j].classList.remove("active");
      if (navButtons[j].getAttribute("data-screen") === name) {
        navButtons[j].classList.add("active");
      }
    }

    if (mobileMenu) {
      mobileMenu.value = name;
    }

    if (name === "settings") {
      initSettingsUI();
      loadBuyConditions();
    }

    if (name === "engine-test") {
      engineTestLoadTodayResults();
    }

    if (name === "data") {
      loadDataAndApi();
      loadDQStatus();
    }

    if (name === "alerts") {
      loadAlerts();
    }

    if (name === "approval") {
      loadApprovalQueue();
    }

    if (name === "shadow-trading") {
      loadMissedTracking();
    }
    if (name === "false-positive") {
      loadFalsePositive();
    }
    if (name === "confidence-cal") {
      loadConfidenceCalibration();
    }

    if (name === "rulepack") {
      loadDailyPlanScreen();
    }

    if (name === "funnel") {
      loadFunnelData();
    }

    if (name === "expert-knowledge") {
      ekLoadHistory();
    }

    if (name === "trading") {
      loadTradingMonitor();
      startTradingMonitorStream();
    }

    if (name === "today") {
      loadTodayOrders();
      loadTodayPlanStatus();
    }

    if (name === "risk") {
      loadExecutionRisk();
    }

    if (name === "review") {
      loadReviewAuditScreen();
    }

    if (name === "statistics") {
      loadStatistics();
      loadAllOrders();
    }

    if (name === "positions") {
      loadAccountBalance();
      loadPositionMonitoring();
      loadTodayOrders();
      if (_positionsTimer) clearInterval(_positionsTimer);
      _positionsTimer = setInterval(function() {
        loadPositionMonitoring();
        loadTodayOrders();
      }, 5000);
    } else {
      if (_positionsTimer) {
        clearInterval(_positionsTimer);
        _positionsTimer = null;
      }
    }

    if (name === "live") {
      loadLiveData();
      if (liveRefreshTimer) clearInterval(liveRefreshTimer);
      liveRefreshTimer = setInterval(loadLiveData, 10000);
    } else {
      if (liveRefreshTimer) {
        clearInterval(liveRefreshTimer);
        liveRefreshTimer = null;
      }
    }
  }

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

  function renderOverview(payload) {
    if (!payload) {
      return;
    }

    overviewData = payload;
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

  async function fetchJson(path, options) {
    var response = await fetch(API_BASE + path, options || {});
    if (response.status === 401) {
      showLogin("로그인이 필요합니다.");
      throw new Error(path + " 인증 필요");
    }
    if (!response.ok) {
      throw new Error(path + " 요청 실패: " + response.status);
    }

    var payload = await response.json();
    if (payload && payload.ok === false) {
      throw new Error(path + " 응답 오류: " + (payload.error || "unknown"));
    }
    return payload;
  }

  function showLogin(message, options) {
    var opts = options || {};
    document.body.classList.add("auth-required");
    currentUser = null;
    resetMfaPanel();
    if (loginStatus) {
      loginStatus.textContent = message || "로그인이 필요합니다.";
      loginStatus.classList.toggle("error", Boolean(message));
    }
    if (loginPassword && opts.clearPassword) {
      loginPassword.value = "";
    }
    if (loginPassword && opts.focusPassword) {
      loginPassword.focus();
    }
  }

  function resetMfaPanel() {
    mfaState = null;
    if (mfaPanel) mfaPanel.style.display = "none";
    if (mfaMethodField) mfaMethodField.style.display = "none";
    if (mfaStartBtn) mfaStartBtn.style.display = "none";
    if (mfaSetupBox) {
      mfaSetupBox.style.display = "none";
      mfaSetupBox.innerHTML = "";
    }
    if (mfaCodeField) mfaCodeField.style.display = "none";
    if (mfaVerifyBtn) mfaVerifyBtn.style.display = "none";
    if (mfaCode) mfaCode.value = "";
    if (loginSubmitBtn) {
      loginSubmitBtn.style.display = "";
      loginSubmitBtn.textContent = "로그인";
      loginSubmitBtn.disabled = false;
    }
  }

  function showMfaEnrollment(payload) {
    mfaState = { mode: "enroll", challengeId: payload.challenge_id };
    if (loginSubmitBtn) loginSubmitBtn.style.display = "none";
    if (mfaPanel) mfaPanel.style.display = "";
    if (mfaMethodField) mfaMethodField.style.display = "";
    if (mfaStartBtn) {
      mfaStartBtn.style.display = "";
      mfaStartBtn.textContent = "선택한 수단 등록";
      mfaStartBtn.disabled = false;
    }
    if (mfaSetupBox) {
      mfaSetupBox.style.display = "";
      mfaSetupBox.textContent = "원하는 2차 인증 수단을 선택해 등록하세요.";
    }
    if (mfaCodeField) mfaCodeField.style.display = "none";
    if (mfaVerifyBtn) mfaVerifyBtn.style.display = "none";
    if (loginStatus) {
      loginStatus.textContent = "비밀번호 확인 완료. 2차 인증 수단을 등록하세요.";
      loginStatus.classList.remove("error");
    }
  }

  function showMfaLogin(payload) {
    mfaState = { mode: "login", challengeId: payload.challenge_id };
    if (loginSubmitBtn) loginSubmitBtn.style.display = "none";
    if (mfaPanel) mfaPanel.style.display = "";
    if (mfaMethodField) mfaMethodField.style.display = "none";
    if (mfaStartBtn) mfaStartBtn.style.display = "none";
    if (mfaSetupBox) {
      var labels = (payload.methods || []).map(function(m) { return m.label || m.method_type; }).join(", ");
      mfaSetupBox.style.display = "";
      mfaSetupBox.textContent = "등록된 2차 인증 수단: " + (labels || "인증 코드");
    }
    if (mfaCodeField) mfaCodeField.style.display = "";
    if (mfaVerifyBtn) {
      mfaVerifyBtn.style.display = "";
      mfaVerifyBtn.textContent = "2차 인증 확인";
    }
    if (loginStatus) {
      loginStatus.textContent = "2차 인증 코드를 입력하세요.";
      loginStatus.classList.remove("error");
    }
    if (mfaCode) mfaCode.focus();
  }

  async function startMfaEnrollment() {
    if (!mfaState || mfaState.mode !== "enroll") return;
    var method = mfaMethodSelect ? mfaMethodSelect.value : "totp";
    if (mfaStartBtn) {
      mfaStartBtn.disabled = true;
      mfaStartBtn.textContent = "등록 준비 중...";
    }
    var data = await fetchJson("/api/v1/auth/mfa/enroll/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ challenge_id: mfaState.challengeId, method_type: method })
    });
    mfaState = { mode: "enroll_verify", method: method, challengeId: data.payload.challenge_id };
    if (mfaStartBtn) mfaStartBtn.style.display = "none";
    if (mfaCodeField) mfaCodeField.style.display = "";
    if (mfaVerifyBtn) {
      mfaVerifyBtn.style.display = "";
      mfaVerifyBtn.textContent = "등록 완료";
    }
    if (method === "totp") {
      if (mfaSetupBox) {
        mfaSetupBox.style.display = "";
        var qrSrc = data.payload.qr_svg_data_uri || "";
        mfaSetupBox.innerHTML = ""
          + "<div style=\"display:flex; gap:12px; align-items:flex-start; flex-wrap:wrap;\">"
          + (qrSrc ? "<img alt=\"2차 인증 QR 코드\" src=\"" + escapeHtml(qrSrc) + "\" style=\"width:160px; height:160px; padding:10px; border:1px solid var(--line); border-radius:6px; background:#fff;\">" : "")
          + "<div style=\"min-width:180px; flex:1;\">"
          + "<div>인증 앱에서 QR 코드를 스캔한 뒤 6자리 코드를 입력하세요.</div>"
          + "<div style=\"margin-top:8px; font-weight:700; word-break:break-all; color:var(--text);\">"
          + escapeHtml(data.payload.secret)
          + "</div>"
          + "<div style=\"margin-top:6px; font-size:11px; word-break:break-all;\">QR 스캔이 안 되면 위 키를 직접 입력하세요.</div>"
          + "</div></div>";
      }
      if (mfaCode) {
        mfaCode.placeholder = "6자리 인증 앱 코드";
        mfaCode.value = "";
        mfaCode.focus();
      }
    } else {
      if (mfaSetupBox) {
        mfaSetupBox.style.display = "";
        mfaSetupBox.innerHTML = "아래 백업 코드를 안전한 곳에 보관하세요. 등록 확인을 위해 코드 하나를 입력하세요.<br><pre style=\"white-space:pre-wrap; margin:8px 0 0;\">"
          + escapeHtml((data.payload.codes || []).join("\n"))
          + "</pre>";
      }
      if (mfaCode) {
        mfaCode.placeholder = "백업 코드 하나 입력";
        mfaCode.value = "";
        mfaCode.focus();
      }
    }
  }

  async function verifyMfaCode() {
    if (!mfaState) return;
    var endpoint = mfaState.mode === "login" ? "/api/v1/auth/mfa/verify" : "/api/v1/auth/mfa/enroll/verify";
    var data = await fetchJson(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ challenge_id: mfaState.challengeId, code: mfaCode ? mfaCode.value : "" })
    });
    if (loginStatus) {
      loginStatus.textContent = mfaState.mode === "login" ? "2차 인증 완료. 콘솔을 여는 중입니다." : "2차 인증 수단 등록 완료. 콘솔을 여는 중입니다.";
      loginStatus.classList.remove("error");
    }
    resetMfaPanel();
    showConsole(data.payload.user);
    await loadConsoleData();
  }

  function showConsole(user) {
    currentUser = user || null;
    document.body.classList.remove("auth-required");
    resetMfaPanel();
    if (loginStatus) {
      loginStatus.textContent = "";
      loginStatus.classList.remove("error");
    }
  }

  async function checkAuth() {
    try {
      var result = await fetchJson("/api/v1/auth/me");
      showConsole(result.payload.user);
      return true;
    } catch (error) {
      showLogin("로그인이 필요합니다.");
      return false;
    }
  }

  async function submitLogin() {
    if (loginStatus) {
      loginStatus.textContent = "로그인 확인 중입니다.";
      loginStatus.classList.remove("error");
    }
    var response = await fetch(API_BASE + "/api/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: loginUsername ? loginUsername.value : "",
        password: loginPassword ? loginPassword.value : ""
      })
    });
    if (!response.ok) {
      throw new Error("아이디 또는 비밀번호를 확인하세요.");
    }
    var result = await response.json();
    if (result.payload && result.payload.status === "mfa_enrollment_required") {
      showMfaEnrollment(result.payload);
      return;
    }
    if (result.payload && result.payload.status === "mfa_required") {
      showMfaLogin(result.payload);
      return;
    }
    showConsole(result.payload.user);
    await loadConsoleData();
  }

  async function logout() {
    await fetch(API_BASE + "/api/v1/auth/logout", { method: "POST" });
    showLogin("로그아웃되었습니다.", { clearPassword: true, focusPassword: true });
  }

	  async function loadConsoleData() {
    var results = await Promise.allSettled([
      fetchJson("/api/v1/bot/overview"),
      fetchJson("/api/v1/bot/data-health")
    ]);
    var apiLogError = null;

    var overviewResult = results[0];
    var dataHealthResult = results[1];
    var failedEndpoints = [];

    if (overviewResult.status === "fulfilled") {
      renderOverview(overviewResult.value.payload);
    } else {
      failedEndpoints.push("overview");
      renderFallbackOverview("overview API 실패");
      console.error("Overview bootstrap failed:", overviewResult.reason);
    }

    if (dataHealthResult.status === "fulfilled") {
      renderDataHealth(dataHealthResult.value.payload);
    } else {
      failedEndpoints.push("data-health");
      console.error("Data health bootstrap failed:", dataHealthResult.reason);
    }

	    try {
	      await loadApiLogs();
	    } catch (error) {
	      apiLogError = error;
	      console.error("API logs bootstrap failed:", error);
	    }

	    try {
	      await loadTodayOrders();
	    } catch (error) {
	      console.error("Today orders bootstrap failed:", error);
	    }

    if (failedEndpoints.length > 0) {
      var warningMessage = "일부 백엔드 API 연결 실패: " + failedEndpoints.join(", ") + " · 정적 mock 상태를 표시 중입니다.";
      if (apiLogError) {
        warningMessage += " 관리 로그 조회도 실패했습니다.";
      }
      if (consoleFooterNote) {
        consoleFooterNote.textContent = "API 일부 실패 · 실거래 엔진 미구현 · fallback mock 표시중";
      }
      return;
    }

    if (consoleFooterNote && dataHealthResult.value && dataHealthResult.value.payload && dataHealthResult.value.payload.note) {
      consoleFooterNote.textContent = dataHealthResult.value.payload.note;
    }
  }

  async function emergencyHalt() {
    var result = await fetchJson("/api/v1/bot/control/halt", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      }
    });
    applyHaltState(result.payload);
    await loadConsoleData();
  }

  async function emergencyResume() {
    var result = await fetchJson("/api/v1/bot/control/resume", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      }
    });
    applyResumeState(result.payload);
    await loadConsoleData();
  }

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

    for (var i = 0; i < navButtons.length; i++) {
      navButtons[i].addEventListener("click", function () {
        showScreen(this.getAttribute("data-screen"));
      });
    }

    if (mobileMenu) {
      mobileMenu.addEventListener("change", function () {
        showScreen(this.value);
      });
    }

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
  var schedulerKeys = [
    {
      key: "schedule_trade_prep_time",
      label: "거래준비 프로세스 시작 시간",
      default: "07:45",
      description: "S1 토큰 갱신 -> S2 시장톤 -> S3 유니버스 -> S4 스크리닝 -> S5 Daily Plan -> S5-V 검증 -> S5-A 활성화 확인"
    },
    {
      key: "schedule_s6_time",
      label: "S6 Decision Engine 시간",
      default: "09:45",
      description: "기존 S6 자동 활성화 스케줄 유지"
    },
    {
      key: "schedule_s7_time",
      label: "S7 실시간 주문 실행",
      default: "실시간",
      description: "cron 등록 없음 · 실시간/트리거 기반 구조 유지",
      readOnly: true
    },
    {
      key: "schedule_s8_time",
      label: "S8 실시간 Position Manager",
      default: "실시간",
      description: "cron 등록 없음 · 실시간/트리거 기반 구조 유지",
      readOnly: true
    },
    {
      key: "schedule_postprocess_time",
      label: "후처리 프로세스 시작 시간",
      default: "15:20",
      description: "S9 당일 청산 -> S10 Review & Audit 순차 실행"
    },
    {
      key: "schedule_s11_time",
      label: "S11 Learning Memory 시간",
      default: "22:00",
      description: "기존 S11 Learning Memory Builder 스케줄 유지"
    }
  ];

  var exitOverrideKeys = [
    { key: "override_stop_loss_rate", label: "손절률 (stop_loss)", placeholder: "-0.015", example: "예: -0.015 = -1.5%" },
    { key: "override_take_profit_rate", label: "익절률 (take_profit) (사용 안 함)", placeholder: "OFF", example: "고정 익절 사용 안 함", disabled: true },
    { key: "override_trailing_activate_rate", label: "트레일링 활성기준", placeholder: "0.02", example: "예: 0.02 = +2% 도달 시 활성화" },
    { key: "override_trailing_stop_rate", label: "트레일링 손절률", placeholder: "0.01", example: "예: 0.01 = 고점 -1% 시 청산" }
  ];

  /* Load editable global risk settings into the Settings form. */
  async function loadRiskSettings() {
    try {
      var settingsMap = await loadSettingsMap();
      var dailyLoss = document.getElementById("risk-daily-loss");
      var maxPositions = document.getElementById("risk-max-positions");
      var positionSize = document.getElementById("risk-position-size");
      var riskMode = document.getElementById("risk-mode");
      var cutoffTime = document.getElementById("setting-cutoff-time");
      var forceExitTime = document.getElementById("setting-force-exit-time");

      if (dailyLoss) dailyLoss.value = settingsMap["risk.daily_loss_limit_percent"] ?? "-2.0";
      if (maxPositions) maxPositions.value = settingsMap["risk.max_positions"] ?? "5";
      if (positionSize) positionSize.value = ((Number(settingsMap["risk.max_position_rate_per_stock"] ?? 0.10) || 0.10) * 100).toFixed(1).replace(/\.0$/, "");
      if (riskMode) riskMode.value = settingsMap["engine.mode"] || "MONITOR";
      if (cutoffTime) cutoffTime.value = settingsMap["risk.new_entry_cutoff_time"] || "15:10";
      if (forceExitTime) forceExitTime.value = settingsMap["risk.force_exit_time"] || "15:20";
    } catch (e) {
      console.error("Failed to load risk settings", e);
    }
  }

  /* Persist editable global risk settings through system_settings. */
  async function saveRiskSettings() {
    var dailyLoss = document.getElementById("risk-daily-loss");
    var maxPositions = document.getElementById("risk-max-positions");
    var positionSize = document.getElementById("risk-position-size");
    var riskMode = document.getElementById("risk-mode");
    var cutoffTime = document.getElementById("setting-cutoff-time");
    var forceExitTime = document.getElementById("setting-force-exit-time");

    var dailyLossValue = Number(dailyLoss && dailyLoss.value);
    var maxPositionsValue = Number(maxPositions && maxPositions.value);
    var positionSizeValue = Number(positionSize && positionSize.value);
    var cutoffValue = cutoffTime ? cutoffTime.value.trim() : "";
    var forceExitValue = forceExitTime ? forceExitTime.value.trim() : "";

    if (!Number.isFinite(dailyLossValue) || dailyLossValue >= 0) {
      alert("일일 손실 한도는 음수 숫자로 입력하세요.");
      return;
    }
    if (!Number.isInteger(maxPositionsValue) || maxPositionsValue < 1) {
      alert("최대 보유 종목은 1 이상의 정수로 입력하세요.");
      return;
    }
    if (!Number.isFinite(positionSizeValue) || positionSizeValue <= 0 || positionSizeValue > 100) {
      alert("종목당 최대 비중은 0보다 크고 100 이하인 숫자로 입력하세요.");
      return;
    }
    if (!isClockTime(cutoffValue) || !isClockTime(forceExitValue)) {
      alert("시간 형식이 올바르지 않습니다 (HH:MM).");
      return;
    }

    var items = [
      { key: "risk.daily_loss_limit_percent", value: dailyLossValue, value_type: "number" },
      { key: "risk.max_positions", value: maxPositionsValue, value_type: "number" },
      { key: "risk.max_position_rate_per_stock", value: positionSizeValue / 100, value_type: "number" },
      { key: "engine.mode", value: riskMode ? riskMode.value : "MONITOR", value_type: "string" },
      { key: "risk.new_entry_cutoff_time", value: cutoffValue, value_type: "string" },
      { key: "risk.force_exit_time", value: forceExitValue, value_type: "string" }
    ];

    try {
      await Promise.all(items.map(function(item) {
        return fetchJson("/api/v1/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(item)
        });
      }));
      alert("저장됨");
      loadRiskSettings();
    } catch (e) {
      alert("저장 실패: " + e.message);
    }
  }

  /* Load persisted scheduler times into the Settings table. */
  async function loadSchedulerSettings() {
    try {
      var res = await fetchJson("/api/v1/settings");
      var settings = res.payload.items || [];
      var settingsMap = {};
      settings.forEach(function(s) { settingsMap[s.key] = s.value; });

      var html = schedulerKeys.map(function(k) {
        var current = settingsMap[k.key] || k.default;
        var inputHtml = k.readOnly
          ? '<span class="muted">' + escapeHtml(current) + '</span>'
          : '<input type="text" id="input-' + k.key + '" value="' + escapeHtml(current) + '" style="width: 80px; padding: 5px; border-radius: 5px; background: var(--panel-2); color: var(--text); border: 1px solid var(--line);">';
        var buttonHtml = k.readOnly
          ? '<span class="muted">실시간</span>'
          : '<button class="btn primary" onclick="saveSchedulerSetting(\'' + k.key + '\')">저장</button>';
        return ''
          + '<tr>'
          + '  <td>' + k.label + '</td>'
          + '  <td class="muted">' + escapeHtml(k.description || k.key) + '</td>'
          + '  <td>' + escapeHtml(current) + '</td>'
          + '  <td>' + inputHtml + '</td>'
          + '  <td>' + buttonHtml + '</td>'
          + '</tr>';
      }).join("");
      var tbody = document.getElementById("schedulerSettingsTableBody");
      if (tbody) tbody.innerHTML = html;
    } catch (e) {
      console.error("Failed to load scheduler settings", e);
      var tbody = document.getElementById("schedulerSettingsTableBody");
      if (tbody) tbody.innerHTML = '<tr><td colspan="5" class="muted">설정 로드 실패: ' + escapeHtml(e.message) + '</td></tr>';
    }
  }

  /* Save one scheduler time through the frontend-compatible settings POST route. */
  async function saveSchedulerSetting(key) {
    var input = document.getElementById("input-" + key);
    if (!input) return;
    var val = input.value;
    if (!isClockTime(val) && val !== "실시간") {
      alert("시간 형식이 올바르지 않습니다 (HH:MM 또는 실시간)");
      return;
    }
    try {
      await fetchJson("/api/v1/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: key, value: val })
      });
      alert("저장됨 (재시작 필요)");
      loadSchedulerSettings();
    } catch (e) {
      alert("저장 실패: " + e.message);
    }
  }

  /* Load manual exit-rule override values into the Settings table. */
  async function loadExitOverrideSettings() {
    try {
      var res = await fetchJson("/api/v1/settings");
      var settings = res.payload.items || [];
      var settingsMap = {};
      settings.forEach(function(s) { settingsMap[s.key] = s.value; });

      var html = exitOverrideKeys.map(function(k) {
        var current = settingsMap[k.key] == null ? "" : String(settingsMap[k.key]);
        var currentLabel = current === "" ? "-" : current;
        return ''
          + '<tr>'
          + '  <td>' + k.label + '</td>'
          + '  <td>' + escapeHtml(currentLabel) + '</td>'
          + '  <td><input type="text" id="input-' + k.key + '" value="' + escapeHtml(current) + '" placeholder="' + escapeHtml(k.placeholder) + '" style="width: 120px; padding: 5px; border-radius: 5px; background: var(--panel-2); color: var(--text); border: 1px solid var(--line);"></td>'
          + '  <td><button class="btn primary" onclick="saveExitOverrideSetting(\'' + k.key + '\')">저장</button></td>'
          + '  <td class="muted">' + k.example + '</td>'
          + '</tr>';
      }).join("");
      var tbody = document.getElementById("exitOverrideSettingsTableBody");
      if (tbody) tbody.innerHTML = html;
    } catch (e) {
      console.error("Failed to load exit override settings", e);
      var tbody = document.getElementById("exitOverrideSettingsTableBody");
      if (tbody) tbody.innerHTML = '<tr><td colspan="5" class="muted">설정 로드 실패: ' + escapeHtml(e.message) + '</td></tr>';
    }
  }

  /* POST /api/v1/settings saves one exit-rule override value. */
  async function saveExitOverrideSetting(key) {
    var input = document.getElementById("input-" + key);
    if (!input) return;
    var val = input.value.trim();
    if (val !== "" && !/^-?\d+(\.\d+)?$/.test(val)) {
      alert("숫자 형식으로 입력하거나 비워두세요. 예: -0.015");
      return;
    }
    try {
      await fetchJson("/api/v1/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: key, value: val })
      });
      alert("저장됨");
      loadExitOverrideSettings();
    } catch (e) {
      alert("저장 실패: " + e.message);
    }
  }

  async function loadBuyConditions() {
    try {
      var [settingsData, screeningData] = await Promise.all([
        fetchJson('/api/v1/settings').catch(() => null),
        fetchJson('/api/v1/screening/today').catch(() => null)
      ]);

      var settings = {};
      (settingsData?.payload?.items || []).forEach(function(s) {
        settings[s.key] = s.value;
      });      
      var aiEntryRules = screeningData?.payload?.screening?.entry_rules || screeningData?.payload?.entry_rules || {};
      
      var rows = [
        {
          label: 'AI confidence 임계값',
          aiValue: aiEntryRules.min_ai_confidence ?? '-',
          guardKey: 'engine.min_confidence_floor',
          desc: 'AI가 설정한 오늘의 최소 신뢰도 / 가드레일은 절대 하한선'
        },
        {
          label: '최소 등락률 %',
          aiValue: aiEntryRules.min_price_change_pct ?? '-',
          guardKey: 'engine.min_price_change_pct',
          desc: '이 등락률 미만 종목은 매수 신호 발생 안 함'
        },
        {
          label: '최대 등락률 %',
          aiValue: aiEntryRules.max_price_change_pct ?? '-',
          guardKey: 'engine.max_price_change_pct',
          desc: '이 등락률 초과 종목은 과열로 판단해 제외'
        },
      ];
      
      var html = rows.map(function(row) {
        var guardVal = settings[row.guardKey] ?? '-';
        return '<tr style="border-bottom:1px solid var(--border);">'
          + '<td style="padding:8px 0;">' + escapeHtml(row.label) + '</td>'
          + '<td style="padding:8px 4px; font-weight:600; color:var(--blue);">' + row.aiValue + '</td>'
          + '<td style="padding:8px 4px;">'
          + '<input type="number" step="0.01" value="' + guardVal + '" '
          + 'onchange="saveGuardrail(\'' + row.guardKey + '\', this.value)" '
          + 'style="width:70px; padding:4px; border-radius:4px; background:var(--panel-2); color:var(--text); border:1px solid var(--border);">'
          + '</td>'
          + '<td style="padding:8px 4px; font-size:11px; color:var(--muted);">' + escapeHtml(row.desc) + '</td>'
          + '</tr>';
      }).join('');
      document.getElementById('buy-condition-tbody').innerHTML = html;
    } catch(e) {
      document.getElementById('buy-condition-tbody').innerHTML =
        '<tr><td colspan="4" class="muted">로드 실패: ' + escapeHtml(e.message) + '</td></tr>';
    }
  }

  async function saveGuardrail(key, value) {
    try {
      await fetchJson('/api/v1/settings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({key: key, value: parseFloat(value), value_type: 'number'})
      });
    } catch(e) {
      alert('저장 실패: ' + e.message);
    }
  }

  /* ── Positions & Exit: Monitoring & Orders ── */
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
  async function loadDataHealth() {
    try {
      var r = await fetchJson("/api/v1/bot/data-health");
      var m = (r.payload && r.payload.metrics) ? r.payload.metrics : {};

      function applyMetricCard(idVal, idDetail, key) {
        var s = m[key] || {};
        var el = document.getElementById(idVal);
        var eld = document.getElementById(idDetail);
        var status = s.status || "info";
        if (el) {
          el.textContent = status === "ok" ? "정상" : status === "warn" ? "주의" : "미구현";
          el.className = "metric " + (status === "ok" ? "good" : status === "warn" ? "warn" : "info");
        }
        if (eld) {
          eld.textContent = s.detail || "-";
        }
      }

      applyMetricCard("dh-kisRest", "dh-kisRestDetail", "kis_rest");
      applyMetricCard("dh-kisWs", "dh-kisWsDetail", "kis_ws");
      applyMetricCard("dh-llm", "dh-llmDetail", "llm_router");
      applyMetricCard("dh-db", "dh-dbDetail", "db");
      var skipMetric = m.schedule_skip || {};
      var skipStatus = document.getElementById("scheduleSkipStatus");
      var skipDetail = document.getElementById("scheduleSkipDetail");
      if (skipStatus) {
        var skipWarn = skipMetric.status === "warn";
        skipStatus.textContent = skipWarn ? "스킵 가능" : "정상";
        skipStatus.className = "status " + (skipWarn ? "warn" : "ok");
      }
      if (skipDetail) skipDetail.textContent = skipMetric.detail || "schedule_skip_today=false";
    } catch(e) {
      console.warn("loadDataHealth error", e);
    }

    try {
      var r2 = await fetchJson("/api/v1/market-tone/providers");
      var providers = (r2.payload && r2.payload.providers) ? r2.payload.providers : (Array.isArray(r2.payload) ? r2.payload : []);
      var tbody = document.getElementById("llmProvidersTableBody");
      if (tbody) {
        if (providers.length === 0) {
          tbody.innerHTML = "<tr><td colspan='4' class='muted'>Provider 없음</td></tr>";
        } else {
          tbody.innerHTML = providers.map(function(p) {
            var statusCls = p.enabled ? "ok" : "warn";
            var statusTxt = p.enabled ? "활성" : "비활성";
            return '<tr>'
              + '<td>' + escapeHtml(p.name || "-") + '</td>'
              + '<td>' + escapeHtml(p.role || "-") + '</td>'
              + '<td>' + escapeHtml(p.model || "-") + '</td>'
              + '<td><span class="status ' + statusCls + '">' + statusTxt + '</span></td>'
              + '</tr>';
          }).join("");
        }
      }
    } catch (e) {
      console.warn("loadDataHealth providers error", e);
      var tbody2 = document.getElementById("llmProvidersTableBody");
      if (tbody2) tbody2.innerHTML = '<tr><td colspan="4" class="muted">불러오기 실패: ' + escapeHtml(e.message) + '</td></tr>';
    }

    var telegramEl = document.getElementById('telegram-status');
    if (telegramEl) {
      telegramEl.textContent = '활성';
      telegramEl.className = 'status ok';
    }
  }

  /* ── Funnel Monitor ── */
  async function loadFunnelMemoryCounts() {
    const scopes = [
      { id: 'funnel-mem-s3', path: '/api/v1/pipeline/S3/context-preview' },
      { id: 'funnel-mem-s4', path: '/api/v1/pipeline/S4/context-preview' },
      { id: 'funnel-mem-s5', path: '/api/v1/pipeline/S5/context-preview' },
    ];
    for (const { id, path } of scopes) {
      try {
        const res = await fetch(path);
        if (res.ok) {
          const data = await res.json();
          const el = document.getElementById(id);
          if (el) el.textContent = (data.payload && data.payload.count) != null ? data.payload.count : 0;
        }
      } catch (_) {}
    }
  }

  /* Return the canonical stock code used by Funnel candidate and assignment payloads. */
  function funnelSymbolKey(item) {
    return item ? (item.symbol || item.ticker || item.code || '') : '';
  }

  /* Update Layer 1 rejection details without inventing unavailable breakdowns. */
  function renderFunnelLayer1Breakdown(summary) {
    var tbody = document.getElementById('funnel-layer1-reasons-tbody');
    if (!tbody) return;
    var breakdown = summary.layer1_rejection_breakdown || [];
    if (Array.isArray(breakdown) && breakdown.length > 0) {
      tbody.innerHTML = breakdown.map(function(row) {
        return '<tr>'
          + '<td>' + escapeHtml(row.condition || '-') + '</td>'
          + '<td>' + escapeHtml(String(row.count != null ? row.count : '-')) + '</td>'
          + '<td>' + escapeHtml(row.ratio || '-') + '</td>'
          + '<td><span class="status info">' + escapeHtml(row.status || '집계') + '</span></td>'
          + '</tr>';
      }).join('');
      return;
    }
    var rejected = summary.layer1_rejected != null ? summary.layer1_rejected.toLocaleString() : '-';
    tbody.innerHTML = '<tr>'
      + '<td>탈락 사유 상세 집계 없음</td>'
      + '<td>' + rejected + '</td>'
      + '<td>-</td>'
      + '<td><span class="status info">S3 breakdown 미수집</span></td>'
      + '</tr>';
  }

  /* Render Funnel quality from known persisted state only. */
  function renderFunnelQuality(summary) {
    var strengthStatus = document.getElementById('funnel-quality-strength-status');
    var strengthDetail = document.getElementById('funnel-quality-strength-detail');
    var anomalyStatus = document.getElementById('funnel-quality-anomaly-status');
    var anomalyDetail = document.getElementById('funnel-quality-anomaly-detail');
    if (summary.has_s3 && summary.layer1_count === 0) {
      if (strengthStatus) strengthStatus.textContent = '후보 없음';
      if (strengthDetail) strengthDetail.textContent = '후보 없음: S3 통과 0';
      if (anomalyStatus) anomalyStatus.textContent = '후속 미생성';
      if (anomalyDetail) anomalyDetail.textContent = summary.empty_reason || 'S3 통과 종목이 없어 S4/S5가 생성되지 않았습니다.';
      return;
    }
    if (strengthStatus) strengthStatus.textContent = summary.has_s3 ? 'DB 기준 표시' : 'S3 없음';
    if (strengthDetail) strengthDetail.textContent = '최근 N거래일 품질 집계 미구현: 오늘 저장된 Funnel 결과만 표시합니다.';
    if (anomalyStatus) anomalyStatus.textContent = summary.empty_reason ? '확인 필요' : '저장 결과 기준';
    if (anomalyDetail) anomalyDetail.textContent = summary.empty_reason || '정적 품질 문구를 제거하고 DB 결과만 표시 중입니다.';
  }

  async function loadFunnelData() {
    loadFunnelMemoryCounts();
    // Load Daily Plan profile assignments
    var assignments = [];
    try {
      var rp = await fetch('/api/v1/daily-plan/today');
      var dp = await rp.json();
      assignments = dp.payload && dp.payload.symbol_assignments ? dp.payload.symbol_assignments : [];
      var counts = {LOW_VOL:0, MID_VOL:0, HIGH_VOL:0, THEME_SPIKE:0};
      assignments.forEach(function(a) { if (counts[a.profile] !== undefined) counts[a.profile]++; });
      var el;
      el = document.getElementById('fn-low-count'); if (el) el.textContent = counts.LOW_VOL;
      el = document.getElementById('fn-mid-count'); if (el) el.textContent = counts.MID_VOL;
      el = document.getElementById('fn-high-count'); if (el) el.textContent = counts.HIGH_VOL;
      el = document.getElementById('fn-spike-count'); if (el) el.textContent = counts.THEME_SPIKE;
    } catch(e) {}

    try {
      var funnelSummary = await fetchJson("/api/v1/funnel/summary");
      if (funnelSummary.ok && funnelSummary.payload) {
        var fp = funnelSummary.payload;
        var totalEl = document.getElementById("funnel-total");
        var l1El = document.getElementById("funnel-layer1");
        var l2El2 = document.getElementById("funnel-layer2");
        var candEl2 = document.getElementById("funnel-candidates");
        var totalSourceEl = document.getElementById("funnel-total-source");
        var l1DetailEl = document.getElementById("funnel-layer1-detail");
        var l2DetailEl = document.getElementById("funnel-layer2-detail");
        var emptyReasonEl = document.getElementById("funnel-empty-reason");
        var lastUpdatedEl = document.getElementById("funnel-last-updated");
        if (totalEl) totalEl.textContent = fp.total_universe != null ? fp.total_universe.toLocaleString() : "-";
        if (totalSourceEl) totalSourceEl.textContent = fp.total_universe_source || "출처 미확인";
        if (l1El) l1El.textContent = fp.layer1_count != null ? fp.layer1_count.toLocaleString() : "-";
        if (l1DetailEl) l1DetailEl.textContent = "raw " + (fp.layer1_raw != null ? fp.layer1_raw.toLocaleString() : "-") + " / 탈락 " + (fp.layer1_rejected != null ? fp.layer1_rejected.toLocaleString() : "-");
        if (l2El2 && fp.layer2_count != null) l2El2.textContent = fp.layer2_count.toLocaleString();
        if (l2DetailEl) l2DetailEl.textContent = (fp.has_s4 ? "S4 결과 있음" : "S4 결과 없음") + " / " + (fp.has_s5 ? "S5 결과 있음" : "S5 결과 없음");
        if (candEl2 && fp.signals_count != null) candEl2.textContent = fp.signals_count;
        if (emptyReasonEl) {
          emptyReasonEl.textContent = fp.empty_reason || "";
          emptyReasonEl.style.display = fp.empty_reason ? "block" : "none";
        }
        if (lastUpdatedEl) lastUpdatedEl.textContent = fp.last_updated_at ? "마지막 Funnel 결과 시각: " + fp.last_updated_at : "오늘 저장된 Funnel 결과 시각 없음";
        renderFunnelLayer1Breakdown(fp);
        renderFunnelQuality(fp);
        // Risk Profile별 배정 수
        var pc = fp.profile_counts || {};
        var setPC = function(id, key) { var el = document.getElementById(id); if (el) el.textContent = pc[key] || 0; };
        setPC('fn-low-count', 'LOW_VOL');
        setPC('fn-mid-count', 'MID_VOL');
        setPC('fn-high-count', 'HIGH_VOL');
        setPC('fn-spike-count', 'THEME_SPIKE');
      }
    } catch (e) { /* ignore funnel summary fail */ }

    try {
      var screenData = await fetchJson("/api/v1/screening/today");
      var sc = screenData.payload && screenData.payload.screening;
      if (sc) {
        var l2El = document.getElementById("funnel-layer2");
        var candEl = document.getElementById("funnel-candidates");
        if (l2El) l2El.textContent = sc.output_count != null ? sc.output_count : "-";
        if (candEl) candEl.textContent = sc.output_count != null ? sc.output_count : "-";

        var tbody = document.getElementById("funnel-candidates-tbody");
        var candidates = sc.candidates;
        if (tbody && Array.isArray(candidates) && candidates.length > 0) {
          tbody.innerHTML = candidates.map(function(c) {
            var score = c.suitability_score != null ? c.suitability_score.toFixed(2) : "-";
            var conf = c.confidence != null ? c.confidence.toFixed(2) : "-";
            var candidateSymbol = funnelSymbolKey(c);
            var asgn = assignments.find(function(a) { return funnelSymbolKey(a) === candidateSymbol; });
            var profileName = asgn ? asgn.profile : "-";
            var profileReason = asgn ? asgn.reason : "-";
            var memRefs = (c.memory_refs || []).join(', ') || '-';

            return '<tr>'
              + '<td>' + escapeHtml(candidateSymbol) + '</td>'
              + '<td>' + escapeHtml(c.name || "") + '</td>'
              + '<td>' + score + '</td>'
              + '<td>-</td><td>-</td>'
              + '<td>' + score + '</td>'
              + '<td>' + conf + '</td>'
              + '<td><span class="status info">감시중</span></td>'
              + '<td>' + escapeHtml(c.reason || "") + '</td>'
              + '<td>' + escapeHtml(profileName) + '</td>'
              + '<td>' + escapeHtml(profileReason) + '</td>'
              + '<td style="font-size:0.8em;color:var(--accent)">' + escapeHtml(memRefs) + '</td>'
              + '</tr>';
          }).join("");
        } else if (tbody && sc.output_count === 0) {
          tbody.innerHTML = '<tr><td colspan="12" class="muted" style="text-align:center;">오늘 스크리닝 후보 없음</td></tr>';
        }
      }
    } catch (e) {
      var tbody2 = document.getElementById("funnel-candidates-tbody");
      if (tbody2) tbody2.innerHTML = '<tr><td colspan="12" class="muted">불러오기 실패: ' + escapeHtml(e.message) + '</td></tr>';
    }
  }

  /* ── Execution & Risk ── */
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

  /* ── Review & Audit ── */
  async function loadReviewData() {
    try {
      var data = await fetchJson("/api/v1/trades/history?limit=30");
      var items = (data.payload && data.payload.items) || [];

      var tradeDays = items.length;
      var totalOrders = 0;
      var profitDays = 0;
      var pnlSum = 0;
      items.forEach(function(item) {
        totalOrders += item.total_orders || 0;
        pnlSum += item.realized_pnl_pct || 0;
        if ((item.realized_pnl_pct || 0) > 0) profitDays++;
      });
      var winrate = tradeDays > 0 ? Math.round(profitDays / tradeDays * 100) : 0;

      function setRV(id, text, cls) {
        var el = document.getElementById(id);
        if (el) { el.textContent = text; if (cls) el.className = "metric " + cls; }
      }

      setRV("review-trade-days", tradeDays + "일");
      setRV("review-total-orders", totalOrders + "건");
      var pnlCls = pnlSum >= 0 ? "good" : "bad";
      setRV("review-pnl", (pnlSum >= 0 ? "+" : "") + pnlSum.toFixed(2) + "%", pnlCls);
      setRV("review-winrate", winrate + "%", winrate >= 50 ? "good" : "warn");
      var wrDetail = document.getElementById("review-winrate-detail");
      if (wrDetail) wrDetail.textContent = profitDays + "수익일 / " + tradeDays + "거래일";

      if (items.length > 0) {
        var latest = items[0];
        var summEl = document.getElementById("review-latest-summary");
        var toneEl = document.getElementById("review-latest-tone");
        var rpEl = document.getElementById("review-latest-rulepack");
        if (summEl) summEl.textContent = latest.trade_date + " · 주문 " + (latest.total_orders || 0) + "건 · 손익 " + (latest.realized_pnl_pct || 0).toFixed(2) + "%";
        if (toneEl) toneEl.textContent = latest.market_tone || "(없음)";
        if (rpEl) rpEl.textContent = latest.rulepack_id || "(없음)";
      }

      var tbody = document.getElementById("review-history-tbody");
      if (tbody) {
        if (items.length === 0) {
          tbody.innerHTML = '<tr><td colspan="6" class="muted" style="text-align:center;">거래 이력 없음 (S10 실행 전)</td></tr>';
        } else {
          tbody.innerHTML = items.map(function(item) {
            var pnl = item.realized_pnl_pct || 0;
            var pnlStr = (pnl >= 0 ? "+" : "") + pnl.toFixed(2) + "%";
            return '<tr style="cursor:pointer;" onclick="showScreen(\'statistics\')">'
              + '<td>' + (item.trade_date || "") + '</td>'
              + '<td>' + (item.total_orders || 0) + '</td>'
              + '<td>' + (item.buy_orders || 0) + '</td>'
              + '<td>' + (item.sell_orders || 0) + '</td>'
              + '<td class="' + (pnl >= 0 ? "good" : "bad") + '">' + pnlStr + '</td>'
              + '<td>' + escapeHtml(item.market_tone || "-") + '</td>'
              + '</tr>';
          }).join("");
        }
      }
    } catch (e) {
      var tbody3 = document.getElementById("review-history-tbody");
      if (tbody3) tbody3.innerHTML = '<tr><td colspan="6" class="muted">불러오기 실패: ' + escapeHtml(e.message) + '</td></tr>';
    }
  }

  async function runDailySummary() {
    if (!confirm("오늘 거래를 집계하고 DB를 백업할까요? (S10 실행)")) return;
    try {
      await fetchJson("/api/v1/trades/run-summary", { method: "POST" });
      alert("일일 요약 생성 완료. 새로고침합니다.");
      loadReviewData();
    } catch (e) {
      alert("실패: " + e.message);
    }
  }

  // Review & Audit — 데이터 로드
  async function loadReviewAuditData() {
    try {
      const today = new Date().toISOString().slice(0, 10);
      // S10 리뷰 결과
      const reviewRes = await fetch('/api/v1/review-audit/today');
      if (reviewRes.ok) {
        const reviewData = await reviewRes.json();
        const p = reviewData.payload || {};
        if (p.profile_summary) renderProfilePerformance(p.profile_summary);
        if (p.exit_summary) renderExitReason(p.exit_summary);
        if (p.trailing_quality) renderTrailingQuality(p.trailing_quality);
        
        // Update Rule Context if available
        if (p.base_rulepack_ver) document.getElementById('ra-rulepack-ver').textContent = p.base_rulepack_ver;
        if (p.risk_profile_pack_ver) document.getElementById('ra-profile-pack-ver').textContent = p.risk_profile_pack_ver;
        if (p.daily_plan_id) document.getElementById('ra-daily-plan-id').textContent = p.daily_plan_id;
      }
      // S11 메모리 결과
      const memRes = await fetch('/api/v1/learning-memory/today');
      if (memRes.ok) {
        const memData = await memRes.json();
        const memories = memData.payload || [];
        renderLearningMemory(memories);
      }
    } catch (e) {
      console.warn('loadReviewAuditData error', e);
    }
  }

  var _raCurrentReport = null;

  /* Load today's Review & Audit report and keep the date picker aligned with the selected report date. */
  async function loadReviewAuditScreen() {
    var today = new Date();
    var todayStr = today.getFullYear() + '-' + String(today.getMonth() + 1).padStart(2, '0') + '-' + String(today.getDate()).padStart(2, '0');
    var input = document.getElementById('ra-date-input');
    if (input) input.value = todayStr;
    await loadReviewByDate(todayStr);
  }

  /* Fetch a Review & Audit report for a specific YYYY-MM-DD date and route empty/error states to the empty panel. */
  async function loadReviewByDate(dateStr) {
    var emptyEl = document.getElementById('ra-empty');
    var reportEl = document.getElementById('ra-report');
    if (emptyEl) emptyEl.style.display = 'none';
    if (reportEl) reportEl.style.display = 'none';

    console.info('[INFO] ReviewAudit - load start', dateStr || 'today');
    try {
      var url = dateStr ? '/api/v1/review-audit/' + encodeURIComponent(dateStr) : '/api/v1/review-audit/today';
      var res = await fetch(url);
      var data = await res.json();
      var report = data.payload || (data.ok ? data : null);

      if (!res.ok || !report) {
        _raCurrentReport = null;
        if (emptyEl) emptyEl.style.display = '';
        console.warn('[WARN] ReviewAudit - report empty', dateStr || 'today');
        return;
      }

      _raCurrentReport = report;
      // md_content만 있고 DB 보고서 없는 경우: 카드는 숨기고 팝업 직접 오픈 버튼만 표시
      if (!report.trade_date && report.md_content) {
        if (reportEl) {
          reportEl.style.display = '';
          // 요약 카드는 데이터 없음으로 처리
          document.getElementById('ra-report-title') && (document.getElementById('ra-report-title').textContent = dateStr ? new Date(dateStr+'T00:00:00').toLocaleDateString('ko-KR',{month:'long',day:'numeric'}) + ' 시스템 점검 보고서' : '점검 보고서');
          document.getElementById('ra-report-subtitle') && (document.getElementById('ra-report-subtitle').textContent = '수동 작성 MD 파일 — 자세히 보기를 클릭하세요');
        }
      } else {
        renderReviewReport(report);
        if (reportEl) reportEl.style.display = '';
      }
      console.info('[INFO] ReviewAudit - load complete', report.trade_date);
    } catch (e) {
      _raCurrentReport = null;
      if (emptyEl) emptyEl.style.display = '';
      console.error('[ERROR] ReviewAudit - load failed', e.message);
    }
  }

  /* Render the selected Review & Audit payload into summary cards and the two performance tables. */
  function renderReviewReport(r) {
    var setEl = function(id, val) {
      var el = document.getElementById(id);
      if (el) el.textContent = val != null ? val : '-';
    };
    var setHtml = function(id, html) {
      var el = document.getElementById(id);
      if (el) el.innerHTML = html;
    };
    var num = function(value, fallback) {
      var parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : (fallback || 0);
    };
    var countOf = function(row) {
      return num(row.total_orders != null ? row.total_orders : (row.trade_count != null ? row.trade_count : row.count), 0);
    };
    var avgPnlOf = function(row) {
      if (row.avg_pnl_pct != null) return num(row.avg_pnl_pct, 0);
      if (row.avg_pnl != null) return num(row.avg_pnl, 0);
      return null;
    };

    var d = new Date(r.trade_date + 'T00:00:00');
    var title = (d.getMonth() + 1) + '월 ' + d.getDate() + '일 시스템 점검 보고서';
    setEl('ra-report-title', title);
    setEl('ra-report-subtitle', '시장톤: ' + (r.market_tone || '-') + ' | RulePack: ' + (r.rulepack_id || '-'));

    setEl('ra-total-orders', num(r.total_orders, r.total_trades || 0) + '건');
    setEl('ra-orders-detail', '매수' + num(r.buy_orders, 0) + ' / 매도' + num(r.sell_orders, 0) + ' / 실패' + num(r.failed_orders, 0));

    var pnl = r.realized_pnl;
    var pnlEl = document.getElementById('ra-pnl');
    if (pnlEl) {
      pnlEl.textContent = pnl != null ? Number(pnl).toLocaleString() + '원' : '-';
      pnlEl.className = 'metric ' + (pnl > 0 ? 'good' : pnl < 0 ? 'bad' : '');
    }
    var pct = r.realized_pnl_pct;
    setEl('ra-pnl-pct', pct != null ? (pct >= 0 ? '+' : '') + Number(pct).toFixed(2) + '%' : '-');

    var exitSummary = r.exit_summary || {};
    var topExit = Object.entries(exitSummary).sort(function(a, b) {
      return num((b[1] || {}).count, 0) - num((a[1] || {}).count, 0);
    })[0];
    setEl('ra-top-exit', topExit ? topExit[0].replace(/_/g, ' ') + ' (' + num((topExit[1] || {}).count, 0) + '건)' : '-');

    var tq = r.trailing_quality || {};
    setEl('ra-trailing', tq.quality_grade || '-');
    setEl('ra-trailing-detail', tq.early_exit_rate != null ? '조기청산 ' + Number(tq.early_exit_rate * 100).toFixed(0) + '%' : '-');

    var profiles = r.profile_performance || [];
    if (profiles.length) {
      setHtml('ra-profile-tbody', profiles.map(function(p) {
        var total = countOf(p);
        var filled = num(p.filled_orders != null ? p.filled_orders : p.win_count, 0);
        var fillRate = total > 0 ? Math.round(filled / total * 100) : 0;
        var avgPnl = avgPnlOf(p);
        var pnlPct = avgPnl != null ? (avgPnl >= 0 ? '+' : '') + Number(avgPnl).toFixed(2) + '%' : '-';
        var color = (avgPnl || 0) >= 0 ? 'var(--green)' : 'var(--red)';
        return '<tr>'
          + '<td><strong>' + escapeHtml(p.profile || '') + '</strong></td>'
          + '<td>' + total + '건</td>'
          + '<td>' + fillRate + '%</td>'
          + '<td style="color:' + color + ';">' + pnlPct + '</td>'
          + '<td>' + escapeHtml(p.evaluation || '-') + '</td>'
          + '</tr>';
      }).join(''));
    } else {
      setHtml('ra-profile-tbody', '<tr><td colspan="5" class="muted" style="text-align:center;">데이터 없음</td></tr>');
    }

    var exits = r.exit_reason_performance || [];
    if (exits.length) {
      setHtml('ra-exit-tbody', exits.map(function(e) {
        var avgPnl = avgPnlOf(e);
        var pnlPct = avgPnl != null ? (avgPnl >= 0 ? '+' : '') + Number(avgPnl).toFixed(2) + '%' : '-';
        var color = (avgPnl || 0) >= 0 ? 'var(--green)' : 'var(--red)';
        return '<tr>'
          + '<td>' + escapeHtml((e.exit_reason || '').replace(/_/g, ' ')) + '</td>'
          + '<td>' + countOf(e) + '건</td>'
          + '<td style="color:' + color + ';">' + pnlPct + '</td>'
          + '</tr>';
      }).join(''));
    } else {
      setHtml('ra-exit-tbody', '<tr><td colspan="3" class="muted" style="text-align:center;">데이터 없음</td></tr>');
    }
  }

  /* Open the Review & Audit detail modal.
     MD 파일이 있으면 그 내용을 우선 표시하고, 없으면 DB 기반 요약 텍스트를 생성한다. */
  function openReviewDetailModal() {
    if (!_raCurrentReport) return;
    var modal = document.getElementById('ra-detail-modal');
    var content = document.getElementById('ra-detail-content');
    var title = document.getElementById('ra-modal-title');
    if (!modal || !content) return;

    var r = _raCurrentReport;
    var d = new Date((r.trade_date || '') + 'T00:00:00');
    var dateLabel = r.trade_date ? ((d.getMonth() + 1) + '월 ' + d.getDate() + '일') : '-';
    if (title) title.textContent = dateLabel + ' 점검 보고서 전문';

    // MD 파일 내용이 있으면 그대로 표시
    if (r.md_content) {
      content.textContent = r.md_content;
      modal.style.display = '';
      return;
    }

    // DB 기반 요약 텍스트 생성 (MD 없을 때 fallback)
    var lines = [];
    var countOf = function(row) {
      var value = row.total_orders != null ? row.total_orders : (row.trade_count != null ? row.trade_count : row.count);
      var parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : 0;
    };
    var avgPnlOf = function(row) {
      var value = row.avg_pnl_pct != null ? row.avg_pnl_pct : row.avg_pnl;
      var parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : null;
    };
    lines.push('===================================');
    lines.push('  ' + dateLabel + ' 시스템 점검 보고서');
    lines.push('  (DB 자동 생성 — 수동 점검 파일 없음)');
    lines.push('===================================');
    lines.push('');
    lines.push('[기본 정보]');
    lines.push('  거래일     : ' + (r.trade_date || '-'));
    lines.push('  시장 톤    : ' + (r.market_tone || '-'));
    lines.push('  RulePack   : ' + (r.rulepack_id || '-'));
    lines.push('');
    lines.push('[주문 요약]');
    lines.push('  총 주문    : ' + (r.total_orders || 0) + '건');
    lines.push('  매수       : ' + (r.buy_orders || 0) + '건');
    lines.push('  매도       : ' + (r.sell_orders || 0) + '건');
    lines.push('  실패       : ' + (r.failed_orders || 0) + '건');
    lines.push('');
    lines.push('[손익]');
    lines.push('  실현 손익  : ' + (r.realized_pnl != null ? Number(r.realized_pnl).toLocaleString() + '원' : '-'));
    lines.push('  손익률     : ' + (r.realized_pnl_pct != null ? (r.realized_pnl_pct >= 0 ? '+' : '') + Number(r.realized_pnl_pct).toFixed(2) + '%' : '-'));
    lines.push('');
    lines.push('[Risk Profile별 성과]');
    var profiles = r.profile_performance || [];
    if (profiles.length) {
      profiles.forEach(function(p) {
        var avgPnl = avgPnlOf(p);
        lines.push('  ' + (p.profile || '-').padEnd(16) + ' | 주문 ' + countOf(p) + '건 | 평균 손익 ' + (avgPnl != null ? (avgPnl >= 0 ? '+' : '') + avgPnl.toFixed(2) + '%' : '-'));
      });
    } else {
      lines.push('  데이터 없음');
    }
    lines.push('');
    lines.push('[청산 사유별 성과]');
    var exits = r.exit_reason_performance || [];
    if (exits.length) {
      exits.forEach(function(e) {
        var avgPnl = avgPnlOf(e);
        lines.push('  ' + (e.exit_reason || '-').replace(/_/g, ' ').padEnd(20) + ' | ' + countOf(e) + '건 | ' + (avgPnl != null ? (avgPnl >= 0 ? '+' : '') + avgPnl.toFixed(2) + '%' : '-'));
      });
    } else {
      lines.push('  데이터 없음');
    }
    lines.push('');
    lines.push('[트레일링 품질]');
    var tq = r.trailing_quality || {};
    lines.push('  등급       : ' + (tq.quality_grade || '-'));
    lines.push('  조기청산율 : ' + (tq.early_exit_rate != null ? (tq.early_exit_rate * 100).toFixed(0) + '%' : '-'));
    lines.push('');
    lines.push('----------------------------------- 끝');

    content.textContent = lines.join('\n');
    modal.style.display = '';
  }

  /* Close the Review & Audit detail modal without mutating the loaded report. */
  function closeReviewDetailModal() {
    var modal = document.getElementById('ra-detail-modal');
    if (modal) modal.style.display = 'none';
  }

  /* Request Review & Audit generation for the selected date, then reload the Review screen state. */
  async function runReviewAudit() {
    console.info('[INFO] ReviewAudit - generate start');
    try {
      var today = new Date();
      var defaultDate = today.getFullYear() + '-' + String(today.getMonth() + 1).padStart(2, '0') + '-' + String(today.getDate()).padStart(2, '0');
      var input = document.getElementById('ra-date-input');
      var targetDate = input && input.value ? input.value : defaultDate;
      await fetch('/api/v1/review-audit/run', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({date: targetDate})});
      await loadReviewByDate(targetDate);
      console.info('[INFO] ReviewAudit - generate complete', targetDate);
    } catch (e) {
      console.error('[ERROR] ReviewAudit - generate failed', e.message);
      alert('생성 실패: ' + e.message);
    }
  }

  function renderProfilePerformance(summary) {
    const tbody = document.getElementById('ra-profile-tbody');
    if (!tbody) return;
    const entries = Object.entries(summary);
    if (!entries.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="muted">데이터 없음</td></tr>';
      return;
    }
    tbody.innerHTML = entries.map(([profile, data]) => {
      const wr = data.win_count && data.trade_count
        ? ((data.win_count / data.trade_count) * 100).toFixed(0) + '%'
        : '—';
      const pnl = data.avg_pnl != null ? (data.avg_pnl * 100).toFixed(2) + '%' : '—';
      return `<tr><td>${profile}</td><td>${data.trade_count || 0}</td><td>${wr}</td><td>${pnl}</td></tr>`;
    }).join('');
  }

  function renderExitReason(summary) {
    const tbody = document.getElementById('ra-exit-tbody');
    if (!tbody) return;
    const entries = Object.entries(summary);
    if (!entries.length) {
      tbody.innerHTML = '<tr><td colspan="3" class="muted">데이터 없음</td></tr>';
      return;
    }
    tbody.innerHTML = entries.map(([reason, data]) => {
      const pnl = data.avg_pnl != null ? (data.avg_pnl * 100).toFixed(2) + '%' : '—';
      return `<tr><td>${reason}</td><td>${data.count || 0}</td><td>${pnl}</td></tr>`;
    }).join('');
  }

  function renderTrailingQuality(tq) {
    const r = document.getElementById('ra-trailing-recovery');
    const e = document.getElementById('ra-trailing-early');
    const c = document.getElementById('ra-trailing-count');
    if (r) r.textContent = tq.avg_recovery_rate != null ? (tq.avg_recovery_rate * 100).toFixed(1) + '%' : '—';
    if (e) e.textContent = tq.early_exit_rate != null ? (tq.early_exit_rate * 100).toFixed(1) + '%' : '—';
    if (c) c.textContent = tq.total_trailing_exits ?? '—';
  }

  function renderLearningMemory(memories) {
    const total = memories.length;
    const auto = memories.filter(m => m.auto_apply_allowed).length;
    const approval = memories.filter(m => m.requires_approval).length;
    const s3 = memories.filter(m => m.scope === 'S3_UNIVERSE_FILTER').length;
    const s4 = memories.filter(m => m.scope === 'S4_HYBRID_SCREENING').length;
    const s5 = memories.filter(m => m.scope === 'S5_DAILY_PLAN').length;

    const setEl = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    setEl('ra-mem-total', total);
    setEl('ra-mem-auto', auto);
    setEl('ra-mem-approval', approval);
    setEl('ra-mem-s3', `S3: ${s3}건`);
    setEl('ra-mem-s4', `S4: ${s4}건`);
    setEl('ra-mem-s5', `S5: ${s5}건`);

    const list = document.getElementById('ra-mem-list');
    if (!list) return;
    if (!total) { list.innerHTML = '<p class="muted">생성된 메모리 없음</p>'; return; }
    list.innerHTML = memories.map(m => `
      <div class="memory-item" style="border-left:3px solid var(--accent);padding:8px 12px;margin-bottom:8px">
        <div><strong>[${m.scope}]</strong> ${m.summary}</div>
        <div class="muted" style="font-size:0.85em">
          auto: ${m.auto_apply_allowed ? 'Yes' : 'No'} |
          approval: ${m.requires_approval ? 'Yes' : 'No'} |
          status: ${m.status}
        </div>
      </div>
    `).join('');
  }

  async function buildLearningMemory() {
    const btn = document.getElementById('ra-build-memory-btn');
    if (btn) { btn.disabled = true; btn.textContent = '생성 중...'; }
    try {
      const res = await fetch('/api/v1/learning-memory/build', { method: 'POST' });
      const data = await res.json();
      if (res.ok && data.ok) {
        showToast('Learning Memory 생성 완료');
        await loadReviewAuditData();
      } else {
        showToast('생성 실패: ' + (data.detail || data.payload?.reason || 'unknown'), 'error');
      }
    } catch (e) {
      showToast('오류: ' + e.message, 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = 'S11 Learning Memory 생성'; }
    }
  }

  async function runTestS11() {
    const result = document.getElementById('test-s11-result');
    if (result) { result.style.display = 'block'; result.textContent = '실행 중...'; }
    try {
      const res = await fetch('/api/v1/learning-memory/build', { method: 'POST' });
      const data = await res.json();
      if (result) result.textContent = JSON.stringify(data.payload || data, null, 2);
    } catch (e) {
      if (result) result.textContent = '오류: ' + e.message;
    }
  }

  /* ── Statistics ── */
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
    if (tbody) tbody.innerHTML = '<tr><td colspan="7" class="muted" style="text-align:center;">로딩중...</td></tr>';

    try {
      var orders = [];
      if (stFilter === "today") {
        var todayResponse = await fetchJson("/api/v1/orders/today");
        orders = (todayResponse && todayResponse.payload && todayResponse.payload.orders) || [];
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
      }

      if (stFilter === "today") {
        var now = new Date();
        var todayStr = now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0") + "-" + String(now.getDate()).padStart(2, "0");
        orders = orders.filter(function(o) { return (o.trade_date || (o.created_at || "").slice(0, 10) || todayStr) === todayStr; });
      }

      var filterLabel = { today: "오늘", week: "이번주", month: "이번달", lastmonth: "지난달", all: "전체" };
      if (title) title.textContent = (filterLabel[stFilter] || "") + " 주문 내역";

      renderOrdersTable(orders, "해당 기간 주문 없음");
    } catch (e) {
      console.error("[ERROR]", "loadAllOrders", "-", e.message);
      if (tbody) tbody.innerHTML = '<tr><td colspan="7" class="muted" style="text-align:center;">조회 실패: ' + escapeHtml(e.message || "") + '</td></tr>';
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
    if (tbody) tbody.innerHTML = '<tr><td colspan="7" class="muted" style="text-align:center;">로딩중...</td></tr>';
    if (title) title.textContent = tradeDate + " 주문 내역";

    try {
      var data = await fetchJson("/api/v1/trades/history/" + tradeDate);
      var p = data.payload || {};
      var orders = p.orders || [];
      var signals = p.signals || [];
      renderOrdersTable(orders.concat(signals), "해당 날짜 주문 없음");
    } catch (e) {
      console.error("[ERROR]", "loadStatisticsDetail", "-", e.message);
      if (tbody) tbody.innerHTML = '<tr><td colspan="7" class="muted" style="text-align:center;">불러오기 실패: ' + escapeHtml(e.message) + '</td></tr>';
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
      if (el) el.textContent = plan.id || '미생성';
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
  async function loadDailyPlanScreen() {
    try {
      var r = await fetch('/api/v1/daily-plan/today');
      var d = await r.json();
      var plan = d.payload;
      var el;
      if (!plan) {
        el = document.getElementById('dp-market-tone');
        if (el) el.textContent = '미생성';
        el = document.getElementById('dp-plan-status');
        if (el) el.textContent = 'Plan 없음';
        return;
      }

      el = document.getElementById('dp-market-tone');
      if (el) el.textContent = plan.market_tone || '-';
      el = document.getElementById('dp-trading-intensity');
      if (el) el.textContent = '매매 강도: ' + (plan.trading_intensity || '-');
      el = document.getElementById('dp-new-entry');
      if (el) el.textContent = plan.new_entry_allowed ? '허용' : '차단';
      var statusColors = { active:'ok', validated:'info', generated:'info', validation_failed:'err', inactive:'warn', expired:'warn', superseded:'warn', rollbacked:'warn', dry_run:'info', draft:'warn', none:'warn' };
      var statusLabel = { active:'active', validated:'validated', generated:'generated', validation_failed:'검증실패', inactive:'inactive', expired:'만료', superseded:'superseded', rollbacked:'롤백됨', dry_run:'dry_run', draft:'draft', none:'없음' };
      var st = (plan && plan.status) ? plan.status : 'none';
      var planStatusEl = document.getElementById('dp-plan-status');
      if (planStatusEl) planStatusEl.innerHTML = 'Plan 상태: <span class="status ' + (statusColors[st]||'warn') + '">' + (statusLabel[st]||st) + '</span>';
      el = document.getElementById('dp-assignments-count');
      if (el) el.textContent = (plan.symbol_assignments || []).length + '종목';
      el = document.getElementById('dp-excluded-count');
      if (el) el.textContent = '제외: ' + (plan.excluded_symbols || []).length + '종목';
      el = document.getElementById('dp-provider');
      if (el) el.textContent = plan.provider || '-';
      var createdBy = (plan && plan.created_by) ? plan.created_by : 'scheduler';
      var creationMode = (plan && plan.creation_mode) ? plan.creation_mode : 'auto';
      var createdAtEl = document.getElementById('dp-created-at');
      if (createdAtEl) createdAtEl.textContent = '생성: ' + creationMode + ' · ' + createdBy;
      el = document.getElementById('dp-plan-id-badge');
      if (el) el.textContent = plan.id || '';

      var profileColors = {LOW_VOL:'#6cb6ff', MID_VOL:'#3fb950', HIGH_VOL:'#d29922', THEME_SPIKE:'#f85149'};
      var assignments = plan.symbol_assignments || [];
      var tbody = document.getElementById('dp-assignments-tbody');
      if (tbody) {
        tbody.innerHTML = assignments.length ? assignments.map(function(a) {
          var pc = profileColors[a.profile] || '#aaa';
          return '<tr>'
            + '<td>' + escapeHtml(a.code || '') + '</td>'
            + '<td>' + escapeHtml(a.name || '') + '</td>'
            + '<td><span style="color:' + pc + '; font-weight:600;">' + escapeHtml(a.profile || '-') + '</span></td>'
            + '<td style="font-size:11px; color:var(--muted);">' + escapeHtml(a.reason || '') + '</td>'
            + '</tr>';
        }).join('') : '<tr><td colspan="4" class="muted" style="text-align:center;">배정 없음</td></tr>';
      }

      var excluded = plan.excluded_symbols || [];
      var exEl = document.getElementById('dp-excluded-list');
      if (exEl) {
        exEl.innerHTML = excluded.length
          ? excluded.map(function(e) { return '<div>' + escapeHtml(e.name || '') + ' (' + escapeHtml(e.code || '') + ') — ' + escapeHtml(e.reason || '') + '</div>'; }).join('')
          : '<span>없음</span>';
      }

      var summaryEl = document.getElementById('dp-llm-summary');
      if (summaryEl) summaryEl.textContent = plan.llm_summary || '-';

      var validation = plan.validation_result || {};
      var validEl = document.getElementById('dp-validation-list');
      if (validEl) {
        var labelMap = {
          schema_valid: 'JSON Schema 검증',
          profiles_exist: 'Risk Profile 존재 검증',
          symbol_assignments_valid: 'Symbol Assignment 검증',
          global_risk_guard_ok: 'Global Risk Guard 검증',
          take_profit_off: '고정 익절 OFF 검증',
          stop_price_increase_only: '손절선 하향 금지 검증',
          force_exit_on: '장마감 강제청산 ON 검증',
          runtime_interpretable: 'Runtime 해석 가능 검증'
        };
        validEl.innerHTML = Object.keys(labelMap).map(function(k) {
          var label = labelMap[k];
          var v = validation[k] || '미검증';
          var pass = v === 'pass';
          return '<div style="display:flex; justify-content:space-between; padding:4px 0; border-bottom:1px solid var(--line); font-size:12px;">'
            + '<span>' + label + '</span>'
            + '<span style="color:' + (pass ? '#3fb950' : '#f85149') + '; font-weight:600;">' + (pass ? '✓ PASS' : '✗ ' + escapeHtml(v)) + '</span>'
            + '</div>';
        }).join('');
      }

      var jsonEl = document.getElementById('dp-raw-json');
      if (jsonEl) jsonEl.textContent = JSON.stringify(plan, null, 2);
    } catch(e) {
      console.error('loadDailyPlanScreen error:', e);
    }

    try {
      var rp = await fetch('/api/v1/rule/profiles');
      var dp = await rp.json();
      var pack = dp.payload || {};
      var pidEl = document.getElementById('dp-profile-pack-id');
      if (pidEl) pidEl.textContent = pack.id || '';
      var profiles = pack.profiles || {};
      var profTbody = document.getElementById('dp-profiles-tbody');
      if (profTbody) {
        var profileOrder = ['LOW_VOL', 'MID_VOL', 'HIGH_VOL', 'THEME_SPIKE'];
        var profileColors2 = {LOW_VOL:'#6cb6ff', MID_VOL:'#3fb950', HIGH_VOL:'#d29922', THEME_SPIKE:'#f85149'};
        profTbody.innerHTML = profileOrder.map(function(name) {
          var p = profiles[name] || {};
          var pc = profileColors2[name] || '#aaa';
          return '<tr>'
            + '<td><span style="color:' + pc + '; font-weight:600;">' + name + '</span></td>'
            + '<td>' + ((p.initial_stop_loss || 0) * 100).toFixed(1) + '%</td>'
            + '<td>+' + ((p.trailing_activate_profit || 0) * 100).toFixed(1) + '%</td>'
            + '<td>' + ((p.trailing_stop_rate || 0) * 100).toFixed(1) + '%</td>'
            + '<td>' + ((p.max_position_rate || 0) * 100).toFixed(0) + '%</td>'
            + '<td>' + (p.max_holding_minutes || '-') + '분</td>'
            + '<td>' + (p.reentry_allowed === false ? '불가' : '허용') + '</td>'
            + '</tr>';
        }).join('');
      }
    } catch(e) {}
  }

  async function generateDailyPlan() {
    var btn = event.target;
    btn.disabled = true;
    btn.textContent = '생성 중...';
    try {
      var r = await fetch('/api/v1/daily-plan/generate', {method:'POST'});
      var d = await r.json();
      if (d.ok) {
        await loadDailyPlanScreen();
        btn.textContent = '생성 완료';
      } else {
        btn.textContent = '실패';
      }
    } catch(e) {
      btn.textContent = '오류';
    }
    setTimeout(function() { btn.disabled = false; btn.textContent = 'Daily Plan 생성'; }, 2000);
  }

  function toggleDpAdvanced(btn) {
    var menu = document.getElementById('dp-advanced-menu');
    if (!menu) return;
    menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
  }
  document.addEventListener('click', function(e) {
    var menu = document.getElementById('dp-advanced-menu');
    if (menu && !e.target.closest('[onclick^="toggleDpAdvanced"]') && !e.target.closest('#dp-advanced-menu')) {
      menu.style.display = 'none';
    }
  });
  function showDpContext() { alert('Context 보기 기능은 Phase 2에서 구현됩니다.'); }
  function runDailyPlanDryRun() { alert('Dry Run 기능은 Phase 2에서 구현됩니다.'); }
  function manualRerunS5() { alert('S5 수동 재실행 기능은 Phase 2에서 구현됩니다.'); }
  function revalidateDailyPlan() { alert('Daily Plan 재검증 기능은 Phase 2에서 구현됩니다.'); }
  function deactivateDailyPlan() { alert('Daily Plan 비활성화 기능은 Phase 2에서 구현됩니다.'); }
  function rollbackDailyPlan() { alert('이전 Plan으로 롤백 기능은 Phase 2에서 구현됩니다.'); }

  function toggleDpJson() {
    var el = document.getElementById('dp-raw-json');
    if (!el) return;
    el.style.display = el.style.display === 'none' ? 'block' : 'none';
  }

  /* ── System Status ── */
  async function loadDataAndApi() {
    await loadDataHealth();
    try {
      var rb = await fetch('/api/v1/rule/base');
      var db = await rb.json();
      var el = document.getElementById('da-base-id');
      if (el) el.textContent = db.payload && db.payload.id ? db.payload.id : '-';
    } catch(e) {}
    try {
      var rp = await fetch('/api/v1/rule/profiles');
      var dp = await rp.json();
      var el2 = document.getElementById('da-profile-id');
      if (el2) el2.textContent = dp.payload && dp.payload.id ? dp.payload.id : '-';
    } catch(e) {}
    try {
      var rdp = await fetch('/api/v1/daily-plan/today');
      var ddp = await rdp.json();
      var plan = ddp.payload || {};
      var el3 = document.getElementById('da-plan-id');
      if (el3) el3.textContent = plan.id || '미생성';
      var el4 = document.getElementById('da-assignments-n');
      if (el4) el4.textContent = (plan.symbol_assignments || []).length + '개';
    } catch(e) {}
    try {
      var da = document.getElementById('da-telegram-status');
      var dd = document.getElementById('da-telegram-detail');
      if (da) da.textContent = '활성';
      if (dd) dd.textContent = 'Telegram Bot 연동';
    } catch(e) {}
    await loadDataApiLogs();
  }

  async function loadDataApiLogs() {
    var tbody = document.getElementById('da-api-logs-tbody');
    if (!tbody) return;
    try {
      var today = new Date().toISOString().slice(0,10);
      var r = await fetch('/api/v1/logs/api?date=' + today);
      var d = await r.json();
      var logs = d.payload || d.logs || [];
      var todayLogs = logs.filter(function(l) {
        var ts = l.called_at || l.timestamp || '';
        return ts.startsWith(today);
      });
      if (!todayLogs.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="muted" style="text-align:center;">오늘 로그 없음</td></tr>';
        return;
      }
      tbody.innerHTML = todayLogs.slice(0, 100).map(function(l) {
        var ts = (l.called_at || l.timestamp || '').slice(11, 19);
        var status = l.status_code || l.status || '-';
        var statusColor = status >= 200 && status < 300 ? '#3fb950' : '#f85149';
        return '<tr>'
          + '<td style="font-size:11px;">' + escapeHtml(ts) + '</td>'
          + '<td style="font-size:11px;">' + escapeHtml(l.method || '-') + '</td>'
          + '<td style="font-size:11px; max-width:200px; overflow:hidden; text-overflow:ellipsis;">' + escapeHtml(l.path || l.endpoint || '-') + '</td>'
          + '<td style="color:' + statusColor + '; font-size:11px;">' + escapeHtml(String(status)) + '</td>'
          + '<td style="font-size:11px;">' + escapeHtml(String(l.duration_ms || l.elapsed_ms || '-')) + 'ms</td>'
          + '</tr>';
      }).join('');
    } catch(e) {
      tbody.innerHTML = '<tr><td colspan="5" class="muted" style="text-align:center;">로그 조회 실패</td></tr>';
    }
  }

  /* ── KIS System Test: additional test functions ── */
  async function testRiskProfilePack() {
    try {
      var r = await fetch('/api/v1/rule/profiles');
      var d = await r.json();
      alert('Risk Profile Pack:\n' + JSON.stringify(d.payload && d.payload.profiles ? Object.keys(d.payload.profiles) : 'N/A', null, 2));
    } catch(e) { alert('오류: ' + e.message); }
  }

  async function testDailyPlanValidate() {
    try {
      var r = await fetch('/api/v1/daily-plan/validate', {method:'POST'});
      var d = await r.json();
      alert('Daily Plan 검증:\n' + JSON.stringify(d.payload && d.payload.validation ? d.payload.validation : d, null, 2));
    } catch(e) { alert('오류: ' + e.message); }
  }

  async function testRuleComposition() {
    var code = prompt('종목코드를 입력하세요 (예: 005930)');
    if (!code) return;
    try {
      var r = await fetch('/api/v1/rule/composition/' + code);
      var d = await r.json();
      alert('Rule Composition:\n' + JSON.stringify(d.payload, null, 2));
    } catch(e) { alert('오류: ' + e.message); }
  }

  /* ── Settings: Risk Profile Pack management ── */
  var _settingsProfileData = {};

  async function loadSettingsProfiles() {
    try {
      var r = await fetch('/api/v1/rule/profiles');
      var d = await r.json();
      var pack = d.payload || {};
      var verEl = document.getElementById('settings-profile-ver');
      if (verEl) verEl.textContent = pack.id || '';
      _settingsProfileData = JSON.parse(JSON.stringify(pack.profiles || {}));
      renderSettingsProfilesTable(_settingsProfileData);
    } catch(e) {}
  }

  function renderSettingsProfilesTable(profiles) {
    var profileOrder = ['LOW_VOL', 'MID_VOL', 'HIGH_VOL', 'THEME_SPIKE'];
    var tbody = document.getElementById('settings-profiles-tbody');
    if (!tbody) return;
    tbody.innerHTML = profileOrder.map(function(name) {
      var p = profiles[name] || {};
      var escName = name.replace(/'/g, "\\'");
      return '<tr>'
        + '<td style="font-weight:600;">' + name + '</td>'
        + '<td><input type="number" step="0.1" value="' + ((p.initial_stop_loss||0)*100).toFixed(1) + '"'
        + ' onchange="_settingsProfileData[\'' + escName + '\'].initial_stop_loss=parseFloat(this.value)/100"'
        + ' style="width:70px; text-align:center;"></td>'
        + '<td><input type="number" step="0.1" value="' + ((p.trailing_activate_profit||0)*100).toFixed(1) + '"'
        + ' onchange="_settingsProfileData[\'' + escName + '\'].trailing_activate_profit=parseFloat(this.value)/100"'
        + ' style="width:70px; text-align:center;"></td>'
        + '<td><input type="number" step="0.1" value="' + ((p.trailing_stop_rate||0)*100).toFixed(1) + '"'
        + ' onchange="_settingsProfileData[\'' + escName + '\'].trailing_stop_rate=parseFloat(this.value)/100"'
        + ' style="width:70px; text-align:center;"></td>'
        + '<td><input type="number" step="1" value="' + ((p.max_position_rate||0)*100).toFixed(0) + '"'
        + ' onchange="_settingsProfileData[\'' + escName + '\'].max_position_rate=parseFloat(this.value)/100"'
        + ' style="width:60px; text-align:center;"></td>'
        + '<td><input type="number" step="10" value="' + (p.max_holding_minutes||180) + '"'
        + ' onchange="_settingsProfileData[\'' + escName + '\'].max_holding_minutes=parseInt(this.value)"'
        + ' style="width:60px; text-align:center;"></td>'
        + '<td><select onchange="_settingsProfileData[\'' + escName + '\'].reentry_allowed=this.value===\'true\'" style="font-size:11px;">'
        + '<option value="true"' + (p.reentry_allowed!==false?' selected':'') + '>허용</option>'
        + '<option value="false"' + (p.reentry_allowed===false?' selected':'') + '>불가</option>'
        + '</select></td>'
        + '</tr>';
    }).join('');
  }

    async function saveRiskProfilePack() {
    if (!confirm('저장하면 새 Profile Pack 버전이 생성됩니다. 계속하시겠습니까?')) return;
    try {
      var r = await fetch('/api/v1/rule/profiles', {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({profiles: _settingsProfileData})
      });
      var d = await r.json();
      if (d.ok) {
        alert('저장 완료: ' + d.payload.id);
        await loadSettingsProfiles();
      } else {
        alert('저장 실패: ' + JSON.stringify(d));
      }
    } catch(e) {
      alert('저장 오류: ' + e.message);
    }
  }

  /* ── Expert Knowledge ── */
  var _ekCurrentAnalysisId = null;

  /* Upload a selected PDF and render the LLM strategy analysis result. */
  async function ekUploadPdf() {
    var input = document.getElementById('ek-pdf-input');
    var statusEl = document.getElementById('ek-upload-status');
    var resultCard = document.getElementById('ek-result-card');
    var uploadBtn = document.getElementById('ek-upload-btn');
    if (!input.files || !input.files[0]) {
      statusEl.textContent = 'PDF 파일을 선택해주세요.';
      return;
    }
    var file = input.files[0];
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      statusEl.textContent = 'PDF 파일만 업로드 가능합니다.';
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      statusEl.textContent = 'PDF 파일 크기는 10MB를 초과할 수 없습니다.';
      return;
    }
    statusEl.textContent = '업로드 중... (LLM 분석에 30~60초 소요될 수 있습니다)';
    resultCard.style.display = 'none';
    _ekCurrentAnalysisId = null;
    if (uploadBtn) uploadBtn.disabled = true;

    try {
      var formData = new FormData();
      formData.append('file', file);
      var res = await fetch('/api/v1/expert-knowledge/upload-pdf', {
        method: 'POST',
        body: formData
      });
      var data = await res.json();
      if (!data.ok) {
        statusEl.textContent = '분석 실패: ' + (data.error || data.detail || '알 수 없는 오류');
        return;
      }
      _ekCurrentAnalysisId = data.payload.analysis_id;
      statusEl.textContent = data.payload.error
        ? '분석 저장 완료. LLM 설정 확인 필요: ' + data.payload.error
        : '분석 완료. 아래 결과를 확인하세요.';
      ekRenderResult(data.payload);
      ekLoadHistory();
    } catch(e) {
      console.error('[ERROR]', 'ekUploadPdf', '-', e.message);
      statusEl.textContent = '오류: ' + e.message;
    } finally {
      if (uploadBtn) uploadBtn.disabled = false;
    }
  }

  /* Render the current PDF analysis candidates, unmappable items, and summary. */
  function ekRenderResult(payload) {
    var resultCard = document.getElementById('ek-result-card');
    var summaryEl = document.getElementById('ek-summary');
    var tbody = document.getElementById('ek-candidates-tbody');
    var unmappableEl = document.getElementById('ek-unmappable');
    var unmappableList = document.getElementById('ek-unmappable-list');
    var applyResult = document.getElementById('ek-apply-result');

    resultCard.style.display = '';
    summaryEl.textContent = payload.summary || '';
    applyResult.style.color = '';
    applyResult.textContent = '';

    var candidates = payload.candidates || [];
    tbody.innerHTML = candidates.length === 0
      ? '<tr><td colspan="5" class="muted" style="padding:12px; text-align:center;">추출된 전략 항목 없음</td></tr>'
      : candidates.map(function(c, i) {
          return '<tr style="border-bottom:1px solid var(--border);">'
            + '<td style="padding:6px 8px; text-align:center;"><input type="checkbox" id="ek-chk-' + i + '" data-key="' + escapeHtml(c.setting_key || '') + '" checked' + (c.setting_key ? '' : ' disabled') + '></td>'
            + '<td style="padding:6px 8px;">' + escapeHtml(c.label || '') + '</td>'
            + '<td style="padding:6px 8px; font-weight:600; color:var(--blue);">' + escapeHtml(String(c.value || '')) + '</td>'
            + '<td style="padding:6px 8px; font-size:11px; color:var(--muted);">' + escapeHtml(c.setting_key || '매핑 불가') + '</td>'
            + '<td style="padding:6px 8px; font-size:11px; color:var(--muted);">' + escapeHtml(c.reason || '') + '</td>'
            + '</tr>';
        }).join('');

    var unmappable = payload.unmappable || [];
    if (unmappable.length > 0) {
      unmappableEl.style.display = '';
      unmappableList.innerHTML = unmappable.map(function(u) {
        return '<div style="margin-bottom:4px;">- <strong>' + escapeHtml(u.label || '') + '</strong>: '
          + escapeHtml(u.description || '') + ' - '
          + '<em>OOO 기능을 Setting 화면에 추가하여야 합니다. 개발 후 재 요청해주세요.</em></div>';
      }).join('');
    } else {
      unmappableEl.style.display = 'none';
    }
  }

  /* Apply checked strategy candidates from the active analysis to Settings. */
  async function ekApplyStrategy() {
    if (!_ekCurrentAnalysisId) return;
    var applyResult = document.getElementById('ek-apply-result');
    var applyBtn = document.getElementById('ek-apply-btn');
    var checkboxes = document.querySelectorAll('#ek-candidates-tbody input[type=checkbox]:checked');
    var approvedKeys = Array.from(checkboxes).map(function(cb) { return cb.getAttribute('data-key'); }).filter(Boolean);
    if (!approvedKeys.length) {
      applyResult.style.color = 'var(--yellow)';
      applyResult.textContent = '적용할 항목을 선택해주세요.';
      return;
    }
    if (applyBtn) applyBtn.disabled = true;
    applyResult.style.color = 'var(--muted)';
    applyResult.textContent = 'Settings 적용 중...';
    try {
      var res = await fetch('/api/v1/expert-knowledge/apply-strategy/' + encodeURIComponent(_ekCurrentAnalysisId), {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({approved_keys: approvedKeys})
      });
      var data = await res.json();
      if (!data.ok) {
        applyResult.style.color = 'var(--yellow)';
        applyResult.textContent = '적용 실패: ' + (data.error || data.detail || '');
        return;
      }
      var msgs = (data.payload.messages || []).join('\n');
      applyResult.style.color = 'var(--green)';
      applyResult.textContent = msgs || '적용 완료';
      ekLoadHistory();
    } catch(e) {
      console.error('[ERROR]', 'ekApplyStrategy', '-', e.message);
      applyResult.style.color = 'var(--yellow)';
      applyResult.textContent = '오류: ' + e.message;
    } finally {
      if (applyBtn) applyBtn.disabled = false;
    }
  }

  /* Reset the PDF upload form and hide the current analysis result. */
  function ekReset() {
    _ekCurrentAnalysisId = null;
    document.getElementById('ek-result-card').style.display = 'none';
    document.getElementById('ek-pdf-input').value = '';
    document.getElementById('ek-upload-status').textContent = '';
  }

  /* Load the latest PDF analysis history for the Expert Knowledge screen. */
  async function ekLoadHistory() {
    var el = document.getElementById('ek-history-list');
    if (!el) return;
    try {
      var res = await fetch('/api/v1/expert-knowledge/analyses');
      var data = await res.json();
      if (!data.ok) {
        el.textContent = '이력 로드 실패: ' + (data.error || data.detail || '알 수 없는 오류');
        return;
      }
      var items = data.payload || [];
      if (!items.length) { el.textContent = '분석 이력 없음'; return; }
      el.innerHTML = items.map(function(item) {
        var ts = item.created_at ? item.created_at.substring(0, 16).replace('T', ' ') : '-';
        var status = item.status === 'applied' ? '<span style="color:var(--green);">적용됨</span>' : '대기';
        return '<div style="padding:6px 0; border-bottom:1px solid var(--border); display:flex; gap:8px; align-items:center;">'
          + '<span style="color:var(--muted); font-size:11px;">' + ts + '</span>'
          + '<span>' + escapeHtml(item.filename || '') + '</span>'
          + '<span>' + status + '</span>'
          + '</div>';
      }).join('');
    } catch(e) {
      console.error('[ERROR]', 'ekLoadHistory', '-', e.message);
      el.textContent = '이력 로드 실패: ' + e.message;
    }
  }

  async function loadExpertKnowledge() {
    try {
      const res = await fetch('/api/v1/expert-knowledge/');
      if (!res.ok) return;
      const data = await res.json();
      const items = data.payload || [];
      renderKnowledgeList(items);
    } catch (e) {
      console.warn('loadExpertKnowledge error', e);
    }
  }

  function renderKnowledgeList(items) {
    const tbody = document.getElementById('ek-list-tbody');
    if (!tbody) return;
    if (!items.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="muted" style="text-align:center;">등록된 지식 없음</td></tr>';
      return;
    }
    tbody.innerHTML = items.map(item => {
      const statusClass = item.status === 'approved' ? 'ok' : item.status === 'rejected' ? 'fail' : 'info';
      const actionBtns = item.status === 'pending'
        ? `<button class="btn small secondary" onclick="approveKnowledge('${item.id}')">승인</button>
           <button class="btn small" onclick="rejectKnowledge('${item.id}')">거부</button>`
        : `<span class="muted">${item.status}</span>`;
      return `<tr>
        <td>${escapeHtml(item.title)}</td>
        <td><span class="tag">${escapeHtml(item.scope)}</span></td>
        <td>${escapeHtml(item.category)}</td>
        <td>${item.priority}</td>
        <td><span class="status ${statusClass}">${item.status}</span></td>
        <td>${(item.created_at || '').slice(0, 10)}</td>
        <td>${actionBtns}</td>
      </tr>`;
    }).join('');
  }

  async function submitKnowledge() {
    const title = document.getElementById('ek-title')?.value?.trim();
    const content = document.getElementById('ek-content')?.value?.trim();
    const scope = document.getElementById('ek-scope')?.value;
    const category = document.getElementById('ek-category')?.value;
    const priority = parseInt(document.getElementById('ek-priority')?.value || '5');

    if (!title || !content) {
      showToast('제목과 내용을 입력하세요', 'error');
      return;
    }

    try {
      const res = await fetch('/api/v1/expert-knowledge/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, content, scope, category, priority, auto_inject: false }),
      });
      const data = await res.json();
      if (res.ok && data.ok) {
        showToast('지식 등록 완료');
        document.getElementById('ek-title').value = '';
        document.getElementById('ek-content').value = '';
        await loadExpertKnowledge();
      } else {
        showToast('등록 실패: ' + (data.detail || 'unknown'), 'error');
      }
    } catch (e) {
      showToast('오류: ' + e.message, 'error');
    }
  }

  async function approveKnowledge(itemId) {
    try {
      const res = await fetch(`/api/v1/expert-knowledge/${itemId}/approve`, { method: 'POST' });
      const data = await res.json();
      if (res.ok && data.ok) {
        showToast('승인 완료');
        await loadExpertKnowledge();
      } else {
        showToast('승인 실패', 'error');
      }
    } catch (e) {
      showToast('오류: ' + e.message, 'error');
    }
  }

  async function rejectKnowledge(itemId) {
    try {
      const res = await fetch(`/api/v1/expert-knowledge/${itemId}/reject`, { method: 'POST' });
      const data = await res.json();
      if (res.ok && data.ok) {
        showToast('거부 완료');
        await loadExpertKnowledge();
      } else {
        showToast('거부 실패', 'error');
      }
    } catch (e) {
      showToast('오류: ' + e.message, 'error');
    }
  }

  // Data Quality Guard 로드
  async function loadDQStatus() {
    try {
      const res = await fetch('/api/v1/data-quality/status');
      if (!res.ok) return;
      const data = await res.json();
      const p = data.payload || {};
      const el = document.getElementById('dq-overall-status');
      if (el) {
        el.textContent = p.overall_status || 'NORMAL';
        el.className = 'status ' + ({
          NORMAL: 'ok', WARNING: 'warn', DEGRADED: 'warn',
          BLOCK_NEW_ENTRY: 'fail', EMERGENCY: 'fail'
        }[p.overall_status] || 'info');
      }
      const detail = document.getElementById('dq-overall-detail');
      if (detail) detail.textContent = p.overall_status === 'NORMAL' ? '데이터 이상 없음' : '이상 감지됨';
      const count = document.getElementById('dq-event-count');
      const events = p.events || [];
      if (count) count.textContent = events.length;
      const breakdown = document.getElementById('dq-event-breakdown');
      if (breakdown) {
        const counts = {};
        events.forEach(e => { counts[e.event_type] = (counts[e.event_type] || 0) + 1; });
        breakdown.textContent = Object.entries(counts).map(([k, v]) => `${k}: ${v}`).join(' | ') || '이벤트 없음';
      }
    } catch (e) { console.warn('loadDQStatus error', e); }
  }

  // Alert Center 로드
  async function loadAlerts() {
    try {
      const [listRes, summaryRes] = await Promise.all([
        fetch('/api/v1/alerts/'),
        fetch('/api/v1/alerts/summary'),
      ]);
      if (summaryRes.ok) {
        const sum = await summaryRes.json();
        const s = sum.payload || {};
        const setEl = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v ?? '-'; };
        setEl('al-total', s.total);
        setEl('al-critical', s.by_severity?.CRITICAL ?? 0);
        setEl('al-warning', s.by_severity?.WARNING ?? 0);
        setEl('al-unacked', s.unacknowledged);
      }
      if (listRes.ok) {
        const list = await listRes.json();
        const items = list.payload || [];
        const tbody = document.getElementById('al-list-tbody');
        if (!tbody) return;
        if (!items.length) {
          tbody.innerHTML = '<tr><td colspan="7" class="muted" style="text-align:center">알림 없음</td></tr>';
          return;
        }
        tbody.innerHTML = items.map(a => {
          const cls = a.severity === 'CRITICAL' ? 'fail' : a.severity === 'WARNING' ? 'warn' : 'info';
          const ackBtn = !a.acknowledged
            ? `<button class="btn small secondary" onclick="ackAlert('${a.id}')">확인</button>`
            : '<span class="muted">확인됨</span>';
          return `<tr>
            <td><span class="status ${cls}">${a.severity}</span></td>
            <td>${a.alert_type}</td>
            <td>${a.title}</td>
            <td class="muted" style="font-size:0.85em">${a.detail || '-'}</td>
            <td>${(a.created_at || '').slice(11, 19)}</td>
            <td>${a.acknowledged ? '확인됨' : '미확인'}</td>
            <td>${ackBtn}</td>
          </tr>`;
        }).join('');
      }
    } catch (e) { console.warn('loadAlerts error', e); }
  }

  async function ackAlert(alertId) {
    try {
      const res = await fetch(`/api/v1/alerts/${alertId}/acknowledge`, { method: 'POST' });
      if (res.ok) { showToast('알림 확인 처리됨'); await loadAlerts(); }
    } catch (e) { showToast('오류: ' + e.message, 'error'); }
  }

  // Approval Queue 로드
  async function loadApprovalQueue() {
    try {
      const res = await fetch('/api/v1/approval/');
      if (!res.ok) return;
      const data = await res.json();
      const items = data.payload || [];
      const tbody = document.getElementById('aq-list-tbody');
      if (!tbody) return;
      if (!items.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="muted" style="text-align:center">승인 요청 없음</td></tr>';
        return;
      }
      tbody.innerHTML = items.map(r => {
        const cls = r.status === 'pending' ? 'warn' : r.status === 'approved' ? 'ok' : 'fail';
        const btns = r.status === 'pending'
          ? `<button class="btn small secondary" onclick="approveRequest('${r.id}')">승인</button>
             <button class="btn small" onclick="rejectRequest('${r.id}')">거부</button>
             <button class="btn small" onclick="deferRequest('${r.id}')">보류</button>`
          : `<span class="muted">${r.status}</span>`;
        return `<tr>
          <td>${r.change_type}</td>
          <td>${r.title}</td>
          <td class="muted" style="font-size:0.85em">${r.description || '-'}</td>
          <td><span class="status ${cls}">${r.status}</span></td>
          <td>${(r.created_at || '').slice(0, 10)}</td>
          <td>${btns}</td>
        </tr>`;
      }).join('');
    } catch (e) { console.warn('loadApprovalQueue error', e); }
  }

  async function approveRequest(id) {
    const res = await fetch(`/api/v1/approval/${id}/approve`, { method: 'POST' });
    if (res.ok) { showToast('승인 완료'); await loadApprovalQueue(); }
  }
  async function rejectRequest(id) {
    const res = await fetch(`/api/v1/approval/${id}/reject`, { method: 'POST' });
    if (res.ok) { showToast('거부 완료'); await loadApprovalQueue(); }
  }
  async function deferRequest(id) {
    const res = await fetch(`/api/v1/approval/${id}/defer`, { method: 'POST' });
    if (res.ok) { showToast('보류 처리됨'); await loadApprovalQueue(); }
  }

  // 미진입 추적 화면의 전체 API 병합 결과와 현재 필터 상태를 보관한다.
  var _missedTrackingAll = [];
  var _missedFilter = 'all';

  /* Normalize API responses that may arrive either as an array or as { payload: [...] }. */
  function getPayloadRows(response) {
    if (Array.isArray(response)) return response;
    if (response && Array.isArray(response.payload)) return response.payload;
    return [];
  }

  /* Refresh merged missed-tracking data from Shadow Trading and Missed Opportunity endpoints. */
  async function loadMissedTracking() {
    var tbody = document.getElementById('missed-tracking-tbody');
    if (tbody) tbody.innerHTML = '<tr><td colspan="9" class="muted" style="text-align:center;">로딩중...</td></tr>';

    try {
      var fetchJson = function(url) {
        return fetch(url).then(function(r) {
          if (!r.ok) throw new Error(url + ' ' + r.status);
          return r.json();
        });
      };
      var results = await Promise.allSettled([
        fetchJson('/api/v1/shadow-trading/today'),
        fetchJson('/api/v1/missed-opportunity/today'),
      ]);
      var shadowRes = results[0].status === 'fulfilled' ? results[0].value : { payload: [] };
      var missedRes = results[1].status === 'fulfilled' ? results[1].value : { payload: [] };
      if (results[0].status === 'rejected') console.warn('[WARN] loadMissedTracking - shadow endpoint failed', results[0].reason.message);
      if (results[1].status === 'rejected') console.warn('[WARN] loadMissedTracking - missed endpoint failed', results[1].reason.message);
      if (results[0].status === 'rejected' && results[1].status === 'rejected') {
        throw new Error('missed tracking endpoints failed');
      }

      // Shadow Trading rows represent S6 candidates that reached monitoring but never emitted a buy signal.
      var shadowRows = getPayloadRows(shadowRes).map(function(r) {
        return {
          symbol: r.symbol || '',
          symbol_name: r.symbol_name || '',
          missed_stage: r.missed_stage || 'S6_NO_SIGNAL',
          missed_reason: r.missed_reason || '신호 조건 미달',
          entry_price: r.entry_price || 0,
          ret_10m: r.max_return_10m,
          ret_30m: r.max_return_30m,
          ret_eod: r.max_return_eod,
          improvement_candidate: 0,
        };
      });

      // Missed Opportunity rows represent S3/S4/S5 candidates filtered before live signal monitoring.
      var missedRows = getPayloadRows(missedRes).map(function(r) {
        return {
          symbol: r.symbol || '',
          symbol_name: r.symbol_name || '',
          missed_stage: r.missed_stage || 'S3_FILTER',
          missed_reason: r.missed_reason || '-',
          entry_price: r.price_at_missed || 0,
          ret_10m: r.max_return_after_10m,
          ret_30m: r.max_return_after_30m,
          ret_eod: r.max_return_until_eod,
          improvement_candidate: r.improvement_candidate || 0,
        };
      });

      _missedTrackingAll = shadowRows.concat(missedRows);

      var filterCount = _missedTrackingAll.filter(function(r) {
        return r.missed_stage.indexOf('S3') !== -1 || r.missed_stage.indexOf('S4') !== -1;
      }).length;
      var planCount = _missedTrackingAll.filter(function(r) { return r.missed_stage.indexOf('S5') !== -1; }).length;
      var signalCount = _missedTrackingAll.filter(function(r) { return r.missed_stage.indexOf('S6') !== -1; }).length;
      var candidateCount = _missedTrackingAll.filter(function(r) { return r.improvement_candidate; }).length;

      var setEl = function(id, val) { var el = document.getElementById(id); if (el) el.textContent = val; };
      setEl('ms-filter-count', filterCount);
      setEl('ms-plan-count', planCount);
      setEl('ms-signal-count', signalCount);
      setEl('ms-candidate-count', candidateCount);

      renderMissedTracking();
    } catch (e) {
      console.error('[ERROR] loadMissedTracking - render failed', e.message);
      if (tbody) tbody.innerHTML = '<tr><td colspan="9" class="muted" style="text-align:center;">로드 실패. 새로고침으로 다시 시도해주세요.</td></tr>';
    }
  }

  /* Update the active missed-tracking filter and redraw the merged table. */
  function filterMissedTracking(filter) {
    _missedFilter = filter;
    renderMissedTracking();
  }

  /* Render the merged missed-tracking table using the current filter state. */
  function renderMissedTracking() {
    var tbody = document.getElementById('missed-tracking-tbody');
    if (!tbody) return;

    var rows = _missedTrackingAll;
    if (_missedFilter === 'filter') {
      rows = rows.filter(function(r) { return r.missed_stage.indexOf('S3') !== -1 || r.missed_stage.indexOf('S4') !== -1; });
    } else if (_missedFilter === 'plan') {
      rows = rows.filter(function(r) { return r.missed_stage.indexOf('S5') !== -1; });
    } else if (_missedFilter === 'signal') {
      rows = rows.filter(function(r) { return r.missed_stage.indexOf('S6') !== -1; });
    } else if (_missedFilter === 'candidate') {
      rows = rows.filter(function(r) { return r.improvement_candidate; });
    }

    ['all', 'filter', 's3s4', 's5', 's6', 'candidate'].forEach(function(key) {
      var button = document.getElementById('ms-filter-' + key);
      if (button) button.classList.toggle('primary', key === _missedFilter || (key === 's3s4' && _missedFilter === 'filter') || (key === 's5' && _missedFilter === 'plan') || (key === 's6' && _missedFilter === 'signal'));
    });

    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="9" class="muted" style="text-align:center;">해당 항목 없음</td></tr>';
      return;
    }

    var stageLabel = {
      'S3_FILTER': 'S3 필터탈락', 'S3_UNIVERSE_FILTER': 'S3 필터탈락',
      'S4_SCREENING': 'S4 스크리닝탈락', 'S4_HYBRID_SCREENING': 'S4 스크리닝탈락',
      'S5_NOT_ASSIGNED': 'S5 미배정',
      'S6_NO_SIGNAL': 'S6 신호미발생',
    };

    var fmtPct = function(v) {
      if (v == null) return '-';
      var n = parseFloat(v);
      if (isNaN(n)) return '-';
      var color = n > 0 ? 'var(--green)' : n < 0 ? 'var(--red)' : 'var(--muted)';
      return '<span style="color:' + color + ';">' + (n >= 0 ? '+' : '') + n.toFixed(2) + '%</span>';
    };

    tbody.innerHTML = rows.map(function(r) {
      var stage = stageLabel[r.missed_stage] || r.missed_stage;
      var priceNum = Number(r.entry_price);
      var price = priceNum ? priceNum.toLocaleString() + '원' : '-';
      var candiBadge = r.improvement_candidate
        ? '<span style="color:var(--warn); font-size:11px;">개선후보</span>'
        : '-';
      return '<tr>'
        + '<td>' + escapeHtml(r.symbol) + '</td>'
        + '<td>' + escapeHtml(r.symbol_name) + '</td>'
        + '<td><span style="font-size:11px; color:var(--muted);">' + escapeHtml(stage) + '</span></td>'
        + '<td style="font-size:11px; color:var(--muted);">' + escapeHtml(r.missed_reason || '-') + '</td>'
        + '<td>' + price + '</td>'
        + '<td>' + fmtPct(r.ret_10m) + '</td>'
        + '<td>' + fmtPct(r.ret_30m) + '</td>'
        + '<td>' + fmtPct(r.ret_eod) + '</td>'
        + '<td>' + candiBadge + '</td>'
        + '</tr>';
    }).join('');
  }

  /* Preserve legacy callers by routing the old Shadow Trading refresh into the unified screen. */
  async function loadShadowTrading() {
    await loadMissedTracking();
  }

  /* Preserve legacy callers by routing the removed Missed Opportunity screen into the unified screen. */
  async function loadMissedOpportunity() {
    await loadMissedTracking();
  }

  // False Positive
  async function loadFalsePositive() {
    try {
      const res = await fetch('/api/v1/false-positive/today');
      if (!res.ok) return;
      const data = await res.json();
      const items = data.payload || [];
      const tbody = document.getElementById('fp-list-tbody');
      if (!tbody) return;
      if (!items.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="muted" style="text-align:center">데이터 없음</td></tr>';
        return;
      }
      tbody.innerHTML = items.map(f => `<tr>
        <td>${f.symbol_name || f.symbol}</td>
        <td>${f.false_positive_type}</td>
        <td>${f.original_score != null ? f.original_score.toFixed(2) : '-'}</td>
        <td>${f.original_confidence != null ? (f.original_confidence*100).toFixed(1)+'%' : '-'}</td>
        <td class="muted" style="font-size:0.85em">${f.entry_reason || '-'}</td>
        <td class="muted" style="font-size:0.85em">${f.loss_reason || '-'}</td>
      </tr>`).join('');
    } catch (e) { console.warn('loadFalsePositive error', e); }
  }

  // Confidence Calibration
  async function loadConfidenceCalibration() {
    try {
      const res = await fetch('/api/v1/confidence-calibration/today');
      if (!res.ok) return;
      const data = await res.json();
      const items = data.payload || [];
      const tbody = document.getElementById('cc-list-tbody');
      if (!tbody) return;
      if (!items.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="muted" style="text-align:center">데이터 없음 (실행 버튼 클릭)</td></tr>';
        return;
      }
      tbody.innerHTML = items.map(c => `<tr>
        <td>${c.bin_label}</td>
        <td>${c.trade_count}</td>
        <td style="color:${(c.actual_win_rate||0)>=(c.expected_win_rate||0)?'#3fb950':'#f85149'}">${c.actual_win_rate != null ? (c.actual_win_rate*100).toFixed(1)+'%' : '-'}</td>
        <td>${c.expected_win_rate != null ? (c.expected_win_rate*100).toFixed(1)+'%' : '-'}</td>
        <td style="color:${(c.avg_pnl||0)>=0?'#3fb950':'#f85149'}">${c.avg_pnl != null ? c.avg_pnl.toFixed(2)+'%' : '-'}</td>
      </tr>`).join('');
    } catch (e) { console.warn('loadConfidenceCalibration error', e); }
  }

  async function runConfidenceCalibration() {
    try {
      const res = await fetch('/api/v1/confidence-calibration/run', { method: 'POST' });
      if (res.ok) { showToast('캘리브레이션 완료'); await loadConfidenceCalibration(); }
      else showToast('실행 실패', 'error');
    } catch (e) { showToast('오류: ' + e.message, 'error'); }
  }

  function showToast(message, type = 'success') {
    alert(message); // Simple alert as fallback if showToast is not defined
  }

  function initSettingsUI() {
    loadBuyConditions();
    loadRiskSettings();
    loadSchedulerSettings();
    loadExitOverrideSettings();
    loadSettingsProfiles();
  }

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
