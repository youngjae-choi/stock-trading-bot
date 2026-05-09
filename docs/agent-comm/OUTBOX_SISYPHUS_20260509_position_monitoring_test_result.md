# 보유 포지션 자동감시 P0 수정 — 테스트결과서

## 대상
- 보유 포지션 손절/트레일링 미동작 원인 수정
- Trading Monitor 자동감시 상태 표시

## 구현 요약
- 전략 소유가 확인된 S8 포지션만 자동 손절/트레일링 감시 대상으로 유지한다.
- KIS-only 수동/이월 보유 종목은 자동 매도 대상으로 등록하지 않고 Trading Monitor에서 `미감시`로 표시한다.
- 이미 S8이 관리 중인 종목은 KIS 실제 잔고 수량으로 동기화해 과매도 위험을 줄인다.
- KIS 잔고에서 사라진 S8 포지션은 제거해 수동 전량매도 후 중복 매도 위험을 줄인다.
- 오늘 stop state 조회는 SQLite `date()` 대신 저장된 KST ISO 날짜 prefix로 필터링한다.
- 트레일링 활성화 상태는 고점 미갱신 상황에서도 DB에 저장되도록 보강했다.

## 실행한 테스트
| 구분 | 명령 | 결과 |
|---|---|---|
| Python 단위 테스트 | `python3 -m unittest tests.unit.test_position_monitoring` | PASS, 7 tests |
| Python 컴파일 | `python3 -m py_compile backend/services/engine/decision_engine.py backend/services/engine/position_manager.py backend/api/routes/trading_monitor.py tests/unit/test_position_monitoring.py` | PASS |
| JavaScript 문법 | `node --check backend/static/js/screens/console-trading-monitor.js` | PASS |
| Playwright 콘솔 회귀 | `npx playwright test tests/e2e/status-truth.spec.cjs --reporter=list` | PASS, 9 tests |
| LSP 진단 | 변경 Python/JS/테스트 파일 error 진단 | PASS, error 0 |
| Oracle 최종 안전 리뷰 | Final safety review | PASS |

## 확인된 시나리오
- KIS 실보유에는 있지만 S8 인메모리/실시간 구독 대상이 아닌 종목은 `미감시`로 분리 표시된다.
- S8 등록 + 실시간 구독이 모두 있는 종목만 `자동감시중`으로 분류된다.
- S8에는 있지만 실시간 구독이 빠진 종목은 `상태불일치`로 분류된다.
- +28% 같은 큰 수익 구간에서 트레일링 활성화가 고점 미갱신 상황이어도 저장된다.
- S8 관리 포지션의 실제 KIS 수량 감소가 반영된다.
- KIS 잔고에서 사라진 S8 포지션은 제거되어 과매도 위험을 줄인다.
- KST 자정 직후 stop state가 전일로 오판되지 않는다.
- Trading Monitor 행에서 `자동감시중 / 미감시 / 상태불일치`, S8 등록 여부, 실시간 구독 여부, 상태 원천이 표시된다.

## 남은 위험
- KIS 잔고 조회 자체가 실패하면 그 시점의 수량 동기화/잔고 미존재 제거가 건너뛰며, 다음 성공 시점까지 기존 S8 메모리 포지션이 남을 수 있다.
- 수동/이월 보유 종목을 자동 청산 대상으로 확대하려면 별도 PM 승인 정책이 필요하다.
