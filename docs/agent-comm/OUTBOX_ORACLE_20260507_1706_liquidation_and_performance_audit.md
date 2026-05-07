# OUTBOX_ORACLE - 2026-05-07 17:06 KST - 청산/성과 운영 감사

## 감사 범위

- 역할: Oracle
- 모드: read-only 운영/성과 감사
- 금지 준수: 파일 수정은 본 OUTBOX 작성만 수행. git commit 없음. 주문성 API/decision activate/S1~S11 실행/외부 LLM 호출 없음.
- 사용한 read-only 조회:
  - DB read-only: `data/stock_trading_bot.sqlite3`
  - 로그 read-only: `logs/server.log`, `logs/uvicorn.out`
  - GET API: `GET /api/v1/orders/today`, `GET /api/v1/orders/positions`, `GET /api/v1/account/balance`
  - KIS read-only: `GET /api/v1/account/balance` 경유 잔고조회. 계좌번호는 보고서에 노출하지 않음.

## Findings

### P1 - 현재 계좌 보유 종목은 2026-05-07 S9 미실행 때문이 아니라, 2026-05-04 잔여 포지션이다

근거:
- 2026-05-07 15:20 KST 후처리는 실제 실행됐다. `logs/server.log:37727-37762`
- S9는 `036930` 18주, `050890` 122주를 EOD 매도 제출했고, 이후 인메모리 포지션은 0건이다. `logs/server.log:37733-37745`, `GET /api/v1/orders/positions -> count=0`
- KIS 잔고조회 결과 현재 보유 10종목에는 `036930`, `050890`이 없다.
- 현재 KIS 보유 10종목 중 대부분은 DB의 2026-05-04 매수 주문과 일치한다: `0101N0`, `059120`, `125020`, `126730`, `199820`, `307930`, `321260`, `332570`, `473590`, `491090`.
- DB `trading_orders` 기준 2026-05-04는 매수 20건, 매도 0건, 실패 9건이다. 즉 5/4 포지션이 당일 청산되지 않고 계좌에 남았다.

영향:
- PM이 본 “청산 시간이 지났는데 남아 있는 종목”은 오늘 신규 매수분이 아니라 과거 잔여 포지션이다.
- 현재 S9가 “당일 포지션” 중심이라 전일 잔여/오프라인 수동/실계좌 보유를 정리하지 못한다.

제안:
- S9 청산 대상 소스를 `오늘 DB 포지션`이 아니라 `KIS 실제 잔고 + 전략 소유권 태그/주문 이력` 기준으로 재정의해야 한다.
- 테스트 계좌 정책상 “전 종목 강제청산”인지 “전략이 산 종목만 청산”인지 PM 결정이 필요하다.

### P1 - 서버 재시작 후 포지션 복원이 이미 매도 제출된 종목까지 되살려 중복 EOD 매도를 만들었다

근거:
- 2026-05-07 오전에 이미 트레일링 스탑 매도가 있었다.
  - `050890` 10:03 KST `TRAILING_STOP`
  - `036930` 11:13 KST `TRAILING_STOP`
- 15:09 KST 서버 재시작 시 포지션 복원이 `036930`, `050890`을 다시 인메모리에 추가했다. `logs/server.log:37575-37580`
- 15:20 KST S9가 같은 두 종목에 대해 다시 EOD 매도를 제출했다. `logs/server.log:37734-37744`
- 원인 코드:
  - startup은 오늘 날짜만 넘겨 복원한다. `backend/main.py:108-117`
  - `_restore_positions_from_db()`는 오늘 buy 주문과 stop state만 조인하고 sell 주문 차감/제외가 없다. `backend/services/engine/decision_engine.py:371-415`
  - S9는 인메모리 포지션이 있으면 DB의 sell 제외 쿼리를 타지 않는다. `backend/services/engine/eod_liquidation.py:60-73`

영향:
- 이미 청산된 포지션이 재시작 후 다시 살아나 중복 매도 시도가 발생한다.
- 오늘 EOD 매도 2건은 `kis_order_no`가 빈 문자열인데도 성공으로 기록됐다. 체결 검증 없이 “청산 완료”가 찍힌다.

제안:
- 포지션 복원은 buy - sell 순수량(net qty)을 계산해야 한다.
- sell 주문은 `submitted`가 아니라 체결/잔고 확인 전까지 포지션 제거로 확정하면 안 된다.
- EOD 성공 조건에 `kis_order_no` 존재 및 사후 잔고 확인을 포함해야 한다.

### P1 - 주문 상태와 체결 상태가 분리되지 않아 수익률/청산/리뷰가 모두 부정확하다

근거:
- `trading_orders`의 매수/매도는 대부분 `submitted` 상태로 남아 있고, S10은 실현손익을 0으로 집계한다.
- 2026-05-07 S10 결과: `trades=3`, `orders=6`, `pnl=0.0000`. `logs/server.log:37756-37758`
- `review_audit`는 `trading_signals.realized_pnl` 중심으로 손익을 계산한다. 체결가/매도가/fills 기반 손익이 아니다. `backend/services/engine/review_audit.py:287-310`
- 2026-05-04도 Review는 `executed_no_exit=11`, `total_pnl=0.0`으로 기록됐으나 실제 계좌에는 보유 손익이 크게 남아 있다.

영향:
- “계좌 수익 약 0.4%”와 시스템 리뷰의 `pnl=0`이 서로 연결되지 않는다.
- 전략 성과, 손절/트레일링 품질, false positive 판단이 신뢰 불가능하다.

제안:
- Fill poller가 KIS 주문내역/체결내역을 주기적으로 반영해 `submitted -> filled/cancelled/rejected`를 확정해야 한다.
- S10은 `fills + KIS 잔고 스냅샷 + trading_orders` 기준으로 실현/미실현 손익을 계산해야 한다.

### P2 - 2026-05-06은 강한 장이었지만 프로세스는 S2/S4/S5에서 보수적으로 꺾였고 S6 신호가 0건이었다

근거:
- 5/6 S2: `mixed`, confidence `0.55`
- 5/6 S4: raw 30, output 7, overall confidence `0.30`
- 5/6 S5: `defensive`, `min_ai_confidence=0.7`, `max_theme_spike_positions=0`
- 5/6 trading_signals 0건, trading_orders 0건, daily_summary 주문 0건, review `no_trade_count=1`

영향:
- 강한 지수 상승일에 시스템은 시장을 “mixed/defensive”로 인식했고, 매수 기회를 거의 만들지 않았다.

제안:
- S2 시장톤이 실제 당일 장세와 괴리될 때 장중 보정 루프를 둔다.
- S4 confidence가 낮을 때도 강한 시장에서는 watch/shadow/missed entry를 남겨 사후 학습 가능하게 한다.

### P2 - 2026-05-07은 긍정 장세를 인식했지만 진입 폭이 너무 좁고, 실제 수익 기여가 거의 없었다

근거:
- 5/7 S2: `positive`, confidence `0.88`
- 5/7 S4: output 29였지만 overall confidence `0.52`
- 5/7 S5: `normal`, `min_ai_confidence=0.7`
- S6 실제 신호는 3건뿐이다: `050890`, `036930`, `254490`
- `254490`은 preflight에서 `confidence=0.64 < 최소 0.70`로 차단됐다.
- `050890`, `036930`은 매수 후 각각 트레일링 스탑 매도가 발생했고, S10은 여전히 `pnl=0`으로 집계했다.

영향:
- 상승장을 넓게 먹지 못하고 2종목만 진입했다.
- 청산/체결 기록이 부정확해 실제 단타 품질을 평가할 수 없다.

제안:
- positive/high-confidence 장세에서는 S5가 `normal`이 아니라 공격/확장 프로파일을 선택할 조건을 명시한다.
- confidence 0.60~0.70 후보는 실주문 차단하더라도 shadow/missed entry로 남긴다.

### P2 - 2026-05-04 성과가 계좌를 끌어내리는 핵심 원천이다

근거:
- 5/4 S2 positive, S5 aggressive였고 11개 매수 주문이 제출됐다.
- 같은 날 매도 주문은 0건이다.
- 현재 계좌 보유 10종목이 대부분 5/4 매수 종목과 일치한다.
- 5/4 주문 실패 9건은 KIS rate limit/token limit 계열이다: `EGW00201 초당 거래건수 초과`, `EGW00133 접근토큰 발급 1분당 1회`.
- 현재 잔고에는 큰 손실 종목도 함께 남아 있다: `125020 -14.64%`, `199820 -11.08%`, `307930 -8.62%`, `126730 -7.85%` 등.

영향:
- 5/4 강한 장에서 잡은 포지션 일부는 수익이지만, 손실 포지션도 함께 며칠간 방치되어 계좌 수익률을 희석/훼손했다.
- 단타 시스템이 아니라 “5/4 매수 후 미청산 보유 계좌”처럼 운영됐다.

제안:
- 5/4 잔여 포지션을 별도 incident로 분류하고, 청산 정책 결정 후 수동/자동 정리 계획을 세워야 한다.

### P3 - Missed Entries / False Positive / Shadow 기록이 없어 상승장 미진입 원인을 학습할 수 없다

근거:
- 5/4, 5/6, 5/7 모두 `missed_opportunities=0`, `false_positive_cases=0`
- 5/6처럼 주문 0건인 날도 no-trade reason은 `no_candidates` 수준이라 실제 병목이 S2/S4/S5/S6 중 어디인지 충분히 남지 않는다.

영향:
- PM 질문 2번에 대해 “왜 못 먹었는지”를 사후 학습 데이터로 설명하기 어렵다.

제안:
- S3/S4 후보 중 강한 상승 후보가 S5/S6에서 탈락한 이유를 `missed_opportunities`로 남긴다.
- 실주문 기준 미달 후보도 shadow trade로 추적해 장세별 threshold 조정 근거를 만든다.

## 청산 미실행 원인 결론

2026-05-07 15:20 KST S9 자체는 실행됐다. 오늘 S9 미실행이 원인이 아니다.

계좌에 종목이 남아 있는 직접 원인은 2026-05-04 매수 포지션이 당일 청산되지 않았고, 현재 S9/복원 로직이 전일 잔여 또는 실제 KIS 잔고를 청산 대상으로 삼지 않기 때문이다. 추가로 2026-05-07에는 이미 트레일링 스탑으로 매도된 종목이 서버 재시작 후 다시 복원되어 EOD 중복 매도가 발생했다.

## 2026-05-07 15:20 후처리 타임라인

- 15:09:33 KST: 서버 시작, `schedule_postprocess_time=15:20` migration 확인, job 6개 등록. `logs/server.log:37560-37574`
- 15:09:33 KST: 오늘 포지션 `036930`, `050890` 복원. `logs/server.log:37575-37580`
- 15:20:00 KST: `PostProcess S9~S10` 실행 시작. `logs/server.log:37727-37733`
- 15:20:02 KST: `036930` 18주 EOD 매도 제출. `logs/server.log:37734-37740`
- 15:20:06 KST: `050890` 122주 EOD 매도 제출. `logs/server.log:37741-37745`
- 15:20:06 KST: Decision Engine 비활성화. `logs/server.log:37747-37751`
- 15:20:06 KST: S10 Review & Audit 실행, `trades=3`, `orders=6`, `pnl=0`. `logs/server.log:37754-37758`
- 이후 확인: `GET /api/v1/orders/positions`는 0건. `GET /api/v1/account/balance`는 10종목 보유, 단 `036930`, `050890` 없음.

## 현재 보유 종목 출처 판단

현재 KIS 보유 종목은 오늘 S9 대상이었던 `036930`, `050890`이 아니라 2026-05-04 전략 매수 잔여로 판단된다.

KIS 잔고 현재 보유:
- `0101N0` RISE AI전력인프라
- `059120` 아진엑스텍
- `125020` 티씨머티리얼즈
- `126730` 코칩
- `199820` 제일일렉트릭
- `307930` 컴퍼니케이
- `321260` 프로이천
- `332570` PS일렉트로닉스
- `473590` ACE 미국주식베스트셀러
- `491090` KODEX 미국테크TOP3플러스

DB의 5/4 submitted buy와 대부분 일치한다. 다만 일부 수량은 DB 주문 수량과 KIS 보유 수량이 다르므로 부분체결/부분매도/주문상태 미반영 가능성이 있다.

## 성과 저조 원인 가설과 근거

1. 5/4 잔여 포지션이 계좌 성과를 지배한다.
   - 5/4 매수 후 매도 0건.
   - 손실 종목이 며칠간 남아 시장 상승 효과를 상쇄했다.

2. 5/6은 프로세스 상 S2/S4/S5에서 보수화되어 S6 주문 기회가 0이 됐다.
   - mixed tone, low S4 confidence, defensive plan, min confidence 0.7.

3. 5/7은 positive 장세였지만 S6 실제 진입은 2종목뿐이었다.
   - 후보는 많았지만 실제 신호는 적고, 한 후보는 confidence threshold로 차단.

4. 체결/청산 확인 부재로 리뷰와 실제 계좌가 분리됐다.
   - `submitted` 상태가 체결처럼 취급되고, 손익은 0으로 남는다.

5. KIS 호출 제한 대응이 부족해 5/4 매수 실패가 다수 발생했다.
   - EGW00201/EGW00133 계열 실패가 주문 실패의 주요 원인.

## 즉시 수정해야 할 항목

1. S9 청산 소스를 KIS 실제 잔고 기준으로 확장하고, 전일 잔여 포지션 정책을 명확히 한다.
2. `_restore_positions_from_db()`를 buy-only 복원이 아니라 net position 복원으로 수정한다.
3. 이미 sell submitted/filled인 종목은 재복원 및 EOD 재매도 대상에서 제외한다.
4. EOD 매도 성공 조건을 `HTTP 200`이 아니라 주문번호/체결/잔고확인 기준으로 강화한다.
5. Fill poller와 `trading_orders` 상태 전이를 정상화한다.
6. S10 Review & Audit 손익 산식을 `trading_signals.realized_pnl` 중심에서 `fills/잔고/주문` 중심으로 변경한다.
7. KIS rate limit/token issuance 호출을 전역 큐/캐시로 묶어 5/4 같은 대량 실패를 줄인다.

## 다음 작업계획서 항목

1. **P1 청산/포지션 정합성 수정**
   - 대상: `decision_engine._restore_positions_from_db`, `eod_liquidation`, `order_executor.execute_sell`, fill poller.
   - 완료 기준: 재시작 후 이미 매도된 종목이 복원되지 않고, S9 후 KIS 잔고와 DB net position이 일치한다.

2. **P1 체결/손익 파이프라인 수정**
   - 대상: `fill_poller`, `trading_orders`, `fills`, `daily_summary`, `review_audit`.
   - 완료 기준: submitted/filled/cancelled 상태가 분리되고, S10 손익이 KIS 체결/잔고와 대조 가능하다.

3. **P2 상승장 미진입 진단/전략 조정**
   - 대상: S2 장중 보정, S4/S5 threshold, S6 missed/shadow 기록.
   - 완료 기준: 5/6 같은 강한 장에서 no-trade가 발생하면 S2/S4/S5/S6 중 탈락 지점과 후보별 사유가 DB에 남는다.

