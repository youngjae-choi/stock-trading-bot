# EOD 검증 리포트 — 2026-05-28

- 생성: 2026-05-28T18:30:01.541767+09:00
- 거래일: YES (weekday + skip_today=false)
- 결과: PASS 18 / WARN 6 / FAIL 0 / SKIP 0 / INFO 5
- Critical FAIL: **0건**

---

## 전체 검증 결과

### ✅ A1 🔴 서버 프로세스 + health — PASS
- **결과**: pids=['813086'], health=200

### ℹ️ A2 🔴 서버 시작 시간 vs 코드 커밋 — INFO
- **결과**: server_started=Tue May 26 20:22:28 2026 | scheduler.py last_commit=2026-05-26T08:17:57+00:00

### ✅ A3 🟠 APScheduler 등록 job — PASS
- **결과**: recent_job_executions=42

### ✅ M2 🟠 silent failure 로그 스캔 — PASS
- **결과**: recent_errors=0

### ℹ️ C1 🔴 schedule_skip_today — INFO
- **결과**: value=false

### ✅ B1 🔴 S2 아침 실행 — PASS
- **결과**: tone=mixed, conf=0.72, provider=anthropic
- **증거**:
  - `{'trade_date': '2026-05-28', 'tone': 'mixed', 'confidence': 0.72, 'summary': '미국 기술·반도체 강세+VIX 하락으로 위험선호, 다만 중국·에너지 약세 혼조', 'provider': 'anthropic', 'created_at': '2026-05-28T00:01:22.667Z'}`

### ✅ B2 🟠 야간 데이터 핵심 키 — PASS
- **결과**: missing=[], present=['kospi', 'nasdaq', 'sp500', 'usdkrw', 'vix']

### ✅ C2 🔴 S3 Universe Filter — PASS
- **결과**: raw=55, filtered=32
- **증거**:
  - `{'trade_date': '2026-05-28', 'raw_count': 55, 'filtered_count': 32, 'created_at': '2026-05-28T01:30:30.366Z'}`

### ✅ C3 🔴 S4 Hybrid Screening — PASS
- **결과**: output=5, conf=0.52, provider=anthropic
- **증거**:
  - `{'trade_date': '2026-05-28', 'output_count': 5, 'overall_confidence': 0.52, 'provider': 'anthropic', 'created_at': '2026-05-28T01:31:18.815Z'}`

### ⚠️ C4 🔴 S5 Daily Plan — WARN
- **결과**: intensity=normal, assignments=4, tone=positive
- **증거**:
  - `{'trade_date': '2026-05-28', 'market_tone': 'positive', 'trading_intensity': 'normal', 'assignments': 4, 'new_entry_allowed': 1, 'created_at': '2026-05-28T01:31:37.656Z'}`

### ✅ E1 🟠 장중 슬롯 5건 실행 — PASS
- **결과**: executed=5/5, missing=[]
- **증거**:
  - `{'slot': '09:30', 'ran': True, 'triggered': True, 'avg_change': 5.58, 'reason': 'neutral 플랜인데 시장 avg_change=+5.58% (>= ±3.0%)'}`
  - `{'slot': '10:30', 'ran': True, 'triggered': True, 'avg_change': 2.52, 'reason': 'defensive 플랜인데 시장 avg_change=+2.52% (>= +2.0%)'}`
  - `{'slot': '11:30', 'ran': True, 'triggered': False, 'avg_change': 1.66, 'reason': 'sector_sample_insufficient'}`
  - `{'slot': '13:00', 'ran': True, 'triggered': False, 'avg_change': -0.84, 'reason': 'sector_sample_insufficient'}`
  - `{'slot': '14:00', 'ran': True, 'triggered': False, 'avg_change': -0.7, 'reason': 'sector_sample_insufficient'}`

### ⚠️ E2 🟠 매 슬롯 S2 장중 실행 — WARN
- **결과**: morning_context_rows=1 (expected ≥6 = 아침1 + 슬롯5)

### ⚠️ E3 🟡 슬롯 스냅샷 KIS 지수 — WARN
- **결과**: non_zero_kospi_count=0/1
- **증거**:
  - `{'created_at': '2026-05-28T05:00:38.872Z', 'kospi': None, 'kosdaq': None}`

### ✅ E4 🟡 sector_rotation — PASS
- **결과**: rows=5, insufficient=0
- **증거**:
  - `{'slot': '09:30', 'top_sectors': '[]', 'bottom_sectors': '[]', 'gap_pct': 0.0, 'triggered': 0}`
  - `{'slot': '10:30', 'top_sectors': '[]', 'bottom_sectors': '[]', 'gap_pct': 0.0, 'triggered': 0}`
  - `{'slot': '11:30', 'top_sectors': '[]', 'bottom_sectors': '[]', 'gap_pct': 0.0, 'triggered': 0}`
  - `{'slot': '13:00', 'top_sectors': '[]', 'bottom_sectors': '[]', 'gap_pct': 0.0, 'triggered': 0}`
  - `{'slot': '14:00', 'top_sectors': '[]', 'bottom_sectors': '[]', 'gap_pct': 0.0, 'triggered': 0}`

### ⚠️ F1 🟠 매수 신호 발행 — WARN
- **결과**: buy_signals=0

### ℹ️ F2 🟠 주문 체결 분포 — INFO
- **결과**: {}

### ✅ G1 🔴 S9 EOD 청산 — PASS
- **결과**: S9 statuses=['success']
- **증거**:
  - `{'step': 'S9', 'status': 'success', 'message': 'liquidation_completed', 'started_at': '2026-05-28T06:20:00.004576+00:00', 'finished_at': '2026-05-28T06:20:03.777584+00:00'}`

### ✅ G3 🔴 POSTPROCESS — PASS
- **결과**: statuses=['success'], msg=['S9~S10 completed']
- **증거**:
  - `{'step': 'POSTPROCESS', 'status': 'success', 'message': 'S9~S10 completed', 'started_at': '2026-05-28T06:20:00.001887+00:00'}`

### ✅ H1 🔴 missed_returns 추적 — PASS
- **결과**: total=98, tracked=92 (93.9%), improvements=15

### ℹ️ H3 🟢 미진입 상승 TOP10 — INFO
- **결과**: top10_count=10
- **증거**:
  - `{'symbol': '024800', 'symbol_name': '유성티엔에스', 'max_return_until_eod': 8.7273, 'missed_stage': 'S4_HYBRID_SCREENING', 'missed_reason': 'S4_SCREENING: change_rate +19.44%로 max 6.0% 대폭 초과, 상한가 수준'}`
  - `{'symbol': '131400', 'symbol_name': '이브이첨단소재', 'max_return_until_eod': 6.1606, 'missed_stage': 'S4_HYBRID_SCREENING', 'missed_reason': 'S4_SCREENING: change_rate +22.42%로 max 5.0% 대폭 초과, 상한가 수준'}`
  - `{'symbol': '0194R0', 'symbol_name': 'KIWOOM SK하이닉스선물단일종목레버리지', 'max_return_until_eod': 3.9816, 'missed_stage': 'S3_UNIVERSE_FILTER', 'missed_reason': 'S3_FILTER: 거래량/거래대금 0'}`
  - `{'symbol': '0197W0', 'symbol_name': 'SOL SK하이닉스단일종목레버리지', 'max_return_until_eod': 3.8437, 'missed_stage': 'S3_UNIVERSE_FILTER', 'missed_reason': 'S3_FILTER: 거래량/거래대금 0'}`
  - `{'symbol': '0194T0', 'symbol_name': 'ACE SK하이닉스단일종목레버리지', 'max_return_until_eod': 3.8155, 'missed_stage': 'S3_UNIVERSE_FILTER', 'missed_reason': 'S3_FILTER: 거래량/거래대금 0'}`
  - `{'symbol': '0198D0', 'symbol_name': '1Q SK하이닉스선물단일종목레버리지', 'max_return_until_eod': 3.7923, 'missed_stage': 'S4_HYBRID_SCREENING', 'missed_reason': 'S4_SCREENING: change_rate -0.24%로 min 1.0% 미달, 레버리지 선물 단일종목 상품'}`
  - `{'symbol': '0193T0', 'symbol_name': 'KODEX SK하이닉스단일종목레버리지', 'max_return_until_eod': 3.7017, 'missed_stage': 'S3_UNIVERSE_FILTER', 'missed_reason': 'S3_FILTER: 거래량/거래대금 0'}`
  - `{'symbol': '0195S0', 'symbol_name': 'TIGER SK하이닉스단일종목레버리지', 'max_return_until_eod': 3.668, 'missed_stage': 'S3_UNIVERSE_FILTER', 'missed_reason': 'S3_FILTER: 거래량/거래대금 0'}`
  - `{'symbol': '0192L0', 'symbol_name': 'RISE SK하이닉스단일종목레버리지', 'max_return_until_eod': 3.5142, 'missed_stage': 'S3_UNIVERSE_FILTER', 'missed_reason': 'S3_FILTER: 거래량/거래대금 0'}`
  - `{'symbol': 'Q700018', 'symbol_name': '하나 인버스 2X 코스닥150 선물 ETN', 'max_return_until_eod': 3.2194, 'missed_stage': 'S4_HYBRID_SCREENING', 'missed_reason': 'S4_SCREENING: 인버스 2X ETN으로 mixed 톤에서 인버스 롱 진입 근거 불명확, 운영 메모리에서 인버스 상품 톤 역방향 반복 제외 이력'}`

### ✅ I1 🟠 false_positive 분석 — PASS
- **결과**: realized_pnl=0, fp_cases=0

### ✅ I2 🔴 daily_review_reports — PASS
- **결과**: trades=0, pnl=0.0, fp=0, memory=106, missed=106, pnl_status=no_orders
- **증거**:
  - `{'total_trades': 0, 'total_pnl': 0.0, 'false_positive_count': 0, 'memory_count': 106, 'missed_entries_count': 106, 'pnl_status': 'no_orders', 'created_at': '2026-05-28T15:20:33.806545+09:00'}`

### ✅ I3 🟠 learning_memories 생성 — PASS
- **결과**: total=106
- **증거**:
  - `{'scope': 'S3_UNIVERSE_FILTER', 'category': 'missed_entry', 'total': 49}`
  - `{'scope': 'S4_HYBRID_SCREENING', 'category': 'missed_entry', 'total': 43}`
  - `{'scope': 'S5_DAILY_PLAN', 'category': 'missed_entry', 'total': 14}`

### ✅ J1 🟠 daily_trade_summary — PASS
- **결과**: orders=0, pnl=0.0, status=no_orders, warnings=1
- **증거**:
  - `{'total_orders': 0, 'realized_pnl': 0.0, 'realized_pnl_pct': 0.0, 'symbols_traded': '[]', 'pnl_status': 'no_orders', 'integrity_warnings': '["청산 대상 외 전일 전략 잔여 포지션이 있습니다."]', 'created_at': '2026-05-28T15:20:33.786478+09:00'}`
  - `{'warn': '청산 대상 외 전일 전략 잔여 포지션이 있습니다.'}`

### ✅ K1 🟠 활성 learning_memories — PASS
- **결과**: active_total=231
- **증거**:
  - `{'scope': 'S3_UNIVERSE_FILTER', 'cnt': 75}`
  - `{'scope': 'S4_HYBRID_SCREENING', 'cnt': 126}`
  - `{'scope': 'S5_DAILY_PLAN', 'cnt': 30}`

### ℹ️ L1 🔴 7일 review 동작 — INFO
- **결과**: days_with_report=6
- **증거**:
  - `{'d': '2026-05-28', 'cnt': 1}`
  - `{'d': '2026-05-27', 'cnt': 1}`
  - `{'d': '2026-05-25', 'cnt': 1}`
  - `{'d': '2026-05-24', 'cnt': 1}`
  - `{'d': '2026-05-22', 'cnt': 1}`
  - `{'d': '2026-05-21', 'cnt': 1}`

### ⚠️ L2 🟠 7일 missed 추적률 — WARN
- **결과**: days_with_low_tracking=3/8
- **증거**:
  - `{'trade_date': '2026-05-28', 'total': 98, 'tracked': 92}`
  - `{'trade_date': '2026-05-27', 'total': 45, 'tracked': 45}`
  - `{'trade_date': '2026-05-26', 'total': 53, 'tracked': 50}`
  - `{'trade_date': '2026-05-25', 'total': 26, 'tracked': 26}`
  - `{'trade_date': '2026-05-24', 'total': 27, 'tracked': 0}`
  - `{'trade_date': '2026-05-23', 'total': 29, 'tracked': 0}`
  - `{'trade_date': '2026-05-22', 'total': 38, 'tracked': 35}`
  - `{'trade_date': '2026-05-21', 'total': 28, 'tracked': 0}`

### ✅ L4 🟡 7일 매수 신호 추세 — PASS
- **결과**: avg_buys_per_day=3.5, days=2
- **증거**:
  - `{'trade_date': '2026-05-26', 'cnt': 3}`
  - `{'trade_date': '2026-05-22', 'cnt': 4}`

### ⚠️ L5 🟡 missed/매수 비율 (보수성) — WARN
- **결과**: missed=344, buys=7, ratio=49.1
