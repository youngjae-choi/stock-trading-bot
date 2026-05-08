  // Alert Center 로드
  async function loadAlerts() {
    try {
      const [listRes, summaryRes] = await Promise.all([
        fetch('/api/v1/alerts/'),
        fetch('/api/v1/alerts/summary'),
      ]);
      if (summaryRes.ok) {
        const sum = await summaryRes.json();
        const s = sum.payload || {};
        const setEl = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v ?? '-'; };
        setEl('al-total', s.total);
        setEl('al-critical', s.by_severity?.CRITICAL ?? 0);
        setEl('al-warning', s.by_severity?.WARNING ?? 0);
        setEl('al-unacked', s.unacknowledged);
      }
      if (listRes.ok) {
        const list = await listRes.json();
        const items = list.payload || [];
        const tbody = document.getElementById('al-list-tbody');
        if (!tbody) return;
        if (!items.length) {
          tbody.innerHTML = '<tr><td colspan="7" class="muted" style="text-align:center">알림 없음</td></tr>';
          return;
        }
        tbody.innerHTML = items.map(a => {
          const cls = a.severity === 'CRITICAL' ? 'fail' : a.severity === 'WARNING' ? 'warn' : 'info';
          const ackBtn = !a.acknowledged
            ? `<button class="btn small secondary" data-action="ackAlert" data-id="${escapeHtml(a.id)}">확인</button>`
            : '<span class="muted">확인됨</span>';
          return `<tr>
            <td><span class="status ${cls}">${a.severity}</span></td>
            <td>${a.alert_type}</td>
            <td>${a.title}</td>
            <td class="muted" style="font-size:0.85em">${a.detail || '-'}</td>
            <td>${(a.created_at || '').slice(11, 19)}</td>
            <td>${a.acknowledged ? '확인됨' : '미확인'}</td>
            <td>${ackBtn}</td>
          </tr>`;
        }).join('');
      }
    } catch (e) { console.warn('loadAlerts error', e); }
  }

  async function ackAlert(alertId) {
    try {
      const res = await fetch(`/api/v1/alerts/${alertId}/acknowledge`, { method: 'POST' });
      if (res.ok) { showToast('알림 확인 처리됨'); await loadAlerts(); }
    } catch (e) { showToast('오류: ' + e.message, 'error'); }
  }
