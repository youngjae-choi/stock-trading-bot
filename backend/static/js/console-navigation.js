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

    if (name === "dividends") {
      refreshDividends();
    }
    if (name === "dividend-stats") {
      refreshDividendStats();
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

  /* Bind sidebar and mobile menu navigation controls to the shared screen switcher. */
  function bindNavigationEvents() {
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
  }
