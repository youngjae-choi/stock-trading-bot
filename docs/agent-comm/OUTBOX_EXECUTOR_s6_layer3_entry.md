# OUTBOX_EXECUTOR_s6_layer3_entry

## 변경 파일 목록

- `backend/services/engine/rule_resolver.py`
- `backend/services/engine/decision_engine.py`
- `docs/agent-comm/OUTBOX_EXECUTOR_s6_layer3_entry.md`

## 구현 요약

### 1. RulePack 진입 조건 병합 보강

- `rule_resolver.py`의 `_get_active_rulepack_entry_rules(trade_date)`가 이제 `machine_rules.layer3_entry`와 legacy `machine_rules.entry_rules`를 모두 읽는다.
- 병합 순서는 `layer3_entry` 먼저, `entry_rules` 나중이다.
  - 이유: 기존 S4 자동 생성 경로가 `entry_rules`를 사용하고 있었으므로 같은 키가 있으면 기존 런타임 동작을 우선 유지한다.
- `machine_rules`, `layer3_entry`, `entry_rules`가 dict가 아니면 WARN 로그를 남기고 빈 값으로 방어 처리한다.

### 2. S6 런타임 평가 보강

- `decision_engine.py`의 `_evaluate_rules()`가 기존 핵심 게이트 키를 유지한다.
  - `volume_ratio`
  - `ai_confidence`
  - `price_change`
- 신호 발행 판단은 위 3개 게이트만 명시적으로 확인하도록 `_rules_allow_signal()`을 추가했다.
- `rule_matched`에는 추가 추적 정보를 함께 저장한다.
  - `observed_values`: 실제 확인한 confidence, change_rate, volume_ratio 및 임계값
  - `unavailable_conditions`: 현재 tick/candidate 데이터로 평가할 수 없는 조건과 사유

### 3. 데이터 없는 Layer3 조건 처리

- RSI, VWAP, MA5/MA20, spread는 현재 S6 tick/candidate 입력에 원천 데이터가 없으므로 임의 계산하지 않았다.
- 해당 조건이 최종 룰에 들어 있으면 `unavailable_conditions`에 사유를 남기고 WARN 로그를 기록한다.
- 거래량 배수(`volume_ratio_min`)는 후보 데이터에 `volume_ratio`, `vol_ratio`, `volume_ratio_20d` 또는 tick에 `volume_ratio`가 있을 때만 실제 배수로 비교한다.
- tick의 단일 거래량 값만으로는 배수를 계산하지 않도록 변경했다.

## 테스트 명령과 결과

### 통과

```bash
python -m py_compile backend/services/engine/rule_resolver.py backend/services/engine/decision_engine.py backend/services/engine/rule_cache.py
```

결과: 성공. 문법 오류 없음.

### 실행 불가

```bash
python -m pytest
```

결과: 실패.

사유:

- 현재 로컬 Python 환경에 `pytest`가 설치되어 있지 않다.
- 프로젝트 런타임 import도 `pydantic_settings` 미설치로 실패한다.

확인 명령 결과:

```text
pydantic_settings: missing (ModuleNotFoundError: No module named 'pydantic_settings')
pytest: missing (ModuleNotFoundError: No module named 'pytest')
```

## 남은 리스크 / 확인 필요 사항

- KIS 실시간 체결 tick의 등락률 필드 위치는 이번 작업에서 공식 근거 없이 추가하지 않았다.
- 운영에서 price change 평가를 안정화하려면 tick payload에 공식 문서 기반의 `change_rate` 매핑을 별도 작업으로 확인해야 한다.
- `unavailable_conditions`는 DB의 `trading_signals.rule_matched` JSON에 저장된다. 이 값을 화면에서 보여주려면 프론트/모니터링 표시 작업이 추가로 필요하다.
- 현재 환경에 의존성이 없어 API 호출 테스트, E2E 테스트, 서버 로그 확인은 수행하지 못했다.

## PM용 쉬운 설명

기존에는 AI가 만든 매수 조건이 `entry_rules`에 있으면 읽었지만, 새 RulePack 표준인 `layer3_entry` 조건은 S6가 제대로 읽지 못했다. 이제 두 형식을 모두 읽게 했다.

또한 거래량 조건은 단순히 "거래량 값이 있다"만 보고 통과시키던 부분을 고쳤다. 실제 배수 값이 있을 때만 비교하고, 데이터가 없으면 왜 평가하지 못했는지 기록한다.

RSI, VWAP, 이동평균 같은 조건은 현재 실시간 tick에 필요한 원천 데이터가 없어서 임의로 계산하지 않았다. 대신 어떤 조건이 평가 불가였는지 로그와 `rule_matched`에 남기도록 했다.
