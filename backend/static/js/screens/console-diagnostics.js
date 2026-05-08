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
