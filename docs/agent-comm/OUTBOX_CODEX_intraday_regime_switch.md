# OUTBOX: Codex — 장중 레짐 SET 전환 백엔드 구현 결과

**작업일:** 2026-05-23  
**담당:** Codex (Backend Executor)  
**상태:** 구현 및 로컬 검증 완료

---

## 1. 구현 요약

- `regime_set_applications`를 하루 1건 구조에서 하루 다중 전환 구조로 변경했다.
  - `trade_date UNIQUE` 제거용 테이블 재생성 마이그레이션 추가
  - `applied_at`, `trigger`, `current_flag` 추가
  - `(trade_date, applied_at)` 복합 UNIQUE 인덱스 추가
- `positions.entry_set_id` 컬럼 마이그레이션을 추가했다.
- `RegimeSetService.record_application()`을 UPSERT 방식에서 신규 전환 row INSERT 방식으로 변경했다.
  - 같은 날짜 기존 row는 `current_flag=0`
  - 새 row는 `current_flag=1`
  - `trigger='morning' | 'intraday'` 저장
- `get_today_application()`은 현재 활성 SET만 반환하도록 변경했다.
- `get_today_transitions()` 신규 추가로 당일 전환 이력 전체를 반환한다.
- `backend/services/engine/intraday_regime_monitor.py`를 신규 작성했다.
  - 아침 VIX는 `morning_context.market_data`에서 읽음
  - KOSPI 현재 등락률은 `market_snapshots` 최신 row에서 읽음
  - 25분 최소 전환 간격 적용
  - SET 변경 시 `system_alerts`에 `regime_transition` alert 삽입
- `scheduler.py`에 09:30~15:00 30분 간격 장중 레짐 모니터 job 12개를 등록했다.
- `/api/v1/regime/today` 응답에 `transitions`, `transition_count`를 추가했다.

---

## 2. 실제 DB 마이그레이션 결과

`initialize_database()` 직접 실행 결과:

```text
initialize_database ok
```

현재 `regime_set_applications` 컬럼:

```text
id, trade_date, applied_at, set_id, set_name, match_reason, match_score,
applied_settings, regime_label, vix_value, kospi_change_pct, trigger,
current_flag, total_trades, win_count, total_pnl, result_updated_at, created_at
```

현재 인덱스:

```text
idx_regime_set_applications_created_at
idx_regime_set_applications_set_id
idx_regime_set_applications_trade_applied_at UNIQUE(trade_date, applied_at)
sqlite_autoindex_regime_set_applications_1 PRIMARY KEY(id)
```

현재 `positions`에는 `entry_set_id TEXT`가 추가되었다.

---

## 3. market_snapshots 실제 컬럼 구조

실제 컬럼은 INBOX 예시의 `data_json`이 아니라 아래 구조다.

```text
id TEXT PRIMARY KEY
symbol TEXT NOT NULL
price REAL
volume REAL
change_rate REAL
source TEXT NOT NULL DEFAULT 'kis'
captured_at TEXT NOT NULL
raw_json TEXT NOT NULL DEFAULT '{}'
```

따라서 `_get_current_kospi_change()`는 우선 `symbol IN ('KOSPI', 'KS11', '^KS11')` 최신 row의 `raw_json` 또는 `change_rate`를 읽고, 없으면 최신 snapshot row를 fallback으로 읽도록 구현했다.

---

## 4. 검증 결과

컴파일 검증 통과:

```bash
python -m py_compile \
  backend/services/db.py \
  backend/services/regime_set_service.py \
  backend/services/engine/intraday_regime_monitor.py \
  backend/services/scheduler.py \
  backend/api/routes/regime_sets.py
```

실제 DB 기준 `check_intraday_regime()` 직접 호출:

```text
{'ok': True, 'action': 'skipped', 'reason': 'no_morning_set'}
```

현재 실제 DB에는 2026-05-23 기준 아침 SET 적용 row가 없어 정상 스킵되었다.

임시 DB smoke 테스트:

```text
{'ok': True, 'action': 'switched', 'from_set': 'SET-NEUTRAL', 'to_set': 'SET-RISK_ON', 'from_regime': 'neutral', 'to_regime': 'risk_on', 'vix': 18.5, 'kospi_change': 0.8}
applications= [
  {'set_id': 'SET-NEUTRAL', 'regime_label': 'neutral', 'trigger': 'morning', 'current_flag': 0},
  {'set_id': 'SET-RISK_ON', 'regime_label': 'risk_on', 'trigger': 'intraday', 'current_flag': 1}
]
alerts= [
  {'alert_type': 'regime_transition', 'severity': 'WARNING', 'title': '[장중 레짐 전환] 22:02 neutral → risk_on'}
]
```

스케줄러 등록 확인:

```text
12 [
  'job_intraday_regime_monitor_0930',
  'job_intraday_regime_monitor_1000',
  'job_intraday_regime_monitor_1030',
  'job_intraday_regime_monitor_1100',
  'job_intraday_regime_monitor_1130',
  'job_intraday_regime_monitor_1200',
  'job_intraday_regime_monitor_1230',
  'job_intraday_regime_monitor_1300',
  'job_intraday_regime_monitor_1330',
  'job_intraday_regime_monitor_1400',
  'job_intraday_regime_monitor_1430',
  'job_intraday_regime_monitor_1500'
]
```

API 함수 직접 호출:

```text
{'ok': True, 'date': '2026-05-23', 'application': None, 'transitions': [], 'transition_count': 0}
```

---

## 5. 주의 및 후속 필요

- `system_alerts` 실제 스키마는 INBOX 예시의 `message/is_read`가 아니라 `title/detail/acknowledged`라서 실제 스키마에 맞춰 INSERT했다.
- 이번 범위에서는 INBOX 지시대로 `positions.entry_set_id` 컬럼만 추가했다. 실제 포지션 진입 시 `entry_set_id`를 채우는 로직은 별도 태스크가 필요하다.
- 실제 장중 전환은 `market_snapshots`에 KOSPI 또는 fallback 가능한 최신 등락률 row가 있어야 실행된다.
