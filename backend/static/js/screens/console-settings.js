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
          : '<button class="btn primary" data-action="saveSchedulerSetting" data-key="' + escapeHtml(k.key) + '">저장</button>';
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
          + '  <td><button class="btn primary" data-action="saveExitOverrideSetting" data-key="' + escapeHtml(k.key) + '">저장</button></td>'
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
          label: '주식단타매매 전문 AI 판단값',
          aiValue: aiEntryRules.min_ai_confidence ?? '-',
          guardKey: 'engine.min_confidence_floor',
          desc: '전문 AI가 판단한 오늘의 추천값 / 가드레일은 절대 하한선'
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
          + 'data-action="saveGuardrail" data-key="' + escapeHtml(row.guardKey) + '" '
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
      if (el3) el3.textContent = plan.id || '미수집';
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
      var escName = escapeHtml(name);
      return '<tr>'
        + '<td style="font-weight:600;">' + name + '</td>'
        + '<td><input type="number" step="0.1" value="' + ((p.initial_stop_loss||0)*100).toFixed(1) + '"'
        + ' data-action="updateSettingsProfileField" data-profile="' + escName + '" data-field="initial_stop_loss" data-value-type="number" data-scale="100"'
        + ' style="width:70px; text-align:center;"></td>'
        + '<td><input type="number" step="0.1" value="' + ((p.trailing_activate_profit||0)*100).toFixed(1) + '"'
        + ' data-action="updateSettingsProfileField" data-profile="' + escName + '" data-field="trailing_activate_profit" data-value-type="number" data-scale="100"'
        + ' style="width:70px; text-align:center;"></td>'
        + '<td><input type="number" step="0.1" value="' + ((p.trailing_stop_rate||0)*100).toFixed(1) + '"'
        + ' data-action="updateSettingsProfileField" data-profile="' + escName + '" data-field="trailing_stop_rate" data-value-type="number" data-scale="100"'
        + ' style="width:70px; text-align:center;"></td>'
        + '<td><input type="number" step="1" value="' + ((p.max_position_rate||0)*100).toFixed(0) + '"'
        + ' data-action="updateSettingsProfileField" data-profile="' + escName + '" data-field="max_position_rate" data-value-type="number" data-scale="100"'
        + ' style="width:60px; text-align:center;"></td>'
        + '<td><input type="number" step="10" value="' + (p.max_holding_minutes||180) + '"'
        + ' data-action="updateSettingsProfileField" data-profile="' + escName + '" data-field="max_holding_minutes" data-value-type="integer"'
        + ' style="width:60px; text-align:center;"></td>'
        + '<td><select data-action="updateSettingsProfileField" data-profile="' + escName + '" data-field="reentry_allowed" data-value-type="boolean" style="font-size:11px;">'
        + '<option value="true"' + (p.reentry_allowed!==false?' selected':'') + '>허용</option>'
        + '<option value="false"' + (p.reentry_allowed===false?' selected':'') + '>불가</option>'
        + '</select></td>'
        + '</tr>';
    }).join('');
  }

  /* Update the editable Profile Pack draft from declarative form controls. */
  function updateSettingsProfileField(profileName, fieldName, rawValue, valueType, scale) {
    if (!_settingsProfileData[profileName]) return;
    var value;
    if (valueType === 'boolean') {
      value = rawValue === 'true';
    } else if (valueType === 'integer') {
      value = parseInt(rawValue);
    } else {
      value = parseFloat(rawValue);
      if (scale) value = value / scale;
    }
    _settingsProfileData[profileName][fieldName] = value;
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


  function initSettingsUI() {
    loadBuyConditions();
    loadRiskSettings();
    loadSchedulerSettings();
    loadExitOverrideSettings();
    loadSettingsProfiles();
  }

  /* Bootstrap the console after all classic scripts have loaded. */
