  /* Switch visible console screen and trigger the screen-specific data refresh. */
  var _todayTimer = null;
  var _screenHistory = [];

  function _pushScreenHistory(screenName) {
    if (_screenHistory[_screenHistory.length - 1] !== screenName) {
      _screenHistory.push(screenName);
    }
  }

  // Today Control 진입 시 거래일 확인 + 기준일 전역 저장
  async function _checkTodayTradingDay() {
    var today = new Date().toLocaleDateString('sv-SE', {timeZone:'Asia/Seoul'});
    window._tcTradeDate = today; // 기본값
    try {
      var r = await fetch('/api/v1/bot/overview');
      var d = await r.json();
      var data = d.payload || {};
      var planDate = data.trade_date || today;
      window._tcTradeDate = planDate; // 실제 거래일(비거래일이면 마지막 거래일)
      var banner = document.getElementById('tc-non-trading-banner');
      if (!banner) return;
      if (planDate !== today) {
        banner.style.display = 'block';
        var dateEl = document.getElementById('tc-non-trading-date');
        if (dateEl) dateEl.textContent = planDate;
      } else {
        banner.style.display = 'none';
      }
    } catch(e) {}
  }

  /* loadConsoleData 래퍼 — 최소 5초 간격 보장 (KIS rate-limit 대응)
   * window._lastConsoleDataTs 를 공유 타임스탬프로 사용 */
  function _safeLoadConsoleData() {
    var now = Date.now();
    if (now - (window._lastConsoleDataTs || 0) < 5000) return;
    window._lastConsoleDataTs = now;
    loadConsoleData();
  }

  function showScreen(name, opts) {
    opts = opts || {};
    if (name === "missed-opportunity") {
      name = "shadow-trading";
    }
    if (name === "data") {
      name = "engine-test";
    }
    sessionStorage.setItem('currentScreen', name);

    if (!opts.skipHistory) {
      _pushScreenHistory(name);
      history.pushState({screen: name}, '', '#' + name);
    }

    if (window._tmRefreshInterval) {
      clearInterval(window._tmRefreshInterval);
      window._tmRefreshInterval = null;
    }
    stopTradingMonitorStream();
    if (_todayTimer) { clearInterval(_todayTimer); _todayTimer = null; }

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

    // 모바일 하단 탭 동기화
    setActiveTab(name);

    if (name === "settings") {
      initSettingsUI();
      loadBuyConditions();
      loadRegimeSets();
    }

    if (name === "engine-test") {
      engineTestLoadTodayResults();
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

    if (name === "plan-funnel") {
      loadPlanFunnel();
    }

    if (name === "funnel") {
      loadFunnelData();
      var td = window._tcTradeDate || null;
      if (typeof loadIntradayReselectionTimeline === "function") loadIntradayReselectionTimeline(td);
      if (typeof loadReplacementSignals === "function") loadReplacementSignals(td);
      if (typeof loadIntradayKillSwitches === "function") loadIntradayKillSwitches();
    }

    if (name === "expert-knowledge") {
      ekLoadHistory();
    }

    if (name === "trading") {
      loadTradingMonitor();
      startTradingMonitorStream();
    }

    if (name === "today") {
      _checkTodayTradingDay().then(function() {
        var td = window._tcTradeDate || null;
        _safeLoadConsoleData();
        loadTodayOrders(5, td);
        loadTodayPlanStatus(td);
        loadMorningBrief(td);
        loadTodayRegimeTimeline(td);
        loadKrIndexLive();
        loadCumulativeReturn();
      });
      _todayTimer = setInterval(function() {
        _safeLoadConsoleData();
        var td = window._tcTradeDate || null;
        loadTodayRegimeTimeline(td);
        loadKrIndexLive();
        loadCumulativeReturn();
      }, 30000);
    }

    if (name === "risk") {
      loadExecutionRisk();
    }

    if (name === "dividends") {
      refreshDividends();
    }
    if (name === "dividend-stats") {
      refreshDividendStats();
    }

    if (name === "daily-results") {
      loadDailyResults();
    }

    if (name === "regime-analytics") {
      loadRegimeAnalyticsScreen();
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

  /* ── Bottom Tab Bar ── */
  var _bottomTabDirectScreens = ['today', 'trading', 'rulepack', 'shadow-trading'];

  function setActiveTab(screenName) {
    var tabBar = document.getElementById('bottomTabBar');
    if (!tabBar) return;
    tabBar.querySelectorAll('.tab-item').forEach(function(btn) {
      btn.classList.remove('active');
      var s = btn.getAttribute('data-screen');
      if (s === screenName) {
        btn.classList.add('active');
      } else if (s === 'more-menu' && _bottomTabDirectScreens.indexOf(screenName) === -1) {
        btn.classList.add('active');
      }
    });
  }

  function toggleMoreDrawer(open) {
    var drawer = document.getElementById('moreDrawer');
    if (drawer) drawer.style.display = open ? 'block' : 'none';
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

    // Bottom Tab Bar 이벤트
    var tabBar = document.getElementById('bottomTabBar');
    if (tabBar) {
      tabBar.querySelectorAll('.tab-item').forEach(function(btn) {
        btn.addEventListener('click', function() {
          var screen = this.getAttribute('data-screen');
          if (screen === 'more-menu') {
            toggleMoreDrawer(true);
            return;
          }
          showScreen(screen);
          toggleMoreDrawer(false);
        });
      });
    }

    // 더보기 드로어
    var drawer = document.getElementById('moreDrawer');
    if (drawer) {
      drawer.querySelectorAll('.more-drawer-item').forEach(function(btn) {
        btn.addEventListener('click', function() {
          showScreen(this.getAttribute('data-screen'));
          toggleMoreDrawer(false);
        });
      });
      var backdrop = document.getElementById('moreDrawerBackdrop');
      if (backdrop) {
        backdrop.addEventListener('click', function() { toggleMoreDrawer(false); });
      }
    }
  }

  // ── 브라우저 뒤로가기 (popstate) ────────────────────────────
  window.addEventListener('popstate', function(e) {
    if (_screenHistory.length > 1) {
      _screenHistory.pop(); // 현재 제거
      var prev = _screenHistory[_screenHistory.length - 1];
      if (prev) {
        showScreen(prev, { skipHistory: true }); // 히스토리 중복 push 방지 플래그
        return;
      }
    }
    // 첫 화면이면 X 동작과 동일 → confirm
    _confirmClose();
  });

  function _confirmClose() {
    if (confirm('KAIROS를 종료하시겠습니까?')) {
      window.close();
      // window.close()가 막힌 환경(대부분)이면 빈 페이지로
      setTimeout(function() { window.location.href = '/logout'; }, 200);
    }
  }

  // beforeunload로 브라우저 탭 닫기 감지
  window.addEventListener('beforeunload', function(e) {
    e.preventDefault();
    e.returnValue = ''; // 크롬 기본 confirm 표시
  });
