  /* Resolve declarative console action values from data attributes or form controls. */
  function getConsoleActionValue(element) {
    if (element.dataset.valueSource) {
      var source = document.getElementById(element.dataset.valueSource);
      return source ? source.value : '';
    }
    if (typeof element.dataset.value !== 'undefined') return element.dataset.value;
    if (typeof element.value !== 'undefined') return element.value;
    return '';
  }

  /* Dispatch a click action declared in HTML or generated table markup. */
  function dispatchConsoleClickAction(element) {
    var action = element.dataset.action;
    var actionMap = {
      refreshTodayControl: function() { return refreshTodayControl(); },
      showScreen: function() { return showScreen(element.dataset.screen); },
      toggleDecisionEngine: function() { return toggleDecisionEngine(); },
      loadTradingMonitor: function() { return loadTradingMonitor(); },
      loadAccountBalance: function() { return loadAccountBalance(); },
      loadDailyPlanScreen: function() { return loadDailyPlanScreen(); },
      showDpContext: function() { return showDpContext(); },
      toggleDpAdvanced: function() { return toggleDpAdvanced(); },
      runDailyPlanDryRun: function() { return runDailyPlanDryRun(); },
      manualRerunS5: function() { return manualRerunS5(); },
      revalidateDailyPlan: function() { return revalidateDailyPlan(); },
      deactivateDailyPlan: function() { return deactivateDailyPlan(); },
      rollbackDailyPlan: function() { return rollbackDailyPlan(); },
      toggleDpJson: function() { return toggleDpJson(); },
      loadFunnelData: function() { return loadFunnelData(); },
      ekUploadPdf: function() { return ekUploadPdf(); },
      ekApplyStrategy: function() { return ekApplyStrategy(); },
      ekReset: function() { return ekReset(); },
      loadAlerts: function() { return loadAlerts(); },
      loadApprovalQueue: function() { return loadApprovalQueue(); },
      loadMissedTracking: function() { return loadMissedTracking(); },
      filterMissedTracking: function() { return filterMissedTracking(element.dataset.filter); },
      loadFalsePositive: function() { return loadFalsePositive(); },
      runConfidenceCalibration: function() { return runConfidenceCalibration(); },
      loadConfidenceCalibration: function() { return loadConfidenceCalibration(); },
      liveDecisionActivate: function() { return liveDecisionActivate(); },
      liveDecisionDeactivate: function() { return liveDecisionDeactivate(); },
      loadLiveData: function() { return loadLiveData(); },
      loadPositionMonitoring: function() { return loadPositionMonitoring(); },
      liquidateAll: function() { return liquidateAll(); },
      loadExecutionRisk: function() { return loadExecutionRisk(); },
      loadDataAndApi: function() { return loadDataAndApi(); },
      loadDataApiLogs: function() { return loadDataApiLogs(); },
      loadReviewAuditScreen: function() { return loadReviewAuditScreen(); },
      runReviewAudit: function() { return runReviewAudit(); },
      openReviewDetailModal: function() { return openReviewDetailModal(); },
      closeReviewDetailModal: function() { return closeReviewDetailModal(); },
      loadAllOrders: function() { return loadAllOrders(); },
      setStatsFilter: function() { return setStatsFilter(element.dataset.filter); },
      engineTestClearAll: function() { return engineTestClearAll(); },
      engineTestLoadLogs: function() { return engineTestLoadLogs(getConsoleActionValue(element)); },
      engineTestRun: function() { return engineTestRun(element.dataset.step); },
      engineTestClearLog: function() { return engineTestClearLog(); },
      saveRiskSettings: function() { return saveRiskSettings(); },
      saveRiskProfilePack: function() { return saveRiskProfilePack(); },
      ackAlert: function() { return ackAlert(element.dataset.id); },
      approveRequest: function() { return approveRequest(element.dataset.id); },
      rejectRequest: function() { return rejectRequest(element.dataset.id); },
      deferRequest: function() { return deferRequest(element.dataset.id); },
      toggleCandidateDetail: function() { return toggleCandidateDetail(element.dataset.code); },
      approveKnowledge: function() { return approveKnowledge(element.dataset.id); },
      rejectKnowledge: function() { return rejectKnowledge(element.dataset.id); },
      saveSchedulerSetting: function() { return saveSchedulerSetting(element.dataset.key); },
      saveExitOverrideSetting: function() { return saveExitOverrideSetting(element.dataset.key); }
    };
    if (actionMap[action]) return actionMap[action]();
    return undefined;
  }

  /* Dispatch a change action declared in HTML or generated form markup. */
  function dispatchConsoleChangeAction(element) {
    var action = element.dataset.action;
    if (action === 'loadReviewByDate') return loadReviewByDate(element.value);
    if (action === 'loadStatisticsDetail') return loadStatisticsDetail(element.value);
    if (action === 'saveGuardrail') return saveGuardrail(element.dataset.key, element.value);
    if (action === 'updateSettingsProfileField') {
      return updateSettingsProfileField(
        element.dataset.profile,
        element.dataset.field,
        element.value,
        element.dataset.valueType,
        Number(element.dataset.scale || '1')
      );
    }
    return undefined;
  }

  /* Bind delegated handlers for all declarative console actions. */
  function bindConsoleActionEvents() {
    document.addEventListener('click', function(event) {
      var actionEl = event.target.closest('[data-action]');
      if (!actionEl || !document.body.contains(actionEl)) return;
      dispatchConsoleClickAction(actionEl);
    });

    document.addEventListener('change', function(event) {
      var actionEl = event.target.closest('[data-action]');
      if (!actionEl || !document.body.contains(actionEl)) return;
      dispatchConsoleChangeAction(actionEl);
    });
  }
