  // False Positive — 손실 거래 분석 화면
  (function () {
    function _todayKst() {
      return new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Seoul' }));
    }
    function _fmtDate(d) {
      return d.toISOString().slice(0, 10);
    }
    function _firstOfMonth(d) {
      return new Date(d.getFullYear(), d.getMonth(), 1);
    }

    function _initFpDates() {
      var today = _todayKst();
      var s = document.getElementById('fp-start-date');
      var e = document.getElementById('fp-end-date');
      if (s && !s.value) s.value = _fmtDate(_firstOfMonth(today));
      if (e && !e.value) e.value = _fmtDate(today);
    }

    function _fpTypeKr(t) {
      if (t === 'entry_fail')    return '진입실패';
      if (t === 'early_exit')    return '조기청산';
      if (t === 'wrong_profile') return '프로파일오류';
      return t || '-';
    }

    function _renderFpTable(items) {
      var tbody = document.getElementById('fp-list-tbody');
      var summCard = document.getElementById('fp-summary-card');
      if (!tbody) return;

      if (!items || !items.length) {
        tbody.innerHTML = '<tr><td colspan="9" class="muted" style="text-align:center">'
          + '조회 결과 없음 — 해당 기간에 손실 거래가 없거나 분석이 실행되지 않았습니다</td></tr>';
        if (summCard) summCard.style.display = 'none';
        return;
      }

      // 요약 카드
      if (summCard) summCard.style.display = '';
      var totalPnlAmt = 0, pnlPctSum = 0, pnlCnt = 0;
      items.forEach(function (f) {
        if (f.pnl_amount != null) totalPnlAmt += f.pnl_amount;
        if (f.pnl_pct != null)   { pnlPctSum += f.pnl_pct; pnlCnt++; }
      });
      var avgPnl = pnlCnt > 0 ? pnlPctSum / pnlCnt : null;

      var cntEl   = document.getElementById('fp-count');
      var avgEl   = document.getElementById('fp-avg-pnl');
      var totalEl = document.getElementById('fp-total-pnl');
      if (cntEl)   cntEl.textContent = items.length + '건';
      if (avgEl) {
        avgEl.textContent = avgPnl != null
          ? (avgPnl >= 0 ? '+' : '') + avgPnl.toFixed(2) + '%'
          : '-';
        avgEl.style.color = (avgPnl != null && avgPnl < 0)
          ? 'var(--red,#f85149)' : '';
      }
      if (totalEl) {
        totalEl.textContent = (totalPnlAmt >= 0 ? '+' : '')
          + Math.round(totalPnlAmt).toLocaleString() + '원';
        totalEl.style.color = totalPnlAmt < 0 ? 'var(--red,#f85149)' : '';
      }

      // 테이블 행
      tbody.innerHTML = items.map(function (f) {
        var pnlPct = f.pnl_pct != null ? f.pnl_pct : null;
        var pnlAmt = f.pnl_amount != null ? f.pnl_amount : null;

        var pnlStr = pnlPct != null
          ? '<span class="' + (pnlPct >= 0 ? 'good' : 'bad') + '">'
            + (pnlPct >= 0 ? '+' : '') + pnlPct.toFixed(2) + '%'
            + (pnlAmt != null
              ? '<br><small>' + (pnlAmt >= 0 ? '+' : '')
                + Math.round(pnlAmt).toLocaleString() + '원</small>'
              : '')
            + '</span>'
          : '-';

        var buyStr  = f.buy_price  != null ? Math.round(f.buy_price).toLocaleString()  + '원' : '-';
        var sellStr = f.sell_price != null ? Math.round(f.sell_price).toLocaleString() + '원' : '-';
        var confStr = f.original_confidence != null
          ? (f.original_confidence * 100).toFixed(1) + '%' : '-';

        var reviewBtn = '<button class="btn-sm" style="font-size:11px;padding:2px 8px;" '
          + 'onclick="reviewFalsePositive(\'' + escapeHtml(f.id) + '\')" title="확인 완료 처리 — 목록에서 숨김">확인</button>';
        return '<tr>'
          + '<td style="white-space:nowrap">' + escapeHtml(f.trade_date || '-') + '</td>'
          + '<td><strong>' + escapeHtml(f.symbol_name || f.symbol) + '</strong>'
          + '<br><small class="muted">' + escapeHtml(f.symbol) + '</small></td>'
          + '<td>' + _fpTypeKr(f.false_positive_type) + '</td>'
          + '<td style="text-align:right">' + buyStr  + '</td>'
          + '<td style="text-align:right">' + sellStr + '</td>'
          + '<td style="text-align:right">' + pnlStr  + '</td>'
          + '<td style="text-align:center">' + confStr + '</td>'
          + '<td style="font-size:0.82em;color:var(--muted)">'
          + escapeHtml(f.loss_reason  || '-') + '</td>'
          + '<td style="font-size:0.82em;color:var(--muted)">'
          + escapeHtml(f.entry_reason || '-') + '</td>'
          + '<td style="text-align:center">' + reviewBtn + '</td>'
          + '</tr>';
      }).join('');
    }

    async function searchFalsePositive() {
      _initFpDates();
      var s     = document.getElementById('fp-start-date');
      var e     = document.getElementById('fp-end-date');
      var start = s ? s.value : '';
      var end   = e ? e.value : '';
      if (!start || !end) { alert('날짜를 입력해주세요.'); return; }
      try {
        var data  = await fetchJson('/api/v1/false-positive/list?start=' + start + '&end=' + end);
        var items = (data.payload && data.payload.items) || [];
        _renderFpTable(items);
      } catch (ex) {
        var tbody = document.getElementById('fp-list-tbody');
        if (tbody) tbody.innerHTML = '<tr><td colspan="9" class="muted" style="text-align:center">'
          + '조회 실패: ' + escapeHtml(ex.message) + '</td></tr>';
      }
    }

    async function generateFalsePositive() {
      _initFpDates();
      var e         = document.getElementById('fp-end-date');
      var tradeDate = e ? e.value : '';
      if (!tradeDate) { alert('날짜를 입력해주세요.'); return; }
      if (!confirm(tradeDate + ' 기준 손실 거래를 분석해 False Positive 데이터를 생성할까요?')) return;
      try {
        var data = await fetchJson(
          '/api/v1/false-positive/generate?trade_date=' + tradeDate,
          { method: 'POST' }
        );
        var p = data.payload || {};
        alert(
          '분석 완료\n'
          + '  전체 손실 거래: ' + (p.total_losing || 0) + '건\n'
          + '  신규 저장: '      + (p.saved  || []).length + '건\n'
          + '  중복 스킵: '      + (p.skipped || []).length + '건'
        );
        searchFalsePositive();
      } catch (ex) {
        alert('실행 실패: ' + ex.message);
      }
    }

    async function loadFalsePositive() {
      _initFpDates();
      await searchFalsePositive();
    }

    async function reviewFpCase(fpId) {
      try {
        await fetchJson('/api/v1/false-positive/' + fpId + '/review', { method: 'PATCH' });
        await searchFalsePositive();
      } catch (ex) {
        alert('처리 실패: ' + ex.message);
      }
    }

    // 전역 노출
    window._fpSearch   = searchFalsePositive;
    window._fpGenerate = generateFalsePositive;
    window._fpLoad     = loadFalsePositive;
    window._fpReview   = reviewFpCase;
  }());

  function searchFalsePositive()  { return window._fpSearch();   }
  function generateFalsePositive() { return window._fpGenerate(); }
  function loadFalsePositive()    { return window._fpLoad();     }
  function reviewFalsePositive(id) { return window._fpReview(id); }
