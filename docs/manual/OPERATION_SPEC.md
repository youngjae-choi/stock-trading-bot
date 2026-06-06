# 정상 동작 기획서 (Operation Spec)

> **목적**: 시스템의 기대 동작을 명문화해서 실제 동작과 대조할 수 있게 한다.
> 학습 루프가 자율 동작하기 전까지는 PM과 Sisyphus가 매일 EOD에 이 문서를 기준으로 리뷰한다.
>
> **변경 원칙**: 기획서는 살아있는 문서다. 기능 추가/수정 시 이 문서부터 갱신하고 코드를 맞춘다. 코드가 먼저 가면 기획서가 부정확해진다.

---

## 1. 일일 거래 사이클 (정상 흐름)

### 시간표 (KST)

```
00:01  S2  아침 시장 톤 분석 (LLM, 야간 해외 데이터)
       → market_tone_results / morning_context INSERT

09:01  S1~S5-A  거래준비 프로세스 (job_trade_preparation_pipeline)
       ※ DB schedule_trade_prep_time=08:25 → 개장 가드로 09:01 하한 보정
       S1  시장 개장 점검 (휴장일 가드, 토큰 발급)
       S3  Universe Filter — KIS 거래량+등락률 순위 상위 60종목
           → 0거래/상한가/하한가/ETP/우선주/스팩 제외
           → 단타 모멘텀 점수(상승폭 0.5 + 거래량급증 0.5) top_n 30
       S4  Hybrid Screening (LLM) — 후보 30 → 정성 점수 6~10개
           → entry_rules 산출 (min_ai_confidence, price 범위 등)
       S5  Daily Plan (LLM) — Risk Profile 배정 + trading_intensity 결정
       S5-A 플랜 정합성 검증 + 활성화
08:00  배당락일 D-2 알림 (오전)
08:30  S2-프리마켓  장 개시 전 시장 톤 독립 재확보 (당일 이미 산출 시 재사용)

09:10  S6  Decision Engine 활성화 — 실시간 tick 수신 시작 (장중 워치독 자동복구)
       ※ DB schedule_s6_time=08:59 → 가드로 09:10 하한 보정 (max 09:10, trade_prep+5)

09:30  슬롯1  스냅샷 + S2 장중 재실행 + (trigger 시) S3→S4→S5→S6 재선별
10:30  슬롯2  동일
11:30  슬롯3  동일
13:00  슬롯4  동일 (점심 슬롯, kill switch로 제어 가능)
13:00  배당락일 알림 (오후)
14:00  슬롯5  동일

15:20  S9   EOD 청산 + Decision Engine 비활성화
15:30  KIS 장 마감
15:35  job_missed_returns_update — 당일 미진입 종목 수익률 backfill
16:00  S10 Review & Audit
       → false_positive_cases 생성 (손실 거래 자동 분석)
       → daily_review_reports INSERT
       → S11 learning_memory_builder (다음날 자동 적용용 메모리 생성)
       → loss_streak_guard (3회+ 손실 종목 자동 차단)

18:00  S10 Daily Summary + DB 백업
```

### 단계별 기대 동작 & 헬스 지표

| 단계 | 기대 동작 | 헬스 지표 (정상) | 이상 신호 |
|---|---|---|---|
| S2 아침 | LLM 호출 1회, market_tone_results 1건 INSERT | tone ∈ {positive,neutral,negative,mixed}, confidence ≥ 0.3 | confidence=0.0 또는 tone=neutral confidence<0.3 (LLM 실패) |
| S2 장중 | 슬롯마다 LLM 호출 1회, morning_context 새 행 | 5회/거래일 | 0~3회면 슬롯 trigger 미발동 또는 LLM 실패 |
| S3 | 60→30 단타 모멘텀(상승폭+거래량급증), filtered>0 | top_n_count ≥ 20 | 0건 = KIS 호출 실패 |
| S4 | 30→6~10, overall_confidence ≥ 0.4 | output_count ≥ 5 | output_count=0 또는 confidence<0.3 |
| S5 | trading_intensity ∈ {aggressive,normal,defensive} | symbol_assignments ≥ 5 | assignments=0 = LLM 실패 |
| S6 매수 신호 | (기본) AND 게이트 통과 / (탐색 ON·모의) OR 조건 그룹 발화 | 일 평균 5~15건, 탐색 ON 시 폭증 | <2건이면 보수성 과다 |
| 슬롯 trigger | avg_change ≥ threshold(2~3%) | triggered=True 1~2회/일 | 강세장에서 0회면 retrigger delta 또는 sector_rotation 문제 |
| S9 청산 | 모든 보유 포지션 매도 | liquidated 보유수와 일치 | 잔여 포지션 있으면 KIS 동기화 문제 |
| missed_returns | EOD 가격으로 tracked 갱신 | tracked = total | tracked=0이면 cron 미실행 또는 KIS rate limit |
| S10 Review | false_positive_count + memory_count | 매일 created_at 기록 | created_at 빠진 날이 있으면 POSTPROCESS 실패 |
| S11 learning_memory | 다음날 S3/S4에서 활용할 메모리 생성 | total ≥ 10 | 0건이면 review_audit 미실행 |

---

## 2. 학습 루프 (정상 흐름)

```
[당일 장중]
  매수 신호 → 체결 → 보유 → 청산 → trading_orders
  S6 게이트 통과 못한 종목 → missed_opportunities (S3/S4 단계별 사유 기록)

[당일 EOD 15:35]
  missed_opportunities → max_return_until_eod 갱신
  EOD 가격이 진입가 대비 +2% 이상이면 improvement_candidate=1

[당일 EOD 16:00]
  손실 거래 → false_positive_cases (자동 분석)
  daily_review_reports 생성 (total_trades, win/loss, pnl)
  learning_memory_builder:
    - improvement_candidate → "이런 패턴은 다음에 진입 고려" 메모리
    - false_positive → "이런 패턴은 다음에 회피" 메모리
    - auto_apply_allowed=1이면 즉시 다음날 적용
    - requires_approval=1이면 콘솔에서 PM 승인 대기
  loss_streak_guard: 같은 종목 3회+ 손실 → expert_knowledge에 자동 차단 등록

[다음날 S3/S4]
  hybrid_screening: 활성 learning_memories를 프롬프트에 주입
  universe_filter: memory 기반 가중치 조정
  expert_knowledge: 차단 목록 적용
```

### 학습 루프 헬스 메트릭

| 지표 | 정상 | 비고 |
|---|---|---|
| missed_opportunities.tracked / total | ≥ 0.9 | 15:35 backfill cron 정상 동작 |
| missed_opportunities.improvement_candidate | total 대비 5~20% | 너무 낮으면 시스템이 다 잡고 있다는 뜻, 너무 높으면 보수성 과다 |
| false_positive_cases | 손실 거래 수 ≥ false_positive 수 (≤ 100%) | 손실인데 fp 분석 안 되면 review_audit Step 0 실패 |
| learning_memories.created (daily) | ≥ 10건 | 0건이면 review_audit 또는 builder 실패 |
| learning_memories.status='active' | 점진 증가 | 만료 처리되면서도 누적되어야 함 |
| daily_review_reports.created_at | 매 거래일 1건 | 빠진 날 = POSTPROCESS 실패 |

---

## 3. 거래 보수성 메트릭 (Exploration vs Strict)

현재 시스템은 **과도하게 보수적**이다 (놓친 기회가 매수의 18배).
헐렁한 거래로 데이터 축적 단계 → 점진 strict 전환.

### 기준선 (현재 strict)
- `min_ai_confidence`: 0.65 (시장톤별 0.45~0.72)
- `min_confidence_floor`: 0.40
- `max_price_change_pct`: 5.0 (S4 LLM이 설정)
- `top_n`: 시장톤별 20~35
- `max_positions`: 30
- `position_size`: 5% (1억 시드 → 종목당 333만원)

### 탐색 엔진 (Exploration Mode — 구현됨, 모의계좌 전용)
탐색모드가 켜지면 매수 = **OR 조건 그룹**(돌파/눌림/모멘텀/베이스라인)으로 바뀌고, S3 선정은 단타 모멘텀(상승폭+거래량급증)이다.
- 켜기/끄기: Settings 탐색모드 카드 → `engine.exploration_mode` (기본 OFF)
- 풀예수금 사이징: `exploration.budget_rate`=0.95, `exploration.max_positions`=40
- 🔒 KIS 모의계좌일 때만 활성, 실계좌면 하드 차단
- EOD EV(승률×손익비) 가지치기로 음수 그룹 weight 자동 하향(floor 0.1)
- 유지: stop_loss -5%, daily_loss -10%, max_position_size 30% (안전 가드)
- 상세: [`EXPLORATION_ENGINE.md`](EXPLORATION_ENGINE.md)

### Exploration 종료 조건
- 100거래 이상 누적
- 학습 루프 안정 동작 2주 이상
- false_positive 표본 ≥ 30건 누적

---

## 4. 진단 체크리스트 (Deviation 발생 시)

### 시스템이 보수적으로 보일 때
1. `min_ai_confidence` 현재 설정값 확인 (`system_settings.engine.min_ai_confidence`)
2. S4 `overall_confidence` 최근 5일 추이 확인 → 0.5 미만 지속이면 LLM이 잘못된 시장 맥락으로 판단 중
3. `morning_context.regime` 확인 → 야간 데이터 stale인지 장중 업데이트되는지
4. `daily_trading_plans.trading_intensity` → defensive 고착이면 S5 프롬프트 점검

### 학습 루프 안 도는 것 같을 때
1. `daily_review_reports.created_at` 최근 7일 — 빠진 날 있는지
2. `pipeline_run_audit` 최근 POSTPROCESS/S10/S11 status
3. `missed_opportunities.tracked` 비율
4. `false_positive_cases` 최근 7일 vs 손실 거래 수
5. uvicorn 프로세스 시작 시간 vs 마지막 커밋 시간 (서버 미반영 의심)

### 매수 신호 0건
1. S6 게이트 조건별 통과율 (`shadow_trades` rule_matched JSON 분석)
2. `daily_trading_plans.new_entry_allowed` = true 인지
3. KIS 잔고 동기화 정상 인지
4. S4 후보 종목이 보유 종목과 겹치는지 (보유는 신규 평가 제외)

### 슬롯 trigger 안 발동
1. `_RETRIGGER_DELTA` (현재 1.0) — 같은 방향 추가 변동 필요
2. `_REFRESH_THRESHOLD` (defensive=2.0, normal=3.0)
3. `intraday_refresh.master_enabled`, `lunch_slots_enabled` kill switch
4. snapshot avg_change가 실제 시장과 일치하는지

---

## 5. 운영 원칙

### 백엔드 코드 수정 → 서버 재시작 필수
- APScheduler는 모듈 로드 시점의 코드를 캐시
- silent failure 사례: `import asyncio` 누락 (2026-05-21~26 4일간 EOD 학습 루프 차단)
- 매일 첫 작업: `daily_review_reports.created_at` 최근 1~2일 확인

### Codex 디스패치 전 백엔드 서버 중지
- DB 마이그레이션 동시 쓰기로 SQLite corrupt 사례 (2026-05-25)

### 새 기능 기획 시 이 문서 먼저 갱신
- 단계 변경 → 시간표 수정
- 새 메트릭 → 헬스 지표 추가
- 새 진단 케이스 → 체크리스트 추가
