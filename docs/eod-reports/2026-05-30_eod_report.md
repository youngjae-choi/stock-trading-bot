# EOD 검증 리포트 — 2026-05-30

- 생성: 2026-05-30T18:30:01.278742+09:00
- 거래일: NO (weekend (wd=5))
- 결과: PASS 5 / WARN 2 / FAIL 0 / SKIP 0 / INFO 3
- Critical FAIL: **0건**

---

## 전체 검증 결과

### ✅ A1 🔴 서버 프로세스 + health — PASS
- **결과**: pids=['813086'], health=200

### ℹ️ A2 🔴 서버 시작 시간 vs 코드 커밋 — INFO
- **결과**: server_started=Tue May 26 20:22:28 2026 | scheduler.py last_commit=2026-05-26T08:17:57+00:00

### ✅ A3 🟠 APScheduler 등록 job — PASS
- **결과**: recent_job_executions=70

### ✅ M2 🟠 silent failure 로그 스캔 — PASS
- **결과**: recent_errors=0

### ℹ️ C1 🔴 schedule_skip_today — INFO
- **결과**: value=false

### ✅ K1 🟠 활성 learning_memories — PASS
- **결과**: active_total=163
- **증거**:
  - `{'scope': 'S3_UNIVERSE_FILTER', 'cnt': 72}`
  - `{'scope': 'S4_HYBRID_SCREENING', 'cnt': 69}`
  - `{'scope': 'S5_DAILY_PLAN', 'cnt': 22}`

### ℹ️ L1 🔴 7일 review 동작 — INFO
- **결과**: days_with_report=4
- **증거**:
  - `{'d': '2026-05-28', 'cnt': 1}`
  - `{'d': '2026-05-27', 'cnt': 1}`
  - `{'d': '2026-05-25', 'cnt': 1}`
  - `{'d': '2026-05-24', 'cnt': 1}`

### ⚠️ L2 🟠 7일 missed 추적률 — WARN
- **결과**: days_with_low_tracking=2/6
- **증거**:
  - `{'trade_date': '2026-05-28', 'total': 98, 'tracked': 92}`
  - `{'trade_date': '2026-05-27', 'total': 45, 'tracked': 45}`
  - `{'trade_date': '2026-05-26', 'total': 53, 'tracked': 50}`
  - `{'trade_date': '2026-05-25', 'total': 26, 'tracked': 26}`
  - `{'trade_date': '2026-05-24', 'total': 27, 'tracked': 0}`
  - `{'trade_date': '2026-05-23', 'total': 29, 'tracked': 0}`

### ✅ L4 🟡 7일 매수 신호 추세 — PASS
- **결과**: avg_buys_per_day=3.0, days=1
- **증거**:
  - `{'trade_date': '2026-05-26', 'cnt': 3}`

### ⚠️ L5 🟡 missed/매수 비율 (보수성) — WARN
- **결과**: missed=278, buys=3, ratio=92.7
