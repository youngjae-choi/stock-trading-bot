  // Engine Monitor — 6엔진 상태를 한 화면에 (monitor_engines.py의 웹 버전)
  async function loadEngineMonitor() {
    try {
      const res = await fetch('/api/v1/engine-monitor/status');
      if (!res.ok) return;
      const j = await res.json();
      const p = j.payload || {};
      const set = (id, v) => { const el = document.getElementById(id); if (el) el.innerHTML = v; };

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
