  async function loadDailyPlanScreen() {
    try {
      var r = await fetch('/api/v1/daily-plan/today');
      var d = await r.json();
      var plan = d.payload;
      var el;
      if (!plan) {
        el = document.getElementById('dp-market-tone');
        if (el) el.textContent = '미수집·대기';
        el = document.getElementById('dp-plan-status');
        if (el) el.textContent = 'Plan 상태: 미수집·대기 - 오늘 Daily Plan 생성 전';
        return;
      }

      el = document.getElementById('dp-market-tone');
      if (el) el.textContent = plan.market_tone || '-';
      el = document.getElementById('dp-trading-intensity');
      if (el) el.textContent = '매매 강도: ' + (plan.trading_intensity || '-');
      el = document.getElementById('dp-new-entry');
      if (el) el.textContent = plan.new_entry_allowed ? '허용' : '차단';
      var statusColors = { active:'ok', validated:'info', generated:'info', validation_failed:'err', inactive:'warn', expired:'warn', superseded:'warn', rollbacked:'warn', dry_run:'info', draft:'warn', none:'warn' };
      var statusLabel = { active:'active', validated:'validated', generated:'generated', validation_failed:'검증실패', inactive:'inactive', expired:'만료', superseded:'superseded', rollbacked:'롤백됨', dry_run:'dry_run', draft:'draft', none:'미수집' };
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

      // ── 오늘의 Regime Set 카드 ──
      try {
        var setResp = await fetch('/api/v1/regime/today');
        var setData = await setResp.json();
        if (setData.ok && setData.application) {
          var app = setData.application;
          var setCard = document.getElementById('dp-regime-set-card');
          if (setCard) {
            var nameEl = document.getElementById('dp-set-name');
            if (nameEl) nameEl.textContent = app.set_name || '-';
            
            var regimeEl = document.getElementById('dp-set-regime');
            if (regimeEl) {
              var regimeLabels = {risk_on:'Risk On', neutral:'중립', risk_off:'Risk Off', volatile:'변동성'};
              var parts = [];
              if (app.regime_label) parts.push(regimeLabels[app.regime_label] || app.regime_label);
              if (app.vix_value != null) parts.push('VIX ' + app.vix_value.toFixed(1));
              if (app.kospi_change_pct != null) {
                var kp = app.kospi_change_pct;
                parts.push('KOSPI ' + (kp >= 0 ? '+' : '') + kp.toFixed(2) + '%');
              }
              regimeEl.textContent = parts.join(' · ');
            }
            
            var reasonEl = document.getElementById('dp-set-reason');
            if (reasonEl) reasonEl.textContent = app.match_reason || '';
            
            var scoreEl = document.getElementById('dp-set-score');
            if (scoreEl) scoreEl.textContent = app.match_score != null
              ? '매칭 점수: ' + (app.match_score * 100).toFixed(0) + '%' : '';
            
            var badge = document.getElementById('dp-set-prebuilt-badge');
            if (badge) badge.style.display = app.is_prebuilt ? 'inline' : 'none';
            
            // 적용된 설정값 표시
            var settingsEl = document.getElementById('dp-set-settings');
            if (settingsEl && app.applied_settings) {
              var s = app.applied_settings;
              var lines = [];
              if (s.max_positions != null) lines.push('최대포지션: ' + s.max_positions + '개');
              if (s.stop_loss_rate != null) lines.push('손절: ' + (s.stop_loss_rate * 100).toFixed(1) + '%');
              if (s.take_profit_rate != null) lines.push('익절: +' + (s.take_profit_rate * 100).toFixed(1) + '%');
              if (s.new_entry_allowed != null) lines.push('신규매수: ' + (s.new_entry_allowed ? '허용' : '차단'));
              settingsEl.textContent = lines.join('\n');
            }

            // 추론 체인 렌더
            var chainEl = document.getElementById('dp-set-chain');
            if (chainEl && app) {
              var regimeColors = {risk_on:'#3fb950', neutral:'#8b9bb4', risk_off:'#f85149', volatile:'#d29922'};
              var regimeLabels = {risk_on:'Risk On', neutral:'중립', risk_off:'Risk Off', volatile:'변동성'};
              var rLabel = regimeLabels[app.regime_label] || app.regime_label || '-';
              var rColor = regimeColors[app.regime_label] || '#8b9bb4';
              
              var steps = [
                {
                  icon: '🌅',
                  title: '아침 브리핑',
                  lines: [
                    app.vix_value != null ? 'VIX ' + app.vix_value.toFixed(1) : null,
                    app.kospi_change_pct != null ? 'KOSPI ' + (app.kospi_change_pct >= 0 ? '+' : '') + app.kospi_change_pct.toFixed(2) + '%' : null
                  ].filter(Boolean)
                },
                {
                  icon: '📊',
                  title: '레짐 판단',
                  lines: ['<span style="color:' + rColor + '; font-weight:700;">' + rLabel + '</span>'],
                  color: rColor
                },
                {
                  icon: '🎯',
                  title: 'SET 선택',
                  lines: [
                    '<span style="font-weight:600;">' + escapeHtml(app.set_name || '-') + '</span>',
                    app.is_prebuilt ? '<span style="font-size:10px; background:#d29922; color:#000; border-radius:3px; padding:1px 5px;">예측 SET</span>' : ''
                  ].filter(Boolean)
                },
                {
                  icon: '⚙️',
                  title: '적용 설정',
                  lines: (function() {
                    var s = app.applied_settings || {};
                    var r = [];
                    if (s.max_positions != null) r.push('포지션 최대 ' + s.max_positions + '개');
                    if (s.stop_loss_rate != null) r.push('손절 ' + (s.stop_loss_rate * 100).toFixed(1) + '%');
                    if (s.take_profit_rate != null) r.push('익절 +' + (s.take_profit_rate * 100).toFixed(1) + '%');
                    return r;
                  })()
                }
              ];
              
              chainEl.innerHTML = steps.map(function(step, i) {
                var arrow = i < steps.length - 1
                  ? '<div style="display:flex; align-items:center; padding:0 4px; color:var(--muted); font-size:16px;">→</div>'
                  : '';
                return '<div style="flex:1; min-width:120px; background:var(--bg2); border-radius:8px; padding:10px 12px; font-size:12px;">'
                  + '<div style="font-size:10px; color:var(--muted); margin-bottom:4px;">' + step.icon + ' ' + step.title + '</div>'
                  + step.lines.map(function(l) { return '<div>' + l + '</div>'; }).join('')
                  + '</div>' + arrow;
              }).join('');

              // 전환 이력이 2개 이상이면 미니 타임라인 표시
              var transitions = setData.transitions || [];
              if (transitions.length > 1) {
                var REGIME_COLORS = {risk_on:'#3fb950', neutral:'#8b9bb4', risk_off:'#f85149', volatile:'#d29922'};
                var miniTimeline = '<div style="margin-top:10px; padding-top:10px; border-top:1px solid var(--line);">'
                  + '<div style="font-size:10px; color:var(--muted); margin-bottom:6px;">오늘 전환 이력 (' + transitions.length + '회)</div>'
                  + '<div style="display:flex; gap:6px; flex-wrap:wrap;">'
                  + transitions.map(function(t) {
                      var rc = REGIME_COLORS[t.regime_label] || '#8b9bb4';
                      var timeStr = (t.applied_at || t.created_at || '').slice(11, 16);
                      var isCurrent = t.current_flag === 1 || t.current_flag === true;
                      return '<div style="font-size:11px; padding:3px 8px; border-radius:12px; '
                        + 'border:1px solid ' + rc + '; color:' + rc + '; '
                        + (isCurrent ? 'background:' + rc + '; color:#fff;' : '') + '">'
                        + timeStr + ' ' + escapeHtml(t.set_name || '-')
                        + '</div>';
                    }).join('<span style="color:var(--muted); font-size:12px; align-self:center;">→</span>')
                  + '</div></div>';
                chainEl.insertAdjacentHTML('beforeend', miniTimeline);
              }
            }
          }
        }
      } catch(e) {
        console.warn('regime set card load failed:', e);
      }
    } catch(e) {
      var toneEl = document.getElementById('dp-market-tone');
      var statusEl = document.getElementById('dp-plan-status');
      if (toneEl) toneEl.textContent = '실행 실패';
      if (statusEl) statusEl.textContent = 'Plan 상태: 실행 실패 - Daily Plan 조회 실패';
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
            + '<td>' + (p.reentry_allowed === false ? '불가' : '허용') + '</td>'
            + '</tr>';
        }).join('');
      }
    } catch(e) {}
  }

  // Daily Plan 수동 생성 버튼 상태를 갱신하며 생성 API를 호출한다.
  async function generateDailyPlan(btn) {
    if (!btn) return;
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

  function toggleDpAdvanced() {
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

  function loadMorningBrief(tradeDate) {
    var card = document.getElementById('morningBriefCard');
    if (!card) return;
    var url = tradeDate ? '/api/v1/morning-context/today?trade_date=' + tradeDate : '/api/v1/morning-context/today';

    fetch(url)
      .then(function(res) { return res.json(); })
      .then(function(json) {
        if (!json.ok || !json.data) {
          card.style.display = 'none';
          return;
        }
        var d = json.data;
        var isToday = json.is_today !== false;
        card.style.display = 'block';

        // 날짜 + 전일 기준 표시
        var dateEl = document.getElementById('mbDate');
        if (dateEl) {
          dateEl.textContent = d.trade_date || '';
          if (!isToday) {
            dateEl.textContent += ' (전일 기준)';
            dateEl.style.color = 'var(--muted)';
          } else {
            dateEl.style.color = '';
          }
        }

        // 레짐 배지
        var regimeEl = document.getElementById('mbRegime');
        if (regimeEl) {
          var regimeLabels = {
            'risk_on': 'Risk On', 'risk_off': 'Risk Off',
            'neutral': 'Neutral', 'volatile': 'Volatile'
          };
          regimeEl.textContent = regimeLabels[d.regime] || d.regime || '-';
          regimeEl.setAttribute('data-val', d.regime || 'neutral');
        }

        // 리스크 배지
        var riskEl = document.getElementById('mbRisk');
        if (riskEl) {
          var riskLabels = {
            'low': 'Low Risk', 'normal': 'Normal',
            'high': 'High Risk', 'extreme': 'Extreme'
          };
          riskEl.textContent = riskLabels[d.risk_level] || d.risk_level || '-';
          riskEl.setAttribute('data-val', d.risk_level || 'normal');
        }

        // 시장 수치 그리드 (SOX, 10Y 국채 추가)
        var grid = document.getElementById('mbMarketGrid');
        if (grid && d.market_data) {
          var marketLabels = {
            'nasdaq': 'NASDAQ', 'sp500': 'S&P500',
            'vix': 'VIX', 'usdkrw': 'USD/KRW',
            'nikkei': '닛케이', 'hangseng': '항셍',
            'kospi': 'KOSPI', 'kospi_night_futures': '코스피 야간선물',
            'oil_wti': 'WTI',
            'sox': 'SOX', 'us_10y_yield': '미국10Y'
          };
          var html = '';
          var keys = ['nasdaq', 'sp500', 'vix', 'usdkrw', 'nikkei', 'hangseng', 'kospi', 'kospi_night_futures', 'oil_wti', 'sox', 'us_10y_yield'];
          keys.forEach(function(k) {
            var item = d.market_data[k];
            if (!item) return;
            var pct = item.change_pct;
            // 색상은 실제 등락 부호 기준: 상승=빨강(up), 하락=파랑(down). (PM 지시 2026-06-03)
            var dir = pct > 0 ? 'up' : (pct < 0 ? 'down' : 'flat');
            var arrow = pct > 0 ? '▲' : (pct < 0 ? '▼' : '━');
            // 현재값(지수 레벨)을 등락률과 함께 표시
            var price = item.price;
            var priceStr = (price != null) ? Number(price).toLocaleString('en-US') : '';
            html += '<div class="mb-market-item">' +
              '<span class="mb-market-label">' + (marketLabels[k] || k) + '</span>' +
              '<span class="mb-market-value ' + dir + '">' +
                (priceStr ? priceStr + ' ' : '') +
                arrow + (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%' +
              '</span>' +
            '</div>';
          });
          grid.innerHTML = html;
        }

        // 분석 텍스트
        var charEl = document.getElementById('mbStockChar');
        if (charEl) charEl.textContent = d.stock_character || '-';

        var hintEl = document.getElementById('mbRulepackHint');
        if (hintEl) hintEl.textContent = d.rulepack_hint || '-';

        var factorsEl = document.getElementById('mbKeyFactors');
        if (factorsEl) {
          var factors = Array.isArray(d.key_factors) ? d.key_factors : [];
          factorsEl.textContent = factors.length ? factors.join(' · ') : '-';
        }
      })
      .catch(function(err) {
        console.warn('morning context load failed', err);
        if (card) card.style.display = 'none';
      });
  }

  async function loadTodayRegimeTimeline(tradeDate) {
    var card = document.getElementById('tc-regime-timeline-card');
    var timelineEl = document.getElementById('tc-regime-timeline');
    var badgeEl = document.getElementById('tc-regime-current-badge');
    if (!card || !timelineEl) return;

    try {
      var regimeUrl = tradeDate ? '/api/v1/regime/today?trade_date=' + tradeDate : '/api/v1/regime/today';
      var r = await fetch(regimeUrl);
      var d = await r.json();
      if (!d.ok) { card.style.display = 'none'; return; }

      var transitions = d.transitions || [];
      var current = d.application;

      if (!current && transitions.length === 0) {
        card.style.display = 'none';
        return;
      }

      card.style.display = 'block';

      // 현재 SET 배지
      if (badgeEl && current) {
        badgeEl.textContent = current.set_name || '-';
      }

      // 타임라인
      var REGIME_COLORS = {risk_on:'#3fb950', neutral:'#8b9bb4', risk_off:'#f85149', volatile:'#d29922'};
      var TRIGGER_LABELS = {morning: '🌅 아침', intraday: '⚡ 장중'};

      if (transitions.length === 0) {
        timelineEl.innerHTML = '<div style="color:var(--muted);">전환 이력 없음 — 아침 SET 유지 중</div>';
      } else {
        timelineEl.innerHTML = transitions.map(function(t, i) {
          var rc = REGIME_COLORS[t.regime_label] || '#8b9bb4';
          var triggerLabel = TRIGGER_LABELS[t.trigger] || t.trigger;
          var timeStr = (t.applied_at || t.created_at || '').slice(11, 16);  // HH:MM
          var isCurrent = t.current_flag === 1 || t.current_flag === true;
          var kp = t.kospi_change_pct;
          var kpStr = kp != null ? ' KOSPI ' + (kp >= 0 ? '+' : '') + kp.toFixed(2) + '%' : '';
          var vixStr = t.vix_value != null ? ' VIX ' + t.vix_value.toFixed(1) : '';

          return '<div style="display:flex; gap:10px; align-items:flex-start; padding:6px 0;'
            + (i < transitions.length - 1 ? ' border-bottom:1px solid var(--line);' : '') + '">'
            + '<div style="width:40px; flex-shrink:0; font-size:11px; color:var(--muted); padding-top:1px;">' + timeStr + '</div>'
            + '<div style="width:8px; height:8px; border-radius:50%; background:' + rc + '; flex-shrink:0; margin-top:4px;"></div>'
            + '<div style="flex:1;">'
              + '<span style="font-weight:' + (isCurrent ? '700' : '400') + '; color:' + (isCurrent ? 'var(--fg)' : 'var(--muted)') + ';">'
                + escapeHtml(t.set_name || t.set_id || '-')
              + '</span>'
              + ' <span style="font-size:10px; color:' + rc + ';">' + escapeHtml(t.regime_label || '') + '</span>'
              + (isCurrent ? ' <span style="font-size:10px; background:var(--accent); color:#fff; border-radius:3px; padding:1px 4px;">현재</span>' : '')
              + '<div style="font-size:11px; color:var(--muted);">'
                + triggerLabel + kpStr + vixStr
              + '</div>'
            + '</div>'
            + '</div>';
        }).join('');
      }
    } catch(e) {
      card.style.display = 'none';
      console.warn('regime timeline load failed:', e);
    }
  }

  /* ── System Status ── */
