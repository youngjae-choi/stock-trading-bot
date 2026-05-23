  async function loadReviewData() {
    try {
      var data = await fetchJson("/api/v1/trades/history?limit=31");
      var items = (data.payload && data.payload.items) || [];

      var tradeDays = items.length;
      var totalOrders = 0;
      var profitDays = 0;
      var pnlSum = 0;
      items.forEach(function(item) {
        totalOrders += item.total_orders || 0;
        pnlSum += item.realized_pnl_pct || 0;
        if ((item.realized_pnl_pct || 0) > 0) profitDays++;
      });
      var winrate = tradeDays > 0 ? Math.round(profitDays / tradeDays * 100) : 0;

      function setRV(id, text, cls) {
        var el = document.getElementById(id);
        if (el) { el.textContent = text; if (cls) el.className = "metric " + cls; }
      }

      setRV("review-trade-days", tradeDays + "일");
      setRV("review-total-orders", totalOrders + "건");
      var pnlCls = pnlSum >= 0 ? "good" : "bad";
      setRV("review-pnl", (pnlSum >= 0 ? "+" : "") + pnlSum.toFixed(2) + "%", pnlCls);
      setRV("review-winrate", winrate + "%", winrate >= 50 ? "good" : "warn");
      var wrDetail = document.getElementById("review-winrate-detail");
      if (wrDetail) wrDetail.textContent = profitDays + "수익일 / " + tradeDays + "거래일";

      if (items.length > 0) {
        var latest = items[0];
        var summEl = document.getElementById("review-latest-summary");
        var toneEl = document.getElementById("review-latest-tone");
        var rpEl   = document.getElementById("review-latest-rulepack");
        if (summEl) summEl.textContent = latest.trade_date + " · 주문 " + (latest.total_orders || 0) + "건 · 손익 " + (latest.realized_pnl_pct || 0).toFixed(2) + "%";
        if (toneEl) toneEl.textContent = latest.market_tone || "(없음)";
        if (rpEl)   rpEl.textContent   = latest.rulepack_id  || "(없음)";
      }

      var tbody = document.getElementById("review-history-tbody");
      if (tbody) {
        if (items.length === 0) {
          tbody.innerHTML = '<tr><td colspan="6" class="muted" style="text-align:center;">데이터 없음: 최근 31일 거래 요약 없음</td></tr>';
        } else {
          tbody.innerHTML = items.map(function(item) {
            var pnl = item.realized_pnl_pct || 0;
            var pnlStr = (pnl >= 0 ? "+" : "") + pnl.toFixed(2) + "%";
            return '<tr style="cursor:pointer;" data-action="showScreen" data-screen="statistics">'
              + '<td>' + (item.trade_date || "") + '</td>'
              + '<td>' + (item.total_orders || 0) + '</td>'
              + '<td>' + (item.buy_orders || 0) + '</td>'
              + '<td>' + (item.sell_orders || 0) + '</td>'
              + '<td class="' + (pnl >= 0 ? "good" : "bad") + '">' + pnlStr + '</td>'
              + '<td>' + escapeHtml(item.market_tone || "-") + '</td>'
              + '</tr>';
          }).join("");
        }
      }
    } catch (e) {
      var tbody3 = document.getElementById("review-history-tbody");
      if (tbody3) tbody3.innerHTML = '<tr><td colspan="6" class="muted">실행 실패: 거래 요약을 불러오지 못했습니다 - ' + escapeHtml(e.message) + '</td></tr>';
    }
  }

  async function runDailySummary() {
    if (!confirm("오늘 거래를 집계하고 DB를 백업할까요? (S10 실행)")) return;
    try {
      await fetchJson("/api/v1/trades/run-summary", { method: "POST" });
      alert("일일 요약 생성 완료. 새로고침합니다.");
      loadReviewData();
    } catch (e) {
      alert("실패: " + e.message);
    }
  }

  // ── Review & Audit ─────────────────────────────────────────────────────────

  var _raCurrentReport      = null;
  var _raRecommendedOverrides = {};   // _nlTomorrow()가 채움 → applyNextDayOverrides()가 읽음

  function setReviewAuditEmptyState(statusText, detailText) {
    var emptyEl  = document.getElementById('ra-empty');
    var reportEl = document.getElementById('ra-report');
    if (emptyEl)  emptyEl.style.display  = '';
    if (reportEl) reportEl.style.display = 'none';
    var statusEl = document.getElementById('ra-empty-status');
    var detailEl = document.getElementById('ra-empty-detail');
    if (statusEl) statusEl.textContent = statusText;
    if (detailEl) detailEl.textContent = detailText;
  }

  async function loadReviewAuditScreen() {
    var today = new Date();
    var todayStr = today.getFullYear() + '-'
      + String(today.getMonth() + 1).padStart(2, '0') + '-'
      + String(today.getDate()).padStart(2, '0');
    var input = document.getElementById('ra-date-input');
    if (input) input.value = todayStr;
    await _loadReviewByDateStr(todayStr);
  }

  /* 날짜 피커 값을 읽어 조회 — console-actions.js에서 호출 */
  async function loadReviewByDate() {
    var input = document.getElementById('ra-date-input');
    var dateStr = input ? input.value : '';
    if (!dateStr) { await loadReviewAuditScreen(); return; }
    await _loadReviewByDateStr(dateStr);
  }

  async function _loadReviewByDateStr(dateStr) {
    var emptyEl  = document.getElementById('ra-empty');
    var reportEl = document.getElementById('ra-report');
    if (emptyEl)  emptyEl.style.display  = 'none';
    if (reportEl) reportEl.style.display = 'none';

    try {
      var url = dateStr ? '/api/v1/review-audit/' + encodeURIComponent(dateStr) : '/api/v1/review-audit/today';
      var res  = await fetch(url);
      var data = await res.json();
      var report = (data.payload && typeof data.payload === 'object') ? data.payload : null;

      if (!res.ok || !report) {
        _raCurrentReport = null;
        setReviewAuditEmptyState(
          res.ok ? '미수집·대기: S10 Review & Audit 미실행' : '데이터 없음: 해당 날짜 보고서 없음',
          res.ok ? 'S10 실행 버튼을 눌러 보고서를 생성하세요.' : '선택한 날짜에 저장된 보고서가 없습니다.'
        );
        return;
      }

      _raCurrentReport = report;
      if (!report.trade_date && report.md_content) {
        // MD 전용 — 헤더만 표시
        if (reportEl) reportEl.style.display = '';
        var titleEl = document.getElementById('ra-report-title');
        if (titleEl) titleEl.textContent = (dateStr || '복기') + ' 보고서';
        var subEl = document.getElementById('ra-report-subtitle');
        if (subEl) subEl.textContent = 'MD 파일 전용 — 자세히 보기를 눌러주세요';
      } else {
        renderReviewReport(report);
        if (reportEl) reportEl.style.display = '';
      }
    } catch (e) {
      _raCurrentReport = null;
      setReviewAuditEmptyState('오류: 보고서 조회 실패', e.message || 'unknown');
    }
  }

  /* 모든 섹션을 한번에 렌더링 — 자연어 5블록 */
  function renderReviewReport(r) {
    // LLM 복기 카드
    var llmCard = document.getElementById('ra-llm-review-card');
    var llmReview = r.llm_review || {};
    var regimeEval = llmReview.regime_evaluation || {};

    if (llmCard) {
      var narrative = llmReview.narrative || '';
      var appliedAt = llmReview.applied_at || '';
      var appliedSettings = llmReview.applied_settings || [];
      var evaluation = regimeEval.evaluation || '';
      var patterns = llmReview.patterns || {};
      var recs = llmReview.recommendations || [];   // 구형식 fallback

      if (narrative || evaluation || recs.length) {
        llmCard.style.display = 'block';

        // 적용 시각
        var atEl = document.getElementById('ra-llm-applied-at');
        if (atEl && appliedAt) {
          atEl.textContent = '반영: ' + appliedAt.slice(11, 16) + ' KST';
        }

        // 레짐 평가 배지
        var badgeEl = document.getElementById('ra-regime-eval-badge');
        if (badgeEl) {
          if (evaluation) {
            var evalColors = { good: '#3fb950', neutral: '#8b9bb4', bad: '#f85149' };
            var evalLabels = { good: '✅ 레짐 선택 적절', neutral: '📊 레짐 선택 보통', bad: '⚠️ 레짐 선택 부적절' };
            var col = evalColors[evaluation] || '#8b9bb4';
            var label = evalLabels[evaluation] || evaluation;
            var reason = regimeEval.reason || '';
            var hint = regimeEval.next_regime_hint || '';
            badgeEl.innerHTML =
              '<div style="display:flex; gap:10px; align-items:flex-start; flex-wrap:wrap;">'
              + '<span style="padding:4px 12px; border-radius:20px; background:' + col + '22; color:' + col + '; font-weight:700; font-size:13px;">' + escapeHtml(label) + '</span>'
              + (hint && hint !== 'same' ? '<span style="font-size:12px; color:var(--muted); align-self:center;">내일 힌트: <strong style="color:var(--fg);">' + escapeHtml(hint) + '</strong></span>' : '')
              + '</div>'
              + (reason ? '<div style="font-size:12px; color:var(--muted); margin-top:6px;">' + escapeHtml(reason) + '</div>' : '');
          } else if (!narrative) {
            // 구형식: 레짐 평가 없음 안내
            badgeEl.innerHTML = '<span style="font-size:12px; color:var(--muted);">S10 LLM 분석 전 — 아래 권장사항은 규칙 기반 분석 결과입니다.</span>';
          }
        }

        // 서술 (LLM narrative 우선, 없으면 구형식 recommendations fallback)
        var narrativeEl = document.getElementById('ra-llm-narrative');
        if (narrativeEl) {
          if (narrative) {
            narrativeEl.innerHTML = narrative.split('\n').map(function(line) {
              return '<div>' + escapeHtml(line) + '</div>';
            }).join('');
          } else if (recs.length) {
            narrativeEl.innerHTML = recs.map(function(rec) {
              return '<div style="padding:4px 0; border-bottom:1px solid var(--border-faint,#2a2a2a);">' + escapeHtml(rec) + '</div>';
            }).join('');
          }
        }

        // 패턴
        var patternsEl = document.getElementById('ra-llm-patterns');
        if (patternsEl) {
          var winning = patterns.winning || [];
          var losing = patterns.losing || [];
          var html = '';
          if (winning.length) {
            html += '<div style="margin-bottom:8px;"><span style="color:#3fb950; font-size:11px; font-weight:600;">▲ 승리 패턴</span>'
              + winning.map(function(p) { return '<div style="margin-left:10px; font-size:12px; color:var(--muted);">• ' + escapeHtml(p) + '</div>'; }).join('') + '</div>';
          }
          if (losing.length) {
            html += '<div><span style="color:#f85149; font-size:11px; font-weight:600;">▼ 손실 패턴</span>'
              + losing.map(function(p) { return '<div style="margin-left:10px; font-size:12px; color:var(--muted);">• ' + escapeHtml(p) + '</div>'; }).join('') + '</div>';
          }
          patternsEl.innerHTML = html;
        }
      } else {
        llmCard.style.display = 'none';
      }
    }

    var setEl   = function(id, val) { var el = document.getElementById(id); if (el) el.textContent = val != null ? val : '-'; };
    var setHtml = function(id, html) { var el = document.getElementById(id); if (el) el.innerHTML = html; };

    // 헤더
    var d = new Date((r.trade_date || '') + 'T00:00:00');
    setEl('ra-report-title', (d.getMonth() + 1) + '월 ' + d.getDate() + '일 복기 보고서');
    var dp = r.daily_plan || {};
    var ta = r.tone_analysis || {};
    var toneLabel = _toneKr(ta.tone || r.market_tone);
    var intensityLabel = _intensityKr(dp.trading_intensity);
    var rpLabel = dp.base_rulepack_id || r.rulepack_id || '미설정';
    setEl('ra-report-subtitle',
      '시장톤: ' + toneLabel
      + (intensityLabel ? ' | 매매강도: ' + intensityLabel : '')
      + ' | RulePack: ' + rpLabel
    );

    // 자연어 5블록
    setHtml('ra-nl-context',  _nlContext(r));
    setHtml('ra-nl-result',   _nlResult(r));
    setHtml('ra-nl-missed',   _nlMissed(r));
    setHtml('ra-nl-loss',     _nlLoss(r));
    setHtml('ra-nl-tomorrow', _nlTomorrow(r));

    // BLOCK 6 — 시스템 반영 내역
    setHtml('ra-nl-settings-applied', _nlSettingsApplied(r));

    // 장중 재선별 이력 비동기 로드
    if (r.trade_date) {
      _loadIntradayRefreshForReview(r.trade_date);
      loadRegimeEvalForReview(r.trade_date);
    }
  }

  async function loadRegimeEvalForReview(tradeDate) {
    var card = document.getElementById('ra-regime-eval');
    var content = document.getElementById('ra-regime-eval-content');
    if (!card || !content) return;
    
    try {
      var r = await fetch('/api/v1/regime/day-detail?trade_date=' + encodeURIComponent(tradeDate));
      var d = await r.json();
      if (!d.ok || !d.regime_application) {
        card.style.display = 'none';
        return;
      }
      
      card.style.display = 'block';
      var app = d.regime_application;
      var evalHtml = '';
      
      // 평가 내용 (자연어)
      if (app.eval_summary) {
        evalHtml += '<div style="margin-bottom:12px; line-height:1.6; color:var(--fg);">' + escapeHtml(app.eval_summary) + '</div>';
      } else {
        evalHtml += '<div style="margin-bottom:12px; color:var(--muted);">시스템이 판단한 레짐 적합성 평가가 없습니다.</div>';
      }
      
      // 점수 및 배지
      var score = Math.round((app.eval_score || 0) * 100);
      var scoreCls = score >= 80 ? 'good' : (score >= 50 ? 'warn' : 'bad');
      
      evalHtml += '<div style="display:flex; align-items:center; gap:16px;">'
        + '<div>'
          + '<div style="font-size:11px; color:var(--muted); margin-bottom:2px;">적합성 점수</div>'
          + '<div class="metric ' + scoreCls + '" style="font-size:24px;">' + score + '점</div>'
        + '</div>'
        + '<div style="flex:1; font-size:12px; border-left:1px solid var(--border); padding-left:16px;">'
          + '<div style="margin-bottom:4px;">적용 SET: <strong>' + escapeHtml(app.set_name || '-') + '</strong></div>'
          + '<div>판단 레짐: <strong>' + escapeHtml(app.regime_label || '-') + '</strong></div>'
        + '</div>'
        + '</div>';
        
      content.innerHTML = evalHtml;
    } catch(e) {
      console.warn('loadRegimeEvalForReview failed:', e);
      card.style.display = 'none';
    }
  }

  /* 리뷰 화면용 장중 재선별 이력 로드 */
  async function _loadIntradayRefreshForReview(tradeDate) {
    var el = document.getElementById('ra-nl-intraday');
    if (!el) return;
    try {
      var res = await fetchJson('/api/v1/funnel/intraday-refresh?date=' + encodeURIComponent(tradeDate));
      var history = (res.payload && res.payload.history) ? res.payload.history : [];
      if (!history.length) {
        el.innerHTML = '<p class="muted">해당 날짜 장중 재선별 이력이 없습니다.</p>';
        el.closest('.card') && (el.closest('[data-ra-intraday]') || el.parentElement.parentElement).style && '';
        return;
      }
      var triggered = history.filter(function(h) { return h.triggered; });
      var ran = history.filter(function(h) { return h.ran; });
      var summary = ran.length + '회 시도 / ' + triggered.length + '회 재선별 실행';
      var rows = history.map(function(h) {
        var trigBadge = h.triggered
          ? '<span class="status warn">재선별</span>'
          : (h.ran ? '<span class="status info">스킵</span>' : '<span style="color:var(--muted);">미실행</span>');
        var avg = h.avg_change != null ? (h.avg_change >= 0 ? '+' : '') + h.avg_change.toFixed(2) + '%' : '-';
        var resel = h.reselection;
        var newCandidates = resel && resel.s4 ? resel.s4.output_count : null;
        var detail = h.triggered && newCandidates != null ? ' 신규 후보 ' + newCandidates + '종목' : '';
        return '<p style="font-size:12px; padding-left:8px;">'
          + '· <strong>' + escapeHtml(h.slot || '-') + '</strong> ' + trigBadge
          + ' <span style="color:var(--muted);">' + escapeHtml(avg) + (detail ? ' →' + detail : '') + '</span>'
          + (h.reason ? '<br><span style="color:var(--muted);padding-left:12px;font-size:11px;">' + escapeHtml(h.reason.slice(0, 120)) + '</span>' : '')
          + '</p>';
      }).join('');
      el.innerHTML = '<p>' + escapeHtml(summary) + '</p>' + rows;
    } catch (e) {
      el.innerHTML = '<p class="muted">재선별 이력 조회 실패: ' + escapeHtml(e.message || '') + '</p>';
    }
  }

  /* 시장 톤 한국어 변환 */
  function _toneKr(tone) {
    return {
      bullish: '강세장', bearish: '약세장', mixed: '혼조세', volatile: '변동성 장세',
      negative: '부정적', positive: '긍정적', neutral: '중립'
    }[tone] || (tone || '파악 불가');
  }

  /* 매매 강도 한국어 변환 */
  function _intensityKr(intensity) {
    return {
      aggressive: '공격적', moderate: '보통', defensive: '수비적',
      conservative: '보수적', reduced: '축소', normal: '정상'
    }[intensity] || (intensity || null);
  }

  /* 수익률 문자열 (부호 포함) */
  function _pctStr(v) {
    var n = Number(v);
    if (!Number.isFinite(n)) return null;
    return (n >= 0 ? '+' : '') + n.toFixed(2) + '%';
  }

  /* ── BLOCK 1 — 오늘의 전략 컨텍스트 ── */
  function _nlContext(r) {
    var ta    = r.tone_analysis || {};
    var dp    = r.daily_plan   || {};
    var total = Number(r.total_orders  || 0);
    var buy   = Number(r.buy_orders    || 0);
    var sell  = Number(r.sell_orders   || 0);
    var pairs = r.trade_pairs        || [];
    var warns = r.integrity_warnings || [];
    var lines = [];

    // 장 시황 — AI 생성 요약 우선, 없으면 tone 코드로 폴백
    if (ta.summary) {
      lines.push('<p><strong>[장 시황]</strong> ' + escapeHtml(ta.summary) + '</p>');
    } else {
      var toneLabel = _toneKr(ta.tone || r.market_tone);
      lines.push('<p>오늘 시장은 <strong>' + escapeHtml(toneLabel) + '</strong>이었습니다.</p>');
    }

    // 주요 요인
    var kf = ta.key_factors || [];
    if (kf.length) {
      lines.push('<p><em>주요 요인:</em> ' + kf.map(function(f) { return escapeHtml(f); }).join(' / ') + '</p>');
    }

    // 전략 설정 — AI llm_summary 우선, 없으면 intensity+rulepack 폴백
    if (dp.llm_summary) {
      lines.push('<p><strong>[오늘 전략]</strong> ' + escapeHtml(dp.llm_summary) + '</p>');
    } else {
      var intensity = _intensityKr(dp.trading_intensity);
      var baseRp    = dp.base_rulepack_id || r.rulepack_id;
      if (intensity || baseRp) {
        lines.push('<p>전략 강도: <strong>' + (intensity || '기본') + '</strong>'
          + (baseRp ? ' · 기본 RulePack: <strong>' + escapeHtml(baseRp) + '</strong>' : '') + '</p>');
      }
    }

    // 파라미터 조정 (daily_overrides)
    var overrides = dp.daily_overrides || {};
    var oKeys = Object.keys(overrides);
    if (oKeys.length) {
      var oDesc = oKeys.map(function(k) {
        return '<code>' + escapeHtml(k) + '</code>: ' + escapeHtml(String(overrides[k]));
      }).join(', ');
      lines.push('<p>오늘 적용된 파라미터 조정: ' + oDesc + '</p>');
    }

    // 주문 현황
    if (total > 0) {
      lines.push('<p>시스템은 <strong>' + pairs.length + '개 종목</strong>에 매매를 실행했습니다. '
        + '매수 ' + buy + '건 / 매도 ' + sell + '건 처리됨.</p>');
    } else {
      lines.push('<p>오늘은 <strong>주문이 없었습니다.</strong> 스크리닝 조건 충족 종목 없거나 Daily Plan 미활성화.</p>');
    }

    if (warns.length) {
      lines.push('<p style="color:var(--yellow,#e3b341)">⚠ 무결성 경고 ' + warns.length + '건 — 손익 수치가 부정확할 수 있습니다.</p>');
    }

    return lines.join('');
  }

  /* ── BLOCK 2 — 매수 판단 결과 ── */
  function _nlResult(r) {
    var pairs       = r.trade_pairs || [];
    var dp          = r.daily_plan  || {};
    var assignments = dp.symbol_assignments || [];

    if (!pairs.length && !assignments.length) {
      return '<p class="muted">오늘 거래한 종목이 없습니다.</p>';
    }

    // symbol → assignment 맵 (AI 진입 판단 이유)
    var assignMap = {};
    assignments.forEach(function(a) { if (a.symbol) assignMap[a.symbol] = a; });

    var completed  = pairs.filter(function(p) { return p.status === '매도완료'; });
    var inProgress = pairs.filter(function(p) { return p.status !== '매도완료'; });
    var winners    = completed.filter(function(p) { return (p.pnl_pct || 0) > 0; });
    var losers     = completed.filter(function(p) { return (p.pnl_pct || 0) < 0; });

    var _avg = function(arr) {
      return arr.length ? arr.reduce(function(s, p) { return s + (p.pnl_pct || 0); }, 0) / arr.length : null;
    };
    var avgWin  = _avg(winners);
    var avgLoss = _avg(losers);
    var winRate = completed.length > 0 ? Math.round(winners.length / completed.length * 100) : 0;
    var sorted  = completed.slice().sort(function(a, b) { return (b.pnl_pct || 0) - (a.pnl_pct || 0); });
    var best    = sorted[0];
    var worst   = sorted[sorted.length - 1];

    var lines = [];

    // 요약 한 줄
    if (completed.length > 0) {
      var summary;
      if (winners.length > 0 && losers.length > 0) {
        summary = '<span class="good"><strong>' + winners.length + '건 수익</strong>'
          + (avgWin  != null ? ' (평균 +' + avgWin.toFixed(1) + '%)' : '') + '</span>'
          + ', <span class="bad"><strong>' + losers.length + '건 손실</strong>'
          + (avgLoss != null ? ' (평균 ' + avgLoss.toFixed(1) + '%)' : '') + '</span>'
          + '로 마감했습니다.';
      } else if (winners.length > 0) {
        summary = '<span class="good"><strong>전 건 수익</strong>'
          + (avgWin != null ? ' (평균 +' + avgWin.toFixed(1) + '%)' : '') + '</span>으로 마감했습니다.';
      } else if (losers.length > 0) {
        summary = '<span class="bad"><strong>전 건 손실</strong>'
          + (avgLoss != null ? ' (평균 ' + avgLoss.toFixed(1) + '%)' : '') + '</span>로 마감했습니다.';
      } else {
        summary = '손익 데이터가 아직 집계되지 않았습니다.';
      }
      lines.push('<p>완료 <strong>' + completed.length + '건</strong> 중 ' + summary + '</p>');
    }

    if (best && worst && best !== worst) {
      lines.push('<p>'
        + '최고: <strong>' + escapeHtml(best.name || best.symbol) + '</strong>'
        + (_pctStr(best.pnl_pct) ? ' <span class="good">' + _pctStr(best.pnl_pct) + '</span>' : '')
        + ' &nbsp;/&nbsp; '
        + '최저: <strong>' + escapeHtml(worst.name || worst.symbol) + '</strong>'
        + (_pctStr(worst.pnl_pct) ? ' <span class="bad">' + _pctStr(worst.pnl_pct) + '</span>' : '')
        + '</p>');
    }

    // 종목별 AI 진입 판단 → 실제 결과
    var allPairs = completed.concat(inProgress);
    if (allPairs.length > 0) {
      lines.push('<p style="margin-top:10px;font-size:12px;color:var(--muted)">종목별 내역 (AI 진입 판단 → 실제 결과):</p>');
      allPairs.forEach(function(p) {
        var a      = assignMap[p.symbol] || {};
        var reason = a.reason || a.entry_reason || null;
        var pctStr = _pctStr(p.pnl_pct);
        var pctSpan = pctStr
          ? ' <span class="' + ((p.pnl_pct || 0) >= 0 ? 'good' : 'bad') + '">' + pctStr + '</span>'
          : (p.status !== '매도완료' ? ' <span class="muted">(보유중)</span>' : '');
        lines.push('<p style="font-size:12px;padding-left:12px">'
          + '· <strong>' + escapeHtml(p.name || p.symbol) + '</strong>' + pctSpan
          + (reason ? '<br><span style="color:var(--muted);padding-left:8px">AI 판단: ' + escapeHtml(reason.slice(0, 120)) + '</span>' : '')
          + '</p>');
      });
    }

    // 승률 평가
    if (completed.length > 0) {
      var evalLine;
      if (winRate >= 70)      evalLine = '<span class="good">✓ 승률 ' + winRate + '% — 진입 판단이 전반적으로 좋았습니다.</span>';
      else if (winRate >= 50) evalLine = '<span style="color:var(--yellow,#e3b341)">△ 승률 ' + winRate + '% — 개선 여지가 있습니다.</span>';
      else                    evalLine = '<span class="bad">✗ 승률 ' + winRate + '% — 진입 기준을 재검토할 필요가 있습니다.</span>';
      lines.push('<p>' + evalLine + '</p>');
    }

    if (inProgress.length > 0) {
      lines.push('<p style="color:var(--muted);font-size:12px">※ 미청산 보유 ' + inProgress.length + '건: '
        + inProgress.map(function(p) { return escapeHtml(p.name || p.symbol); }).join(', ') + '</p>');
    }

    return lines.join('');
  }

  /* ── BLOCK 3 — 걸러낸 종목 ── */
  function _nlMissed(r) {
    var missed   = r.missed_entries    || [];
    var dp       = r.daily_plan        || {};
    var excluded = dp.excluded_symbols || [];

    if (!missed.length && !excluded.length) {
      return '<p>오늘은 걸러낸 종목이 없었습니다. 후보 전원이 매매로 이어졌거나 스크리닝 단계에서 후보가 없었습니다.</p>';
    }

    var lines = [];

    // AI 사전 제외 종목 (daily_plan.excluded_symbols — 장 시작 전 AI 판단)
    if (excluded.length) {
      lines.push('<p><strong>[장전 AI 제외] (' + excluded.length + '건)</strong></p>');
      excluded.forEach(function(e) {
        var reason = e.reason || e.excluded_reason || null;
        lines.push('<p style="font-size:12px;padding-left:12px">'
          + '· <strong>' + escapeHtml(e.name || e.symbol || '-') + '</strong>'
          + (reason ? ' — ' + escapeHtml(reason.slice(0, 120)) : '')
          + '</p>');
      });
    }

    // 런타임 미진입 (스크리닝 통과 후 실제 주문 미체결)
    if (missed.length) {
      lines.push('<p style="margin-top:10px"><strong>[미진입] 스크리닝 통과 후 미진입 (' + missed.length + '건)</strong></p>');
      var byStage = {};
      missed.forEach(function(m) {
        var s = m.missed_stage || m.source || '미분류';
        if (!byStage[s]) byStage[s] = [];
        byStage[s].push(m);
      });
      Object.keys(byStage).forEach(function(stage) {
        var items = byStage[stage];
        var names = items.slice(0, 5).map(function(m) {
          return '<strong>' + escapeHtml(m.symbol || m.name || '-') + '</strong>';
        }).join(', ') + (items.length > 5 ? ' 외 ' + (items.length - 5) + '건' : '');
        lines.push('<p style="font-size:12px;padding-left:12px"><em>' + escapeHtml(stage) + '</em>: ' + names + '</p>');
        var reason = (items[0] || {}).reason || (items[0] || {}).missed_reason;
        if (reason) {
          lines.push('<p style="color:var(--muted);font-size:12px;padding-left:24px">주요 사유: ' + escapeHtml(reason.slice(0, 120)) + '</p>');
        }
      });
    }

    lines.push('<p style="color:var(--yellow,#e3b341);margin-top:8px">[반성] 제외된 종목의 실제 등락을 확인하고, 진입 조건이 너무 좁게 설정된 것은 아닌지 검토하세요.</p>');
    return lines.join('');
  }

  /* ── BLOCK 4 — 손실 패턴 분석 ── */
  function _nlLoss(r) {
    var fp          = r.false_positives || [];
    var dp          = r.daily_plan      || {};
    var assignments = dp.symbol_assignments || [];

    if (!fp.length) {
      return '<p class="good">오늘은 손실 거래가 없었습니다.</p>';
    }

    // symbol → AI 진입 판단 맵
    var assignMap = {};
    assignments.forEach(function(a) { if (a.symbol) assignMap[a.symbol] = a; });

    var typeMap = { entry_fail: '진입 실패', early_exit: '조기 청산', wrong_profile: '프로파일 오류' };
    var byType  = {};
    fp.forEach(function(f) { var t = f.false_positive_type || '기타'; (byType[t] = byType[t] || []).push(f); });

    var byExit = {};
    fp.forEach(function(f) { var e = f.exit_reason || '미기록'; byExit[e] = (byExit[e] || 0) + 1; });

    var confArr = fp.filter(function(f) { return f.original_confidence != null; }).map(function(f) { return f.original_confidence; });
    var avgConf = confArr.length ? confArr.reduce(function(a, b) { return a + b; }, 0) / confArr.length : null;
    var minConf = confArr.length ? Math.min.apply(null, confArr) : null;

    var lines = [];
    lines.push('<p><strong>' + fp.length + '건</strong>의 손실 거래가 발생했습니다.</p>');

    var typeDesc = Object.keys(byType).map(function(t) {
      return (typeMap[t] || t) + ' ' + byType[t].length + '건';
    }).join(' / ');
    lines.push('<p>유형: ' + typeDesc + '</p>');

    if (avgConf != null) {
      lines.push('<p>진입 시점 평균 confidence: <strong>' + (avgConf * 100).toFixed(1) + '%</strong>'
        + (minConf != null ? ' (최저 ' + (minConf * 100).toFixed(1) + '%)' : '') + ' — '
        + (avgConf < 0.45
          ? '<span class="bad">낮은 confidence에서 진입한 케이스가 많습니다.</span>'
          : '비교적 높은 confidence에서도 손실이 발생했습니다. 시장 외부 변수를 검토하세요.')
        + '</p>');
    }

    var exitDesc = Object.keys(byExit).map(function(e) { return e + ' ' + byExit[e] + '건'; }).join(' / ');
    lines.push('<p>청산 사유: ' + exitDesc + '</p>');

    // 개별 종목 — AI 진입 판단 + 실제 손실 이유 함께 표시
    lines.push('<p style="margin-top:10px;font-size:12px;color:var(--muted)">종목별 손실 내역 (AI 진입 판단 → 실제 손실 원인):</p>');
    fp.forEach(function(f) {
      var a           = assignMap[f.symbol] || {};
      var entryReason = a.reason || a.entry_reason || null;
      var lossReason  = f.loss_reason || null;
      var pctStr = f.pnl_pct != null ? ' <span class="bad">' + _pctStr(f.pnl_pct) + '</span>' : '';
      lines.push('<p style="font-size:12px;padding-left:12px">'
        + '· <strong>' + escapeHtml(f.symbol_name || f.symbol) + '</strong>' + pctStr
        + (entryReason ? '<br><span style="color:var(--muted);padding-left:8px">AI 진입 판단: ' + escapeHtml(entryReason.slice(0, 100)) + '</span>' : '')
        + (lossReason  ? '<br><span style="color:var(--red,#f85149);padding-left:8px">손실 원인: '  + escapeHtml(lossReason.slice(0, 100))  + '</span>' : '')
        + '</p>');
    });

    // 반성 포인트
    var allEntryFail = Object.keys(byType).length === 1 && byType['entry_fail'];
    var allEod       = Object.keys(byExit).length === 1 && byExit['eod'];
    var lowConf      = avgConf != null && avgConf < 0.45;
    var reflections  = [];
    if (allEntryFail) reflections.push('손실 전 건이 진입 실패 유형 — 진입 조건 자체를 재검토하세요.');
    if (allEod)       reflections.push('전 건 EOD 청산 — 장중 손절(-5~8%) 조건을 추가하면 손실을 줄일 수 있습니다.');
    if (lowConf)      reflections.push('confidence가 낮은 종목을 진입하고 있습니다 — 임계값 상향을 권장합니다.');
    if (!reflections.length) reflections.push('패턴이 뚜렷하지 않습니다 — AI 진입 판단과 실제 결과의 괴리를 분석하세요.');

    lines.push('<p style="color:var(--red,#f85149);margin-top:8px">[반성] ' + reflections.join(' / ') + '</p>');
    return lines.join('');
  }

  /* 다음 거래일(월~금 기준) 계산 */
  function _nextTradingDay(fromDateStr) {
    var d = new Date(fromDateStr + 'T00:00:00');
    do { d.setDate(d.getDate() + 1); } while (d.getDay() === 0 || d.getDay() === 6);
    return d.getFullYear() + '-'
      + String(d.getMonth() + 1).padStart(2, '0') + '-'
      + String(d.getDate()).padStart(2, '0');
  }

  /* ── BLOCK 5 — 다음 거래일 액션 플랜 ── */
  function _nlTomorrow(r) {
    var fp       = r.false_positives    || [];
    var missed   = r.missed_entries     || [];
    var pairs    = r.trade_pairs        || [];
    var warns    = r.integrity_warnings || [];
    var dp       = r.daily_plan         || {};
    var ta       = r.tone_analysis      || {};

    var overrides    = dp.daily_overrides  || {};
    var riskFactors  = ta.risk_factors     || [];
    var completed    = pairs.filter(function(p) { return p.status === '매도완료'; });
    var winners      = completed.filter(function(p) { return (p.pnl_pct || 0) > 0; });
    var winRate      = completed.length > 0 ? winners.length / completed.length : 0;
    var eodAll       = completed.length > 0 && completed.every(function(p) { return p.exit_reason === 'eod'; });

    var confArr = fp.filter(function(f) { return f.original_confidence != null; }).map(function(f) { return f.original_confidence; });
    var avgConf = confArr.length ? confArr.reduce(function(a, b) { return a + b; }, 0) / confArr.length : null;

    // 다음 거래일 계산
    var nextDay = r.trade_date ? _nextTradingDay(r.trade_date) : null;

    // 추천 override 누적 (버튼 적용용)
    _raRecommendedOverrides = {};
    function recommend(key, value) { _raRecommendedOverrides[key] = value; }

    var items = [];
    var n = 0;
    function add(html) { n++; items.push('<p><strong>' + n + '.</strong> ' + html + '</p>'); }

    // 다음 거래일 표시
    if (nextDay) {
      items.push('<p style="color:var(--muted);font-size:12px;margin-bottom:8px">적용 대상: <strong>' + nextDay + '</strong> (다음 거래일)</p>');
    }

    // 오늘 daily_overrides 효과 평가
    var oKeys = Object.keys(overrides);
    if (oKeys.length) {
      var oDesc = oKeys.map(function(k) {
        return '<code>' + escapeHtml(k) + '=' + escapeHtml(String(overrides[k])) + '</code>';
      }).join(', ');
      if (winRate >= 0.6) {
        add('<strong>오늘 파라미터 조정 효과 확인</strong> — ' + oDesc
          + ' 설정으로 승률 ' + Math.round(winRate * 100) + '% 달성. 다음 거래일도 유지 권장.');
        // 유효했던 override 그대로 추천
        oKeys.forEach(function(k) { recommend(k, overrides[k]); });
      } else if (completed.length > 0 && winRate < 0.5) {
        add('<strong>파라미터 조정 재검토</strong> — 오늘 적용한 ' + oDesc
          + ' 에도 불구하고 승률 ' + Math.round(winRate * 100) + '%. 원래 설정 복원 검토.');
      }
    }

    // 리스크 요인 (정보성, override 없음)
    if (riskFactors.length) {
      add('<strong>다음 거래일 리스크 요인:</strong> '
        + riskFactors.map(function(f) { return escapeHtml(f); }).join(' / '));
    }

    // FP confidence 기반 → min_confidence 추천
    if (fp.length >= 3 && avgConf != null && avgConf < 0.5) {
      var rec = Math.ceil((avgConf + 0.07) * 20) * 5 / 100;  // 0.xx 형태
      recommend('min_confidence', rec);
      add('<strong>confidence 임계값 상향</strong> — 손실 ' + fp.length + '건 평균 진입 confidence <strong>'
        + (avgConf * 100).toFixed(0) + '%</strong>. <code>min_confidence → '
        + (rec * 100).toFixed(0) + '%</code> 적용 권장.');
    } else if (fp.length >= 2) {
      add('<strong>진입 필터 재검토</strong> — 손실 ' + fp.length + '건. S3/S4 파라미터 점검 필요.');
    } else if (fp.length === 1) {
      add('<strong>손실 종목 개별 확인</strong> — 단발 변수 가능성. 종목 뉴스·재무지표 재검토.');
    }

    // EOD 청산 집중 → stop_loss_pct 추천
    if (eodAll && fp.length > 0) {
      recommend('stop_loss_pct', -0.06);
      add('<strong>장중 손절 조건 추가</strong> — 손실 전 건 EOD 청산. <code>stop_loss_pct → -6%</code> 적용 권장.');
    } else if (eodAll && completed.length > 3) {
      add('<strong>익절 조건 점검</strong> — 완료 거래 전 건 EOD 청산. <code>take_profit_pct</code> 재확인 권장.');
    }

    // 놓친 기회
    if (missed.length > 3) {
      add('<strong>스크리닝 조건 완화 검토</strong> — 미진입 ' + missed.length + '건. S3/S4 필터 재검토.');
    }

    // 좋은 성과 — override 없음
    if (fp.length === 0 && winRate >= 0.7) {
      add('<strong>현재 전략 유지</strong> — 승률 ' + Math.round(winRate * 100) + '%, 손실 없음. 변경 불필요.');
    } else if (fp.length <= 1 && winRate >= 0.5) {
      add('<strong>전략 유지 + 모니터링</strong> — 승률 ' + Math.round(winRate * 100) + '% 양호. 추가 데이터 축적 중.');
    }

    // 무결성 경고
    if (warns.length) {
      add('<strong>체결 데이터 점검 필수</strong> — 무결성 경고 ' + warns.length + '건. fills 테이블 / KIS 체결 대조 후 재집계.');
    }

    if (!items.length) {
      items.push('<p class="good">특이사항 없음 — 현재 설정을 유지하세요.</p>');
    }

    return items.join('');
  }

  /* ── BLOCK 6 — 시스템 반영 내역 ── */
  function _nlSettingsApplied(r) {
    var llmReview = r.llm_review || {};
    var appliedSettings = llmReview.applied_settings || [];
    var appliedAt = llmReview.applied_at || '';
    var badgeEl = document.getElementById('ra-settings-applied-badge');
    var section = document.getElementById('ra-settings-applied-section');

    if (appliedSettings.length) {
      if (badgeEl) badgeEl.textContent = '자동 반영 ' + appliedSettings.length + '건' + (appliedAt ? ' · ' + appliedAt.slice(11,16) : '');
      if (section) section.style.display = 'block';
      return '<div>' + appliedSettings.map(function(s) {
        return '<div style="font-size:12px; padding:4px 0; border-bottom:1px solid var(--line);">'
          + '• ' + escapeHtml(s) + '</div>';
      }).join('') + '</div>';
    }

    // old_value == new_value인 항목(실제 변경 없음) 필터링
    var changes = (r.settings_changes || []).filter(function(c) {
      if (c.old_value === null || c.old_value === undefined) return true;
      return String(c.old_value) !== String(c.new_value);
    });
    if (section) section.style.display = changes.length ? 'block' : 'none';
    if (!changes.length) {
      return '<p class="muted">자동 반영된 설정 없음.</p>';
    }

    // actor별 표시 이름 매핑
    function actorLabel(actor) {
      if (!actor) return '시스템';
      if (actor === 's10_auto') return 'S10 자동반영';
      if (actor === 'ghost_timing_upgrade') return '귀신타이밍 전략 업그레이드';
      if (actor.startsWith('pm_manual')) return 'PM 수동 변경';
      if (actor === 'admin') return '관리자';
      if (actor.startsWith('scheduler')) return '스케줄러';
      return actor;
    }

    // 키 설명 매핑
    function keyLabel(key) {
      var m = {
        'engine.min_confidence_floor': 'AI 신뢰도 최소 기준',
        'engine.min_price_change_pct': '최소 등락률',
        'engine.max_price_change_pct': '최대 등락률',
        'engine.min_volume_ratio': '최소 거래량 비율',
        'engine.entry_start_time': '진입 시작 시간',
        'engine.entry_end_time': '진입 종료 시간',
        'override_stop_loss_rate': '손절 기준',
        'override_trailing_activate_rate': '트레일링 활성화 기준',
        'override_trailing_stop_rate': '트레일링 손절폭',
        'risk.daily_loss_limit_percent': '일일 손실 한도',
        'risk.max_positions': '최대 보유 종목 수',
      };
      return m[key] || key;
    }

    function fmtVal(v) {
      if (v === null || v === undefined) return '-';
      if (typeof v === 'number' && v < 1 && v > -1 && v !== 0) return (v * 100).toFixed(1) + '%';
      return String(v);
    }

    function fmtTime(iso) {
      if (!iso) return '';
      try {
        var d = new Date(iso);
        return (d.getMonth()+1) + '/' + d.getDate() + ' ' +
          String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0');
      } catch(e) { return iso.slice(11,16); }
    }

    var rows = changes.map(function(c) {
      var oldV = fmtVal(c.old_value);
      var newV = fmtVal(c.new_value);
      var arrow = oldV === '-' ? '' : oldV + ' → ';
      var actorBadge = '<span style="font-size:10px;color:var(--muted);background:var(--panel-2);padding:1px 5px;border-radius:3px;">' + escapeHtml(actorLabel(c.actor)) + '</span>';
      var timeStr = fmtTime(c.changed_at);
      return '<tr>'
        + '<td style="padding:6px 8px 6px 0; color:var(--muted); font-size:11px;">' + escapeHtml(timeStr) + '</td>'
        + '<td style="padding:6px 8px;">' + escapeHtml(keyLabel(c.key)) + '<br><span style="font-size:10px;color:var(--muted);">' + escapeHtml(c.key) + '</span></td>'
        + '<td style="padding:6px 8px; font-weight:600;">' + escapeHtml(arrow) + '<strong style="color:var(--green);">' + escapeHtml(newV) + '</strong></td>'
        + '<td style="padding:6px 0;">' + actorBadge + '</td>'
        + '</tr>'
        + (c.reason ? '<tr><td></td><td colspan="3" style="padding:0 8px 8px; font-size:11px; color:var(--muted);">' + escapeHtml(c.reason) + '</td></tr>' : '');
    }).join('');

    return '<table style="width:100%; border-collapse:collapse;">'
      + '<thead><tr>'
      + '<th style="text-align:left;padding:4px 8px 4px 0;font-size:11px;color:var(--muted);">시각</th>'
      + '<th style="text-align:left;padding:4px 8px;font-size:11px;color:var(--muted);">설정 항목</th>'
      + '<th style="text-align:left;padding:4px 8px;font-size:11px;color:var(--muted);">변경 값</th>'
      + '<th style="text-align:left;padding:4px 0;font-size:11px;color:var(--muted);">반영 주체</th>'
      + '</tr></thead>'
      + '<tbody>' + rows + '</tbody>'
      + '</table>';
  }

  /* 간이 Markdown → HTML 변환기 */
  function _mdToHtml(md) {
    if (!md) return '<p class="muted">내용 없음</p>';
    var lines  = md.split('\n');
    var html   = [];
    var inTable = false;
    var inUl    = false;

    function closeList() { if (inUl) { html.push('</ul>'); inUl = false; } }
    function closeTable() { if (inTable) { html.push('</tbody></table>'); inTable = false; } }

    function inlineRender(text) {
      return text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/`([^`]+)`/g, '<code style="background:var(--panel-2);padding:1px 4px;border-radius:3px">$1</code>');
    }

    lines.forEach(function(raw) {
      var line = raw;
      // 수평선
      if (/^---+$/.test(line.trim())) {
        closeList(); closeTable();
        html.push('<hr style="border:none;border-top:1px solid var(--line);margin:12px 0">');
        return;
      }
      // 표 행
      if (/^\|/.test(line)) {
        if (!inTable) { closeList(); html.push('<table style="width:100%;border-collapse:collapse;font-size:12px"><tbody>'); inTable = true; }
        if (/^\|[-| ]+\|$/.test(line.trim())) return; // 구분선 skip
        var cells = line.replace(/^\||\|$/g, '').split('|').map(function(c) { return c.trim(); });
        html.push('<tr>' + cells.map(function(c) {
          return '<td style="padding:4px 8px;border:1px solid var(--line)">' + inlineRender(c) + '</td>';
        }).join('') + '</tr>');
        return;
      }
      closeTable();
      // 제목
      if (/^### /.test(line)) { closeList(); html.push('<h4 style="margin:14px 0 6px;font-size:13px">' + inlineRender(line.slice(4)) + '</h4>'); return; }
      if (/^## /. test(line)) { closeList(); html.push('<h3 style="margin:18px 0 8px;font-size:15px">' + inlineRender(line.slice(3)) + '</h3>'); return; }
      if (/^# /.  test(line)) { closeList(); html.push('<h2 style="margin:20px 0 10px;font-size:17px;border-bottom:1px solid var(--line);padding-bottom:6px">' + inlineRender(line.slice(2)) + '</h2>'); return; }
      // 목록
      if (/^- /.test(line)) {
        if (!inUl) { html.push('<ul style="margin:4px 0 8px;padding-left:18px">'); inUl = true; }
        html.push('<li style="margin:2px 0">' + inlineRender(line.slice(2)) + '</li>');
        return;
      }
      closeList();
      // 빈 줄
      if (line.trim() === '') { html.push('<div style="height:6px"></div>'); return; }
      // 일반 문단
      html.push('<p style="margin:4px 0">' + inlineRender(line) + '</p>');
    });
    closeList();
    closeTable();
    return html.join('');
  }

  /* "자세히 보기" 모달 — 마크다운 렌더링 */
  function openReviewDetailModal() {
    if (!_raCurrentReport) {
      alert('먼저 날짜를 선택하고 조회하거나 S10을 실행하세요.');
      return;
    }
    var modal   = document.getElementById('ra-detail-modal');
    var viewer  = document.getElementById('ra-md-viewer');
    var titleEl = document.getElementById('ra-modal-title');
    if (!modal || !viewer) return;

    var r = _raCurrentReport;
    var d = new Date((r.trade_date || '') + 'T00:00:00');
    var dateLabel = r.trade_date ? ((d.getMonth() + 1) + '월 ' + d.getDate() + '일') : '-';
    if (titleEl) titleEl.textContent = dateLabel + ' 복기 보고서 전문';

    var md = r.md_content || '';
    if (!md && r.trade_date) {
      // md_content가 없으면 DB 데이터 기반으로 직접 마크다운 생성
      md = _buildFallbackMd(r);
    }
    viewer.innerHTML = _mdToHtml(md);
    modal.style.display = '';
  }

  function _buildFallbackMd(r) {
    var lines = [
      '# 복기 보고서 — ' + (r.trade_date || '-'),
      '',
      '## 요약',
      '| 항목 | 값 |',
      '|------|-----|',
      '| 시장 톤 | ' + (r.market_tone || '-') + ' |',
      '| RulePack | ' + (r.rulepack_id || '-') + ' |',
      '| 총 주문 | ' + (r.total_orders || 0) + '건 |',
      '| 실현 손익 | ' + (r.realized_pnl != null ? Number(r.realized_pnl).toLocaleString() + '원' : '-') + ' |',
      '| 놓친 기회 | ' + (r.missed_entries_count || 0) + '건 |',
      '| 손실 거래 | ' + (r.false_positive_count || 0) + '건 |',
      '',
      '> DB 보고서 전용 — S10 재실행 시 전체 마크다운 파일이 생성됩니다.',
    ];
    return lines.join('\n');
  }

  function closeReviewDetailModal() {
    var modal = document.getElementById('ra-detail-modal');
    if (modal) modal.style.display = 'none';
  }

  async function runReviewAudit() {
    var input = document.getElementById('ra-date-input');
    var today = new Date();
    var defaultDate = today.getFullYear() + '-'
      + String(today.getMonth() + 1).padStart(2, '0') + '-'
      + String(today.getDate()).padStart(2, '0');
    var targetDate = (input && input.value) ? input.value : defaultDate;

    if (!confirm(targetDate + ' S10 Review & Audit를 실행할까요?')) return;
    try {
      await fetch('/api/v1/review-audit/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date: targetDate }),
      });
      await _loadReviewByDateStr(targetDate);
    } catch (e) {
      alert('실행 실패: ' + e.message);
    }
  }

  // 레거시 — loadReviewAuditData는 이전 layout용. 현재 screen-review에서는 loadReviewAuditScreen 사용
  async function loadReviewAuditData() {
    try {
      const reviewRes = await fetch('/api/v1/review-audit/today');
      if (reviewRes.ok) {
        const reviewData = await reviewRes.json();
        const p = reviewData.payload || {};
        if (p.profile_summary) renderProfilePerformance(p.profile_summary);
        if (p.exit_summary) renderExitReason(p.exit_summary);
      }
    } catch (e) {
      console.warn('loadReviewAuditData error', e);
    }
  }

  function renderProfilePerformance(summary) {
    const tbody = document.getElementById('ra-profile-tbody');
    if (!tbody) return;
    const entries = Object.entries(summary);
    if (!entries.length) { tbody.innerHTML = '<tr><td colspan="4" class="muted">데이터 없음</td></tr>'; return; }
    tbody.innerHTML = entries.map(([profile, data]) => {
      const wr  = data.win_count && data.trade_count ? ((data.win_count / data.trade_count) * 100).toFixed(0) + '%' : '—';
      const pnl = data.avg_pnl != null ? (data.avg_pnl * 100).toFixed(2) + '%' : '—';
      return `<tr><td>${profile}</td><td>${data.trade_count || 0}</td><td>${wr}</td><td>${pnl}</td></tr>`;
    }).join('');
  }

  function renderExitReason(summary) {
    const tbody = document.getElementById('ra-exit-tbody');
    if (!tbody) return;
    const entries = Object.entries(summary);
    if (!entries.length) { tbody.innerHTML = '<tr><td colspan="3" class="muted">데이터 없음</td></tr>'; return; }
    tbody.innerHTML = entries.map(([reason, data]) => {
      const pnl = data.avg_pnl != null ? (data.avg_pnl * 100).toFixed(2) + '%' : '—';
      return `<tr><td>${reason}</td><td>${data.count || 0}</td><td>${pnl}</td></tr>`;
    }).join('');
  }

  /* ── Statistics ── */
