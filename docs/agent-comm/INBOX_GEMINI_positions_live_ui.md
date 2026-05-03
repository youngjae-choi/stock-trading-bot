# INBOX_GEMINI_positions_live_ui — Positions 탭 계좌 정보 + Live Decisions 실시간 신호 UI

## 수정 대상
`backend/static/console.html`

---

## 작업 1 — Positions & Exit 탭 상단에 계좌 정보 추가

### API
- `GET /api/v1/account/balance` — 계좌 정보 + 보유종목

### 응답 구조
```json
{
  "ok": true,
  "payload": {
    "account_no": "12345678-01",
    "deposit": 1234567,
    "total_eval": 5678900,
    "positions": [
      {"symbol": "005930", "name": "삼성전자", "qty": 10, "avg_price": 72500, "current_price": 73000, "pnl_pct": 0.69}
    ]
  }
}
```

### UI 구성

`screen-positions` 섹션 최상단에 아래 섹션 추가 (기존 "보유 종목 청산 상태" 카드 위):

```
[계좌 정보]                                              [새로고침]
계좌번호: 12345678-01
예수금: 1,234,567원    총평가금액: 5,678,900원

[보유 종목]
  종목코드  종목명      수량   매입평균가   현재가   손익률
  005930   삼성전자     10     72,500      73,000   +0.69%
  000660   SK하이닉스   5     184,000     181,300   -1.47%
  (없으면 "보유 종목 없음")
```

- 손익률 양수 → `class="good"` (초록), 음수 → `class="bad"` (빨강)
- 새로고침 버튼 클릭 시 API 재호출
- `showScreen('positions')` 진입 시 자동 1회 호출
- 숫자는 `toLocaleString()` 으로 천단위 콤마 표시

---

## 작업 2 — Live Decisions 탭 실시간 신호 표시

현재 `screen-live` 섹션 내용을 아래로 교체.

### API
- `GET /api/v1/decision/status` — 엔진 상태 (active, ws_connected, candidates, signals_sent)
- `GET /api/v1/decision/signals/today` — 오늘 생성된 신호 목록
- `POST /api/v1/decision/activate` — 수동 활성화
- `POST /api/v1/decision/deactivate` — 수동 비활성화

### UI 구성

```
[Decision Engine 상태]
  상태: 활성 / 비활성          WS: 연결됨 / 끊김
  후보 종목: 12개              신호 발행: 3건
  [수동 활성화]  [비활성화]

[오늘 매수 신호]                               [새로고침]
  시간       종목코드  종목명      진입가    신뢰도   상태
  09:14:23  005930   삼성전자    72,800   0.82    대기중
  09:22:11  000660   SK하이닉스  183,500  0.75    대기중
  (없으면 "아직 신호 없음")
```

- 상태 뱃지: 활성=`status ok`, 비활성=`status warn`
- WS 연결됨=초록, 끊김=빨강
- `showScreen('live')` 진입 시 자동 조회
- 10초마다 자동 갱신 (setInterval, 다른 탭으로 이동 시 clearInterval)
- 수동 활성화 클릭 → confirm("Decision Engine을 수동으로 활성화할까요?") → POST

---

## 완료 기준
```bash
python3 -c "from html.parser import HTMLParser; p=HTMLParser(); p.feed(open('backend/static/console.html').read()); print('HTML OK')"
grep -c "account/balance\|decision/status\|decision/signals" backend/static/console.html
```

OUTBOX(`docs/agent-comm/OUTBOX_GEMINI_positions_live_ui.md`)에 결과 작성.
