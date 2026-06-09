# 상시 모멘텀 스캐너 (Continuous Momentum Scanner) — 설계서 v0.1

> 탐색 엔진이 하루 종일 "지금 활발히 거래되는 종목"을 상시 발굴해 매수 후보로 유입시킨다.
> 기존 장중 재선별(레짐 반응형)과 별개로, 레짐 트리거와 무관하게 항상 돈다. (PM 요청 2026-06-08)

## 왜 필요한가 (WHY)
현재 장중 재선별(`intraday_refresh`)은 **하루 5개 슬롯(09:30~14:00)에서 시장/섹터 레짐 변화 트리거가 걸릴 때만** 유니버스를 재스캔한다. 개별 종목의 활발함과 무관하고, 슬롯·트리거 사이에 새로 급등하는 종목을 못 잡는다. 그래서 "활발한 종목을 발굴하는 느낌이 없다"(PM). 탐색 목표(풀배포·하루 종일 활발한 거래·데이터 수집)와 안 맞는다.

## 확정 정책 (PM 승인 2026-06-08)
- **발굴 주기: 2~3분마다** (장중 상시, 레짐 트리거 무관).
- **편입 상한: 상위 N개 무제한 적극** — 매 스캔 현재 등락률·거래량급증 상위 적격 종목을 watchlist에 추가. 95% 배포·Profile 비중이 자연 상한.
- 적용 범위: **exploration_mode=true (모의 전용)**.

## 제안 모델

### 핵심: 레짐 게이트 없는 "S3-Light 상시 스캔 → S6 watchlist 유입" (LLM 없음)
- 2~3분마다 `momentum_scanner` 실행:
  1. 현재 movers 조회: `get_price_rank`(등락률 순위) + `get_volume_rank`(거래량급증) — 기존 S3 소스 재사용.
  2. 탐색 모멘텀 기준(상승폭 + 거래량급증, 기존 universe_filter 로직)으로 적격 필터.
  3. **신규 적격 종목**(미보유·미감시·쿨다운 외) → S6 watchlist 추가 + WS 구독.
  4. S6가 OR그룹 조건 충족 시 매수(Profile 비중·95% 배포 게이트 — 기존 경로).
- **LLM 미사용** (토큰 절약 — S4/S5 LLM은 아침·레짐 재선별에서만). 순수 정량 발굴.

### 기존 자산 재사용
- `universe_service.get_price_rank/get_volume_rank` (현재 시세 순위)
- `universe_filter`의 모멘텀 스코어·sanity 필터
- `decision_engine` 후보 추가 + WS 재구독 (refresh_candidates 경로)
- `buy_condition_framework`/OR그룹 (S6 진입 판정)
- 기존 `intraday_refresh`(레짐 반응)는 그대로 유지 — 보완 관계.

## 상태별 로그/가시화
- 스캔 로그: `[MomentumScan] 적격 N개, 신규편입 M개 (심볼...) 구독중 K`.
- Funnel/Trading Monitor에 "상시 발굴 유입" 표시(후속).

## 엣지케이스 & 예외처리
- **rate-limit**: 2~3분 주기 + rank API 호출 최소화(스냅샷 재사용), 실패 시 스킵(에러 아님).
- **신규매수 금지시간**: `new_entry_cutoff_time`(15:10) 이후 스캔 중지(발굴해도 매수 안 됨).
- **중복/churn**: 이미 보유·감시·당일 청산(쿨다운) 종목 제외.
- **WS 구독 폭증**: 95% 배포 도달 시 추가 구독 의미 약화 — 구독 상한(예: 동시 40~60) 가드 두되, 매수는 95% 게이트가 제어.
- **exploration_mode=false**: 스캐너 전체 비활성(모의 전용 하드 게이트).
- **장 시작 직후**: 09:00~09:05는 데이터 불안정 → 스캔 시작 09:05~.

## 기술 구현 힌트 (변경 예상 파일)
- 신규 `backend/services/engine/momentum_scanner.py`: 스캔·필터·신규편입 + WS 구독.
- `scheduler.py`: `job_momentum_scan` (09:05~15:10, */3분, exploration 가드).
- `decision_engine.py`: watchlist 추가 진입점(기존 refresh_candidates/load_daily_rules 재사용 또는 얇은 add_candidates).
- settings: `momentum_scan.enabled`, `momentum_scan.interval_min`(3), `momentum_scan.max_subscriptions`(가드).

## 검토 결과 (PM 승인 2026-06-08)
1. 발굴 주기 **3분** (`momentum_scan.interval_min=3`)
2. 동시 WS 구독 상한 **40** (`momentum_scan.max_subscriptions=40`) — 매수는 95% 배포가 제어, 구독 폭증 방지 안전판
3. **LLM 미사용** (순수 정량 발굴)

## 완료 기준
- exploration_mode에서 2~3분마다 현재 movers 스캔 → 신규 적격 종목 watchlist 유입 → S6 매수.
- 레짐 트리거 무관하게 상시 동작, 신규매수 금지시간 준수.
- TDD(필터·신규편입·중복제외·cutoff·exploration 가드), 회귀. docs/manual 갱신.
