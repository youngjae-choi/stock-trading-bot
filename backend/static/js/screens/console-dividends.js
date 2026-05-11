/**
 * Portfolio: Dividend Management Screen Logic
 */

let _currentEditAccountId = null;
let _currentEditEntryId = null;

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
        const data = await fetchJson('/api/v1/dividends/accounts');
        
        if (data.ok) {
            // Update table
            if (data.accounts.length === 0) {
                tbody.innerHTML = '<tr><td colspan="4" class="muted" style="text-align:center;">등록된 계좌가 없습니다.</td></tr>';
            } else {
                tbody.innerHTML = data.accounts.map(acc => `
                    <tr>
                        <td>${escapeHtml(acc.bank_name)}</td>
                        <td>${escapeHtml(acc.account_number)}</td>
                        <td>${escapeHtml(acc.owner_name)}</td>
                        <td class="action-cell">
                            <button class="action-btn" title="수정" onclick="editDividendAccount('${acc.id}', '${escapeJs(acc.bank_name)}', '${escapeJs(acc.account_number)}', '${escapeJs(acc.owner_name)}')">✎ 수정</button>
                            <button class="action-btn danger" title="삭제" onclick="deleteDividendAccount('${acc.id}')">✕ 삭제</button>
                        </td>
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
        tbody.innerHTML = `<tr><td colspan="4" class="bad">오류: ${escapeHtml(e.message)}</td></tr>`;
    }
}

async function refreshDividendHistory() {
    const tbody = document.getElementById('dividendHistoryTableBody');
    try {
        const data = await fetchJson('/api/v1/dividends/history');
        
        if (data.ok) {
            if (data.history.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" class="muted" style="text-align:center;">배당 이력이 없습니다.</td></tr>';
            } else {
                tbody.innerHTML = data.history.map(row => `
                    <tr>
                        <td style="font-size:12px;">${row.dividend_date}</td>
                        <td>${escapeHtml(row.bank_name)}</td>
                        <td class="good">${row.net_amount.toLocaleString()}</td>
                        <td class="muted" style="font-size:12px; max-width:120px; overflow:hidden; text-overflow:ellipsis;">${escapeHtml(row.memo || '-')}</td>
                        <td class="action-cell">
                            <button class="action-btn" title="수정" onclick="editDividendEntry('${row.id}', '${row.account_id}', '${row.dividend_date}', ${row.amount}, ${row.tax}, '${escapeJs(row.memo)}')">✎ 수정</button>
                            <button class="action-btn danger" title="삭제" onclick="deleteDividendEntry('${row.id}')">✕ 삭제</button>
                        </td>
                    </tr>
                `).join('');
            }
        }
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="5" class="bad">오류: ${escapeHtml(e.message)}</td></tr>`;
    }
}

function escapeJs(str) {
    return (str || '').replace(/'/g, "\\'").replace(/"/g, '\\"');
}

// ── Account CRUD ────────────────────────────────────────────────────────────

document.getElementById('dividendAccountForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
        bank_name: document.getElementById('divAccBank').value,
        account_number: document.getElementById('divAccNumber').value,
        owner_name: document.getElementById('divAccOwner').value
    };
    
    const isEdit = !!_currentEditAccountId;
    const url = isEdit ? `/api/v1/dividends/accounts/${_currentEditAccountId}` : '/api/v1/dividends/accounts';
    const method = isEdit ? 'PUT' : 'POST';

    try {
        const data = await fetchJson(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (data.ok) {
            alert(isEdit ? '계좌 정보가 수정되었습니다.' : '계좌가 등록되었습니다.');
            cancelAccountEdit();
            loadDividendAccounts();
        } else {
            alert('작업 실패: ' + (data.detail || '알 수 없는 오류'));
        }
    } catch (err) {
        alert('서버 통신 오류: ' + err.message);
    }
});

function editDividendAccount(id, bank, number, owner) {
    _currentEditAccountId = id;
    document.getElementById('divAccBank').value = bank;
    document.getElementById('divAccNumber').value = number;
    document.getElementById('divAccOwner').value = owner;
    
    const btn = document.querySelector('#dividendAccountForm button[type="submit"]');
    btn.textContent = '계좌 수정';
    
    // Add cancel button if not exists
    if (!document.getElementById('divAccCancelBtn')) {
        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.id = 'divAccCancelBtn';
        cancelBtn.className = 'btn';
        cancelBtn.style.width = '100%';
        cancelBtn.style.marginTop = '8px';
        cancelBtn.textContent = '수정 취소';
        cancelBtn.onclick = cancelAccountEdit;
        document.getElementById('dividendAccountForm').appendChild(cancelBtn);
    }
}

function cancelAccountEdit() {
    _currentEditAccountId = null;
    document.getElementById('dividendAccountForm').reset();
    document.querySelector('#dividendAccountForm button[type="submit"]').textContent = '계좌 등록';
    const cancelBtn = document.getElementById('divAccCancelBtn');
    if (cancelBtn) cancelBtn.remove();
}

async function deleteDividendAccount(id) {
    if (!confirm('정말로 이 계좌를 삭제하시겠습니까? (이 계좌의 배당 내역은 숨겨집니다)')) return;
    try {
        const data = await fetchJson(`/api/v1/dividends/accounts/${id}`, { method: 'DELETE' });
        if (data.ok) {
            loadDividendAccounts();
            refreshDividendHistory();
        }
    } catch (err) {
        alert('삭제 실패: ' + err.message);
    }
}

// ── Dividend Entry CRUD ──────────────────────────────────────────────────────

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
    
    const isEdit = !!_currentEditEntryId;
    const url = isEdit ? `/api/v1/dividends/entries/${_currentEditEntryId}` : '/api/v1/dividends/entries';
    const method = isEdit ? 'PUT' : 'POST';

    try {
        const data = await fetchJson(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (data.ok) {
            alert(isEdit ? '배당 내역이 수정되었습니다.' : '배당 내역이 저장되었습니다.');
            cancelEntryEdit();
            refreshDividendHistory();
        } else {
            alert('작업 실패: ' + (data.detail || '알 수 없는 오류'));
        }
    } catch (err) {
        alert('서버 통신 오류: ' + err.message);
    }
});

function editDividendEntry(id, accountId, date, amount, tax, memo) {
    _currentEditEntryId = id;
    document.getElementById('divEntryAccId').value = accountId;
    document.getElementById('divEntryDate').value = date;
    document.getElementById('divEntryAmount').value = amount;
    document.getElementById('divEntryTax').value = tax;
    document.getElementById('divEntryNet').value = (amount - tax).toFixed(2);
    document.getElementById('divEntryMemo').value = memo === 'null' ? '' : memo;
    
    const btn = document.querySelector('#dividendEntryForm button[type="submit"]');
    btn.textContent = '기록 수정';
    
    if (!document.getElementById('divEntryCancelBtn')) {
        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.id = 'divEntryCancelBtn';
        cancelBtn.className = 'btn';
        cancelBtn.style.width = '100%';
        cancelBtn.style.marginTop = '8px';
        cancelBtn.textContent = '수정 취소';
        cancelBtn.onclick = cancelEntryEdit;
        document.getElementById('dividendEntryForm').appendChild(cancelBtn);
    }
}

function cancelEntryEdit() {
    _currentEditEntryId = null;
    document.getElementById('dividendEntryForm').reset();
    document.getElementById('divEntryNet').value = 0;
    document.querySelector('#dividendEntryForm button[type="submit"]').textContent = '배당금 기록';
    const cancelBtn = document.getElementById('divEntryCancelBtn');
    if (cancelBtn) cancelBtn.remove();
}

async function deleteDividendEntry(id) {
    if (!confirm('정말로 이 배당 내역을 삭제하시겠습니까?')) return;
    try {
        const data = await fetchJson(`/api/v1/dividends/entries/${id}`, { method: 'DELETE' });
        if (data.ok) {
            refreshDividendHistory();
        }
    } catch (err) {
        alert('삭제 실패: ' + err.message);
    }
}

// Auto-calculation for Net Amount
['divEntryAmount', 'divEntryTax'].forEach(id => {
    document.getElementById(id).addEventListener('input', () => {
        const gross = parseFloat(document.getElementById('divEntryAmount').value) || 0;
        const tax = parseFloat(document.getElementById('divEntryTax').value) || 0;
        document.getElementById('divEntryNet').value = (gross - tax).toFixed(2);
    });
});
