/**
 * Portfolio: Dividend Statistics Screen Logic
 */

async function refreshDividendStats() {
    const year = document.getElementById('divStatsYear').value;
    const grossEl = document.getElementById('divStatGross');
    const taxEl = document.getElementById('divStatTax');
    const netEl = document.getElementById('divStatNet');
    const monthlyTbody = document.getElementById('divStatMonthlyTableBody');
    const accountTbody = document.getElementById('divStatAccountTableBody');

    try {
        const data = await fetchJson(`/api/v1/dividends/stats/summary?year=${year}`);

        if (!data.ok) return;

        // ── 요약 카드 ──────────────────────────────────────────────────
        grossEl.innerText = data.total.gross.toLocaleString();
        taxEl.innerText   = data.total.tax.toLocaleString();
        netEl.innerText   = data.total.net.toLocaleString();

        // ── 일자별 표 ──────────────────────────────────────────────────
        const totalNet = data.total.net || 1;
        const daily = Array.isArray(data.daily) ? data.daily : [];
        if (daily.length === 0) {
            monthlyTbody.innerHTML = '<tr><td colspan="5" class="muted" style="text-align:center;">선택한 연도의 데이터가 없습니다.</td></tr>';
        } else {
            let rows = '';
            let sumGross = 0, sumTax = 0, sumNet = 0;

            daily.forEach(d => {
                const gross = d.total_gross || 0;
                const tax   = d.total_tax   || 0;
                const net   = d.total_net   || 0;
                sumGross += gross; sumTax += tax; sumNet += net;

                const share = net > 0 ? (net / totalNet * 100).toFixed(1) + '%' : '-';
                const netCls = net > 0 ? 'good' : net < 0 ? 'bad' : 'muted';
                // YYYY-MM-DD → MM-DD (연도는 상단 선택값으로 고정)
                const parts = (d.date || '').split('-');
                const dateLabel = parts.length === 3 ? `${parts[1]}-${parts[2]}` : (d.date || '-');

                rows += `<tr>
                    <td style="font-weight:500;">${dateLabel}</td>
                    <td style="text-align:right;">${gross > 0 ? gross.toLocaleString() : '-'}</td>
                    <td style="text-align:right; color:var(--red);">${tax > 0 ? tax.toLocaleString() : '-'}</td>
                    <td style="text-align:right;" class="${netCls}">${net > 0 ? net.toLocaleString() : '-'}</td>
                    <td style="text-align:right; font-size:12px;">${share}</td>
                </tr>`;
            });

            // 합계 행
            rows += `<tr style="border-top:2px solid var(--line); font-weight:600;">
                <td>Total</td>
                <td style="text-align:right;">${sumGross.toLocaleString()}</td>
                <td style="text-align:right; color:var(--red);">${sumTax.toLocaleString()}</td>
                <td style="text-align:right;" class="good">${sumNet.toLocaleString()}</td>
                <td style="text-align:right;">100%</td>
            </tr>`;

            monthlyTbody.innerHTML = rows;
        }

        // ── 계좌별 표 ──────────────────────────────────────────────────
        if (data.by_account.length === 0) {
            accountTbody.innerHTML = '<tr><td colspan="5" class="muted" style="text-align:center;">데이터 없음</td></tr>';
        } else {
            accountTbody.innerHTML = data.by_account.map(acc => `
                <tr>
                    <td>${escapeHtml(acc.bank_name)}</td>
                    <td class="muted" style="font-size:12px;">${escapeHtml(acc.owner_name || '-')}</td>
                    <td class="muted" style="font-size:12px;">${escapeHtml(acc.account_number)}</td>
                    <td style="text-align:right;" class="good">${acc.total_net.toLocaleString()}</td>
                    <td style="text-align:right;">${(acc.total_net / (data.total.net || 1) * 100).toFixed(1)}%</td>
                </tr>
            `).join('');
        }

    } catch (e) {
        if (monthlyTbody) monthlyTbody.innerHTML = `<tr><td colspan="5" class="bad">로드 실패: ${escapeHtml(e.message)}</td></tr>`;
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
