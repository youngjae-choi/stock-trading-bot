# EOD 검증 리포트 — 2026-05-27

- 생성: 2026-05-27T18:30:01.881505+09:00
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
- **결과**: recent_job_executions=21

### ✅ M2 🟠 silent failure 로그 스캔 — PASS
- **결과**: recent_errors=0

### ℹ️ C1 🔴 schedule_skip_today — INFO
- **결과**: value=false

### ✅ B1 🔴 S2 아침 실행 — PASS
- **결과**: tone=positive, conf=0.82, provider=anthropic
- **증거**:
  - `{'trade_date': '2026-05-27', 'tone': 'positive', 'confidence': 0.82, 'summary': '미국·유럽 동반 강세, SOX 7%대 급등, VIX 17대로 리스크온 환경', 'provider': 'anthropic', 'created_at': '2026-05-27T00:01:23.824Z'}`

### ✅ B2 🟠 야간 데이터 핵심 키 — PASS
- **결과**: missing=[], present=['kospi', 'nasdaq', 'sp500', 'usdkrw', 'vix']

### ✅ C2 🔴 S3 Universe Filter — PASS
- **결과**: raw=55, filtered=32
- **증거**:
  - `{'trade_date': '2026-05-27', 'raw_count': 55, 'filtered_count': 32, 'created_at': '2026-05-27T00:01:27.885Z'}`

### ✅ C3 🔴 S4 Hybrid Screening — PASS
- **결과**: output=8, conf=0.55, provider=anthropic
- **증거**:
  - `{'trade_date': '2026-05-27', 'output_count': 8, 'overall_confidence': 0.55, 'provider': 'anthropic', 'created_at': '2026-05-27T00:02:27.917Z'}`

### ✅ C4 🔴 S5 Daily Plan — PASS
- **결과**: intensity=aggressive, assignments=8, tone=positive
- **증거**:
  - `{'trade_date': '2026-05-27', 'market_tone': 'positive', 'trading_intensity': 'aggressive', 'assignments': 8, 'new_entry_allowed': 1, 'created_at': '2026-05-27T00:02:46.585Z'}`

### ✅ E1 🟠 장중 슬롯 5건 실행 — PASS
- **결과**: executed=5/5, missing=[]
- **증거**:
  - `{'slot': '09:30', 'ran': True, 'triggered': False, 'avg_change': 4.62, 'reason': 'sector_sample_insufficient'}`
  - `{'slot': '10:30', 'ran': True, 'triggered': False, 'avg_change': 4.91, 'reason': 'sector_sample_insufficient'}`
  - `{'slot': '11:30', 'ran': True, 'triggered': False, 'avg_change': 3.85, 'reason': 'sector_sample_insufficient'}`
  - `{'slot': '13:00', 'ran': True, 'triggered': False, 'avg_change': None, 'reason': 'no_items'}`
  - `{'slot': '14:00', 'ran': True, 'triggered': False, 'avg_change': 1.04, 'reason': 'sector_sample_insufficient'}`

### ⚠️ E2 🟠 매 슬롯 S2 장중 실행 — WARN
- **결과**: morning_context_rows=1 (expected ≥6 = 아침1 + 슬롯5)

### ⚠️ E3 🟡 슬롯 스냅샷 KIS 지수 — WARN
- **결과**: non_zero_kospi_count=0/1
- **증거**:
  - `{'created_at': '2026-05-27T05:00:28.313Z', 'kospi': None, 'kosdaq': None}`

### ✅ E4 🟡 sector_rotation — PASS
- **결과**: rows=4, insufficient=0
- **증거**:
  - `{'slot': '09:30', 'top_sectors': '[]', 'bottom_sectors': '[]', 'gap_pct': 0.0, 'triggered': 0}`
  - `{'slot': '10:30', 'top_sectors': '[]', 'bottom_sectors': '[]', 'gap_pct': 0.0, 'triggered': 0}`
  - `{'slot': '11:30', 'top_sectors': '[]', 'bottom_sectors': '[]', 'gap_pct': 0.0, 'triggered': 0}`
  - `{'slot': '14:00', 'top_sectors': '[]', 'bottom_sectors': '[]', 'gap_pct': 0.0, 'triggered': 0}`

### ⚠️ F1 🟠 매수 신호 발행 — WARN
- **결과**: buy_signals=0

### ℹ️ F2 🟠 주문 체결 분포 — INFO
- **결과**: {}

### ✅ G1 🔴 S9 EOD 청산 — PASS
- **결과**: S9 statuses=['success']
- **증거**:
  - `{'step': 'S9', 'status': 'success', 'message': 'liquidation_completed', 'started_at': '2026-05-27T06:20:00.007318+00:00', 'finished_at': '2026-05-27T06:20:02.762306+00:00'}`

### ✅ G3 🔴 POSTPROCESS — PASS
- **결과**: statuses=['success'], msg=['S9~S10 completed']
- **증거**:
  - `{'step': 'POSTPROCESS', 'status': 'success', 'message': 'S9~S10 completed', 'started_at': '2026-05-27T06:20:00.002719+00:00'}`

### ✅ H1 🔴 missed_returns 추적 — PASS
- **결과**: total=45, tracked=45 (100.0%), improvements=3

### ℹ️ H3 🟢 미진입 상승 TOP10 — INFO
- **결과**: top10_count=10
- **증거**:
  - `{'symbol': '208710', 'symbol_name': '포톤', 'max_return_until_eod': 8.6085, 'missed_stage': 'S4_HYBRID_SCREENING', 'missed_reason': 'S4_SCREENING: 포톤: change_rate +19.61%로 max 6.0% 대폭 초과, 상한가 수준으로 추격 매수 리스크 극대'}`
  - `{'symbol': '252670', 'symbol_name': 'KODEX 200선물인버스2X', 'max_return_until_eod': 7.0588, 'missed_stage': 'S3_UNIVERSE_FILTER', 'missed_reason': 'S3_FILTER: 거래량/거래대금 0'}`
  - `{'symbol': '114800', 'symbol_name': 'KODEX 인버스', 'max_return_until_eod': 2.9683, 'missed_stage': 'S3_UNIVERSE_FILTER', 'missed_reason': 'S3_FILTER: 거래량/거래대금 0'}`
  - `{'symbol': 'Q570060', 'symbol_name': '한투 인버스2X금선물 ETN', 'max_return_until_eod': 1.8764, 'missed_stage': 'S4_HYBRID_SCREENING', 'missed_reason': 'S4_SCREENING: 한투 인버스2X금선물 ETN: 인버스 상품으로 positive 톤에서 금 인버스 근거 부족'}`
  - `{'symbol': '189690', 'symbol_name': '포시에스', 'max_return_until_eod': 1.8597, 'missed_stage': 'S4_HYBRID_SCREENING', 'missed_reason': 'S4_SCREENING: 포시에스: change_rate -2.28%로 하락 중이며 min 0.8% 미달'}`
  - `{'symbol': '115500', 'symbol_name': '케이씨에스', 'max_return_until_eod': 1.1819, 'missed_stage': 'S4_HYBRID_SCREENING', 'missed_reason': 'S4_SCREENING: 케이씨에스: change_rate -5.53%로 하락 중이며 롱 진입 부적합'}`
  - `{'symbol': '290130', 'symbol_name': 'RISE ESG사회책임투자', 'max_return_until_eod': 0.9289, 'missed_stage': 'S3_UNIVERSE_FILTER', 'missed_reason': 'S3_FILTER: 거래량/거래대금 0'}`
  - `{'symbol': '423170', 'symbol_name': 'SOL 글로벌AI반도체탑픽액티브', 'max_return_until_eod': 0.8574, 'missed_stage': 'S3_UNIVERSE_FILTER', 'missed_reason': 'S3_FILTER: 거래량/거래대금 0'}`
  - `{'symbol': 'Q550063', 'symbol_name': 'N2 인버스 레버리지 금 선물 ETN(H)', 'max_return_until_eod': 0.5797, 'missed_stage': 'S4_HYBRID_SCREENING', 'missed_reason': 'S4_SCREENING: N2 인버스 레버리지 금 선물 ETN(H): 인버스 상품으로 positive 톤에서 방향 불명확, change_rate +1.77%이나 금 인버스 근거 부족'}`
  - `{'symbol': 'Q530064', 'symbol_name': '삼성 인버스 2X 구리 선물 ETN(H)', 'max_return_until_eod': 0.428, 'missed_stage': 'S4_HYBRID_SCREENING', 'missed_reason': 'S4_SCREENING: 삼성 인버스 2X 구리 선물 ETN(H): 인버스 상품으로 positive 톤에서 롱 진입은 톤과 역방향'}`

### ✅ I1 🟠 false_positive 분석 — PASS
- **결과**: realized_pnl=0, fp_cases=0

### ✅ I2 🔴 daily_review_reports — PASS
- **결과**: trades=0, pnl=0.0, fp=0, memory=53, missed=53, pnl_status=no_orders
- **증거**:
  - `{'total_trades': 0, 'total_pnl': 0.0, 'false_positive_count': 0, 'memory_count': 53, 'missed_entries_count': 53, 'pnl_status': 'no_orders', 'created_at': '2026-05-27T15:20:32.804643+09:00'}`

### ✅ I3 🟠 learning_memories 생성 — PASS
- **결과**: total=53
- **증거**:
  - `{'scope': 'S3_UNIVERSE_FILTER', 'category': 'missed_entry', 'total': 23}`
  - `{'scope': 'S4_HYBRID_SCREENING', 'category': 'missed_entry', 'total': 22}`
  - `{'scope': 'S5_DAILY_PLAN', 'category': 'missed_entry', 'total': 8}`

### ✅ J1 🟠 daily_trade_summary — PASS
- **결과**: orders=0, pnl=0.0, status=no_orders, warnings=1
- **증거**:
  - `{'total_orders': 0, 'realized_pnl': 0.0, 'realized_pnl_pct': 0.0, 'symbols_traded': '[]', 'pnl_status': 'no_orders', 'integrity_warnings': '["청산 대상 외 전일 전략 잔여 포지션이 있습니다."]', 'created_at': '2026-05-27T15:20:32.772767+09:00'}`
  - `{'warn': '청산 대상 외 전일 전략 잔여 포지션이 있습니다.'}`

### ✅ K1 🟠 활성 learning_memories — PASS
- **결과**: active_total=150
- **증거**:
  - `{'scope': 'S3_UNIVERSE_FILTER', 'cnt': 27}`
  - `{'scope': 'S4_HYBRID_SCREENING', 'cnt': 102}`
  - `{'scope': 'S5_DAILY_PLAN', 'cnt': 21}`

### ℹ️ L1 🔴 7일 review 동작 — INFO
- **결과**: days_with_report=6
- **증거**:
  - `{'d': '2026-05-27', 'cnt': 1}`
  - `{'d': '2026-05-25', 'cnt': 1}`
  - `{'d': '2026-05-24', 'cnt': 1}`
  - `{'d': '2026-05-22', 'cnt': 1}`
  - `{'d': '2026-05-21', 'cnt': 1}`
  - `{'d': '2026-05-20', 'cnt': 1}`

### ⚠️ L2 🟠 7일 missed 추적률 — WARN
- **결과**: days_with_low_tracking=4/8
- **증거**:
  - `{'trade_date': '2026-05-27', 'total': 45, 'tracked': 45}`
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
- **결과**: missed=271, buys=8, ratio=33.9
