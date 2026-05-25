# OUTBOX: 백테스트 모듈 — pykrx 과거 데이터 기반

**날짜:** 2026-05-22  
**담당:** Codex / Executor  
**상태:** 구현 완료, 제한 환경 검증 완료

---

## 1. 작업 요약

`pykrx` 과거 OHLCV 데이터를 기반으로 현재 스크리닝형 조건을 적용하는 백테스트 서비스와 API 라우터를 추가했다.

인박스 스케치와 달리 현재 `hybrid_screening_results` 테이블에는 `symbol` 단일 컬럼이 없고 `candidates` JSON 컬럼만 확인되어, 최근 `candidates` JSON에서 `symbol/ticker/code`를 추출하는 방식으로 구현했다.

---

## 2. 변경 파일

- `backend/services/engine/backtest.py` 신규
  - 유니버스 추출
  - pykrx OHLCV 조회
  - RSI(14), 등락률, 거래량 비율 계산
  - 손절 / 트레일링 / 5봉 강제청산 시뮬레이션
  - 승률, 평균 수익률, 간이 Sharpe, MDD 요약
- `backend/api/routes/backtest.py` 신규
  - `POST /api/v1/backtest/run`
  - `GET /api/v1/backtest/quick`
  - `POST /api/v1/backtest/quick`
  - 인박스 완료 기준의 curl 예시는 `POST /quick`이나 작업 2 명세는 `GET /quick`이라 둘 다 지원하도록 처리
- `backend/main.py`
  - `backtest_router` import 및 `app.include_router(backtest_router)` 등록

---

## 3. 구현 세부 사항

- `pykrx 1.2.8` 설치 및 `stock.get_market_ohlcv`, `stock.get_market_cap` API 존재 확인.
- 모든 신규 함수에 목적과 파라미터 주석을 작성.
- 주요 흐름에 `START / SUCCESS / WARN / FAIL` 로그 추가.
- API 입력 날짜 오류는 `400`으로 변환하고, 예기치 않은 서버 오류는 내부 로그 후 일반 메시지로 `500` 처리.
- 거래가 0건이거나 유니버스 로딩이 실패해도 `total`, `win_rate_pct`, `avg_pnl_pct` 필드는 항상 포함되도록 처리.
- `quick` 백테스트는 최근 90일 기준이며 다음 설정을 사용:
  - `engine.min_price_change_pct`
  - `override_stop_loss_rate`
  - `override_trailing_activate_rate`
  - `override_trailing_stop_rate`

---

## 4. 검증 결과

### 통과

```bash
python -m py_compile backend/services/engine/backtest.py backend/api/routes/backtest.py backend/main.py
```

결과: 통과

```bash
python - <<'PY'
from backend.main import app
paths = sorted(route.path for route in app.routes if 'backtest' in route.path)
print('\n'.join(paths))
PY
```

결과:

```text
/api/v1/backtest/quick
/api/v1/backtest/quick
/api/v1/backtest/run
```

```bash
python - <<'PY'
from datetime import datetime
from unittest.mock import patch
import pandas as pd
from backend.services.engine.backtest import run_backtest

dates = pd.date_range(datetime(2026, 1, 1), periods=40, freq='D')
df = pd.DataFrame({'종가': [100 + i for i in range(40)], '거래량': [1000 + i * 10 for i in range(40)]}, index=dates)
with patch('backend.services.engine.backtest._get_universe_symbols', return_value=['005930']), patch('backend.services.engine.backtest._pykrx_ohlcv', return_value=df):
    result = run_backtest('2026-01-25', '2026-02-10', min_price_change_pct=0.0, max_price_change_pct=5.0, min_volume_ratio=0.0, min_rsi=0.0, max_rsi=100.0, universe_limit=1)
print({k: result.get(k) for k in ('total', 'win_rate_pct', 'avg_pnl_pct')})
print(result['trades'][0])
PY
```

결과:

```text
{'total': 16, 'win_rate_pct': 93.8, 'avg_pnl_pct': 3.126}
{'symbol': '005930', 'entry_date': '20260125', 'entry_price': 124.0, 'price_change_pct': 0.81, 'volume_ratio': 1.09, 'rsi14': 100.0, 'exit_idx': 29, 'exit_price': 129.0, 'pnl_pct': 4.032, 'exit_reason': 'force_exit', 'hold_bars': 5}
```

라우터 함수 단위 mock 검증:

- `POST /run` 응답에 `total`, `win_rate_pct`, `avg_pnl_pct`, `trades` 포함 확인
- `GET /quick` 응답에 동일 필드 포함 확인
- `POST /quick` 응답에 동일 필드 포함 확인

### 제한 / 미완료

실제 pykrx 네트워크 호출 검증은 현재 샌드박스의 DNS/네트워크 제한으로 실패했다.

제한 환경에서 실제 호출 시 응답 필드 형태:

```text
{'total': 0, 'win_rate_pct': 0, 'avg_pnl_pct': 0, 'message': '조건에 맞는 거래 없음', 'error': None}
trade_count 0
```

확인된 실패 로그:

```text
WARN: Backtest pykrx OHLCV failed symbol=009150 error=HTTPConnectionPool(host='fchart.stock.naver.com', port=80): Max retries exceeded ... NameResolutionError
```

따라서 인박스 완료 기준 중 아래 항목은 이 환경에서 실데이터로 확인하지 못했다.

- `curl -X POST "http://127.0.0.1:8000/api/v1/backtest/quick"` 실서버 호출
- 실제 pykrx 과거 데이터 기반 최소 1건 이상 trade 반환

---

## 5. 남은 리스크

- pykrx 데이터 호출은 외부 네트워크와 KRX/Naver 데이터 소스 상태에 의존한다.
- `pykrx` import 시 로컬 환경에서 `KRX_ID` / `KRX_PW` 미설정 경고가 출력됐다. 현재 사용한 OHLCV API 자체는 함수가 존재하지만, 운영 환경에서 pykrx 인증/접속 정책을 별도 확인해야 한다.
- 현재 RSI는 백테스트 모듈 내부 단순 RSI 계산이다. 실시간 S6에서 외부 tick에 포함되는 RSI와 계산 방식이 다르면 백테스트와 실거래 판정이 일부 달라질 수 있다.

---

## 6. 다음 추천 작업

1. 네트워크 가능한 개발 서버에서 `POST /api/v1/backtest/quick` 실데이터 curl 검증.
2. 백테스트 결과를 콘솔 화면에 표시하는 Frontend 작업.
3. S6 실시간 진입 조건과 백테스트 조건의 파라미터/지표 계산 방식을 한 곳에서 공유하도록 정리.
