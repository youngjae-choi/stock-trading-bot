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
