Dantabot 설계변경 요청서 2차
1. 문서 목적
본 문서는 현재 Dantabot Control Console 화면 구현 결과를 스크린샷 기준으로 검수한 뒤, 1차 설계변경 요청서의 미반영/오반영 항목을 수정하고, 아래 3개 후속 변경요청서의 내용을 통합 반영하기 위한 2차 개발변경 요청서이다.

1. Review & Audit 변경요청서
2. S3~S5 동작프로세스 변경요청서
3. AI 단타봇 운영안정화 및 판단검증 추가기능 요청서
본 문서는 단순 UI 문구 수정이 아니라, 실제 자동매매 운영 프로세스를 아래 구조로 전환하는 것을 목표로 한다.

Base RulePack 고정
+ Risk Profile Pack 고정
+ S5 Daily Trading Plan 자동 생성
+ Daily Trading Plan 검증/활성화
+ Review & Audit 기반 Learning Memory
+ Expert Knowledge Base
+ S3~S5 컨텍스트 주입
+ Risk Guard 우선
+ Order Pre-Flight Check
+ 판단검증/운영안정화 기능
가장 중요한 변경점은 다음과 같다.

Daily Plan은 사용자가 직접 생성하는 것이 아니라,
S5 단계에서 Scheduler 또는 Pipeline에 의해 자동 생성되는 운영 산출물이다.

사용자는 Daily Plan을 생성하는 사람이 아니라,
자동 생성된 Daily Plan의 상태와 검증 결과를 확인하고,
예외 상황에서만 수동 재생성, Dry Run, 재검증, 비활성화, 롤백에 개입한다.
2. 현재 화면 기준 검수 결과
검수 대상 화면:

- Today Control
- Trading Monitor
- Trade History
- Daily Plan & RulePack
- Funnel Monitor
- Review & Audit
- Data & API
- KIS System Test
- Settings
전체 평가:

현재 구현은 1차 설계변경의 일부 UI 문구와 Risk Profile 개념만 반영된 상태로 보인다.
그러나 S5가 RulePack 생성에서 Daily Trading Plan 자동 생성으로 완전히 전환되지 않았고,
Review & Audit → Learning Memory → 다음날 S3~S5 반영 구조도 화면과 테스트 플로우에서 확인되지 않는다.
주요 미반영/오반영:

1. S5가 여전히 RulePack 자동 생성으로 표시됨
2. Today Control의 운영 일정에 RulePack 생성이 남아 있음
3. KIS System Test에 S5 - RulePack 자동 생성이 남아 있음
4. Settings 스케줄러에 S5 RulePack이 남아 있음
5. Review & Audit 설명에 다음 RulePack에 반영이라는 문구가 남아 있음
6. Daily Plan이 S5 자동 생성 산출물이라는 점이 화면에 명확히 드러나지 않음
7. Daily Plan 생성 버튼이 메인 액션으로 노출되어 사용자가 직접 생성해야 하는 것처럼 보임
8. Daily Plan 검증/활성화/비활성화/롤백 흐름이 없음
9. Learning Memory 영역이 없음
10. Expert Knowledge Base 또는 Knowledge refs 확인 영역이 없음
11. 운영안정화/판단검증 기능이 화면에 없음
3. 절대 유지해야 할 설계 원칙
2차 개발에서 반드시 유지해야 할 원칙은 다음과 같다.

1. S5는 RulePack 전체를 매일 새로 생성하지 않는다.
2. S5는 Daily Trading Plan을 자동 생성한다.
3. Daily Plan은 정상 운영에서 사용자가 직접 생성하지 않는다.
4. 사용자는 자동 생성된 Daily Plan을 확인하고, 예외 상황에서만 수동 개입한다.
5. Base RulePack은 고정 버전으로 관리한다.
6. Risk Profile Pack은 고정 버전으로 관리한다.
7. Risk Profile 원본 값 변경은 사용자 승인 없이는 불가능하다.
8. Global Risk Guard는 AI 판단보다 항상 우선한다.
9. LLM은 기억 주체가 아니다.
10. 기억은 DB와 Backend가 관리한다.
11. Review & Audit 결과는 Learning Memory로 저장된다.
12. Learning Memory는 다음날 S3~S5의 입력 컨텍스트로 사용된다.
13. 외부자료는 Expert Knowledge Base로 구조화한다.
14. 승인된 Expert Knowledge만 S3~S5에 주입한다.
15. Daily Plan 생성은 실전 적용을 의미하지 않는다.
16. Daily Plan은 검증 후 활성화되어야만 S6 Decision Engine에서 사용된다.
17. 모든 주문은 Risk Guard와 Order Pre-Flight Check를 통과해야 한다.
4. 화면별 검수 및 수정 요청
4.1 Today Control 화면
현재 확인된 상태
Today Control 화면에는 아래 항목이 보인다.

- 운용 모드 AUTO
- 당일 손익
- 현재 포지션
- 다음 작업
- Base RulePack
- Risk Profile Pack
- Daily Plan
- 매매 강도
- Funnel Progress
- 오늘 운영 현황
- 오늘 주문내역
현재 문제:

1. 오늘 운영 현황에 "08:45 RulePack 생성"이 남아 있음
2. S5 Daily Plan 자동 생성 상태가 명확히 표시되지 않음
3. Base RulePack / Risk Profile Pack / Daily Plan 값이 비어 있거나 충분히 표시되지 않음
4. Daily Plan 상태가 active/validated/generated 등으로 표시되지 않음
5. Daily Plan이 자동 생성된 것인지 수동 생성된 것인지 표시되지 않음
6. Data Quality 상태가 없음
7. Risk Guard 상태는 일부 있으나 상세 차단 사유 확인 불가
8. Pre-Flight 차단 수가 없음
9. Shadow Mode 상태가 없음
10. 승인 대기 항목 수가 없음
11. Alert 상태가 없음
수정 요청
오늘 운영 현황을 아래처럼 변경한다.

기존:

08:45 RulePack 생성
변경:

08:45 S5 Daily Trading Plan 자동 생성
08:50 Daily Plan Validation 자동 실행
08:55 Daily Plan 활성화 확인
Today Control 상단 카드에 아래 항목을 표시한다.

- Active Daily Plan ID
- Daily Plan 상태
- Daily Plan 생성 방식: auto/manual/dry_run
- Daily Plan 생성자: scheduler/user/system
- Base RulePack Version
- Risk Profile Pack Version
- Market Tone
- Trading Intensity
- 신규매수 허용 여부
- Data Quality 상태
- Risk Guard 상태
- Pre-Flight 차단 수
- Shadow Mode 상태
- Approval Queue 대기 수
- Critical Alert 수
Daily Plan 상태값:

none
draft
generated
validation_failed
validated
active
inactive
expired
superseded
rollbacked
dry_run
4.2 Trading Monitor 화면
현재 확인된 상태
Trading Monitor 화면에는 아래 항목이 보인다.

- 계좌 정보
- 오늘 적용 정책
- 매수 대기 종목 모니터링
- 보유 포지션 모니터링
- DE 활성 버튼
현재 문제:

1. 오늘 적용 정책의 Base RulePack, Risk Profile Pack, Daily Plan 값이 비어 있음
2. Active Daily Plan ID가 표시되지 않음
3. Daily Plan Validation 상태가 표시되지 않음
4. 매수 대기 종목에 S4 결과가 없을 때 No Trade/No Candidate 사유가 부족함
5. Pre-Flight 상태가 없음
6. Data Quality 상태가 없음
7. signal_proximity 표시가 없음
8. no_entry_reason 표시가 없음
9. Shadow tracking 여부가 없음
10. 각 후보의 assigned_profile, confidence, entry_policy가 없음
수정 요청
매수 대기 종목 테이블에 아래 컬럼을 추가한다.

- 종목코드
- 종목명
- S4 점수
- AI confidence
- assigned_profile
- entry_policy
- signal_proximity
- allowed
- no_entry_reason
- preflight_status
- data_quality_status
- shadow_tracking
- knowledge_refs
- memory_refs
보유 포지션 테이블에 아래 컬럼을 추가한다.

- 진입가
- 현재가
- 수익률
- 최고수익률
- 현재 손절선
- 트레일링 활성 여부
- 손절선까지 거리
- 마지막 tick age
- Data Quality 상태
- 청산 예상 사유
DE 활성 버튼은 아래 조건에서만 활성화한다.

- Active Daily Plan 존재
- Daily Plan Validation 통과
- Risk Guard 정상
- Data Quality NORMAL 또는 WARNING
- KIS WebSocket 정상
4.3 Trade History 화면
현재 확인된 상태
Trade History에는 아래 항목이 보인다.

- 기간 필터
- 매매일수
- 총 주문수
- 수익일 비율
- 누적 손익
- 일 평균 손익
- 주문내역 테이블
현재 문제:

1. Daily Plan ID가 없음
2. Base RulePack Version이 없음
3. Risk Profile Pack Version이 없음
4. 주문별 Risk Profile은 있으나 Daily Plan과 연결이 불명확함
5. 청산 사유는 있으나 Exit Reason 표준값이 불명확함
6. Shadow Trade / Missed Opportunity / False Positive와 연결이 없음
수정 요청
주문내역 테이블에 아래 컬럼을 추가한다.

- Daily Plan ID
- Base RulePack Version
- Risk Profile Pack Version
- Risk Profile
- entry_policy
- entry_reason
- exit_reason
- knowledge_refs
- memory_refs
- preflight_check_id
- data_quality_status_at_order
표준 exit_reason:

INITIAL_STOP
TRAILING_STOP
TIME_EXIT
DAILY_FORCE_EXIT
MANUAL_EXIT
RISK_GUARD_EXIT
DATA_QUALITY_EXIT
4.4 Daily Plan & RulePack 화면
현재 확인된 상태
화면에는 아래 항목이 보인다.

- 시장 톤
- 신규매수
- 종목 배정
- LLM Provider
- 청산 조건
- Risk Profile Pack
- 종목별 Profile 배정
- 검증 결과
- 제외 종목
- LLM 분석 요약
- 원본 Daily Trading Plan JSON
- Daily Plan 생성 버튼
현재 문제:

1. Daily Plan 생성 버튼이 메인 액션으로 노출되어 있음
2. 사용자가 Daily Plan을 직접 생성해야 하는 것처럼 보임
3. Daily Plan이 S5 단계에서 자동 생성되는 산출물이라는 점이 드러나지 않음
4. 생성이 곧 적용인지 여부가 불명확함
5. Daily Plan 상태가 명확하지 않음
6. Active Plan 여부가 보이지 않음
7. Validation 결과가 비어 있음
8. Daily Overrides가 표시되지 않음
9. S3 Result ID, S4 Result ID가 없음
10. used_learning_memory_ids가 없음
11. used_knowledge_ids가 없음
12. symbol_assignments 상세가 부족함
13. Risk Profile Pack이 로딩중으로 보이며 실제 version/value 확인이 어려움
14. 수동 재생성/검증/활성화/비활성화/롤백의 권한과 조건이 정의되어 있지 않음
핵심 수정 원칙
Daily Plan은 정상 운영에서 사용자가 직접 생성하지 않는다.

Daily Plan은 아래 자동 파이프라인에 의해 생성되어야 한다.

S2 시장 톤 분석
→ S3 유니버스 필터
→ S4 하이브리드 스크리닝
→ S5 Daily Trading Plan 자동 생성
→ Daily Plan Validation 자동 실행
→ 검증 통과 시 운영 모드에 따라 자동 활성화 또는 승인 대기
→ S6 Decision Engine은 active Daily Plan만 사용
따라서 Daily Plan 생성 버튼은 메인 액션 버튼으로 두면 안 된다.

이 화면의 기본 목적은 다음과 같다.

- 오늘 S5에서 자동 생성된 Daily Plan 확인
- Daily Plan 상태 확인
- Validation 결과 확인
- Active 여부 확인
- Daily Overrides 확인
- 종목별 Risk Profile 배정 확인
- S3/S4 Result ID 확인
- used_learning_memory_ids 확인
- used_knowledge_ids 확인
- 원본 JSON 확인
Daily Plan 생성 주체
Daily Plan 생성 주체는 기본적으로 시스템이다.

생성 주체: Scheduler 또는 Backend Pipeline
생성 단계: S5
생성 시각: Settings의 Scheduler Settings에서 설정
생성 결과 저장 위치: daily_trading_plans
기본 생성 방식: auto
사용자는 Daily Plan 생성자가 아니다.

사용자는 아래 예외 상황에서만 개입할 수 있다.

- S5 자동 생성 실패
- S4 결과를 재생성한 뒤 S5만 다시 실행해야 하는 경우
- 장 시작 전 Review Memory 또는 Expert Knowledge 승인 후 재생성이 필요한 경우
- 개발/테스트 환경에서 Dry Run을 수행하는 경우
- Paper Trading 또는 Simulation용 Plan을 생성하는 경우
화면 버튼 정책
기존:

[Daily Plan 생성] [새로고침]
변경:

[새로고침]
[Context 보기]
[검증 결과 보기]

고급 작업 ▼
  - Daily Plan Dry Run
  - S5 수동 재실행
  - Daily Plan 재검증
  - Daily Plan 비활성화
  - 이전 Plan으로 롤백
Daily Plan 생성이라는 단일 메인 버튼명은 사용하지 않는다.

수동 기능은 고급 작업 또는 관리자 작업 영역으로 이동한다.

버튼별 동작 정의
Context 보기
S5에 주입된 또는 주입될 컨텍스트를 보여준다.

표시 항목:

- Market Context
- S4 candidates
- Learning Memory
- Expert Knowledge
- Risk Guard 상태
- Base RulePack Version
- Risk Profile Pack Version
- S3 Result ID
- S4 Result ID
- Prompt Context Snapshot ID
Daily Plan Dry Run
실전 DB의 active plan에 영향을 주지 않고 임시 Plan을 생성한다.

용도:

- 개발 테스트
- Paper Trading
- Simulation
- S5 프롬프트 검증
- Daily Plan Schema 검증
저장 정책:

- active plan으로 승격하지 않음
- 실주문에 사용하지 않음
- dry_run 결과로 별도 저장
- Audit Log 저장
S5 수동 재실행
자동 생성 실패 또는 장전 재생성 필요 시에만 S5를 수동 실행한다.

동작:

- S4 결과를 입력으로 사용
- Market Context 사용
- Learning Memory 사용
- Expert Knowledge 사용
- Base RulePack Version 사용
- Risk Profile Pack Version 사용
- Daily Plan을 generated 상태로 저장
- 실전 적용은 하지 않음
수동 재실행 조건:

- 관리자 권한 필요
- 재실행 사유 입력 필수
- S3 Result ID 존재
- S4 Result ID 존재
- S4 후보 데이터 존재
- Base RulePack Version 존재
- Risk Profile Pack Version 존재
- Risk Guard 상태 확인
- Audit Log 저장
장중 수동 재실행은 기본적으로 금지한다.

장중 수동 재실행을 허용할 경우 아래 조건을 추가로 요구한다.

- 신규매수 일시 중지
- 사용자 확인 2회
- 기존 Active Plan superseded 처리
- 변경 전/후 Plan Snapshot 저장
- 모든 변경 이력 Audit Log 저장
Daily Plan 재검증
generated 상태 또는 validation_failed 상태의 Plan을 다시 검증한다.

검증 항목:

- JSON Schema Validation
- 필수 필드 검증
- symbol_assignments 검증
- Risk Profile 값 검증
- Daily Overrides 검증
- Global Risk Guard 위반 여부 검증
- allowed=false 종목 제외 여부 검증
- Risk Profile 원본 값 변경 시도 여부 검증
결과:

통과 → validated
실패 → validation_failed
Daily Plan 활성화
완전 자동 모드에서는 Scheduler가 검증 통과 후 자동 active 처리할 수 있다.

반자동 모드 또는 수동 승인 모드에서는 사용자가 validated Plan을 활성화할 수 있다.

활성화 조건:

- Plan 상태가 validated
- Risk Guard 검증 통과
- Data Quality 상태가 NORMAL 또는 WARNING
- Base RulePack Version 존재
- Risk Profile Pack Version 존재
- S3/S4 Result ID 존재
동작:

- validated Plan을 active로 변경
- 기존 active Plan은 superseded 처리
- S6 Decision Engine은 active Plan만 사용
- 활성화 이력 저장
금지:

- validation_failed Plan 활성화 금지
- generated 상태에서 바로 active 전환 금지
- Risk Guard 위반 Plan 활성화 금지
- Risk Profile 원본 변경이 포함된 Plan 활성화 금지
Daily Plan 비활성화
active 상태의 Plan을 inactive 처리한다.

동작:

- active Plan을 inactive로 변경
- 신규매수 중단
- 기존 보유 포지션 관리는 계속 수행
- 비활성화 사유 입력
- Audit Log 저장
이전 Plan으로 롤백
직전 validated 또는 active Plan으로 복구한다.

조건:

- 롤백 대상 Plan이 validation 통과 상태여야 함
- 롤백 사유 입력 필수
- 관리자 권한 필요
- 장중 롤백 시 신규매수 일시 중지
동작:

- 현재 active Plan은 superseded 또는 rollbacked 처리
- 선택한 이전 Plan을 active로 변경
- 롤백 이력 저장
- 변경 전/후 Snapshot 저장
Daily Plan 상태값
Daily Plan은 아래 상태값을 가져야 한다.

none
draft
generated
validation_failed
validated
active
inactive
expired
superseded
rollbacked
dry_run
상태 전이:

S5 자동 생성
→ generated
→ validation_failed 또는 validated
→ active
→ expired 또는 superseded
Dry Run 상태 전이:

Dry Run 실행
→ dry_run
→ active 승격 불가
수동 재실행 상태 전이:

S5 수동 재실행
→ generated
→ 재검증
→ validated
→ 수동 또는 자동 active
화면 필수 표시 항목
Daily Plan & RulePack 화면은 아래 항목을 반드시 표시해야 한다.

Daily Plan 기본 정보
- Daily Plan ID
- Plan 상태
- Active 여부
- 생성 시각
- 생성 방식: auto/manual/dry_run
- 생성자: scheduler/user/system
- 마지막 검증 시각
- 마지막 활성화 시각
Rule Composition 정보
- Base RulePack Version
- Risk Profile Pack Version
- Active Daily Plan ID
- Daily Overrides 적용 여부
Market & Strategy 정보
- Market Tone
- Trading Intensity
- 신규매수 허용 여부
- THEME_SPIKE 허용 수
- min_ai_confidence
- volume_filter_multiplier
Daily Overrides
- override field
- override value
- 적용 사유
- 출처: Learning Memory / Expert Knowledge / Market Context
- auto_apply 여부
- Risk Guard 위반 여부
Pipeline 참조 정보
- S3 Result ID
- S4 Result ID
- used_learning_memory_ids
- used_knowledge_ids
- prompt_context_snapshot_id
Validation 결과
- Schema Validation 결과
- Risk Guard Validation 결과
- Daily Override Validation 결과
- symbol_assignments Validation 결과
- 실패 사유
- 경고 메시지
Risk Profile Pack
Risk Profile Pack이 로딩중으로만 표시되면 안 된다.

표시 항목:

- Profile 이름
- 초기 손절
- 트레일링 활성 기준
- 트레일링 손절폭
- 최대 비중
- 최대 보유 수
- 재진입 허용 여부
- Profile Pack Version
종목별 Profile 배정
symbol_assignments 테이블에 아래 컬럼을 표시한다.

- 종목코드
- 종목명
- assigned_profile
- allowed
- entry_policy
- confidence
- 배정 사유
- memory_refs
- knowledge_refs
제외 종목
excluded_symbols에 아래 컬럼을 표시한다.

- 종목코드
- 종목명
- 제외 단계
- 제외 사유
- 관련 memory_refs
- 관련 knowledge_refs
원본 JSON
원본 Daily Trading Plan JSON에는 아래 필드가 포함되어야 한다.

{
  "daily_plan_id": "daily-2026-05-04",
  "status": "active",
  "created_by": "scheduler",
  "creation_mode": "auto",
  "market_tone": "positive",
  "trading_intensity": "normal",
  "base_rulepack_version": "base-v1.0",
  "risk_profile_pack_version": "profile-v1.0",
  "s3_result_id": "s3-20260504-001",
  "s4_result_id": "s4-20260504-001",
  "used_learning_memory_ids": [
    "mem-20260503-001"
  ],
  "used_knowledge_ids": [
    "knw-20260503-001"
  ],
  "daily_overrides": {
    "max_theme_spike_positions": 1,
    "min_ai_confidence": 0.65,
    "volume_filter_multiplier": 2.0
  },
  "symbol_assignments": [
    {
      "symbol_code": "123456",
      "symbol_name": "예시종목",
      "assigned_profile": "HIGH_VOL",
      "allowed": true,
      "entry_policy": "wait_for_pullback",
      "confidence": 0.73,
      "reason": "VWAP 위 눌림 후 재상승 가능성이 있으나 변동성이 커 HIGH_VOL로 배정",
      "memory_refs": [
        "mem-20260503-001"
      ],
      "knowledge_refs": [
        "knw-20260503-001"
      ]
    }
  ],
  "excluded_symbols": [
    {
      "symbol_code": "654321",
      "symbol_name": "제외예시종목",
      "excluded_stage": "S5",
      "reason": "첫 급등 장대양봉 이후 과열 구간으로 판단",
      "memory_refs": [],
      "knowledge_refs": [
        "knw-20260503-002"
      ]
    }
  ],
  "validation": {
    "schema_valid": true,
    "risk_guard_valid": true,
    "override_valid": true,
    "errors": [],
    "warnings": []
  }
}
4.5 Funnel Monitor 화면
현재 확인된 상태
Funnel Monitor에는 아래 항목이 보인다.

- 전체 종목
- Layer 1 통과
- Layer 2 통과
- 현재 매수대기
- Profile 배정 현황
- Layer 1 탈락 사유
- Funnel Quality
- 후보 선정 결과
현재 장점:

S3/S4의 결과를 확인하는 기본 틀은 존재한다.
후보 선정 사유도 일부 표시된다.
현재 문제:

1. Profile 배정 현황이 LOW_VOL/MID_VOL/HIGH_VOL/THEME_SPIKE 모두 "-"로 표시됨
2. S4 후보에 assigned_profile이 없음
3. memory_refs가 없음
4. knowledge_refs가 없음
5. Memory 영향 점수가 없음
6. Knowledge 영향 점수가 없음
7. S3 탈락 사유가 기본 필터 중심이며 Review Memory/Expert Knowledge 반영 여부 확인 불가
8. Shadow tracking 여부가 없음
9. Missed Opportunity 후보 표시가 없음
수정 요청
상단 카드 추가:

- S3 Result ID
- S4 Result ID
- used_learning_memory_count
- used_knowledge_count
- Shadow tracking 후보 수
후보 선정 결과 컬럼 추가:

- 종목코드
- 종목명
- 기술 점수
- 거래량 점수
- 테마 점수
- AI confidence
- Memory 영향
- Knowledge 영향
- 최종 점수
- assigned_profile
- allowed
- entry_policy
- 후보 선정 사유
- risk_notes
- knowledge_refs
- memory_refs
- shadow_tracking
Layer 1 탈락 사유에 아래 구분을 추가한다.

- 기본 필터 제외
- Risk Guard성 제외
- Review Memory 기반 제외
- Expert Knowledge 기반 제외
- Data Quality 기반 제외
4.6 Review & Audit 화면
현재 확인된 상태
Review & Audit 화면에는 아래 항목이 보인다.

- 총 손익
- 승률
- 매매일수
- 총 주문수
- 가장 최근 거래일 요약
- 시장 톤
- RulePack
- 일별 거래 이력
- 일일 요약 생성 버튼
현재 문제:

1. 설명에 "다음 RulePack에 반영"이라고 되어 있음
2. 이제는 "다음 Daily Plan/S3~S5에 반영"으로 바뀌어야 함
3. Learning Memory 생성 결과가 없음
4. 내일 S3/S4/S5 반영 예정 항목이 없음
5. Risk Profile별 성과 분석이 없음
6. Exit Reason 분석이 없음
7. Trailing Stop Quality가 없음
8. No Trade Reason이 없음
9. Missed Opportunity Summary가 없음
10. False Positive Summary가 없음
11. Shadow Trading 결과가 없음
12. 승인 필요 변경 후보가 없음
문구 수정
기존:

복기의 목적은 리포트가 아니라 학습입니다. 좋은 전략, 나쁜 전략, 좋은 타이밍을 구조화해서 다음 RulePack에 반영합니다.
변경:

복기의 목적은 리포트가 아니라 학습입니다. 당일 매매 결과와 미진입 사유를 구조화하여 Learning Memory로 저장하고, 다음 거래일 S3~S5와 Daily Trading Plan 생성에 반영합니다.
화면 추가 영역
1. Rule Context
2. Risk Profile Performance
3. Exit Reason Analysis
4. Trailing Stop Quality
5. No Trade Reason
6. Missed Opportunity Summary
7. False Positive Summary
8. Shadow Trading Summary
9. Learning Memory
10. Approval Required Changes
Rule Context 표시
- Base RulePack Version
- Risk Profile Pack Version
- Daily Plan ID
- S3 Result ID
- S4 Result ID
- used_learning_memory_ids
- used_knowledge_ids
Learning Memory 영역
표시 항목:

- 오늘 생성된 Learning Memory 수
- S3 반영 예정
- S4 반영 예정
- S5 반영 예정
- 자동 반영 가능
- 승인 필요
- 만료 예정
4.7 Data & API 화면
현재 확인된 상태
Data & API 화면에는 아래 항목이 보인다.

- KIS REST
- KIS WebSocket
- LLM Router
- SQLite DB
- Auto Engine
- RulePack
- WebSocket
- Risk Guard
- LLM Provider 상태
현재 문제:

1. RulePack만 표시되고 Daily Plan 상태가 없음
2. Data Quality Guard 상태가 없음
3. REST/WS 가격 괴리 상태가 없음
4. Tick 지연 상태가 없음
5. DB write latency가 없음
6. LLM JSON Schema 오류 상태가 없음
7. S3/S4/S5 마지막 실행 상태가 없음
8. Pre-Flight Check 상태가 없음
수정 요청
System Health에 아래 항목을 추가한다.

- Active Daily Plan
- Daily Plan Validation 상태
- Data Quality Guard 상태
- REST/WS 가격 괴리 상태
- WebSocket tick delay
- DB write 상태
- Pre-Flight Check 상태
- S3 마지막 실행
- S4 마지막 실행
- S5 마지막 실행
- Learning Memory Builder 상태
RulePack 카드 변경:

기존: RulePack
변경: Rule Composition
Rule Composition에는 아래를 표시한다.

- Base RulePack Version
- Risk Profile Pack Version
- Active Daily Plan ID
- Daily Overrides 적용 여부
4.8 KIS System Test 화면
현재 확인된 상태
KIS System Test에는 아래 단계가 보인다.

S1 - KIS 토큰 갱신
S2 - 시장 톤 분석
S3 - 유니버스 필터
S4 - 하이브리드 스크리닝
S5 - RulePack 자동 생성
S6 - Decision Engine 활성화
S7 - 주문 실행
S8 - Position Manager 상태
S9 - 당일 청산
S10 - 일일 요약 + DB 백업
현재 문제:

1. S5가 여전히 RulePack 자동 생성으로 되어 있음
2. S5 설명에 LLM → rulepacks 자동 활성화가 남아 있음
3. Daily Plan Validation 테스트가 없음
4. Learning Memory Builder 테스트가 없음
5. Expert Knowledge Context 테스트가 없음
6. Risk Guard 테스트가 S6와 분리되어 있지 않음
7. Order Pre-Flight Check 테스트가 없음
8. Data Quality Guard 테스트가 없음
9. Shadow Trading 테스트가 없음
10. Missed Opportunity / False Positive 탐지 테스트가 없음
수정 요청
KIS System Test 단계를 아래로 변경한다.

S1 - KIS 토큰/계좌 연결 테스트
S2 - 시장 톤 분석 테스트
S3 - 유니버스 필터 테스트
S4 - 하이브리드 스크리닝 테스트
S5 - Daily Trading Plan 생성 테스트
S5-V - Daily Plan Validation 테스트
S6 - Decision Engine 테스트
S6-R - Risk Guard 테스트
S6-P - Order Pre-Flight Check 테스트
S7 - 주문 실행 Dry Run 테스트
S8 - Position Manager 테스트
S9 - 장마감 청산 테스트
S10 - Review & Audit 테스트
S11 - Learning Memory Builder 테스트
DQ - Data Quality Guard 테스트
SH - Shadow Trading 테스트
MO - Missed Opportunity 탐지 테스트
FP - False Positive 탐지 테스트
S5 카드 문구 변경:

기존:

S5 - RulePack 자동 생성
08:45 KST - LLM → rulepacks (자동 활성화)
변경:

S5 - Daily Trading Plan 자동 생성
08:45 KST - LLM → daily_trading_plans (generated 상태 저장)
S5-V 추가:

S5-V - Daily Plan Validation
08:50 KST - Schema/Risk Guard/Daily Override 검증 → validated 또는 validation_failed
S6 설명 변경:

기존:

WS 연결 + RulePack 조건 감시
변경:

WS 연결 + Active Daily Plan + Base RulePack + Risk Profile 조건 감시
S10 설명 변경:

기존:

일일 요약 + DB 백업
변경:

Review & Audit 생성
S11 추가:

S11 - Learning Memory Builder
Review & Audit 결과를 Learning Memory로 구조화하여 다음 거래일 S3~S5에 반영
4.9 Settings 화면
현재 확인된 상태
Settings 화면에는 아래 항목이 보인다.

- 리스크 & 청산 설정
- 일일 손실 한도
- 주간 손실 한도
- 월간 손실 한도
- 최대 보유 종목
- 종목당 최대 비중
- 기본 운용 모드
- 포지션별 청산 기준
- 스케줄러 시간 설정
현재 문제:

1. 스케줄러에 S5 RulePack이 남아 있음
2. S5 Daily Plan 생성/검증/활성화 시간이 없음
3. Review & Audit 실행 시간이 없음
4. Learning Memory Builder 실행 시간이 없음
5. LLM Provider 역할별 설정이 없음
6. Learning Memory 사용 설정이 없음
7. Expert Knowledge 사용 설정이 없음
8. Risk Profile Pack Version 관리가 없음
9. Order Pre-Flight 설정이 없음
10. Data Quality Guard 설정이 없음
11. Shadow Trading 설정이 없음
12. Approval Policy 설정이 없음
수정 요청
Settings 화면 섹션을 아래처럼 확장한다.

1. Trading Operation Settings
2. Rule Composition Settings
3. Scheduler Settings
4. LLM Provider Settings
5. Learning Memory Settings
6. Expert Knowledge Settings
7. Risk Guard Settings
8. Order Pre-Flight Settings
9. Data Quality Guard Settings
10. Shadow Trading Settings
11. Approval Policy Settings
12. Emergency Control Settings
Scheduler Settings 수정
기존:

S5 RulePack
변경:

S5 Daily Plan 자동 생성
S5-V Daily Plan 자동 검증
S5-A Daily Plan 활성화 확인
S10 Review & Audit
S11 Learning Memory Builder
예시 스케줄:

07:45 S1 KIS 토큰 갱신
08:00 S2 시장 톤 분석
08:15 S3 유니버스 필터
08:30 S4 하이브리드 스크리닝
08:45 S5 Daily Plan 자동 생성
08:50 S5-V Daily Plan 자동 검증
08:55 S5-A Daily Plan 활성화 확인
15:10 신규매수 금지
15:20 장마감 강제청산
16:00 S10 Review & Audit
16:30 S11 Learning Memory Builder
18:00 데이터 백업
Rule Composition Settings 추가
- Base RulePack Version
- Risk Profile Pack Version
- Active Daily Plan ID
- Daily Overrides 허용 범위
- Risk Profile 원본 수정 잠금
- Profile 변경은 Approval Queue를 통해서만 적용
Learning Memory Settings 추가
- Learning Memory 사용 여부
- S3 반영 여부
- S4 반영 여부
- S5 반영 여부
- 최근 N일 메모리 사용
- 자동 반영 허용 범위
- 승인 필요 변경 분리 여부
Expert Knowledge Settings 추가
- Expert Knowledge Base 사용 여부
- 승인된 지식만 사용
- context_only 기본값
- scoring_hint 허용 여부
- approved_strategy_rule 허용 여부
- 원문 저장 허용 여부
- 요약 저장 허용 여부
- 저작권/출처 기록 필수 여부
Order Pre-Flight Settings 추가
- 최대 허용 tick age
- REST/WS 가격 괴리 허용치
- 최대 허용 호가 스프레드
- 중복 주문 차단 여부
- 미체결 주문 존재 시 신규 주문 차단 여부
- 급등락 직후 주문 차단 기준
- 신규매수 금지 시간
Data Quality Guard Settings 추가
- WebSocket 지연 허용 시간
- REST 오류 허용 횟수
- DB 저장 실패 허용 횟수
- 체결통보 누락 감지 사용 여부
- DEGRADED 시 신규매수 차단 여부
- EMERGENCY 상태 진입 기준
Shadow Trading Settings 추가
- Shadow Mode 사용 여부
- S4 제외 후보 추적 여부
- S5 allowed=false 후보 추적 여부
- Risk Guard 차단 후보 추적 여부
- Pre-Flight 차단 후보 추적 여부
- 가상 진입/청산 방식
Approval Policy Settings 추가
- Profile 원본 변경 승인 필요
- Base RulePack 변경 승인 필요
- Knowledge apply_level 상향 승인 필요
- Risk Guard 변경 승인 필요
- Daily Override 자동 허용 범위
5. Review & Audit → Learning Memory 변경 요청
Review & Audit은 단순 리포트가 아니라 다음날 전략 입력 데이터를 생성해야 한다.

처리 흐름:

장 종료
→ 주문/체결/포지션 데이터 수집
→ Daily Plan 대비 실제 결과 비교
→ Risk Profile별 성과 분석
→ Exit Reason 분석
→ Trailing Stop Quality 분석
→ No Trade Reason 분석
→ Missed Opportunity 분석
→ False Positive 분석
→ Shadow Trading 결과 분석
→ Learning Memory 생성
→ DB 저장
→ 다음날 S3~S5 컨텍스트로 사용
Learning Memory scope:

S3_UNIVERSE_FILTER
S4_HYBRID_SCREENING
S5_DAILY_PLAN
Learning Memory 예시:

{
  "memory_id": "mem-20260504-001",
  "date": "2026-05-04",
  "scope": "S5_DAILY_PLAN",
  "category": "profile_allocation",
  "summary": "THEME_SPIKE 손실 변동성이 높아 다음 거래일 허용 개수를 제한하는 것이 좋음",
  "evidence": {
    "profile": "THEME_SPIKE",
    "trade_count": 3,
    "win_rate": 0.33,
    "avg_pnl": -0.009
  },
  "recommendation": {
    "type": "daily_override",
    "field": "max_theme_spike_positions",
    "value": 1
  },
  "auto_apply_allowed": true,
  "requires_approval": false,
  "status": "active"
}
6. S3~S5 동작프로세스 변경 요청
6.1 S3 유니버스 필터
S3 입력:

- 전체 종목 데이터
- 시장 톤
- 테마/섹터 흐름
- S3용 Learning Memory
- S3용 Expert Knowledge
- 기본 제외 규칙
S3 출력:

- S3 Result ID
- 포함 종목 목록
- 제외 종목 목록
- 제외 사유
- memory_refs
- knowledge_refs
6.2 S4 하이브리드 스크리닝
S4 입력:

- S3 결과
- 기술적 지표
- 거래량/거래대금
- 뉴스/테마
- S4용 Learning Memory
- S4용 Expert Knowledge
- Market Context
S4 출력:

- S4 Result ID
- 후보 종목
- S4 점수
- 기술 점수
- 테마 점수
- Memory 영향
- Knowledge 영향
- 후보 선정 사유
- risk_notes
- memory_refs
- knowledge_refs
6.3 S5 Daily Trading Plan
S5는 Daily Trading Plan을 자동 생성한다.

사용자가 정상 운영에서 Daily Plan을 직접 생성하지 않는다.

S5 입력:

- S4 후보
- 시장 톤
- Base RulePack Version
- Risk Profile Pack Version
- S5용 Learning Memory
- S5용 Expert Knowledge
- Risk Guard 설정
S5 출력:

- Daily Plan ID
- Plan status
- creation_mode: auto/manual/dry_run
- created_by: scheduler/user/system
- Market Tone
- Trading Intensity
- Daily Overrides
- symbol_assignments
- excluded_symbols
- used_learning_memory_ids
- used_knowledge_ids
- LLM analysis summary
symbol_assignments 필수 필드:

- symbol_code
- symbol_name
- assigned_profile
- allowed
- entry_policy
- confidence
- reason
- memory_refs
- knowledge_refs
6.4 Daily Plan Validation
Daily Plan Validation은 S5 자동 생성 후 자동 실행되어야 한다.

검증 항목:

- JSON Schema 검증
- 필수 필드 존재 여부
- profile 값 검증
- allowed=false 종목 매수 대상 제외 여부
- Daily Overrides가 Risk Guard를 완화하지 않는지 검증
- Risk Profile 원본 값 변경 시도 여부 검증
- THEME_SPIKE 허용 개수 초과 여부 검증
- 신규매수 금지 정책 위반 여부 검증
검증 결과:

통과 → validated
실패 → validation_failed
완전 자동 모드에서는 검증 통과 후 자동으로 active 처리할 수 있다.

반자동 모드에서는 검증 통과 후 사용자 승인 대기 상태로 둔다.

7. Expert Knowledge Base 추가 요청
외부자료는 직접 룰로 적용하지 않고, 승인된 지식만 S3~S5에 주입한다.

처리 흐름:

외부자료 업로드
→ 텍스트 추출
→ AI 요약
→ 핵심 전략 원칙 추출
→ S3/S4/S5 적용 위치 태깅
→ 위험도 및 신뢰도 평가
→ 사용자 승인
→ Expert Knowledge Base 저장
→ S3/S4/S5 프롬프트에 주입
→ Review & Audit에서 성과 추적
Knowledge 상태:

draft
review_required
approved
active
watch
deprecated
rejected
메뉴 추가:

Knowledge Base
표시 항목:

- 자료 업로드
- 추출된 전략 지식
- 적용 단계 S3/S4/S5
- 승인 상태
- 적용 횟수
- 성과
- active/watch/deprecated 상태
8. 운영안정화 기능 추가 요청
8.1 Order Pre-Flight Check
주문 흐름:

Decision Engine
→ Risk Guard
→ Order Pre-Flight Check
→ KIS 주문 실행
검증 항목:

- 장 운영 시간
- 신규매수 금지 시간
- 현재가 급변
- 호가 스프레드 과다
- 종목당 최대 비중 초과
- 동일 종목 중복 주문
- 미체결 주문 존재
- REST/WS 가격 괴리
- 마지막 tick age
- 거래정지/투자경고
- 긴급정지 상태
8.2 Data Quality Guard
감시 항목:

- WebSocket tick 지연
- REST 현재가와 WS 현재가 괴리
- 거래량 데이터 누락
- 호가 데이터 누락
- 체결통보 누락
- DB 저장 실패
- 동일 tick 중복 처리
- 종목코드 매핑 오류
- LLM JSON 파싱 오류
- S3/S4/S5 Schema 오류
상태값:

NORMAL
WARNING
DEGRADED
BLOCK_NEW_ENTRY
EMERGENCY
8.3 Alert Center
알림 유형:

- Risk Guard 발동
- 일일 손실 한도 접근
- WebSocket 지연
- REST 오류
- DB 저장 실패
- 체결통보 누락
- Daily Plan 검증 실패
- Pre-Flight 차단
- Data Quality DEGRADED
- 긴급정지 실행
9. 판단검증 기능 추가 요청
9.1 Paper Trading Shadow Mode
대상:

- S4 후보였으나 S5에서 제외된 종목
- S5 allowed=false 종목
- confidence 미달 종목
- Risk Guard 차단 종목
- Pre-Flight 차단 종목
9.2 Missed Opportunity Tracker
기록 항목:

- missed_stage
- missed_reason
- price_at_missed
- max_return_after_10m
- max_return_after_30m
- max_return_until_eod
- improvement_candidate
9.3 False Positive Tracker
기록 항목:

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
9.4 Confidence Calibration
confidence 구간별 성과 분석:

- 0.90 이상
- 0.80 ~ 0.90
- 0.70 ~ 0.80
- 0.60 ~ 0.70
- 0.60 미만
9.5 Knowledge Impact Scoring
Knowledge별 지표:

- 적용 횟수
- 실제 거래 수
- Shadow 거래 수
- 승률
- 평균손익
- 최대손실
- 잘 맞는 시장 톤
- 안 맞는 시장 톤
- 상태 변경 제안
9.6 Human Approval Queue
승인 필요 항목:

- Risk Profile 원본 값 변경
- Base RulePack 변경
- Global Risk Guard 변경
- Expert Knowledge 상태 변경
- Knowledge apply_level 상향
- S4 scoring weight 고정 변경
- 기본 min_ai_confidence 변경
상태값:

pending
approved
rejected
deferred
simulation_only
9.7 No Trade Reason
무매매 또는 미진입 사유를 기록한다.

후보별 미진입 사유:

- confidence 미달
- VWAP 조건 미충족
- 거래량 재증가 미확인
- Risk Guard 차단
- Pre-Flight Check 차단
- Data Quality 문제
- 신규매수 시간 초과
- 과열 추격 위험
- Expert Knowledge 기준 제외
10. DB 테이블 추가/변경 제안
10.1 Review & Learning Memory
daily_review_reports
learning_memories
profile_performance_daily
exit_reason_performance_daily
trailing_quality_daily
no_trade_daily_reasons
candidate_no_entry_reasons
10.2 S3~S5
universe_filter_results
hybrid_screening_results
daily_trading_plans
daily_plan_versions
symbol_assignments
prompt_context_snapshots
daily_plan_validation_results
10.3 Expert Knowledge
external_knowledge_sources
strategy_knowledge_items
knowledge_prompt_contexts
knowledge_impact_stats
knowledge_approval_logs
10.4 운영 안정화
order_preflight_checks
data_quality_events
data_quality_snapshots
system_alerts
10.5 판단 검증
shadow_trades
shadow_trade_events
missed_opportunities
false_positive_cases
confidence_calibration_daily
confidence_calibration_bins
human_approval_queue
approval_decision_logs
10.6 Replay / Simulation
trading_event_log
replay_sessions
simulation_results
11. API 변경 제안
11.1 Daily Plan API
Daily Plan은 기본적으로 S5 Scheduler/Pipeline이 자동 생성한다.

사용자가 직접 호출하는 생성 API는 일반 운영 버튼이 아니라 관리자/테스트/복구 용도로만 사용한다.

GET  /api/daily-plan/today
GET  /api/daily-plan/{daily_plan_id}
GET  /api/daily-plan/context-preview
POST /api/daily-plan/dry-run
POST /api/daily-plan/manual-regenerate
POST /api/daily-plan/{daily_plan_id}/validate
POST /api/daily-plan/{daily_plan_id}/activate
POST /api/daily-plan/{daily_plan_id}/deactivate
POST /api/daily-plan/{daily_plan_id}/rollback
주의:

POST /api/daily-plan/manual-regenerate 는 일반 운영자가 매일 누르는 API가 아니다.
S5 자동 생성 실패, 장전 재생성, 테스트, 복구 상황에서만 사용한다.
11.2 S3~S5 API
POST /api/pipeline/S3/universe-filter/run
POST /api/pipeline/S4/hybrid-screening/run
POST /api/pipeline/S5/daily-plan/run
GET  /api/pipeline/S3/context-preview
GET  /api/pipeline/S4/context-preview
GET  /api/pipeline/S5/context-preview
POST /api/pipeline/S5/daily-plan/run은 Scheduler가 호출하는 S5 자동 생성용 API이다.

11.3 Learning Memory API
GET  /api/learning-memories
POST /api/learning-memories/build-from-review
GET  /api/learning-memories/context/S3
GET  /api/learning-memories/context/S4
GET  /api/learning-memories/context/S5
11.4 Knowledge API
POST /api/knowledge/sources/upload
POST /api/knowledge/sources/{source_id}/process
GET  /api/knowledge/items
PUT  /api/knowledge/items/{knowledge_id}/approve
PUT  /api/knowledge/items/{knowledge_id}/deprecate
GET  /api/knowledge/context/S3
GET  /api/knowledge/context/S4
GET  /api/knowledge/context/S5
11.5 운영 안정화 API
POST /api/orders/preflight-check
GET  /api/orders/preflight-checks
GET  /api/data-quality/status
GET  /api/data-quality/events
POST /api/data-quality/check
GET  /api/alerts
PUT  /api/alerts/{alert_id}/resolve
11.6 판단 검증 API
GET  /api/shadow-trades
POST /api/shadow-trades/evaluate
GET  /api/missed-opportunities
POST /api/missed-opportunities/detect
GET  /api/false-positives
POST /api/false-positives/detect
GET  /api/confidence-calibration
GET  /api/knowledge-impact
11.7 Approval API
GET  /api/approval-queue
POST /api/approval-queue
PUT  /api/approval-queue/{id}/approve
PUT  /api/approval-queue/{id}/reject
PUT  /api/approval-queue/{id}/defer
PUT  /api/approval-queue/{id}/simulation-only
12. 개발 우선순위
Phase 1: 1차 오반영 수정 및 용어 정리
- S5 RulePack 자동 생성 문구 제거
- S5 Daily Trading Plan 자동 생성으로 전환
- Today Control 운영 일정 수정
- KIS System Test 단계 수정
- Settings 스케줄러 수정
- Review & Audit 문구 수정
- Daily Plan 상태값 추가
- Daily Plan 생성 버튼을 메인 액션에서 제거
- 수동 재생성/Dry Run/재검증/비활성화/롤백을 고급 작업으로 이동
Phase 2: Daily Plan 실제 운영 흐름 구현
- S5 Scheduler/Pipeline 기반 Daily Plan 자동 생성 구현
- Daily Plan generated/validated/active 상태 관리
- Daily Plan Validation 자동 실행 구현
- 완전 자동/반자동/테스트 모드별 활성화 정책 구현
- Active Plan만 S6 Decision Engine에서 사용
- Base RulePack + Risk Profile Pack + Daily Plan 합성 구조 표시
- symbol_assignments 저장/표시
- Daily Plan 수동 재실행 시 사유 입력 및 Audit Log 저장
Phase 3: Review & Audit 및 Learning Memory 구현
- Risk Profile별 성과 분석
- Exit Reason 분석
- Trailing Stop Quality 분석
- No Trade Reason 기록
- Learning Memory Builder 구현
- S3/S4/S5 컨텍스트 조회 API 구현
Phase 4: S3~S5 컨텍스트 고도화
- S3/S4/S5에서 Learning Memory 주입
- Expert Knowledge Base 추가
- memory_refs / knowledge_refs 저장
- Funnel Monitor에 Memory/Knowledge 영향 표시
Phase 5: 운영안정화 및 판단검증
- Order Pre-Flight Check
- Data Quality Guard
- Alert Center
- Shadow Trading
- Missed Opportunity
- False Positive
- Confidence Calibration
- Knowledge Impact Scoring
- Human Approval Queue
13. 완료 기준
2차 개발 완료 기준은 다음과 같다.

1. 모든 화면에서 S5 RulePack 자동 생성 문구가 제거됨
2. S5는 Daily Trading Plan 자동 생성으로 표시됨
3. Daily Plan은 S5 Scheduler/Pipeline이 자동 생성함
4. 사용자가 매일 Daily Plan을 직접 생성해야 하는 UI가 제거됨
5. Daily Plan 생성 버튼은 메인 액션에서 제거되거나 고급 작업으로 이동됨
6. 수동 재생성은 S5 자동 생성 실패/장전 재생성/테스트/복구 상황에서만 가능함
7. 수동 재생성 시 사유 입력과 Audit Log 저장이 필수임
8. Daily Plan은 generated/validated/active 상태를 가짐
9. Daily Plan Validation은 S5 생성 후 자동 실행됨
10. Daily Plan은 Validation 통과 후에만 active가 될 수 있음
11. Active Daily Plan만 S6 Decision Engine에서 사용됨
12. Today Control에서 Active Daily Plan 상태를 확인할 수 있음
13. KIS System Test에서 S5-V Validation, S11 Learning Memory Builder 테스트가 가능함
14. Settings에서 S5 Daily Plan 자동 생성/자동 검증/활성화 확인 시간이 설정 가능함
15. Review & Audit에서 Learning Memory 생성 결과를 확인할 수 있음
16. S3/S4/S5 결과에 memory_refs와 knowledge_refs가 저장됨
17. Funnel Monitor에서 Memory/Knowledge 영향이 보임
18. Data & API에서 Data Quality Guard 상태가 보임
19. 주문 전 Pre-Flight Check 결과가 저장됨
20. No Trade Reason이 기록됨
21. Shadow Trading, Missed Opportunity, False Positive 결과가 Review & Audit에 표시됨
22. 승인 필요 변경사항이 Human Approval Queue에 등록됨
14. 개발 AI에게 전달할 핵심 지시
현재 구현은 RulePack 중심 구조가 화면과 테스트 플로우에 여전히 남아 있다.
2차 개발의 최우선 목표는 S5를 RulePack 생성이 아니라 Daily Trading Plan 자동 생성/검증/활성화 구조로 완전히 전환하는 것이다.

Daily Plan은 사용자가 직접 생성하는 것이 아니다.
Daily Plan은 S5 Scheduler 또는 Backend Pipeline이 자동 생성하는 운영 산출물이다.

사용자는 Daily Plan 생성자가 아니라 운영 검수자이다.
사용자는 자동 생성된 Daily Plan의 상태, 검증 결과, Active 여부, 종목별 배정, Daily Overrides, used_learning_memory_ids, used_knowledge_ids를 확인한다.

수동 재생성, Dry Run, 재검증, 비활성화, 롤백은 예외 상황을 위한 관리자/고급 작업으로 분리한다.

Daily Plan 생성은 실전 적용이 아니다.
Daily Plan은 반드시 Validation을 통과한 뒤 active 상태가 되어야 S6 Decision Engine에서 사용할 수 있다.

Review & Audit은 리포트 화면이 아니라 Learning Memory 생성 화면이어야 하며,
생성된 Learning Memory는 다음 거래일 S3~S5 컨텍스트로 주입되어야 한다.

화면 문구 변경만 하지 말고 DB, API, Backend Service, Scheduler, Test 화면, UI 상태값까지 일관되게 수정해야 한다.