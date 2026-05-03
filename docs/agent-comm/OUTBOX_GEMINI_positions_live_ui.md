# OUTBOX_GEMINI_positions_live_ui — 작업 완료 보고

## 완료 상태: ✅ 성공

---

## 완료 기준 검증

```
python3 -c "from html.parser import HTMLParser; ..." → HTML OK
grep -c "account/balance|decision/status|decision/signals" → 3
```

---

## 작업 1 — Positions & Exit 탭 계좌 정보 추가 ✅

### 변경 내용 (`backend/static/console.html`)

`#screen-positions` 섹션 최상단 ("보유 종목 청산 상태" 카드 위)에 신규 카드 추가:

- **계좌번호** (`#positions-account-no`)
- **예수금** (`#positions-deposit`) + **총평가금액** (`#positions-total-eval`) — `toLocaleString()` 천단위 표시
- **보유 종목 테이블** (`#positions-holdings-tbody`): 종목코드/종목명/수량/매입평균가/현재가/손익률
  - 손익률 양수 → `class="good"`, 음수 → `class="bad"`
  - 보유 종목 없으면 "보유 종목 없음" 표시
- **새로고침 버튼** → `loadAccountBalance()` 호출
- `showScreen('positions')` 진입 시 자동 1회 호출

### 추가된 JS 함수
- `loadAccountBalance()` — `GET /api/v1/account/balance` 호출 후 DOM 업데이트

---

## 작업 2 — Live Decisions 탭 실시간 신호 표시 ✅

### 변경 내용 (`backend/static/console.html`)

`#screen-live` 섹션 내용을 정적 더미 데이터에서 실시간 API 기반 UI로 교체:

**Decision Engine 상태 카드**
- 상태 뱃지 (`#live-engine-active`): 활성=`status ok`, 비활성=`status warn`
- WS 연결 상태 (`#live-engine-ws`): 연결됨=초록, 끊김=빨강
- 후보 종목 수 (`#live-engine-candidates`)
- 신호 발행 건수 (`#live-engine-signals-sent`)
- 수동 활성화 버튼 → `confirm()` 후 `POST /api/v1/decision/activate`
- 비활성화 버튼 → `confirm()` 후 `POST /api/v1/decision/deactivate`

**오늘 매수 신호 테이블** (`#live-signals-tbody`)
- 컬럼: 시간/종목코드/종목명/진입가/신뢰도/상태
- 신호 없으면 "아직 신호 없음"
- 새로고침 버튼

**자동 갱신**
- `showScreen('live')` 진입 시 `loadLiveData()` 1회 즉시 호출
- `setInterval(loadLiveData, 10000)` — 10초마다 자동 갱신
- 다른 탭으로 이동 시 `clearInterval` 으로 정리

### 추가된 JS 함수
- `loadLiveData()` — `/api/v1/decision/status` + `/api/v1/decision/signals/today` 병렬 조회
- `liveDecisionActivate()` — confirm 후 POST activate
- `liveDecisionDeactivate()` — confirm 후 POST deactivate
- `liveRefreshTimer` 변수로 interval 관리

---

## 변경 파일
| 파일 | 변경 유형 |
|------|-----------|
| `backend/static/console.html` | 수정 |
| `docs/agent-comm/OUTBOX_GEMINI_positions_live_ui.md` | 신규 (본 파일) |
