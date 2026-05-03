# INBOX_EXECUTOR_trading_monitor_v2 — Trading Monitor 전면 재설계

## 작업 목적

Trading Monitor(`screen-trading`)를 실질적인 실시간 감시 화면으로 재설계한다.
파일은 `backend/static/console.html` 하나만 수정한다.

---

## 핵심 개념

**매수 모니터링**: S4 Hybrid Screening 후보 종목들이 매수 신호 조건에 얼마나 가까운지 (접근률 = AI confidence score)
**매도 모니터링**: 이미 체결되어 보유 중인 종목들이 청산 조건에 얼마나 가까운지 (접근률 = max(손절접근률, 익절접근률))
- 접근률 높은 순 자동 정렬
- 10초마다 자동 갱신 (화면이 활성화된 동안만)

**제거 항목**:
- 실시간 포지션 감시 테이블 (컬럼 10개짜리) → 완전 제거
- 주문내역 카드 → Trading Monitor에서 제거, Today Control 하단으로 이동

**Decision Engine 토글**: 상단 page-head 오른쪽에 토글 버튼만 배치. 상세 카드 불필요.

---

## 목표 레이아웃

```
┌────────────────────────────────────────────────────────────────┐
│ Trading Monitor            [● DE 활성  토글버튼]  [전체새로고침] │
├─────────────────────────┬──────────────────────────────────────┤
│ 계좌 정보                │ 오늘 RulePack 조건                    │
│ 예수금 / 총평가          │ 매수조건 뱃지들 / 위험한도 뱃지들       │
├─────────────────────────┼──────────────────────────────────────┤
│ 매수 종목 모니터링       │ 매도 종목 모니터링                      │
│ (S4 후보 → 접근률 순)    │ (보유 포지션 → 접근률 순)               │
│                         │                                        │
│ 종목명/코드 + 접근률bar   │ 종목명/코드 + 접근률bar                 │
│ 자동갱신 카운터           │ 자동갱신 카운터                         │
└─────────────────────────┴────────────────────────────────────┘
```

---

## Task 1 — `screen-trading` 전체 교체

현재 line 987~1116의 `<section class="screen" id="screen-trading">...</section>` 전체를
아래 HTML로 교체한다.

```html
<section class="screen" id="screen-trading">
  <div class="page-head">
    <div>
      <h1 class="page-title">Trading Monitor</h1>
      <p class="page-desc">매수 후보와 보유 포지션의 신호 접근률을 실시간으로 감시합니다.</p>
    </div>
    <div style="display:flex; gap:8px; align-items:center;">
      <button id="tm-de-toggle" class="btn" onclick="toggleDecisionEngine()" style="min-width:120px;">
        <span id="tm-de-label">DE 상태 로딩중</span>
      </button>
      <button class="btn" onclick="loadTradingMonitor()">새로고침</button>
    </div>
  </div>

  <!-- 상단: 계좌정보 + RulePack 조건 -->
  <div style="display:flex; gap:16px; margin-bottom:16px; flex-wrap:wrap;">

    <div class="card" style="flex:1; min-width:240px;">
      <div class="card-title" style="display:flex; justify-content:space-between;">
        <span>계좌 정보</span>
        <button class="btn" style="font-size:11px; padding:2px 8px;" onclick="loadAccountBalance()">새로고침</button>
      </div>
      <div style="font-size:11px; color:var(--muted); margin-bottom:8px;" id="tm-account-no">계좌번호: -</div>
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px;">
        <div style="background:var(--bg2); border-radius:6px; padding:8px 10px;">
          <div style="font-size:10px; color:var(--muted); margin-bottom:2px;">예수금</div>
          <div style="font-size:14px; font-weight:700;" id="tm-deposit">-</div>
        </div>
        <div style="background:var(--bg2); border-radius:6px; padding:8px 10px;">
          <div style="font-size:10px; color:var(--muted); margin-bottom:2px;">총평가금액</div>
          <div style="font-size:14px; font-weight:700;" id="tm-total-eval">-</div>
        </div>
        <div style="background:var(--bg2); border-radius:6px; padding:8px 10px;">
          <div style="font-size:10px; color:var(--muted); margin-bottom:2px;">보유종목</div>
          <div style="font-size:14px; font-weight:700;" id="tm-holdings-count">-</div>
        </div>
        <div style="background:var(--bg2); border-radius:6px; padding:8px 10px;">
          <div style="font-size:10px; color:var(--muted); margin-bottom:2px;">오늘 실현손익</div>
          <div style="font-size:14px; font-weight:700;" id="tm-pnl-today">-</div>
        </div>
      </div>
    </div>

    <div class="card" style="flex:1; min-width:240px;">
      <div class="card-title">
        오늘 매매 조건
        <span id="tm-rulepack-id" style="font-size:10px; color:var(--muted); font-weight:400; margin-left:8px;">-</span>
      </div>
      <div style="margin-bottom:10px;">
        <div style="font-size:10px; color:var(--muted); font-weight:600; margin-bottom:6px; letter-spacing:0.05em;">매수 조건</div>
        <div style="display:flex; flex-wrap:wrap; gap:5px;" id="tm-buy-conditions">
          <span style="background:var(--bg2); border-radius:4px; padding:3px 7px; font-size:11px; color:var(--muted);">로딩중</span>
        </div>
      </div>
      <div>
        <div style="font-size:10px; color:var(--muted); font-weight:600; margin-bottom:6px; letter-spacing:0.05em;">위험 한도</div>
        <div style="display:flex; flex-wrap:wrap; gap:5px;" id="tm-risk-conditions">
          <span style="background:var(--bg2); border-radius:4px; padding:3px 7px; font-size:11px; color:var(--muted);">로딩중</span>
        </div>
      </div>
    </div>

  </div>

  <!-- 하단: 매수/매도 모니터링 2열 -->
  <div style="display:flex; gap:16px; align-items:flex-start; flex-wrap:wrap;">

    <!-- 좌: 매수 종목 모니터링 -->
    <div class="card" style="flex:1; min-width:280px;">
      <div class="card-title" style="display:flex; justify-content:space-between; align-items:center;">
        <span>매수 종목 모니터링</span>
        <span id="tm-buy-refresh-countdown" style="font-size:11px; color:var(--muted);">10s</span>
      </div>
      <p style="font-size:11px; color:var(--muted); margin-bottom:12px;">S4 후보 종목의 매수 신호 접근률 (AI 신뢰도 기준). 높을수록 매수 조건에 근접.</p>
      <div id="tm-buy-list" style="display:flex; flex-direction:column; gap:10px;">
        <div style="color:var(--muted); font-size:13px; text-align:center; padding:20px 0;">데이터 로딩중...</div>
      </div>
    </div>

    <!-- 우: 매도 종목 모니터링 -->
    <div class="card" style="flex:1; min-width:280px;">
      <div class="card-title" style="display:flex; justify-content:space-between; align-items:center;">
        <span>매도 종목 모니터링</span>
        <span id="tm-sell-refresh-countdown" style="font-size:11px; color:var(--muted);">10s</span>
      </div>
      <p style="font-size:11px; color:var(--muted); margin-bottom:12px;">보유 포지션의 청산 조건 접근률. 손절/익절 중 더 가까운 쪽 기준. 높을수록 청산 임박.</p>
      <div id="tm-sell-list" style="display:flex; flex-direction:column; gap:10px;">
        <div style="color:var(--muted); font-size:13px; text-align:center; padding:20px 0;">데이터 로딩중...</div>
      </div>
    </div>

  </div>
</section>
```

---

## Task 2 — JS 함수 교체/추가

현재 `loadTradingMonitor()` 함수를 찾아 아래로 완전 교체한다.
`showTradingTab()` 함수는 삭제한다.

### 접근률 바 렌더링 헬퍼 추가

```javascript
function _tmApproachBar(label, code, rate, colorFn) {
  // rate: 0~100 숫자
  const pct = Math.min(100, Math.max(0, rate));
  const color = colorFn(pct);
  return `
    <div style="display:flex; flex-direction:column; gap:4px;">
      <div style="display:flex; justify-content:space-between; align-items:baseline;">
        <span style="font-size:13px; font-weight:600;">${label}</span>
        <span style="font-size:11px; color:var(--muted);">${code}</span>
      </div>
      <div style="display:flex; align-items:center; gap:8px;">
        <div style="flex:1; background:var(--bg2); border-radius:4px; height:10px; overflow:hidden;">
          <div style="width:${pct}%; height:100%; background:${color}; border-radius:4px; transition:width 0.8s ease;"></div>
        </div>
        <span style="font-size:12px; font-weight:700; min-width:36px; text-align:right; color:${color};">${pct.toFixed(0)}%</span>
      </div>
    </div>`;
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

### `loadTradingMonitor()` 교체

```javascript
async function loadTradingMonitor() {
  // 1. Decision Engine 토글 상태 갱신
  try {
    const r = await apiFetch('/api/v1/decision/status');
    if (r && r.ok && r.payload) {
      const active = r.payload.active;
      const btn = document.getElementById('tm-de-toggle');
      const lbl = document.getElementById('tm-de-label');
      if (btn && lbl) {
        lbl.textContent = active ? '● DE 활성' : '○ DE 비활성';
        btn.className = 'btn ' + (active ? 'primary' : '');
        btn._deActive = active;
      }
    }
  } catch(e) {}

  // 2. RulePack 조건
  try {
    const r = await apiFetch('/api/v1/bot/rulepack/today');
    if (r && r.ok && r.payload) {
      const rp = r.payload;
      const idEl = document.getElementById('tm-rulepack-id');
      if (idEl) idEl.textContent = rp.rulepack_id || '-';
      const mr = rp.machine_rules || {};
      const l3 = mr.layer3_entry || {};
      const rl = mr.risk_limits || {};

      const buyEl = document.getElementById('tm-buy-conditions');
      if (buyEl) {
        const items = [
          l3.vwap_position ? `VWAP: ${l3.vwap_position}` : null,
          l3.volume_ratio_min != null ? `거래량비 ≥${l3.volume_ratio_min}x` : null,
          l3.rsi_range ? `RSI ${l3.rsi_range[0]}~${l3.rsi_range[1]}` : null,
          l3.ai_confidence_min != null ? `AI ≥${(l3.ai_confidence_min*100).toFixed(0)}%` : null,
          l3.ma5_above_ma20 != null ? (l3.ma5_above_ma20 ? 'MA5>MA20' : 'MA5무관') : null,
        ].filter(Boolean);
        buyEl.innerHTML = items.map(t =>
          `<span style="background:var(--bg2); border-radius:4px; padding:3px 7px; font-size:11px;">${t}</span>`
        ).join('') || '<span style="color:var(--muted); font-size:11px;">정보 없음</span>';
      }

      const riskEl = document.getElementById('tm-risk-conditions');
      if (riskEl) {
        const items = [
          rl.max_positions ? `최대 ${rl.max_positions}포지션` : null,
          rl.daily_loss_limit_rate != null ? `일손절 ${(rl.daily_loss_limit_rate*100).toFixed(1)}%` : null,
          rl.position_size_pct ? `비중 ${rl.position_size_pct}%` : null,
        ].filter(Boolean);
        riskEl.innerHTML = items.map(t =>
          `<span style="background:var(--bg2); border:1px solid var(--warn,#f59e0b); border-radius:4px; padding:3px 7px; font-size:11px;">${t}</span>`
        ).join('') || '<span style="color:var(--muted); font-size:11px;">정보 없음</span>';
      }
    } else {
      ['tm-buy-conditions','tm-risk-conditions'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.innerHTML = '<span style="color:var(--muted); font-size:11px;">오늘 RulePack 없음</span>';
      });
    }
  } catch(e) {}

  // 3. 매수 종목 모니터링 (S4 후보 접근률)
  try {
    const r = await apiFetch('/api/v1/screening/today');
    const listEl = document.getElementById('tm-buy-list');
    if (listEl) {
      if (r && r.ok && r.payload && r.payload.candidates && r.payload.candidates.length > 0) {
        const candidates = [...r.payload.candidates]
          .sort((a, b) => (b.confidence || 0) - (a.confidence || 0));
        listEl.innerHTML = candidates.map(c => {
          const rate = ((c.confidence || 0) * 100);
          return _tmApproachBar(c.name || c.ticker, c.ticker, rate, _buyColor);
        }).join('');
      } else {
        listEl.innerHTML = '<div style="color:var(--muted); font-size:13px; text-align:center; padding:20px 0;">오늘 S4 스크리닝 결과 없음</div>';
      }
    }
  } catch(e) {
    const listEl = document.getElementById('tm-buy-list');
    if (listEl) listEl.innerHTML = '<div style="color:var(--muted); font-size:13px; text-align:center; padding:20px 0;">데이터 조회 실패</div>';
  }

  // 4. 매도 종목 모니터링 (보유 포지션 청산 접근률)
  try {
    const r = await apiFetch('/api/v1/account/balance');
    const listEl = document.getElementById('tm-sell-list');
    const accountNo = document.getElementById('tm-account-no');
    const depositEl = document.getElementById('tm-deposit');
    const totalEl = document.getElementById('tm-total-eval');
    const countEl = document.getElementById('tm-holdings-count');
    const pnlEl = document.getElementById('tm-pnl-today');

    if (r && r.ok && r.payload) {
      const p = r.payload;
      if (accountNo) accountNo.textContent = '계좌번호: ' + (p.account_no || '-');
      if (depositEl) depositEl.textContent = p.deposit ? Number(p.deposit).toLocaleString() + '원' : '-';
      if (totalEl) totalEl.textContent = p.total_eval ? Number(p.total_eval).toLocaleString() + '원' : '-';

      const holdings = p.holdings || [];
      if (countEl) countEl.textContent = holdings.length + '종목';
      if (pnlEl) pnlEl.textContent = p.total_pnl_pct != null ? (p.total_pnl_pct >= 0 ? '+' : '') + p.total_pnl_pct.toFixed(2) + '%' : '-';

      // tm-holdings-tbody 동기화 (기존 positions 화면용)
      const holdingsTbody = document.getElementById('tm-holdings-tbody');
      if (holdingsTbody) {
        holdingsTbody.innerHTML = holdings.length === 0
          ? '<tr><td colspan="6" class="muted" style="text-align:center;">보유 종목 없음</td></tr>'
          : holdings.map(h => `<tr>
              <td>${h.symbol||''}</td><td>${h.name||''}</td><td>${h.qty||0}</td>
              <td>${h.avg_price?Number(h.avg_price).toLocaleString():'-'}</td>
              <td>${h.current_price?Number(h.current_price).toLocaleString():'-'}</td>
              <td class="${(h.pnl_pct||0)>=0?'green':'red'}">${h.pnl_pct!=null?(h.pnl_pct>=0?'+':'')+h.pnl_pct.toFixed(2)+'%':'-'}</td>
            </tr>`).join('');
      }

      if (listEl) {
        if (holdings.length === 0) {
          listEl.innerHTML = '<div style="color:var(--muted); font-size:13px; text-align:center; padding:20px 0;">보유 포지션 없음</div>';
        } else {
          // 접근률: |pnl_pct| / 청산기준(3%) 기준으로 근사. 실제 stop_loss/take_profit 없으면 abs(pnl_pct)/3.0
          const withRate = holdings.map(h => {
            const pnl = h.pnl_pct || 0;
            // 손절 -3%, 익절 +5% 기준 (RulePack 없을 때 기본값)
            const stopApproach = pnl < 0 ? Math.min(100, Math.abs(pnl) / 3.0 * 100) : 0;
            const profitApproach = pnl > 0 ? Math.min(100, pnl / 5.0 * 100) : 0;
            const rate = Math.max(stopApproach, profitApproach);
            return { ...h, rate };
          }).sort((a, b) => b.rate - a.rate);

          listEl.innerHTML = withRate.map(h =>
            _tmApproachBar(h.name || h.symbol, h.symbol, h.rate, _sellColor)
          ).join('');
        }
      }
    }
  } catch(e) {}
}
```

### `toggleDecisionEngine()` 추가

```javascript
async function toggleDecisionEngine() {
  const btn = document.getElementById('tm-de-toggle');
  const isActive = btn && btn._deActive;
  if (isActive) {
    await liveDecisionDeactivate();
  } else {
    await liveDecisionActivate();
  }
  // 상태 갱신
  setTimeout(loadTradingMonitor, 500);
}
```

### 자동갱신 카운터 설정

`showScreen()` 함수 내 `name === "trading"` 분기에서 기존 `loadTradingMonitor()` 호출 이후
아래 카운터 로직을 추가한다 (기존에 있으면 교체):

```javascript
// Trading Monitor 자동갱신
if (window._tmRefreshInterval) clearInterval(window._tmRefreshInterval);
let tmCountdown = 10;
const updateCounters = () => {
  const b = document.getElementById('tm-buy-refresh-countdown');
  const s = document.getElementById('tm-sell-refresh-countdown');
  if (b) b.textContent = tmCountdown + 's';
  if (s) s.textContent = tmCountdown + 's';
  tmCountdown--;
  if (tmCountdown < 0) { tmCountdown = 10; loadTradingMonitor(); }
};
window._tmRefreshInterval = setInterval(updateCounters, 1000);
```

다른 화면으로 이동 시(`showScreen(name)` 에서 name !== "trading"일 때):
```javascript
if (window._tmRefreshInterval) { clearInterval(window._tmRefreshInterval); window._tmRefreshInterval = null; }
```
이 줄은 `showScreen()` 함수 시작 부분에 추가하면 된다.

---

## Task 3 — 오늘 주문내역을 Today Control 하단으로 이동

`screen-today` 섹션의 맨 마지막 카드 뒤에 아래를 추가한다.

```html
<div class="section-gap"></div>
<div class="card" id="today-orders-card">
  <div class="card-title" style="display:flex; justify-content:space-between; align-items:center;">
    <span>오늘 주문내역</span>
    <button class="btn" onclick="loadTodayOrders()">새로고침</button>
  </div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>시간</th><th>종목</th><th>구분</th><th>수량</th><th>가격</th><th>상태</th></tr>
      </thead>
      <tbody id="tm-orders-tbody">
        <tr><td colspan="6" class="muted" style="text-align:center;">주문내역 없음</td></tr>
      </tbody>
    </table>
  </div>
</div>
```

`loadTodayOrders()` 함수가 `tm-orders-tbody`를 타겟으로 쓰면 그대로 연결된다.

---

## Task 4 — `showTradingTab()` 함수 삭제 확인

파일에 `showTradingTab` 정의가 남아 있으면 삭제한다.
`trading-tab-btn-buy`, `trading-tab-btn-sell`, `trading-tab-buy`, `trading-tab-sell` 등
탭 관련 id 참조도 JS에서 모두 제거한다.

---

## 완료 기준

```bash
python3 - <<'PY'
content = open('backend/static/console.html').read()
checks = [
  ('tm-buy-list exists', 'id="tm-buy-list"'),
  ('tm-sell-list exists', 'id="tm-sell-list"'),
  ('tm-de-toggle exists', 'id="tm-de-toggle"'),
  ('tm-buy-conditions exists', 'id="tm-buy-conditions"'),
  ('tm-risk-conditions exists', 'id="tm-risk-conditions"'),
  ('_tmApproachBar exists', '_tmApproachBar'),
  ('loadTradingMonitor exists', 'function loadTradingMonitor'),
  ('toggleDecisionEngine exists', 'toggleDecisionEngine'),
  ('_tmRefreshInterval exists', '_tmRefreshInterval'),
  ('tab buttons removed', 'trading-tab-btn' not in content),
  ('showTradingTab removed', 'showTradingTab' not in content),
  ('today-orders-card in screen-today', 'today-orders-card' in content),
]
for name, check in checks:
  if isinstance(check, bool):
    print(f'{name}: {"OK" if check else "MISSING"}')
  else:
    print(f'{name}: {"OK" if check in content else "MISSING"}')
PY
```

OUTBOX: `docs/agent-comm/OUTBOX_EXECUTOR_trading_monitor_v2.md`
