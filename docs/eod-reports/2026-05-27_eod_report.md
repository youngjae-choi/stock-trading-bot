# EOD 검증 리포트 — 2026-05-27

- 생성: 2026-05-27T05:24:26.037130+09:00
- 거래일: YES (weekday + skip_today=false)
- 결과: PASS 3 / WARN 14 / FAIL 7 / SKIP 0 / INFO 5
- Critical FAIL: **5건** — 즉시 조치 필요

---

## 🔴 Critical FAIL 요약
- **B1**: S2 아침 실행 → no row
- **C2**: S3 Universe Filter → no row
- **C3**: S4 Hybrid Screening → no row
- **C4**: S5 Daily Plan → no row
- **I2**: daily_review_reports → no row

---

## 전체 검증 결과

### ✅ A1 🔴 서버 프로세스 + health — PASS
- **결과**: pids=['813086'], health=200

### ℹ️ A2 🔴 서버 시작 시간 vs 코드 커밋 — INFO
- **결과**: server_started=Tue May 26 20:21:42 2026 | scheduler.py last_commit=2026-05-26T08:17:57+00:00

### ⚠️ A3 🟠 APScheduler 등록 job — WARN
- **결과**: running=None, job_count=0

### ✅ M2 🟠 silent failure 로그 스캔 — PASS
- **결과**: recent_errors=0

### ℹ️ C1 🔴 schedule_skip_today — INFO
- **결과**: value=false

### ❌ B1 🔴 S2 아침 실행 — FAIL
- **결과**: no row

### ❌ B2 🟠 야간 데이터 핵심 키 — FAIL
- **결과**: no morning_context

### ❌ C2 🔴 S3 Universe Filter — FAIL
- **결과**: no row

### ❌ C3 🔴 S4 Hybrid Screening — FAIL
- **결과**: no row

### ❌ C4 🔴 S5 Daily Plan — FAIL
- **결과**: no row

### ⚠️ E1 🟠 장중 슬롯 5건 실행 — WARN
- **결과**: executed=0/5, missing=['09:30', '10:30', '11:30', '13:00', '14:00']

### ⚠️ E2 🟠 매 슬롯 S2 장중 실행 — WARN
- **결과**: morning_context_rows=0 (expected ≥6 = 아침1 + 슬롯5)

### ⚠️ E3 🟡 슬롯 스냅샷 KIS 지수 — WARN
- **결과**: non_zero_kospi_count=0/0

### ⚠️ E4 🟡 sector_rotation — WARN
- **결과**: no log rows

### ⚠️ F1 🟠 매수 신호 발행 — WARN
- **결과**: buy_signals=0

### ℹ️ F2 🟠 주문 체결 분포 — INFO
- **결과**: {}

### ⚠️ G1 🔴 S9 EOD 청산 — WARN
- **결과**: no S9 row today

### ⚠️ G3 🔴 POSTPROCESS — WARN
- **결과**: no POSTPROCESS row today

### ⚠️ H1 🔴 missed_returns 추적 — WARN
- **결과**: missed_opportunities=0

### ℹ️ H3 🟢 미진입 상승 TOP10 — INFO
- **결과**: top10_count=0

### ⚠️ I1 🟠 false_positive 분석 — WARN
- **결과**: no daily_trade_summary

### ❌ I2 🔴 daily_review_reports — FAIL
- **결과**: no row

### ⚠️ I3 🟠 learning_memories 생성 — WARN
- **결과**: total=0

### ❌ J1 🟠 daily_trade_summary — FAIL
- **결과**: no row

### ✅ K1 🟠 활성 learning_memories — PASS
- **결과**: active_total=97
- **증거**:
  - `{'scope': 'S3_UNIVERSE_FILTER', 'cnt': 4}`
  - `{'scope': 'S4_HYBRID_SCREENING', 'cnt': 80}`
  - `{'scope': 'S5_DAILY_PLAN', 'cnt': 13}`

### ℹ️ L1 🔴 7일 review 동작 — INFO
- **결과**: days_with_report=5
- **증거**:
  - `{'d': '2026-05-25', 'cnt': 1}`
  - `{'d': '2026-05-24', 'cnt': 1}`
  - `{'d': '2026-05-22', 'cnt': 1}`
  - `{'d': '2026-05-21', 'cnt': 1}`
  - `{'d': '2026-05-20', 'cnt': 1}`

### ⚠️ L2 🟠 7일 missed 추적률 — WARN
- **결과**: days_with_low_tracking=4/7
- **증거**:
  - `{'trade_date': '2026-05-26', 'total': 53, 'tracked': 50}`
  - `{'trade_date': '2026-05-25', 'total': 26, 'tracked': 26}`
  - `{'trade_date': '2026-05-24', 'total': 27, 'tracked': 0}`
  - `{'trade_date': '2026-05-23', 'total': 29, 'tracked': 0}`
  - `{'trade_date': '2026-05-22', 'total': 38, 'tracked': 35}`
  - `{'trade_date': '2026-05-21', 'total': 28, 'tracked': 0}`
  - `{'trade_date': '2026-05-20', 'total': 25, 'tracked': 0}`

### ⚠️ L4 🟡 7일 매수 신호 추세 — WARN
- **결과**: avg_buys_per_day=2.7, days=3
- **증거**:
  - `{'trade_date': '2026-05-26', 'cnt': 3}`
  - `{'trade_date': '2026-05-22', 'cnt': 4}`
  - `{'trade_date': '2026-05-20', 'cnt': 1}`

### ⚠️ L5 🟡 missed/매수 비율 (보수성) — WARN
- **결과**: missed=226, buys=8, ratio=28.2
