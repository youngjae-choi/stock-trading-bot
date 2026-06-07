# 운영 감시봇 (Ops Watchdog) — 설계서 v1.0

## 목적
시스템이 스케줄·매매 단계에서 "해야 할 일을 했나·잘했나"를 **규칙기반(LLM 없음)** 으로 5분마다 자가 감시하고, 이상(미실행·실패·매수 미발생·데이터 결손·품질 미달)을 감지하면 **규칙·DB 조회로 컨텍스트를 수집**해 Alert Center에 기록 → PM이 보고 수정 결정.

## 제약 (PM 지시)
- **LLM 진단 금지** (토큰 낭비) — 컨텍스트는 규칙·DB 조회로만.
- **코드 자동수정 금지** — 감지·기록까지만. 수정은 PM 검토 후.

## 아키텍처
- `backend/services/engine/ops_watchdog.py` — 체크 레지스트리 + `run_ops_watchdog(now_kst)`.
- 스케줄러 `job_ops_watchdog` — **5분마다**, 시각인지형.
- **거래일 가드**: `trading_calendar` 비거래일이면 전체 스킵 (주말·공휴일 오경보 방지).
- 이상 → 기존 **`alert_center.create_alert(alert_type, title, severity, detail)`** 로 `system_alerts` 기록 → Alert Center 화면.

## 체크 레지스트리 (v1)
각 체크 = `{id, severity, applies(now,td), evaluate(conn,td) -> None|{title,detail}}`. 출력 테이블을 1차 증거로, `pipeline_run_audit` 실패 메시지를 보강.

| id | 적용 시각 | 정상 조건 | 이상 시 detail |
|----|----------|----------|---------------|
| `s2_premarket` | ≥08:35 | `market_tone_results` 오늘 존재 | "프리마켓 S2 미실행" + audit 실패 메시지 |
| `trade_prep` | ≥09:06 | `daily_trading_plans` 오늘 status='active' | "거래준비(S1~S5-A) 미완료/미활성" + audit |
| `quality_universe` | ≥09:06 | `universe_filter_results` 오늘 items ≥ 1 | "유니버스 0건/결손" |
| `quality_screening` | ≥09:06 | `hybrid_screening_results` 오늘 output_count ≥1 & confidence>0 | "스크리닝 결과 부실" |
| `baseline_capture` | ≥09:05 | `daily_capital_baseline` 오늘 존재 | "09:00 예수금 baseline 미캡처" |
| `buy_not_executed` | 09:10~15:30 | 매수신호(`trading_signals` signal_type='BUY') >0 이면 체결주문(`trading_orders` side='buy', status∈submitted/filled)도 >0 | 신호 N건·주문 0 + `order_preflight_checks.block_reasons` 동봉 |
| `postprocess` | ≥15:25 | `daily_review_reports` 오늘 존재 | "S9~S10 후처리 미완료" |

severity: 거래준비·매수미발생·후처리 = CRITICAL, 품질·baseline·프리마켓 = WARNING.

## 노이즈 제어 (5분 틱 스팸 방지) — 핵심
이상 생성 전 `system_alerts`에서 **`(alert_type, trade_date)` 미확인(acknowledged=0) 알림 존재 시 스킵**. → 같은 이상은 하루 1회만. (앞서 Alert Center 도배 경험 반영)

## 데이터 소스 (전부 규칙·DB, LLM 없음)
market_tone_results, daily_trading_plans, universe_filter_results, hybrid_screening_results, daily_capital_baseline, trading_signals, trading_orders, order_preflight_checks, pipeline_run_audit(실패 메시지), trading_calendar(거래일).

## 테스트 (TDD)
- 각 evaluate: 정상→None, 이상→{title,detail} (모의 DB 행 INSERT).
- dedup: 미확인 알림 있으면 create_alert 미호출.
- 거래일 가드: 주말 now → run_ops_watchdog 전체 스킵.
- applies 시각 게이트: 08:00엔 trade_prep 체크 미적용, 09:30엔 적용.

## 완료 기준
- ops_watchdog.py + job_ops_watchdog(5분) 등록.
- TDD 통과, 회귀 통과. 서버 재시작 후 비거래일 스킵 로그 확인.
- 이상 시 Alert Center에 컨텍스트 포함 기록(중복 없음).
