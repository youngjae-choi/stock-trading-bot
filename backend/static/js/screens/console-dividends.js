/**
 * Portfolio: Dividend Management Screen Logic
 */

async function refreshDividends() {
    await Promise.all([
        loadDividendAccounts(),
        refreshDividendHistory()
    ]);
}

async function loadDividendAccounts() {
    const tbody = document.getElementById('dividendAccountsTableBody');
    const select = document.getElementById('divEntryAccId');
    
    try {
        const resp = await authFetch('/api/v1/dividends/accounts');
        const data = await resp.json();
        
        if (data.ok) {
            // Update table
            if (data.accounts.length === 0) {
                tbody.innerHTML = '<tr><td colspan="3" class="muted" style="text-align:center;">등록된 계좌가 없습니다.</td></tr>';
            } else {
                tbody.innerHTML = data.accounts.map(acc => `
                    <tr>
                        <td>${escapeHtml(acc.bank_name)}</td>
                        <td>${escapeHtml(acc.account_number)}</td>
                        <td>${escapeHtml(acc.owner_name)}</td>
                    </tr>
                `).join('');
            }
            
            // Update select options
            const currentVal = select.value;
            select.innerHTML = '<option value="">계좌 선택</option>' + data.accounts.map(acc => `
                <option value="${acc.id}">${escapeHtml(acc.bank_name)} (${escapeHtml(acc.account_number)})</option>
            `).join('');
            select.value = currentVal;
        }
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="3" class="bad">오류: ${escapeHtml(e.message)}</td></tr>`;
    }
}

async function refreshDividendHistory() {
    const tbody = document.getElementById('dividendHistoryTableBody');
    try {
        const resp = await authFetch('/api/v1/dividends/history');
        const data = await resp.json();
        
        if (data.ok) {
            if (data.history.length === 0) {
                tbody.innerHTML = '<tr><td colspan="4" class="muted" style="text-align:center;">배당 이력이 없습니다.</td></tr>';
            } else {
                tbody.innerHTML = data.history.map(row => `
                    <tr>
                        <td>${row.dividend_date}</td>
                        <td>${escapeHtml(row.bank_name)}</td>
                        <td class="good">${row.net_amount.toLocaleString()}</td>
                        <td class="muted" style="font-size:12px;">${escapeHtml(row.memo || '-')}</td>
                    </tr>
                `).join('');
            }
        }
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="4" class="bad">오류: ${escapeHtml(e.message)}</td></tr>`;
    }
}

// Event Listeners for Forms
document.getElementById('dividendAccountForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
        bank_name: document.getElementById('divAccBank').value,
        account_number: document.getElementById('divAccNumber').value,
        owner_name: document.getElementById('divAccOwner').value
    };
    
    try {
        const resp = await authFetch('/api/v1/dividends/accounts', {
            method: 'POST',
            body: JSON.stringify(payload)
        });
        const data = await resp.json();
        if (data.ok) {
            alert('계좌가 등록되었습니다.');
            e.target.reset();
            loadDividendAccounts();
        } else {
            alert('등록 실패: ' + (data.detail || '알 수 없는 오류'));
        }
    } catch (err) {
        alert('서버 통신 오류: ' + err.message);
    }
});

document.getElementById('dividendEntryForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
        account_id: document.getElementById('divEntryAccId').value,
        dividend_date: document.getElementById('divEntryDate').value,
        amount: parseFloat(document.getElementById('divEntryAmount').value),
        tax: parseFloat(document.getElementById('divEntryTax').value),
        net_amount: parseFloat(document.getElementById('divEntryNet').value),
        memo: document.getElementById('divEntryMemo').value
    };
    
    try {
        const resp = await authFetch('/api/v1/dividends/entries', {
            method: 'POST',
            body: JSON.stringify(payload)
        });
        const data = await resp.json();
        if (data.ok) {
            alert('배당 내역이 저장되었습니다.');
            e.target.reset();
            // Reset net calculation
            document.getElementById('divEntryNet').value = 0;
            refreshDividendHistory();
        } else {
            alert('저장 실패: ' + (data.detail || '알 수 없는 오류'));
        }
    } catch (err) {
        alert('서버 통신 오류: ' + err.message);
    }
});

// Auto-calculation for Net Amount
['divEntryAmount', 'divEntryTax'].forEach(id => {
    document.getElementById(id).addEventListener('input', () => {
        const gross = parseFloat(document.getElementById('divEntryAmount').value) || 0;
        const tax = parseFloat(document.getElementById('divEntryTax').value) || 0;
        document.getElementById('divEntryNet').value = (gross - tax).toFixed(2);
    });
});
