# 자동 등록 종목 트레일링 제외 + 60초 sync 운영 로그 보강 결과

**발신: Codex (Backend Executor) | 수신: Sisyphus**
**날짜: 2026-05-26**

---

## 1. 항목 A 구현 요약 + diff 핵심

### 자동 등록 flag

- `PositionManager.add_position(..., auto_imported: bool = False)` 파라미터를 추가했다.
- 일반 매수/복원 경로는 기본값 `False`로 등록된다.
- `PositionManager.sync_account_position()`에서 KIS-only 보유 종목을 새로 등록할 때 `auto_imported=True`로 저장한다.
- 포지션 dict에 `"auto_imported": bool` 필드가 포함된다.

핵심 위치:

- `backend/services/engine/position_manager.py`
  - `add_position()`에 `auto_imported` 파라미터와 position dict 필드 추가
  - `sync_account_position()` 자동 등록 경로에서 `auto_imported=True` 전달

### 자동 등록 종목 트레일링 비활성

- `_update_trailing()` 진입 시 `auto_imported=True`면 트레일링 계산/활성화/stop 갱신을 하지 않고 즉시 return한다.
- 기존 `initial_stop_price`와 `active_stop_price`는 등록 시 설정된 LOW_VOL fallback 손절선 그대로 유지된다.
- 최초 skip 시 분석용 로그를 1회 남긴다.

예시:

```text
INFO: [S8] trailing disabled for auto_imported position symbol=005930 price=110.00 active_stop=98.00
```

### S9 auto_imported 메타데이터

- S9 KIS 실보유 청산 대상 조회 시 현재 `PositionManager`에 같은 symbol이 있으면 `auto_imported` 여부를 청산 position payload에 붙인다.
- S9 시작/중복 skip/개별 sell 로그에 `auto_imported` 값을 남긴다.
- `execute_sell()` 결과 dict에도 `auto_imported`를 추가한다.

---

## 2. 항목 B 로그 패턴 예시

새 로그는 `key=value` 한 줄 포맷으로 맞췄다.

```text
START: PositionSync trade_date=2026-05-26 seq=1
SUCCESS: PositionSync seq=1 kis_response_ms=184 kis_symbols=2 managed_before=1 managed_after=2 added=['000660'] removed=[] qty_changed=[('005930', 10, 6)] ws_resub=True elapsed_ms=207 rate_limit_hits=0
SKIP: PositionSync trade_date=2026-05-26 seq=2 reason=engine_inactive
EVENT: position auto_imported symbol=000660 name=SK하이닉스 qty=2 entry_price=120000.00 profile=LOW_VOL detection_reason=kis_only_holding
FAIL: PositionSync seq=3 reason=kis_balance_error exc=KIS API Error ... elapsed_ms=1012 rate_limit_hits=1
WARN: KIS rate_limit pressure high last_30m_hits=51
```

보강 내용:

- sync seq 카운터 추가
- KIS 잔고 API 응답 시간 `kis_response_ms` 추가
- `managed_before`, `managed_after`, `added`, `removed`, `qty_changed`, `ws_resub`, `elapsed_ms`, `rate_limit_hits` 추가
- EGW00201 감지 시 30분 누적 counter 기록, 임계값 50 초과 시 WARN 로그
- 자동 등록 이벤트는 `grep "auto_imported"`로 찾을 수 있게 별도 `EVENT` 로그 추가

---

## 3. 단위 테스트 결과

실행 명령:

```bash
python -m py_compile backend/services/engine/position_manager.py backend/services/engine/decision_engine.py backend/services/engine/eod_liquidation.py tests/unit/test_position_monitoring.py
PYTHONPATH=. pytest tests/unit/test_position_monitoring.py -q
```

결과:

```text
...........                                                              [100%]
11 passed in 0.39s
```

참고:

- `pytest tests/unit/test_position_monitoring.py -q` 단독 실행은 로컬 test runner 경로 문제로 `ModuleNotFoundError: No module named 'backend'`가 발생했다.
- 동일 테스트를 `PYTHONPATH=.`로 실행해 통과 확인했다.

---

## 4. 변경된 파일 목록과 라인 수

`git diff --numstat` 기준:

| 파일 | 추가 | 삭제 |
|------|------|------|
| `backend/services/engine/decision_engine.py` | 144 | 12 |
| `backend/services/engine/eod_liquidation.py` | 25 | 3 |
| `backend/services/engine/position_manager.py` | 27 | 4 |
| `tests/unit/test_position_monitoring.py` | 83 | 0 |
| `docs/agent-comm/OUTBOX_CODEX_20260526_auto_imported_flag.md` | 신규 | 신규 |

---

## 5. 위험 요소

- 백엔드 서버 stop/start는 수행하지 않았다. 변경 사항은 다음 백엔드 재시작 시 반영된다.
- DB 마이그레이션은 수행하지 않았다. `auto_imported`는 메모리 position dict와 S9 결과 메타데이터에만 추가했다.
- KIS retry decorator 내부에서 EGW00201이 발생했다가 최종 성공하는 경우는 `kis_rate_limiter.last_rate_limited_at` 변화로 감지하므로, 한 sync 안의 복수 retry hit는 `1`로 집계될 수 있다. 최종 실패 예외에 포함된 EGW00201은 문자열 발생 횟수 기준으로 집계한다.
- 현재 작업 전부터 존재하던 다른 미커밋 변경 파일들은 건드리지 않았다.
