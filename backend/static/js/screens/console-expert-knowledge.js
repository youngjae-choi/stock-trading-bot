  var _ekCurrentAnalysisId = null;

  /* Upload a selected PDF and render the LLM strategy analysis result. */
  async function ekUploadPdf() {
    var input = document.getElementById('ek-pdf-input');
    var statusEl = document.getElementById('ek-upload-status');
    var resultCard = document.getElementById('ek-result-card');
    var uploadBtn = document.getElementById('ek-upload-btn');
    if (!input.files || !input.files[0]) {
      statusEl.textContent = 'PDF 파일을 선택해주세요.';
      return;
    }
    var file = input.files[0];
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      statusEl.textContent = 'PDF 파일만 업로드 가능합니다.';
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      statusEl.textContent = 'PDF 파일 크기는 10MB를 초과할 수 없습니다.';
      return;
    }
    statusEl.textContent = '업로드 중... (LLM 분석에 30~60초 소요될 수 있습니다)';
    resultCard.style.display = 'none';
    _ekCurrentAnalysisId = null;
    if (uploadBtn) uploadBtn.disabled = true;

    try {
      var formData = new FormData();
      formData.append('file', file);
      var res = await fetch('/api/v1/expert-knowledge/upload-pdf', {
        method: 'POST',
        body: formData
      });
      var data = await res.json();
      if (!data.ok) {
        statusEl.textContent = '분석 실패: ' + (data.error || data.detail || '알 수 없는 오류');
        return;
      }
      _ekCurrentAnalysisId = data.payload.analysis_id;
      statusEl.textContent = data.payload.error
        ? '분석 저장 완료. LLM 설정 확인 필요: ' + data.payload.error
        : '분석 완료. 아래 결과를 확인하세요.';
      ekRenderResult(data.payload);
      ekLoadHistory();
    } catch(e) {
      console.error('[ERROR]', 'ekUploadPdf', '-', e.message);
      statusEl.textContent = '오류: ' + e.message;
    } finally {
      if (uploadBtn) uploadBtn.disabled = false;
    }
  }

  /* Render the current PDF analysis candidates, unmappable items, and summary. */
  function ekRenderResult(payload) {
    var resultCard = document.getElementById('ek-result-card');
    var summaryEl = document.getElementById('ek-summary');
    var tbody = document.getElementById('ek-candidates-tbody');
    var unmappableEl = document.getElementById('ek-unmappable');
    var unmappableList = document.getElementById('ek-unmappable-list');
    var applyResult = document.getElementById('ek-apply-result');

    resultCard.style.display = '';
    summaryEl.textContent = payload.summary || '';
    applyResult.style.color = '';
    applyResult.textContent = '';

    var candidates = payload.candidates || [];
    tbody.innerHTML = candidates.length === 0
      ? '<tr><td colspan="5" class="muted" style="padding:12px; text-align:center;">추출된 전략 항목 없음</td></tr>'
      : candidates.map(function(c, i) {
          return '<tr style="border-bottom:1px solid var(--border);">'
            + '<td style="padding:6px 8px; text-align:center;"><input type="checkbox" id="ek-chk-' + i + '" data-key="' + escapeHtml(c.setting_key || '') + '" checked' + (c.setting_key ? '' : ' disabled') + '></td>'
            + '<td style="padding:6px 8px;">' + escapeHtml(c.label || '') + '</td>'
            + '<td style="padding:6px 8px; font-weight:600; color:var(--blue);">' + escapeHtml(String(c.value || '')) + '</td>'
            + '<td style="padding:6px 8px; font-size:11px; color:var(--muted);">' + escapeHtml(c.setting_key || '매핑 불가') + '</td>'
            + '<td style="padding:6px 8px; font-size:11px; color:var(--muted);">' + escapeHtml(c.reason || '') + '</td>'
            + '</tr>';
        }).join('');

    var unmappable = payload.unmappable || [];
    if (unmappable.length > 0) {
      unmappableEl.style.display = '';
      unmappableList.innerHTML = unmappable.map(function(u) {
        return '<div style="margin-bottom:4px;">- <strong>' + escapeHtml(u.label || '') + '</strong>: '
          + escapeHtml(u.description || '') + ' - '
          + '<em>OOO 기능을 Setting 화면에 추가하여야 합니다. 개발 후 재 요청해주세요.</em></div>';
      }).join('');
    } else {
      unmappableEl.style.display = 'none';
    }
  }

  /* Apply checked strategy candidates from the active analysis to Settings. */
  async function ekApplyStrategy() {
    if (!_ekCurrentAnalysisId) return;
    var applyResult = document.getElementById('ek-apply-result');
    var applyBtn = document.getElementById('ek-apply-btn');
    var checkboxes = document.querySelectorAll('#ek-candidates-tbody input[type=checkbox]:checked');
    var approvedKeys = Array.from(checkboxes).map(function(cb) { return cb.getAttribute('data-key'); }).filter(Boolean);
    if (!approvedKeys.length) {
      applyResult.style.color = 'var(--yellow)';
      applyResult.textContent = '적용할 항목을 선택해주세요.';
      return;
    }
    if (applyBtn) applyBtn.disabled = true;
    applyResult.style.color = 'var(--muted)';
    applyResult.textContent = 'Settings 적용 중...';
    try {
      var res = await fetch('/api/v1/expert-knowledge/apply-strategy/' + encodeURIComponent(_ekCurrentAnalysisId), {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({approved_keys: approvedKeys})
      });
      var data = await res.json();
      if (!data.ok) {
        applyResult.style.color = 'var(--yellow)';
        applyResult.textContent = '적용 실패: ' + (data.error || data.detail || '');
        return;
      }
      var msgs = (data.payload.messages || []).join('\n');
      applyResult.style.color = 'var(--green)';
      applyResult.textContent = msgs || '적용 완료';
      ekLoadHistory();
    } catch(e) {
      console.error('[ERROR]', 'ekApplyStrategy', '-', e.message);
      applyResult.style.color = 'var(--yellow)';
      applyResult.textContent = '오류: ' + e.message;
    } finally {
      if (applyBtn) applyBtn.disabled = false;
    }
  }

  /* Reset the PDF upload form and hide the current analysis result. */
  function ekReset() {
    _ekCurrentAnalysisId = null;
    document.getElementById('ek-result-card').style.display = 'none';
    document.getElementById('ek-pdf-input').value = '';
    document.getElementById('ek-upload-status').textContent = '';
  }

  /* Load the latest PDF analysis history for the Expert Knowledge screen. */
  async function ekLoadHistory() {
    var el = document.getElementById('ek-history-list');
    if (!el) return;
    try {
      var res = await fetch('/api/v1/expert-knowledge/analyses');
      var data = await res.json();
      if (!data.ok) {
        el.textContent = '이력 로드 실패: ' + (data.error || data.detail || '알 수 없는 오류');
        return;
      }
      var items = data.payload || [];
      if (!items.length) { el.textContent = '분석 이력 없음'; return; }
      el.innerHTML = items.map(function(item) {
        var ts = item.created_at ? item.created_at.substring(0, 16).replace('T', ' ') : '-';
        var status = item.status === 'applied' ? '<span style="color:var(--green);">적용됨</span>' : '대기';
        return '<div style="padding:6px 0; border-bottom:1px solid var(--border); display:flex; gap:8px; align-items:center;">'
          + '<span style="color:var(--muted); font-size:11px;">' + ts + '</span>'
          + '<span>' + escapeHtml(item.filename || '') + '</span>'
          + '<span>' + status + '</span>'
          + '</div>';
      }).join('');
    } catch(e) {
      console.error('[ERROR]', 'ekLoadHistory', '-', e.message);
      el.textContent = '이력 로드 실패: ' + e.message;
    }
  }

  async function loadExpertKnowledge() {
    try {
      const res = await fetch('/api/v1/expert-knowledge/');
      if (!res.ok) return;
      const data = await res.json();
      const items = data.payload || [];
      renderKnowledgeList(items);
    } catch (e) {
      console.warn('loadExpertKnowledge error', e);
    }
  }

  function renderKnowledgeList(items) {
    const tbody = document.getElementById('ek-list-tbody');
    if (!tbody) return;
    if (!items.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="muted" style="text-align:center;">등록된 지식 없음</td></tr>';
      return;
    }
    tbody.innerHTML = items.map(item => {
      const statusClass = item.status === 'approved' ? 'ok' : item.status === 'rejected' ? 'fail' : 'info';
      const actionBtns = item.status === 'pending'
        ? `<button class="btn small secondary" onclick="approveKnowledge('${item.id}')">승인</button>
           <button class="btn small" onclick="rejectKnowledge('${item.id}')">거부</button>`
        : `<span class="muted">${item.status}</span>`;
      return `<tr>
        <td>${escapeHtml(item.title)}</td>
        <td><span class="tag">${escapeHtml(item.scope)}</span></td>
        <td>${escapeHtml(item.category)}</td>
        <td>${item.priority}</td>
        <td><span class="status ${statusClass}">${item.status}</span></td>
        <td>${(item.created_at || '').slice(0, 10)}</td>
        <td>${actionBtns}</td>
      </tr>`;
    }).join('');
  }

  async function submitKnowledge() {
    const title = document.getElementById('ek-title')?.value?.trim();
    const content = document.getElementById('ek-content')?.value?.trim();
    const scope = document.getElementById('ek-scope')?.value;
    const category = document.getElementById('ek-category')?.value;
    const priority = parseInt(document.getElementById('ek-priority')?.value || '5');

    if (!title || !content) {
      showToast('제목과 내용을 입력하세요', 'error');
      return;
    }

    try {
      const res = await fetch('/api/v1/expert-knowledge/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, content, scope, category, priority, auto_inject: false }),
      });
      const data = await res.json();
      if (res.ok && data.ok) {
        showToast('지식 등록 완료');
        document.getElementById('ek-title').value = '';
        document.getElementById('ek-content').value = '';
        await loadExpertKnowledge();
      } else {
        showToast('등록 실패: ' + (data.detail || 'unknown'), 'error');
      }
    } catch (e) {
      showToast('오류: ' + e.message, 'error');
    }
  }

  async function approveKnowledge(itemId) {
    try {
      const res = await fetch(`/api/v1/expert-knowledge/${itemId}/approve`, { method: 'POST' });
      const data = await res.json();
      if (res.ok && data.ok) {
        showToast('승인 완료');
        await loadExpertKnowledge();
      } else {
        showToast('승인 실패', 'error');
      }
    } catch (e) {
      showToast('오류: ' + e.message, 'error');
    }
  }

  async function rejectKnowledge(itemId) {
    try {
      const res = await fetch(`/api/v1/expert-knowledge/${itemId}/reject`, { method: 'POST' });
      const data = await res.json();
      if (res.ok && data.ok) {
        showToast('거부 완료');
        await loadExpertKnowledge();
      } else {
        showToast('거부 실패', 'error');
      }
    } catch (e) {
      showToast('오류: ' + e.message, 'error');
    }
  }

  // Data Quality Guard 로드
