  // Approval Queue 로드
  async function loadApprovalQueue() {
    try {
      const res = await fetch('/api/v1/approval/');
      if (!res.ok) return;
      const data = await res.json();
      const items = data.payload || [];
      const tbody = document.getElementById('aq-list-tbody');
      if (!tbody) return;
      if (!items.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="muted" style="text-align:center">승인 요청 없음</td></tr>';
        return;
      }
      tbody.innerHTML = items.map(r => {
        const cls = r.status === 'pending' ? 'warn' : r.status === 'approved' ? 'ok' : 'fail';
        const btns = r.status === 'pending'
          ? `<button class="btn small secondary" data-action="approveRequest" data-id="${escapeHtml(r.id)}">승인</button>
             <button class="btn small" data-action="rejectRequest" data-id="${escapeHtml(r.id)}">거부</button>
             <button class="btn small" data-action="deferRequest" data-id="${escapeHtml(r.id)}">보류</button>`
          : `<span class="muted">${r.status}</span>`;
        return `<tr>
          <td>${r.change_type}</td>
          <td>${r.title}</td>
          <td class="muted" style="font-size:0.85em">${r.description || '-'}</td>
          <td><span class="status ${cls}">${r.status}</span></td>
          <td>${(r.created_at || '').slice(0, 10)}</td>
          <td>${btns}</td>
        </tr>`;
      }).join('');
    } catch (e) { console.warn('loadApprovalQueue error', e); }
  }

  async function approveRequest(id) {
    const res = await fetch(`/api/v1/approval/${id}/approve`, { method: 'POST' });
    if (res.ok) { showToast('승인 완료'); await loadApprovalQueue(); }
  }
  async function rejectRequest(id) {
    const res = await fetch(`/api/v1/approval/${id}/reject`, { method: 'POST' });
    if (res.ok) { showToast('거부 완료'); await loadApprovalQueue(); }
  }
  async function deferRequest(id) {
    const res = await fetch(`/api/v1/approval/${id}/defer`, { method: 'POST' });
    if (res.ok) { showToast('보류 처리됨'); await loadApprovalQueue(); }
  }
