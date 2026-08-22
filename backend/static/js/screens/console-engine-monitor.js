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

      // ④⑤⑥
      set('em-todo', (p.engines_todo || []).join(' · ') + ' — 미착수');
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

  // 전략 엔진 설정 (SSOT 추적) — Settings 화면 섹션. 엔진이 읽는 설정을 그대로 편집.
  async function loadEngineSettings() {
    try {
      const res = await fetch('/api/v1/engine-monitor/settings');
      if (!res.ok) return;
      const groups = ((await res.json()).payload || {}).groups || [];
      const body = document.getElementById('engine-settings-body');
      if (!body) return;
      body.innerHTML = groups.map(g => {
        const rows = g.items.map(it => {
          const drift = (it.intent != null && String(it.value) !== String(it.intent))
            ? ` <span class="status warn" style="font-size:0.8em">의도 ${it.intent}</span>` : '';
          const src = it.in_db ? '' : ' <span class="muted" style="font-size:0.8em">(코드기본)</span>';
          return `<tr>
            <td style="padding:4px 8px;font-size:12px;">${it.key}${src}${drift}</td>
            <td style="padding:4px 8px;"><input class="es-input" data-key="${it.key}" value="${it.value != null ? it.value : ''}" style="width:120px;padding:3px 6px;background:var(--panel-2);border:1px solid var(--border);border-radius:4px;color:var(--text);font-size:12px;"></td>
            <td style="padding:4px 8px;"><button class="btn small" data-action="saveEngineSetting" data-key="${it.key}">저장</button></td>
          </tr>`;
        }).join('');
        return `<div style="margin-bottom:10px;"><div style="font-weight:600;font-size:12px;color:var(--muted);margin:8px 0 4px;">${g.title}</div>
          <table style="width:100%;border-collapse:collapse;">${rows}</table></div>`;
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
