# OUTBOX: S6 진입 시점 기술지표 스냅샷 저장

**날짜:** 2026-05-22  
**대상:** Codex (Backend)  
**상태:** 구현 완료, 로컬 검증 일부 제한

---

## 작업 요약

S6 BUY 신호 생성 시점의 기술지표를 `signal_technical_indicators` 테이블에 저장하도록 백엔드 경로를 추가했다.

### 변경 파일

- `backend/services/db.py`
  - `signal_technical_indicators` 테이블 추가
  - `idx_sti_symbol_date`, `idx_sti_signal_id` 인덱스 추가
- `backend/services/engine/technical_indicators.py`
  - 신규 파일
  - pykrx 기반 OHLCV 조회
  - RSI(14), 5일/20일 이평 대비, 5일 모멘텀, 거래량 비율, KOSPI 등락률 계산
  - BUY 신호별 지표 저장
  - 매도 완료 후 outcome 손익률/보유시간 업데이트
- `backend/services/engine/decision_engine.py`
  - `trading_signals` INSERT 직후 `save_signal_indicators()`를 executor로 백그라운드 실행
- `backend/services/engine/review_audit.py`
  - S10의 completed trade pair 동기화 시 `signal_technical_indicators.outcome_pnl_pct`, `outcome_hold_min` 업데이트
  - 날짜를 넘긴 보유 건을 고려해 최근 7일 trade pair 범위에서 당일 매도 완료 건을 처리

---

## 구현 메모

- KOSPI 지수는 pykrx의 `get_index_ohlcv_by_date(start, end, "1001")` 경로를 사용했다.
- `save_signal_indicators()`는 같은 `signal_id`가 이미 저장된 경우 중복 저장하지 않는다.
- 직접 서비스 호출이 앱 DB 초기화보다 먼저 실행되는 상황을 방어하기 위해 신규 서비스 내부에도 테이블 보장 함수를 추가했다.
- SQLite 쓰기 연결 중첩을 피하기 위해 S10 outcome 업데이트는 대상 signal을 먼저 수집한 뒤 별도 단계에서 실행한다.

---

## 검증 결과

### 통과

1. 문법 검사

```bash
python -m py_compile backend/services/db.py backend/services/engine/technical_indicators.py backend/services/engine/decision_engine.py backend/services/engine/review_audit.py
```

결과: 통과

2. DB 테이블 생성 확인

```bash
APP_DB_PATH=/tmp/stock_bot_signal_indicators_test.sqlite3 python - <<'PY'
from backend.services.db import initialize_database, get_connection
initialize_database()
with get_connection() as conn:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='signal_technical_indicators'").fetchone()
    cols = [r[1] for r in conn.execute('PRAGMA table_info(signal_technical_indicators)').fetchall()]
    indexes = [r[1] for r in conn.execute("PRAGMA index_list('signal_technical_indicators')").fetchall()]
print({'table': bool(row), 'cols': cols, 'indexes': indexes})
PY
```

결과: 테이블 생성 확인, 요청 컬럼 및 인덱스 확인

3. 외부망 의존 없는 계산/저장/업데이트 단위 검증

pykrx 조회 함수를 테스트 더블로 대체해 아래 항목을 확인했다.

- `calculate_indicators()` 계산 결과 생성
- `save_signal_indicators()` 저장 성공
- `update_signal_outcome()` outcome 업데이트 성공
- 저장 row의 `rsi14`, `volume_ratio`, `outcome_pnl_pct`, `outcome_hold_min` 확인

결과:

```text
{'signal_id': 'sig-1', 'symbol': '005930', 'trade_date': '2026-05-22', 'rsi14': 100.0, 'volume_ratio': 1.09, 'outcome_pnl_pct': 3.21, 'outcome_hold_min': 45.0}
```

4. S6 호출 위치 확인

```bash
rg -n "save_signal_indicators|signal_technical_indicators|update_signal_outcome" backend/services/db.py backend/services/engine/technical_indicators.py backend/services/engine/decision_engine.py backend/services/engine/review_audit.py
```

결과: `decision_engine.py`의 `trading_signals` INSERT 직후 호출 위치 확인

### 제한 / 실패

1. 실제 pykrx 라이브 조회

```bash
from backend.services.engine.technical_indicators import calculate_indicators
r = calculate_indicators("005930", "2026-05-22")
print(r)
```

결과: `{}`  
원인: 현재 실행 환경에서 외부 DNS/네트워크가 차단되어 `fchart.stock.naver.com`, `data.krx.co.kr` 조회 실패. 또한 KRX_ID/KRX_PW 환경변수가 없어 KRX 로그인 실패 메시지가 출력됨.

2. 전체 unit 테스트

```bash
pytest tests/unit -q
```

결과: `backend` import 경로 문제로 collection 실패

```bash
PYTHONPATH=. pytest tests/unit -q
```

결과: 15 passed, 1 failed  
실패 테스트: `tests/unit/test_position_monitoring.py::EODLiquidationPolicyTest::test_eod_liquidation_sells_all_kis_account_holdings`  
실패 원인: `eod_liquidation.execute_sell()` 호출에 기존 테스트 기대값에는 없는 `name=''` 인자가 포함됨. 이번 signal indicators 작업 범위와 직접 관련 없는 기존/병행 변경 영향으로 판단됨.

---

## 완료 기준 체크

- [x] `py_compile` 통과
- [x] `signal_technical_indicators` 테이블 생성 확인
- [x] `decision_engine.py`에서 `save_signal_indicators` 호출 위치 확인
- [x] 저장/결과 업데이트 경로 단위 검증
- [ ] 실제 pykrx 라이브 값 확인: 네트워크/KRX 환경변수 제한으로 미완료
- [ ] 전체 unit 테스트 100% 통과: unrelated EOD 테스트 실패 존재

---

## 남은 확인 필요

1. 실제 운영 환경에서 KRX/pykrx 조회가 가능한지 확인 필요
2. `KOSPI` 지수 조회에 필요한 KRX 계정 환경변수 또는 pykrx 설정 상태 확인 필요
3. 별도 작업으로 EOD liquidation 테스트 기대값과 현재 구현의 `name` 인자 변경을 정리할 필요 있음

---

## 다음 추천 작업

1. 운영 서버에서 `calculate_indicators("005930", 오늘 날짜)`를 외부망/KRX 환경변수 포함 상태로 재검증
2. S6 실제 BUY 신호 1건 발생 후 `signal_technical_indicators` row 생성 여부와 서버 로그 확인
3. EOD liquidation unit test 실패 원인을 별도 INBOX로 분리해 테스트 또는 구현 중 어느 쪽이 최신 계약인지 확정
