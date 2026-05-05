# INBOX_EXECUTOR_s6_layer3_entry

## 역할
너는 Executor / Oracle 역할의 Codex CLI다. 비프론트엔드 백엔드 구현, 통합, 테스트, 정밀 디버깅을 담당한다.

## 먼저 읽을 문서
아래 문서를 순서대로 확인한 뒤 작업한다.

1. `ONBOARDING.md`
2. `AGENTS.md`
3. `DOC_HIERARCHY.md`
4. `CODEX.md`
5. `FEATURE_TEMPLATE.md`
6. `ERROR_HANDLING.md`
7. `IMPLEMENTATION_RULES.md`
8. `TEST_RULES.md`

## 원본 요구사항
PM 요청:

> 현재 S6 구조를 먼저 파악하고 개발계획서 작성합니다.
> Claude가 떠 멈추었어. 니가 다시 시지프스가 되어야 해 . 어디까지 했는지 체크해보고 claude.md를 읽어서 앞으로의 작업은 CLI에게 지시해
> 1. 커밋
> 2. 승인

Sisyphus 확인 결과:

- 기존 변경분은 `4047a1a Save console account and audit updates`로 커밋됨.
- PM은 S6 구조 파악 및 개발계획을 승인함.
- 이제 CLI가 S6 Layer3 진입조건 정합성 보강을 수행한다.

## 현재 파악된 구조

- `backend/services/engine/decision_engine.py`
  - S6 활성화 시 S4 후보를 읽고 `load_daily_rules()`로 종목별 최종 룰을 캐시한다.
  - `_evaluate_rules()`는 현재 `volume_ratio`, `ai_confidence`, `price_change`만 평가한다.
  - 현재 `volume_ratio`는 실제 배수 비교가 아니라 tick에 거래량 값이 있으면 통과하는 수준이다.

- `backend/services/engine/rule_cache.py`
  - S6 시작 시 `resolve_symbol_rule()`로 최종 룰을 만들고 메모리에 캐시한다.

- `backend/services/engine/rule_resolver.py`
  - 활성 RulePack에서 `machine_rules.entry_rules`만 읽는다.
  - 그런데 RulePack validator/API는 `machine_rules.layer3_entry`를 요구한다.

- `backend/services/engine/rulepack_validator.py`
  - 필수 진입 조건 키는 `layer3_entry.vwap_position`, `volume_ratio_min`, `ma5_above_ma20`, `rsi_range`, `spread_max_pct`다.

- `backend/services/kis/realtime_ws.py`
  - 현재 tick 콜백 payload는 `symbol`, `price`, `volume`, `time`, `fields`만 넘긴다.
  - `change_rate`도 tick payload에 직접 넣지 않고 있어 `decision_engine.py`의 `tick.get("change_rate")`는 기본적으로 0이 될 수 있다.

## 개발계획서

### 작업명
S6 Layer3 진입조건 실평가 정합성 보강

### 구현 범위

- [ ] S6가 active RulePack의 `entry_rules`와 `layer3_entry`를 하위 호환 방식으로 읽도록 정리한다.
- [ ] `decision_engine.py`의 `_evaluate_rules()`가 기존 `ai_confidence`, `price_change`, `volume_ratio` 평가를 깨지 않도록 보강한다.
- [ ] 실시간 tick/candidate/final_rule에서 실제 확인 가능한 데이터만 평가한다.
- [ ] RSI/VWAP/MA 등 현재 데이터가 없는 조건은 임의 계산하지 않는다.
- [ ] 평가 불가능 조건은 조용히 통과시키지 말고 로그 또는 `rule_matched`에 확인 가능한 상태를 남긴다.
- [ ] 주요 함수에는 목적/파라미터 주석을 유지 또는 보강한다.
- [ ] 주요 흐름은 START/SUCCESS/WARN/FAIL 로그 규칙을 따른다.
- [ ] 검증 결과를 `docs/agent-comm/OUTBOX_EXECUTOR_s6_layer3_entry.md`에 작성한다.

### 변경 예상 파일

| 파일 경로 | 변경 유형 | 변경 이유 |
| --- | --- | --- |
| `backend/services/engine/rule_resolver.py` | 수정 | `entry_rules` / `layer3_entry` 스키마 불일치 해소 |
| `backend/services/engine/decision_engine.py` | 수정 | S6 runtime 진입조건 평가 보강 |
| `backend/services/kis/realtime_ws.py` | 수정 가능 | KIS tick 필드 중 이미 확인 가능한 값만 payload에 추가 |
| 테스트 파일 | 추가/수정 | S6 평가 로직 회귀 테스트 |

### 요구사항 대조표

| 요구사항 항목 | 계획서 반영 여부 | 비고 |
| --- | --- | --- |
| 현재 S6 구조 파악 | 반영됨 | 위 구조 요약 기준으로 재확인 후 진행 |
| 개발계획서 작성 | 반영됨 | 본 문서 포함 |
| CLI에게 지시 | 반영됨 | 이 INBOX를 읽고 작업 |
| 추측 금지 | 반영됨 | KIS/RulePack 실제 코드 기준으로만 구현 |
| 기존 기능 파괴 금지 | 반영됨 | 하위 호환 및 테스트 필수 |

### 테스트계획서

- 정상 시나리오
  - `entry_rules`만 있는 기존 RulePack도 S6 최종 룰에 반영된다.
  - `layer3_entry`만 있는 RulePack도 S6 최종 룰에 반영된다.
  - AI confidence와 price change 조건이 기존처럼 동작한다.

- 경계/예외 시나리오
  - tick에 가격이 없거나 0이면 신호가 생성되지 않는다.
  - 평가에 필요한 데이터가 없는 Layer3 조건은 임의 통과/임의 실패하지 않고 추적 가능한 결과를 남긴다.
  - RulePack JSON 파싱 실패 시 기존 경고 로그와 fallback 동작이 유지된다.

- 회귀 시나리오
  - S4 후보가 없으면 S6가 기존처럼 비활성화된다.
  - 이미 신호를 보낸 종목은 중복 신호를 만들지 않는다.
  - `order_executor.execute_signal()` 호출 경로가 깨지지 않는다.

### 완료 기준

- [ ] 구현 파일의 변경 범위가 위 계획에 한정됨.
- [ ] S6 룰 병합과 runtime 평가의 스키마 불일치가 해소됨.
- [ ] 테스트 또는 최소 재현 스크립트로 핵심 평가 로직을 검증함.
- [ ] 가능한 경우 `python -m pytest` 또는 관련 테스트를 실행함.
- [ ] 실행하지 못한 검증은 이유를 명확히 OUTBOX에 기록함.
- [ ] git commit은 하지 않음.

## 금지 사항

- git commit 금지.
- 기존 미커밋 변경 임의 되돌리기 금지.
- API 키, 토큰, 계좌번호 전체값 등 민감정보 로그 출력 금지.
- 확인되지 않은 KIS 필드 의미를 임의로 단정해 계산 로직 작성 금지.
- 새 라이브러리 추가 금지.

## 결과 보고

작업 후 반드시 `docs/agent-comm/OUTBOX_EXECUTOR_s6_layer3_entry.md`를 작성한다.

포함할 내용:

- 변경 파일 목록
- 구현 요약
- 테스트 명령과 결과
- 남은 리스크 / 확인 필요 사항
- PM이 이해할 수 있는 쉬운 설명
