# Kairos 시스템 가이드 — 철학·알고리즘·프로세스

> 최종 수정: 2026-05-26
> 대상: 운영자(PM) + Sisyphus(Orchestrator)
> 본 문서는 **시스템이 왜 이렇게 만들어졌는가**를 정의한다.
> 일일 운영 시간표·헬스 지표는 [`OPERATION_SPEC.md`](OPERATION_SPEC.md)에, EOD 체크리스트는 [`EOD_CHECKLIST.md`](EOD_CHECKLIST.md)에 분리.

---

## 목차

1. [핵심 철학](#1-핵심-철학)
2. [시스템 아키텍처](#2-시스템-아키텍처)
3. [파이프라인 단계 (S1~S11)](#3-파이프라인-단계-s1s11)
4. [의사결정 알고리즘](#4-의사결정-알고리즘)
5. [학습 루프 알고리즘](#5-학습-루프-알고리즘)
6. [장중 재선별 알고리즘](#6-장중-재선별-알고리즘)
7. [LLM과 Rule Engine의 분담](#7-llm과-rule-engine의-분담)
8. [데이터 흐름과 SSOT](#8-데이터-흐름과-ssot)
9. [알려진 취약점](#9-알려진-취약점)
10. [운영 명령어](#10-운영-명령어)
11. [API 인덱스](#11-api-인덱스)

---

## 1. 핵심 철학

### 1.1 단타·매수 only·모의계좌 단계

- **시간 단위**: 분~시간. 일봉/주봉 모멘텀 불필요.
- **포지션**: 매수만. 공매도·인버스 진입 금지 (인버스 ETF/ETN은 long으로 잡지 않는다).
- **현재 단계**: KIS **모의계좌**. 실수 비용 = 0, 학습 가치 = 무한. 망설일 이유 없다.

### 1.2 데이터 축적 우선 (Exploration > Exploitation)

> "More data is better than better data" — Renaissance Technologies

거래봇 초기에는 **다양한 거래 데이터가 자산**이다. 보수적 필터로 거래량을 0에 가깝게 만들면 시스템은 검증된 좁은 패턴만 반복하고 실패 사례 없이 늙어간다.

- 실패 사례(`false_positive_cases`)는 LLM에 "회피 패턴" 컨텍스트로 주입된다.
- 놓친 기회(`missed_opportunities` + `improvement_candidate=1`)는 LLM에 "고려 패턴" 컨텍스트로 주입된다.
- **이 두 데이터셋이 학습 루프의 연료**다. 거래가 적으면 연료가 마른다.

### 1.3 시스템 가설은 검증돼야 한다

다음은 *가설*이다. 데이터로 검증 전까지는 "절대 규칙"이 아니다.

| 가설 | 현재 구현 | 검증 방법 |
|---|---|---|
| 이미 +5% 이상 오른 종목 추격은 위험 | `max_price_change_pct = 5.0` | improvement_candidate 중 change_rate > 5% 비율 |
| risk_on 장에서는 인버스 진입 부적합 | S4 LLM이 자동 회피 | 인버스 종목 max_return_until_eod 추적 |
| 거래대금 상위 = 단타 좋은 종목 | S3 거래대금 가중치 0.50 | 상위 종목과 미진입 상승 종목 분포 비교 |

→ **데이터가 가설을 부정하면 가설을 바꾼다**. 가설을 지키려고 데이터를 무시하지 않는다.

### 1.4 정상 동작은 코드보다 먼저 문서로 정의된다

PM이 매번 "이거 왜 안 돼?"라고 묻기 전에, **기대 동작이 문서에 명시**되어 있어야 한다. 그래야 deviation을 자동 진단할 수 있다.

- 기능 추가 시 `OPERATION_SPEC.md`부터 갱신 → 코드를 맞춤
- 매 EOD `EOD_CHECKLIST.md`로 자동 검증 → 미통과 항목만 PM에 보고

### 1.5 Silent Failure는 시스템 신뢰의 적

조용히 실패하는 코드는 매일 손실을 누적시킨다. 2026-05-21~26 4일간 `import asyncio` 누락으로 EOD 학습 루프가 전체 차단됐던 사례가 있다.

- `try: ... except: pass` 패턴 금지. 실패도 로그로 외친다.
- APScheduler "executed successfully" ≠ "함수 정상 종료". `pipeline_run_audit`에서 status 확인.
- 코드 수정 후 **서버 재시작 확인 필수** (모듈 캐시 문제).

---

## 2. 시스템 아키텍처

```
KIS API (한국투자증권)
  ↕ REST: 시세·주문·잔고·지수·업종
  ↕ WebSocket: 실시간 틱 (H0STCNT0)
      │
Backend (FastAPI · Port 8000)
  ├── scheduler.py            ← APScheduler S1~S11 자동 실행
  ├── services/
  │   ├── kis/                ← KIS API 래퍼
  │   │   ├── common/client   ← 토큰·rate limit·retry
  │   │   ├── domestic/       ← 국내 시세·주문
  │   │   │   ├── universe_service  ← volume-rank, price-rank, index, sector
  │   │   │   └── service           ← 매수/매도, 잔고
  │   │   └── realtime_ws     ← 실시간 틱 구독
  │   └── engine/             ← 매매 로직
  │       ├── decision_engine      ← S6 진입 판단 (틱 기반)
  │       ├── order_executor       ← KIS 주문 제출
  │       ├── fill_poller          ← 체결 확인 + 텔레그램
  │       ├── position_manager     ← 포지션 추적 (KIS 잔고 SSOT)
  │       ├── eod_liquidation      ← S9 장마감 청산
  │       ├── review_audit         ← S10 LLM 복기
  │       ├── learning_memory      ← S11 학습 메모리 빌더
  │       ├── intraday_refresh     ← 슬롯 단위 재선별
  │       ├── intraday_regime_monitor ← 레짐 SET 모니터링
  │       ├── sector_rotation      ← 섹터 회전 감지
  │       ├── market_tone          ← S2 시장 톤 분석
  │       ├── universe_filter      ← S3 정량 필터
  │       ├── hybrid_screening     ← S4 LLM 정성 점수
  │       ├── daily_plan           ← S5 Risk Profile 배정
  │       ├── missed_opportunity   ← 미진입 추적
  │       ├── false_positive       ← 손실 거래 자동 분석
  │       ├── loss_streak_guard    ← 연속 손실 자동 차단
  │       ├── llm_router           ← Opus 4.7 / 4.6 라우팅
  │       └── prompt_loader        ← 프롬프트 렌더링
  └── static/console.html    ← 운영 콘솔 (SPA)

Data:
  SQLite        data/stock_trading_bot.sqlite3 (SSOT for system state)
  KIS 실계좌    잔고·체결 (SSOT for position truth)

Notifications:
  Telegram Bot   수신 전용 (자동 처리, 승인 버튼 없음)
```

### 2.1 SSOT (Single Source of Truth)

| 데이터 | SSOT | 사유 |
|---|---|---|
| 보유 포지션 수량 | **KIS 실계좌 잔고** | 시스템 재시작/장애와 무관. position_manager가 60초 주기 동기화 |
| 매수 신호 발행 | `trading_signals` 테이블 | S6 게이트 통과 시점의 사실 |
| 일일 손익 | `daily_trade_summary` | S10 daily_summary가 fills 집계 |
| 시장 톤 | `market_tone_results` (최신) | S2 + 장중 S2 모두 같은 테이블 |
| 시장 컨텍스트 | `morning_context` (`ORDER BY created_at DESC LIMIT 1`) | 장중 업데이트되는 regime/risk_level |
| Daily Plan | `daily_trading_plans` (trade_date PK) | S5 결과, 장중 trigger 시 REPLACE |
| 거래일 여부 | `system_settings.schedule_skip_today` | S1 결과, 휴장일 false 고정 |

---

## 3. 파이프라인 단계 (S1~S11)

> **모든 시간 KST.** 자세한 헬스 지표는 [`OPERATION_SPEC.md`](OPERATION_SPEC.md) 참조.

| 단계 | 시간 | 함수 | 핵심 동작 | 출력 SSOT |
|:---:|:---:|---|---|---|
| **S2** | 00:01 | `run_market_tone_analysis(trigger_source="auto_scheduler")` | 야간 해외 데이터 → LLM tone 분석 | `market_tone_results`, `morning_context` |
| **S1** | 08:00 | `job_trade_preparation_pipeline` 1단계 | KIS 토큰, 거래일 확인 | `schedule_skip_today` |
| **S3** | 08:00 | `run_universe_filter` | KIS volume/trade rank 60 → top_n 30 (시장톤별), ETF 제외 | `universe_results` |
| **S4** | 08:30 | `run_hybrid_screening` | 30 → 6~10 + LLM 점수 + entry_rules | `screening_results` |
| **S5** | 08:45 | `run_daily_plan_generation` | Risk Profile 배정 + trading_intensity | `daily_trading_plans` |
| **S5-A** | 08:50 | `activate_daily_plan` | 플랜 정합성 검증 + 활성화 | (in-memory + DB flag) |
| **S6** | 09:00 | `decision_engine.activate()` | 실시간 틱 구독 시작 | `trading_signals`, `shadow_trades` |
| **S7** | 장중 | `order_executor.execute_buy()` | S6 신호 → KIS 시장가 주문 | `trading_orders` |
| **S8** | 장중 | `position_manager.evaluate_exit()` | 트레일링·손절·시간 청산 | `trading_orders (sell)` |
| **슬롯** | 09:30/10:30/11:30/13:00/14:00 | `check_and_refresh` | 매 슬롯 스냅샷 + S2 장중 + (trigger 시) S3~S6 재실행 | `morning_context` 갱신, `intraday_refresh.{date}.{slot}` |
| **S9** | 15:20 | `run_eod_liquidation` + `decision_engine.deactivate()` | 전 포지션 시장가 청산 | `trading_orders (sell, EOD)` |
| **MissedReturns** | 15:35 | `update_missed_returns` | 당일 미진입 종목 EOD 가격으로 max_return 갱신 | `missed_opportunities` |
| **S10-Review** | 16:00 | `job_review_audit` | false_positive 자동 분석 + LLM 복기 + learning_memory | `false_positive_cases`, `daily_review_reports`, `learning_memories` |
| **S11-LossGuard** | 16:00+ | `auto_block_loss_streak_symbols` | 3회+ 손실 종목 자동 차단 등록 | `expert_knowledge (blocks)` |
| **S10-Summary** | 18:00 | `run_daily_summary` + DB 백업 | 당일 거래 집계 + .db.gz 백업 | `daily_trade_summary`, `backups/` |

### 비거래일 (`schedule_skip_today=true`)
- S1이 휴장일 감지하면 S3~S10 전체 스킵
- 콘솔은 마지막 실거래일 데이터 표시 (`_latest_pipeline_data_date()` 2단계 우선순위)
- `schedule_skip_today`는 다음날 자정에 자동 리셋

---

## 4. 의사결정 알고리즘

### 4.1 4계층 게이트

매수 신호가 실제 주문이 되기까지 통과해야 하는 4계층 게이트:

```
S3 정량 게이트     KIS 거래량/거래대금 상위 + 가격·거래량 0 제외 + 상한가/하한가 제외 + ETF 제외
  ↓ 30개 (시장톤별 20~35)
S4 LLM 정성 게이트  LLM이 시장톤/메모리/뉴스 기반으로 suitability_score 0.0~1.0 부여
  ↓ 6~10개 + 종목별 confidence
S5 Risk Profile     LOW_VOL/MID_VOL/HIGH_VOL/THEME_SPIKE 분류 + 일일 한도
  ↓ symbol_assignments
S6 Rule Engine 게이트 (AND)
  ├── ai_confidence ≥ min_ai_confidence (LLM이 산출, 기본 0.65)
  ├── price_change_pct ∈ [min, max]      (LLM이 산출, 기본 1.0~5.0)
  ├── volume_ratio ≥ min_volume_ratio    (기본 1.0)
  └── time_window: 진입 가능 시간대
  ↓ 통과
KIS 주문 (시장가)
```

### 4.2 S6 게이트 세부 (실시간 틱 평가)

```python
# decision_engine.py 핵심 조건
matched = {
    "ai_confidence":   candidate.confidence >= min_ai_confidence,
    "price_change":    min_price_change <= tick.change_rate <= max_price_change,
    "volume_ratio":    tick.volume_ratio >= min_volume_ratio,
    "time_window":     entry_start_time <= now <= entry_end_time,
}

# OR 게이트: time_window·volume_ratio·ai_confidence 필수
# price_change만 미달 허용 (LLM 신뢰 강함 + 거래량 활발하면 가격 조건 완화 가능)
```

### 4.3 매도 알고리즘 (Trailing Stop)

```
진입가 P0
  ↓ 가격 P 변동
trailing_high = max(trailing_high, P)
trailing_stop = trailing_high × (1 - trailing_stop_rate)   # 기본 -2%

if P <= trailing_stop:       매도
if P <= P0 × (1 - stop_loss_rate):       손절 (-5%)
if now >= entry_time + max_holding_minutes: 시간 청산 (390분)
if now >= 15:20:               EOD 청산 (S9)
```

### 4.4 절대 한도 (L1 — 코드 하드코딩, LLM 변경 불가)

```python
_DAILY_LOSS_LIMIT_L1  = -0.10  # -10%
_MAX_POSITIONS_L1     = 30
_STOP_LOSS_L1         = -0.05  # -5%
_MAX_POS_SIZE_L1      = 0.30   # 30%
_TAKE_PROFIT_L1       = 0.30   # 30%
_MAX_HOLDING_MIN_L1   = 390    # 분
```

LLM이 더 위험한 값을 제안해도 L1에 clamp된다.

---

## 5. 학습 루프 알고리즘

### 5.1 데이터 수집 단계 (장중)

```
S6 게이트 단계별 누락 → missed_opportunities INSERT
  ├── stage='S3_UNIVERSE_FILTER'  (정량 필터 탈락)
  ├── stage='S4_HYBRID_SCREENING' (LLM 점수 부족)
  └── stage='S6_DECISION_ENGINE'  (틱 게이트 미통과)

S6 감시 종목 중 미매수 → shadow_trades INSERT
  └── rule_matched JSON에 게이트 통과/실패 내역

매수 → trading_orders INSERT (buy)
매도 → trading_orders INSERT (sell, status=filled 후 fills 매칭)
```

### 5.2 EOD 분석 단계 (15:35 ~ 16:00)

```
[15:35] update_missed_returns(today)
  미진입 종목들의 EOD 가격으로 추적:
    - max_return_after_10m
    - max_return_after_30m
    - max_return_until_eod
  EOD 수익률이 진입가 대비 +2% 이상이면 improvement_candidate=1
  → "이 종목들은 다음에 진입 고려해야 한다"

[16:00] job_review_audit
  Step 0: generate_false_positives_for_date(today)
    당일 손실 거래 → LLM이 패턴 분석 → false_positive_cases INSERT
    "왜 손실이 났는가" 자동 귀인 (진입 사유 vs 청산 사유)

  Step 1: run_review_audit(today)
    daily_review_reports INSERT (total_trades, win/loss, pnl)
    LLM이 narrative + regime_evaluation + settings_overrides 생성
    settings_overrides → system_settings 즉시 반영 (actor='s10_llm')

  Step 2: run_learning_memory_builder(today)
    improvement_candidate 종목 → "고려 패턴" 메모리
    false_positive_cases → "회피 패턴" 메모리
    auto_apply_allowed=1: 다음날 자동 적용
    requires_approval=1: 콘솔에서 PM 승인 대기

  Step 3: auto_block_loss_streak_symbols(today)
    같은 종목 3회+ 손실 → expert_knowledge 자동 차단 등록
```

### 5.3 다음날 반영 단계

```
S3 universe_filter:
  활성 learning_memories 중 scope='S3'인 메모리를 LLM 가중치 조정에 반영

S4 hybrid_screening:
  활성 learning_memories 중 scope='S4'/'ALL'을 프롬프트에 주입
  expert_knowledge 차단 목록 → 후보에서 제외

S5 daily_plan:
  활성 learning_memories 중 scope='S5'/'ALL'을 프롬프트에 주입
```

### 5.4 학습 루프 헬스 = 데이터 흐름 끊김 없음

루프가 끊기는 흔한 원인:
- **15:35 cron 미실행** (서버 미반영, asyncio 같은 import 누락) → missed_returns 추적 0
- **16:00 review_audit 실패** → daily_review_reports 누락 → learning_memory 0
- **learning_memory `auto_apply_allowed=0` 고착** → PM이 콘솔에서 승인 안 함

→ 매 EOD `EOD_CHECKLIST.md`로 자동 검증.

---

## 6. 장중 재선별 알고리즘

### 6.1 슬롯 (5회/거래일)

```
09:30 / 10:30 / 11:30 / 13:00 / 14:00
```

13:00/14:00은 점심 슬롯. `intraday_refresh.lunch_slots_enabled` kill switch로 제어.

### 6.2 슬롯 동작 흐름 (`check_and_refresh`)

```
1. 시장 스냅샷 수집 (fetch_intraday_kr_market_snapshot)
     ├── KOSPI/KOSDAQ 지수 (FHPUP02100000)
     ├── 거래대금 상위 10
     ├── 거래량 상위 30 (avg_change용)
     └── 업종 지수 4 (반도체/IT, 2차전지, 금융, 바이오)

2. S2 장중 분석 (매 슬롯, 항상)
     스냅샷 재사용 → intraday_market_tone.md 프롬프트 → morning_context 새 행

3. trigger 판단 (_needs_refresh)
     intensity별 threshold:
       defensive: 2.0%
       aggressive: 2.0%
       neutral/normal: 3.0%
     이미 같은 방향 trigger 있으면 _RETRIGGER_DELTA(1.0%) 만큼 추가 변동 필요

4. sector_rotation 판단 (detect_sector_rotation)
     상위 2섹터 평균 - 하위 N섹터 평균 ≥ 3.0%이면 trigger
     섹터 정보: KIS volume-rank 응답의 bstp_kor_isnm 인라인 사용

5. triggered=True면 reselection:
     S3 → S4 → S5 → S6 (S2는 이미 실행됨)
     S6: 기존 보유는 유지, 신규 후보로 교체
```

### 6.3 재선별 시 보유 종목 처리

- 보유 종목은 신규 매수 평가에서 자동 제외 (`position_manager`)
- S5 재실행 시 보유는 그대로, 신규만 교체
- S6 후보 교체: `old_count=N, new_count=M` 로그

---

## 7. LLM과 Rule Engine의 분담

| 작업 | LLM | Rule Engine | 사유 |
|---|:---:|:---:|---|
| 시장 톤 판단 (tone/regime) | ✓ | | 정성적, 다중 신호 통합 |
| 후보 종목 정성 점수 (confidence) | ✓ | | 뉴스·테마·메모리 통합 |
| 진입 임계값 (min_ai_confidence 등) | ✓ | | 시장톤별 동적 조정 |
| Risk Profile 분류 | ✓ | | 종목 특성 판단 |
| 실시간 틱 게이트 (AND 조건) | | ✓ | 결정론적, 빠른 응답 |
| 트레일링 스탑 계산 | | ✓ | 결정론적 |
| 손익 집계 | | ✓ | 사실 |
| EOD 청산 | | ✓ | 결정론적 |
| 손실 거래 패턴 분석 (false_positive) | ✓ | | 정성적 귀인 |
| 학습 메모리 생성 (improvement/false_positive → memory) | ✓ | | 자연어 패턴화 |
| `learning_memory.auto_apply_allowed` 판단 | ✓ | | 메모리 신뢰도 |
| L1 한도 clamp | | ✓ | LLM 폭주 방지 |

**원칙**: LLM은 "정성적 판단·자연어 패턴화", Rule Engine은 "결정론적 실행·안전 가드". LLM이 위험한 값을 제안해도 L1이 막는다.

---

## 8. 데이터 흐름과 SSOT

```
[수집]
  KIS volume-rank, trade-amount-rank → universe_filter → universe_results
  KIS index/sector                    → fetch_intraday_kr_market_snapshot
  KIS WebSocket H0STCNT0              → decision_engine
  KIS REST inquire-balance            → position_manager (60초 주기 sync)

[판단]
  market_tone_results → morning_context → hybrid_screening → daily_trading_plans → decision_engine

[실행]
  decision_engine → trading_signals → order_executor → trading_orders → fill_poller → fills
                                                    → position_manager (메모리 + KIS sync)

[학습]
  game gates → missed_opportunities (실시간)
  trading_orders → daily_trade_summary → false_positive_cases (16:00)
                                       → daily_review_reports (16:00)
                                       → learning_memories (16:00)
                                       → expert_knowledge (loss streak)

[피드백]
  learning_memories (active) → 다음날 universe_filter / hybrid_screening / daily_plan 프롬프트
  expert_knowledge (blocks)  → 다음날 모든 단계 차단 적용
```

### 8.1 schedule_skip_today

- S1이 휴장일 판단 → `true` 설정 → S3~S10 전체 스킵
- 다음날 00:00 KST에 `_reset_schedule_skip_if_stale()`로 자동 리셋
- 고착 시 콘솔 Settings 화면에서 수동 false 설정 가능

### 8.2 시간대 처리

- **모든 도메인 시간은 KST (`Asia/Seoul`)**
- DB의 `created_at` 등은 UTC ISO8601 또는 KST ISO8601 혼재 — 신규 코드는 KST ISO8601 권장
- 서버 OS 시간이 UTC여도 `ZoneInfo("Asia/Seoul")` 명시 사용

---

## 9. 알려진 취약점

> 2026-05-22 전문가 감사 기준. 심각도 HIGH > MEDIUM > LOW.

### HIGH

| ID | 위치 | 현상 | 현재 방어 | 대응 필요 |
|---|---|---|---|---|
| H1 | `decision_engine._restore_positions_from_db`, `eod_liquidation` | 재시작 후 매도 미체결 포지션 복원 누락 | `_has_recent_submitted_buy` (5분 내 중복 차단) | KIS 잔고 자동 대사 |
| H2 | `order_executor`, `fill_poller` | ODNO 미수신 시 영구 추적 불가 | 재조회, `recover-fills` API | ODNO 실패 시 텔레그램 즉시 경보 |
| H3 | `decision_engine._emit_signal` | DB 저장 실패 시 빈 signal_id 주문 가능 | 없음 | DB 저장 실패 시 주문 차단 |
| H4 | `trade_pairs` | 동일 종목 복수 진입/청산 합산 | 없음 | FIFO 페어링 |

### MEDIUM

| ID | 위치 | 현상 | 대응 필요 |
|---|---|---|---|
| M1 | daily_loss tracking | -10% 초과해도 신규 진입 계속 | -3% 초과 시 차단 |
| M2 | `order_executor` | 동시 신호 race condition | semaphore 내부로 이동 |
| M3 | `position_manager` | 트레일링 활성 전 손실 확대 | 30분 후 break-even 상향 |
| M4 | S9 | 부분 청산 실패 후 야간 gap | 텔레그램 즉시 경보 |
| M5 | S9~S10 | 사이 추가 체결 누락 | S10 직전 2회 추가 poll |

### LOW

- L1: `asyncio.create_task` 알림 타이밍 불확실 (주문은 정상)
- L2: pykrx 일봉 백테스트 정밀도 한계 (실거래에는 무관)

### 2026-05-26 신규 발견

- **N1**: `scheduler.py import asyncio` 누락 — 4일간 EOD 학습 루프 silent failure. 코드 fix 완료, 서버 재시작으로 활성화.
- **N2**: `symbols.sector` 테이블 비어있음 — sector_rotation 항상 `sector_sample_insufficient` 반환. KIS 응답 `bstp_kor_isnm` 인라인 사용으로 우회.
- **N3**: `morning_context`가 항상 아침 값 — S2 장중 재실행이 reselection 안에만 있어서 trigger 안 되면 stale. 매 슬롯 항상 실행으로 수정.

---

## 10. 운영 명령어

```bash
# 서버 시작 (venv 활성화 후)
source .venv/bin/activate
nohup python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 > logs/server.log 2>&1 &

# 서버 상태
curl http://127.0.0.1:8000/health

# 서버 재시작 (코드 변경 후 필수)
pkill -f "uvicorn backend.main" ; sleep 2
nohup python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 > logs/server.log 2>&1 &

# 로그 추적
tail -f logs/server.log

# 오늘 missed_returns 수동 backfill
python -c "
import asyncio
from backend.services.engine.missed_opportunity import update_missed_returns
asyncio.run(update_missed_returns('YYYY-MM-DD'))
"

# 특정 날짜 S10 LLM 복기 재실행
curl -X POST http://127.0.0.1:8000/api/v1/review-audit/run \
  -H "Content-Type: application/json" -d '{"date": "YYYY-MM-DD"}'

# 체결 수동 복구
curl -X POST http://127.0.0.1:8000/api/v1/trading/admin/recover-fills

# 백테스트 즉시 실행 (현재 설정)
curl -X POST http://127.0.0.1:8000/api/v1/backtest/quick

# TOTP 코드 생성 (콘솔 로그인 2차 인증)
python3 -c "
import hmac, hashlib, struct, time, base64
def totp(s): k=base64.b32decode(s.upper()); t=int(time.time())//30; h=hmac.new(k,struct.pack('>Q',t),hashlib.sha1).digest(); o=h[-1]&0xf; return str((struct.unpack('>I',h[o:o+4])[0]&0x7fffffff)%1000000).zfill(6)
print(totp('CN3OQNTSTRNWWGXMBRP7466IMY4DXEXL'))
"
```

---

## 11. API 인덱스

| 그룹 | 엔드포인트 | 용도 |
|---|---|---|
| 시스템 | `GET /health` | 서버 상태 |
| 봇 | `GET /api/v1/bot/overview` | Today Control |
| 스케줄러 | `GET /api/v1/scheduler/status` | 파이프라인 진행 |
| 설정 | `GET/POST /api/v1/settings` | system_settings |
| 매매 | `GET /api/v1/trading/orders` | 주문 내역 |
| 매매 | `GET /api/v1/trading/signals` | BUY 신호 |
| 매매 | `POST /api/v1/trading/admin/recover-fills` | 체결 수동 복구 |
| 복기 | `GET /api/v1/review-audit/{date}` | 복기 리포트 |
| 복기 | `POST /api/v1/review-audit/run` | S10 LLM 복기 실행 |
| False Positive | `GET /api/v1/false-positive/list` | 손실 분석 목록 |
| 학습 메모리 | `GET /api/v1/learning-memory/list` | 활성 메모리 |
| 미진입 | `GET /api/v1/missed-opportunity/list` | 미진입 추적 |
| 레짐 | `GET /api/v1/regime/day-detail` | 레짐 SET 상세 |
| 장중 재선별 | `GET /api/v1/funnel/intraday-refresh` | 재선별 이력 |
| 백테스트 | `POST /api/v1/backtest/run` | 파라미터 백테스트 |
| 진단 | `GET /api/v1/engine/audit/today` | 단계별 감사 |
| Data Quality | `GET /api/v1/data-quality/...` | 데이터 결손 체크 |
