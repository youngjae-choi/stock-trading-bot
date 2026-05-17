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

            // Render Monthly Chart — SVG
            if (data.monthly.length === 0) {
                chartContainer.innerHTML = '<div class="muted" style="width:100%;text-align:center;padding:60px 0;">선택한 연도의 데이터가 없습니다.</div>';
            } else {
                const isDark = document.body.classList.contains('dark') || !document.body.classList.contains('light');
                const BAR_COLOR = isDark ? '#35b779' : '#188a58';   // --green light/dark
                const LABEL_COLOR = isDark ? '#8b949e' : '#6e7681'; // --muted

                const W = 560, H = 200, PAD_T = 32, PAD_B = 24, BAR_GAP = 8;
                const barW = Math.floor((W - BAR_GAP * 13) / 12);
                const barAreaH = H - PAD_T - PAD_B;
                const maxVal = Math.max(...data.monthly.map(m => m.total_net), 1);
                const totalNet = data.monthly.reduce((s, m) => s + m.total_net, 0);
                const totalKw = Math.round(totalNet / 1000).toLocaleString();

                // 상단 합계
                const header = `<text x="${W / 2}" y="16" text-anchor="middle" font-size="12" font-weight="600" fill="${BAR_COLOR}">합계 ${totalKw}천원</text>`;

                let bars = '', labels = '', valLabels = '';
                for (let i = 0; i < 12; i++) {
                    const monthStr = (i + 1).toString().padStart(2, '0');
                    const monthData = data.monthly.find(m => m.month === monthStr);
                    const val = monthData ? monthData.total_net : 0;
                    const barH = val > 0 ? Math.max(Math.round(val / maxVal * barAreaH), 4) : 0;
                    const x = BAR_GAP + i * (barW + BAR_GAP);
                    const y = PAD_T + barAreaH - barH;
                    const cx = x + barW / 2;
                    if (barH > 0) {
                        bars += `<rect x="${x}" y="${y}" width="${barW}" height="${barH}" rx="3" fill="${BAR_COLOR}" opacity="0.85"><title>${Math.round(val / 1000).toLocaleString()}천원</title></rect>`;
                        // 막대 위 금액 (값이 충분히 클 때만)
                        if (barH >= 18) {
                            valLabels += `<text x="${cx}" y="${y - 3}" text-anchor="middle" font-size="9" fill="${BAR_COLOR}">${Math.round(val / 1000)}k</text>`;
                        }
                    }
                    labels += `<text x="${cx}" y="${H - 5}" text-anchor="middle" font-size="10" fill="${LABEL_COLOR}">${i + 1}월</text>`;
                }
                chartContainer.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" xmlns="http://www.w3.org/2000/svg">${header}${bars}${valLabels}${labels}</svg>`;
            }

            // Update Account Table
            if (data.by_account.length === 0) {
                accountTbody.innerHTML = '<tr><td colspan="5" class="muted" style="text-align:center;">데이터 없음</td></tr>';
            } else {
                const totalNet = data.total.net || 1;
                accountTbody.innerHTML = data.by_account.map(acc => `
                    <tr>
                        <td>${escapeHtml(acc.bank_name)}</td>
                        <td class="muted" style="font-size:12px;">${escapeHtml(acc.owner_name || '-')}</td>
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
