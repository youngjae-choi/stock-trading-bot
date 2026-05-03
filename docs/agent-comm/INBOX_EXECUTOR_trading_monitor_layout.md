# INBOX_EXECUTOR_trading_monitor_layout — Trading Monitor 레이아웃 재설계

## 작업 목적

현재 Trading Monitor(`screen-trading`)는 탭 방식이라 한 화면에서 볼 의미가 없다.
아래 레이아웃으로 완전히 교체한다. 파일은 `backend/static/console.html` 하나만 수정.

---

## 목표 레이아웃

```
┌──────────────────────────────────────────────────────┐
│  Trading Monitor (page-head)                         │
├──────────────────────┬───────────────────────────────┤
│  계좌 정보 (카드)     │  RulePack 조건 (카드)          │
│  계좌번호 / 예수금    │  매수 조건 (layer3_entry)       │
│  총평가 / 오늘 P&L    │  위험 한도 (risk_limits)        │
├──────────────────────┼───────────────────────────────┤
│  매수 후보 모니터링   │  보유 포지션 모니터링            │
│  (좌측 50%)          │  (우측 50%)                    │
│  - DE 상태+버튼       │  - 실시간 포지션 감시 테이블     │
│  - 오늘 매수 신호     │  - 오늘 주문내역                 │
│    테이블             │  - 전체청산 버튼                 │
└──────────────────────┴───────────────────────────────┘
```

---

## 구현 내용

### 1. `screen-trading` 전체 HTML 교체

현재 line 987~1116의 `<section class="screen" id="screen-trading">...</section>` 전체를
아래 HTML로 교체한다.

```html
<section class="screen" id="screen-trading">
  <div class="page-head">
    <div>
      <h1 class="page-title">Trading Monitor</h1>
      <p class="page-desc">계좌 상태와 RulePack 조건을 위에서 확인하고, 아래에서 매수 후보와 보유 포지션을 실시간으로 모니터링합니다.</p>
    </div>
    <button class="btn" onclick="loadTradingMonitor()">전체 새로고침</button>
  </div>

  <!-- 상단: 계좌정보 + RulePack 조건 -->
  <div style="display:flex; gap:16px; margin-bottom:16px; flex-wrap:wrap;">

    <!-- 계좌 정보 -->
    <div class="card" style="flex:1; min-width:260px;">
      <div class="card-title" style="display:flex; justify-content:space-between; align-items:center;">
        <span>계좌 정보</span>
        <button class="btn" onclick="loadAccountBalance()">새로고침</button>
      </div>
      <div style="font-size:12px; color:var(--muted); margin-bottom:8px;" id="tm-account-no">계좌번호: -</div>
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px;">
        <div style="background:var(--bg2); border-radius:6px; padding:10px;">
          <div style="font-size:11px; color:var(--muted); margin-bottom:4px;">예수금</div>
          <div style="font-size:16px; font-weight:700;" id="tm-deposit">-</div>
        </div>
        <div style="background:var(--bg2); border-radius:6px; padding:10px;">
          <div style="font-size:11px; color:var(--muted); margin-bottom:4px;">총평가금액</div>
          <div style="font-size:16px; font-weight:700;" id="tm-total-eval">-</div>
        </div>
        <div style="background:var(--bg2); border-radius:6px; padding:10px;">
          <div style="font-size:11px; color:var(--muted); margin-bottom:4px;">보유종목 수</div>
          <div style="font-size:16px; font-weight:700;" id="tm-holdings-count">-</div>
        </div>
        <div style="background:var(--bg2); border-radius:6px; padding:10px;">
          <div style="font-size:11px; color:var(--muted); margin-bottom:4px;">오늘 실현손익</div>
          <div style="font-size:16px; font-weight:700;" id="tm-pnl-today">-</div>
        </div>
      </div>
    </div>

    <!-- RulePack 조건 -->
    <div class="card" style="flex:1; min-width:260px;">
      <div class="card-title" style="display:flex; justify-content:space-between; align-items:center;">
        <span>오늘 RulePack 조건</span>
        <span id="tm-rulepack-id" style="font-size:11px; color:var(--muted);">-</span>
      </div>
      <div style="margin-bottom:10px;">
        <div style="font-size:11px; color:var(--muted); font-weight:600; margin-bottom:6px; text-transform:uppercase; letter-spacing:0.05em;">매수 조건 (Layer 3)</div>
        <div style="display:flex; flex-wrap:wrap; gap:6px;" id="tm-buy-conditions">
          <span style="background:var(--bg2); border-radius:4px; padding:4px 8px; font-size:12px;">로딩중...</span>
        </div>
      </div>
      <div>
        <div style="font-size:11px; color:var(--muted); font-weight:600; margin-bottom:6px; text-transform:uppercase; letter-spacing:0.05em;">위험 한도</div>
        <div style="display:flex; flex-wrap:wrap; gap:6px;" id="tm-risk-conditions">
          <span style="background:var(--bg2); border-radius:4px; padding:4px 8px; font-size:12px;">로딩중...</span>
        </div>
      </div>
    </div>

  </div>

  <!-- 하단: 좌우 분할 -->
  <div style="display:flex; gap:16px; align-items:flex-start; flex-wrap:wrap;">

    <!-- 좌측: 매수 후보 모니터링 -->
    <div style="flex:1; min-width:300px; display:flex; flex-direction:column; gap:16px;">

      <!-- Decision Engine 상태 -->
      <div class="card">
        <div class="card-title">Decision Engine</div>
        <div style="display:flex; flex-wrap:wrap; gap:12px; align-items:center; margin-bottom:12px;">
          <div style="font-size:13px;">상태: <span id="tm-engine-active" class="status warn">로딩중</span></div>
          <div style="font-size:13px;">WS: <span id="tm-engine-ws" style="color:var(--muted);">-</span></div>
          <div style="font-size:13px;">후보: <span id="tm-engine-candidates" style="color:var(--muted);">-</span>종목</div>
          <div style="font-size:13px;">신호: <span id="tm-engine-signals-sent" style="color:var(--muted);">-</span>건</div>
        </div>
        <div style="display:flex; gap:8px;">
          <button class="btn primary" onclick="liveDecisionActivate()">수동 활성화</button>
          <button class="btn" onclick="liveDecisionDeactivate()">비활성화</button>
        </div>
      </div>

      <!-- 오늘 매수 신호 -->
      <div class="card">
        <div class="card-title" style="display:flex; justify-content:space-between; align-items:center;">
          <span>오늘 매수 신호</span>
          <button class="btn" onclick="loadTradingMonitor()">새로고침</button>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>시간</th><th>종목</th><th>진입가</th><th>신뢰도</th><th>상태</th></tr>
            </thead>
            <tbody id="tm-signals-tbody">
              <tr><td colspan="5" class="muted" style="text-align:center;">신호 없음</td></tr>
            </tbody>
          </table>
        </div>
        <div style="margin-top:8px; font-size:11px; color:var(--muted);">KIS WebSocket은 S4 스크리닝 완료 후 자동 구독됩니다.</div>
      </div>

    </div>

    <!-- 우측: 보유 포지션 모니터링 -->
    <div style="flex:1; min-width:300px; display:flex; flex-direction:column; gap:16px;">

      <!-- 실시간 포지션 감시 -->
      <div class="card">
        <div class="card-title" style="display:flex; justify-content:space-between; align-items:center;">
          <span>실시간 포지션 감시</span>
          <div style="display:flex; gap:8px;">
            <button class="btn" onclick="loadPositionMonitoring()">새로고침</button>
            <button class="btn danger" onclick="liquidateAll()">전체 청산</button>
          </div>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>종목</th><th>수량</th><th>진입가</th><th>현재가</th><th>손익률</th><th>손절가</th><th>익절가</th><th>보유시간</th></tr>
            </thead>
            <tbody id="tm-monitor-tbody">
              <tr><td colspan="8" class="muted" style="text-align:center;">보유 포지션 없음</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 오늘 주문내역 -->
      <div class="card">
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

      <!-- 보유 종목 (KIS 계좌 실제 보유) -->
      <div class="card">
        <div class="card-title" style="display:flex; justify-content:space-between; align-items:center;">
          <span>KIS 계좌 보유종목</span>
          <button class="btn" onclick="loadAccountBalance()">새로고침</button>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>종목코드</th><th>종목명</th><th>수량</th><th>매입가</th><th>현재가</th><th>손익률</th></tr>
            </thead>
            <tbody id="tm-holdings-tbody">
              <tr><td colspan="6" class="muted" style="text-align:center;">보유 종목 없음</td></tr>
            </tbody>
          </table>
        </div>
      </div>

    </div>

  </div>
</section>
```

---

### 2. JS — `loadTradingMonitor()` 함수 수정

현재 `loadTradingMonitor()` 함수를 찾아 아래로 교체한다.
RulePack 조건 카드(`tm-buy-conditions`, `tm-risk-conditions`, `tm-rulepack-id`)를 채우는 로직을 추가한다.

```javascript
async function loadTradingMonitor() {
  // 1. Decision Engine 상태
  try {
    const r = await apiFetch('/api/v1/decision/status');
    if (r && r.ok && r.payload) {
      const p = r.payload;
      const el = document.getElementById('tm-engine-active');
      if (el) { el.textContent = p.active ? '활성' : '비활성'; el.className = 'status ' + (p.active ? 'ok' : 'warn'); }
      setTextSafe('tm-engine-ws', p.ws_connected ? '연결됨' : '미연결');
      setTextSafe('tm-engine-candidates', String(p.candidates_count ?? '-'));
      setTextSafe('tm-engine-signals-sent', String(p.signals_sent_today ?? '-'));
    }
  } catch(e) {}

  // 2. 오늘 매수 신호
  try {
    const r = await apiFetch('/api/v1/decision/signals/today');
    const tbody = document.getElementById('tm-signals-tbody');
    if (tbody && r && r.ok) {
      const signals = r.payload?.signals || [];
      if (signals.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="muted" style="text-align:center;">오늘 신호 없음</td></tr>';
      } else {
        tbody.innerHTML = signals.map(s => {
          const statusCls = s.status === 'executed' ? 'ok' : s.status === 'failed' ? 'error' : 'warn';
          const statusText = s.status === 'executed' ? '체결' : s.status === 'failed' ? '실패' : '대기';
          return `<tr>
            <td>${(s.created_at||'').slice(11,16)}</td>
            <td>${s.name||''}<br><span class="muted" style="font-size:11px;">${s.symbol||''}</span></td>
            <td>${s.entry_price ? Number(s.entry_price).toLocaleString()+'원' : '-'}</td>
            <td>${s.confidence != null ? (s.confidence*100).toFixed(0)+'%' : '-'}</td>
            <td><span class="status ${statusCls}">${statusText}</span></td>
          </tr>`;
        }).join('');
      }
    }
  } catch(e) {}

  // 3. RulePack 조건
  try {
    const r = await apiFetch('/api/v1/bot/rulepack/today');
    if (r && r.ok && r.payload) {
      const rp = r.payload;
      setTextSafe('tm-rulepack-id', rp.rulepack_id || '-');
      const mr = rp.machine_rules || {};
      const l3 = mr.layer3_entry || {};
      const rl = mr.risk_limits || {};

      const buyEl = document.getElementById('tm-buy-conditions');
      if (buyEl) {
        const items = [
          l3.vwap_position ? `VWAP: ${l3.vwap_position}` : null,
          l3.volume_ratio_min ? `거래량비: ≥${l3.volume_ratio_min}x` : null,
          l3.rsi_range ? `RSI: ${l3.rsi_range[0]}~${l3.rsi_range[1]}` : null,
          l3.ai_confidence_min != null ? `AI신뢰도: ≥${(l3.ai_confidence_min*100).toFixed(0)}%` : null,
          l3.ma5_above_ma20 != null ? (l3.ma5_above_ma20 ? 'MA5>MA20' : 'MA5 무관') : null,
          l3.spread_max_pct != null ? `스프레드: ≤${l3.spread_max_pct}%` : null,
        ].filter(Boolean);
        buyEl.innerHTML = items.length
          ? items.map(t => `<span style="background:var(--bg2); border-radius:4px; padding:4px 8px; font-size:12px;">${t}</span>`).join('')
          : '<span style="color:var(--muted); font-size:12px;">RulePack 없음</span>';
      }

      const riskEl = document.getElementById('tm-risk-conditions');
      if (riskEl) {
        const items = [
          rl.max_positions ? `최대포지션: ${rl.max_positions}개` : null,
          rl.daily_loss_limit_rate != null ? `일손절: ${(rl.daily_loss_limit_rate*100).toFixed(1)}%` : null,
          rl.position_size_pct ? `포지션비중: ${rl.position_size_pct}%` : null,
        ].filter(Boolean);
        riskEl.innerHTML = items.length
          ? items.map(t => `<span style="background:var(--bg2); border:1px solid var(--warn); border-radius:4px; padding:4px 8px; font-size:12px;">${t}</span>`).join('')
          : '<span style="color:var(--muted); font-size:12px;">한도 정보 없음</span>';
      }
    } else {
      ['tm-buy-conditions','tm-risk-conditions'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.innerHTML = '<span style="color:var(--muted); font-size:12px;">오늘 RulePack 없음</span>';
      });
    }
  } catch(e) {}

  // 4. 계좌/포지션/주문은 기존 함수 재사용
  loadAccountBalance();
  loadPositionMonitoring();
  loadTodayOrders();
}
```

`setTextSafe(id, text)` 헬퍼가 없으면 아래도 추가:
```javascript
function setTextSafe(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}
```
단, 이미 동일한 헬퍼(`setText` 또는 `setTextSafe`)가 있으면 재사용하고 중복 선언하지 말 것.

### 3. JS — `showTradingTab()` 함수 제거

`showTradingTab()` 함수는 더 이상 필요 없으니 삭제한다.
HTML에서도 `trading-tab-btn-buy`, `trading-tab-btn-sell` 등 탭 관련 id/onclick은 이미 위 HTML 교체로 사라진다.

### 4. `loadAccountBalance()` 에서 `tm-holdings-count` 갱신 추가

`loadAccountBalance()` 함수 내부에서 `tm-holdings-tbody` 업데이트 코드 근처에
아래를 추가한다:

```javascript
const cntEl = document.getElementById('tm-holdings-count');
if (cntEl) cntEl.textContent = holdings.length + '종목';
```

`holdings`는 해당 함수 내 계좌 보유 종목 배열 변수명으로 맞춘다.

---

## 완료 기준

```bash
# 1. Trading Monitor 탭 버튼 제거 확인
grep -c "trading-tab-btn" backend/static/console.html
# → 0 이어야 함

# 2. 새 레이아웃 요소 존재 확인
python3 -c "
content = open('backend/static/console.html').read()
checks = [
  ('tm-account-no', 'tm-account-no'),
  ('tm-buy-conditions', 'tm-buy-conditions'),
  ('tm-risk-conditions', 'tm-risk-conditions'),
  ('tm-engine-active', 'tm-engine-active'),
  ('tm-signals-tbody', 'tm-signals-tbody'),
  ('tm-monitor-tbody', 'tm-monitor-tbody'),
  ('tm-holdings-tbody', 'tm-holdings-tbody'),
  ('tm-orders-tbody', 'tm-orders-tbody'),
]
for name, pattern in checks:
  print(f'{name}: {\"OK\" if pattern in content else \"MISSING\"}')
"

# 3. showTradingTab 제거 확인
python3 -c "
content = open('backend/static/console.html').read()
print('showTradingTab removed:', 'showTradingTab' not in content)
"
```

OUTBOX: `docs/agent-comm/OUTBOX_EXECUTOR_trading_monitor_layout.md`
