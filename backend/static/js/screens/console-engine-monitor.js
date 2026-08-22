  // Engine Monitor — 6엔진 상태를 한 화면에 (monitor_engines.py의 웹 버전)
  async function loadEngineMonitor() {
    try {
      const res = await fetch('/api/v1/engine-monitor/status');
      if (!res.ok) return;
      const j = await res.json();
      const p = j.payload || {};
      const set = (id, v) => { const el = document.getElementById(id); if (el) el.innerHTML = v; };

      // Alert Center 요약(미확인 경고) — Alert 화면 안 봐도 여기서 감지
      const al = p.alerts || {};
      const crit = al.critical || 0, un = al.unacked || 0;
      set('em-alerts', (crit > 0)
        ? `<span class="status fail">🔴 CRITICAL ${crit}건</span> · 미확인 ${un}건 <a href="#alerts" style="font-size:0.85em">→ Alert Center</a>`
        : (un > 0)
          ? `<span class="status warn">⚠ 미확인 ${un}건</span> <a href="#alerts" style="font-size:0.85em">→ Alert Center</a>`
          : '<span class="status ok">✅ 미확인 경고 없음</span>');

      // SSOT 폐루프
      const ssot = p.ssot || {};
      set('em-ssot', ssot.ok
        ? '<span class="status ok">✅ 정합</span> 드리프트 0 · conformance 0'
        : `<span class="status fail">🔴 드리프트 ${ssot.drift} · conformance ${ssot.conformance}</span><br><span class="muted" style="font-size:0.85em">${(ssot.items || []).join(' / ')}</span>`);

      // 엔진① 사이징(활성)
      const e1 = p.engine1_sizing || {};
      const e1on = String(e1.active) === 'true' || e1.active === true;
      set('em-e1', `<span class="status ${e1on ? 'ok' : 'warn'}">${e1on ? '활성' : 'off'}</span> `
        + `종목당 <b>${e1.per_rate_min}~${e1.per_rate_max}</b> · 종목수 ${e1.positions_min}~${e1.positions_max} · 폭등상한 ${e1.surge_rate_max}`);

      // 엔진② 시장감지 + 대응
      const e2 = p.engine2_regime || {};
      const th = e2.thresholds || {};
      const ract = String(e2.response_active) === 'true' || e2.response_active === true;
      set('em-e2', `현재 5장세=<b>${e2.current_5tier}</b> 전환=<b>${e2.current_transition}</b> · `
        + `대응 <span class="status ${ract ? 'ok' : 'warn'}">${ract ? 'on' : 'off(감지검증 후)'}</span> 트레일배수 ${e2.trail_tighten_factor}`
        + `<br><span class="muted" style="font-size:0.85em">임계 하락 ${th.down} · 상승 ${th.up} · 폭등 ${th.surge} · 전환 ${th.down_transition_pp}/${th.up_transition_pp}%p</span>`);

      const series = e2.kospi_series || [];
      set('em-kospi', series.length
        ? series.map(s => `<span class="${s.v > 0 ? 'up' : s.v < 0 ? 'down' : ''}">${s.t} ${s.v > 0 ? '+' : ''}${s.v}%</span>`).join(' → ')
        : '<span class="muted">시계열 없음 (거래일 레짐 틱 대기)</span>');

      // 엔진③ 종목선정
      const e3 = p.engine3_selection || {};
      set('em-e3', `선정 가중치 등락률 <b>${e3.change_weight}</b> · 거래량 <b>${e3.surge_weight}</b> `
        + `<span class="muted">(점수 모듈 구축, 미배선)</span>`);

      // 엔진④ 매수 게이트 (현재 레짐 기준 라이브)
      const e4 = p.engine4_buy || {};
      const e4on = e4.wired === true;
      const pct = (v) => (v == null ? '-' : v);
      set('em-e4', `<span class="status ${e4on ? 'ok' : 'warn'}">${e4on ? '소비중' : '미배선'}</span> `
        + `레짐 <b>${e4.regime || '-'}</b> · VWAP눌림 <b>${e4.vwap_mode || '-'}</b> (≤${pct(e4.max_vwap_dist)}%) · `
        + `진입밴드 <b>${pct(e4.band_min)}~${pct(e4.band_max)}%</b> · 거래량 ≥${pct(e4.min_vol)} · 레버리지 ${e4.leverage || '-'}`
        + `<br><span class="muted" style="font-size:0.85em">decision_engine VWAP게이트 + 진입차단 경유</span>`);

      // 엔진⑤ 매도 (스케일아웃·트레일 — 현재 레짐 기준)
      const e5 = p.engine5_sell || {};
      const e5on = e5.wired === true;
      set('em-e5', `<span class="status ${e5on ? 'ok' : 'warn'}">${e5on ? '소비중' : '미배선'}</span> `
        + `수확 <b>${e5.harvest || '-'}</b> · +<b>${pct(e5.scaleout_target)}%</b>서 <b>${pct(e5.scaleout_ratio)}</b> 확정 · `
        + `손절 ${pct(e5.stop_loss)}% · 트레일 ${pct(e5.trail)}%`
        + `<br><span class="muted" style="font-size:0.85em">position_manager 스케일아웃 + 트레일 경유</span>`);

      // 엔진⑥ 매매·실행 사이징
      const e6 = p.engine6_execution || {};
      const e6on = String(e6.model_active) === 'true' || e6.model_active === true;
      set('em-e6', `<span class="status ${e6on ? 'ok' : 'warn'}">${e6on ? '활성' : 'off'}</span> `
        + `확신도=<b>${e6.conviction || '-'}</b> → 예수금 비중배분(엔진① 사이징)`
        + `<br><span class="muted" style="font-size:0.85em">order_executor._compute_new_model_sizing 경유</span>`);

      // 잔여 과제
      set('em-todo', (p.engines_todo || []).join(' · ') || '없음');
    } catch (e) { console.warn('loadEngineMonitor error', e); }
  }

  // Today Control 최상단 핵심 요약 바 — 현재 장세·엔진 정합·경고를 한눈에
  async function loadTodaySummary() {
    try {
      const res = await fetch('/api/v1/engine-monitor/status');
      if (!res.ok) return;
      const p = ((await res.json()).payload) || {};
      const set = (id, v) => { const el = document.getElementById(id); if (el) el.innerHTML = v; };
      const e2 = p.engine2_regime || {};
      const r5 = e2.current_5tier || '-';
      const tr = e2.current_transition;
      const label = { crash: '폭락', down: '하락', flat: '보합', up: '상승', surge: '폭등', volatile: '변동성', '-': '-' }[r5] || r5;
      set('tcs-regime', `${label} <span class="muted" style="font-size:0.7em">${r5}</span>`);
      set('tcs-transition', (tr && tr !== 'none' && tr !== '-')
        ? (tr === 'down_transition' ? '<span class="status warn">↓ 하락전환</span>' : '<span class="status ok">↑ 상승전환</span>')
        : '<span class="muted">방향 안정</span>');
      const ssot = p.ssot || {};
      set('tcs-engine', ssot.ok ? '<span class="status ok">✅ 정합</span>' : `<span class="status fail">🔴 ${ssot.drift + ssot.conformance}건</span>`);
      const al = p.alerts || {};
      const crit = al.critical || 0, un = al.unacked || 0;
      set('tcs-alerts', crit > 0 ? `<span class="status fail">🔴 ${crit}</span> <span class="muted">/${un}</span>`
        : un > 0 ? `<span class="status warn">⚠ ${un}</span>` : '<span class="status ok">없음</span>');
    } catch (e) { console.warn('loadTodaySummary error', e); }
  }

  // 전략 엔진 설정 (SSOT 추적) — Settings 화면 섹션. 사람이 읽는 라벨·설명·드롭다운으로 편집.
  async function loadEngineSettings() {
    try {
      const res = await fetch('/api/v1/engine-monitor/settings');
      if (!res.ok) return;
      const groups = ((await res.json()).payload || {}).groups || [];
      const body = document.getElementById('engine-settings-body');
      if (!body) return;
      const esc = (s) => String(s == null ? '' : s).replace(/"/g, '&quot;');

      function inputHtml(it) {
        const v = it.value != null ? String(it.value) : '';
        const style = 'padding:4px 8px;background:var(--panel-2);border:1px solid var(--border);border-radius:4px;color:var(--text);font-size:12px;';
        if (it.kind === 'bool') {
          const on = (v === 'true' || v === 'True');
          return `<select class="es-input" data-key="${it.key}" style="${style}width:90px;">
            <option value="true"${on ? ' selected' : ''}>ON</option>
            <option value="false"${!on ? ' selected' : ''}>OFF</option></select>`;
        }
        if (it.kind === 'enum' && Array.isArray(it.options)) {
          const opts = it.options.map(o => `<option value="${esc(o)}"${String(o) === v ? ' selected' : ''}>${o}</option>`).join('');
          return `<select class="es-input" data-key="${it.key}" style="${style}width:150px;">${opts}</select>`;
        }
        return `<input class="es-input" type="number" step="any" data-key="${it.key}" value="${esc(v)}" style="${style}width:110px;text-align:right;">`;
      }

      body.innerHTML = groups.map((g, gi) => {
        const rows = g.items.map(it => {
          const label = it.label || it.key;
          const drift = (it.intent != null && String(it.value) !== String(it.intent))
            ? ` <span class="status warn" style="font-size:0.75em;">의도값 ${it.intent}</span>` : '';
          const src = it.in_db
            ? ''
            : ' <span class="muted" style="font-size:0.72em;">· 기본값(DB 미설정)</span>';
          return `<div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;padding:9px 4px;border-bottom:1px solid var(--line);">
            <div style="flex:1;min-width:0;">
              <div style="font-size:13px;font-weight:600;">${label}${drift}</div>
              <div style="font-size:11px;color:var(--muted);margin-top:2px;line-height:1.5;">${it.desc || ''}</div>
              <div style="font-size:10px;color:var(--muted);opacity:0.6;margin-top:2px;font-family:monospace;">${it.key}${src}</div>
            </div>
            <div style="display:flex;gap:6px;align-items:center;flex-shrink:0;">
              ${inputHtml(it)}
              <button class="btn small" data-action="saveEngineSetting" data-key="${it.key}">저장</button>
            </div>
          </div>`;
        }).join('');
        // 첫 그룹만 펼침, 나머지는 접힘(스크롤 부담 완화)
        const open = gi === 0 ? ' open' : '';
        return `<details${open} style="margin-bottom:8px;border:1px solid var(--line);border-radius:6px;padding:4px 10px;">
          <summary style="cursor:pointer;font-weight:600;font-size:12.5px;padding:6px 2px;">${g.title} <span class="muted" style="font-weight:400;">· ${g.items.length}개</span></summary>
          <div style="margin-top:2px;">${rows}</div>
        </details>`;
      }).join('');
    } catch (e) { console.warn('loadEngineSettings error', e); }
  }

  async function saveEngineSetting(key) {
    try {
      const input = document.querySelector('.es-input[data-key="' + key + '"]');
      if (!input) return;
      let raw = input.value.trim();
      let value = raw, vtype = 'string';
      if (raw === 'true' || raw === 'false' || raw === 'True' || raw === 'False') {
        value = (raw.toLowerCase() === 'true'); vtype = 'bool';
      } else if (raw !== '' && !isNaN(Number(raw))) {
        value = Number(raw); vtype = 'number';
      }
      const res = await fetch('/api/v1/settings', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: key, value: value, value_type: vtype }),
      });
      if (res.ok) { showToast('저장: ' + key); await loadEngineSettings(); }
      else showToast('저장 실패: ' + key, 'error');
    } catch (e) { showToast('오류: ' + e.message, 'error'); }
  }
