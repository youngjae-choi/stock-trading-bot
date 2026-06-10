# 전략엔진 완성 + 실계좌 안전벨트 — 개발계획서 v1.0

> PM 승인 2026-06-10: "A 진행 후 B까지 진행. 서브에이전트로 개발/테스트 완료."
> 근거: 2026-06-10 4축 시스템 감사 (매도엔진/매수전략/실계좌안전/데이터품질)

## 원본 요구사항 (PM)
> - 활발하게 거래하면서 추후 자동화매매에 사용할 시장상황별 매수/매도전략 발굴/검증
> - 이후 실계좌를 이용한 완전자동화 Daytrading bot 개발

## Phase A — 전략 발굴·검증 엔진 완성

| # | 작업 | 파일 | 핵심 |
|---|------|------|------|
| A1 | 10초봉 DB 영구 저장 | intraday_bar_engine.py, bar_store.py(신규), scheduler.py | 봉 마감 시 버퍼 적재→60초 주기 flush, retention 30일, 백테스트 토대 |
| A2 | weight·레짐 필터 → 매수 판정 반영 | buy_condition_framework.py, exploration_decision.py, decision_engine.py | weight<임계(0.2) 그룹 제외, assigned_to≠현재레짐 그룹 제외(빈 값=전체) |
| A3 | EV 층화 + 중복가중 완화 | ev_analysis.py, ev_pruning.py | 다중그룹 발화 시 1/N 분할 가중, regime×group 층화 집계 추가 |
| A4 | 손실한도 평가손익 포함 + fail-closed | order_preflight.py | unrealized 포함 일중손실 산출, 산출 불가 시 차단(fail-closed) |
| A5 | MFE/MAE·보유시간 태깅 | position_manager.py, order_executor.py, trade_tagging.py | 포지션 peak/trough 추적→청산 시 outcome에 기록, 백필은 merge |
| A6 | shadow 추적 S4 확대 | missed_opportunity.py, scheduler.py | S4 선정-미진입 종목 EOD shadow_trades 기록→기존 사후수익 추적 재사용 |

## Phase B — 실계좌 안전벨트

| # | 작업 | 파일 | 핵심 |
|---|------|------|------|
| B1 | 부분체결 잔량 재주문 + 매도실패 포지션 보존 | order_executor.py, fill_poller.py | 매도 partial 정체 시 잔량 시장가 재주문, 제출 실패 시 remove_position 금지 |
| B2 | 손절 REST 폴링 백업 | position_manager.py, scheduler.py | WS 무수신 90초+보유 중이면 REST 현재가로 손절 판정(1분 주기) |
| B3 | WAL + rate-limit 동적 감속 + 자동 emergency halt | db.py, utils.py, ops_watchdog.py | PRAGMA WAL/busy_timeout, EGW00201 시 일시 RPS 감속, 일중손실 임계 도달 시 halt 설정+CRITICAL 알림 |

## 실행 방식
- 서브에이전트 구동 TDD, 웨이브별 파일 소유권 분리(동일 파일 동시 수정 금지)
- Wave1: A1, A2, A3, A4 (병렬) → Wave2: A5, A6, B1 → Wave3: B2, B3
- 각 웨이브 후 지휘자가 전체 회귀(pytest tests/unit) + diff 리뷰 + 커밋
- 서버 반영은 장 마감 시간대 systemctl restart (지휘자)

## 완료 기준
- 전체 유닛 테스트 통과, 신규 기능별 테스트 존재
- weight/레짐이 실제 판정을 바꾸는 테스트 증명
- 10초봉이 DB에 쌓이고 retention 동작
- 손실한도가 평가손익 포함으로 차단되는 테스트 증명
