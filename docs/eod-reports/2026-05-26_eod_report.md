# EOD 검증 리포트 — 2026-05-26

- 생성: 2026-05-27T05:25:47.069586+09:00
- 거래일: YES (weekday + skip_today=false)
- 결과: PASS 16 / WARN 7 / FAIL 1 / SKIP 0 / INFO 5
- Critical FAIL: **1건** — 즉시 조치 필요

---

## 🔴 Critical FAIL 요약
- **G3**: POSTPROCESS → statuses=['failed'], msg=["postprocess failed: name 'asyncio' is not defined"]

---

## 전체 검증 결과

### ✅ A1 🔴 서버 프로세스 + health — PASS
- **결과**: pids=['813086'], health=200

### ℹ️ A2 🔴 서버 시작 시간 vs 코드 커밋 — INFO
- **결과**: server_started=Tue May 26 20:21:42 2026 | scheduler.py last_commit=2026-05-26T08:17:57+00:00

### ⚠️ A3 🟠 APScheduler 등록 job — WARN
- **결과**: recent_job_executions=0

### ✅ M2 🟠 silent failure 로그 스캔 — PASS
- **결과**: recent_errors=0

### ℹ️ C1 🔴 schedule_skip_today — INFO
- **결과**: value=false

### ✅ B1 🔴 S2 아침 실행 — PASS
- **결과**: tone=mixed, conf=0.68, provider=anthropic
- **증거**:
  - `{'trade_date': '2026-05-26', 'tone': 'mixed', 'confidence': 0.68, 'summary': '미·유럽 상승+VIX 16대로 risk_on이나, 원유 급락·삼성전자 약세가 혼조 요인', 'provider': 'anthropic', 'created_at': '2026-05-26T00:01:22.031Z'}`

### ✅ B2 🟠 야간 데이터 핵심 키 — PASS
- **결과**: missing=[], present=['kospi', 'nasdaq', 'sp500', 'usdkrw', 'vix']

### ✅ C2 🔴 S3 Universe Filter — PASS
- **결과**: raw=59, filtered=37
- **증거**:
  - `{'trade_date': '2026-05-26', 'raw_count': 59, 'filtered_count': 37, 'created_at': '2026-05-26T02:30:07.249Z'}`

### ✅ C3 🔴 S4 Hybrid Screening — PASS
- **결과**: output=6, conf=0.45, provider=anthropic
- **증거**:
  - `{'trade_date': '2026-05-26', 'output_count': 6, 'overall_confidence': 0.45, 'provider': 'anthropic', 'created_at': '2026-05-26T02:31:03.396Z'}`

### ⚠️ C4 🔴 S5 Daily Plan — WARN
- **결과**: intensity=defensive, assignments=3, tone=mixed
- **증거**:
  - `{'trade_date': '2026-05-26', 'market_tone': 'mixed', 'trading_intensity': 'defensive', 'assignments': 3, 'new_entry_allowed': 1, 'created_at': '2026-05-26T02:31:18.617Z'}`

### ✅ E1 🟠 장중 슬롯 5건 실행 — PASS
- **결과**: executed=5/5, missing=[]
- **증거**:
  - `{'slot': '09:30', 'ran': True, 'triggered': False, 'avg_change': 2.6, 'reason': 'sector_sample_insufficient'}`
  - `{'slot': '10:30', 'ran': True, 'triggered': False, 'avg_change': 3.95, 'reason': 'sector_sample_insufficient'}`
  - `{'slot': '11:30', 'ran': True, 'triggered': True, 'avg_change': 3.92, 'reason': 'normal 플랜인데 시장 avg_change=+3.92% (>= ±3.0%)'}`
  - `{'slot': '13:00', 'ran': True, 'triggered': False, 'avg_change': 4.36, 'reason': 'sector_sample_insufficient'}`
  - `{'slot': '14:00', 'ran': True, 'triggered': False, 'avg_change': 3.61, 'reason': 'sector_sample_insufficient'}`

### ⚠️ E2 🟠 매 슬롯 S2 장중 실행 — WARN
- **결과**: morning_context_rows=1 (expected ≥6 = 아침1 + 슬롯5)

### ⚠️ E3 🟡 슬롯 스냅샷 KIS 지수 — WARN
- **결과**: non_zero_kospi_count=0/1
- **증거**:
  - `{'created_at': '2026-05-26T00:01:22.031Z', 'kospi': None, 'kosdaq': None}`

### ✅ E4 🟡 sector_rotation — PASS
- **결과**: rows=6, insufficient=0
- **증거**:
  - `{'slot': '09:30', 'top_sectors': '[]', 'bottom_sectors': '[]', 'gap_pct': 0.0, 'triggered': 0}`
  - `{'slot': '10:30', 'top_sectors': '[]', 'bottom_sectors': '[]', 'gap_pct': 0.0, 'triggered': 0}`
  - `{'slot': '11:30', 'top_sectors': '[]', 'bottom_sectors': '[]', 'gap_pct': 0.0, 'triggered': 0}`
  - `{'slot': '13:00', 'top_sectors': '[]', 'bottom_sectors': '[]', 'gap_pct': 0.0, 'triggered': 0}`
  - `{'slot': '14:00', 'top_sectors': '[]', 'bottom_sectors': '[]', 'gap_pct': 0.0, 'triggered': 0}`
  - `{'slot': 'TEST', 'top_sectors': '[{"sector": "전기전자", "avg_change": 4.95, "count": 2}, {"sector": "운수장비", "avg_change": 4.9, "count": 1}]', 'bottom_sectors': '[{"sector": "서비스업", "avg_change": 1.2, "count": 1}, {"sector": "전기장비", "avg_change": -0.1, "count": 1}, {"sector": "의약품", "avg_change": -1.5, "count": 1}]', 'gap_pct': 5.06, 'triggered': 1}`

### ✅ F1 🟠 매수 신호 발행 — PASS
- **결과**: buy_signals=3

### ℹ️ F2 🟠 주문 체결 분포 — INFO
- **결과**: {"buy/filled": 1, "sell/submitted": 1}
- **증거**:
  - `{'side': 'buy', 'status': 'filled', 'cnt': 1}`
  - `{'side': 'sell', 'status': 'submitted', 'cnt': 1}`

### ✅ G1 🔴 S9 EOD 청산 — PASS
- **결과**: S9 statuses=['success']
- **증거**:
  - `{'step': 'S9', 'status': 'success', 'message': 'liquidation_completed', 'started_at': '2026-05-26T06:20:00.007385+00:00', 'finished_at': '2026-05-26T06:20:13.579660+00:00'}`

### ❌ G3 🔴 POSTPROCESS — FAIL
- **결과**: statuses=['failed'], msg=["postprocess failed: name 'asyncio' is not defined"]
- **증거**:
  - `{'step': 'POSTPROCESS', 'status': 'failed', 'message': "postprocess failed: name 'asyncio' is not defined", 'started_at': '2026-05-26T06:20:00.001864+00:00'}`

### ✅ H1 🔴 missed_returns 추적 — PASS
- **결과**: total=53, tracked=50 (94.3%), improvements=5

### ℹ️ H3 🟢 미진입 상승 TOP10 — INFO
- **결과**: top10_count=10
- **증거**:
  - `{'symbol': '457370', 'symbol_name': '한켐', 'max_return_until_eod': 11.706, 'missed_stage': 'S4_HYBRID_SCREENING', 'missed_reason': 'S4_SCREENING: change_rate +16.37%로 max 5.0% 대폭 초과, 종목 정보 부족'}`
  - `{'symbol': 'Q520057', 'symbol_name': '미래에셋 인버스 2X 코스닥150 선물 ETN', 'max_return_until_eod': 4.596, 'missed_stage': 'S4_HYBRID_SCREENING', 'missed_reason': 'S4_SCREENING: 미래에셋 인버스 2X 코스닥150 선물 ETN: 인버스 2X ETN으로 risk_on regime에서 롱 진입 부적합, change_rate -6.58%로 하락 방향'}`
  - `{'symbol': '356680', 'symbol_name': '엑스게이트', 'max_return_until_eod': 4.1588, 'missed_stage': 'S4_HYBRID_SCREENING', 'missed_reason': 'S4_SCREENING: change_rate +24.76%로 max 5.0% 대폭 초과, 상한가 수준 추격 매수 리스크 극대; 전일에도 +11.13%로 max 초과 missed_entry 이력'}`
  - `{'symbol': 'Q530107', 'symbol_name': '삼성 인버스 2X 코스닥150 선물 ETN', 'max_return_until_eod': 4.0149, 'missed_stage': 'S4_HYBRID_SCREENING', 'missed_reason': 'S4_SCREENING: 삼성 인버스 2X 코스닥150 선물 ETN: 인버스 2X ETN으로 risk_on regime에서 롱 진입 부적합, change_rate -6.34%로 하락 방향'}`
  - `{'symbol': '251340', 'symbol_name': 'KODEX 코스닥150선물인버스', 'max_return_until_eod': 2.1399, 'missed_stage': 'S4_HYBRID_SCREENING', 'missed_reason': 'S4_SCREENING: KODEX 코스닥150선물인버스: 인버스 ETF로 risk_on regime에서 롱 진입 부적합, change_rate -3.23%로 하락 방향이며 운영 메모리에서 반복 제외 이력'}`
  - `{'symbol': 'Q530107', 'symbol_name': '삼성 인버스 2X 코스닥150 선물 ETN', 'max_return_until_eod': 1.5977, 'missed_stage': 'S4_HYBRID_SCREENING', 'missed_reason': 'S4_SCREENING: 인버스 2X ETN으로 mixed(risk_on 기조) 톤에서 인버스 롱 진입 근거 부족; 운영 메모리에서도 반복 제외 이력'}`
  - `{'symbol': '250780', 'symbol_name': 'TIGER 코스닥150선물인버스', 'max_return_until_eod': 1.0747, 'missed_stage': 'S3_UNIVERSE_FILTER', 'missed_reason': 'S3_FILTER: 거래량/거래대금 0'}`
  - `{'symbol': '252670', 'symbol_name': 'KODEX 200선물인버스2X', 'max_return_until_eod': 1.0526, 'missed_stage': 'S4_HYBRID_SCREENING', 'missed_reason': 'S4_SCREENING: KODEX 200선물인버스2X: 인버스 2X ETF로 시장톤 mixed/regime risk_on 환경에서 롱 진입 근거 부족, change_rate -6.86%로 하락 방향이며 운영 메모리에서 반복 제외 이력'}`
  - `{'symbol': '252670', 'symbol_name': 'KODEX 200선물인버스2X', 'max_return_until_eod': 1.0526, 'missed_stage': 'S3_UNIVERSE_FILTER', 'missed_reason': 'S3_FILTER: 거래량/거래대금 0'}`
  - `{'symbol': '251340', 'symbol_name': 'KODEX 코스닥150선물인버스', 'max_return_until_eod': 0.9283, 'missed_stage': 'S3_UNIVERSE_FILTER', 'missed_reason': 'S3_FILTER: 거래량/거래대금 0'}`

### ✅ I1 🟠 false_positive 분석 — PASS
- **결과**: realized_pnl=0, fp_cases=0

### ✅ I2 🔴 daily_review_reports — PASS
- **결과**: trades=0, pnl=0.0, fp=0, memory=4, missed=4, pnl_status=no_orders
- **증거**:
  - `{'total_trades': 0, 'total_pnl': 0.0, 'false_positive_count': 0, 'memory_count': 4, 'missed_entries_count': 4, 'pnl_status': 'no_orders', 'created_at': '2026-05-26T01:48:16.442285+09:00'}`

### ✅ I3 🟠 learning_memories 생성 — PASS
- **결과**: total=4
- **증거**:
  - `{'scope': 'S4_HYBRID_SCREENING', 'category': 'missed_entry', 'total': 4}`

### ✅ J1 🟠 daily_trade_summary — PASS
- **결과**: orders=2, pnl=0.0, status=unverified, warnings=2
- **증거**:
  - `{'total_orders': 2, 'realized_pnl': 0.0, 'realized_pnl_pct': 0.0, 'symbols_traded': '["469150"]', 'pnl_status': 'unverified', 'integrity_warnings': '["체결/손익 검증 미완료: submitted 주문에 대응하는 fills 기록이 없습니다.","청산 대상 외 전일 전략 잔여 포지션이 있습니다."]', 'created_at': '2026-05-26T18:00:00.011004+09:00'}`
  - `{'warn': '체결/손익 검증 미완료: submitted 주문에 대응하는 fills 기록이 없습니다.'}`
  - `{'warn': '청산 대상 외 전일 전략 잔여 포지션이 있습니다.'}`

### ✅ K1 🟠 활성 learning_memories — PASS
- **결과**: active_total=126
- **증거**:
  - `{'scope': 'S3_UNIVERSE_FILTER', 'cnt': 4}`
  - `{'scope': 'S4_HYBRID_SCREENING', 'cnt': 105}`
  - `{'scope': 'S5_DAILY_PLAN', 'cnt': 17}`

### ℹ️ L1 🔴 7일 review 동작 — INFO
- **결과**: days_with_report=6
- **증거**:
  - `{'d': '2026-05-25', 'cnt': 1}`
  - `{'d': '2026-05-24', 'cnt': 1}`
  - `{'d': '2026-05-22', 'cnt': 1}`
  - `{'d': '2026-05-21', 'cnt': 1}`
  - `{'d': '2026-05-20', 'cnt': 1}`
  - `{'d': '2026-05-19', 'cnt': 1}`

### ⚠️ L2 🟠 7일 missed 추적률 — WARN
- **결과**: days_with_low_tracking=5/8
- **증거**:
  - `{'trade_date': '2026-05-26', 'total': 53, 'tracked': 50}`
  - `{'trade_date': '2026-05-25', 'total': 26, 'tracked': 26}`
  - `{'trade_date': '2026-05-24', 'total': 27, 'tracked': 0}`
  - `{'trade_date': '2026-05-23', 'total': 29, 'tracked': 0}`
  - `{'trade_date': '2026-05-22', 'total': 38, 'tracked': 35}`
  - `{'trade_date': '2026-05-21', 'total': 28, 'tracked': 0}`
  - `{'trade_date': '2026-05-20', 'total': 25, 'tracked': 0}`
  - `{'trade_date': '2026-05-19', 'total': 26, 'tracked': 0}`

### ⚠️ L4 🟡 7일 매수 신호 추세 — WARN
- **결과**: avg_buys_per_day=2.5, days=4
- **증거**:
  - `{'trade_date': '2026-05-26', 'cnt': 3}`
  - `{'trade_date': '2026-05-22', 'cnt': 4}`
  - `{'trade_date': '2026-05-20', 'cnt': 1}`
  - `{'trade_date': '2026-05-19', 'cnt': 2}`

### ⚠️ L5 🟡 missed/매수 비율 (보수성) — WARN
- **결과**: missed=252, buys=10, ratio=25.2
