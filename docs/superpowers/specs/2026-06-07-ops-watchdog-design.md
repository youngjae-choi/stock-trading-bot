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

## 정합성 감시 (Sanity Watchdog v2, 2026-08-24)
v1이 "스텝이 **돌았나**"(운영 단계)를 본다면, v2는 **"시스템의 내부 판단이 실제 시장·계좌·설정과 어긋난 순간"**을 잡는다. PM이 눈으로 잡던 "이거 이상해"를 규칙화한 6종. 감지·Alert만, **자동수정·LLM 없음**(v1 제약 동일). 규칙마다 `watchdog.<rule>_enabled` 킬스위치(기본 True), 임계는 `watchdog.*` 설정으로 재배포 없이 튜닝.

| id | severity | 적용 시각 | 감지 내용 | 임계 설정(기본) | 데이터 소스 | 대응 사고 |
|----|----------|----------|----------|----------------|------------|----------|
| `regime_reality` | WARNING | 09:40~15:20 | 적용 레짐(risk_on/neutral) vs 라이브 코스피 반대방향(하락), 또는 risk_off인데 급반등. 적용 후 지속조건 충족 시만 | `regime_div_kospi_pct`(1.5), `regime_div_sustain_min`(20) | `regime_set_applications`(current_flag=1) + `market_snapshots`(KOSPI) | 2026-08-24 재기동 레짐 되돌림 |
| `order_reject_streak` | CRITICAL | 09:10~15:20 | 오늘 매수주문 N건↑ 전부 실패(성공 0) — 계좌만료/토큰 사망 | `order_reject_streak_n`(3) | `trading_orders`(side=buy, status) | 2026-07-13 40910000 주문거부 |
| `market_data_stale` | WARNING | 09:40~15:20 | 장중 KOSPI 스냅샷 갱신 나이 > 임계, 또는 스냅샷 부재 | `market_stale_min`(10) | `market_snapshots`(captured_at) | 2026-07-11 index-board 사망 |
| `entry_paralysis` | WARNING | 09:40~15:20 | S3 후보>0인데 매수신호=0, 긴급정지·진입중단(래치)도 아님 | — | `universe_filter_results`, `trading_signals`, `regime.entry_suspended` | 2026-07-23 밴드역전 마비 |
| `position_conflict` | CRITICAL | 09:10~15:20 | 실보유 종목수 > max_positions(과다 노출) | — (max_positions 단일출처) | `daily_holdings_snapshot`(qty>0) vs `strategy_playbook.resolve_max_positions` | 포지션-설정 충돌 |
| `qty_drift` | WARNING | 09:40~15:20 | DB원장 보유 > KIS 실보유(유령보유). 오늘 원장·스냅샷 모두 있을 때만 대조 | — | `position_cost_basis` vs `daily_holdings_snapshot` (fresh KIS 호출 없음) | 유령매도 조기경보 |

설계 원칙:
- **KIS 호출 금지**: 라이브 코스피는 `market_snapshots`(DB), 잔고는 `daily_holdings_snapshot`(캐시된 스냅샷)만 읽어 레이트리밋 안전.
- **오탐 억제**: `regime_reality`는 적용 후 20분 지속조건(전환 직후 억제), `qty_drift`는 오늘 원장·스냅샷 동시 존재 시만, 전 규칙 v1 daily dedup 공유.
- **후속(v2.1 예정)**: `position_conflict`의 "레버리지 차단인데 보유" 서브체크는 보유종목 name 조인 필요 → 별도 과제로 이연.

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
