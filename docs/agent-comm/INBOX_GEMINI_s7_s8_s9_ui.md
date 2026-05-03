# INBOX_GEMINI_s7_s8_s9_ui — S7/S8/S9 UI: 주문내역 + 포지션 감시 + KIS Test 카드 추가

## 수정 대상
`backend/static/console.html`

---

## 작업 1 — Positions & Exit 탭에 주문내역 + 실시간 포지션 섹션 추가

기존 "보유 종목 청산 상태" 정적 더미 테이블을 실제 API 기반으로 교체하고, 주문내역 섹션을 추가한다.

### API
| 메서드 | URL | 설명 |
|--------|-----|------|
| GET | `/api/v1/orders/positions` | PositionManager 인메모리 포지션 |
| GET | `/api/v1/orders/today` | 오늘 발행 주문 목록 |
| POST | `/api/v1/orders/liquidate-all` | 전체 즉시 청산 |

### 포지션 응답 구조
```json
{
  "ok": true,
  "payload": {
    "positions": [
      {
        "symbol": "005930", "name": "삼성전자",
        "qty": 10, "entry_price": 72500, "current_price": 73000,
        "pnl_pct": 0.69,
        "stop_loss_price": 71412, "take_profit_price": 74675,
        "trailing_active": false, "entry_time": "2026-05-02T09:14:23"
      }
    ]
  }
}
```

### 주문 응답 구조
```json
{
  "ok": true,
  "payload": {
    "orders": [
      {
        "symbol": "005930", "name": "삼성전자",
        "side": "buy", "qty": 10, "price": 72500,
        "status": "submitted", "kis_order_no": "0000123456",
        "reason": "", "created_at": "2026-05-02T09:14:22"
      }
    ]
  }
}
```

### UI 구성

#### 실시간 포지션 감시 카드 (기존 "보유 종목 청산 상태" 교체)
```
[실시간 포지션 감시]                                    [새로고침] [전체 청산]
  종목코드  종목명      수량  진입가    현재가   손익률  손절가   익절가   트레일링  보유시간
  005930   삼성전자     10   72,500   73,000  +0.69%  71,412  74,675  대기      12분
  (없으면 "보유 포지션 없음")
```
- 손익률 양수 → `class="good"`, 음수 → `class="bad"`
- 트레일링 활성 → `<span class="status ok">활성</span>`, 비활성 → `<span class="status warn">대기</span>`
- 보유시간: entry_time 기준 현재 경과 분 계산
- [전체 청산] → `confirm("전체 포지션을 즉시 청산할까요?")` → `POST /api/v1/orders/liquidate-all`
- 10초마다 자동 갱신 (`showScreen('positions')` 진입 시 interval 시작, 이탈 시 clearInterval)

#### 오늘 주문내역 카드 (기존 카드 아래에 추가)
```
[오늘 주문내역]                                         [새로고침]
  시간       종목     구분  수량  가격      주문번호      상태
  09:14:22  005930  매수   10  72,500   0000123456   제출됨
  09:35:11  005930  매도   10  73,200   0000123457   제출됨
  (없으면 "오늘 주문 없음")
```
- side=buy → "매수", sell → "매도"
- status: submitted→"제출됨", filled→"체결됨", failed→"실패", cancelled→"취소"

---

## 작업 2 — KIS System Test 페이지에 S7/S8/S9 카드 추가

기존 S6 카드 뒤에 S7, S8, S9 카드 추가.

### S7 카드
```
S7 — 주문 실행 (수동 테스트)
09:00~ KST · pending 신호 → KIS 주문
[▶ 오늘 신호 주문 실행]  → POST /api/v1/orders/execute-pending  (없으면 badge="신호없음")
```

### S8 카드
```
S8 — Position Manager 상태
장중 · WS tick → 손절/익절 감시
[▶ 포지션 조회]  → GET /api/v1/orders/positions (결과 표시)
```

### S9 카드
```
S9 — 당일 청산
15:20 KST · 전량 시장가 청산
[▶ 즉시 전체 청산]  → POST /api/v1/orders/liquidate-all
```

### STEP_URLS 추가
기존 STEP_URLS에 s7, s8, s9 추가:
```javascript
s7: "/api/v1/orders/execute-pending",
s8: "/api/v1/orders/positions",
s9: "/api/v1/orders/liquidate-all"
```
단, s8은 GET 메서드로 호출 (다른 step은 POST).
`engineTestRun()` 함수에서 s8일 때는 GET으로 호출하도록 처리.

---

## 완료 기준
```bash
python3 -c "from html.parser import HTMLParser; p=HTMLParser(); p.feed(open('backend/static/console.html').read()); print('HTML OK')"
grep -c "orders/positions\|orders/today\|liquidate-all\|et-card-s7\|et-card-s8\|et-card-s9" backend/static/console.html
```

OUTBOX(`docs/agent-comm/OUTBOX_GEMINI_s7_s8_s9_ui.md`)에 결과 작성.
