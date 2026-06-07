(function() {
  /* Task 1 & 2: Load Reselection Stats & Timeline */
  async function loadIntradayReselectionTimeline(tradeDate) {
    const card = document.getElementById('tc-intraday-reselection-card');
    const container = document.getElementById('tc-reselection-timeline');
    const dateEl = document.getElementById('tc-reselection-date');
    if (!card || !container) return;

    try {
      const url = tradeDate ? '/api/v1/trading-monitor/reselection-stats?trade_date=' + tradeDate : '/api/v1/trading-monitor/reselection-stats';
      const res = await fetchJson(url);
      if (!res.ok || !res.payload) {
        card.style.display = 'none';
        return;
      }
      
      const payload = res.payload;
      if (dateEl) dateEl.textContent = payload.trade_date || '오늘';
      
      const slots = payload.slots || [];
      const rotations = payload.sector_rotations || [];
      
      if (slots.length === 0) {
        card.style.display = 'none';
        return;
      }
      
      card.style.display = 'block';
      
      let html = '';
      slots.forEach(slot => {
        const isTriggered = slot.triggered;
        const isRan = slot.ran !== false; // ran 필드가 없으면 이미 지난 슬롯으로 간주
        const statusClass = isTriggered ? 'ok' : (isRan ? 'skip' : 'wait');
        const statusIcon = isTriggered ? '✅' : (isRan ? '⏭️' : '🕒');
        const statusText = isTriggered ? '트리거됨' : (isRan ? '스킵' : '대기');
        
        const reason = slot.reason || '';
        const countStr = slot.new_candidates ? `(${slot.new_candidates}종목)` : '';
        
        html += `
          <div style="display:flex; flex-direction:column; padding:10px; background:var(--bg2); border-radius:6px; border-left:4px solid ${isTriggered ? 'var(--green)' : 'var(--line)'};">
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <div style="font-weight:700; font-size:13px;">
                <span style="color:var(--muted); margin-right:8px;">${slot.slot}</span>
                <span class="status ${statusClass}" style="font-size:11px; padding:2px 6px;">${statusIcon} ${statusText}</span>
              </div>
              <div style="font-size:12px; font-weight:600;">${countStr}</div>
            </div>
            ${reason ? `<div style="font-size:12px; color:var(--fg); margin-top:4px;">${escapeHtml(reason)}</div>` : ''}
        `;
        
        // Sector Rotation info (Task 2)
        const rotation = rotations.find(r => r.slot === slot.slot);
        if (rotation) {
          const _fmtSector = (s) => (s && typeof s === 'object')
            ? (s.sector + (s.avg_change != null ? ' (' + (s.avg_change > 0 ? '+' : '') + s.avg_change + '%)' : ''))
            : String(s);
          const top = (rotation.top_sectors || []).map(_fmtSector).join(', ');
          const bottom = (rotation.bottom_sectors || []).map(_fmtSector).join(', ');
          html += `
            <div style="margin-top:8px; padding-top:8px; border-top:1px dashed var(--line); font-size:12px;">
              <div style="display:flex; align-items:center; gap:4px; font-weight:600; color:var(--yellow);">
                🔄 섹터 회전 감지 (갭 ${rotation.gap_pct}%)
              </div>
              <div style="color:var(--green); margin-top:2px;">▲ 상위: ${escapeHtml(top)}</div>
              <div style="color:var(--red); margin-top:2px;">▼ 하위: ${escapeHtml(bottom)}</div>
            </div>
          `;
        }
        
        html += `</div>`;
      });
      
      container.innerHTML = html;
    } catch (e) {
      console.warn('Failed to load reselection timeline', e);
      card.style.display = 'none';
    }
  }

  /* Task 3: Load Replacement Signals */
  async function loadReplacementSignals(tradeDate) {
    const card = document.getElementById('tc-replacement-signal-card');
    const container = document.getElementById('tc-replacement-list');
    const countEl = document.getElementById('tc-replacement-count');
    if (!card || !container) return;

    try {
      const url = tradeDate ? '/api/v1/trading-monitor/replacement-signals?trade_date=' + tradeDate : '/api/v1/trading-monitor/replacement-signals';
      const res = await fetchJson(url);
      if (!res.ok || !res.payload) {
        card.style.display = 'none';
        return;
      }
      
      const signals = res.payload.signals || [];
      if (countEl) countEl.textContent = signals.length + '건';
      
      if (signals.length === 0) {
        container.innerHTML = '<div style="color:var(--muted); text-align:center; padding:16px; font-size:13px;">오늘 교체 신호 없음</div>';
        card.style.display = 'block';
        return;
      }
      
      card.style.display = 'block';
      
      let html = '';
      signals.forEach(sig => {
        const scoreGap = sig.score_gap || 0;
        const gapColor = scoreGap >= 20 ? 'var(--green)' : 'var(--yellow)';
        
        html += `
          <details style="background:var(--bg2); border-radius:6px; overflow:hidden;" ${signals.length === 1 ? 'open' : ''}>
            <summary style="padding:10px 12px; cursor:pointer; font-weight:700; font-size:13px; display:flex; justify-content:space-between; align-items:center;">
              <span>▼ ${sig.slot} 신호</span>
              <span style="color:var(--yellow); font-size:11px;">${escapeHtml(sig.new.name)} (${(sig.new.score * 100).toFixed(0)})</span>
            </summary>
            <div style="padding:0 12px 12px; font-size:12px;">
              <div style="display:grid; grid-template-columns:1fr auto 1fr; gap:12px; align-items:center; margin-top:4px; background:var(--panel-2); padding:10px; border-radius:4px;">
                <div>
                  <div style="font-size:10px; color:var(--muted);">보유</div>
                  <div style="font-weight:700;">${escapeHtml(sig.current.name)}</div>
                  <div style="font-size:11px;">점수 ${(sig.current.score * 100).toFixed(0)} / ${sig.current.pnl_pct}%</div>
                </div>
                <div style="font-size:18px;">➔</div>
                <div>
                  <div style="font-size:10px; color:var(--muted);">후보</div>
                  <div style="font-weight:700; color:var(--yellow);">${escapeHtml(sig.new.name)}</div>
                  <div style="font-size:11px;">점수 ${(sig.new.score * 100).toFixed(0)} <span style="color:${gapColor}; font-weight:700;">+${scoreGap}%↑</span></div>
                </div>
              </div>
              <div style="margin-top:8px; color:var(--muted);">
                <strong>사유:</strong> ${escapeHtml(sig.reason)}
              </div>
            </div>
          </details>
        `;
      });
      
      container.innerHTML = html;
    } catch (e) {
      console.warn('Failed to load replacement signals', e);
      card.style.display = 'none';
    }
  }

  /* Task 4: Kill Switch (긴급 비활성화 토글) */
  const KILL_SWITCH_KEYS = [
    { key: "intraday_refresh.master_enabled", label: "전체 활성화 (마스터)", help: "모든 신규 재선별 기능을 일괄 제어" },
    { key: "intraday_refresh.lunch_slots_enabled", label: "점심 슬롯 (13:00 / 14:00)", help: "점심 이후 추가 재선별 슬롯", sub: true },
    { key: "intraday_refresh.sector_rotation_enabled", label: "섹터 회전 감지", help: "섹터 회전 시 재선별 트리거", sub: true },
    { key: "intraday_refresh.replacement_signal_enabled", label: "교체 신호 발생", help: "신규 후보 > 보유 종목 시 신호 발생", sub: true },
  ];

  function _coerceBool(value) {
    if (typeof value === "boolean") return value;
    if (typeof value === "string") return value.toLowerCase() === "true";
    if (typeof value === "number") return value !== 0;
    return Boolean(value);
  }

  async function loadIntradayKillSwitches() {
    const container = document.getElementById("tc-kill-switch-list");
    if (!container) return;

    try {
      const res = await fetchJson("/api/v1/settings");
      if (!res.ok || !res.payload) {
        container.innerHTML = '<div class="muted" style="font-size:12px; text-align:center; padding:8px;">설정을 불러올 수 없습니다 (인증 필요)</div>';
        return;
      }
      const items = (res.payload.items) || [];
      const map = {};
      items.forEach(it => { if (it && it.key) map[it.key] = it; });

      const masterItem = map["intraday_refresh.master_enabled"] || {};
      const masterOn = _coerceBool(masterItem.value !== undefined ? masterItem.value : true);

      let html = "";
      KILL_SWITCH_KEYS.forEach(spec => {
        const item = map[spec.key] || {};
        const value = item.value !== undefined ? item.value : true;
        const isOn = _coerceBool(value);
        const disabled = spec.sub && !masterOn;
        const indent = spec.sub ? "padding-left:20px;" : "";
        const updatedAt = item.updated_at || "";
        const updatedBy = item.updated_by || "";
        const meta = updatedAt ? `<div class="muted" style="font-size:10px; margin-top:2px;">최근 변경: ${escapeHtml(updatedAt)} by ${escapeHtml(updatedBy || "?")}</div>` : "";

        html += `
          <div style="display:flex; align-items:center; justify-content:space-between; ${indent} padding:6px 0; border-bottom:1px dashed var(--line);">
            <div style="flex:1;">
              <div style="font-weight:600; font-size:13px; ${disabled ? 'color:var(--muted);' : ''}">${spec.sub ? "└ " : ""}${escapeHtml(spec.label)}</div>
              <div class="muted" style="font-size:11px;">${escapeHtml(spec.help)}</div>
              ${meta}
            </div>
            <label style="display:inline-flex; align-items:center; cursor:${disabled ? 'not-allowed' : 'pointer'}; gap:6px;">
              <input type="checkbox" data-kskey="${escapeHtml(spec.key)}" data-kshelp="${escapeHtml(spec.help)}" ${isOn ? "checked" : ""} ${disabled ? "disabled" : ""} class="kill-switch-toggle">
              <span style="font-weight:700; font-size:12px; color:${isOn ? 'var(--green)' : 'var(--muted)'};">${isOn ? "ON" : "OFF"}</span>
            </label>
          </div>
        `;
      });

      container.innerHTML = html;

      container.querySelectorAll("input.kill-switch-toggle").forEach(input => {
        input.addEventListener("change", async (ev) => {
          const cb = ev.currentTarget;
          const key = cb.getAttribute("data-kskey");
          const help = cb.getAttribute("data-kshelp") || "";
          const newValue = cb.checked;
          try {
            const post = await fetchJson("/api/v1/settings", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ key, value: newValue, value_type: "bool", description: help }),
            });
            if (post && post.ok) {
              // 마스터 변경 시 sub 상태도 같이 갱신
              loadIntradayKillSwitches();
            } else {
              cb.checked = !newValue;
              alert("설정 변경 실패: " + key);
            }
          } catch (e) {
            cb.checked = !newValue;
            console.warn("Failed to update kill switch", e);
            alert("설정 변경 실패 (네트워크): " + key);
          }
        });
      });
    } catch (e) {
      console.warn("Failed to load kill switches", e);
      container.innerHTML = '<div class="muted" style="font-size:12px; text-align:center; padding:8px;">설정을 불러올 수 없습니다</div>';
    }
  }

  // Export to window
  window.loadIntradayReselectionTimeline = loadIntradayReselectionTimeline;
  window.loadReplacementSignals = loadReplacementSignals;
  window.loadIntradayKillSwitches = loadIntradayKillSwitches;

})();
