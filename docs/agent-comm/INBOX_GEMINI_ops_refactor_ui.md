# INBOX_GEMINI_ops_refactor_ui

## 역할
너는 Frontend(Gemini)다. 1차 운영 화면 개편 UI를 수행하라.
완료 후 `docs/agent-comm/OUTBOX_GEMINI_ops_refactor_ui.md`에 결과를 작성하라.

## 공통 규칙
- 작업 전 `ONBOARDING.md`, `AGENTS.md`, `GEMINI.md`, `UI_BASELINE.md`, `ERROR_HANDLING.md`, `docs/planning/today_control_trading_monitor_refactor_plan_20260505.md`를 확인한다.
- git commit 금지.
- 기본 수정 대상은 `backend/static/console.html` 단일 파일이다.
- 백엔드 파일은 수정하지 않는다. 필요한 API는 Executor가 담당한다.
- 같은 기능의 기존 스타일/패턴을 재사용한다.

## 목적
매일 보는 운영 화면을 Today Control 중심으로 정리하고, Approval Queue/Alert Center를 별도 페이지가 아닌 자동 운영/요약 흐름으로 단순화한다.

## 작업 1 — Approval Queue / Alert Center 별도 페이지 숨김
1. 사이드바 버튼 제거 또는 숨김:
   - `Alert Center`
   - `Approval Queue`
2. 모바일 메뉴 option 제거 또는 숨김.
3. 기존 섹션/API 함수는 삭제하지 말고 보존해도 된다.
   - 단 사용자가 메뉴에서 접근하지 않게 한다.
4. Today Control에 작은 운영 알림 요약을 배치한다.
   - 기존 Alert summary API를 사용하되 필드명은 실제 API 기준:
     - `total_count`
     - `severity_counts.CRITICAL`
     - `severity_counts.WARNING`
     - `unacknowledged_count`
   - 별도 승인 동작은 넣지 않는다.

## 작업 2 — Today Control 개선
1. `오늘 주문내역`을 `최근 주문내역`으로 변경.
2. `/api/v1/orders/recent?limit=5`를 사용해 최신 5개만 표시.
   - API가 아직 실패하면 기존 `/api/v1/orders/today` fallback 가능.
3. 카드 안에 `자세히보기` 버튼 추가.
   - 클릭 시 `showScreen('statistics')`
4. `Funnel Progress` 카드 안에 `자세히보기` 버튼 추가.
   - 클릭 시 `showScreen('funnel')`
5. Today Control 내부 카드별 `새로고침` 버튼 제거.
6. 우측 상단 `새로고침` 버튼은 Today Control 관련 전체 데이터 재조회 함수로 연결.
   - 기존 화면을 완전 reload 하지 말고, UX상 페이지 데이터 전체 reload.
   - 예: `refreshTodayControl()` 생성 후 `loadConsoleData`, `renderTodayFeed`, `loadTodayOrders`, `loadTodayPlanStatus`, alert summary 등을 호출.

## 작업 3 — Trading Monitor 개선
1. `계좌 정보` 카드와 `오늘 적용 정책` 카드의 좌우 위치 변경.
2. 계좌 정보 표시:
   - `예수금: xxx원`
   - `주식매수 가능금액: xxx원`
   - 기존 총평가/보유종목/손익 표시를 유지하되 문구를 명확히 한다.
   - `buyable_cash` 또는 `available_cash` 필드가 있으면 사용, 없으면 deposit fallback.
3. 보유 포지션 모니터링:
   - 종목별 `매수금액` 표시 추가.
   - 단가/현재가/최고가/손절선은 소수점 이하 없이 표시.
4. 오늘 적용 정책:
   - `/api/v1/trading-monitor/policy-summary`를 우선 사용.
   - Settings 값이 아니라 오늘 AI 산출물 기반의 자연어 문구를 보여준다.
   - 표시 예:
     - `매수: AI 신뢰도 0.60 이상, 등락률 0.5~8.0% 후보만 감시`
     - `매도: 트레일링/손절/15:20 청산 기준 적용`
     - `현금: 시장톤 mixed, 신규 진입 보수적`
   - API 실패 시 기존 rule/daily-plan fallback을 사용하되 `데이터 확인 필요` 문구를 표시.
5. LIVE 깜빡임 완화:
   - `loadTradingCandidates()`와 `loadTradingPositions()`에서 매번 `container.innerHTML = ...`로 전체 교체하는 방식을 줄인다.
   - 같은 key(`symbol`/`code`)가 있으면 기존 row를 유지하고 내용만 바꾸거나, 최소한 opacity transition으로 부드럽게 갱신한다.
   - empty/error 상태는 기존처럼 표시하되 정상 LIVE 갱신 때 전체 카드가 번쩍이지 않게 한다.

## 작업 4 — Trade History 단순화
1. 첨부 이미지에 보인 요약 카드 영역 제거.
   - 매매일수
   - 총 주문수
   - 수익일 비율
   - 누적 손익
   - 일 평균 손익
2. Trade History는 내역 조회/필터/테이블 중심으로만 둔다.
3. 통계성 카드는 나중에 Statistics 화면을 만들 때 복구할 수 있도록 함수 삭제보다는 DOM 표시 제거 중심으로 처리해도 된다.

## 작업 5 — 자동승인 방향 반영
1. Approval Queue는 별도 페이지에서 제거.
2. 화면 문구/주석에서 “승인 대기” 중심 UX를 Today Control 주요 흐름에 노출하지 않는다.
3. Alert는 승인용이 아니라 운영 알림/차단 기록 느낌으로 표현한다.

## 검증
아래를 실행하고 결과 기록:
```bash
python3 - <<'PY'
from html.parser import HTMLParser
with open('backend/static/console.html', encoding='utf-8') as f:
    HTMLParser().feed(f.read())
print('HTML parse OK')
PY
```

가능하면 브라우저 확인:
- Today Control 진입
- 최근 주문 자세히보기 -> Trade History 이동
- Funnel 자세히보기 -> Funnel Monitor 이동
- Trading Monitor 표시 확인
- Trade History 요약 카드 제거 확인

## 완료 체크리스트
- [ ] Alert/Approval 별도 메뉴 숨김
- [ ] Today Control 최근 주문/자세히보기/새로고침 정리
- [ ] Funnel 자세히보기 이동
- [ ] Trading Monitor 계좌/정책/포지션 표시 수정
- [ ] LIVE 깜빡임 완화
- [ ] Trade History 요약 카드 제거
- [ ] HTML parse OK
