# OUTBOX_EXECUTOR_s5_risk_inline — risk_constants 인라인 통합 결과

## 작업 결과
- `backend/services/engine/rulepack_generation.py`에서 `importlib` 기반 `risk_constants.py` 우회 로딩 코드를 제거했다.
- L1 절대 한도 상수와 `_cap()`, `_apply_l1_caps()`를 `rulepack_generation.py`에 인라인으로 추가했다.
- `_load_pm_settings()`가 인라인 L1 상수를 기본값으로 사용하도록 수정했다.
- `_apply_caps_and_build_validation()`이 `_apply_l1_caps()` 결과를 `validation.cap_applied`에 반영하도록 수정했다.
- `backend/config/risk_constants.py`를 삭제했고, 남은 `__pycache__`까지 정리해 `backend/config/` 디렉토리를 삭제했다.

## 변경 파일
- `backend/services/engine/rulepack_generation.py`
- 삭제: `backend/config/risk_constants.py`
- 신규: `docs/agent-comm/OUTBOX_EXECUTOR_s5_risk_inline.md`

## 검증 결과
- `python -m py_compile backend/services/engine/rulepack_generation.py && echo "OK"` → `OK`
- `python -c "from backend.services.engine.rulepack_generation import run_rulepack_generation; print('import OK')"` → `import OK`
- `_apply_caps_and_build_validation()` 런타임 스니펫 검증 → `cap test OK`
- `backend/config/` 삭제 확인 → `backend/config removed`

## 참고 / 남은 리스크
- 전체 E2E와 API 호출 테스트는 이번 지시의 완료 기준에 포함된 두 커맨드 중심으로 검증했다.
- `backend/prompts/DECISION_LOG.md`에는 과거 결정 기록으로 `config/risk_constants.py` 언급이 남아 있으나, 이번 작업 범위가 실행 코드 인라인 통합이므로 수정하지 않았다.
