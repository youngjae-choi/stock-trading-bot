/**
 * Portfolio: Dividend Management Screen Logic
 * 2026-05-24: 모달 방식으로 전환 (등록/수정 폼 카드 제거)
 * 2026-05-25: 카드 순서 변경 (이력 최상단), 페이지네이션 추가
 */

const DIV_PAGE_SIZE = 10;

let _currentEditAccountId = null;
let _currentEditEntryId   = null;
let _dividendAccountsMap  = {};
let _dividendHistoryMap   = {};
let _dividendStocksMap    = {};
let _divModalType = null;   // 'account' | 'stock' | 'entry'
let _divModalMode = null;   // 'add' | 'edit'

// 페이지 상태
let _divPages = { history: 1, stocks: 1, accounts: 1 };
// 전체 데이터 캐시 (페이지네이션용)
let _divAllHistory  = [];
let _divAllStocks   = [];
let _divAllAccounts = [];

// ── 페이지네이션 헬퍼 ────────────────────────────────────────────────────────

function divPagePrev(type) {
  if (_divPages[type] > 1) { _divPages[type]--; _divRenderPage(type); }
}
function divPageNext(type) {
  const all = type === 'history' ? _divAllHistory : type === 'stocks' ? _divAllStocks : _divAllAccounts;
  const maxPage = Math.max(1, Math.ceil(all.length / DIV_PAGE_SIZE));
  if (_divPages[type] < maxPage) { _divPages[type]++; _divRenderPage(type); }
}

function _divUpdatePager(type, total) {
  const page    = _divPages[type];
  const maxPage = Math.max(1, Math.ceil(total / DIV_PAGE_SIZE));
  const map = {
    history:  { info: 'divHistoryPageInfo',  prev: 'divHistoryPrev',  next: 'divHistoryNext'  },
    stocks:   { info: 'divStocksPageInfo',   prev: 'divStocksPrev',   next: 'divStocksNext'   },
    accounts: { info: 'divAccountsPageInfo', prev: 'divAccountsPrev', next: 'divAccountsNext' },
  };
  const ids = map[type];
  const infoEl = document.getElementById(ids.info);
  const prevEl = document.getElementById(ids.prev);
  const nextEl = document.getElementById(ids.next);
  if (infoEl) infoEl.textContent = total > 0 ? `${page} / ${maxPage}` : '';
  if (prevEl) prevEl.disabled = page <= 1;
  if (nextEl) nextEl.disabled = page >= maxPage;
}

function _divRenderPage(type) {
  const page  = _divPages[type];
  const start = (page - 1) * DIV_PAGE_SIZE;
  const end   = start + DIV_PAGE_SIZE;

  if (type === 'history') {
    const slice = _divAllHistory.slice(start, end);
    const tbody = document.getElementById('dividendHistoryTableBody');
    if (!tbody) return;
    if (slice.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" class="muted" style="text-align:center;">배당 이력이 없습니다.</td></tr>';
    } else {
      tbody.innerHTML = slice.map(row => {
        const rateStr  = row.dividend_rate != null ? row.dividend_rate.toFixed(2) + '%' : '-';
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
    _divUpdatePager('history', _divAllHistory.length);

  } else if (type === 'stocks') {
    const slice = _divAllStocks.slice(start, end);
    const tbody = document.getElementById('dividendStocksTableBody');
    if (!tbody) return;
    const today = new Date();
    if (slice.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" class="muted" style="text-align:center;">종목을 등록해 주세요.</td></tr>';
    } else {
      tbody.innerHTML = slice.map(s => {
        const exDate = s.next_ex_date ? new Date(s.next_ex_date + 'T00:00:00') : null;
        const delta  = exDate ? Math.round((exDate - today) / 86400000) : null;
        const dday   = delta == null ? '-'
          : delta < 0   ? `<span class="muted">D+${Math.abs(delta)}</span>`
          : delta === 0 ? '<span class="bad">D-Day</span>'
          : delta <= 2  ? `<span class="bad">D-${delta}</span>`
          : `<span>D-${delta}</span>`;
        const muteBtn = s.notification_muted
          ? `<button class="btn compact" onclick="unmuteStock('${s.id}')">🔔</button>`
          : `<button class="btn compact" onclick="muteStock('${s.id}')">🔕</button>`;
        const editBtn = `<button class="btn compact" onclick="openDivModal('stock','edit',_dividendStocksMap['${s.id}'])" title="수정">✏️</button>`;
        return `<tr>
          <td><input type="checkbox" value="${s.id}"></td>
          <td><strong>${escapeHtml(s.name)}</strong></td>
          <td class="muted" style="font-size:12px;">${escapeHtml(s.code)}</td>
          <td style="font-size:12px;">${s.next_ex_date || '-'}</td>
          <td>${dday}</td>
          <td>${muteBtn}</td>
          <td>${editBtn}</td>
        </tr>`;
      }).join('');
    }
    _divUpdatePager('stocks', _divAllStocks.length);

  } else if (type === 'accounts') {
    const slice = _divAllAccounts.slice(start, end);
    const tbody = document.getElementById('dividendAccountsTableBody');
    if (!tbody) return;
    if (slice.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" class="muted" style="text-align:center;">등록된 계좌가 없습니다.</td></tr>';
    } else {
      tbody.innerHTML = slice.map(acc => `
        <tr>
          <td><input type="checkbox" value="${acc.id}"></td>
          <td>${escapeHtml(acc.bank_name)}</td>
          <td>${escapeHtml(acc.account_number)}</td>
          <td>${escapeHtml(acc.owner_name)}</td>
        </tr>
      `).join('');
    }
    _divUpdatePager('accounts', _divAllAccounts.length);
  }
}

// ── 모달 열기/닫기 ────────────────────────────────────────────────────────────

function openDivModal(type, mode, data) {
  _divModalType = type;
  _divModalMode = mode;
  const modal = document.getElementById('divModal');
  if (!modal) return;

  // 모든 폼 숨기기
  ['divModalAccountForm','divModalStockForm','divModalEntryForm'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  });

  const titleEl = document.getElementById('divModalTitle');
  const labels = { account: '계좌', stock: '종목', entry: '배당금' };
  const label = labels[type] || '';
  if (titleEl) titleEl.textContent = mode === 'edit' ? `${label} 수정` : `${label} 등록`;

  if (type === 'account') {
    const f = document.getElementById('divModalAccountForm');
    if (f) f.style.display = 'block';
    document.getElementById('divAccEditId').value = '';
    document.getElementById('divAccSubmitBtn').textContent = mode === 'edit' ? '수정' : '등록';
    if (mode === 'edit' && data) {
      document.getElementById('divAccBank').value   = data.bank_name || '';
      document.getElementById('divAccNumber').value = data.account_number || '';
      document.getElementById('divAccOwner').value  = data.owner_name || '';
      document.getElementById('divAccEditId').value = data.id || '';
    } else {
      document.getElementById('divAccBank').value   = '';
      document.getElementById('divAccNumber').value = '';
      document.getElementById('divAccOwner').value  = '';
    }

  } else if (type === 'stock') {
    const f = document.getElementById('divModalStockForm');
    if (f) f.style.display = 'block';
    document.getElementById('divStockEditId').value = '';
    document.getElementById('divStockSubmitBtn').textContent = mode === 'edit' ? '수정' : '등록';
    if (mode === 'edit' && data) {
      document.getElementById('divStockName').value   = data.name || '';
      document.getElementById('divStockCode').value   = data.code || '';
      document.getElementById('divStockExDate').value = data.next_ex_date || '';
      document.getElementById('divStockEditId').value = data.id || '';
    } else {
      document.getElementById('divStockName').value   = '';
      document.getElementById('divStockCode').value   = '';
      document.getElementById('divStockExDate').value = '';
    }

  } else if (type === 'entry') {
    const f = document.getElementById('divModalEntryForm');
    if (f) f.style.display = 'block';
    document.getElementById('divEntryEditId').value = '';
    document.getElementById('divEntrySubmitBtn').textContent = mode === 'edit' ? '수정' : '등록';
    if (mode === 'edit' && data) {
      document.getElementById('divEntryAccId').value    = data.account_id || '';
      document.getElementById('divEntryStockId').value  = data.stock_id || '';
      document.getElementById('divEntryDate').value     = data.dividend_date || '';
      document.getElementById('divEntryAmount').value   = data.amount || 0;
      document.getElementById('divEntryTax').value      = data.tax || 0;
      document.getElementById('divEntryNet').value      = ((data.amount || 0) - (data.tax || 0)).toFixed(2);
      document.getElementById('divEntryRate').value     = data.dividend_rate != null ? data.dividend_rate : '';
      document.getElementById('divEntryMemo').value     = data.memo || '';
      document.getElementById('divEntryEditId').value   = data.id || '';
    } else {
      document.getElementById('divEntryAccId').value   = '';
      document.getElementById('divEntryStockId').value = '';
      document.getElementById('divEntryDate').value    = '';
      document.getElementById('divEntryAmount').value  = 0;
      document.getElementById('divEntryTax').value     = 0;
      document.getElementById('divEntryNet').value     = 0;
      document.getElementById('divEntryRate').value    = '';
      document.getElementById('divEntryMemo').value    = '';
    }
  }

  modal.style.display = 'flex';
}

function closeDivModal() {
  const modal = document.getElementById('divModal');
  if (modal) modal.style.display = 'none';
  _divModalType = null;
  _divModalMode = null;
}

// 모달 바깥 클릭 시 닫기
document.addEventListener('click', function(e) {
  const modal = document.getElementById('divModal');
  if (modal && e.target === modal) closeDivModal();
});

// ── 모달 제출 ─────────────────────────────────────────────────────────────────

async function submitDivModal(e, type) {
  e.preventDefault();
  const isEdit = _divModalMode === 'edit';

  if (type === 'account') {
    const editId = document.getElementById('divAccEditId').value;
    const payload = {
      bank_name:      document.getElementById('divAccBank').value.trim(),
      account_number: document.getElementById('divAccNumber').value.trim(),
      owner_name:     document.getElementById('divAccOwner').value.trim(),
    };
    const url    = isEdit ? `/api/v1/dividends/accounts/${editId}` : '/api/v1/dividends/accounts';
    const method = isEdit ? 'PUT' : 'POST';
    try {
      const btn = document.getElementById('divAccSubmitBtn');
      btn.disabled = true; btn.textContent = '저장 중...';
      const data = await fetchJson(url, { method, headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
      if (data.ok) {
        showToast(isEdit ? '계좌가 수정되었습니다.' : '계좌가 등록되었습니다.');
        closeDivModal();
        await loadDividendAccounts();
      }
    } catch (err) { alert('오류: ' + err.message); }
    finally {
      const btn = document.getElementById('divAccSubmitBtn');
      if (btn) { btn.disabled = false; btn.textContent = isEdit ? '수정' : '등록'; }
    }

  } else if (type === 'stock') {
    const editId = document.getElementById('divStockEditId').value;
    const exDate = document.getElementById('divStockExDate').value;
    const payload = {
      name: document.getElementById('divStockName').value.trim(),
      code: document.getElementById('divStockCode').value.trim(),
      next_ex_date: exDate || null,
    };
    const url    = isEdit ? `/api/v1/dividends/stocks/${editId}` : '/api/v1/dividends/stocks';
    const method = isEdit ? 'PUT' : 'POST';
    try {
      const btn = document.getElementById('divStockSubmitBtn');
      btn.disabled = true; btn.textContent = '저장 중...';
      const data = await fetchJson(url, { method, headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
      if (data.ok) {
        showToast(isEdit ? '종목이 수정되었습니다.' : '종목이 등록되었습니다.');
        closeDivModal();
        await loadDividendStocks();
      }
    } catch (err) { alert('오류: ' + err.message); }
    finally {
      const btn = document.getElementById('divStockSubmitBtn');
      if (btn) { btn.disabled = false; btn.textContent = isEdit ? '수정' : '등록'; }
    }

  } else if (type === 'entry') {
    const editId  = document.getElementById('divEntryEditId').value;
    const rateVal = document.getElementById('divEntryRate').value;
    const stockId = document.getElementById('divEntryStockId').value;
    const payload = {
      account_id:    document.getElementById('divEntryAccId').value,
      dividend_date: document.getElementById('divEntryDate').value,
      amount:        parseFloat(document.getElementById('divEntryAmount').value),
      tax:           parseFloat(document.getElementById('divEntryTax').value),
      net_amount:    parseFloat(document.getElementById('divEntryNet').value),
      dividend_rate: rateVal !== '' ? parseFloat(rateVal) : null,
      memo:          document.getElementById('divEntryMemo').value,
    };
    if (stockId) payload.stock_id = stockId;
    const url    = isEdit ? `/api/v1/dividends/entries/${editId}` : '/api/v1/dividends/entries';
    const method = isEdit ? 'PUT' : 'POST';
    try {
      const btn = document.getElementById('divEntrySubmitBtn');
      btn.disabled = true; btn.textContent = '저장 중...';
      const data = await fetchJson(url, { method, headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
      if (data.ok) {
        showToast(isEdit ? '배당 내역이 수정되었습니다.' : '배당 내역이 저장되었습니다.');
        closeDivModal();
        await refreshDividendHistory();
      }
    } catch (err) { alert('오류: ' + err.message); }
    finally {
      const btn = document.getElementById('divEntrySubmitBtn');
      if (btn) { btn.disabled = false; btn.textContent = isEdit ? '수정' : '등록'; }
    }
  }
}

// ── 수정 버튼 핸들러 ─────────────────────────────────────────────────────────

function handleEditSelectedAccount() {
  const ids = getSelectedIds('dividendAccountsTableBody');
  if (!ids.length) { alert('수정할 계좌를 선택해 주세요.'); return; }
  if (ids.length > 1) { alert('수정은 1개만 선택해 주세요.'); return; }
  const acc = _dividendAccountsMap[ids[0]];
  if (!acc) return;
  openDivModal('account', 'edit', acc);
}

function handleEditSelectedEntry() {
  const ids = getSelectedIds('dividendHistoryTableBody');
  if (!ids.length) { alert('수정할 배당 내역을 선택해 주세요.'); return; }
  if (ids.length > 1) { alert('수정은 1개만 선택해 주세요.'); return; }
  const entry = _dividendHistoryMap[ids[0]];
  if (!entry) return;
  openDivModal('entry', 'edit', entry);
}

// ── 삭제 ─────────────────────────────────────────────────────────────────────

async function handleBulkDeleteAccounts() {
  const ids = getSelectedIds('dividendAccountsTableBody');
  if (!ids.length) { alert('삭제할 계좌를 선택해 주세요.'); return; }
  if (!confirm(`선택한 ${ids.length}개 계좌를 삭제할까요? (관련 배당 내역은 숨겨집니다)`)) return;
  try {
    const data = await fetchJson('/api/v1/dividends/accounts/bulk-delete', {
      method: 'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ ids })
    });
    if (data.ok) { await loadDividendAccounts(); await refreshDividendHistory(); }
  } catch (err) { alert('삭제 실패: ' + err.message); }
}

async function handleBulkDeleteEntries() {
  const ids = getSelectedIds('dividendHistoryTableBody');
  if (!ids.length) { alert('삭제할 배당 내역을 선택해 주세요.'); return; }
  if (!confirm(`선택한 ${ids.length}개 배당 내역을 삭제할까요?`)) return;
  try {
    const data = await fetchJson('/api/v1/dividends/entries/bulk-delete', {
      method: 'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ ids })
    });
    if (data.ok) await refreshDividendHistory();
  } catch (err) { alert('삭제 실패: ' + err.message); }
}

async function deleteDividendStock() {
  const ids = getSelectedIds('dividendStocksTableBody');
  if (!ids.length) { alert('삭제할 종목을 선택해 주세요.'); return; }
  if (!confirm(`선택한 ${ids.length}개 종목을 삭제할까요?`)) return;
  try {
    await Promise.all(ids.map(id => fetchJson(`/api/v1/dividends/stocks/${id}`, { method: 'DELETE' })));
    await loadDividendStocks();
  } catch (err) { alert('삭제 실패: ' + err.message); }
}

// ── 유틸리티 ─────────────────────────────────────────────────────────────────

function toggleSelectAll(tbodyId, checked) {
  document.querySelectorAll(`#${tbodyId} input[type="checkbox"]`).forEach(cb => cb.checked = checked);
}

function getSelectedIds(tbodyId) {
  return Array.from(document.querySelectorAll(`#${tbodyId} input[type="checkbox"]:checked`)).map(cb => cb.value);
}

// ── 순수익 자동 계산 ─────────────────────────────────────────────────────────

['divEntryAmount', 'divEntryTax'].forEach(id => {
  document.addEventListener('input', function(e) {
    if (e.target.id === id) {
      const gross = parseFloat(document.getElementById('divEntryAmount')?.value) || 0;
      const tax   = parseFloat(document.getElementById('divEntryTax')?.value)   || 0;
      const net   = document.getElementById('divEntryNet');
      if (net) net.value = (gross - tax).toFixed(2);
    }
  });
});

// ── 데이터 로드 ───────────────────────────────────────────────────────────────

async function refreshDividends() {
  await Promise.all([loadDividendStocks(), loadDividendAccounts(), refreshDividendHistory()]);
}

async function loadDividendStocks() {
  const tbody  = document.getElementById('dividendStocksTableBody');
  const select = document.getElementById('divEntryStockId');
  try {
    const data = await fetchJson('/api/v1/dividends/stocks');
    if (!data.ok) return;
    _dividendStocksMap = {};
    data.stocks.forEach(s => _dividendStocksMap[s.id] = s);
    _divAllStocks = data.stocks;
    _divPages.stocks = 1;
    _divRenderPage('stocks');
    const currentVal = select ? select.value : '';
    if (select) {
      select.innerHTML = '<option value="">종목 선택 안함</option>'
        + data.stocks.map(s => `<option value="${s.id}">${escapeHtml(s.name)} (${escapeHtml(s.code)})</option>`).join('');
      select.value = currentVal;
    }
  } catch (e) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="7" class="bad">오류: ${escapeHtml(e.message)}</td></tr>`;
  }
}

async function loadDividendAccounts() {
  const tbody  = document.getElementById('dividendAccountsTableBody');
  const select = document.getElementById('divEntryAccId');
  try {
    const data = await fetchJson('/api/v1/dividends/accounts');
    if (!data.ok) return;
    _dividendAccountsMap = {};
    data.accounts.forEach(acc => _dividendAccountsMap[acc.id] = acc);
    _divAllAccounts = data.accounts;
    _divPages.accounts = 1;
    _divRenderPage('accounts');
    if (select) {
      const currentVal = select.value;
      select.innerHTML = '<option value="">계좌 선택</option>'
        + data.accounts.map(acc =>
          `<option value="${acc.id}">${escapeHtml(acc.bank_name)} - ${escapeHtml(acc.account_number)} (${escapeHtml(acc.owner_name)})</option>`
        ).join('');
      select.value = currentVal;
    }
  } catch (e) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="4" class="bad">오류: ${escapeHtml(e.message)}</td></tr>`;
  }
}

async function refreshDividendHistory() {
  const tbody = document.getElementById('dividendHistoryTableBody');
  try {
    const data = await fetchJson('/api/v1/dividends/history');
    if (!data.ok) return;
    _dividendHistoryMap = {};
    data.history.forEach(row => _dividendHistoryMap[row.id] = row);
    _divAllHistory = data.history;
    _divPages.history = 1;
    _divRenderPage('history');
  } catch (e) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="7" class="bad">오류: ${escapeHtml(e.message)}</td></tr>`;
  }
}

// ── 종목 알림/배당락일 ────────────────────────────────────────────────────────

async function muteStock(stockId) {
  try { await fetchJson(`/api/v1/dividends/stocks/${stockId}/mute`, { method: 'POST' }); await loadDividendStocks(); }
  catch (err) { alert('오류: ' + err.message); }
}

async function unmuteStock(stockId) {
  try { await fetchJson(`/api/v1/dividends/stocks/${stockId}/unmute`, { method: 'POST' }); await loadDividendStocks(); }
  catch (err) { alert('오류: ' + err.message); }
}
