  /* ── Plan & Funnel 통합 화면 (P4) ──
   * 상단: 오늘 Daily Plan 요약 (레짐/톤/강도/프로파일 분포) — daily-plan/regime API 재사용
   * 중단: 장중 선별 타임라인 — GET /api/v1/daily-plan/intraday-events?date=
   * 하단: Funnel Progress 숫자 — GET /api/v1/funnel/summary 재사용
   */

  var PF_PROFILE_COLORS = { LOW_VOL: '#6cb6ff', MID_VOL: '#3fb950', HIGH_VOL: '#d29922', THEME_SPIKE: '#f85149' };
  var PF_REGIME_LABELS = { risk_on: 'Risk On', neutral: '중립', risk_off: 'Risk Off', volatile: '변동성' };
  var PF_REGIME_COLORS = { risk_on: '#3fb950', neutral: '#8b9bb4', risk_off: '#f85149', volatile: '#d29922' };

  function _pfSet(id, text) {
    var el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  /* ISO timestamp → HH:MM (KST) */
  function _pfHHMM(isoStr) {
    if (!isoStr) return '-';
    try {
      var d = new Date(isoStr);
      if (isNaN(d.getTime())) {
        // 'HH:MM:SS' 같은 시간 문자열 대응
        var m = String(isoStr).match(/^(\d{2}):(\d{2})/);
        return m ? m[1] + ':' + m[2] : String(isoStr);
      }
      return d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Seoul' });
    } catch (e) { return String(isoStr); }
  }

  function _pfProfileBadge(profile) {
    var color = PF_PROFILE_COLORS[profile] || '#8b9bb4';
    var short = { LOW_VOL: 'L', MID_VOL: 'M', HIGH_VOL: 'H', THEME_SPIKE: 'T' }[profile] || (profile || '?');
    return '<span style="display:inline-block; min-width:14px; text-align:center; font-size:10px; font-weight:700;'
      + ' color:' + color + '; border:1px solid ' + color + '; border-radius:3px; padding:0 3px;"'
      + ' title="' + escapeHtml(profile || '') + '">' + escapeHtml(short) + '</span>';
  }

  /* ── 상단: Daily Plan 요약 ── */
  async function _pfLoadPlanSummary(tradeDate) {
    try {
      var url = tradeDate ? '/api/v1/daily-plan/today?trade_date=' + encodeURIComponent(tradeDate) : '/api/v1/daily-plan/today';
      var r = await fetch(url);
      var d = await r.json();
      var plan = d.payload;
      if (!plan) {
        _pfSet('pf-market-tone', '미수집·대기');
        _pfSet('pf-intensity', '매매 강도: -');
        _pfSet('pf-assignments-count', '-');
        var distEl0 = document.getElementById('pf-profile-dist');
        if (distEl0) distEl0.innerHTML = '<span class="muted">오늘 Daily Plan 생성 전</span>';
        return;
      }
      _pfSet('pf-market-tone', plan.market_tone || '-');
      _pfSet('pf-intensity', '매매 강도: ' + (plan.trading_intensity || '-'));
      _pfSet('pf-new-entry', plan.new_entry_allowed ? '허용' : '차단');
      _pfSet('pf-plan-status', 'Plan 상태: ' + (plan.status || '-'));

      var assignments = plan.symbol_assignments || [];
      _pfSet('pf-assignments-count', assignments.length + '종목');
      var counts = { LOW_VOL: 0, MID_VOL: 0, HIGH_VOL: 0, THEME_SPIKE: 0 };
      assignments.forEach(function(a) { if (counts[a.profile] !== undefined) counts[a.profile]++; });
      var distEl = document.getElementById('pf-profile-dist');
      if (distEl) {
        distEl.innerHTML = Object.keys(counts).map(function(k) {
          return '<span style="margin-right:10px;">' + _pfProfileBadge(k) + ' <strong>' + counts[k] + '</strong></span>';
        }).join('');
      }
    } catch (e) {
      console.warn('[WARN] plan-funnel plan summary load failed', e.message);
    }

    // 레짐(오늘 Regime Set 적용 결과) — Daily Plan 화면과 동일 API 재사용
    try {
      var regimeUrl = tradeDate ? '/api/v1/regime/today?trade_date=' + encodeURIComponent(tradeDate) : '/api/v1/regime/today';
      var sr = await fetch(regimeUrl);
      var sd = await sr.json();
      var app = (sd && sd.ok && sd.application) ? sd.application : null;
      var regimeEl = document.getElementById('pf-regime');
      if (regimeEl) {
        if (app && app.regime_label) {
          var rc = PF_REGIME_COLORS[app.regime_label] || '#8b9bb4';
          regimeEl.innerHTML = '<span style="color:' + rc + '; font-weight:700;">'
            + escapeHtml(PF_REGIME_LABELS[app.regime_label] || app.regime_label) + '</span>';
          _pfSet('pf-regime-set', app.set_name || '-');
        } else {
          regimeEl.textContent = '-';
          _pfSet('pf-regime-set', '오늘 적용 기록 없음');
        }
      }
    } catch (e) {
      console.warn('[WARN] plan-funnel regime load failed', e.message);
    }
  }

  /* ── 중단: 장중 선별 타임라인 ── */
  async function _pfLoadIntradayEvents(tradeDate) {
    var box = document.getElementById('pf-intraday-timeline');
    if (!box) return;
    box.innerHTML = '<div class="muted" style="padding:8px; grid-column:1/-1;">로딩중...</div>';
    try {
      var r = await fetchJson('/api/v1/daily-plan/intraday-events?date=' + encodeURIComponent(tradeDate));
      var events = r.events || [];
      _pfSet('pf-intraday-count', r.count != null ? r.count + '건' : '-');
      if (!events.length) {
        box.innerHTML = '<div class="muted" style="padding:8px; grid-column:1/-1;">해당 날짜의 장중 선별 이벤트 없음 — 모멘텀 스캔/재선별이 종목을 추가하면 여기에 시각순으로 표시됩니다.</div>';
        return;
      }
      box.innerHTML = events.map(function(ev) {
        var symbols = ev.symbols_added || [];
        var rc = PF_REGIME_COLORS[ev.regime] || '#8b9bb4';
        var regimeTxt = ev.regime ? (PF_REGIME_LABELS[ev.regime] || ev.regime) : '-';
        var head = '<div style="display:flex; gap:6px; align-items:center; flex-wrap:wrap; margin-bottom:6px;">'
          + '<span style="font-weight:700; font-size:13px;">' + escapeHtml(_pfHHMM(ev.event_time)) + '</span>'
          + '<span style="font-size:10px; color:var(--accent);">' + escapeHtml(ev.trigger || '-') + '</span>'
          + '<span style="font-size:10px; color:' + rc + ';">' + escapeHtml(regimeTxt) + '</span>'
          + (ev.market_tone ? '<span style="font-size:10px; color:var(--muted);">' + escapeHtml(ev.market_tone) + '</span>' : '')
          + '<span style="font-size:10px; color:var(--muted); margin-left:auto;">' + symbols.length + '종목</span>'
          + '</div>';
        var body = symbols.length
          ? '<div style="display:flex; flex-direction:column; gap:3px;">'
            + symbols.map(function(s) {
                return '<div style="display:flex; gap:6px; align-items:baseline; font-size:12px;">'
                  + _pfProfileBadge(s.profile)
                  + '<span style="font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="' + escapeHtml(s.name || '') + '">'
                    + escapeHtml(s.name || s.symbol || '-') + '</span>'
                  + '</div>';
              }).join('')
            + '</div>'
          : '<div class="muted" style="font-size:11px;">추가 종목 없음</div>';
        return '<div class="card compact" style="border-left:3px solid var(--accent);">' + head + body + '</div>';
      }).join('');
    } catch (e) {
      box.innerHTML = '<div class="muted" style="padding:8px; grid-column:1/-1;">장중 선별 이력 조회 실패: ' + escapeHtml(e.message) + '</div>';
    }
  }

  /* ── 하단: Funnel Progress 숫자 ── */
  async function _pfLoadFunnelSummary() {
    try {
      var r = await fetchJson('/api/v1/funnel/summary');
      var fp = (r && r.ok && r.payload) ? r.payload : {};
      _pfSet('pf-funnel-total', fp.total_universe != null && fp.total_universe > 0 ? fp.total_universe.toLocaleString() : '-');
      _pfSet('pf-funnel-layer1', fp.layer1_count != null ? fp.layer1_count.toLocaleString() : '-');
      _pfSet('pf-funnel-layer2', fp.layer2_count != null ? fp.layer2_count.toLocaleString() : '-');
      _pfSet('pf-funnel-signals', fp.signals_count != null ? String(fp.signals_count) : '-');
      var noteEl = document.getElementById('pf-funnel-note');
      if (noteEl) {
        noteEl.textContent = fp.empty_reason
          ? fp.empty_reason
          : (fp.last_updated_at ? '마지막 Funnel 결과 시각: ' + fp.last_updated_at : '오늘 저장된 Funnel 결과 시각 없음');
      }
    } catch (e) {
      var noteEl2 = document.getElementById('pf-funnel-note');
      if (noteEl2) noteEl2.textContent = 'Funnel summary 조회 실패: ' + (e.message || 'unknown');
    }
  }

  /* Plan & Funnel 통합 화면 로드 진입점 */
  async function loadPlanFunnel() {
    var tradeDate = window._tcTradeDate || getKstDateString();
    _pfSet('pf-trade-date', tradeDate);
    await Promise.allSettled([
      _pfLoadPlanSummary(tradeDate),
      _pfLoadIntradayEvents(tradeDate),
      _pfLoadFunnelSummary(),
    ]);
  }
