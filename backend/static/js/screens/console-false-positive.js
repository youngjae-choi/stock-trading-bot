  // False Positive
  async function loadFalsePositive() {
    try {
      const res = await fetch('/api/v1/false-positive/today');
      if (!res.ok) return;
      const data = await res.json();
      const items = data.payload || [];
      const tbody = document.getElementById('fp-list-tbody');
      if (!tbody) return;
      if (!items.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="muted" style="text-align:center">미수집</td></tr>';
        return;
      }
      tbody.innerHTML = items.map(f => `<tr>
        <td>${f.symbol_name || f.symbol}</td>
        <td>${f.false_positive_type}</td>
        <td>${f.original_score != null ? f.original_score.toFixed(2) : '-'}</td>
        <td>${f.original_confidence != null ? (f.original_confidence*100).toFixed(1)+'%' : '-'}</td>
        <td class="muted" style="font-size:0.85em">${f.entry_reason || '-'}</td>
        <td class="muted" style="font-size:0.85em">${f.loss_reason || '-'}</td>
      </tr>`).join('');
    } catch (e) { console.warn('loadFalsePositive error', e); }
  }
