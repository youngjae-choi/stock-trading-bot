/**
 * Portfolio: Dividend Statistics Screen Logic
 */

async function refreshDividendStats() {
    const year = document.getElementById('divStatsYear').value;
    const grossEl = document.getElementById('divStatGross');
    const taxEl = document.getElementById('divStatTax');
    const netEl = document.getElementById('divStatNet');
    const chartContainer = document.getElementById('dividendMonthlyChartContainer');
    const accountTbody = document.getElementById('divStatAccountTableBody');

    try {
        const data = await fetchJson(`/api/v1/dividends/stats/summary?year=${year}`);

        if (data.ok) {
            // Update Summary Cards
            grossEl.innerText = data.total.gross.toLocaleString();
            taxEl.innerText = data.total.tax.toLocaleString();
            netEl.innerText = data.total.net.toLocaleString();

            // Render Monthly Chart (CSS Bar Chart)
            if (data.monthly.length === 0) {
                chartContainer.innerHTML = '<div class="muted" style="width:100%; text-align:center;">선택한 연도의 데이터가 없습니다.</div>';
            } else {
                const maxVal = Math.max(...data.monthly.map(m => m.total_net), 1);
                chartContainer.innerHTML = Array.from({length: 12}, (_, i) => {
                    const monthStr = (i + 1).toString().padStart(2, '0');
                    const monthData = data.monthly.find(m => m.month === monthStr);
                    const val = monthData ? monthData.total_net : 0;
                    const heightPct = (val / maxVal * 100).toFixed(0);
                    
                    return `
                        <div style="flex: 1; display: flex; flex-direction: column; align-items: center; height: 100%; justify-content: flex-end;">
                            <div class="good" style="width: 80%; height: ${heightPct}%; background: var(--good); border-radius: 4px 4px 0 0; min-height: ${val > 0 ? '2px' : '0'};" title="${val.toLocaleString()}"></div>
                            <div style="font-size: 10px; margin-top: 5px;">${i + 1}월</div>
                        </div>
                    `;
                }).join('');
            }

            // Update Account Table
            if (data.by_account.length === 0) {
                accountTbody.innerHTML = '<tr><td colspan="4" class="muted" style="text-align:center;">데이터 없음</td></tr>';
            } else {
                const totalNet = data.total.net || 1;
                accountTbody.innerHTML = data.by_account.map(acc => `
                    <tr>
                        <td>${escapeHtml(acc.bank_name)}</td>
                        <td class="muted" style="font-size:12px;">${escapeHtml(acc.account_number)}</td>
                        <td class="good">${acc.total_net.toLocaleString()}</td>
                        <td>${(acc.total_net / totalNet * 100).toFixed(1)}%</td>
                    </tr>
                `).join('');
            }
        }
    } catch (e) {
        chartContainer.innerHTML = `<div class="bad">통계 로드 실패: ${escapeHtml(e.message)}</div>`;
    }
}

// Initial year population
(function() {
    const currentYear = new Date().getFullYear();
    const select = document.getElementById('divStatsYear');
    select.innerHTML = [0, 1, 2].map(offset => `
        <option value="${currentYear - offset}">${currentYear - offset}년</option>
    `).join('');
})();
