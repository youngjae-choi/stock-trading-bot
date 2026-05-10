# 계좌 전체 시간청산 정책 반영 — 테스트결과서

## 대상
- 관리자 지정 청산 시간/S9 청산 정책을 `KIS 계좌 실보유 전체 전량 시장가 매도`로 변경
- Trading Monitor에 손절/트레일링 감시 상태와 별도로 `시간청산 대상` 표시

## 정책 결론
- 손절/트레일링은 S8 관리 포지션 기준으로 동작한다.
- 관리자 지정 청산 시간에는 수동/장기/이월/봇 매수 여부를 구분하지 않고 KIS 계좌 실보유 전체를 전량 시장가 매도 대상으로 삼는다.
- 오늘은 비거래일이므로 실제 매도 주문은 실행하지 않았다.

## 구현 요약
- `run_eod_liquidation()`이 KIS 잔고를 우선 조회해 positive qty 보유종목 전체를 시장가 매도 대상으로 사용한다.
- 기존 중복 매도 방지(`find_active_sell_order`)는 유지한다.
- KIS 잔고 조회 실패 시에만 기존 S8/DB 포지션 fallback을 사용하고 `account_lookup_failed`를 결과에 남긴다.
- Trading Monitor API는 모든 KIS 보유 종목에 `timed_liquidation_target=true`, `timed_liquidation_status=시간청산 대상`을 내려준다.
- Trading Monitor UI는 자동감시 배지와 함께 `시간청산 대상` 배지를 표시한다.

## 실행한 테스트
| 구분 | 명령 | 결과 |
|---|---|---|
| Python 단위 테스트 | `python3 -m unittest tests.unit.test_position_monitoring` | PASS, 8 tests |
| Python 컴파일 | `python3 -m py_compile backend/services/engine/eod_liquidation.py backend/api/routes/trading_monitor.py tests/unit/test_position_monitoring.py` | PASS |
| JavaScript 문법 | `node --check backend/static/js/screens/console-trading-monitor.js` | PASS |
| Playwright 콘솔 회귀 | `npx playwright test tests/e2e/status-truth.spec.cjs --reporter=list` | PASS, 9 tests |
| LSP 진단 | 변경 파일 error 진단 | PASS, error 0 |

## 확인된 시나리오
- S8/PositionManager 소유 여부와 무관하게 KIS 실보유 2종목이 S9 청산 대상이 된다.
- 각 청산 대상은 `price=0`, `reason=eod`로 시장가 매도 호출된다.
- Trading Monitor에서 미감시 종목도 `시간청산 대상`으로 보인다.
- 기존 자동감시/미감시/상태불일치 표시와 시간청산 대상 표시가 동시에 유지된다.

## 남은 위험
- KIS 잔고 조회가 실패하면 계좌 전체 기준이 아니라 기존 S8/DB fallback 기준으로 청산을 시도한다.
- 비거래일/장외 시간에 실제 API 호출 시 증권사 API가 주문을 거절할 수 있다. 실제 실행은 거래일/장중 최종 승인 후 진행해야 한다.
