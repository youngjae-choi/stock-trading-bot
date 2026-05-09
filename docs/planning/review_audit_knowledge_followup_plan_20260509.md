# Review/Audit + Knowledge 운영 검증 후속 — 개발계획서/테스트계획서 v0.1

## 원본 요구사항
> 내 요구사항을 니가 반영하였는지 점검한 MD파일이 있어. 그거 보고 다음작업 찾아보자
>
> 전략과 내가 외부로 부터 업로드하는 문서에 따른 전략을 LLM 분석하고 전략을 수립 => PM 검증 => 반영 or 설정이 없으면 개발 후에 반영.. 이런형태로 개발한다면 어때?

## 확정된 방향
- 새 기능을 바로 추가하기보다 `Review/Audit`, `Knowledge`, `Settings`, 주요 콘솔 화면의 운영 검증 흐름을 먼저 정리한다.
- 화면의 최종 상태 기준은 프론트 추측이 아니라 `Backend audit` 기록으로 삼는다.
- AI/LLM 추천은 모두 자동 반영하지 않는다. 낮은 위험값은 자동 반영 가능하지만, 매수/청산/손실한도/포지션에 영향을 주는 값은 PM 승인 후 반영한다.
- 외부 업로드 문서와 AI 운영 복기는 `Knowledge`에 전략 후보로 저장하고, PM이 `승인 / 보류 / 개발필요`로 판단한다.
- 구현 착수 전 이 계획서와 테스트계획서를 PM이 승인해야 한다.

## P0 결함 분석: 보유 포지션 자동 손절/트레일링 미동작
PM이 보유 포지션 모니터링 화면에서 `매수가 대비 -16%` 종목이 손절되지 않고, `매수가 대비 +28%` 종목도 트레일링 보호를 받지 못하는 문제를 확인했다. 이 문제는 단순 표시 오류가 아니라 실제 손실 방어 실패 가능성이 있으므로, 기존 화면 정리보다 우선순위를 높여 분석/수정한다.

### 코드 기준 1차 원인 가설
- `PositionManager`는 `backend/services/engine/position_manager.py`에서 실시간 tick을 받을 때, 해당 종목이 인메모리 `_positions`에 없으면 바로 무시한다. 즉 KIS 계좌에는 보유 중이어도 `PositionManager`에 등록되지 않은 종목은 자동 손절/트레일링이 발동하지 않는다.
- `DecisionEngine.activate()`는 `backend/services/engine/decision_engine.py`에서 오늘 S4 후보 종목 중심으로 실시간 WebSocket 구독을 시작한다. 현재 KIS 실보유 전체가 항상 구독/감시 대상이 된다는 보장이 없다.
- `Trading Monitor`의 `/api/v1/trading-monitor/positions`는 KIS 실보유를 기준으로 표시하면서 `position_stop_states` 또는 fallback 손절선을 덧씌운다. 따라서 화면에 손절선이 보인다고 해서 실제 자동 청산 감시가 돌고 있다는 뜻은 아니다.
- `/api/v1/orders/positions`는 `PositionManager` 인메모리 포지션만 반환하고, Trading Monitor는 KIS 실보유를 반환한다. 두 화면/API가 말하는 `포지션`의 의미가 다르다.
- `position_stop_states` 테이블에는 `trade_date`와 종료 상태가 없어 과거 row가 오늘 화면에 섞일 수 있다.
- 트레일링 상태는 고점 갱신 시에만 DB에 저장된다. 트레일링 활성화 자체와 화면 표시가 실제 인메모리 상태와 어긋날 수 있다.

### 우선 결론
- `-16%` 손절 미동작은 해당 종목이 `PositionManager` 감시 대상 또는 실시간 구독 대상에서 빠졌을 가능성이 가장 크다.
- `+28%` 종목의 트레일링 미동작도 현재 보유 종목과 S8 감시 대상 불일치, 또는 stale/fallback 손절 상태 표시 불일치 가능성이 크다.
- 구현 전 PM이 결정해야 할 핵심 정책은 `오늘 봇이 매수한 종목만 자동 감시할지`, `현재 KIS 실보유 전체를 자동 감시/청산 대상으로 삼을지`이다. 안전 관점에서는 최소한 Trading Monitor에 `자동감시중 / 미감시` 상태를 분리 표시해야 한다.

## 구현할 기능 설명
0. 보유 포지션 자동 손절/트레일링 감시 결함 수정
   - KIS 실보유, `PositionManager` 인메모리 포지션, 실시간 WebSocket 구독 종목, `position_stop_states`를 대조한다.
   - 보유 종목별로 실제 자동감시 상태를 `자동감시중 / 미감시 / 상태불일치`로 표시한다.
   - PM 승인 정책에 따라 감시 대상 복원 범위를 확정한다. 기본 수정 방향은 KIS 실보유 전체가 손절/트레일링 감시 대상에서 누락되지 않도록 하는 것이다.
   - stale `position_stop_states`가 오늘 화면에 실제 감시 상태처럼 보이지 않도록 날짜/상태 기준을 보강한다.

1. `Backend audit` 기반 상태 표시 정리
   - Console, Review/Audit, Daily Plan, System Diagnostics는 백엔드 감사 로그를 최종 기준으로 상태를 보여준다.
   - 빈 화면은 `데이터 없음`, `미수집·대기`, `실행 실패` 3단계로 구분한다.

2. Trade History / Trade Review 역할 정리
   - Trade History는 체결 결과만이 아니라 매수/매도 시도, 주문 제출, 체결, 실패, 취소, 청산 사유까지 전체 주문 이력을 보여준다.
   - Trade Review는 DB를 원본으로 저장하고, 사람이 읽을 수 있는 MD 백업을 추가 생성한다.

3. Settings 반영 경계 정리
   - 낮은 위험 추천값은 자동 반영 가능하게 한다.
   - 매수, 청산, 손실한도, 포지션에 영향을 주는 값은 PM 승인 후 반영한다.
   - Settings에 없는 전략은 `개발필요`로 표시한다.

4. Knowledge 전략 검증 흐름 정리
   - 외부 문서 전략과 AI 운영 복기 전략을 Knowledge에 저장한다.
   - 전략별 상태를 `승인`, `보류`, `개발필요`로 분류한다.
   - 승인된 전략만 Settings 반영 후보가 된다.

5. 주요 화면 의도 정리
   - Trading Monitor: 위험/포지션 감시 중심.
   - Daily Plan: 오늘 전략 요약을 최상단에 배치.
   - Funnel Monitor: 어디서 몇 개가 탈락했고 왜 탈락했는지 중심.
   - System Diagnostics: 위험한 수동 실행 버튼 노출보다 감사 로그 확인 중심.

## 구현 범위
- [ ] P0: KIS 실보유 전체와 `PositionManager` 감시 대상의 불일치 여부 확인
- [ ] P0: 실시간 WebSocket 구독 종목에 현재 보유 종목이 포함되는지 확인
- [ ] P0: 보유 종목별 `자동감시중 / 미감시 / 상태불일치` 표시 추가
- [ ] P0: `position_stop_states`의 날짜/상태 기준 보강 또는 stale row 차단
- [ ] P0: 트레일링 활성화/고점/active stop 상태가 DB와 화면에 일관되게 반영되도록 보강
- [ ] 백엔드 감사 로그와 화면 상태 표시 연결 지점 확인
- [ ] 상태 표시를 `데이터 없음 / 미수집·대기 / 실행 실패`로 구분
- [ ] Trade History 데이터 범위를 전체 주문 이력으로 확장 또는 표시 기준 수정
- [ ] Trade Review DB 원본 저장과 MD 백업 생성 경로 설계 및 구현
- [ ] Settings 추천값 자동 반영/승인 필요 경계 적용
- [ ] Knowledge 전략 상태값 `승인 / 보류 / 개발필요` 흐름 적용
- [ ] Trading Monitor, Daily Plan, Funnel Monitor, System Diagnostics 화면 목적에 맞게 표시 정리
- [ ] 관련 서버 로그를 시작/완료/실패 단계로 남김
- [ ] 테스트 결과서와 사용자 매뉴얼/WBS 업데이트

## 변경 파일 목록
| 파일 경로 | 변경 유형 | 변경 이유 |
|---|---|---|
| `backend/static/console.html` | 수정 예상 | 주요 콘솔 화면 표시와 이동 흐름 정리 |
| `backend/static/js/*.js` | 수정 예상 | 화면별 상태 표시, History/Review/Knowledge 동작 JS 정리 |
| `backend/api/routes/*.py` | 수정 가능 | 감사 로그, 주문 이력, Knowledge, Settings API 보강 필요 시 |
| `backend/services/engine/position_manager.py` | 수정 예상 | 손절/트레일링 감시 대상, 상태 저장, 자동 청산 판단 보강 |
| `backend/services/engine/decision_engine.py` | 수정 예상 | S8 활성화 시 실보유 종목 복원/실시간 구독 범위 보강 |
| `backend/services/kis/realtime_ws.py` | 수정 가능 | 실시간 구독 종목에 보유 종목 추가 필요 시 보강 |
| `backend/api/routes/trading_monitor.py` | 수정 예상 | KIS 실보유와 실제 자동감시 상태를 분리 표시 |
| `backend/services/**/*.py` | 수정 가능 | Review MD 백업 생성, 추천값 반영 경계, 서버 로그 처리 |
| `tests/e2e/**/*.spec.*` | 추가/수정 예상 | PM 브라우저 확인 시나리오 자동화 |
| `docs/manual/**` | 수정 예상 | 변경된 운영 흐름 사용자 매뉴얼 반영 |
| `docs/agent-comm/**` | 추가 예상 | Executor/Frontend/Oracle 작업 지시와 결과 보고 |

정확한 파일 목록은 구현 전 Explore가 실제 활성 코드 경로를 확인한 뒤 확정한다.

## 기존 기능 영향 범위
- 보유 포지션 자동 손절/트레일링은 실제 매도 주문과 연결되므로 최우선 회귀 위험이다. 잘못 수정하면 보유 종목이 과도하게 매도되거나, 반대로 손실 방어가 계속 실패할 수 있다.
- KIS 실보유 전체를 자동 감시 대상으로 확장할 경우, 수동 매수 또는 과거 보유 종목까지 자동 청산 대상이 될 수 있으므로 PM 승인 정책이 필요하다.
- 주문 실행 자체는 기존 API를 사용하되, 감시 대상/구독 대상/표시 상태의 정합성을 먼저 맞춘다.
- Settings 자동 반영 범위를 잘못 잡으면 실제 매매 조건에 영향을 줄 수 있으므로 위험값은 PM 승인 게이트를 유지한다.
- 기존 History/Review 데이터는 삭제하지 않는다. 기본 화면은 오늘 기준이지만 날짜별 조회로 과거 데이터를 볼 수 있어야 한다.
- System Diagnostics에서 위험한 수동 실행 기능을 숨기거나 약화할 경우, 운영자가 기존에 사용하던 수동 확인 경로가 바뀔 수 있다.

## 요구사항 대조표
| 요구사항 항목 | 계획서 반영 여부 | 비고 |
|---|---|---|
| 보유 포지션 손절/트레일링 미동작 원인 분석 | 반영됨 | KIS 실보유와 S8 감시 대상 불일치 가능성 우선 검증 |
| 보유 종목 자동감시 상태 표시 | 반영됨 | `자동감시중 / 미감시 / 상태불일치` 분리 필요 |
| Backend audit을 최종 상태 기준으로 사용 | 반영됨 | 프론트 임의 추측 축소 |
| 빈 상태 3단계 구분 | 반영됨 | 문구는 구현 중 최종 확정 |
| Trade History를 전체 주문 이력으로 표시 | 반영됨 | 컬럼명은 구현 중 확정 |
| Trade Review DB 원본 + MD 백업 | 반영됨 | MD 저장 위치는 구현 중 확정 |
| 낮은 위험 Settings 자동 반영 | 반영됨 | 위험값 목록은 구현 중 확정 |
| 매수/청산/손실한도/포지션 영향값 PM 승인 | 반영됨 | 자동 반영 금지 |
| 과거 데이터 보관 + 오늘 기본 + 날짜별 조회 | 반영됨 | 삭제 금지 |
| Trading Monitor 위험/포지션 감시 중심 | 반영됨 | 화면 구성 정리 대상 |
| Daily Plan 오늘 전략 요약 최상단 | 반영됨 | PM이 이유를 먼저 보게 함 |
| Funnel Monitor 탈락 수와 이유 중심 | 반영됨 | 운영 복기 연결 |
| System Diagnostics 감사 로그 확인 중심 | 반영됨 | 위험 버튼 노출 최소화 |
| Knowledge 전략 승인/보류/개발필요 분류 | 반영됨 | PM 검증 후 반영 |

## Settings 안전 기준
- 구현 시작 시점의 기본값은 `자동 반영 allowlist 없음`으로 둔다.
- 자동 반영은 PM이 명시적으로 승인한 allowlist 항목에만 허용한다.
- 현재 코드에서 확인된 위험 승인 대상 후보는 `risk.daily_loss_limit_percent`, `risk.max_positions`, `risk.max_position_rate_per_stock`, `engine.mode`, `risk.new_entry_cutoff_time`, `risk.force_exit_time`, `override_stop_loss_rate`, `override_trailing_activate_rate`, `override_trailing_stop_rate`이다.
- 낮은 위험 자동 반영 후보는 매매 조건을 바꾸지 않는 화면 표시, 리포트 생성, 감사/복기 문구, 알림 문구 같은 운영 보조값으로 제한한다. 실제 key는 구현 전 PM 승인 allowlist로 고정한다.
- allowlist에 없는 Settings key는 자동 반영하지 않고 `PM 승인 필요` 또는 `개발필요`로 분류한다.

## 추가 확정 필요 항목
- `데이터 없음 / 미수집·대기 / 실행 실패`의 화면별 최종 문구.
- 자동 반영 allowlist의 최종 key 목록.
- 자동 손절/트레일링 감시 대상을 `오늘 봇 매수분`으로 제한할지, `KIS 실보유 전체`로 확장할지.
- 수동 매수 또는 이전 영업일 보유 종목에 자동 청산을 적용할지.
- Trade History 컬럼명과 정렬 기준.
- Trade Review MD 백업 파일명, 저장 위치, 보관 기간.

## 예상 소요 시간
- 코드 경로 확인 및 상세 설계: 0.5일
- 백엔드/API/저장 흐름 구현: 1.0~1.5일
- 프론트 화면 표시 정리: 1.0일
- E2E/서버 테스트 및 회귀 확인: 0.5~1.0일
- 문서/매뉴얼/WBS 업데이트: 0.5일

총 예상: 3~4.5일

## 완료 기준 Definition of Done
- [ ] PM이 이 개발계획서와 테스트계획서를 승인했다.
- [ ] 실제 활성 코드 경로를 확인한 뒤 구현했다.
- [ ] 모든 신규/수정 함수와 주요 컴포넌트에 목적 주석이 있다.
- [ ] 주요 서버 작업은 INFO/WARN/ERROR 로그로 시작/완료/실패를 확인할 수 있다.
- [ ] 관련 API 호출 테스트가 통과했다.
- [ ] 관련 E2E 테스트가 통과했다.
- [ ] 빌드 또는 정적 검증이 통과했다.
- [ ] 기존 주문 실행, Settings, History 조회 기능이 깨지지 않았다.
- [ ] 테스트결과서, 사용자 매뉴얼, WBS가 업데이트됐다.

## 테스트계획서

### 테스트 시나리오
| 시나리오 | 도구 | 입력값/절차 | 예상 결과 |
|---|---|---|---|
| -16% 보유종목 손절 감시 | API + 단위/통합 테스트 | KIS 실보유에는 있으나 `PositionManager` 인메모리에 없는 손실 포지션을 준비한다 | 수정 후 해당 종목이 감시 대상으로 복원되거나 화면에 `미감시`로 명확히 표시됨 |
| +28% 보유종목 트레일링 활성화 | API + 단위/통합 테스트 | 진입가 대비 충분히 상승한 보유 포지션과 실시간 tick을 주입한다 | trailing 활성화, 최고가, active stop이 인메모리/DB/화면에 일관되게 반영됨 |
| 실보유 종목 WebSocket 구독 | API + 로그 확인 | S4 후보가 아니지만 KIS 실보유인 종목을 준비하고 S8을 활성화한다 | 실보유 종목이 구독 대상에 포함되거나 미구독 사유가 화면/로그에 표시됨 |
| 과거 stop state 오염 방지 | DB + API | 전일 `position_stop_states` row와 오늘 KIS 보유를 같은 symbol로 준비한다 | 전일 stale row가 오늘 자동감시 상태처럼 표시되지 않음 |
| Backend audit 정상 상태 표시 | API + 브라우저 | 테스트용 오늘 감사 로그를 준비한 뒤 Console/Review/Audit/Daily Plan/Diagnostics 화면을 연다 | 각 화면이 완료 또는 정상 상태를 audit 기준으로 표시 |
| 미수집·대기 상태 표시 | API + 브라우저 | 오늘 감사 로그가 없는 날짜/상태로 화면을 연다 | 완료처럼 보이지 않고 `미수집·대기` 계열 상태를 표시 |
| 데이터 없음 상태 표시 | API + 브라우저 | 정상 실행됐지만 결과 데이터가 없는 날짜를 조회한다 | 오류가 아니라 `데이터 없음` 계열 상태를 표시 |
| 실행 실패 상태 표시 | API + 브라우저 | 실패 audit 로그가 있는 날짜를 조회한다 | 실패 상태와 확인 가능한 실패 사유를 표시 |
| Trade History 전체 주문 이력 | API + Playwright | 매수 시도, 주문 제출, 실패, 취소, 청산 테스트 데이터를 만든 뒤 Trade History를 조회한다 | 체결 건만이 아니라 전체 주문 이벤트가 조회됨 |
| Trade Review 저장 | API + 파일 확인 | 일일 리뷰 생성을 실행하고 DB 조회와 MD 백업 파일 존재 여부를 확인한다 | DB 원본이 저장되고 MD 백업이 함께 생성됨 |
| 낮은 위험 Settings 자동 반영 | API + 브라우저 | PM 승인 allowlist에 포함된 낮은 위험 key 추천값을 생성한다 | 승인 없이 Settings에 반영되고 변경 이력이 남음 |
| 위험 Settings 승인 필요 | API + 브라우저 | 위험 승인 대상 key 추천값을 생성한다 | 자동 반영되지 않고 PM 승인 필요 상태로 남음 |
| Settings 미지원 전략 | API + 브라우저 | 현재 Settings에 없는 전략을 Knowledge에 등록한다 | `개발필요`로 표시되고 자동 반영되지 않음 |
| Knowledge 전략 승인 | 브라우저 + API | PM 역할로 전략을 승인하고 반영 후보 목록을 확인한다 | 승인 상태로 바뀌고 반영 가능 후보로 분류됨 |
| 과거 날짜 조회 | Playwright | 오늘이 아닌 날짜를 선택해 History/Review/Daily Plan을 조회한다 | 과거 데이터를 삭제하지 않고 날짜별로 조회 가능 |

### 브라우저 확인 항목
- [ ] Console 주요 카드가 audit 기준 상태를 표시한다.
- [ ] Trading Monitor가 각 보유 종목의 `자동감시중 / 미감시 / 상태불일치`를 구분해서 보여준다.
- [ ] Trading Monitor가 위험/포지션 감시 정보를 우선 보여준다.
- [ ] Daily Plan 상단에서 오늘 전략 요약을 먼저 확인할 수 있다.
- [ ] Funnel Monitor에서 탈락 수와 탈락 이유를 확인할 수 있다.
- [ ] System Diagnostics가 감사 로그 확인 중심으로 보인다.
- [ ] Knowledge에서 전략 상태를 `승인 / 보류 / 개발필요`로 구분할 수 있다.
- [ ] Trade History에서 전체 주문 이력이 날짜별로 조회된다.
- [ ] Trade Review 결과를 화면과 MD 백업으로 확인할 수 있다.

### 엣지 케이스
- KIS 실보유에는 있지만 `PositionManager` 인메모리에는 없는 종목.
- KIS 실보유에는 있지만 실시간 WebSocket 구독 대상에는 없는 종목.
- 전일 `position_stop_states`가 오늘 같은 symbol 화면에 섞이는 경우.
- trailing 활성화는 됐지만 고점 미갱신으로 DB 표시가 갱신되지 않는 경우.
- audit 로그는 성공인데 상세 데이터가 비어 있는 경우.
- 상세 데이터는 있는데 audit 로그가 없는 경우.
- 장 휴일 또는 비거래일 조회.
- LLM 추천값이 Settings에 없는 항목을 제안하는 경우.
- 위험값과 낮은 위험값이 한 번에 같이 추천되는 경우.
- Trade Review MD 백업 생성은 실패했지만 DB 저장은 성공한 경우.
- 과거 데이터가 많아 조회가 느려지는 경우.

## 승인 게이트
이 문서는 구현 전 계획서다. PM이 승인하기 전에는 코드 구현을 시작하지 않는다.
