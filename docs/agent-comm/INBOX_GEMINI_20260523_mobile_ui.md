# INBOX — Gemini Frontend Agent
# 발신: Sisyphus (PM 승인 완료)
# 날짜: 2026-05-23
# 제목: 모바일 UI 최적화 — Phase 1~3 구현

---

## 배경

Kairos 콘솔은 현재 860px 이하 모바일에서 `<select>` 드롭다운 하나로 화면을 전환한다.
PM(운영자)은 모바일에서 주로 모니터링 목적으로 사용하며, **세로모드에서 한눈에 Trading Monitor가 보여야 한다**는 요구가 있다.
이번 작업은 모바일 UX를 Bottom Tab Bar + 카드형 레이아웃으로 전면 개선한다.

---

## 작업 범위

| Phase | 내용 | 우선순위 |
|-------|------|----------|
| 1 | Bottom Tab Bar 구현 (select 드롭다운 대체) | 필수 |
| 2 | Trading Monitor 세로모드 카드 레이아웃 | 필수 |
| 3 | Today Control / Missed Entries / Daily Results 카드 변환 | 권장 |

---

## Phase 1 — Bottom Tab Bar

### 1-A. HTML 변경 (`backend/static/console.html`)

**현재 (line ~68-90):**
```html
<div class="mobile-nav-row">
  <select id="mobileMenu" class="mobile-menu" aria-label="화면 선택">
    <option value="today">Today Control</option>
    <option value="trading">Trading Monitor</option>
    ...
  </select>
  <span class="mobile-date-label">기준일<strong id="mobileDateLabel">--</strong></span>
</div>
```

**변경 후:**
```html
<div class="mobile-nav-row">
  <!-- 기존 select는 유지하되 숨김 처리 (JS 호환성) -->
  <select id="mobileMenu" class="mobile-menu" aria-label="화면 선택" style="display:none">
    <option value="today">Today Control</option>
    <option value="trading">Trading Monitor</option>
    <option value="rulepack">Daily Plan</option>
    <option value="shadow-trading">Missed Entries</option>
    <option value="daily-results">Daily Results</option>
    <option value="dividends">Dividend Entry</option>
    <option value="dividend-stats">Statistics</option>
    <option value="statistics">Trade History</option>
    <option value="funnel">Funnel Monitor</option>
    <option value="review">Trade Review</option>
    <option value="data">System Status</option>
    <option value="settings">Settings</option>
  </select>
  <span class="mobile-date-label">기준일<strong id="mobileDateLabel">--</strong></span>
</div>
```

**`</body>` 직전에 추가 (Bottom Tab Bar HTML):**
```html
<!-- Bottom Tab Bar — 모바일 전용 -->
<nav class="bottom-tab-bar" id="bottomTabBar" aria-label="모바일 하단 메뉴">
  <button class="tab-item active" data-screen="today" aria-label="Today Control">
    <svg class="tab-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>
      <rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>
    </svg>
    <span class="tab-label">오늘</span>
  </button>
  <button class="tab-item" data-screen="trading" aria-label="Trading Monitor">
    <svg class="tab-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <polyline points="2,17 8,11 12,15 18,8"/><polyline points="16,8 18,8 18,10"/>
    </svg>
    <span class="tab-label">모니터</span>
  </button>
  <button class="tab-item" data-screen="rulepack" aria-label="Daily Plan">
    <svg class="tab-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <rect x="3" y="4" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/>
      <line x1="9" y1="4" x2="9" y2="9"/>
    </svg>
    <span class="tab-label">플랜</span>
  </button>
  <button class="tab-item" data-screen="shadow-trading" aria-label="Missed Entries">
    <svg class="tab-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <circle cx="12" cy="12" r="9"/><line x1="12" y1="8" x2="12" y2="12"/>
      <line x1="12" y1="16" x2="12.01" y2="16"/>
    </svg>
    <span class="tab-label">미진입</span>
  </button>
  <button class="tab-item" data-screen="more-menu" aria-label="더보기">
    <svg class="tab-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <circle cx="5" cy="12" r="1.5" fill="currentColor"/><circle cx="12" cy="12" r="1.5" fill="currentColor"/>
      <circle cx="19" cy="12" r="1.5" fill="currentColor"/>
    </svg>
    <span class="tab-label">더보기</span>
  </button>
</nav>

<!-- 더보기 드로어 -->
<div class="more-drawer" id="moreDrawer" style="display:none">
  <div class="more-drawer-backdrop" id="moreDrawerBackdrop"></div>
  <div class="more-drawer-panel">
    <div class="more-drawer-title">메뉴</div>
    <button class="more-drawer-item" data-screen="daily-results">Daily Results</button>
    <button class="more-drawer-item" data-screen="dividends">Dividend Entry</button>
    <button class="more-drawer-item" data-screen="dividend-stats">Statistics</button>
    <button class="more-drawer-item" data-screen="statistics">Trade History</button>
    <button class="more-drawer-item" data-screen="review">Trade Review</button>
    <button class="more-drawer-item" data-screen="funnel">Funnel Monitor</button>
    <button class="more-drawer-item" data-screen="data">System Status</button>
    <button class="more-drawer-item" data-screen="settings">Settings</button>
  </div>
</div>
```

---

### 1-B. CSS 추가 (`backend/static/css/console.css`)

`@media (max-width: 860px)` 블록 내부(또는 파일 끝)에 추가:

```css
/* ── Bottom Tab Bar ── */
.bottom-tab-bar {
  display: none;
}

@media (max-width: 860px) {
  /* 콘텐츠 영역에 하단 바 높이만큼 패딩 추가 */
  .main {
    padding-bottom: 68px;
  }

  .bottom-tab-bar {
    display: flex;
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    z-index: 100;
    background: var(--surface);
    border-top: 1px solid var(--border);
    height: 60px;
    align-items: stretch;
    safe-area-inset-bottom: env(safe-area-inset-bottom);
    padding-bottom: env(safe-area-inset-bottom);
  }

  .tab-item {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 3px;
    background: none;
    border: none;
    cursor: pointer;
    color: var(--muted);
    font-size: 10px;
    padding: 6px 0 4px;
    transition: color 0.15s;
    -webkit-tap-highlight-color: transparent;
  }

  .tab-item.active {
    color: #E8520A;
  }

  .tab-icon {
    width: 22px;
    height: 22px;
    stroke: currentColor;
    fill: none;
  }

  .tab-label {
    font-size: 10px;
    line-height: 1;
  }

  /* 더보기 드로어 */
  .more-drawer {
    position: fixed;
    inset: 0;
    z-index: 200;
  }

  .more-drawer-backdrop {
    position: absolute;
    inset: 0;
    background: rgba(0,0,0,0.4);
  }

  .more-drawer-panel {
    position: absolute;
    bottom: 60px;
    left: 0;
    right: 0;
    background: var(--surface);
    border-top: 1px solid var(--border);
    border-radius: 16px 16px 0 0;
    padding: 16px 0 8px;
    max-height: 60vh;
    overflow-y: auto;
  }

  .more-drawer-title {
    font-size: 12px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 1px;
    padding: 0 20px 8px;
  }

  .more-drawer-item {
    display: block;
    width: 100%;
    background: none;
    border: none;
    text-align: left;
    padding: 14px 20px;
    font-size: 15px;
    color: var(--text);
    cursor: pointer;
    border-bottom: 1px solid var(--border);
  }

  .more-drawer-item:last-child {
    border-bottom: none;
  }

  /* 모바일에서 기존 date-label 숨김 */
  .mobile-date-label {
    display: none;
  }
}
```

---

### 1-C. JS 변경 (`backend/static/js/console-navigation.js`)

파일 하단(DOMContentLoaded 블록 내)에 아래 코드를 추가한다.
기존 `mobileMenu` select change 이벤트 리스너는 유지한다 (JS 호환성).

```javascript
// ── Bottom Tab Bar 초기화 ──
(function initBottomTabBar() {
  var tabBar = document.getElementById('bottomTabBar');
  if (!tabBar) return;

  // 탭 클릭
  tabBar.querySelectorAll('.tab-item[data-screen]').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var screen = this.dataset.screen;
      if (screen === 'more-menu') {
        toggleMoreDrawer(true);
        return;
      }
      showScreen(screen);
      setActiveTab(screen);
      toggleMoreDrawer(false);
    });
  });

  // 더보기 드로어 항목 클릭
  var drawer = document.getElementById('moreDrawer');
  if (drawer) {
    drawer.querySelectorAll('.more-drawer-item[data-screen]').forEach(function(btn) {
      btn.addEventListener('click', function() {
        showScreen(this.dataset.screen);
        setActiveTab(this.dataset.screen);
        toggleMoreDrawer(false);
      });
    });
    var backdrop = document.getElementById('moreDrawerBackdrop');
    if (backdrop) {
      backdrop.addEventListener('click', function() { toggleMoreDrawer(false); });
    }
  }

  // showScreen 호출 시 탭 동기화 — 기존 navigateTo 함수를 래핑
  // (기존 코드가 showScreen을 직접 호출하는 경우를 대비해 MutationObserver 대신 직접 패치)
  var _origShowScreen = window.showScreen;
  if (typeof _origShowScreen === 'function') {
    window.showScreen = function(name) {
      _origShowScreen(name);
      setActiveTab(name);
    };
  }
})();

function setActiveTab(screenName) {
  var tabBar = document.getElementById('bottomTabBar');
  if (!tabBar) return;
  // 직접 탭 매핑된 화면
  var directTabs = ['today', 'trading', 'rulepack', 'shadow-trading'];
  tabBar.querySelectorAll('.tab-item').forEach(function(btn) {
    btn.classList.remove('active');
    if (btn.dataset.screen === screenName) {
      btn.classList.add('active');
    }
    // 더보기 탭 — 직접 탭이 아닌 화면 선택 시 활성화
    if (btn.dataset.screen === 'more-menu' && !directTabs.includes(screenName)) {
      btn.classList.add('active');
    }
  });
}

function toggleMoreDrawer(open) {
  var drawer = document.getElementById('moreDrawer');
  if (!drawer) return;
  drawer.style.display = open ? 'block' : 'none';
}
```

---

## Phase 2 — Trading Monitor 세로모드 카드 레이아웃

**목표:** 세로모드(360-430px) 에서 포지션 상태를 한눈에 볼 수 있도록 카드형으로 변환.

### 2-A. CSS 추가 (`backend/static/css/console.css`)

`@media (max-width: 860px)` 블록에 추가:

```css
/* ── Trading Monitor 모바일 카드 ── */
@media (max-width: 860px) {
  /* 기존 가로 스크롤 테이블 대신 카드 */
  #screen-trading .data-table-wrap {
    overflow-x: unset;
  }

  #screen-trading table.data-table {
    display: none; /* 테이블 숨김 */
  }

  /* 포지션 카드 컨테이너 */
  .tm-card-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
    margin: 8px 0;
  }

  /* 포지션 카드 */
  .tm-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 12px 14px;
    position: relative;
  }

  .tm-card-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 8px;
  }

  .tm-card-symbol {
    font-size: 16px;
    font-weight: 700;
    color: var(--text);
  }

  .tm-card-name {
    font-size: 11px;
    color: var(--muted);
    margin-top: 1px;
  }

  .tm-card-pnl {
    font-size: 15px;
    font-weight: 700;
    text-align: right;
  }

  .tm-card-pnl.positive { color: #E8520A; }
  .tm-card-pnl.negative { color: #ef4444; }

  .tm-card-meta {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 4px 12px;
    font-size: 11px;
    color: var(--muted);
    margin-bottom: 10px;
  }

  .tm-card-meta span strong {
    color: var(--text);
    font-weight: 600;
  }

  /* 손절가 게이지 */
  .tm-stop-bar-wrap {
    margin-top: 6px;
  }

  .tm-stop-bar-label {
    display: flex;
    justify-content: space-between;
    font-size: 10px;
    color: var(--muted);
    margin-bottom: 3px;
  }

  .tm-stop-bar {
    height: 4px;
    background: var(--border);
    border-radius: 2px;
    overflow: hidden;
  }

  .tm-stop-bar-fill {
    height: 100%;
    border-radius: 2px;
    transition: width 0.3s;
  }

  .tm-stop-bar-fill.safe { background: #22c55e; }
  .tm-stop-bar-fill.warn { background: #f59e0b; }
  .tm-stop-bar-fill.danger { background: #ef4444; }

  /* 상태 배지 */
  .tm-card-badge {
    position: absolute;
    top: 12px;
    right: 14px;
    font-size: 10px;
    padding: 2px 7px;
    border-radius: 10px;
    font-weight: 600;
  }

  .tm-card-badge.hold { background: rgba(34,197,94,0.15); color: #22c55e; }
  .tm-card-badge.sell { background: rgba(239,68,68,0.15); color: #ef4444; }
}
```

### 2-B. JS 변경 (`backend/static/js/screens/console-trading-monitor.js`)

파일 내 Trading Monitor 렌더 함수(포지션 목록 그리는 부분) 수정.
기존 테이블 렌더 함수가 끝난 후 아래 함수를 추가하고, 포지션 렌더 시 호출한다.

**추가할 함수:**

```javascript
/**
 * 모바일 카드 렌더 — 860px 이하에서만 표시
 * positions: [{symbol, name, quantity, avg_price, current_price, pnl_pct, stop_loss_price, status}, ...]
 */
function renderPositionCards(positions) {
  var container = document.getElementById('tmCardList');
  if (!container) return;

  if (!positions || positions.length === 0) {
    container.innerHTML = '<div style="padding:24px;text-align:center;color:var(--muted);font-size:13px;">보유 포지션 없음</div>';
    return;
  }

  container.innerHTML = positions.map(function(p) {
    var pnlPct = (p.pnl_pct || 0) * 100;
    var pnlClass = pnlPct >= 0 ? 'positive' : 'negative';
    var pnlSign = pnlPct >= 0 ? '+' : '';

    // 손절 게이지: current_price 가 avg_price 에서 stop_loss 까지 얼마나 왔는지
    var stopFillPct = 0;
    var stopClass = 'safe';
    if (p.avg_price && p.stop_loss_price && p.current_price) {
      var range = p.avg_price - p.stop_loss_price;
      var gone = p.avg_price - p.current_price;
      stopFillPct = range > 0 ? Math.min(100, Math.max(0, (gone / range) * 100)) : 0;
      stopClass = stopFillPct > 80 ? 'danger' : stopFillPct > 50 ? 'warn' : 'safe';
    }

    var badgeClass = (p.status === 'sell' || p.status === 'closing') ? 'sell' : 'hold';
    var badgeLabel = badgeClass === 'sell' ? '매도중' : '보유';

    return [
      '<div class="tm-card">',
        '<div class="tm-card-header">',
          '<div>',
            '<div class="tm-card-symbol">' + (p.symbol || '') + '</div>',
            '<div class="tm-card-name">' + (p.name || '') + '</div>',
          '</div>',
          '<div class="tm-card-pnl ' + pnlClass + '">' + pnlSign + pnlPct.toFixed(2) + '%</div>',
        '</div>',
        '<span class="tm-card-badge ' + badgeClass + '">' + badgeLabel + '</span>',
        '<div class="tm-card-meta">',
          '<span>평균가 <strong>' + fmtPrice(p.avg_price) + '</strong></span>',
          '<span>현재가 <strong>' + fmtPrice(p.current_price) + '</strong></span>',
          '<span>수량 <strong>' + (p.quantity || 0) + '주</strong></span>',
          '<span>손절가 <strong>' + fmtPrice(p.stop_loss_price) + '</strong></span>',
        '</div>',
        '<div class="tm-stop-bar-wrap">',
          '<div class="tm-stop-bar-label">',
            '<span>손절 여유</span>',
            '<span>' + (100 - stopFillPct).toFixed(0) + '%</span>',
          '</div>',
          '<div class="tm-stop-bar">',
            '<div class="tm-stop-bar-fill ' + stopClass + '" style="width:' + stopFillPct.toFixed(1) + '%"></div>',
          '</div>',
        '</div>',
      '</div>'
    ].join('');
  }).join('');
}

function fmtPrice(v) {
  if (v == null) return '-';
  return Number(v).toLocaleString('ko-KR') + '원';
}
```

**HTML 추가 (`backend/static/console.html`, `#screen-trading` 섹션 내)**

포지션 테이블 `<div class="data-table-wrap">` 바로 **아래**에 추가:

```html
<!-- 모바일 카드 리스트 — JS에서 채움 -->
<div class="tm-card-list" id="tmCardList" style="display:none"></div>
```

**카드 리스트 표시/숨김 로직 (`console-trading-monitor.js`):**

기존 포지션 렌더 함수 내에서 포지션 데이터를 그린 후:

```javascript
// 모바일이면 카드 표시, 아니면 숨김
var isMobile = window.innerWidth <= 860;
var cardList = document.getElementById('tmCardList');
if (cardList) cardList.style.display = isMobile ? 'flex' : 'none';
if (isMobile) renderPositionCards(positions);
```

---

## Phase 3 — 기타 화면 카드 변환

### 3-A. Today Control — 4열 테이블 → 2열 그리드

`@media (max-width: 860px)` CSS:

```css
/* Today Control 테이블 → 카드 그리드 */
#screen-today .data-table-wrap {
  overflow-x: unset;
}

#screen-today table.data-table {
  display: none;
}

.today-order-cards {
  display: none;
}

@media (max-width: 860px) {
  .today-order-cards {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }

  .today-order-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 12px;
    font-size: 12px;
  }

  .today-order-card .toc-symbol {
    font-weight: 700;
    font-size: 14px;
    margin-bottom: 4px;
  }

  .today-order-card .toc-side-buy { color: #E8520A; }
  .today-order-card .toc-side-sell { color: #ef4444; }

  .today-order-card .toc-meta {
    color: var(--muted);
    font-size: 11px;
    line-height: 1.6;
  }
}
```

구현 시 `console-today-orders.js` 에서 기존 테이블 렌더와 별개로 `.today-order-cards` 요소를 채우는 `renderTodayOrderCards(orders)` 함수를 추가한다.

---

### 3-B. Missed Entries — 카드 리스트

```css
@media (max-width: 860px) {
  #screen-shadow-trading .data-table {
    display: none;
  }

  .missed-card-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .missed-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px 14px;
  }

  .missed-card-top {
    display: flex;
    justify-content: space-between;
    margin-bottom: 6px;
  }

  .missed-card-symbol { font-weight: 700; font-size: 14px; }
  .missed-card-reason { font-size: 11px; color: var(--muted); }
  .missed-card-pnl { font-size: 13px; font-weight: 600; color: #22c55e; }
}
```

---

### 3-C. Daily Results — 5열 테이블 → 1열 리스트

```css
@media (max-width: 860px) {
  #screen-daily-results .data-table {
    display: none;
  }

  .daily-result-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .daily-result-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 14px;
  }

  .daily-result-date { font-size: 13px; font-weight: 600; }
  .daily-result-trades { font-size: 11px; color: var(--muted); }
  .daily-result-pnl { font-size: 14px; font-weight: 700; }
  .daily-result-pnl.pos { color: #E8520A; }
  .daily-result-pnl.neg { color: #ef4444; }
}
```

---

## 완료 기준

- [ ] Phase 1: 860px 이하에서 하단 탭 바 표시, 탭 탭 탭마다 화면 전환 동작
- [ ] Phase 1: "더보기" 탭 클릭 시 드로어 슬라이드업, 항목 선택 후 드로어 닫힘
- [ ] Phase 1: 기존 `showScreen()` / `navigateTo()` JS 함수와 충돌 없음
- [ ] Phase 2: 860px 이하 Trading Monitor에서 테이블 숨김, 카드 리스트 표시
- [ ] Phase 2: 손절 게이지 색상 (safe/warn/danger) 정상 렌더
- [ ] Phase 3: Today Control, Missed Entries, Daily Results 모바일 카드 표시
- [ ] 데스크탑(860px 초과)에서 기존 레이아웃 변화 없음
- [ ] 다크/라이트 모드 모두 정상 표시

---

## 완료 후 OUTBOX 작성

작업 완료 후 아래 파일을 생성하라:
`docs/agent-comm/OUTBOX_GEMINI_20260523_mobile_ui.md`

포함 내용:
- 완료된 Phase 목록
- 변경된 파일 목록 (경로 + 변경 유형)
- 미완료 항목 있으면 이유 기재
- 발생한 이슈 및 해결 방법
