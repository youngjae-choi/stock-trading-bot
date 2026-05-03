# INBOX_EXECUTOR_trading_monitor_v2_fix — Trading Monitor 접근률 헬퍼 및 리스트 누락 보완

## 상황

`backend/static/console.html` 에서 Trading Monitor v2 작업이 대부분 완료됐으나 두 가지가 누락됐다.

1. **`_tmApproachBar`, `_buyColor`, `_sellColor` 함수 미존재** — HTML에 `tm-buy-list`, `tm-sell-list` 엘리먼트는 있으나 이 엘리먼트를 채울 헬퍼 함수들이 없다.
2. **`loadTradingMonitor()` 가 `tm-buy-list`, `tm-sell-list` 를 채우지 않음** — 현재 구현은 `loadAccountBalance()`, `loadPositionMonitoring()` 등 기존 함수를 호출할 뿐, 접근률 바를 렌더링하지 않는다.

## Task 1 — 헬퍼 함수 추가

`backend/static/console.html` 안에서 `async function loadTradingMonitor()` 선언 바로 직전에 아래 3개 함수를 삽입한다.

```javascript
  function _tmApproachBar(label, code, rate, colorFn) {
    var pct = Math.min(100, Math.max(0, rate));
    var color = colorFn(pct);
    return '<div style="display:flex; flex-direction:column; gap:4px;">'
      + '<div style="display:flex; justify-content:space-between; align-items:baseline;">'
      + '<span style="font-size:13px; font-weight:600;">' + escapeHtml(label) + '</span>'
      + '<span style="font-size:11px; color:var(--muted);">' + escapeHtml(code) + '</span>'
      + '</div>'
      + '<div style="display:flex; align-items:center; gap:8px;">'
      + '<div style="flex:1; background:var(--bg2); border-radius:4px; height:10px; overflow:hidden;">'
      + '<div style="width:' + pct + '%; height:100%; background:' + color + '; border-radius:4px; transition:width 0.8s ease;"></div>'
      + '</div>'
      + '<span style="font-size:12px; font-weight:700; min-width:36px; text-align:right; color:' + color + ';">' + pct.toFixed(0) + '%</span>'
      + '</div>'
      + '</div>';
  }

  function _buyColor(pct) {
    if (pct >= 80) return 'var(--green, #22c55e)';
    if (pct >= 50) return 'var(--yellow, #eab308)';
    return 'var(--muted, #888)';
  }

  function _sellColor(pct) {
    if (pct >= 80) return 'var(--red, #ef4444)';
    if (pct >= 50) return 'var(--yellow, #eab308)';
    return 'var(--muted, #888)';
  }
```

## Task 2 — `loadTradingMonitor()` 끝부분에 tm-buy-list / tm-sell-list 로딩 추가

현재 `loadTradingMonitor()` 함수의 마지막 3줄이 이렇게 되어 있다:

```javascript
    loadAccountBalance();
    loadPositionMonitoring();
    loadTodayOrders();
  }
```

이 부분을 아래로 교체한다 (기존 3줄 + 새 블록):

```javascript
    loadAccountBalance();
    loadPositionMonitoring();
    loadTodayOrders();

    // 매수 종목 모니터링 (S4 후보 접근률)
    try {
      var screeningData = await fetchJson('/api/v1/screening/today');
      var buyListEl = document.getElementById('tm-buy-list');
      if (buyListEl) {
        if (screeningData && screeningData.ok && screeningData.payload && screeningData.payload.candidates && screeningData.payload.candidates.length > 0) {
          var candidates = screeningData.payload.candidates.slice().sort(function(a, b) { return (b.confidence || 0) - (a.confidence || 0); });
          buyListEl.innerHTML = candidates.map(function(c) {
            var rate = (c.confidence || 0) * 100;
            return _tmApproachBar(c.name || c.ticker || c.symbol || '-', c.ticker || c.symbol || '-', rate, _buyColor);
          }).join('');
        } else {
          buyListEl.innerHTML = '<div style="color:var(--muted); font-size:13px; text-align:center; padding:20px 0;">오늘 S4 스크리닝 결과 없음</div>';
        }
      }
    } catch(e) {
      var buyListElErr = document.getElementById('tm-buy-list');
      if (buyListElErr) buyListElErr.innerHTML = '<div style="color:var(--muted); font-size:13px; text-align:center; padding:20px 0;">데이터 조회 실패</div>';
    }

    // 매도 종목 모니터링 (보유 포지션 청산 접근률)
    try {
      var balData = await fetchJson('/api/v1/account/balance');
      var sellListEl = document.getElementById('tm-sell-list');
      if (sellListEl && balData && balData.ok && balData.payload) {
        var holdings = balData.payload.holdings || [];
        if (holdings.length === 0) {
          sellListEl.innerHTML = '<div style="color:var(--muted); font-size:13px; text-align:center; padding:20px 0;">보유 포지션 없음</div>';
        } else {
          var withRate = holdings.map(function(h) {
            var pnl = h.pnl_pct || 0;
            var stopApproach = pnl < 0 ? Math.min(100, Math.abs(pnl) / 3.0 * 100) : 0;
            var profitApproach = pnl > 0 ? Math.min(100, pnl / 5.0 * 100) : 0;
            var rate = Math.max(stopApproach, profitApproach);
            return { name: h.name, symbol: h.symbol, rate: rate };
          }).sort(function(a, b) { return b.rate - a.rate; });
          sellListEl.innerHTML = withRate.map(function(h) {
            return _tmApproachBar(h.name || h.symbol || '-', h.symbol || '-', h.rate, _sellColor);
          }).join('');
        }
      }
    } catch(e) { /* ignore */ }
  }
```

## 완료 기준

작업 후 아래 스크립트로 검증한다:

```bash
python3 - <<'PY'
content = open('backend/static/console.html').read()
checks = [
  ('_tmApproachBar exists', '_tmApproachBar'),
  ('_buyColor exists', '_buyColor'),
  ('_sellColor exists', '_sellColor'),
  ('tm-buy-list populated', 'tm-buy-list'),
  ('tm-sell-list populated', 'tm-sell-list'),
]
for name, check in checks:
  print(f'{name}: {"OK" if check in content else "MISSING"}')
PY
```

OUTBOX: `docs/agent-comm/OUTBOX_EXECUTOR_trading_monitor_v2.md` (기존 파일에 이어서 작성)
