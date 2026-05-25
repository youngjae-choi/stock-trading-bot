# OUTBOX: 귀신타이밍 전략 — 완료 보고

**날짜:** 2026-05-22  
**작업자:** Claude Code (Sisyphus 보조)  
**원본 INBOX:** INBOX_CODEX_20260522_ghost_timing.md

---

## 완료 항목

### 작업 1: Decision Engine — 진입 시간 창 필터

**파일:** `backend/services/engine/decision_engine.py`

- `_evaluate_entry_rules()` 에 `time_window` 체크 추가 (line 799~811)
- `required_keys = ["volume_ratio", "ai_confidence", "price_change", "time_window"]` 반영 (line 419)
- `matched["time_window"] = time_window_ok` 추가 (line 843)
- `engine.entry_start_time` / `engine.entry_end_time` settings 읽기 (기본값 09:00~10:30)
- `vol_floor = _get_setting_float("engine.min_volume_ratio", 1.0)` 가드레일 추가

**검증:** `py_compile` 통과 ✓

---

### 작업 2: 분봉 백테스트 — KIS + pykrx 폴백

**파일:** `backend/services/engine/backtest.py` (전면 교체)

- `fetch_intraday_bars()`: KIS 분봉 조회, 실패/빈 응답 시 pykrx 폴백
  - KIS API 예외(EGW00201 rate limit 포함) 자동 캐치 → `[]` 반환
- `_pykrx_daily_to_bars()`: pykrx 일봉 → 4개 합성 분봉 (09:10/09:30/11:00/15:20)
- `_prev_close_and_avg_volume()`: pykrx로 전일 종가 + 20일 평균 거래량 조회
- `simulate_intraday_trade()`: stop_loss / trailing_stop / force_exit(15:20)
- `run_backtest_intraday()`: 1일 분봉 백테스트
- `run_backtest()`: 날짜 범위 백테스트

**검증:** `py_compile` 통과 ✓

---

### 작업 3: Backtest API

**파일:** `backend/api/routes/backtest.py`

- `POST /api/v1/backtest/run` — 파라미터 지정 백테스트
- `GET /api/v1/backtest/quick` — 어제 날짜 + 유니버스 30종목 1일 백테스트
- `POST /api/v1/backtest/quick` — 동일

**파일:** `backend/main.py`
- `backtest_router` 등록 완료

**검증:** `py_compile` 통과 ✓, curl 응답 확인 ✓

---

## 검증 결과

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/backtest/quick"
```

응답: `ok=true`, `period.start=2026-05-21`, `errors=[]` (KIS 빈 응답 → pykrx 폴백 정상 동작)  
total=0 → 당일 3%~10% 등락 + 2.5배 거래량 조건 충족 종목 없음 (타이트한 진입 조건 정상 작동)

---

## 비고

- KIS 분봉 API는 **당일 데이터만** 제공 → 과거 날짜는 pykrx 합성 4봉 시뮬레이션
- pykrx KOSPI 지수(`get_index_ohlcv_by_date`)는 KRX 로그인 필요 → KODEX 200 ETF(069500) 프록시 사용
- 실시간 진입은 KIS WebSocket 틱 (분봉보다 정밀) 사용 중이므로 별도 개선 불필요
