# 계좌유형(모의/실) 운영설정 자동 분기 — 개발계획서 v0.1

## 원본 요구사항 (PM 발화 그대로 인용)

> 5로 진행하자. 실계좌에서는 20으로 진행하고 실계좌 설정과 모의 계좌 셋팅화면에
> 모의계좌, 실계좌 스위치를 생성하고 실계좌일때랑 모의계좌일때랑 시스템 운영설정을 바꿔.

> PM 결정(2026-06-16): **C안 — 자동감지+표시(읽기전용)+계좌유형별 설정 자동적용**.
> 분기 대상: ① KIS RPS(이미 자동 5/20) ② 사이징·예수금 배포 ③ 탐색모드·max_positions ④ 신규진입승인·강제청산.

## 설계 (C안 — 최소 침습·불일치 불가)

- 계좌유형은 **`_is_virtual_trading()`(KIS_URL openapivts 여부)로 자동 감지** — 이미 존재. 런타임 연결 전환 없음(실제 돈 사고 위험 차단).
- **모드별 설정 override**: settings_store에 `{key}@virtual` / `{key}@real` 키를 두고,
  `get_setting(key)`가 **현재 모드의 override가 있으면 그것을, 없으면 base(공유)값을** 반환하도록 **단일 지점(get_setting)만** 수정.
  → 기존 수십 개 소비처(`get_active_budget_rate`, exploration 읽기 등)는 **무수정**으로 모드 인지.
- UI: 셋팅 화면 상단에 **현재 모드 배지(읽기전용)** + 분기 대상 설정에 모의/실 값 **2열 입력**(미설정=base 공유).

## 변경 파일 목록

| 파일 | 변경 | 이유 |
|------|------|------|
| `backend/services/settings_store.py` | 수정 | `get_setting`에 모드 override 폴백(`{key}@{mode}`) + `get_account_mode()` 헬퍼 |
| `backend/utils.py` | 재사용 | `_is_virtual_trading()` 그대로 활용(공개 래퍼만) |
| `backend/api/routes/settings.py` | 수정 | 현재 모드 반환 + 모드별 override get/set 엔드포인트 |
| `backend/static/js/screens/console-settings.js` | 수정 | 모드 배지 + 분기설정 모의/실 2열 UI |
| `backend/static/console.html` | 소수정 | 모드 배지 영역 |

## 요구사항 대조표

| 요구사항 | 계획 반영 | 비고 |
|----------|-----------|------|
| 모의 5 / 실 20 RPS | ✓ (기존) | profile auto — 추가공수 없음, 확인만 |
| 셋팅화면 모의/실 스위치 | ✓ | 단, C안이므로 "연결전환"이 아닌 **모드 배지(읽기전용)+설정 2열** |
| 계좌별 운영설정 분기 | ✓ | get_setting 모드 override로 sizing/탐색/max_positions/승인/강제청산 전부 커버 |
| 사이징·예수금 배포 | ✓ | `exploration.deploy_target_rate`, `budget_cap` 등 @mode override |
| 탐색·max_positions | ✓ | `engine.exploration_mode`, max_positions @mode |
| 신규진입승인·강제청산 | ✓ | 관련 키 @mode override |

## 미결 확인 (PM 결정 필요)

1. **각 설정의 모의/실 기본값**: 예) 탐색모드 모의=ON·실=OFF, deploy_rate 모의=95%·실=? max_positions 모의=20·실=? — 실계좌 보수값을 PM이 지정해야 함. (이번 구현은 **틀만 만들고 값은 UI에서 PM이 입력**하는 방식 권장)
2. **신규진입 승인**: 실계좌에서 수동승인 게이트를 "강제 ON"으로 둘지 — [[project_new_entry_allowed_advisory]]상 현재는 표시용. 실계좌 전환 시 강제화 여부.

## 완료 기준
- [ ] 현재 모드 자동감지·UI 배지 표시
- [ ] @mode override 저장 시 해당 모드에서만 적용, 미설정은 base 공유 (단위테스트)
- [ ] 기존 글로벌 설정 회귀 없음 (override 없으면 동작 불변)
- [ ] Playwright: 셋팅 화면 모드 배지·2열 입력 확인
