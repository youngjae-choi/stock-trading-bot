  /* ── Plan & Funnel 통합 화면 (P4 재구성 2026-06-21) ──
   * PM 의도: 종목 목록이 아니라 "환경 → 전략 → 선별" 인과 스토리를 본다.
   *   ① 오늘 시장은?(환경)  — 레짐/톤/전일대비 지표/장중 톤 추이
   *   ② 그래서 전략은?(전략) — 매매강도/신규매수/프로파일 분포/청산정책
   *   ③ 그래서 고른 종목은?(선별) — Funnel 압축 + 선별 요약, 종목 리스트는 접힘
   * 모두 기존 읽기 API 재사용 + 톤 슬롯 추이(GET /market-tone/today/slots, 순수 읽기).
   */

  var PF_PROFILE_COLORS = { LOW_VOL: '#6cb6ff', MID_VOL: '#3fb950', HIGH_VOL: '#d29922', THEME_SPIKE: '#f85149' };
  var PF_REGIME_LABELS = { risk_on: 'Risk On', neutral: '중립', risk_off: 'Risk Off', volatile: '변동성' };
  var PF_REGIME_COLORS = { risk_on: '#3fb950', neutral: '#8b9bb4', risk_off: '#f85149', volatile: '#d29922' };
  var PF_TONE_LABELS = { positive: '긍정', mixed: '혼조', negative: '부정', neutral: '중립', defensive: '방어' };
  var PF_PROFILE_CODE = { L: 'LOW_VOL', M: 'MID_VOL', H: 'HIGH_VOL', T: 'THEME_SPIKE' };
  // 전일 대비로 보여줄 핵심 지표(키: morning_context.market_data, 라벨)
  var PF_INDEX_KEYS = [
    ['vix', 'VIX'], ['sp500', 'S&P500'], ['nasdaq', '나스닥'],
    ['sox', '필라델피아반도체'], ['kospi_night_futures', 'KOSPI야간선물'], ['usdkrw', '환율(USD/KRW)'],
  ];
  var _pfScanUniq = [];
  var _pfScanFilter = 'ALL';

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
        var m = String(isoStr).match(/^(\d{2}):(\d{2})/);
        return m ? m[1] + ':' + m[2] : String(isoStr);
      }
      return d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Seoul' });
    } catch (e) { return String(isoStr); }
  }

  function _pfToneLabel(t) {
    if (!t) return '-';
    return PF_TONE_LABELS[String(t).toLowerCase()] || t;
  }

  function _pfProfileBadge(profile) {
    var color = PF_PROFILE_COLORS[profile] || '#8b9bb4';
    var short = { LOW_VOL: 'L', MID_VOL: 'M', HIGH_VOL: 'H', THEME_SPIKE: 'T' }[profile] || (profile || '?');
    return '<span style="display:inline-block; min-width:14px; text-align:center; font-size:10px; font-weight:700;'
      + ' color:' + color + '; border:1px solid ' + color + '; border-radius:3px; padding:0 3px;"'
      + ' title="' + escapeHtml(profile || '') + '">' + escapeHtml(short) + '</span>';
  }

  /* ── ① 환경 + ② 전략: Daily Plan 요약 + 레짐 ── */
  async function _pfLoadPlanSummary(tradeDate) {
    try {
      var url = tradeDate ? '/api/v1/daily-plan/today?trade_date=' + encodeURIComponent(tradeDate) : '/api/v1/daily-plan/today';
      var r = await fetch(url);
      var d = await r.json();
      var plan = d.payload;
      if (!plan) {
        _pfSet('pf-market-tone', '미수집·대기');
        _pfSet('pf-intensity', '-');
        _pfSet('pf-new-entry', '-');
        _pfSet('pf-plan-status', 'Plan 상태: 생성 전');
        _pfSet('pf-assignments-count', '-');
        var distEl0 = document.getElementById('pf-profile-dist');
        if (distEl0) distEl0.innerHTML = '<span class="muted">오늘 Daily Plan 생성 전</span>';
        return;
      }
      _pfSet('pf-market-tone', _pfToneLabel(plan.market_tone));
      _pfSet('pf-intensity', plan.trading_intensity || '-');
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

    // 레짐(오늘 Regime Set 적용 결과 + 근거)
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
          _pfSet('pf-regime-reason', app.match_reason ? ('근거: ' + app.match_reason) : '');
        } else {
          regimeEl.textContent = '-';
          _pfSet('pf-regime-set', '오늘 적용 기록 없음');
          _pfSet('pf-regime-reason', '');
        }
      }
    } catch (e) {
      console.warn('[WARN] plan-funnel regime load failed', e.message);
    }
  }

  /* ① 환경: 시장 톤 + 장중 톤 추이(슬롯) */
  async function _pfLoadToneTrend(tradeDate) {
    var confEl = document.getElementById('pf-tone-confidence');
    var trendEl = document.getElementById('pf-tone-trend');
    try {
      var r = await fetch('/api/v1/market-tone/today/slots');
      var d = await r.json();
      var slots = (d && d.payload && d.payload.slots) || [];
      if (!slots.length) {
        if (trendEl) trendEl.innerHTML = '<span class="muted">장중 톤 기록 없음</span>';
        return;
      }
      var last = slots[slots.length - 1];
      if (confEl && last.confidence != null) {
        confEl.textContent = '신뢰도 ' + Math.round(Number(last.confidence) * 100) + '%';
      }
      // 톤이 바뀐 지점만 추려 추이 표시 (예: 긍정 → 혼조)
      var seq = [];
      slots.forEach(function(s) {
        var lab = _pfToneLabel(s.tone);
        if (!seq.length || seq[seq.length - 1] !== lab) seq.push(lab);
      });
      if (trendEl) {
        if (seq.length <= 1) {
          trendEl.innerHTML = '<span class="muted">장중 변화 없음 (' + escapeHtml(seq[0] || '-') + ' 유지, ' + slots.length + '슬롯)</span>';
        } else {
          trendEl.innerHTML = '<span class="muted">장중 변화: </span>'
            + seq.map(function(x) { return '<strong>' + escapeHtml(x) + '</strong>'; }).join('<span class="muted"> → </span>');
        }
      }
    } catch (e) {
      if (trendEl) trendEl.innerHTML = '<span class="muted">톤 추이 조회 실패</span>';
    }
  }

  /* ① 환경: 전일 대비 해외지표·변동성 (morning_context.market_data 내장값) */
  async function _pfLoadIndexChanges(tradeDate) {
    var box = document.getElementById('pf-index-changes');
    if (!box) return;
    try {
      var url = tradeDate ? '/api/v1/morning-context/today?trade_date=' + encodeURIComponent(tradeDate) : '/api/v1/morning-context/today';
      var r = await fetch(url);
      var d = await r.json();
      var md = (d && d.ok && d.data && d.data.market_data) ? d.data.market_data : null;
      if (!md) {
        box.innerHTML = '<span class="muted">아침 시장 데이터 없음(S2 미실행)</span>';
        return;
      }
      var parts = PF_INDEX_KEYS.map(function(pair) {
        var key = pair[0], label = pair[1];
        var v = md[key];
        if (!v || v.change_pct == null) return '';
        var pct = Number(v.change_pct);
        var up = pct > 0, down = pct < 0;
        var color = up ? 'var(--green)' : (down ? 'var(--red)' : 'var(--muted)');
        var arrow = up ? '▲' : (down ? '▼' : '–');
        return '<span title="' + escapeHtml(label) + '">'
          + '<span class="muted">' + escapeHtml(label) + '</span> '
          + '<span style="color:' + color + '; font-weight:600;">' + arrow + ' ' + (up ? '+' : '') + pct.toFixed(2) + '%</span>'
          + '</span>';
      }).filter(Boolean);
      box.innerHTML = parts.length ? parts.join('') : '<span class="muted">전일 대비 데이터 없음</span>';
      if (d.is_today === false) {
        box.innerHTML += '<span class="muted" style="flex-basis:100%; font-size:11px;">(오늘 데이터 없어 최근일 기준)</span>';
      }
    } catch (e) {
      box.innerHTML = '<span class="muted">지표 조회 실패: ' + escapeHtml(e.message) + '</span>';
    }
  }

  /* "재선별" 뱃지 */
  function _pfReselectBadge() {
    return '<span style="display:inline-block; font-size:9px; font-weight:700; color:#fff;'
      + ' background:var(--accent); border-radius:3px; padding:1px 5px; flex-shrink:0;">재선별</span>';
  }

  /* 모멘텀 스캔 유입 종목 리스트 렌더 — 프로파일 필터(_pfScanFilter) 반영 */
  function _pfRenderScanList() {
    var box = document.getElementById('pf-intraday-timeline');
    if (!box) return;
    var prof = PF_PROFILE_CODE[_pfScanFilter] || null;
    var rows = prof ? _pfScanUniq.filter(function(u) { return u.profile === prof; }) : _pfScanUniq;
    _pfSet('pf-intraday-count', prof
      ? (rows.length + ' / ' + _pfScanUniq.length + '종목')
      : (_pfScanUniq.length + '종목'));
    ['ALL', 'L', 'M', 'H', 'T'].forEach(function(code) {
      var b = document.getElementById('pf-scanf-' + code);
      if (b) b.className = 'btn' + (code === _pfScanFilter ? ' primary' : '');
    });
    if (!rows.length) {
      box.innerHTML = '<div class="muted" style="padding:8px; grid-column:1/-1;">'
        + (_pfScanUniq.length ? '해당 프로파일 유입 종목 없음.' : '해당 날짜의 모멘텀 스캔 유입 종목 없음.') + '</div>';
      return;
    }
    box.innerHTML = rows.map(function(u) {
      return '<div style="display:flex; gap:6px; align-items:center; font-size:12px; padding:4px 6px;">'
        + '<span style="font-size:11px; color:var(--muted); width:40px; flex-shrink:0;">' + escapeHtml(_pfHHMM(u.time)) + '</span>'
        + _pfProfileBadge(u.profile)
        + '<span style="font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="' + escapeHtml(u.name || '') + '">'
          + escapeHtml(u.name || u.symbol || '-') + '</span>'
        + '</div>';
    }).join('');
  }

  /* 프로파일 필터 칩 클릭 — ALL/L/M/H/T */
  function pfFilterScan(code) {
    _pfScanFilter = code || 'ALL';
    _pfRenderScanList();
  }
  window.pfFilterScan = pfFilterScan;

  /* ③ 선별 하위(접힘): 장중 선별 타임라인 — 모멘텀 스캔 + 재선별 */
  async function _pfLoadIntradayEvents(tradeDate) {
    var box = document.getElementById('pf-intraday-timeline');
    var listBox = document.getElementById('pf-reselect-list');
    if (!box) return;
    box.innerHTML = '<div class="muted" style="padding:8px; grid-column:1/-1;">로딩중...</div>';
    if (listBox) listBox.innerHTML = '<div class="muted" style="padding:8px;">로딩중...</div>';
    try {
      var r = await fetchJson('/api/v1/daily-plan/intraday-events?date=' + encodeURIComponent(tradeDate));
      var events = r.events || [];
      var scanEvents = events.filter(function(ev) { return ev.trigger === 'momentum_scan'; });
      var reselectEvents = events.filter(function(ev) { return ev.trigger === 'intraday_refresh'; });

      // 모멘텀 스캔 — 종목별 중복 제거 후 "최초 유입 시각"만 표시
      var firstSeen = {};
      scanEvents.forEach(function(ev) {
        (ev.symbols_added || []).forEach(function(s) {
          var key = s.symbol || s.name;
          if (!key) return;
          var t = ev.event_time || '';
          if (!firstSeen[key]) {
            firstSeen[key] = { name: s.name, symbol: s.symbol, profile: s.profile, time: t };
          } else if (t && (!firstSeen[key].time || t < firstSeen[key].time)) {
            firstSeen[key].time = t;
            if (s.profile) firstSeen[key].profile = firstSeen[key].profile || s.profile;
          }
        });
      });
      _pfScanUniq = Object.keys(firstSeen).map(function(k) { return firstSeen[k]; });
      _pfScanUniq.sort(function(a, b) { return String(a.time).localeCompare(String(b.time)); });
      _pfRenderScanList();

      // 장중 재선별 종목 리스트
      if (listBox) {
        var reselectRows = [];
        reselectEvents.forEach(function(ev) {
          (ev.symbols_added || []).forEach(function(s) { reselectRows.push({ ev: ev, s: s }); });
        });
        _pfSet('pf-reselect-count', reselectRows.length + '종목');
        if (!reselectRows.length) {
          listBox.innerHTML = '<div class="muted" style="padding:8px;">오늘 장중 재선별로 유입된 종목이 없습니다.</div>';
        } else {
          listBox.innerHTML = reselectRows.map(function(row) {
            var ev = row.ev, s = row.s;
            var rc = PF_REGIME_COLORS[ev.regime] || '#8b9bb4';
            var regimeTxt = ev.regime ? (PF_REGIME_LABELS[ev.regime] || ev.regime) : '-';
            return '<div style="display:flex; gap:8px; align-items:center; font-size:12px; padding:5px 8px;'
              + ' border-left:3px solid var(--accent); background:var(--bg2,transparent); border-radius:4px;">'
              + _pfReselectBadge()
              + _pfProfileBadge(s.profile)
              + '<span style="font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="' + escapeHtml(s.name || '') + '">'
                + escapeHtml(s.name || s.symbol || '-') + '</span>'
              + '<span style="font-size:10px; color:var(--muted); margin-left:auto;">' + escapeHtml(_pfHHMM(ev.event_time)) + '</span>'
              + '<span style="font-size:10px; color:' + rc + ';">' + escapeHtml(regimeTxt) + '</span>'
              + '</div>';
          }).join('');
        }
      }
    } catch (e) {
      box.innerHTML = '<div class="muted" style="padding:8px; grid-column:1/-1;">장중 선별 이력 조회 실패: ' + escapeHtml(e.message) + '</div>';
      if (listBox) listBox.innerHTML = '<div class="muted" style="padding:8px;">재선별 이력 조회 실패</div>';
    }
  }

  /* ③ 선별: Funnel 압축 숫자 + 선별 요약 */
  async function _pfLoadFunnelSummary() {
    var sumEl = document.getElementById('pf-select-summary');
    try {
      var r = await fetchJson('/api/v1/funnel/summary');
      var fp = (r && r.ok && r.payload) ? r.payload : {};
      _pfSet('pf-funnel-total', fp.total_universe != null && fp.total_universe > 0 ? fp.total_universe.toLocaleString() : '-');
      _pfSet('pf-funnel-layer1', fp.layer1_count != null ? fp.layer1_count.toLocaleString() : '-');
      _pfSet('pf-funnel-layer2', fp.layer2_count != null ? fp.layer2_count.toLocaleString() : '-');
      _pfSet('pf-funnel-signals', fp.signals_count != null ? String(fp.signals_count) : '-');
      if (sumEl) {
        var l2 = fp.layer2_count, sig = fp.signals_count;
        if (l2 != null && l2 > 0) {
          sumEl.innerHTML = '전략 통과 <strong>' + l2 + '종목</strong>'
            + (sig != null ? ' · BUY 신호 <strong>' + sig + '건</strong>' : '')
            + '<span class="muted"> — 상세 종목은 아래 펼쳐보기</span>';
        } else {
          sumEl.innerHTML = '<span class="muted">아직 선별 통과 종목이 없습니다.</span>';
        }
      }
      var noteEl = document.getElementById('pf-funnel-note');
      if (noteEl) {
        noteEl.textContent = fp.empty_reason
          ? fp.empty_reason
          : (fp.last_updated_at ? '마지막 Funnel 결과 시각: ' + fp.last_updated_at : '오늘 저장된 Funnel 결과 시각 없음');
      }
    } catch (e) {
      var noteEl2 = document.getElementById('pf-funnel-note');
      if (noteEl2) noteEl2.textContent = 'Funnel summary 조회 실패: ' + (e.message || 'unknown');
      if (sumEl) sumEl.innerHTML = '';
    }
  }

  /* ── ②.5 장중 전략 변화 타임라인 ── */
  // 전략 파라미터 라벨 맵(레짐 SET applied_settings 키) — 미래 키는 일반표시.
  var PF_SETTINGS_LABELS = {
    max_positions: { label: '최대 보유', fmt: function(v) { return v + '종목'; }, dir: true },
    new_entry_allowed: { label: '신규매수', fmt: function(v) { return v ? '허용' : '차단'; } },
    stop_loss_rate: { label: '손절', fmt: function(v) { return (Number(v) * 100).toFixed(1) + '%'; } },
    take_profit_rate: { label: '익절', fmt: function(v) { return (Number(v) * 100).toFixed(1) + '%'; } },
    trailing_activate_profit: { label: '트레일 발동', fmt: function(v) { return (Number(v) * 100).toFixed(1) + '%'; } },
    trailing_stop_rate: { label: '트레일 폭', fmt: function(v) { return (Number(v) * 100).toFixed(1) + '%'; } },
    trading_intensity: { label: '매매강도', fmt: function(v) { return String(v); } },
  };

  function _pfFmtSetting(key, v) {
    var meta = PF_SETTINGS_LABELS[key];
    if (v === undefined || v === null) return '-';
    return meta ? meta.fmt(v) : String(v);
  }

  /* 직전 SET 대비 변경된 전략 파라미터만 "라벨 a→b" 로 반환(키-무관) */
  function _pfDiffSettings(prev, next) {
    prev = prev || {}; next = next || {};
    var keys = {};
    Object.keys(prev).forEach(function(k) { keys[k] = 1; });
    Object.keys(next).forEach(function(k) { keys[k] = 1; });
    var out = [];
    Object.keys(keys).forEach(function(k) {
      var a = prev[k], b = next[k];
      if (JSON.stringify(a) === JSON.stringify(b)) return;
      var meta = PF_SETTINGS_LABELS[k];
      var label = meta ? meta.label : k;
      var arrow = '';
      if (meta && meta.dir && typeof a === 'number' && typeof b === 'number') arrow = b > a ? ' ↑' : (b < a ? ' ↓' : '');
      out.push(label + ' ' + _pfFmtSetting(k, a) + '→' + _pfFmtSetting(k, b) + arrow);
    });
    return out;
  }

  /* 아침(첫) 행용 절대 요약 */
  function _pfSettingsSummary(s) {
    s = s || {};
    var parts = [];
    if (s.max_positions != null) parts.push('최대 ' + s.max_positions + '종목');
    if (s.new_entry_allowed != null) parts.push('신규매수 ' + (s.new_entry_allowed ? '허용' : '차단'));
    if (s.stop_loss_rate != null) parts.push('손절 ' + (Number(s.stop_loss_rate) * 100).toFixed(1) + '%');
    if (s.take_profit_rate != null) parts.push('익절 ' + (Number(s.take_profit_rate) * 100).toFixed(1) + '%');
    return parts.length ? parts.join(' · ') : '세부 설정 미기록';
  }

  function _pfRenderTlRow(row) {
    var time = '<span style="font-size:11px; color:var(--muted); width:42px; flex-shrink:0;">' + escapeHtml(row.hhmm || '-') + '</span>';
    if (row.kind === 'regime') {
      var t = row.t;
      var rc = PF_REGIME_COLORS[t.regime_label] || '#8b9bb4';
      var rlab = PF_REGIME_LABELS[t.regime_label] || t.regime_label || '-';
      var icon = row.isMorning ? '🌅' : '⚡';
      var head, mkt = '', strat;
      var vix = t.vix_value, kos = t.kospi_change_pct;
      if (row.isMorning) {
        head = '<span style="color:' + rc + '; font-weight:700;">[' + escapeHtml(rlab) + ']</span> SET ' + escapeHtml(t.set_name || '-');
        mkt = '시장: ' + (vix != null ? 'VIX ' + vix : '') + (kos != null ? ' · KOSPI ' + (kos > 0 ? '+' : '') + kos + '%' : '');
        strat = '전략: ' + escapeHtml(_pfSettingsSummary(t.applied_settings));
      } else {
        var pl = row.prev ? (PF_REGIME_LABELS[row.prev.regime_label] || row.prev.regime_label || '') : '';
        head = '<span style="font-weight:700;">' + escapeHtml(pl) + ' → <span style="color:' + rc + ';">' + escapeHtml(rlab) + '</span></span> <span class="muted">← 시장 변화</span>';
        if (row.prev) {
          var pv = row.prev.vix_value, pk = row.prev.kospi_change_pct;
          var vixTxt = (pv != null && vix != null) ? ('VIX ' + pv + '→' + vix) : (vix != null ? 'VIX ' + vix : '');
          var kosTxt = (pk != null && kos != null) ? ('KOSPI ' + (pk > 0 ? '+' : '') + pk + '%→' + (kos > 0 ? '+' : '') + kos + '%') : (kos != null ? 'KOSPI ' + (kos > 0 ? '+' : '') + kos + '%' : '');
          mkt = '시장: ' + [vixTxt, kosTxt].filter(Boolean).join(' · ');
        }
        var diffs = _pfDiffSettings(row.prev ? row.prev.applied_settings : {}, t.applied_settings);
        strat = diffs.length ? ('→ 전략변경: ' + diffs.map(escapeHtml).join(' · ')) : '→ 전략 변경 적용 (세부 변경 항목 미기록)';
      }
      if (t.match_reason) mkt += (mkt ? ' ' : '') + '<span class="muted">(' + escapeHtml(t.match_reason) + ')</span>';
      return '<div style="display:flex; gap:8px; padding:6px 8px; border-left:3px solid ' + rc + '; background:var(--bg2,transparent); border-radius:4px;">'
        + time
        + '<div style="flex:1; min-width:0; font-size:12px;">'
        + '<div>' + icon + ' ' + head + '</div>'
        + (mkt ? '<div class="muted" style="margin-top:2px;">' + mkt + '</div>' : '')
        + '<div style="margin-top:2px;' + (row.isMorning ? '' : ' color:var(--accent); font-weight:600;') + '">' + strat + '</div>'
        + '</div></div>';
    }
    if (row.kind === 'tone') {
      return '<div style="display:flex; gap:8px; font-size:12px; padding:4px 8px;">' + time
        + '<div style="flex:1;">🗣️ 시장 톤 변화: <strong>' + escapeHtml(row.from) + '</strong> → <strong>' + escapeHtml(row.to) + '</strong>'
        + (row.conf != null ? ' <span class="muted">(신뢰도 ' + Math.round(Number(row.conf) * 100) + '%)</span>' : '') + '</div></div>';
    }
    if (row.kind === 'refresh') {
      var sl = row.sl;
      var avg = sl.avg_change;
      var avgTxt = avg != null ? ((avg > 0 ? '+' : '') + Number(avg).toFixed(2) + '%') : '';
      if (!sl.triggered) {
        return '<div style="display:flex; gap:8px; font-size:12px; padding:4px 8px; color:var(--muted);">' + time
          + '<div style="flex:1;">⚙️ 점검 — 변화 없음(검토 후 유지)' + (avgTxt ? ' · avg ' + escapeHtml(avgTxt) : '') + (sl.reason ? ' · ' + escapeHtml(sl.reason) : '') + '</div></div>';
      }
      var extra = [];
      if (sl.new_candidates) extra.push('신규 유입 ' + sl.new_candidates + '종목');
      if (row.sectors && row.sectors.length && row.sectors[0].gap_pct != null) extra.push('섹터 로테이션 gap ' + Number(row.sectors[0].gap_pct).toFixed(1) + '%');
      if (row.reps && row.reps.length) extra.push('교체신호 ' + row.reps.length + '건');
      return '<div style="display:flex; gap:8px; font-size:12px; padding:5px 8px; border-left:3px solid var(--accent); background:var(--bg2,transparent); border-radius:4px;">' + time
        + '<div style="flex:1;">🔁 장중 재선별' + (avgTxt ? ' (avg ' + escapeHtml(avgTxt) + ' 임계초과)' : '')
        + (extra.length ? '<div class="muted" style="margin-top:2px;">' + escapeHtml(extra.join(' · ')) + '</div>' : '') + '</div></div>';
    }
    return '';
  }

  async function _pfLoadStrategyTimeline(tradeDate) {
    var box = document.getElementById('pf-strat-timeline');
    var sumEl = document.getElementById('pf-strat-tl-summary');
    var curEl = document.getElementById('pf-strat-tl-current');
    if (!box) return;
    box.innerHTML = '<div class="muted" style="padding:8px;">로딩중...</div>';
    var qd = tradeDate ? '?trade_date=' + encodeURIComponent(tradeDate) : '';
    var results = await Promise.allSettled([
      fetch('/api/v1/regime/today' + qd).then(function(r) { return r.json(); }),
      fetch('/api/v1/market-tone/today/slots' + qd).then(function(r) { return r.json(); }),
      fetch('/api/v1/trading-monitor/reselection-stats' + qd).then(function(r) { return r.json(); }),
    ]);
    function val(i) { return results[i].status === 'fulfilled' ? results[i].value : null; }
    var regime = val(0) || {}, toneR = val(1) || {}, resel = val(2) || {};
    var transitions = (regime.ok && Array.isArray(regime.transitions)) ? regime.transitions : [];
    var application = (regime.ok && regime.application) ? regime.application : null;
    var toneSlots = (toneR.payload && toneR.payload.slots) || [];
    var rp = resel.payload || {};
    var reSlots = rp.slots || [], sectors = rp.sector_rotations || [], repls = rp.replacement_signals || [];

    var curSet = (application && application.set_name) ? application.set_name
      : (transitions.length ? transitions[transitions.length - 1].set_name : null);
    if (curEl) curEl.textContent = '현재 SET: ' + (curSet || '-');

    if (!transitions.length && !application) {
      box.innerHTML = '<div class="muted" style="padding:8px;">레짐 데이터 수집 대기 중… (장 시작 전이거나 휴장일)</div>';
      if (sumEl) sumEl.innerHTML = '';
      return;
    }

    var rows = [];
    // 같은 SET의 장중 재적용(트리거가 모두 'morning')은 변화가 아니다 —
    // regime_label·set_name·applied_settings가 직전 대비 실제로 바뀐 "변화 지점"만 남긴다.
    var rawList = transitions.length ? transitions : (application ? [application] : []);
    var regimeList = [];
    rawList.forEach(function(t) {
      var prev = regimeList.length ? regimeList[regimeList.length - 1] : null;
      var changed = !prev
        || prev.regime_label !== t.regime_label
        || prev.set_name !== t.set_name
        || JSON.stringify(prev.applied_settings || {}) !== JSON.stringify(t.applied_settings || {});
      if (changed) regimeList.push(t);
    });
    regimeList.forEach(function(t, idx) {
      rows.push({ hhmm: _pfHHMM(t.applied_at), kind: 'regime', t: t,
        prev: idx > 0 ? regimeList[idx - 1] : null, isMorning: idx === 0 });
    });
    var toneSeq = [];
    toneSlots.forEach(function(s) {
      var lab = _pfToneLabel(s.tone);
      if (!toneSeq.length || toneSeq[toneSeq.length - 1].lab !== lab) toneSeq.push({ lab: lab, t: s.created_at, conf: s.confidence });
    });
    toneSeq.forEach(function(p, idx) {
      if (idx === 0) return;
      rows.push({ hhmm: _pfHHMM(p.t), kind: 'tone', from: toneSeq[idx - 1].lab, to: p.lab, conf: p.conf });
    });
    reSlots.forEach(function(sl) {
      var slot = sl.slot || '';
      rows.push({ hhmm: slot, kind: 'refresh', sl: sl,
        sectors: sectors.filter(function(x) { return (x.slot || '') === slot && x.triggered; }),
        reps: repls.filter(function(x) { return (x.slot || '') === slot; }) });
    });
    rows.sort(function(a, b) { return String(a.hhmm).localeCompare(String(b.hhmm)); });

    // 실제 변화 지점 수(아침 baseline 제외) — 트리거값이 신뢰 불가하므로 dedup 결과로 센다.
    var intradayChanges = Math.max(0, regimeList.length - 1);
    var heldChecks = reSlots.filter(function(s) { return !s.triggered; }).length;
    if (sumEl) {
      if (intradayChanges > 0) {
        sumEl.innerHTML = '<span style="color:var(--accent); font-weight:600;">오늘 장중 전략 ' + intradayChanges + '회 변경</span> — 시장 재분석으로 SET 전환됨.';
      } else {
        sumEl.innerHTML = '<span style="color:var(--green); font-weight:600;">✅ 오늘은 장중 변화 없음</span> (아침 전략 유지)'
          + (reSlots.length ? ' · 장중 ' + reSlots.length + '회 점검' + (heldChecks ? (' 중 ' + heldChecks + '회 임계 미만 → 유지') : '') : '');
      }
    }
    box.innerHTML = rows.length ? rows.map(_pfRenderTlRow).join('') : '<div class="muted" style="padding:8px;">표시할 변화 이력이 없습니다.</div>';
  }

  /* Plan & Funnel 통합 화면 로드 진입점 */
  async function loadPlanFunnel() {
    var tradeDate = window._tcTradeDate || getKstDateString();
    _pfSet('pf-trade-date', tradeDate);
    await Promise.allSettled([
      _pfLoadPlanSummary(tradeDate),
      _pfLoadToneTrend(tradeDate),
      _pfLoadIndexChanges(tradeDate),
      _pfLoadStrategyTimeline(tradeDate),
      _pfLoadIntradayEvents(tradeDate),
      _pfLoadFunnelSummary(),
    ]);
  }
