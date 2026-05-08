  // Confidence Calibration
  async function loadConfidenceCalibration() {
    try {
      const res = await fetch('/api/v1/confidence-calibration/today');
      if (!res.ok) return;
      const data = await res.json();
      const items = data.payload || [];
      const tbody = document.getElementById('cc-list-tbody');
      if (!tbody) return;
      if (!items.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="muted" style="text-align:center">데이터 없음 (실행 버튼 클릭)</td></tr>';
        return;
      }
      tbody.innerHTML = items.map(c => `<tr>
        <td>${c.bin_label}</td>
        <td>${c.trade_count}</td>
        <td style="color:${(c.actual_win_rate||0)>=(c.expected_win_rate||0)?'#3fb950':'#f85149'}">${c.actual_win_rate != null ? (c.actual_win_rate*100).toFixed(1)+'%' : '-'}</td>
        <td>${c.expected_win_rate != null ? (c.expected_win_rate*100).toFixed(1)+'%' : '-'}</td>
        <td style="color:${(c.avg_pnl||0)>=0?'#3fb950':'#f85149'}">${c.avg_pnl != null ? c.avg_pnl.toFixed(2)+'%' : '-'}</td>
      </tr>`).join('');
    } catch (e) { console.warn('loadConfidenceCalibration error', e); }
  }

  async function runConfidenceCalibration() {
    try {
      const res = await fetch('/api/v1/confidence-calibration/run', { method: 'POST' });
      if (res.ok) { showToast('캘리브레이션 완료'); await loadConfidenceCalibration(); }
      else showToast('실행 실패', 'error');
    } catch (e) { showToast('오류: ' + e.message, 'error'); }
  }
