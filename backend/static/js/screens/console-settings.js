  var schedulerKeys = [
    {
      key: "schedule_s2_time",
      label: "S2 프리마켓 시장톤 시간",
      default: "08:30",
      description: "장 개시 전 독립 실행 · 야간데이터 기반 시장톤 분석. 09:01 거래준비 파이프라인이 이 결과를 재사용."
    },
    {
      key: "schedule_trade_prep_time",
      label: "거래준비 프로세스 시작 시간",
      default: "07:45",
      description: "S1 토큰 -> S3 유니버스 -> S4 스크리닝 -> S5 Daily Plan -> S5-V/S5-A. ⚠️ 장 개시 후 랭킹데이터가 필요해 09:01 이전 설정은 09:01로 자동 보정됨(S2는 프리마켓에서 선행)."
    },
    {
      key: "schedule_s6_time",
      label: "S6 Decision Engine 시간",
      default: "09:45",
      description: "기존 S6 자동 활성화 스케줄 유지. ⚠️ 거래준비+5분(최소 09:10)로 자동 보정됨."
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
  ];

  var exitOverrideKeys = [
    { key: "override_stop_loss_rate", label: "손절률 (stop_loss)", placeholder: "-0.015", example: "예: -0.015 = -1.5%" },
    { key: "override_take_profit_rate", label: "익절률 (take_profit) (사용 안 함)", placeholder: "OFF", example: "고정 익절 사용 안 함", disabled: true },
    { key: "override_trailing_activate_rate", label: "트레일링 활성기준", placeholder: "0.02", example: "예: 0.02 = +2% 도달 시 활성화" },
    { key: "override_trailing_stop_rate", label: "트레일링 손절률", placeholder: "0.01", example: "예: 0.01 = 고점 -1% 시 청산" }
  ];

  /* 거래 비용 합계 미리보기 업데이트 */
  function _updateCostSummary() {
    var comm = parseFloat(document.getElementById('cost-commission-rate')?.value || 0);
    var tax  = parseFloat(document.getElementById('cost-transaction-tax')?.value || 0);
    var minNet = parseFloat(document.getElementById('cost-min-net-return')?.value || 0);
    var total = comm * 2 + tax;
    var effective = minNet > 0 ? minNet : total;
    var label = document.getElementById('cost-summary-label');
    if (label) {
      label.textContent = '왕복 비용 합계: ' + total.toFixed(3) + '%'
        + ' (수수료 ' + comm.toFixed(3) + '%×2 + 거래세 ' + tax.toFixed(2) + '%)'
        + ' · S4 필터 기준: ' + (minNet > 0 ? minNet.toFixed(2) + '% (수동)' : effective.toFixed(3) + '% (자동)');
    }
  }

  /* 각 input 아래에 타임스탬프 span 동적 삽입 유틸 */
  function _insertSettingTs(inputId, settingKey, fullMap) {
    var el = document.getElementById(inputId);
    if (!el) return;
    var existing = document.getElementById('ts-' + inputId);
    if (existing) existing.remove();
    var item = fullMap[settingKey];
    if (!item || !item.updated_at) return;
    var span = document.createElement('span');
    span.id = 'ts-' + inputId;
    span.style.cssText = 'display:block; font-size:10px; color:var(--muted); margin-top:2px;';
    span.innerHTML = _fmtSettingTs(item.updated_at, item.updated_by);
    el.parentNode.insertBefore(span, el.nextSibling);
  }

  /* 거래 비용 설정 로드 */
  async function loadTradingCostSettings() {
    try {
      var settingsMap = await loadSettingsMap();
      var comm = document.getElementById('cost-commission-rate');
      var tax  = document.getElementById('cost-transaction-tax');
      var minNet = document.getElementById('cost-min-net-return');
      if (comm) comm.value = settingsMap['trading.commission_rate'] ?? '0.015';
      if (tax)  tax.value  = settingsMap['trading.transaction_tax_rate'] ?? '0.20';
      if (minNet) minNet.value = settingsMap['trading.min_net_return_pct'] ?? '0';
      _updateCostSummary();
      // 실시간 미리보기
      [comm, tax, minNet].forEach(function(el) {
        if (el) el.addEventListener('input', _updateCostSummary);
      });
    } catch (e) {
      console.error('Failed to load trading cost settings', e);
    }
  }

  /* 거래 비용 설정 저장 */
  async function saveTradingCostSettings() {
    var comm   = parseFloat(document.getElementById('cost-commission-rate')?.value);
    var tax    = parseFloat(document.getElementById('cost-transaction-tax')?.value);
    var minNet = parseFloat(document.getElementById('cost-min-net-return')?.value || 0);

    if (!Number.isFinite(comm) || comm < 0 || comm > 1) {
      alert('수수료율은 0~1 사이 숫자로 입력하세요 (예: 0.015).'); return;
    }
    if (!Number.isFinite(tax) || tax < 0 || tax > 1) {
      alert('거래세율은 0~1 사이 숫자로 입력하세요 (예: 0.20).'); return;
    }
    if (!Number.isFinite(minNet) || minNet < 0) {
      alert('최소 순수익률은 0 이상 숫자로 입력하세요.'); return;
    }
    var items = [
      { key: 'trading.commission_rate',    value: comm,   value_type: 'number' },
      { key: 'trading.transaction_tax_rate', value: tax,  value_type: 'number' },
      { key: 'trading.min_net_return_pct', value: minNet, value_type: 'number' },
    ];
    try {
      await Promise.all(items.map(function(item) {
        return fetchJson('/api/v1/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(item),
        });
      }));
      _updateCostSummary();
      showToast('거래 비용 설정이 저장되었습니다.', 'ok');
    } catch (e) {
      showToast('저장 실패: ' + e.message, 'err');
    }
  }

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

      var fm = await loadSettingsMapFull();
      _insertSettingTs('risk-daily-loss', 'risk.daily_loss_limit_percent', fm);
      _insertSettingTs('risk-max-positions', 'risk.max_positions', fm);
      _insertSettingTs('risk-position-size', 'risk.max_position_rate_per_stock', fm);
      _insertSettingTs('risk-mode', 'engine.mode', fm);
      _insertSettingTs('setting-cutoff-time', 'risk.new_entry_cutoff_time', fm);
      _insertSettingTs('setting-force-exit-time', 'risk.force_exit_time', fm);
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
      showToast('리스크 설정이 저장되었습니다.', 'ok');
      loadRiskSettings();
    } catch (e) {
      showToast('저장 실패: ' + e.message, 'err');
    }
  }

  /* Load persisted scheduler times into the Settings table. */
  async function loadSchedulerSettings() {
    try {
      var res = await fetchJson("/api/v1/settings");
      var settings = res.payload.items || [];
      var settingsMap = {};
      var settingsMetaMap = {};
      settings.forEach(function(s) {
        settingsMap[s.key] = s.value;
        settingsMetaMap[s.key] = { updated_at: s.updated_at, updated_by: s.updated_by };
      });

      var html = schedulerKeys.map(function(k) {
        var current = settingsMap[k.key] || k.default;
        var meta = settingsMetaMap[k.key] || {};
        var tsHtml = _fmtSettingTs(meta.updated_at, meta.updated_by) || '<span class="muted">-</span>';
        var inputHtml = k.readOnly
          ? '<span class="muted">' + escapeHtml(current) + '</span>'
          : '<input type="text" id="input-' + k.key + '" value="' + escapeHtml(current)
            + '" data-key="' + escapeHtml(k.key) + '"'
            + ' onblur="saveSchedulerSetting(this.dataset.key)"'
            + ' style="width: 80px; padding: 5px; border-radius: 5px; background: var(--panel-2); color: var(--text); border: 1px solid var(--line);">';
        return ''
          + '<tr>'
          + '  <td>' + k.label + '</td>'
          + '  <td class="muted">' + escapeHtml(k.description || k.key) + '</td>'
          + '  <td>' + escapeHtml(current) + '</td>'
          + '  <td>' + tsHtml + '</td>'
          + '  <td>' + inputHtml + '</td>'
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
      showToast('시간 형식이 올바르지 않습니다 (HH:MM 또는 실시간)', 'err');
      return;
    }
    try {
      await fetchJson("/api/v1/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: key, value: val })
      });
      showToast('저장됨 — 서버 재시작 필요', 'ok');
      loadSchedulerSettings();
    } catch (e) {
      showToast('저장 실패: ' + e.message, 'err');
    }
  }

  /* Load manual exit-rule override values into the Settings table. */
  async function loadExitOverrideSettings() {
    try {
      var res = await fetchJson("/api/v1/settings");
      var settings = res.payload.items || [];
      var settingsMap = {};
      var settingsMetaMap = {};
      settings.forEach(function(s) {
        settingsMap[s.key] = s.value;
        settingsMetaMap[s.key] = { updated_at: s.updated_at, updated_by: s.updated_by };
      });

      var html = exitOverrideKeys.map(function(k) {
        var current = settingsMap[k.key] == null ? "" : String(settingsMap[k.key]);
        var currentLabel = current === "" ? "-" : current;
        var meta = settingsMetaMap[k.key] || {};
        var tsHtml = _fmtSettingTs(meta.updated_at, meta.updated_by) || '<span class="muted">-</span>';
        return ''
          + '<tr>'
          + '  <td>' + k.label + '</td>'
          + '  <td>' + escapeHtml(currentLabel) + '</td>'
          + '  <td><input type="text" id="input-' + k.key + '" value="' + escapeHtml(current)
          + '" placeholder="' + escapeHtml(k.placeholder) + '"'
          + ' data-key="' + escapeHtml(k.key) + '"'
          + ' onblur="saveExitOverrideSetting(this.dataset.key)"'
          + ' style="width: 120px; padding: 5px; border-radius: 5px; background: var(--panel-2); color: var(--text); border: 1px solid var(--line);"></td>'
          + '  <td class="muted">' + k.example + '</td>'
          + '  <td>' + tsHtml + '</td>'
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
      showToast('저장됨', 'ok');
      loadExitOverrideSettings();
    } catch (e) {
      showToast('저장 실패: ' + e.message, 'err');
    }
  }

  async function loadBuyConditions() {
    try {
      var [settingsData, screeningData] = await Promise.all([
        fetchJson('/api/v1/settings').catch(() => null),
        fetchJson('/api/v1/screening/today').catch(() => null)
      ]);

      var settingsMeta = {};
      (settingsData?.payload?.items || []).forEach(function(s) {
        settingsMeta[s.key] = { value: s.value, updated_at: s.updated_at, updated_by: s.updated_by };
      });
      var aiEntryRules = screeningData?.payload?.screening?.entry_rules || screeningData?.payload?.entry_rules || {};
      
      // AI 신뢰도(min_ai_confidence/min_confidence_floor)는 매수 게이트에서 제외됨 (2026-06-01).
      // LLM 점수는 관찰·랭킹·메모리 생성용으로만 유지. 정량 지표만 입력 노출.
      var rows = [
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
        var guardMeta = settingsMeta[row.guardKey] || {};
        var guardVal = guardMeta.value ?? '-';
        var tsHtml = _fmtSettingTs(guardMeta.updated_at, guardMeta.updated_by);
        return '<tr style="border-bottom:1px solid var(--border);">'
          + '<td style="padding:8px 0;">' + escapeHtml(row.label) + '</td>'
          + '<td style="padding:8px 4px; font-weight:600; color:var(--blue);">' + row.aiValue + '</td>'
          + '<td style="padding:8px 4px;">'
          + '<input type="number" step="0.01" value="' + guardVal + '" '
          + 'data-action="saveGuardrail" data-key="' + escapeHtml(row.guardKey) + '" '
          + 'style="width:70px; padding:4px; border-radius:4px; background:var(--panel-2); color:var(--text); border:1px solid var(--border);">'
          + (tsHtml ? '<div style="font-size:10px;margin-top:2px;">' + tsHtml + '</div>' : '')
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

  /* ── 탐색엔진 조건/그룹 편집기 ── */
  var _bcConditions = [];   // [{id,name,ctype,params,enabled}]
  var _bcGroups = [];       // [{id,name,condition_ids,enabled,weight,assigned_to}]
  var _bcAssignTargets = { regimes: [], profiles: [] };

  async function loadConditionEditor() {
    try {
      var [cData, gData, aData] = await Promise.all([
        fetchJson('/api/v1/buy-conditions/conditions'),
        fetchJson('/api/v1/buy-conditions/groups'),
        fetchJson('/api/v1/buy-conditions/assign-targets'),
      ]);
      _bcConditions = (cData.payload && cData.payload.conditions) || [];
      _bcGroups = (gData.payload && gData.payload.groups) || [];
      _bcAssignTargets = (aData.payload) || { regimes: [], profiles: [] };
      renderAtomicConditions();
      renderConditionGroups();
      renderNewGroupCheckboxes();
    } catch (e) {
      var tb = document.getElementById('atomic-condition-tbody');
      if (tb) tb.innerHTML = '<tr><td colspan="4" class="muted">로드 실패: ' + escapeHtml(e.message) + '</td></tr>';
    }
  }

  function renderAtomicConditions() {
    var tb = document.getElementById('atomic-condition-tbody');
    if (!tb) return;
    if (!_bcConditions.length) { tb.innerHTML = '<tr><td colspan="4" class="muted">조건 없음</td></tr>'; return; }
    tb.innerHTML = _bcConditions.map(function(c) {
      var pjson = escapeHtml(JSON.stringify(c.params || {}));
      return '<tr style="border-bottom:1px solid var(--border);">'
        + '<td style="padding:8px 0;">' + escapeHtml(c.name) + '</td>'
        + '<td style="padding:8px 4px; font-size:11px; color:var(--muted);">' + escapeHtml(c.ctype) + '</td>'
        + '<td style="padding:8px 4px;">'
        + '<input type="text" value="' + pjson + '" data-action="saveConditionParams" data-cid="' + escapeHtml(c.id) + '" '
        + 'style="width:200px; padding:4px; border-radius:4px; background:var(--panel-2); color:var(--text); border:1px solid var(--border); font-size:11px;">'
        + '</td>'
        + '<td style="padding:8px 4px;">'
        + '<input type="checkbox" ' + (c.enabled ? 'checked' : '') + ' data-action="toggleCondition" data-cid="' + escapeHtml(c.id) + '">'
        + '</td>'
        + '</tr>';
    }).join('');
  }

  function _assignSelectHtml(group) {
    var opts = ['<option value="">미할당</option>'];
    _bcAssignTargets.regimes.forEach(function(r) {
      var v = 'regime:' + r;
      opts.push('<option value="' + escapeHtml(v) + '"' + (group.assigned_to === v ? ' selected' : '') + '>레짐 · ' + escapeHtml(r) + '</option>');
    });
    _bcAssignTargets.profiles.forEach(function(p) {
      var v = 'profile:' + p;
      opts.push('<option value="' + escapeHtml(v) + '"' + (group.assigned_to === v ? ' selected' : '') + '>프로파일 · ' + escapeHtml(p) + '</option>');
    });
    return '<select data-action="assignGroup" data-gid="' + escapeHtml(group.id) + '" '
      + 'style="padding:4px; border-radius:4px; background:var(--panel-2); color:var(--text); border:1px solid var(--border); font-size:11px;">'
      + opts.join('') + '</select>';
  }

  function renderConditionGroups() {
    var box = document.getElementById('condition-group-list');
    if (!box) return;
    if (!_bcGroups.length) { box.innerHTML = '<div class="muted">그룹 없음</div>'; return; }
    var nameById = {};
    _bcConditions.forEach(function(c) { nameById[c.id] = c.name; });
    box.innerHTML = _bcGroups.map(function(g) {
      var condNames = (g.condition_ids || []).map(function(id) { return escapeHtml(nameById[id] || id); }).join(' AND ');
      return '<div style="border:1px solid var(--line); border-radius:6px; padding:10px;">'
        + '<div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">'
        + '<input type="checkbox" ' + (g.enabled ? 'checked' : '') + ' data-action="toggleGroup" data-gid="' + escapeHtml(g.id) + '">'
        + '<strong style="font-size:13px;">' + escapeHtml(g.name) + '</strong>'
        + '<span style="font-size:10px; color:var(--muted);">가중치</span>'
        + '<input type="number" step="0.1" value="' + (g.weight != null ? g.weight : 1.0) + '" data-action="saveGroupWeight" data-gid="' + escapeHtml(g.id) + '" '
        + 'style="width:60px; padding:3px; border-radius:4px; background:var(--panel-2); color:var(--text); border:1px solid var(--border); font-size:11px;">'
        + _assignSelectHtml(g)
        + '</div>'
        + '<div style="margin-top:6px; font-size:11px; color:var(--muted);">' + (condNames || '(조건 없음)') + '</div>'
        + '</div>';
    }).join('');
  }

  function renderNewGroupCheckboxes() {
    var box = document.getElementById('new-group-conditions');
    if (!box) return;
    box.innerHTML = _bcConditions.map(function(c) {
      return '<label style="font-size:11px; color:var(--muted); display:inline-flex; align-items:center; gap:3px;">'
        + '<input type="checkbox" class="new-group-cond" value="' + escapeHtml(c.id) + '"> ' + escapeHtml(c.name) + '</label>';
    }).join('');
  }

  async function _putCondition(cid, payload) {
    await fetchJson('/api/v1/buy-conditions/conditions/' + encodeURIComponent(cid), {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
  }

  async function saveConditionParams(cid, value) {
    try {
      var parsed = JSON.parse(value);
      await _putCondition(cid, { params: parsed });
    } catch (e) {
      alert('파라미터 저장 실패(JSON 형식 확인): ' + e.message);
    }
  }

  async function toggleCondition(cid, checked) {
    try { await _putCondition(cid, { enabled: !!checked }); }
    catch (e) { alert('조건 토글 실패: ' + e.message); }
  }

  async function _putGroup(gid, payload) {
    await fetchJson('/api/v1/buy-conditions/groups/' + encodeURIComponent(gid), {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
  }

  async function toggleGroup(gid, checked) {
    try { await _putGroup(gid, { enabled: !!checked }); }
    catch (e) { alert('그룹 토글 실패: ' + e.message); }
  }

  async function saveGroupWeight(gid, value) {
    try { await _putGroup(gid, { weight: parseFloat(value) }); }
    catch (e) { alert('가중치 저장 실패: ' + e.message); }
  }

  async function assignGroup(gid, value) {
    try { await _putGroup(gid, { assigned_to: value || '' }); }
    catch (e) { alert('할당 저장 실패: ' + e.message); }
  }

  async function createConditionGroup() {
    var nameEl = document.getElementById('new-group-name');
    var name = nameEl ? nameEl.value.trim() : '';
    if (!name) { alert('그룹명을 입력하세요.'); return; }
    var checked = Array.prototype.slice.call(document.querySelectorAll('.new-group-cond:checked'))
      .map(function(el) { return el.value; });
    if (!checked.length) { alert('조건을 1개 이상 선택하세요(AND).'); return; }
    try {
      await fetchJson('/api/v1/buy-conditions/groups', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name, condition_ids: checked }),
      });
      if (nameEl) nameEl.value = '';
      await loadConditionEditor();
    } catch (e) {
      alert('그룹 생성 실패: ' + e.message);
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
    loadConditionEditor();
    loadRiskSettings();
    loadSchedulerSettings();
    loadExitOverrideSettings();
    loadSettingsProfiles();
    loadTradingCostSettings();
    loadRegimeSets();
    loadIntradaySettings();
  }

  async function loadIntradaySettings() {
    try {
      const fullMap = await loadSettingsMapFull();
      const keys = [
        'intraday_refresh.master_enabled',
        'intraday_refresh.lunch_slots_enabled',
        'intraday_refresh.sector_rotation_enabled',
        'intraday_refresh.replacement_signal_enabled'
      ];
      
      const masterEnabled = !!(fullMap['intraday_refresh.master_enabled']?.value);
      
      keys.forEach(key => {
        const elId = key.replace(/\./g, '-');
        const el = document.getElementById(elId);
        if (el) {
          el.checked = !!(fullMap[key]?.value);
          if (key !== 'intraday_refresh.master_enabled') {
            el.disabled = !masterEnabled;
          }
        }
      });

      const lastUpdatedEl = document.getElementById('intraday-settings-last-updated');
      if (lastUpdatedEl) {
        // 가장 최근 업데이트 시간 찾기
        let latest = null;
        keys.forEach(key => {
          const m = fullMap[key];
          if (m && m.updated_at) {
            if (!latest || m.updated_at > latest.updated_at) latest = m;
          }
        });
        if (latest) {
          lastUpdatedEl.innerHTML = _fmtSettingTs(latest.updated_at, latest.updated_by);
        }
      }
    } catch (e) {
      console.warn('Failed to load intraday settings', e);
    }
  }

  window.toggleIntradaySetting = async function(key, checkbox) {
    const val = checkbox.checked;
    try {
      const res = await fetchJson('/api/v1/settings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          key: key,
          value: val,
          value_type: 'boolean'
        })
      });
      
      if (res.ok) {
        showToast('설정이 저장되었습니다.', 'ok');
        // 마스터 토글일 경우 하위 항목 활성/비활성 처리
        if (key === 'intraday_refresh.master_enabled') {
          const subKeys = [
            'intraday_refresh.lunch_slots_enabled',
            'intraday_refresh.sector_rotation_enabled',
            'intraday_refresh.replacement_signal_enabled'
          ];
          subKeys.forEach(sk => {
            const el = document.getElementById(sk.replace(/\./g, '-'));
            if (el) el.disabled = !val;
          });
        }
        // 업데이트 시간 갱신을 위해 재로드
        await loadIntradaySettings();
      } else {
        showToast('저장 실패: ' + (res.error || '알 수 없는 오류'), 'err');
        checkbox.checked = !val; // 원복
      }
    } catch (e) {
      showToast('오류 발생: ' + e.message, 'err');
      checkbox.checked = !val; // 원복
    }
  };

  async function loadRegimeSets() {
    var container = document.getElementById('regime-sets-list');
    if (!container) return;
    try {
      var r = await fetch('/api/v1/regime/sets?active_only=false');
      var d = await r.json();
      if (!d.ok || !d.items) { container.innerHTML = '<div class="muted">불러오기 실패</div>'; return; }
      
      var REGIME_COLORS = {risk_on:'#3fb950', neutral:'#8b9bb4', risk_off:'#f85149', volatile:'#d29922'};
      var REGIME_LABELS = {risk_on:'Risk On', neutral:'중립', risk_off:'Risk Off', volatile:'변동성'};
      
      container.innerHTML = d.items.map(function(set) {
        var tc = set.trigger_conditions || {};
        var sc = set.settings || {};
        var regimeLabel = tc.regime_label || '-';
        var regimeColor = REGIME_COLORS[regimeLabel] || '#8b9bb4';
        var isPrebuilt = set.is_prebuilt;
        
        return '<div class="regime-set-item" id="rset-' + escapeHtml(set.id) + '" style="border:1px solid var(--border); border-radius:8px; margin-bottom:8px; overflow:hidden;">'
          + '<div style="display:flex; align-items:center; gap:10px; padding:12px 14px; cursor:pointer; background:var(--bg2);" onclick="toggleRegimeSetEdit(\'' + escapeHtml(set.id) + '\')">'
            + '<span style="width:10px; height:10px; border-radius:50%; background:' + regimeColor + '; flex-shrink:0; display:inline-block;"></span>'
            + '<div style="flex:1;">'
              + '<span style="font-weight:600; font-size:13px;">' + escapeHtml(set.name) + '</span>'
              + (isPrebuilt ? ' <span style="font-size:10px; background:#d29922; color:#000; border-radius:3px; padding:1px 5px; margin-left:4px;">예측 SET</span>' : '')
              + '<div style="font-size:11px; color:var(--muted); margin-top:2px;">'
                + escapeHtml(set.description || '')
              + '</div>'
            + '</div>'
            + '<div style="font-size:11px; color:var(--muted); text-align:right; white-space:nowrap;">'
              + '포지션 ' + (sc.max_positions || '-') + '개<br>'
              + '손절 ' + ((sc.stop_loss_rate || 0) * 100).toFixed(1) + '%'
            + '</div>'
            + '<span style="color:var(--muted); font-size:14px; margin-left:8px;">▼</span>'
          + '</div>'
          + '<div id="rset-edit-' + escapeHtml(set.id) + '" style="display:none; padding:14px; border-top:1px solid var(--border);">'
            + '<div class="form-grid" style="grid-template-columns:repeat(auto-fill, minmax(160px, 1fr)); gap:10px; margin-bottom:12px;">'
              + _regimeSetField('최대 포지션', 'rset-max_positions-' + set.id, sc.max_positions, 'number', '1', '20')
              + _regimeSetField('손절선 (%)', 'rset-stop_loss_rate-' + set.id, ((sc.stop_loss_rate || 0) * 100).toFixed(2), 'number', '-20', '0')
              + _regimeSetField('목표 익절 (%)', 'rset-take_profit_rate-' + set.id, ((sc.take_profit_rate || 0) * 100).toFixed(2), 'number', '0', '30', '기록용 — 실제 청산 미적용')
              + _regimeSetField('트레일링 발동 (%)', 'rset-trailing_activate_profit-' + set.id, ((sc.trailing_activate_profit || 0) * 100).toFixed(2), 'number', '0', '30')
              + _regimeSetField('트레일링 폭 (%)', 'rset-trailing_stop_rate-' + set.id, ((sc.trailing_stop_rate || 0) * 100).toFixed(2), 'number', '0', '10')
            + '</div>'
            + '<div style="display:flex; align-items:center; gap:12px; margin-bottom:12px;">'
              + '<label style="font-size:12px; display:flex; align-items:center; gap:6px; cursor:pointer;">'
                + '<input type="checkbox" id="rset-new_entry_allowed-' + set.id + '"' + (sc.new_entry_allowed ? ' checked' : '') + '>'
                + '신규매수 허용'
              + '</label>'
            + '</div>'
            + '<div style="display:flex; gap:8px;">'
              + '<button type="button" class="btn primary" onclick="saveRegimeSet(\'' + escapeHtml(set.id) + '\')">저장</button>'
              + '<button type="button" class="btn" onclick="toggleRegimeSetEdit(\'' + escapeHtml(set.id) + '\')">취소</button>'
            + '</div>'
            + '<div id="rset-save-msg-' + escapeHtml(set.id) + '" style="font-size:12px; margin-top:8px;"></div>'
          + '</div>'
        + '</div>';
      }).join('');
    } catch(e) {
      container.innerHTML = '<div class="muted">오류: ' + escapeHtml(e.message) + '</div>';
    }
  }

  function _regimeSetField(label, id, value, type, min, max, hint) {
    return '<div class="field">'
      + '<label style="font-size:11px;">' + label + '</label>'
      + '<input id="' + id + '" type="' + type + '" value="' + value + '"'
      + (min ? ' min="' + min + '"' : '') + (max ? ' max="' + max + '"' : '')
      + ' style="width:100%;">'
      + (hint ? '<small style="display:block; font-size:10px; color:var(--muted); margin-top:3px;">' + hint + '</small>' : '')
      + '</div>';
  }

  function toggleRegimeSetEdit(setId) {
    var panel = document.getElementById('rset-edit-' + setId);
    if (panel) panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
  }

  async function saveRegimeSet(setId) {
    var msgEl = document.getElementById('rset-save-msg-' + setId);
    if (msgEl) msgEl.textContent = '저장 중...';
    
    var maxPos = document.getElementById('rset-max_positions-' + setId);
    var stopRate = document.getElementById('rset-stop_loss_rate-' + setId);
    var tpRate = document.getElementById('rset-take_profit_rate-' + setId);
    var trailActivate = document.getElementById('rset-trailing_activate_profit-' + setId);
    var trailStop = document.getElementById('rset-trailing_stop_rate-' + setId);
    var newEntry = document.getElementById('rset-new_entry_allowed-' + setId);
    
    var settings = {};
    if (maxPos) settings.max_positions = parseInt(maxPos.value);
    if (stopRate) settings.stop_loss_rate = parseFloat(stopRate.value) / 100;
    if (tpRate) settings.take_profit_rate = parseFloat(tpRate.value) / 100;
    if (trailActivate) settings.trailing_activate_profit = parseFloat(trailActivate.value) / 100;
    if (trailStop) settings.trailing_stop_rate = parseFloat(trailStop.value) / 100;
    if (newEntry) settings.new_entry_allowed = newEntry.checked;
    
    try {
      var r = await fetch('/api/v1/regime/sets/' + encodeURIComponent(setId), {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({settings: settings})
      });
      var d = await r.json();
      if (d.ok) {
        if (msgEl) { msgEl.style.color = 'var(--green)'; msgEl.textContent = '✓ 저장됨'; }
        setTimeout(function() { loadRegimeSets(); }, 1000);
      } else {
        if (msgEl) { msgEl.style.color = 'var(--red)'; msgEl.textContent = '저장 실패'; }
      }
    } catch(e) {
      if (msgEl) { msgEl.style.color = 'var(--red)'; msgEl.textContent = '오류: ' + e.message; }
    }
  }

  /* Bootstrap the console after all classic scripts have loaded. */
