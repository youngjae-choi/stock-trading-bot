# OUTBOX: Codex — Set 개념 백엔드 구현 결과

**작성:** Codex 2026-05-23  
**대상 INBOX:** `docs/agent-comm/INBOX_CODEX_set_concept_backend.md`

---

## 1. 생성/수정된 파일 목록

- 수정: `backend/services/db.py`
  - `regime_sets`, `regime_set_applications` 테이블 생성 SQL 추가
  - `ensure_default_regime_sets()` 추가
  - 기본 Set 4종 + 2026-05-26 예측 Set 3종 `INSERT OR IGNORE` 시드 추가
- 신규: `backend/services/regime_set_service.py`
  - Set 목록 조회, 매칭, 자동 생성, 적용 기록, 결과 업데이트, 이력, 미리보기 구현
- 신규: `backend/api/routes/regime_sets.py`
  - `GET /api/v1/regime/sets`
  - `GET /api/v1/regime/today`
  - `GET /api/v1/regime/history`
  - `GET /api/v1/regime/preview`
- 수정: `backend/main.py`
  - `regime_sets_router` 등록
- 수정: `backend/services/engine/decision_engine.py`
  - `_save_daily_context_snapshot(today)`에서 `morning_context.market_data`의 `vix.price`, `kospi.change_pct`를 읽어 Regime Set 매칭 호출

---

## 2. DB 테이블 생성 확인

임시 DB(`/tmp/regime_set_test.sqlite3`) 기준으로 `initialize_database()` 실행 후 확인:

```text
{'tables': ['regime_sets', 'regime_set_applications'], 'set_count': 7, 'prebuilt_0526': 3}
```

확인된 테이블:

- `regime_sets`
- `regime_set_applications`

---

## 3. 기본 Set 7종 INSERT 확인

`ensure_default_regime_sets()` 실행 결과:

- 전체 Set: 7개
- 기본 Set: 4개
  - `SET-RISK_ON`
  - `SET-NEUTRAL`
  - `SET-RISK_OFF`
  - `SET-VOLATILE`
- 2026-05-26 예측 Set: 3개
  - `SET-PRE-0526-RECOVERY`
  - `SET-PRE-0526-SIDEWAYS`
  - `SET-PRE-0526-SELLOFF`

---

## 4. API Route 동작 확인

샌드박스에서 `uvicorn` 포트 바인딩이 실패해 실제 `curl` 호출은 수행하지 못했다.

```text
ERROR: could not bind on any address out of [('127.0.0.1', 8765)]
ERROR: could not bind on any address out of [('127.0.0.1', 8899)]
```

대신 동일 라우트 함수를 임시 DB(`/tmp/regime_set_api_direct.sqlite3`)에서 직접 호출해 응답 구조를 확인했다.

### `/api/v1/regime/sets`

```text
{'ok': True, 'count': 7, 'items': [...]}
```

### `/api/v1/regime/preview?regime_label=risk_on&vix=18.5&kospi_change_pct=0.8&trade_date=2026-05-26`

```text
{
  'ok': True,
  'date': '2026-05-26',
  'preview': {
    'set_id': 'SET-PRE-0526-RECOVERY',
    'set_name': '2026-05-26 반등 예측형',
    'match_score': 1.0,
    'is_new': False,
    'is_prebuilt': True
  }
}
```

### 적용 기록 확인

`match_set('risk_on', 18.5, 0.8, '2026-05-26')` 실행 후:

```text
{
  'ok': True,
  'date': '2026-05-26',
  'application': {
    'set_id': 'SET-PRE-0526-RECOVERY',
    'set_name': '2026-05-26 반등 예측형',
    'match_score': 1.0,
    'regime_label': 'risk_on',
    'vix_value': 18.5,
    'kospi_change_pct': 0.8
  }
}
```

### `/api/v1/regime/history?days=30`

```text
{'ok': True, 'count': 1, 'items': [{'trade_date': '2026-05-26', 'set_id': 'SET-PRE-0526-RECOVERY'}]}
```

---

## 5. 실행한 검증

- `python -m py_compile backend/services/db.py backend/services/regime_set_service.py backend/api/routes/regime_sets.py backend/services/engine/decision_engine.py backend/main.py`
  - 결과: 통과
- 임시 DB 초기화 + 테이블/시드 카운트 확인
  - 결과: 통과
- Regime Set preview/match/application/history 서비스 확인
  - 결과: 통과
- FastAPI 라우트 함수 직접 호출
  - 결과: 통과

---

## 6. 오류 및 해결 내용

- `morning_context` 실제 컬럼명은 `market_data`였으므로, 인박스 예시의 `market_data_json` 대신 `market_data`를 사용했다.
- `db.py`에는 `ensure_tables()`가 없고 `initialize_database()` + `_schema_statements()` 구조였으므로 기존 구조에 맞춰 테이블 생성과 시드를 연결했다.
- `uvicorn` 포트 바인딩은 현재 샌드박스 네트워크 제약으로 실패했다. 코드/DB/API 함수 검증은 임시 DB 기반 직접 호출로 대체했다.

---

## 7. 남은 확인 필요 사항

- 실제 운영 서버에서 `curl http://127.0.0.1:8000/api/v1/regime/sets` 확인 필요
- 월요일(2026-05-26) 실제 `morning_context` 생성 후 S6 활성화 시 `regime_set_applications`에 자동 기록되는지 운영 로그 확인 필요
