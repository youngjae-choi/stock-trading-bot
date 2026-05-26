# EOD 체크리스트 — 매 장마감 후 시스템 로그와 1:1 대조

> **사용법**: 매 거래일 18:00 이후 이 문서의 각 항목을 SQL/curl로 실행하고 정상/비정상을 표시한다.
> 비정상 항목은 의심 위치를 따라가서 원인 추적 후 다음날 아침 전에 fix.
> 학습 루프가 자율 동작 검증되기 전까지는 **PM + Sisyphus 공동 책임**.
>
> 시스템 철학·알고리즘은 [`SYSTEM_GUIDE.md`](SYSTEM_GUIDE.md), 일일 시간표·기대 동작은 [`OPERATION_SPEC.md`](OPERATION_SPEC.md) 참조.

---

## 우선순위 정의

| 등급 | 의미 |
|---|---|
| **🔴 Critical** | 미통과 시 자동매매 시스템 전체 마비 (거래 0건, 데이터 0건 등). 즉시 fix. |
| **🟠 High** | 핵심 기능 일부 차단 (학습 루프 끊김, 특정 단계 실패). 다음날 아침 전 fix. |
| **🟡 Medium** | 데이터 결손 일부 (1~2일 누락). 주중 fix. |
| **🟢 Low** | UX/표시/로그 정합성. 주말 fix. |

---

## 사용 변수

체크리스트 실행 시 다음 변수를 본인 날짜로 치환:
- `TODAY` = `YYYY-MM-DD` (오늘 거래일, KST)
- `YESTERDAY` = `YYYY-MM-DD` (전 거래일)

---

# 섹션 A. 인프라 헬스

## A1. 서버 프로세스 살아있음 🔴

**정상 기준**: uvicorn 프로세스 1개, health=200

```bash
ps aux | grep "uvicorn backend.main" | grep -v grep
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/health
```

**비정상 의심**: 서버 크래시, OOM, 포트 충돌 → `logs/server.log` 마지막 100줄

---

## A2. 서버 시작 시간이 최근 코드 커밋 이후 🔴

**정상 기준**: 서버 PID start_time > 마지막 `backend/services/scheduler.py` 커밋 시각

```bash
# 서버 시작 시간
ps -o lstart= -p $(pgrep -f "uvicorn backend.main")
# 최근 scheduler 커밋
git log -1 --format="%cd" backend/services/scheduler.py
```

**비정상 의심**: 코드 수정 후 서버 미반영 → 재시작 필요 (silent failure 위험)

---

## A3. APScheduler 등록 job 수 🟠

**정상 기준**: 17개 이상 (S1~S11 + 5슬롯 + 12개 레짐 모니터 + 알림)

```bash
curl -s http://127.0.0.1:8000/api/v1/scheduler/status | python -c "
import json, sys
d = json.load(sys.stdin)
print('running:', d.get('running'))
print('jobs:', len(d.get('jobs', [])))
for j in d.get('jobs', []): print(' ', j.get('id'), j.get('next_run_time'))
"
```

**비정상 의심**: scheduler 초기화 실패, import 에러 → `logs/server.log` 검색 `START: scheduler`

---

# 섹션 B. S2 아침 시장 톤 (00:01 KST)

## B1. S2 아침 실행 완료 🔴

**정상 기준**: 오늘 trade_date로 `market_tone_results` 1건 INSERT, tone ∈ {positive,neutral,negative,mixed}, confidence ≥ 0.3

```sql
SELECT trade_date, tone, confidence, summary, provider, created_at
FROM market_tone_results
WHERE trade_date = 'TODAY'
ORDER BY created_at ASC LIMIT 1;
```

**비정상 의심**:
- 0건 → 스케줄러 미실행, 휴장일 인식, LLM 호출 실패
- confidence=0.0 → LLM 파싱 실패 (raw_response 확인)

---

## B2. 야간 데이터 수집 성공 🟠

**정상 기준**: `morning_context.market_data` JSON에 sp500/nasdaq/vix/usdkrw/kospi 등 핵심 키 존재

```sql
SELECT trade_date,
       json_extract(market_data, '$.sp500.change_pct') as sp500,
       json_extract(market_data, '$.vix.value') as vix,
       json_extract(market_data, '$.usdkrw.value') as usdkrw
FROM morning_context
WHERE trade_date = 'TODAY'
ORDER BY created_at ASC LIMIT 1;
```

**비정상 의심**: yfinance 차단, S11 us_market_watch fallback도 실패 → `market_data_fetcher` 로그

---

# 섹션 C. 거래 준비 (08:00~08:50)

## C1. S1 거래일 판단 🔴

**정상 기준**: 거래일이면 `schedule_skip_today=false`, 아니면 `true`

```sql
SELECT key, value_json FROM system_settings WHERE key='schedule_skip_today';
```

**비정상 의심**: KIS 트레이딩 캘린더 API 실패 → `_weekday_trading_day_fallback` 가 작동했는지 확인

---

## C2. S3 Universe Filter 정상 실행 🔴

**정상 기준**: `universe_results` 오늘 1건, `filtered_count` ≥ 20, ETF 제외 작동

```sql
SELECT trade_date, market_tone, top_n_count, filtered_count, rejection_summary, created_at
FROM universe_results
WHERE trade_date = 'TODAY'
ORDER BY created_at DESC LIMIT 1;
```

**비정상 의심**:
- filtered_count < 20 → KIS rate limit, 시장톤 너무 negative
- rejection_summary에 etf가 비정상적으로 높음 → ETF 식별 오류

---

## C3. S4 Hybrid Screening 정상 실행 🔴

**정상 기준**: `screening_results` 오늘 1건, `output_count` ≥ 5, `overall_confidence` ≥ 0.4

```sql
SELECT trade_date, output_count, overall_confidence, entry_rules_json, provider, created_at
FROM screening_results
WHERE trade_date = 'TODAY'
ORDER BY created_at DESC LIMIT 1;
```

**비정상 의심**:
- output_count=0 → LLM 응답 파싱 실패, S3 결과 부족
- overall_confidence < 0.3 → 야간 데이터로 시장 판단 보수적 (stale 의심)

---

## C4. S5 Daily Plan 정상 실행 🔴

**정상 기준**: `daily_trading_plans` 오늘 1건, `symbol_assignments` ≥ 5, `trading_intensity` ∈ {aggressive,normal,defensive}

```sql
SELECT trade_date, market_tone, trading_intensity,
       json_array_length(symbol_assignments) as assignments,
       new_entry_allowed, base_rulepack_id, created_at
FROM daily_trading_plans
WHERE trade_date = 'TODAY'
ORDER BY created_at DESC LIMIT 1;
```

**비정상 의심**:
- assignments=0 → S4 후보 부족 또는 LLM 응답 빈 배열
- intensity=defensive + 시장 강세 → S5 LLM이 stale 데이터로 판단 (B2 확인)

---

## C5. S4 entry_rules 합리성 🟡

**정상 기준**: `min_ai_confidence` ∈ [0.40, 0.85], `min_price_change_pct` ∈ [0.5, 2.0], `max_price_change_pct` ∈ [3.0, 10.0]

```sql
SELECT trade_date,
       json_extract(entry_rules_json, '$.min_ai_confidence') as min_conf,
       json_extract(entry_rules_json, '$.min_price_change_pct') as min_pc,
       json_extract(entry_rules_json, '$.max_price_change_pct') as max_pc
FROM screening_results WHERE trade_date='TODAY';
```

**비정상 의심**:
- max_pc=5.0 고착 + improvement_candidate 다수가 +5% 이상 → 가설 검증 필요 (헐렁한 거래 모드 검토)

---

# 섹션 D. Decision Engine 활성화 (09:00)

## D1. S6 활성화 성공 🔴

**정상 기준**: 로그에 `decision_engine.activate()` 성공, WebSocket 구독 종목 수 = symbol_assignments 수

```bash
grep "S6.*Decision Engine\|decision_engine.activate\|H0STCNT0 subscribe" logs/server.log | tail -20
```

**비정상 의심**: KIS WebSocket 인증 실패, 토큰 만료 → realtime_ws 로그

---

## D2. KIS 잔고 동기화 시작 🟠

**정상 기준**: `position_manager.sync_account_position()` 60초 주기 호출, KIS 잔고 보유 종목과 메모리 일치

```bash
grep "sync_account_position\|KIS 잔고" logs/server.log | tail -20
```

**비정상 의심**: KIS 토큰 만료, REST 호출 실패 → 보유 종목 미인식

---

# 섹션 E. 장중 슬롯 (5회/거래일)

## E1. 슬롯 실행 이력 5건 🟠

**정상 기준**: 오늘 09:30/10:30/11:30/13:00/14:00 슬롯 모두 `ran=true`

```sql
SELECT key, json_extract(value_json,'$.ran') as ran,
       json_extract(value_json,'$.triggered') as triggered,
       json_extract(value_json,'$.avg_change') as avg_change,
       json_extract(value_json,'$.reason') as reason
FROM system_settings
WHERE key LIKE 'intraday_refresh.TODAY.%'
ORDER BY key;
```

**비정상 의심**:
- 누락 슬롯 → 스케줄러 job 미발동, kill switch (lunch_slots_enabled)
- avg_change=null → 스냅샷 수집 실패

---

## E2. 매 슬롯 S2 장중 실행 🟠

**정상 기준**: 오늘 `morning_context` 행 수 ≥ 6 (아침 1 + 슬롯 5)

```sql
SELECT COUNT(*) as rows, MIN(created_at) as first, MAX(created_at) as last
FROM morning_context WHERE trade_date='TODAY';
```

**비정상 의심**:
- rows=1 → 슬롯 S2 미동작 (intraday_refresh._run_s2_intraday 실패)
- rows=2~5 → 일부 슬롯 실패 → 슬롯별 로그 확인

---

## E3. 슬롯 스냅샷 KIS 지수 정상 🟡

**정상 기준**: morning_context.market_data의 kospi/kosdaq change_rate가 실제 KIS 종가와 일치 (±0.5%)

```sql
SELECT created_at,
       json_extract(market_data, '$.kospi.change_rate') as k,
       json_extract(market_data, '$.kosdaq.change_rate') as q
FROM morning_context WHERE trade_date='TODAY' ORDER BY created_at;
```

**비정상 의심**: KIS index API (`FHPUP02100000`) 응답 파싱 실패, 0.0 고착 → `universe_service.get_market_index`

---

## E4. sector_rotation 동작 🟡

**정상 기준**: `sector_sample_insufficient` 가 아닌 정상 sector_avgs 결과

```sql
SELECT trade_date, slot, top_sectors, bottom_sectors, gap_pct, triggered
FROM sector_rotation_log
WHERE trade_date='TODAY' ORDER BY slot;
```

**비정상 의심**:
- 모든 슬롯이 `sector_sample_insufficient` → KIS volume-rank 응답에 bstp_kor_isnm 없음 또는 인라인 sector 누락

---

## E5. trigger 발동 합리성 🟡

**정상 기준**: avg_change ≥ threshold 인 슬롯은 triggered=True, 미만이면 False

```sql
-- 어떤 슬롯이 trigger되어야 했는데 안 됐는지 검출
SELECT key,
       json_extract(value_json,'$.avg_change') as ac,
       json_extract(value_json,'$.triggered') as t,
       json_extract(value_json,'$.reason') as r
FROM system_settings
WHERE key LIKE 'intraday_refresh.TODAY.%';
```

**비정상 의심**:
- avg_change=+4% but triggered=False → `_RETRIGGER_DELTA`(1.0%) 로 인한 retrigger 차단 의도 vs 누락 확인

---

## E6. trigger 발동 시 reselection 체인 정상 🟠

**정상 기준**: triggered=True 슬롯의 reselection.s3/s4/s5/s6 전부 ok=true

```sql
SELECT key,
       json_extract(value_json,'$.reselection.s3.ok') as s3,
       json_extract(value_json,'$.reselection.s4.ok') as s4,
       json_extract(value_json,'$.reselection.s5.ok') as s5,
       json_extract(value_json,'$.reselection.s6.ok') as s6
FROM system_settings
WHERE key LIKE 'intraday_refresh.TODAY.%'
  AND json_extract(value_json,'$.triggered')=1;
```

**비정상 의심**: 어느 한 단계 ok=false → 해당 모듈 로그 확인

---

# 섹션 F. 매매 실행 (장중)

## F1. 매수 신호 발행 건수 🟠

**정상 기준**: 거래일당 최소 1건. 0건 연속 2일 이상이면 보수성 의심 (Exploration Mode 검토).

```sql
SELECT trade_date, COUNT(*) as buys
FROM trading_signals
WHERE signal_type='BUY' AND trade_date >= date('TODAY','-3 days')
GROUP BY trade_date ORDER BY trade_date DESC;
```

**비정상 의심**:
- 0건 + KOSPI 강세 → S4 confidence 낮음 또는 min_ai_confidence 너무 높음
- 0건 + `shadow_trades` 다수 → S6 게이트 미통과 (어느 조건이 떨어졌는지)

---

## F2. 주문 → 체결 전환율 🟠

**정상 기준**: filled / submitted ≥ 0.8

```sql
SELECT side, status, COUNT(*) FROM trading_orders
WHERE trade_date='TODAY' GROUP BY side, status;
```

**비정상 의심**:
- submitted_without_order_no 다수 → KIS ODNO 미수신 (H2 취약점)
- submitted 다수 남음 → fill_poller 실패

---

## F3. shadow_trades로 게이트 분석 🟡

**정상 기준**: shadow_trades에 rule_matched JSON 있고, 각 조건별 통과/실패 분포 확인 가능

```sql
SELECT symbol, json_extract(rule_matched,'$.ai_confidence') as conf,
       json_extract(rule_matched,'$.price_change') as pc,
       json_extract(rule_matched,'$.volume_ratio') as vr,
       json_extract(rule_matched,'$.time_window') as tw
FROM shadow_trades WHERE trade_date='TODAY' LIMIT 20;
```

**비정상 의심**: 특정 조건이 매번 false → 임계값 점검

---

## F4. 트레일링 스탑 발동 정상 🟡

**정상 기준**: 보유 종목 중 익절 또는 손절은 trailing/stop_loss 사유로 매도 기록

```sql
SELECT symbol, side, status, reason FROM trading_orders
WHERE trade_date='TODAY' AND side='sell';
```

**비정상 의심**: reason=null → exit 사유 미기록, position_manager 점검

---

# 섹션 G. S9 청산 (15:20)

## G1. S9 EOD 청산 실행 🔴

**정상 기준**: `pipeline_run_audit`에 step='S9' status='success' 1건, 미청산 잔여 포지션 0

```sql
SELECT date(started_at) as d, step, status, message
FROM pipeline_run_audit
WHERE step='S9' AND started_at >= datetime('TODAY 00:00:00')
ORDER BY started_at DESC;
```

**비정상 의심**:
- status=failed → KIS 주문 실패, 잔고 동기화 문제
- 잔여 포지션 → 부분 청산 실패 (M4 취약점)

---

## G2. Decision Engine 비활성화 🟠

**정상 기준**: `decision_engine.deactivate()` 성공 로그, WebSocket 구독 해제

```bash
grep "decision_engine.deactivate\|S9 Decision Engine 비활성화" logs/server.log | tail -5
```

**비정상 의심**: 비활성화 실패 시 다음 거래일까지 메모리 누수

---

## G3. POSTPROCESS 파이프라인 성공 🔴

**정상 기준**: `pipeline_run_audit`에 step='POSTPROCESS' status='success' (또는 'partial_failed' for S9 only)

```sql
SELECT date(started_at) as d, step, status, message
FROM pipeline_run_audit
WHERE step IN ('POSTPROCESS','S9') AND started_at >= datetime('TODAY 00:00:00')
ORDER BY started_at;
```

**비정상 의심**:
- `name 'asyncio' is not defined` → 코드 수정 후 서버 미반영 (2026-05-26 사례)
- 다른 NameError → 새 silent failure 패턴 가능

---

# 섹션 H. 미진입 추적 (15:35)

## H1. missed_opportunities 추적 완료 🔴

**정상 기준**: tracked/total ≥ 0.9

```sql
SELECT trade_date, COUNT(*) as total,
       SUM(CASE WHEN max_return_until_eod IS NOT NULL THEN 1 ELSE 0 END) as tracked,
       SUM(CASE WHEN improvement_candidate=1 THEN 1 ELSE 0 END) as improvements
FROM missed_opportunities WHERE trade_date='TODAY';
```

**비정상 의심**:
- tracked=0 → 15:35 cron 미실행 (`job_missed_returns_update`) 또는 KIS rate limit
- tracked/total < 0.5 → KIS 일부 종목 실패 (delisting, suspension)

---

## H2. improvement_candidate 분포 🟡

**정상 기준**: total 대비 5~25%

```sql
SELECT
  SUM(CASE WHEN improvement_candidate=1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as pct
FROM missed_opportunities WHERE trade_date='TODAY';
```

**비정상 의심**:
- < 5% → 시스템이 다 잡고 있음 (좋음) 또는 추적 실패
- > 25% → 보수성 과다 (Exploration Mode 도입 검토)

---

## H3. 미진입 상승 TOP10 🟢 (분석용)

**정상 기준**: 가장 크게 놓친 종목과 그 reason 확인

```sql
SELECT symbol, symbol_name, max_return_until_eod, missed_stage, missed_reason
FROM missed_opportunities WHERE trade_date='TODAY'
ORDER BY max_return_until_eod DESC NULLS LAST LIMIT 10;
```

**활용**: 반복되는 missed_reason → S3/S4 알고리즘 가설 재검토 자료

---

# 섹션 I. S10 Review & Audit (16:00)

## I1. false_positive 자동 분석 실행 🟠

**정상 기준**: 손실 거래(`realized_pnl < 0`) 있으면 `false_positive_cases` 동일 수 이상

```sql
-- 손실 거래 수
SELECT COUNT(*) FROM daily_trade_summary WHERE trade_date='TODAY' AND realized_pnl < 0;
-- false_positive_cases 수
SELECT COUNT(*) FROM false_positive_cases WHERE trade_date='TODAY';
```

**비정상 의심**: 손실 ≥ 1 + fp 수 = 0 → `generate_false_positives_for_date` 실패 (Step 0)

---

## I2. daily_review_reports 생성 🔴

**정상 기준**: 오늘 1건 created_at 기록, total_trades/total_pnl/false_positive_count 채워짐

```sql
SELECT trade_date, total_trades, total_pnl, false_positive_count,
       memory_count, missed_entries_count, pnl_status, created_at
FROM daily_review_reports
WHERE trade_date='TODAY';
```

**비정상 의심**:
- 0건 → `run_review_audit` 실패 (LLM 실패, prompt 렌더 실패)
- pnl_status='unverified' → fills 결손, recover-fills 필요

---

## I3. learning_memories 생성 🟠

**정상 기준**: 오늘 ≥ 5건 (improvement + false_positive 합계)

```sql
SELECT trade_date, scope, category,
       SUM(auto_apply_allowed) as auto_apply,
       SUM(requires_approval) as needs_approval,
       COUNT(*) as total
FROM learning_memories
WHERE trade_date='TODAY'
GROUP BY scope, category;
```

**비정상 의심**: 0건 → `run_learning_memory_builder` 실패

---

## I4. settings_overrides 자동 반영 🟡

**정상 기준**: S10 LLM이 변경 권고한 setting은 `system_settings` updated_by='s10_llm'으로 갱신

```sql
SELECT key, value_json, updated_at, updated_by
FROM system_settings
WHERE updated_by='s10_llm' AND date(updated_at) = 'TODAY'
ORDER BY updated_at DESC;
```

**비정상 의심**: 변경 권고는 있는데 반영 0 → upsert_setting 실패

---

## I5. loss_streak_guard 차단 🟢

**정상 기준**: 3회+ 손실 종목이 expert_knowledge에 자동 등록

```sql
SELECT * FROM expert_knowledge
WHERE status='active' AND scope LIKE '%BLOCK%' AND date(created_at)='TODAY';
```

**비정상 의심**: 손실 스트릭 있는데 차단 등록 0 → `auto_block_loss_streak_symbols` 실패

---

# 섹션 J. Daily Summary + 백업 (18:00)

## J1. daily_trade_summary 정상 🟠

**정상 기준**: 오늘 1건, pnl_status ∈ {verified, no_orders, unverified}

```sql
SELECT trade_date, total_orders, realized_pnl, realized_pnl_pct,
       symbols_traded, market_tone, pnl_status, integrity_warnings
FROM daily_trade_summary WHERE trade_date='TODAY';
```

**비정상 의심**:
- 0건 → S10 daily_summary 미실행
- integrity_warnings 비어있지 않음 → 잔여 포지션, ODNO 누락 등

---

## J2. DB 백업 실행 🟡

**정상 기준**: `data/backups/` 또는 설정된 백업 경로에 오늘 날짜 .db.gz 파일

```bash
ls -lh data/backups/ | grep "TODAY" 2>&1 | head -5
```

**비정상 의심**: 백업 미생성 → `run_daily_summary` 백업 단계 실패

---

# 섹션 K. 다음날 반영 검증 (전일 데이터 활용 여부)

## K1. 전일 learning_memories 활성 상태 🟠

**정상 기준**: 어제 생성된 메모리가 today에 status='active', expires_at > today

```sql
SELECT scope, category, COUNT(*) as active_count
FROM learning_memories
WHERE status='active'
  AND (expires_at IS NULL OR expires_at >= 'TODAY')
GROUP BY scope, category;
```

**비정상 의심**: 0건 → 만료 처리 오류 또는 builder 미실행

---

## K2. 오늘 S4 프롬프트에 메모리 주입 확인 🟡

**정상 기준**: 오늘 S4 raw_response에 memory_section 흔적 또는 learning_memory 인용

```sql
-- 직접 확인: 오늘 S4 결과의 raw_response를 보고 memory_section 키 검색
SELECT trade_date, substr(raw_response, 1, 500)
FROM screening_results WHERE trade_date='TODAY' LIMIT 1;
```

**비정상 의심**: memory_section 빈 문자열 → hybrid_screening의 memory 조회 실패 또는 활성 메모리 0

---

## K3. expert_knowledge 차단 종목이 오늘 후보에서 제외됨 🟡

**정상 기준**: 차단 종목이 오늘 universe_filter/hybrid_screening 결과에 없음

```sql
-- 차단 종목 목록
SELECT json_extract(content_json,'$.symbol') as blocked
FROM expert_knowledge WHERE status='active' AND scope LIKE '%BLOCK%';
-- 오늘 screening_results candidates에 포함 여부 (수동 매칭)
```

**비정상 의심**: 차단 종목이 후보에 등장 → expert_knowledge 적용 누락

---

# 섹션 L. 학습 루프 종합 헬스 (주간)

## L1. 7일 학습 루프 동작률 🔴

**정상 기준**: 최근 7거래일 중 daily_review_reports 생성 = 거래일 수

```sql
SELECT date(created_at) as d, COUNT(*) as cnt
FROM daily_review_reports
WHERE created_at >= datetime('TODAY','-7 days')
GROUP BY d ORDER BY d DESC;
```

**비정상 의심**: 빠진 날 있음 → 해당 날짜 POSTPROCESS 로그 확인

---

## L2. 7일 missed_returns 추적률 🟠

**정상 기준**: 모든 날짜에서 tracked/total ≥ 0.9

```sql
SELECT trade_date, COUNT(*) as total,
       SUM(CASE WHEN max_return_until_eod IS NOT NULL THEN 1 ELSE 0 END) as tracked,
       ROUND(SUM(CASE WHEN max_return_until_eod IS NOT NULL THEN 1 ELSE 0 END)*100.0/COUNT(*), 1) as pct
FROM missed_opportunities
WHERE trade_date >= date('TODAY','-7 days')
GROUP BY trade_date ORDER BY trade_date DESC;
```

**비정상 의심**: 일부 날짜 tracked=0 → 해당일 15:35 cron 실패

---

## L3. 7일 false_positive 분석률 🟡

**정상 기준**: 손실 거래 있는 날은 fp_cases ≥ 1

```sql
SELECT s.trade_date,
       SUM(CASE WHEN o.realized_pnl < 0 THEN 1 ELSE 0 END) as losses,
       (SELECT COUNT(*) FROM false_positive_cases f WHERE f.trade_date = s.trade_date) as fp
FROM daily_trade_summary s
LEFT JOIN trading_orders o ON o.trade_date = s.trade_date
WHERE s.trade_date >= date('TODAY','-7 days')
GROUP BY s.trade_date ORDER BY s.trade_date DESC;
```

**비정상 의심**: losses ≥ 1 + fp=0 인 날 → review_audit Step 0 실패

---

## L4. 매수 신호 추세 (보수성 진단) 🟡

**정상 기준**: 7일 평균 매수 신호 ≥ 5건/일 (Exploration Mode 도입 후)

```sql
SELECT trade_date, COUNT(*) as buys
FROM trading_signals
WHERE signal_type='BUY' AND trade_date >= date('TODAY','-7 days')
GROUP BY trade_date ORDER BY trade_date DESC;
```

**비정상 의심**: 평균 < 3건/일 → 보수성 과다, Exploration Mode 미적용 또는 LLM 보수 판단

---

## L5. missed/매수 비율 (보수성 진단) 🟡

**정상 기준**: missed/매수 ≤ 5 (1매수당 5미진입 이하)

```sql
SELECT
  (SELECT COUNT(*) FROM missed_opportunities WHERE trade_date >= date('TODAY','-7 days')) as missed,
  (SELECT COUNT(*) FROM trading_signals WHERE signal_type='BUY' AND trade_date >= date('TODAY','-7 days')) as buys;
```

**비정상 의심**: missed/buys > 15 → 시스템이 거의 작동 안 함 (오늘 18x 사례)

---

# 섹션 M. 사고 후 조치 (Incident Response)

## M1. 코드 수정 후 서버 재시작 확인

**상황**: scheduler/engine 코드 수정 후

```bash
# 시작 시간 확인
ps -o lstart= -p $(pgrep -f "uvicorn backend.main")
# 마지막 커밋 시각
git log -1 --format="%cd %s" backend/services/
```

→ 시작 시간 < 커밋 시각이면 즉시 재시작.

---

## M2. silent failure 검출 패턴

**1차 자동 검색**:
```bash
grep -i "is not defined\|undefined\|NameError\|AttributeError" logs/server.log | tail -50
```

**2차**: `pipeline_run_audit` 최근 N일 status='failed' 메시지 확인
```sql
SELECT date(started_at), step, status, message
FROM pipeline_run_audit
WHERE status='failed' AND started_at >= datetime('TODAY','-7 days')
ORDER BY started_at DESC;
```

---

## M3. 한 항목 미통과 시 RCA 템플릿

```
[항목 번호]: 
[정상 기준]: 
[실제 값]: 
[1차 원인 가설]: 
[증거 (로그/SQL)]: 
[Fix 시점]: 
[재발 방지]: 
```

→ 재발 방지에 따라 신규 체크 항목으로 추가될 수 있음.

---

## 변경 이력

- 2026-05-26: 초안 작성. 70개 항목 (Critical 11, High 22, Medium 25, Low 12).
