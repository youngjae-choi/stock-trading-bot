/**
 * Portfolio: Dividend Management Screen Logic
 */

let _currentEditAccountId = null;
let _currentEditEntryId = null;

let _dividendAccountsMap = {};
let _dividendHistoryMap = {};
let _dividendStocksMap  = {};

async function refreshDividends() {
    await Promise.all([
        loadDividendStocks(),
        loadDividendAccounts(),
        refreshDividendHistory(),
    ]);
}

// ── Dividend Stocks ──────────────────────────────────────────────────────────

async function loadDividendStocks() {
    const tbody  = document.getElementById('dividendStocksTableBody');
    const select = document.getElementById('divEntryStockId');
    try {
        const data = await fetchJson('/api/v1/dividends/stocks');
        if (!data.ok) return;

        _dividendStocksMap = {};
        data.stocks.forEach(s => _dividendStocksMap[s.id] = s);

        // 종목 목록 테이블
        if (data.stocks.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="muted" style="text-align:center;">종목을 등록해 주세요.</td></tr>';
        } else {
            const today = new Date();
            tbody.innerHTML = data.stocks.map(s => {
                const exDate  = s.next_ex_date ? new Date(s.next_ex_date + 'T00:00:00') : null;
                const delta   = exDate ? Math.round((exDate - today) / 86400000) : null;
                const dday    = delta == null ? '-'
                    : delta < 0  ? `<span class="muted">D+${Math.abs(delta)}</span>`
                    : delta === 0 ? '<span class="bad">D-Day</span>'
                    : delta <= 2  ? `<span class="bad">D-${delta}</span>`
                    : `<span>D-${delta}</span>`;
                const muteBtn = s.notification_muted
                    ? `<button class="btn compact" onclick="unmuteStock('${s.id}')">🔔</button>`
                    : `<button class="btn compact" onclick="muteStock('${s.id}')">🔕</button>`;
                const refreshBtn = `<button class="btn compact" onclick="refreshExDate('${s.id}')" title="배당락일 수정">✏️</button>`;
                return `<tr>
                    <td><input type="checkbox" value="${s.id}"></td>
                    <td><strong>${escapeHtml(s.name)}</strong></td>
                    <td class="muted" style="font-size:12px;">${escapeHtml(s.code)}</td>
                    <td style="font-size:12px;">${s.next_ex_date || '-'}</td>
                    <td>${dday}</td>
                    <td>${muteBtn}</td>
                    <td>${refreshBtn}</td>
                </tr>`;
            }).join('');
        }

        // 배당금 입력 드롭다운
        const currentVal = select ? select.value : '';
        if (select) {
            select.innerHTML = '<option value="">종목 선택 안함</option>'
                + data.stocks.map(s =>
                    `<option value="${s.id}">${escapeHtml(s.name)} (${escapeHtml(s.code)})</option>`
                ).join('');
            select.value = currentVal;
        }
    } catch (e) {
        if (tbody) tbody.innerHTML = `<tr><td colspan="7" class="bad">오류: ${escapeHtml(e.message)}</td></tr>`;
    }
}

document.getElementById('dividendStockForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = e.target.querySelector('button[type="submit"]');
    btn.disabled = true;
    btn.textContent = '등록 중...';
    const exDate = document.getElementById('divStockExDate').value;
    const payload = {
        name: document.getElementById('divStockName').value.trim(),
        code: document.getElementById('divStockCode').value.trim(),
        next_ex_date: exDate || null,
    };
    try {
        const data = await fetchJson('/api/v1/dividends/stocks', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (data.ok) {
            e.target.reset();
            await loadDividendStocks();
        }
    } catch (err) {
        alert('등록 실패: ' + err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = '종목 등록';
    }
});

async function refreshExDate(stockId) {
    const s = _dividendStocksMap[stockId];
    const current = s ? s.next_ex_date || '' : '';
    const input = prompt(`${s ? s.name : ''} 다음 배당락일을 입력하세요 (YYYY-MM-DD):`, current);
    if (!input || input === current) return;
    try {
        const data = await fetchJson(`/api/v1/dividends/stocks/${stockId}/ex-date`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ next_ex_date: input }),
        });
        if (data.ok) {
            showToast('배당락일 업데이트: ' + data.next_ex_date);
            await loadDividendStocks();
        }
    } catch (err) {
        alert('업데이트 실패: ' + err.message);
    }
}

async function muteStock(stockId) {
    try {
        await fetchJson(`/api/v1/dividends/stocks/${stockId}/mute`, { method: 'POST' });
        await loadDividendStocks();
    } catch (err) {
        alert('오류: ' + err.message);
    }
}

async function unmuteStock(stockId) {
    try {
        await fetchJson(`/api/v1/dividends/stocks/${stockId}/unmute`, { method: 'POST' });
        await loadDividendStocks();
    } catch (err) {
        alert('오류: ' + err.message);
    }
}

async function deleteDividendStock() {
    const ids = getSelectedIds('dividendStocksTableBody');
    if (!ids.length) { alert('삭제할 종목을 선택해 주세요.'); return; }
    if (!confirm(`선택한 ${ids.length}개 종목을 삭제할까요?`)) return;
    try {
        await Promise.all(ids.map(id =>
            fetchJson(`/api/v1/dividends/stocks/${id}`, { method: 'DELETE' })
        ));
        await loadDividendStocks();
    } catch (err) {
        alert('삭제 실패: ' + err.message);
    }
}

function toggleSelectAll(tbodyId, checked) {
    const checkboxes = document.querySelectorAll(`#${tbodyId} input[type="checkbox"]`);
    checkboxes.forEach(cb => cb.checked = checked);
}

function getSelectedIds(tbodyId) {
    const checkboxes = document.querySelectorAll(`#${tbodyId} input[type="checkbox"]:checked`);
    return Array.from(checkboxes).map(cb => cb.value);
}

// ── Account CRUD ────────────────────────────────────────────────────────────

async function loadDividendAccounts() {
    const tbody = document.getElementById('dividendAccountsTableBody');
    const select = document.getElementById('divEntryAccId');
    
    try {
        const data = await fetchJson('/api/v1/dividends/accounts');
        
        if (data.ok) {
            _dividendAccountsMap = {};
            data.accounts.forEach(acc => _dividendAccountsMap[acc.id] = acc);

            if (data.accounts.length === 0) {
                tbody.innerHTML = '<tr><td colspan="4" class="muted" style="text-align:center;">등록된 계좌가 없습니다.</td></tr>';
            } else {
                tbody.innerHTML = data.accounts.map(acc => `
                    <tr>
                        <td><input type="checkbox" value="${acc.id}"></td>
                        <td>${escapeHtml(acc.bank_name)}</td>
                        <td>${escapeHtml(acc.account_number)}</td>
                        <td>${escapeHtml(acc.owner_name)}</td>
                    </tr>
                `).join('');
            }
            
            // Update select options
            const currentVal = select.value;
            select.innerHTML = '<option value="">계좌 선택</option>' + data.accounts.map(acc => `
                <option value="${acc.id}">${escapeHtml(acc.bank_name)} - ${escapeHtml(acc.account_number)} (${escapeHtml(acc.owner_name)})</option>
            `).join('');
            select.value = currentVal;
        }
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="4" class="bad">오류: ${escapeHtml(e.message)}</td></tr>`;
    }
}

function handleEditSelectedAccount() {
    const ids = getSelectedIds('dividendAccountsTableBody');
    if (ids.length === 0) {
        alert('수정할 계좌를 선택해 주세요.');
        return;
    }
    if (ids.length > 1) {
        alert('수정은 1개만 선택하여주세요.');
        return;
    }
    const acc = _dividendAccountsMap[ids[0]];
    editDividendAccount(acc.id, acc.bank_name, acc.account_number, acc.owner_name);
}

async function handleBulkDeleteAccounts() {
    const ids = getSelectedIds('dividendAccountsTableBody');
    if (ids.length === 0) {
        alert('삭제할 계좌를 선택해 주세요.');
        return;
    }
    if (!confirm(`정말로 선택한 ${ids.length}개의 계좌를 삭제하시겠습니까? (관련 배당 내역은 숨겨집니다)`)) return;
    
    try {
        const data = await fetchJson('/api/v1/dividends/accounts/bulk-delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ids: ids })
        });
        if (data.ok) {
            loadDividendAccounts();
            refreshDividendHistory();
        }
    } catch (err) {
        alert('삭제 실패: ' + err.message);
    }
}

function editDividendAccount(id, bank, number, owner) {
    _currentEditAccountId = id;
    document.getElementById('divAccBank').value = bank;
    document.getElementById('divAccNumber').value = number;
    document.getElementById('divAccOwner').value = owner;
    
    const btn = document.querySelector('#dividendAccountForm button[type="submit"]');
    btn.textContent = '계좌 수정';
    
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
        }
    } catch (err) {
        alert('서버 통신 오류: ' + err.message);
    }
});

// ── Dividend Entry CRUD ──────────────────────────────────────────────────────

async function refreshDividendHistory() {
    const tbody = document.getElementById('dividendHistoryTableBody');
    try {
        const data = await fetchJson('/api/v1/dividends/history');
        
        if (data.ok) {
            _dividendHistoryMap = {};
            data.history.forEach(row => _dividendHistoryMap[row.id] = row);

            if (data.history.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" class="muted" style="text-align:center;">배당 이력이 없습니다.</td></tr>';
            } else {
                tbody.innerHTML = data.history.map(row => {
                    const rateStr = row.dividend_rate != null ? row.dividend_rate.toFixed(2) + '%' : '-';
                    const stockStr = row.stock_name ? escapeHtml(row.stock_name) : '<span class="muted">-</span>';
                    return `<tr>
                        <td><input type="checkbox" value="${row.id}"></td>
                        <td style="font-size:12px;">${row.dividend_date}</td>
                        <td style="font-size:12px;">${stockStr}</td>
                        <td>${escapeHtml(row.bank_name)}</td>
                        <td class="muted" style="font-size:12px;">${escapeHtml(row.owner_name || '-')}</td>
                        <td class="muted" style="font-size:12px;">${rateStr}</td>
                        <td class="good">${row.net_amount.toLocaleString()}</td>
                    </tr>`;
                }).join('');
            }
        }
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="7" class="bad">오류: ${escapeHtml(e.message)}</td></tr>`;
    }
}

function handleEditSelectedEntry() {
    const ids = getSelectedIds('dividendHistoryTableBody');
    if (ids.length === 0) {
        alert('수정할 배당 내역을 선택해 주세요.');
        return;
    }
    if (ids.length > 1) {
        alert('수정은 1개만 선택하여주세요.');
        return;
    }
    const entry = _dividendHistoryMap[ids[0]];
    editDividendEntry(entry.id, entry.account_id, entry.stock_id, entry.dividend_date, entry.amount, entry.tax, entry.dividend_rate, entry.memo);
}

async function handleBulkDeleteEntries() {
    const ids = getSelectedIds('dividendHistoryTableBody');
    if (ids.length === 0) {
        alert('삭제할 배당 내역을 선택해 주세요.');
        return;
    }
    if (!confirm(`정말로 선택한 ${ids.length}개의 배당 내역을 삭제하시겠습니까?`)) return;
    
    try {
        const data = await fetchJson('/api/v1/dividends/entries/bulk-delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ids: ids })
        });
        if (data.ok) {
            refreshDividendHistory();
        }
    } catch (err) {
        alert('삭제 실패: ' + err.message);
    }
}

function editDividendEntry(id, accountId, stockId, date, amount, tax, dividendRate, memo) {
    _currentEditEntryId = id;
    document.getElementById('divEntryAccId').value = accountId;
    if (stockId) document.getElementById('divEntryStockId').value = stockId;
    document.getElementById('divEntryDate').value = date;
    document.getElementById('divEntryAmount').value = amount;
    document.getElementById('divEntryTax').value = tax;
    document.getElementById('divEntryNet').value = (amount - tax).toFixed(2);
    document.getElementById('divEntryRate').value = dividendRate != null ? dividendRate : '';
    document.getElementById('divEntryMemo').value = memo || '';
    
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
    document.getElementById('divEntryRate').value = '';
    document.querySelector('#dividendEntryForm button[type="submit"]').textContent = '배당금 기록';
    const cancelBtn = document.getElementById('divEntryCancelBtn');
    if (cancelBtn) cancelBtn.remove();
}

document.getElementById('dividendEntryForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const rateVal = document.getElementById('divEntryRate').value;
    const payload = {
        account_id: document.getElementById('divEntryAccId').value,
        dividend_date: document.getElementById('divEntryDate').value,
        amount: parseFloat(document.getElementById('divEntryAmount').value),
        tax: parseFloat(document.getElementById('divEntryTax').value),
        net_amount: parseFloat(document.getElementById('divEntryNet').value),
        dividend_rate: rateVal !== '' ? parseFloat(rateVal) : null,
        memo: document.getElementById('divEntryMemo').value
    };

    const stockId = document.getElementById('divEntryStockId') ? document.getElementById('divEntryStockId').value : '';
    if (stockId) payload.stock_id = stockId;

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
        }
    } catch (err) {
        alert('서버 통신 오류: ' + err.message);
    }
});

// Auto-calculation for Net Amount
['divEntryAmount', 'divEntryTax'].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
        el.addEventListener('input', () => {
            const gross = parseFloat(document.getElementById('divEntryAmount').value) || 0;
            const tax = parseFloat(document.getElementById('divEntryTax').value) || 0;
            document.getElementById('divEntryNet').value = (gross - tax).toFixed(2);
        });
    }
});
