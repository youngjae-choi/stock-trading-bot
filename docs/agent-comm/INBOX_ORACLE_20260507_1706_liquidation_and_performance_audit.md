# INBOX_ORACLE - 2026-05-07 17:06 KST - 청산 미실행 및 시장 대비 성과 감사

## 요청자

Sisyphus

## 담당 페르소나

Oracle

## 배경

PM 질문:

1. 청산 시간이 한참 지났는데 테스트 계좌에 아직도 종목을 보유하고 있다. 왜 일괄매도를 하지 않았는가?
2. 2026-05-04, 2026-05-06, 2026-05-07 KOSPI가 크게 상승했는데 테스트 계좌 평가금액 기준 수익은 약 0.4%다. 단타 시스템이면 적어도 더 나야 하는 것 아닌가? 프로세스 중 무엇이 잘못되었는지 봐야 한다.

참고:

- PM이 언급한 KOSPI 상승률은 정확한 수치 검증보다 “강한 상승장 대비 계좌 성과가 낮다”는 문제의식이 핵심이다.
- 외부 확인 결과 2026-05-04 KOSPI는 약 +5.12%, 2026-05-06은 약 +6.45%로 보도된 강한 상승장이 맞다. 2026-05-07도 장중/종가 기준 상승 보도가 있다.

## 금지 사항

- 파일 수정 금지.
- git commit 금지.
- 매수/매도/청산/주문 API 호출 금지.
- `/api/v1/orders/*` POST, `/api/v1/kis/order/*`, `/api/v1/decision/activate`, `/api/v1/trades/run-summary`, `/api/v1/review-audit/run` 호출 금지.
- 실제 S1~S11 실행 금지.
- 외부 LLM 호출 금지.

## 허용 사항

- DB read-only 조회.
- 서버 로그 read-only 조회.
- read-only GET API 조회.
- KIS 잔고/주문내역 read-only 조회가 이미 구현된 GET 또는 내부 read-only 함수로 가능하면 수행해도 된다.
  - 단, 주문성 endpoint는 절대 호출하지 말 것.
  - 호출한 read-only KIS API는 보고서에 명시할 것.

## 감사 목표 1: 왜 계좌에 종목이 남아 있는가?

확인할 것:

- `schedule_postprocess_time`이 오늘 언제였는지.
- 15:20 KST 후처리 프로세스 S9→S10이 실제 실행됐는지.
- `logs/server.log`에서 `PostProcess`, `Job S9`, `EOD liquidation`, `liquidate`, `Decision Engine deactivate`, `Review Audit` 관련 로그 확인.
- DB에서 오늘 청산/주문/포지션 관련 테이블 확인.
  - `orders`
  - `trading_signals`
  - `order_preflight_checks`
  - `position_stop_states`
  - `daily_trade_summary`
  - `daily_review_reports`
  - `pipeline_run_audit`
- 실제 계좌 보유와 DB 포지션/주문이 일치하는지.
- 청산이 안 된 이유 후보를 구분하라.
  - scheduler가 15:20 전에 재시작되어 job 등록이 늦었거나 next_run 계산 문제
  - postprocess job이 실행되지 않음
  - S9 job이 실행됐지만 position source를 못 찾음
  - engine.mode/MONITOR 또는 테스트 계좌 정책 때문에 실매도 차단
  - order route/preflight/emergency halt/risk guard가 매도까지 막음
  - KIS 주문 실패/API 실패
  - 시스템이 실제 계좌 보유를 DB로 복원하지 못함

## 감사 목표 2: 왜 강한 시장 대비 성과가 낮은가?

기간: 가능하면 2026-05-04, 2026-05-06, 2026-05-07 중심.

확인할 것:

- 각 날짜 S2 시장톤 판단.
- S3 universe raw/filtered.
- S4 후보와 confidence, output_count.
- S5 Daily Plan 배정 종목/profile.
- S6 신호 발생 여부.
- S7 주문 실행 여부.
- S8 포지션 관리/손절/트레일링 여부.
- S9 청산 여부.
- Missed Entries / False Positive / Shadow Trading / Review가 기록됐는지.
- 계좌 보유 종목이 전략이 의도한 종목인지, 아니면 이전 수동/잔여 포지션인지.

분석 관점:

- 시장이 오른 것과 시스템 universe가 같은 섹터/주도주를 잡았는지.
- S3/S4에서 거래대금/가격/데이터 결측 때문에 후보가 과도하게 줄었는지.
- S5가 너무 보수적인 profile/threshold를 걸었는지.
- S6가 active 되지 않아 신호/주문이 거의 없었는지.
- 매수는 했는데 청산/트레일링이 약했는지.
- 테스트 계좌가 실제 전략 주문이 아니라 과거 보유분 영향인지.

## 출력 형식

결과를 아래 파일로 작성하라.

`docs/agent-comm/OUTBOX_ORACLE_20260507_1706_liquidation_and_performance_audit.md`

포함 항목:

- Findings 우선: P1/P2/P3, 파일/라인 또는 DB/log 근거, 영향, 제안
- 청산 미실행 원인 결론
- 2026-05-07 15:20 후처리 타임라인
- 현재 보유 종목 출처 판단
- 2026-05-04/06/07 성과 저조 원인 가설과 근거
- 즉시 수정해야 할 항목
- 다음 작업계획서 항목
