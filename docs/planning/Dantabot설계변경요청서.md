Dantabot 설계변경 요청서
1. 문서 목적
현재 개발 중인 Dantabot Control Console 및 자동매매 엔진의 RulePack 구조를 아래 방향으로 변경 요청한다.

기존 구조는 매일 AI가 RulePack 전체를 새로 생성하고, 해당 RulePack을 모든 감시 종목에 공통 적용하는 방식이었다.

변경 후 구조는 다음과 같다.

고정 Base RulePack
+ 고정 Risk Profile 4종
+ 매일 생성되는 Daily Trading Plan
+ 종목별 Risk Profile Assignment
+ Runtime Risk Guard
즉, 매일 룰 자체를 새로 만드는 구조가 아니라, 고정된 룰팩 프로필을 오늘의 종목에 어떻게 적용할지 결정하는 구조로 변경한다.

2. 핵심 설계 변경 요약
2.1 기존 구조
S1 KIS 토큰 갱신
→ S2 시장 톤 분석
→ S3 유니버스 필터
→ S4 하이브리드 스크리닝
→ S5 RulePack 자동 생성
→ S6 Decision Engine 활성화
기존 S5 - RulePack 자동 생성은 매일 AI가 신규 RulePack을 생성하고 자동 활성화하는 구조였다.

이 구조는 다음 문제가 있다.

- 매일 전략이 흔들림
- 손절률, 익절률, 트레일링 기준이 일관되지 않음
- 백테스트 및 복기가 어려움
- AI가 리스크 한도를 과도하게 완화할 가능성 존재
- 모든 종목에 동일 RulePack을 적용하여 종목별 변동성 반영이 어려움
2.2 변경 구조
S1 KIS 토큰 갱신
→ S2 시장 톤 분석
→ S3 유니버스 필터
→ S4 하이브리드 스크리닝
→ S5 Daily Trading Plan 생성
→ S6 Decision Engine 활성화
변경 후 S5는 RulePack 전체 생성이 아니라 Daily Trading Plan 생성으로 변경한다.

Daily Trading Plan은 아래 정보만 생성한다.

- 오늘 시장 톤
- 오늘 매매 강도
- 오늘 감시 종목
- 종목별 Risk Profile 배정
- 오늘 적용할 조건 강화/완화 여부
- 제외 종목
- 주의 테마
- LLM 분석 요약
3. 최종 목표 구조
Base RulePack
    ↓
Risk Profile Pack 4종
    ↓
Daily Trading Plan
    ↓
Symbol Profile Assignment
    ↓
Python Decision Engine
    ↓
Risk Guard
    ↓
KIS REST 주문 실행
    ↓
KIS WebSocket 체결/시세 감시
    ↓
Web Console 관제
4. RulePack 정책 변경
4.1 매일 새로 만들지 않는 것
아래 항목은 AI가 매일 새로 생성하거나 임의 변경하지 않는다.

- Base RulePack
- Risk Profile 4종
- Global Risk Guard
- 일일 손실 한도
- 주간 손실 한도
- 월간 손실 한도
- 최대 보유 종목 수
- 종목당 최대 비중 상한
- 장마감 강제청산 정책
- 긴급정지 정책
- 고정 익절 미사용 원칙
- 트레일링 스탑 청산 원칙
4.2 매일 새로 만드는 것
아래 항목만 매일 AI 또는 시스템이 생성한다.

- Daily Trading Plan
- 오늘 시장 톤
- 오늘 후보 종목
- 종목별 Risk Profile 배정
- 오늘 거래량 필터 강도
- 오늘 최소 AI 신뢰도
- 오늘 신규매수 허용 여부
- 특정 테마/종목 제외 여부
- 오늘 THEME_SPIKE 허용 개수
5. Risk Profile 4종 도입
전체 종목에 동일 RulePack을 적용하지 않는다.

종목별 특성에 따라 아래 4개 Risk Profile 중 하나를 배정한다.

LOW_VOL
MID_VOL
HIGH_VOL
THEME_SPIKE
5.1 Risk Profile 정의
LOW_VOL
대상:

- 대형주
- 저변동성 종목
- 거래대금 안정적 종목
기본값 예시:

{
  "profile": "LOW_VOL",
  "initial_stop_loss": -0.02,
  "trailing_activate_profit": 0.015,
  "trailing_stop_rate": 0.018,
  "max_position_rate": 0.15,
  "max_holding_minutes": 240
}
MID_VOL
대상:

- 일반적인 중형주
- 보통 변동성 종목
- 기본 단타 감시 종목
기본값 예시:

{
  "profile": "MID_VOL",
  "initial_stop_loss": -0.03,
  "trailing_activate_profit": 0.025,
  "trailing_stop_rate": 0.03,
  "max_position_rate": 0.12,
  "max_holding_minutes": 180
}
HIGH_VOL
대상:

- 고변동성 종목
- 최근 급등락 종목
- 변동성이 큰 섹터 종목
기본값 예시:

{
  "profile": "HIGH_VOL",
  "initial_stop_loss": -0.045,
  "trailing_activate_profit": 0.04,
  "trailing_stop_rate": 0.05,
  "max_position_rate": 0.08,
  "max_holding_minutes": 120
}
THEME_SPIKE
대상:

- 당일 급등 테마주
- 뉴스/테마 기반 급등주
- 거래량 급증 종목
- 고위험 단타 후보
기본값 예시:

{
  "profile": "THEME_SPIKE",
  "initial_stop_loss": -0.06,
  "trailing_activate_profit": 0.05,
  "trailing_stop_rate": 0.06,
  "max_position_rate": 0.05,
  "max_holding_minutes": 60,
  "reentry_allowed": false
}
6. 청산 전략 변경
6.1 고정 익절 제거
기존 설정에는 아래 항목이 존재한다.

익절률 take_profit
변경 후에는 고정 익절률을 기본적으로 사용하지 않는다.

기존 방식:

+3% 도달 시 익절
변경 방식:

고정 익절 목표가 없음
수익 발생 시 트레일링 스탑으로 손절선을 상향
고점 대비 하락폭이 트레일링 기준에 도달하면 청산
6.2 트레일링 스탑 중심 청산
모든 포지션은 아래 구조로 관리한다.

1. 진입 직후 초기 손절선 설정
2. 수익률이 트레일링 활성 기준에 도달하면 트레일링 스탑 활성화
3. 진입 후 최고가 갱신 시 손절선을 상향
4. 손절선은 절대 하향하지 않음
5. 현재가가 손절선 이탈 시 매도
6. 장마감 전까지 매도되지 않으면 당일 전량 청산
6.3 청산 공식
initial_stop_price = entry_price * (1 + initial_stop_loss)
trailing_stop_price = highest_price_since_entry * (1 - trailing_stop_rate)
active_stop_price = max(previous_stop_price, initial_stop_price, trailing_stop_price)
단, active_stop_price는 절대 하향되지 않는다.

6.4 당일 전량 청산 유지
Dantabot은 단타 자동매매 봇이므로 오버나잇 보유를 하지 않는다.

공통 정책:

15:10 신규매수 금지
15:20 당일매매 청산 시작
15:25 미체결 포지션 재정리
15:30 장마감 전 전량 청산 완료 목표
이 정책은 모든 Risk Profile에 공통 적용한다.

7. Rule 적용 우선순위
Rule 적용 우선순위는 다음과 같다.

1순위: Emergency Halt
2순위: Global Risk Guard
3순위: 장마감 강제청산 정책
4순위: Symbol Override
5순위: Risk Profile
6순위: Base RulePack
7순위: Daily Trading Plan
8순위: AI Suggestion
핵심 원칙:

AI Suggestion은 가장 낮은 우선순위다.
Global Risk Guard는 항상 우선한다.
종목별 설정은 가능하지만 전체 리스크 한도를 완화할 수 없다.
8. 데이터 구조 변경 요청
8.1 Base RulePack
신규 또는 기존 RulePack 구조를 아래처럼 분리한다.

{
  "base_rulepack_id": "base-v1.0",
  "version": "1.0",
  "take_profit_enabled": false,
  "force_daily_close": true,
  "force_exit_time": "15:20:00",
  "stop_price_can_only_increase": true,
  "order_execution": {
    "entry_order_type": "limit_or_market_by_policy",
    "exit_order_type": "market_or_safe_limit"
  }
}
8.2 Global Risk Guard
{
  "global_risk": {
    "daily_loss_limit": -0.02,
    "weekly_loss_limit": -0.05,
    "monthly_loss_limit": -0.08,
    "max_positions": 5,
    "max_position_rate_per_stock": 0.1,
    "new_entry_cutoff_time": "15:10:00",
    "force_exit_time": "15:20:00",
    "emergency_halt_enabled": true
  }
}
8.3 Risk Profile Pack
{
  "risk_profile_pack_id": "profile-v1.0",
  "profiles": {
    "LOW_VOL": {
      "initial_stop_loss": -0.02,
      "trailing_activate_profit": 0.015,
      "trailing_stop_rate": 0.018,
      "max_position_rate": 0.15,
      "max_holding_minutes": 240
    },
    "MID_VOL": {
      "initial_stop_loss": -0.03,
      "trailing_activate_profit": 0.025,
      "trailing_stop_rate": 0.03,
      "max_position_rate": 0.12,
      "max_holding_minutes": 180
    },
    "HIGH_VOL": {
      "initial_stop_loss": -0.045,
      "trailing_activate_profit": 0.04,
      "trailing_stop_rate": 0.05,
      "max_position_rate": 0.08,
      "max_holding_minutes": 120
    },
    "THEME_SPIKE": {
      "initial_stop_loss": -0.06,
      "trailing_activate_profit": 0.05,
      "trailing_stop_rate": 0.06,
      "max_position_rate": 0.05,
      "max_holding_minutes": 60,
      "reentry_allowed": false
    }
  }
}
8.4 Daily Trading Plan
매일 생성되는 결과물은 아래 구조를 권장한다.

{
  "daily_plan_id": "daily-2026-05-03",
  "date": "2026-05-03",
  "market_tone": "positive",
  "trading_intensity": "normal",
  "base_rulepack_version": "base-v1.0",
  "risk_profile_version": "profile-v1.0",
  "new_entry_allowed": true,
  "daily_overrides": {
    "volume_filter_multiplier": 2.0,
    "min_ai_confidence": 0.65,
    "max_theme_spike_positions": 1
  },
  "symbol_assignments": [
    {
      "code": "005930",
      "name": "삼성전자",
      "profile": "LOW_VOL",
      "reason": "대형주, 저변동성"
    },
    {
      "code": "000660",
      "name": "SK하이닉스",
      "profile": "MID_VOL",
      "reason": "반도체 섹터 대표주, 중간 변동성"
    },
    {
      "code": "247540",
      "name": "에코프로비엠",
      "profile": "HIGH_VOL",
      "reason": "최근 변동성 확대"
    }
  ],
  "excluded_symbols": [
    {
      "code": "000000",
      "name": "예시종목",
      "reason": "거래정지 또는 투자경고"
    }
  ]
}
9. 화면별 변경 요청
9.1 좌측 메뉴 변경
현재 메뉴:

Today Control
Trading Monitor
Trade History
AI RulePack
Funnel Monitor
Review & Audit
Data & API
API Logs
KIS System Test
Settings
변경 요청:

API Logs 화면은 제거한다.
변경 후 메뉴:

Today Control
Trading Monitor
Trade History
Daily Plan & RulePack
Funnel Monitor
Review & Audit
Data & API
KIS System Test
Settings
기존 AI RulePack 메뉴명은 Daily Plan & RulePack으로 변경 권장.

9.2 Today Control 화면 변경
현재 표시:

- 운용 모드
- 당일 손익
- 현재 포지션
- 다음 작업
- Funnel Progress
- 오늘 운영 현황
- 오늘 주문내역
변경 요청:

상단 상태 카드에 아래 항목 추가.

- Active Base RulePack Version
- Active Risk Profile Pack Version
- Active Daily Plan ID
- 오늘 매매 강도
- THEME_SPIKE 허용 개수
Timeline 문구 변경:

기존: 08:45 RulePack 생성
변경: 08:45 Daily Trading Plan 생성
Funnel Progress에는 다음 항목을 추가.

- LOW_VOL 배정 종목 수
- MID_VOL 배정 종목 수
- HIGH_VOL 배정 종목 수
- THEME_SPIKE 배정 종목 수
9.3 Trading Monitor 화면 변경
현재 표시:

- 계좌 정보
- 오늘 매매 조건
- 매수 종목 모니터링
- 매도 종목 모니터링
변경 요청:

오늘 매매 조건 영역을 다음 형태로 변경.

오늘 적용 정책
- Base RulePack: base-v1.0
- Risk Profile Pack: profile-v1.0
- Daily Plan: daily-YYYY-MM-DD
- 고정 익절: OFF
- 청산 방식: Trailing Stop + Daily Force Exit
- 신규매수 컷오프: 15:10
- 강제청산 시작: 15:20
매수 종목 모니터링 테이블에 추가할 컬럼:

- 종목코드
- 종목명
- 배정 프로필
- 진입 신뢰도
- 거래량 배수
- VWAP 상태
- WebSocket 구독 상태
- 진입 가능 여부
매도 종목 모니터링 테이블에 추가할 컬럼:

- 종목코드
- 종목명
- 배정 프로필
- 진입가
- 현재가
- 진입 후 최고가
- 현재 손절선
- 트레일링 활성 여부
- 손절선까지 거리
- 보유 시간
- 청산 예정 사유
기존 표현 중 익절 중심 문구는 제거하고, 트레일링 청산 중심으로 변경한다.

9.4 Trade History 화면 변경
현재 표시:

- 기간별 주문 내역
- 매매일수
- 총 주문수
- 수익일 비율
- 누적 손익
- 일 평균 손익
변경 요청:

주문 내역 테이블에 아래 컬럼 추가.

- Daily Plan ID
- Base RulePack Version
- Risk Profile
- 청산 사유
- 트레일링 청산 여부
- 강제청산 여부
청산 사유 예시:

INITIAL_STOP_LOSS
TRAILING_STOP
TIME_EXIT
DAILY_FORCE_EXIT
EMERGENCY_HALT
MANUAL_EXIT
9.5 Daily Plan & RulePack 화면 변경
기존 AI RulePack 화면은 아래 목적에 맞게 변경한다.

기존 목적:

AI가 생성한 RulePack을 자연어로 보여줌
변경 목적:

오늘 적용되는 Base RulePack, Risk Profile Pack, Daily Trading Plan의 합성 결과를 보여줌
화면 구성 변경 요청:

1. 오늘 시장 톤
2. 오늘 매매 강도
3. 오늘 감시 테마
4. 오늘 신규매수 허용 여부
5. 오늘 적용 Rule Composition
6. Risk Profile 4종 요약
7. 종목별 Profile Assignment
8. 검증 결과
9. 원본 Daily Trading Plan JSON 보기
10. 원본 Rule Composition JSON 보기
기존 문구 중 아래 항목은 변경 필요.

기존: RulePack 생성
변경: Daily Trading Plan 생성
기존 매도 조건 문구:

손절 -1.5%, 익절 +3.0%, 수익 +2.0% 이후 트레일링 스탑 활성화
변경 매도 조건 문구:

고정 익절은 사용하지 않습니다.
각 종목은 배정된 Risk Profile에 따라 초기 손절선을 설정합니다.
수익이 기준 이상 발생하면 트레일링 스탑이 활성화됩니다.
고점 갱신 시 손절선은 상향되며, 손절선은 절대 하향되지 않습니다.
모든 포지션은 장마감 전 강제 청산됩니다.
검증 결과 영역에는 아래 항목 표시.

- Base RulePack Schema 검증
- Risk Profile Pack 검증
- Daily Plan Schema 검증
- Symbol Assignment 검증
- Risk Guard 검증
- Runtime 해석 가능 여부
9.6 Funnel Monitor 화면 변경
현재 표시:

- 전체 종목
- Layer 1 통과
- Layer 2 통과
- 현재 매수대기
- Layer 1 탈락 사유
- 후보 선정 결과
- Funnel Quality
변경 요청:

후보 선정 결과 테이블에 아래 컬럼 추가.

- 종목코드
- 종목명
- 점수
- 배정 Risk Profile
- Profile 배정 사유
- WebSocket 구독 예정 여부
- 제외 여부
상단 카드 추가:

- LOW_VOL 후보 수
- MID_VOL 후보 수
- HIGH_VOL 후보 수
- THEME_SPIKE 후보 수
Funnel Quality 영역에 아래 항목 추가.

- Profile 배정 완료 여부
- THEME_SPIKE 과다 여부
- 고변동 후보 비중
- Daily Plan 생성 가능 여부
9.7 Review & Audit 화면 변경
현재 표시:

- 총 손익
- 승률
- 매매일수
- 총 주문수
- 최근 거래일 요약
- 시장 톤
- RulePack
변경 요청:

복기 기준을 RulePack 단위가 아니라 아래 단위로 확장한다.

- Base RulePack Version
- Risk Profile Pack Version
- Daily Plan ID
- Risk Profile별 성과
- 청산 사유별 성과
- 트레일링 청산 성과
- 강제청산 성과
추가 카드:

- LOW_VOL 손익
- MID_VOL 손익
- HIGH_VOL 손익
- THEME_SPIKE 손익
추가 분석:

- 어떤 프로필이 가장 성과가 좋았는지
- 어떤 프로필이 손실을 키웠는지
- 트레일링 폭이 너무 좁았는지/넓었는지
- 장마감 강제청산이 수익을 줄였는지/손실을 줄였는지
- 다음 프로필 버전에서 조정할 후보
9.8 Data & API 화면 변경
현재 표시:

- KIS REST
- KIS WebSocket
- LLM Router
- SQLite DB
- System Health
- LLM Provider 상태
변경 요청:

RulePack 상태 표시를 아래처럼 변경.

Rule System
- Base RulePack: base-v1.0
- Risk Profile Pack: profile-v1.0
- Daily Plan: daily-YYYY-MM-DD
- Symbol Assignments: N개
- 고정 익절: OFF
- 트레일링 청산: ON
WebSocket 상태에 아래 항목 추가.

- 전체 구독 종목 수
- LOW_VOL 구독 수
- MID_VOL 구독 수
- HIGH_VOL 구독 수
- THEME_SPIKE 구독 수
LLM Provider 상태에는 가능하면 daily usage 또는 quota 표시 추가.

- Gemini daily usage
- Groq daily usage
- OpenAI daily usage
- Anthropic daily usage
9.9 KIS System Test 화면 변경
현재 S5:

S5 - RulePack 자동 생성
08:45 KST - LLM → rulepacks (자동 활성화)
변경 요청:

S5 - Daily Trading Plan 생성
08:45 KST - LLM → daily_trading_plan
S6 설명 변경:

기존:
09:00 KST - WS 연결 + RulePack 조건 감시

변경:
09:00 KST - WS 연결 + Base RulePack + Risk Profile + Daily Plan 조건 감시
S8 설명 변경:

기존:
장중 · WS tick → 손절/익절 감시

변경:
장중 · WS tick → 초기손절/트레일링스탑/강제청산 감시
버튼명 변경:

기존: RulePack 자동 생성 실행
변경: Daily Plan 생성 실행
추가 테스트 버튼:

- Risk Profile Pack 검증
- Daily Plan 검증
- Symbol Assignment 검증
- Rule Composition 미리보기
9.10 Settings 화면 변경
현재 Settings는 아래 구조다.

- 리스크 & 청산 설정
- 포트폴리오 위험 한도
- 포지션별 청산 기준
- 스케줄러 시간 설정
변경 요청:

Settings를 아래 구조로 변경한다.

1. Portfolio Risk Settings
2. Default Exit Policy
3. Risk Profile Pack
4. Symbol Override Settings
5. Scheduler Settings
9.10.1 Portfolio Risk Settings
기존 유지:

- 일일 손실 한도
- 주간 손실 한도
- 월간 손실 한도
- 최대 보유 종목
- 종목당 최대 비중
- 기본 운용 모드
단, 이 값들은 Global Risk Guard 값이므로 종목별 Profile이나 AI가 완화할 수 없어야 한다.

9.10.2 Default Exit Policy
기존 익절률 take_profit 항목은 제거하거나 비활성화한다.

변경 항목:

- 고정 익절 사용 여부: 기본 OFF
- 초기 손절 사용 여부: ON
- 트레일링 스탑 사용 여부: ON
- 손절선 하향 금지: ON
- 장마감 강제청산 사용 여부: ON
- 신규매수 금지 시간
- 강제청산 시작 시간
9.10.3 Risk Profile Pack
Risk Profile 4종을 Settings에서 관리 가능해야 한다.

테이블 컬럼:

- Profile
- 초기 손절률
- 트레일링 활성 수익률
- 트레일링 손절률
- 최대 비중
- 최대 보유 시간
- 재진입 허용 여부
- 저장
프로필:

LOW_VOL
MID_VOL
HIGH_VOL
THEME_SPIKE
9.10.4 Symbol Override Settings
특정 종목에 대해 기본 Profile 값을 override할 수 있는 영역을 추가한다.

테이블 컬럼:

- 종목코드
- 종목명
- 기본 배정 Profile
- Override 손절률
- Override 트레일링 활성 기준
- Override 트레일링 손절률
- Override 최대 비중
- 활성 여부
- 저장
단, override 값도 Global Risk Guard보다 위험하게 설정할 수 없어야 한다.

10. 백엔드 API 변경 요청
기존 RulePack 중심 API를 Daily Plan 및 Profile 중심으로 확장한다.

신규 또는 변경 API 제안:

GET  /api/rule/base
GET  /api/rule/profiles
PUT  /api/rule/profiles
GET  /api/daily-plan/today
POST /api/daily-plan/generate
POST /api/daily-plan/validate
POST /api/daily-plan/activate
GET  /api/rule/composition/today
GET  /api/symbol-assignments/today
PUT  /api/symbol-overrides
GET  /api/trading-monitor/candidates
GET  /api/trading-monitor/positions
POST /api/control/halt
POST /api/control/force-close
기존 API 중 RulePack 자동 생성에 해당하는 API는 Daily Plan 생성 API로 변경한다.

11. 엔진 로직 변경 요청
11.1 Rule Resolve 로직
Python Decision Engine은 종목별 최종 룰을 아래 순서로 계산한다.

def resolve_symbol_rule(symbol_code, base_rulepack, profile_pack, daily_plan, symbol_overrides, global_risk):
    assignment = daily_plan["symbol_assignments"].get(symbol_code)
    profile_name = assignment.get("profile", "MID_VOL")

    base_rule = base_rulepack.copy()
    profile_rule = profile_pack["profiles"][profile_name].copy()
    override_rule = symbol_overrides.get(symbol_code, {})

    final_rule = {}
    final_rule.update(base_rule)
    final_rule.update(profile_rule)
    final_rule.update(override_rule)

    # Global Risk Guard 적용
    final_rule["max_position_rate"] = min(
        final_rule.get("max_position_rate", global_risk["max_position_rate_per_stock"]),
        global_risk["max_position_rate_per_stock"]
    )

    final_rule["force_exit_time"] = global_risk["force_exit_time"]
    final_rule["take_profit_enabled"] = False
    final_rule["stop_price_can_only_increase"] = True

    return final_rule
11.2 Position Manager 변경
Position Manager는 더 이상 고정 익절가를 기본 감시하지 않는다.

감시 대상:

- 초기 손절선
- 진입 후 최고가
- 트레일링 활성 여부
- 현재 트레일링 손절선
- 손절선까지 거리
- 최대 보유 시간
- 장마감 강제청산 시간
11.3 WebSocket 구독 정책
KIS REST를 초당 반복 호출하지 않는다.

장중 실시간 감시는 KIS WebSocket 기반으로 수행한다.

S4 스크리닝 완료
→ S5 Daily Plan 생성
→ 종목별 Profile 배정
→ 감시 종목 WebSocket 구독
→ WS tick 기반 Decision Engine 판단
→ Risk Guard 통과 시 REST 주문
→ WS 체결통보 및 REST 잔고 보정
12. 검증 정책
Daily Plan 및 Rule Composition은 반드시 아래 검증을 통과해야 한다.

1. JSON Schema 검증
2. Risk Profile 존재 여부 검증
3. Symbol Assignment 검증
4. Global Risk Guard 위반 여부 검증
5. 고정 익절 OFF 여부 검증
6. 손절선 하향 금지 여부 검증
7. 장마감 강제청산 ON 여부 검증
8. Runtime 해석 가능 여부 검증
AI 또는 Daily Plan이 아래를 시도하면 차단한다.

- 일일 손실 한도 완화
- 주간 손실 한도 완화
- 월간 손실 한도 완화
- 최대 보유 종목 증가
- 종목당 최대 비중 증가
- 장마감 강제청산 해제
- 손절선 하향 허용
- 고정 익절 강제 활성화
13. DB 변경 제안
최소한 아래 테이블 또는 유사 구조가 필요하다.

base_rulepacks
risk_profile_packs
risk_profiles
daily_trading_plans
symbol_assignments
symbol_overrides
rule_compositions
positions
position_stop_states
trade_orders
trade_fills
daily_trade_summary
position_stop_states에는 아래 필드가 필요하다.

- position_id
- symbol_code
- entry_price
- highest_price_since_entry
- initial_stop_price
- trailing_stop_price
- active_stop_price
- trailing_active
- last_updated_at
14. 용어 변경 정리
아래 용어를 전체 UI와 코드에서 정리한다.

기존: RulePack 자동 생성
변경: Daily Trading Plan 생성

기존: AI RulePack
변경: Daily Plan & RulePack

기존: 익절률 take_profit
변경: 고정 익절 사용 여부, 기본 OFF

기존: 매도 조건
변경: 청산 조건

기존: 손절/익절 감시
변경: 초기손절/트레일링/강제청산 감시
15. 작업 우선순위
1단계
- API Logs 메뉴 제거
- AI RulePack 메뉴명을 Daily Plan & RulePack으로 변경
- KIS System Test의 S5 명칭 변경
- Settings에서 take_profit 기본 제거 또는 OFF 처리
2단계
- Risk Profile 4종 데이터 구조 추가
- Settings에 Risk Profile Pack 관리 UI 추가
- Daily Plan JSON 구조 추가
- Daily Plan 생성 API 추가
3단계
- Funnel Monitor에 종목별 Profile 배정 표시
- Trading Monitor에 종목별 Profile 및 트레일링 상태 표시
- Position Manager에 트레일링 스탑 로직 반영
4단계
- Review & Audit에서 Profile별 성과 분석 추가
- Rule Composition 미리보기 추가
- Daily Plan 검증 및 활성화 플로우 추가
16. 완료 기준
아래 조건을 만족하면 설계변경 1차 완료로 본다.

- 매일 RulePack 전체를 새로 생성하지 않는다.
- S5는 Daily Trading Plan 생성으로 변경된다.
- Risk Profile 4종이 존재한다.
- 각 후보 종목에 Risk Profile이 배정된다.
- 고정 익절은 기본 OFF다.
- 청산은 초기손절 + 트레일링스탑 + 장마감 강제청산으로 동작한다.
- 손절선은 절대 하향되지 않는다.
- Global Risk Guard는 모든 설정보다 우선한다.
- API Logs 화면은 제거된다.
- Trading Monitor에서 종목별 프로필과 트레일링 상태를 확인할 수 있다.
- Review & Audit에서 프로필별 성과를 복기할 수 있다.
17. 최종 요약
이번 변경의 핵심은 다음과 같다.

RulePack을 매일 새로 만드는 구조를 폐지한다.
고정된 Risk Profile 4종을 유지한다.
매일 생성하는 것은 Daily Trading Plan이다.
Daily Trading Plan은 오늘 어떤 종목에 어떤 Risk Profile을 적용할지 결정한다.
모든 포지션은 고정 익절 없이 트레일링 스탑으로 관리한다.
단타 전략이므로 모든 포지션은 장마감 전 청산한다.
AI는 추천과 계획 생성만 담당하며, 실제 주문은 Python Decision Engine과 Risk Guard가 검증 후 실행한다.