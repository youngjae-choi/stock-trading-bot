# INBOX_GEMINI_p2_positions_ui_v2

## 역할
너는 Gemini (Frontend 전담)다.
아래 Positions & Exit 화면 UI 개선 작업을 수행하라.
파일은 `backend/static/console.html` 하나만 수정한다.
완료 후 `docs/agent-comm/OUTBOX_GEMINI_p2_positions_ui_v2.md`에 결과를 작성하라.

---

## 배경

`screen-positions` 섹션과 관련 JS 함수(`loadPositionMonitoring`, `loadAccountBalance`, `loadTodayOrders`)는 이미 구현되어 있다.  
현재 문제:

1. positions 화면 진입 시 5초 자동 새로고침이 없음 (수동만)
2. `loadPositionMonitoring()`이 `pos.current_price === 0`일 때 "0" 숫자 그대로 표시
3. `pos.stop_loss_price` 값이 있어도 일반 숫자로 표시 (빨간색 없음)
4. 주문 상태가 텍스트만 ("체결됨") — 색상 뱃지 없음
5. 예수금/총평가금액이 원단위 그대로라 큰 숫자가 읽기 어려움
6. 마지막 갱신 시각이 표시되지 않음

---

## 수정 사항

### 1) 5초 자동 새로고침

현재 `showScreen()` 함수가 있다. 이 함수에서 screen id가 `'positions'`일 때:

```js
// screen이 positions로 바뀔 때
if (newScreen === 'positions') {
  _positionsTimer = setInterval(function() {
    loadPositionMonitoring();
    loadTodayOrders();
  }, 5000);
  loadAccountBalance();  // 1회만 (잔고는 자주 갱신 불필요)
} else if (_positionsTimer) {
  clearInterval(_positionsTimer);
  _positionsTimer = null;
}
```

`var _positionsTimer = null;` 를 전역 변수로 선언.

### 2) 실시간 포지션 감시 테이블 개선

`loadPositionMonitoring()` 내부의 row 렌더링 부분에서:

**current_price 처리:**
```js
var curPriceHtml = (pos.current_price && pos.current_price > 0)
  ? pos.current_price.toLocaleString()
  : '<span class="muted">-</span>';
```

**pnl_pct 처리:**
```js
var pnlHtml;
if (pos.current_price && pos.current_price > 0) {
  var pnl = pos.pnl_pct || 0;
  var pnlClass = pnl >= 0 ? "good" : "bad";
  pnlHtml = '<span class="' + pnlClass + '">' + (pnl >= 0 ? "+" : "") + pnl.toFixed(2) + "%</span>";
} else {
  pnlHtml = '<span class="muted">-</span>';
}
```

**stop_loss_price 처리 (빨간색):**
```js
var stopHtml = (pos.stop_loss_price && pos.stop_loss_price > 0)
  ? '<span style="color:var(--bad)">' + Math.round(pos.stop_loss_price).toLocaleString() + '</span>'
  : '<span class="muted">-</span>';
```

**빈 상태 메시지:**
```
'<tr><td colspan="10" class="muted" style="text-align:center;">보유 포지션 없음 (Decision Engine 활성화 후 표시됩니다)</td></tr>'
```

**트레일링 뱃지:**
```js
var trailingHtml = pos.trailing_active
  ? '<span class="status ok">ON</span>'
  : '<span class="status">대기</span>';
```

### 3) 주문내역 상태 뱃지 (배지 HTML)

`loadTodayOrders()` 함수에서 `orders-today-tbody` 렌더링 부분의 status 처리를 수정:

```js
var statusBadgeMap = {
  "filled":    '<span class="status ok">체결</span>',
  "submitted": '<span class="status warn">대기중</span>',
  "failed":    '<span class="status bad">실패</span>',
  "cancelled": '<span class="muted" style="font-size:11px;">취소</span>',
  "preflight_blocked": '<span class="status bad">차단</span>'
};
var statusHtml = statusBadgeMap[ord.status] || '<span class="muted">' + escapeHtml(ord.status) + '</span>';
```

`legacyRowsHtml`에서 statusLabel 텍스트를 statusHtml로 교체.

### 4) 예수금/총평가금액 만원 단위

`loadAccountBalance()` 내부에서:

```js
function _toManwon(v) {
  var n = Number(v) || 0;
  if (n >= 10000) return (n / 10000).toFixed(0) + "만원";
  return n.toLocaleString() + "원";
}
setTextForIds(["positions-deposit"], _toManwon(p.deposit));
setTextForIds(["positions-total-eval"], _toManwon(p.total_eval));
```

### 5) 마지막 갱신 시각

`screen-positions`의 `page-head` div 내부 오른쪽에 추가:

```html
<div style="font-size:12px; color:var(--muted); align-self:center;">
  마지막 갱신: <span id="positions-last-updated">-</span>
</div>
```

`loadPositionMonitoring()` 완료 시 (try 블록 마지막):

```js
var el = document.getElementById('positions-last-updated');
if (el) {
  el.textContent = new Date().toLocaleTimeString('ko-KR', {hour:'2-digit', minute:'2-digit', second:'2-digit'});
}
```

---

## 검증

```bash
python3 -c "
from html.parser import HTMLParser
p = HTMLParser()
p.feed(open('backend/static/console.html').read())
print('HTML parse OK')
"
grep -c "_positionsTimer\|positions-last-updated\|statusBadgeMap" backend/static/console.html
```

3개 모두 1 이상이면 통과.

---

## 완료 체크리스트

- [ ] `_positionsTimer` 전역 변수 선언
- [ ] showScreen에서 positions 진입/이탈 시 setInterval/clearInterval
- [ ] current_price=0 처리 (muted dash)
- [ ] stop_loss_price 빨간색 표시
- [ ] 트레일링 뱃지 ON/대기
- [ ] 빈 포지션 메시지 문구 변경
- [ ] 주문 상태 배지 HTML (filled/submitted/failed/cancelled)
- [ ] 예수금/총평가금액 만원 단위
- [ ] 마지막 갱신 시각 표시
- [ ] HTML parse OK
- [ ] grep 검증 3개 통과

결과는 `docs/agent-comm/OUTBOX_GEMINI_p2_positions_ui_v2.md`에 작성하라.
