# 장중 재선별 v2 운영 매뉴얼

## system_settings 키

| Key | 기본값 | 설명 |
| --- | ---: | --- |
| `intraday_refresh.master_enabled` | `true` | v2 신규 기능 전체 kill switch |
| `intraday_refresh.lunch_slots_enabled` | `true` | 13:00, 14:00 재선별 슬롯 활성화 |
| `intraday_refresh.sector_rotation_enabled` | `true` | 섹터 회전 감지 트리거 활성화 |
| `intraday_refresh.sector_rotation_threshold` | `3.0` | 상위 2개 섹터 평균과 나머지 섹터 평균의 갭 임계치(%) |
| `intraday_refresh.replacement_signal_enabled` | `true` | 포지션 교체 신호 생성 활성화 |
| `intraday_refresh.replacement_score_gap` | `0.15` | 신규 후보 점수가 기존 보유 점수보다 높아야 하는 상대 갭 |
| `intraday_refresh.max_replacement_per_symbol` | `1` | 보유 종목별 하루 교체 신호 최대 횟수 |
| `intraday_refresh.max_replacement_per_day` | `5` | 하루 전체 교체 신호 최대 횟수 |

## 트리거 조건

- 기존 시장 평균 트리거는 그대로 유지한다.
  - defensive: 시장 평균 `+2.0%` 이상
  - aggressive: 시장 평균 `-2.0%` 이하
  - neutral: 시장 평균 절댓값 `3.0%` 이상
- 섹터 회전 트리거는 KIS 거래량 상위 30종목을 `symbols.sector`로 묶고, `상위 2개 섹터 평균 등락률 - 나머지 섹터 평균 등락률 >= intraday_refresh.sector_rotation_threshold`이면 작동한다.
- 최종 재선별은 `시장 평균 트리거 OR 섹터 회전 트리거`로 판단한다.
- 13:00, 14:00 슬롯은 `intraday_refresh.lunch_slots_enabled=false` 또는 `intraday_refresh.master_enabled=false`이면 실행 대상에서 제외된다.

## 교체 신호

- 재선별 후 신규 후보와 현재 보유 포지션 점수를 비교한다.
- `(신규 후보 점수 - 기존 보유 점수) / 기존 보유 점수 >= intraday_refresh.replacement_score_gap`이면 `replacement_signals`에 신호를 저장한다.
- 강제 매도/매수는 수행하지 않는다.
- 트레일링 스탑으로 매도 주문이 접수되어 자리가 열리면 S6 후보 감시를 다시 정렬하고, 최근 매수 주문이 없는 후보는 자연 진입 평가를 다시 받을 수 있게 한다.

## 텔레그램 알림

- 장중 재선별 트리거:
  - title: `장중 재선별 - HH:MM`
  - body: `✅ 트리거됨 — 사유\n신규 후보 N종목, 보유 종목 유지`
- 장중 재선별 스킵:
  - title: `장중 재선별 - HH:MM`
  - body: `⏭️ 스킵 — 시장 평균 +0.3% (사유)`
- 섹터 회전:
  - title: `섹터 회전 감지 - HH:MM`
  - body: `🔄 상위섹터 ↔ 하위섹터 (갭 N.N%)\n재선별 트리거됨. 신규 후보 N종목.`
- 교체 신호:
  - title: `교체 신호 발생`
  - body: 현재 보유 종목, 신규 후보, 점수 갭, 강제 교체 없음 안내
