# 시스템 운영 점검 보고서 - 2026-05-06

> 작성 시각: 2026-05-06 08:41 KST  
> 점검 범위: S1~S5 준비/분석/계획 단계 자동 실행 여부 확인 및 누락 단계 수동 실행  
> 금지 준수: 주문 executor, live order route, 매수/매도 API 호출 없음

---

## 1. 점검 요약

2026-05-06은 KST 기준 거래일로 보고 점검했다. 백엔드 서버는 `127.0.0.1:8000`에서 실행 중이었고, DB 경로는 `/home/young/repos/stock-trading-bot/data/stock_trading_bot.sqlite3`였다.

점검 시작 시 오늘 S2~S5 산출물과 성공 audit가 없었다. 또한 `pipeline_run_audit`, `daily_plan_run_history`, `daily_trading_plans.trigger_source/run_audit_id` 등 최신 운영 감사 스키마가 DB에 없어서 현재 코드 기준 DB 초기화/마이그레이션을 먼저 실행했다.

그 뒤 예정 시간이 지난 S2~S5를 `trigger_source=console_manual`로 수동 실행했고 모두 성공했다. 실계좌 주문/매수/매도 경로는 호출하지 않았다.

---

## 2. 스케줄 및 Guard 상태

| 항목 | 값 | 확인 결과 |
|---|---:|---|
| timezone | Asia/Seoul | 스케줄러 `CronTrigger(... timezone="Asia/Seoul")` 사용 |
| S1 | 07:45 | KIS 토큰 갱신 예정 |
| S2 | 08:00 | 시장 톤 분석 예정 |
| S3 | 08:15 | 유니버스 필터 예정 |
| S4 | 08:30 | 하이브리드 스크리닝 예정 |
| S5 | 08:40 | Daily Plan 생성 예정 |
| S5-V | 08:45 | Daily Plan 검증 예정 설정 존재 |
| S5-A | 08:55 | Daily Plan 활성화 확인 예정 설정 존재 |
| `schedule_skip_today` | `"true"` | 2026-05-05 07:45 KST에 기록된 stale 값. 오늘 S1 자동 갱신 흔적 없음 |
| `risk.emergency_halt_enabled` | `false` | 긴급정지 비활성 |
| `engine.mode` | `MONITOR` | 운영 모드 모니터 |
| KIS token | active | 만료 예정 2026-05-07 02:10:37 KST |

후속 조치: 08:45 KST에 `get_schedule_skip_today_status()`를 호출해 stale `true`를 `false`로 리셋했다. 리셋 사유는 `stale_true_reset`이며, 이후 S5-V/S5-A 및 후속 자동 단계가 과거 skip 값 때문에 막히는 상태는 해제됐다.

---

## 3. 단계별 결과

| 단계 | 예정 시간 | 자동 실행 여부 | 수동 실행 여부 | 결과 | trigger_source | 결과 ID |
|---|---:|---|---|---|---|---|
| S1 KIS 토큰 | 07:45 | 성공 audit 없음. 토큰은 active | 미실행 | 토큰 active 확인. S1 schedule_skip 갱신은 stale | - | - |
| S2 시장 톤 | 08:00 | 산출물/audit 없음 | 실행 | 성공, tone=`mixed`, confidence=0.55, provider=`anthropic` | `console_manual` | `1fa682bc-6a08-47f4-a16d-a66f583509f4` |
| S3 유니버스 필터 | 08:15 | 산출물/audit 없음 | 실행 | 성공, raw=45, filtered=45, top=30 | `console_manual` | `d2211235-2197-4796-9b4c-ec0d57c485b9` |
| S4 하이브리드 스크리닝 | 08:30 | 산출물/audit 없음 | 실행 | 성공, input=30, output=7, confidence=0.30, provider=`anthropic` | `console_manual` | `5db97f13-81b9-40cc-b65a-a0f262383729` |
| S5 Daily Plan | 08:40 | 산출물/audit 없음 | 실행 | 성공, status=`active`, assignments=5, excluded=2, provider=`anthropic` | `console_manual` | `daily-2026-05-06` |

S3 실행 중 KIS 초당 호출 제한 `EGW00201`이 1회 발생했으나 준비 단계의 시장 데이터 조회였고, 내장 재시도로 성공했다.

---

## 4. DB/Audit 확인

생성 또는 확인된 주요 레코드:

- `pipeline_run_audit`: S2, S3, S4, S5 모두 `status=success`, `trigger_source=console_manual`
- `market_tone_results`: 2026-05-06 S2 결과 1건
- `universe_filter_results`: 2026-05-06 S3 결과 1건
- `hybrid_screening_results`: 2026-05-06 S4 결과 1건
- `daily_trading_plans`: 2026-05-06 `daily-2026-05-06`, `status=active`
- `daily_plan_run_history`: 2026-05-06 S5 수동 생성 history 1건
- `daily_review_reports`: 점검 시각 기준 오늘 레코드 없음
- `daily_trade_summary`: 점검 시각 기준 오늘 레코드 없음

---

## 5. 남은 위험

1. 오늘 S1 자동 실행 또는 거래일 갱신이 정상 동작했다는 증거가 없다. `schedule_skip_today` stale `true`는 08:45 KST에 false로 리셋했다.
2. 점검 시작 전 `pipeline_run_audit`와 S5 history 스키마가 없었다. DB 초기화/마이그레이션 실행 전에는 운영 감사 추적이 불완전했다.
3. S4 완료 후 구현상 KIS WebSocket 시세 구독을 시작할 수 있다. 주문 경로는 아니지만, S6 이후 자동 판단 단계와의 연결 상태는 별도 통제 확인이 필요하다.
4. S5 Daily Plan은 `active`가 되었지만, PM 요청 범위상 S6 이후 decision/order 단계는 실행하지 않았다.
5. `risk.emergency_halt_enabled=false` 상태다. 실주문 위험을 완전히 차단하려면 운영 정책상 긴급정지 또는 주문 차단 설정을 별도 판단해야 한다.

---

## 6. 다음 확인 항목

1. 08:45 S5-V, 08:55 S5-A가 자동 audit를 남기는지 확인한다.
2. 09:45 S6 이후 단계가 의도치 않게 주문 경로로 이어지지 않도록 운영 모드와 주문 차단 정책을 재확인한다.
3. 장 종료 후 S10 Review & Audit, S11 Learning Memory가 정상 생성되는지 확인한다.
