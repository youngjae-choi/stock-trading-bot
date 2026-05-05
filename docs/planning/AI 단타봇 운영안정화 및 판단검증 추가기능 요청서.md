AI 단타봇 운영안정화 및 판단검증 추가기능 요청서
1. 문서 목적
본 문서는 기존 설계변경 요청서와 S3~S5 동작프로세스 변경요청서에 이어, Dantabot AI 단타매매 시스템의 실전 운영 안정성, AI 판단 검증, 학습 품질 관리, 디버깅/복기 기능을 강화하기 위한 추가 기능 요청서이다.

기존 문서에서 정의한 핵심 구조는 다음과 같다.

- RulePack 전체 매일 생성 폐지
- 고정 Base RulePack + Risk Profile 4종 유지
- S5는 Daily Trading Plan 생성
- Review & Audit → Learning Memory → 다음날 S3~S5 반영
- 외부자료 → Expert Knowledge Base → S3~S5 반영
- 모든 주문은 Global Risk Guard를 통과해야 함
본 문서에서는 여기에 다음 기능들을 추가한다.

1. 주문 전 최종 검증
2. 데이터 품질 감시
3. AI 판단의 가상 검증
4. 놓친 기회와 잘못된 판단 추적
5. 전문가 지식 성과 추적
6. 사용자 승인 큐
7. 무매매 사유 기록
8. 판단 설명 및 리플레이 기능
핵심 목적은 다음과 같다.

AI가 더 많은 판단을 하게 하되,
실제 매매는 더 안전하고 검증 가능하게 만든다.
2. 추가 기능 전체 목록
본 문서에서 추가 요청하는 기능은 다음과 같다.

A. 실전 운영 안정성
   1. Order Pre-Flight Check
   2. Data Quality Guard
   3. Alert Center

B. AI 판단 검증
   4. Paper Trading Shadow Mode
   5. Missed Opportunity Tracker
   6. False Positive Tracker
   7. Confidence Calibration

C. 학습 품질 관리
   8. Knowledge Impact Scoring
   9. Human Approval Queue
   10. No Trade Reason 기록

D. 디버깅/복기
   11. Explainability Panel
   12. Replay / Simulation
   13. Cost & Latency Monitor
3. 기능 우선순위
3.1 1차 필수 기능
실전 운영 전 반드시 우선 구현할 기능이다.

1. Order Pre-Flight Check
2. Data Quality Guard
3. No Trade Reason 기록
4. Paper Trading Shadow Mode
5. Missed Opportunity Tracker
6. False Positive Tracker
7. Human Approval Queue
3.2 2차 고도화 기능
시스템이 안정화된 뒤 구현할 기능이다.

1. Explainability Panel
2. Alert Center
3. Knowledge Impact Scoring
4. Confidence Calibration
5. Replay / Simulation
3.3 3차 운영 최적화 기능
운영 규모가 커진 뒤 추가할 기능이다.

1. Cost & Latency Monitor
2. 고급 Regime Detection
3. 장기 성과 기반 자동 리포트
4. 전략별 A/B 테스트
A. 실전 운영 안정성 기능
4. Order Pre-Flight Check
4.1 목적
Order Pre-Flight Check는 주문 직전에 마지막으로 실행되는 안전 검증 단계이다.

현재 주문 흐름은 다음과 같이 변경되어야 한다.

AI 판단
→ Decision Engine
→ Global Risk Guard
→ Order Pre-Flight Check
→ KIS REST 주문 실행
Pre-Flight Check는 AI 판단이나 Daily Plan이 정상이어도, 실제 주문 직전의 시장 상태와 시스템 상태가 안전하지 않으면 주문을 차단해야 한다.

4.2 검증 항목
주문 직전 아래 항목을 검증한다.

- 현재 장 운영 시간인지
- 신규매수 금지 시간 이후가 아닌지
- 장마감 강제청산 시간과 충돌하지 않는지
- 현재가가 직전 tick 대비 과도하게 급변하지 않았는지
- 호가 스프레드가 과도하지 않은지
- 예상 주문 수량이 종목당 최대 비중을 초과하지 않는지
- 총 보유 종목 수가 max_positions를 초과하지 않는지
- 동일 종목 중복 주문이 아닌지
- 해당 종목에 미체결 주문이 이미 있는지
- WebSocket 현재가와 REST 현재가 차이가 과도하지 않은지
- 마지막 tick 수신 시각이 너무 오래되지 않았는지
- 종목 상태가 거래정지, 투자경고, 관리종목으로 변경되지 않았는지
- 긴급정지 상태가 아닌지
- Risk Guard 상태가 신규 진입 허용인지
4.3 차단 사유 예시
MARKET_CLOSED
NEW_ENTRY_CUTOFF_PASSED
FORCE_EXIT_WINDOW
PRICE_SPIKE_TOO_FAST
SPREAD_TOO_WIDE
POSITION_LIMIT_EXCEEDED
DUPLICATE_ORDER
PENDING_ORDER_EXISTS
WS_REST_PRICE_MISMATCH
STALE_TICK
SYMBOL_HALTED
EMERGENCY_HALT_ACTIVE
RISK_GUARD_BLOCKED
4.4 출력 구조 예시
{
  "order_id": "preflight-20260504-001",
  "symbol_code": "123456",
  "side": "BUY",
  "requested_quantity": 100,
  "requested_price": 10200,
  "passed": false,
  "block_reason": "STALE_TICK",
  "details": {
    "last_tick_age_seconds": 14.2,
    "max_allowed_tick_age_seconds": 5
  },
  "checked_at": "2026-05-04T09:12:03+09:00"
}
4.5 DB 테이블 제안
order_preflight_checks
주요 필드:

- id
- order_request_id
- symbol_code
- side
- requested_quantity
- requested_price
- passed
- block_reason
- details_json
- checked_at
5. Data Quality Guard
5.1 목적
자동매매에서 데이터 품질 문제는 잘못된 매수/매도 판단으로 직결된다.

Data Quality Guard는 KIS REST, KIS WebSocket, DB 저장 상태, 시세 데이터의 신뢰성을 감시하고, 데이터가 불안정할 경우 신규 진입 또는 전체 매매를 제한한다.

5.2 감시 항목
- WebSocket tick 지연
- WebSocket 연결 끊김
- REST 현재가와 WebSocket 현재가 괴리
- 거래량 데이터 누락
- 호가 데이터 누락
- 체결통보 누락
- DB 저장 실패
- 동일 tick 중복 처리
- 종목코드 매핑 오류
- 전일 종가 누락
- 시가/고가/저가/현재가 비정상 값
- LLM 출력 JSON 파싱 오류
- S3/S4/S5 결과 Schema 오류
5.3 대응 정책
특정 종목 tick 지연
→ 해당 종목 신규매수 금지

WebSocket 전체 연결 장애
→ 신규매수 전체 중단

REST/WS 가격 괴리 과다
→ 해당 종목 주문 보류

DB 저장 실패
→ 주문 실행 차단 또는 Safe Mode 진입

체결통보 누락
→ REST 잔고 재조회 후 포지션 동기화

LLM JSON 오류
→ Daily Plan 활성화 금지
5.4 상태값
NORMAL
WARNING
DEGRADED
BLOCK_NEW_ENTRY
EMERGENCY
5.5 출력 예시
{
  "status": "DEGRADED",
  "new_entry_allowed": false,
  "issues": [
    {
      "type": "WS_TICK_DELAY",
      "symbol_code": "123456",
      "severity": "high",
      "message": "최근 tick 수신이 12초 지연됨"
    }
  ],
  "checked_at": "2026-05-04T09:15:00+09:00"
}
5.6 DB 테이블 제안
data_quality_events
data_quality_snapshots
6. Alert Center
6.1 목적
운영 중 발생하는 위험, 오류, 차단, 지연, 검증 실패를 한 화면에서 확인하기 위한 중앙 알림 시스템이다.

6.2 알림 유형
- Risk Guard 발동
- 일일 손실 한도 70% 도달
- 일일 손실 한도 도달
- WebSocket 지연
- REST 오류
- DB 저장 실패
- 미체결 주문 장시간 유지
- 체결통보 누락
- S5 Daily Plan 검증 실패
- THEME_SPIKE 과다 후보
- 특정 종목 급변
- 긴급정지 실행
- Order Pre-Flight 차단
- Data Quality Guard DEGRADED 전환
6.3 알림 심각도
INFO
WARNING
ERROR
CRITICAL
6.4 DB 테이블 제안
system_alerts
주요 필드:

- alert_id
- severity
- category
- title
- message
- related_symbol
- related_order_id
- status
- created_at
- resolved_at
B. AI 판단 검증 기능
7. Paper Trading Shadow Mode
7.1 목적
실매매와 별도로 AI가 제안했지만 실제 매매하지 않은 후보 또는 차단된 후보를 가상 매매로 추적한다.

목적:

- AI가 선택한 후보의 실제 잠재 성과 검증
- Risk Guard 또는 조건 미달로 제외된 종목의 이후 흐름 확인
- 너무 보수적인 필터 여부 확인
- S4/S5 판단 품질 개선
7.2 Shadow 추적 대상
- S4 후보였으나 S5에서 제외된 종목
- S5 allowed=false 종목
- confidence 미달로 제외된 종목
- Risk Guard 때문에 차단된 종목
- Pre-Flight Check에서 차단된 종목
- 실제 매수 조건에 근접했으나 미진입한 종목
7.3 가상 매매 방식
Shadow Mode는 실제 주문을 내지 않는다.

대신 아래 기준으로 가상 진입/청산을 기록한다.

- virtual_entry_price
- virtual_entry_time
- virtual_exit_price
- virtual_exit_time
- virtual_exit_reason
- virtual_pnl
- 실제 매매했을 경우의 예상 결과
7.4 출력 예시
{
  "shadow_id": "shadow-20260504-001",
  "date": "2026-05-04",
  "symbol_code": "123456",
  "symbol_name": "예시종목",
  "origin_stage": "S5_EXCLUDED",
  "origin_reason": "confidence 0.62 < min_ai_confidence 0.65",
  "virtual_entry_price": 10200,
  "virtual_exit_price": 10800,
  "virtual_pnl_rate": 0.058,
  "virtual_exit_reason": "TRAILING_STOP",
  "lesson": "min_ai_confidence 기준이 과도했을 가능성"
}
7.5 DB 테이블 제안
shadow_trades
shadow_trade_events
8. Missed Opportunity Tracker
8.1 목적
매수하지 않았으나 이후 크게 상승한 종목을 추적하여 시스템이 지나치게 보수적인지 판단한다.

8.2 추적 대상
- S3에서 제외했는데 급등한 종목
- S4 후보였지만 S5에서 제외 후 급등한 종목
- S5 allowed=false였는데 급등한 종목
- 조건 접근률 90% 이상이었으나 미진입 후 급등한 종목
- Risk Guard 때문에 차단됐으나 이후 상승한 종목
- Pre-Flight 차단 후 상승한 종목
8.3 기록 항목
- missed_stage
- missed_reason
- price_at_missed
- max_return_after_10m
- max_return_after_30m
- max_return_until_eod
- 해당 종목의 profile 예정값
- 적용된 knowledge_refs
- 적용된 memory_refs
- 개선 후보
8.4 출력 예시
{
  "symbol_code": "123456",
  "missed_stage": "S5_EXCLUDED",
  "missed_reason": "confidence 0.62 < min_ai_confidence 0.65",
  "price_at_missed": 10000,
  "max_return_after_30m": 0.047,
  "max_return_until_eod": 0.092,
  "suggested_learning": "min_ai_confidence가 과도했을 가능성"
}
8.5 DB 테이블 제안
missed_opportunities
9. False Positive Tracker
9.1 목적
AI가 좋다고 판단했지만 실제로 손실을 만든 후보 또는 거래를 추적한다.

9.2 추적 대상
- S4 점수가 높았으나 손실 발생
- S5 confidence가 높았으나 손실 발생
- Expert Knowledge가 적용됐으나 손실 발생
- Review Memory가 반영됐으나 손실 발생
- 특정 Risk Profile 배정 후 반복 손실 발생
9.3 기록 항목
- false_positive_type
- original_score
- original_confidence
- assigned_profile
- entry_reason
- loss_reason
- exit_reason
- applied_knowledge_ids
- applied_memory_ids
- suggested_penalty
9.4 출력 예시
{
  "symbol_code": "654321",
  "false_positive_type": "HIGH_CONFIDENCE_LOSS",
  "original_confidence": 0.84,
  "assigned_profile": "HIGH_VOL",
  "pnl_rate": -0.027,
  "exit_reason": "INITIAL_STOP_LOSS",
  "applied_knowledge_ids": ["knw-20260503-001"],
  "suggested_learning": "해당 패턴의 S4 가점을 낮추는 것을 검토"
}
9.5 DB 테이블 제안
false_positive_cases
10. Confidence Calibration
10.1 목적
AI가 부여한 confidence 값이 실제 성과와 얼마나 일치하는지 검증한다.

AI confidence가 높을수록 실제 승률과 평균손익도 높아야 한다.

10.2 분석 기준
Confidence 구간별로 성과를 집계한다.

0.90 이상
0.80 ~ 0.90
0.70 ~ 0.80
0.60 ~ 0.70
0.60 미만
10.3 출력 예시
Confidence 구간 | 거래수 | 승률 | 평균손익 | 평가
0.80 이상       | 12    | 67%  | +0.8%   | 신뢰 가능
0.70~0.80       | 18    | 55%  | +0.2%   | 보통
0.60~0.70       | 22    | 41%  | -0.4%   | 주의
10.4 활용
- min_ai_confidence 조정 후보 생성
- AI confidence 신뢰도 평가
- 특정 LLM Provider의 판단 품질 비교
- Daily Plan 검증 시 confidence 보정
10.5 DB 테이블 제안
confidence_calibration_daily
confidence_calibration_bins
C. 학습 품질 관리 기능
11. Knowledge Impact Scoring
11.1 목적
Expert Knowledge Base에 저장된 각 지식이 실제 매매 성과에 도움이 되는지 검증한다.

외부자료에서 추출한 지식은 무조건 맞는 것이 아니므로, 적용 후 성과를 추적해야 한다.

11.2 분석 항목
- knowledge_id
- 적용 종목 수
- 실제 거래 수
- 가상 거래 수
- 승률
- 평균손익
- 최대손실
- 적용 시장 톤
- 잘 맞는 시장 조건
- 잘 안 맞는 시장 조건
- 최근 성과 추세
11.3 지식 상태값
active
watch
deprecated
rejected
11.4 출력 예시
{
  "knowledge_id": "knw-20260503-001",
  "title": "VWAP 위 눌림 후 재상승",
  "applied_count": 28,
  "trade_count": 18,
  "win_rate": 0.61,
  "avg_pnl": 0.0042,
  "best_market_tone": "positive",
  "worst_market_tone": "volatile",
  "status_suggestion": "active"
}
11.5 DB 테이블 제안
knowledge_impact_stats
knowledge_impact_daily
12. Human Approval Queue
12.1 목적
AI가 제안한 변경사항 중 자동 반영하면 안 되는 항목을 사용자 승인 대기열로 관리한다.

12.2 승인 필요 항목
- Risk Profile 원본 값 변경
- Base RulePack 변경
- Global Risk Guard 변경
- Expert Knowledge 상태 변경
- Knowledge apply_level 상향
- 특정 전략을 고정 규칙으로 승격
- min_ai_confidence 기본값 변경
- S4 scoring weight 고정 변경
12.3 승인 불필요 또는 자동 가능 항목
보수적 방향의 Daily Override는 자동 반영 가능하다.

- THEME_SPIKE 허용 개수 축소
- 신규매수 강도 낮추기
- min_ai_confidence 당일 상향
- volume_filter_multiplier 당일 상향
- 특정 종목 당일 제외
12.4 승인 큐 항목 예시
{
  "approval_id": "appr-20260504-001",
  "type": "RISK_PROFILE_CHANGE",
  "target": "HIGH_VOL.trailing_stop_rate",
  "current_value": 0.05,
  "suggested_value": 0.045,
  "reason": "최근 HIGH_VOL 평균 수익 반납률이 68%로 높음",
  "evidence_window_days": 5,
  "status": "pending"
}
12.5 상태값
pending
approved
rejected
deferred
simulation_only
12.6 DB 테이블 제안
human_approval_queue
approval_decision_logs
13. No Trade Reason 기록
13.1 목적
매매가 없었던 날 또는 특정 후보에 진입하지 않은 이유를 구조화하여 기록한다.

단순히 오늘 주문 없음으로 남기면 복기와 개선이 불가능하다.

13.2 일일 무매매 사유 예시
{
  "date": "2026-05-04",
  "no_trade": true,
  "summary": "S4 후보는 21개였으나 S5 조건과 장중 진입 조건을 충족한 종목이 없었음",
  "details": {
    "s4_candidates": 21,
    "s5_allowed": 5,
    "max_signal_proximity": 0.72,
    "confidence_failed": 3,
    "vwap_failed": 2,
    "volume_reacceleration_failed": 4,
    "risk_guard_blocked": 0,
    "preflight_blocked": 0
  },
  "learning_candidate": "진입 조건이 시장 톤 대비 과도하게 엄격했는지 검토 필요"
}
13.3 후보별 미진입 사유
- confidence 미달
- VWAP 조건 미충족
- 거래량 재증가 미확인
- Risk Guard 차단
- Pre-Flight Check 차단
- Data Quality 문제
- 신규매수 시간 초과
- 과열 추격 위험
- Expert Knowledge 기준 제외
13.4 DB 테이블 제안
no_trade_daily_reasons
candidate_no_entry_reasons
D. 디버깅 및 복기 기능
14. Explainability Panel
14.1 목적
AI가 왜 특정 종목을 선택했는지, 왜 특정 Profile을 배정했는지, 왜 진입 또는 제외했는지를 운영자가 이해할 수 있도록 표시한다.

14.2 표시 항목
종목별 설명:

- S4 점수
- 기술적 근거
- 거래량/거래대금 근거
- 테마/뉴스 근거
- Review Memory 반영 내용
- Expert Knowledge 반영 내용
- 배정 Risk Profile
- entry_policy
- confidence
- allowed 여부
- 제외 사유
- Risk Guard 적용 내용
14.3 예시
종목: 예시종목

선택 이유:
- S4 점수: 0.74
- 기술적 근거: VWAP 위 눌림 후 재상승
- 테마 근거: 전력기기 섹터 강세
- Review Memory: 최근 MID_VOL 성과 양호
- Expert Knowledge: 첫 급등 추격보다 눌림 재상승 선호
- 배정 Profile: HIGH_VOL
- 진입 정책: wait_for_pullback
- 리스크 제한: 최대 비중 8%
14.4 적용 화면
- Funnel Monitor
- Daily Plan & RulePack
- Trading Monitor
- Review & Audit
15. Replay / Simulation
15.1 목적
장중 tick, 판단, 주문, 체결, 포지션 상태 변화를 저장하고 장 종료 후 재생할 수 있도록 한다.

15.2 저장 대상 이벤트
- tick 수신
- S4 후보 상태
- S5 Daily Plan 상태
- 조건 접근률 변화
- Decision Engine 판단
- Risk Guard 통과/차단
- Pre-Flight Check 결과
- 주문 전송
- 주문 체결
- 포지션 생성
- 최고가 갱신
- 트레일링 활성화
- 손절선 상향
- 청산 판단
- 청산 주문
- 장마감 강제청산
15.3 Replay 용도
- 왜 매수했는지 재현
- 왜 매도했는지 재현
- 손절선이 제대로 올라갔는지 확인
- 트레일링 스탑 버그 확인
- WebSocket 지연 확인
- 같은 데이터를 다른 Profile로 재시뮬레이션
- S4/S5 판단 품질 검증
15.4 DB 테이블 제안
trading_event_log
replay_sessions
simulation_results
16. Cost & Latency Monitor
16.1 목적
LLM 호출, KIS API 호출, WebSocket 이벤트 처리, DB 저장의 비용과 지연을 추적한다.

16.2 추적 항목
- S2 LLM 호출 시간
- S4 LLM 호출 시간
- S5 LLM 호출 시간
- LLM Provider별 실패율
- fallback 발생 횟수
- 평균 응답 시간
- 토큰 사용량
- 일별 LLM 비용
- KIS REST 호출 수
- KIS REST 오류율
- WebSocket tick 처리 지연
- DB write latency
16.3 DB 테이블 제안
provider_latency_stats
llm_usage_daily
api_latency_events
E. 화면 변경 요청
17. Today Control 화면 추가 항목
상단 또는 운영 현황에 아래 상태를 추가한다.

- Data Quality 상태
- Shadow Mode 상태
- 오늘 Pre-Flight 차단 수
- 오늘 Missed Opportunity 수
- 오늘 False Positive 후보 수
- 승인 대기 항목 수
- 최근 Critical Alert 수
18. Trading Monitor 화면 추가 항목
매수 후보 테이블에 아래 컬럼 추가.

- signal_proximity
- no_entry_reason
- preflight_status
- data_quality_status
- shadow_tracking 여부
- missed_opportunity 여부
보유 포지션 테이블에 아래 컬럼 추가.

- 진입 후 최고가
- 현재 손절선
- 트레일링 활성 여부
- 손절선까지 거리
- 마지막 tick age
- Data Quality 상태
19. Review & Audit 화면 추가 항목
아래 영역을 추가한다.

- No Trade Reason
- Missed Opportunity Summary
- False Positive Summary
- Shadow Trading 결과
- Knowledge Impact Summary
- Confidence Calibration
- Human Approval Queue 요약
20. Knowledge Base 화면 추가 항목
Expert Knowledge별로 아래 성과를 표시한다.

- 적용 횟수
- 실제 거래 수
- Shadow 거래 수
- 승률
- 평균손익
- 현재 상태
- 상태 변경 제안
21. Data & API 화면 추가 항목
Data Quality Guard 상태를 표시한다.

- KIS REST 상태
- KIS WebSocket 상태
- REST/WS 가격 괴리 상태
- DB 저장 상태
- Tick 지연 상태
- 체결통보 상태
- Data Quality 종합 상태
22. 신규 화면: Alert Center
API Logs 화면 제거 후 Knowledge Base를 추가할 예정이지만, Alert Center는 별도 탭 또는 Today Control 내 패널로 제공한다.

표시 항목:

- 현재 활성 알림
- Critical 알림
- Warning 알림
- 해결된 알림
- 알림별 원인
- 관련 종목/주문/단계
- 조치 상태
23. 신규 화면 또는 패널: Human Approval Queue
표시 항목:

- 승인 대기 항목
- 변경 대상
- 현재 값
- 제안 값
- 제안 이유
- 근거 기간
- 예상 영향
- 승인/거절/보류/시뮬레이션 버튼
F. API 변경 제안
24. Order Pre-Flight API
POST /api/orders/preflight-check
GET  /api/orders/preflight-checks
GET  /api/orders/preflight-checks/{id}
25. Data Quality API
GET  /api/data-quality/status
GET  /api/data-quality/events
POST /api/data-quality/check
26. Shadow Trading API
GET  /api/shadow-trades
POST /api/shadow-trades/create
POST /api/shadow-trades/evaluate
GET  /api/shadow-trades/summary
27. Opportunity/False Positive API
GET  /api/missed-opportunities
POST /api/missed-opportunities/detect
GET  /api/false-positives
POST /api/false-positives/detect
28. Approval Queue API
GET  /api/approval-queue
POST /api/approval-queue
PUT  /api/approval-queue/{id}/approve
PUT  /api/approval-queue/{id}/reject
PUT  /api/approval-queue/{id}/defer
PUT  /api/approval-queue/{id}/simulation-only
29. Explainability API
GET /api/explain/symbol/{symbol_code}
GET /api/explain/daily-plan/{daily_plan_id}
GET /api/explain/order/{order_id}
30. Replay API
GET  /api/replay/sessions
POST /api/replay/sessions/create
GET  /api/replay/sessions/{id}/events
POST /api/replay/simulate
G. 완료 기준
31. 1차 완료 기준
아래 조건을 만족하면 본 추가 기능의 1차 구현 완료로 본다.

- 주문 직전 Pre-Flight Check가 실행됨
- Pre-Flight 차단 사유가 DB에 저장됨
- Data Quality Guard가 WebSocket 지연과 REST/WS 가격 괴리를 감지함
- 매매가 없었던 날 No Trade Reason이 구조화되어 저장됨
- S4/S5 제외 후보가 Shadow Mode로 추적됨
- Missed Opportunity가 탐지되어 Review & Audit에 표시됨
- False Positive 사례가 탐지되어 Review & Audit에 표시됨
- AI 제안 중 승인 필요 항목이 Human Approval Queue에 등록됨
32. 2차 완료 기준
- Knowledge Impact Scoring이 작동함
- Confidence Calibration 리포트가 생성됨
- Explainability Panel에서 종목별 판단 근거를 확인할 수 있음
- Alert Center에서 주요 위험 알림을 확인할 수 있음
- Trading Event Log 기반 Replay가 가능함
33. 최종 요약
본 추가 기능의 핵심은 다음과 같다.

AI 판단을 더 많이 활용하되,
실제 주문은 더 엄격하게 검증한다.

매수하지 않은 종목도 추적하여 기회비용을 학습한다.
잘못 매수한 종목도 추적하여 False Positive를 줄인다.
외부 전문가 지식도 실제 성과로 검증한다.
AI가 제안한 위험한 변경은 사용자 승인 없이는 적용하지 않는다.
매매하지 않은 이유도 반드시 기록한다.
한 줄 결론:

이 기능들은 Dantabot을 단순 AI 매매봇이 아니라, 판단을 검증하고 실패에서 학습하며 안전하게 진화하는 운영형 AI 트레이딩 시스템으로 만들기 위한 필수 안정화 장치이다.