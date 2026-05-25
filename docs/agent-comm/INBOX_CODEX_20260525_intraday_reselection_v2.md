# INBOX — Codex (Backend) : 장중 재선별 시스템 보강 v2

작성일: 2026-05-25
요청자: Sisyphus (Claude Code)
PM 승인: ✅ (대화 기록 참조)

---

## 배경

장중 재선별 시스템에 다음 3가지 사각지대가 존재:
1. 점심 이후(12:00~15:20) 재선별 미실시
2. 시장 평균에만 의존 → 섹터/테마 회전 미감지
3. 신규 후보 발견 시 기존 보유 종목 비교/교체 로직 부재

이를 모두 보강한다. **모의 테스트 단계**이며, 모든 매직넘버는 `system_settings` 테이블에 저장하여 추후 SQL/UI로 튜닝 가능하게 한다.

---

## 작업 범위 (Feature 1 + 2 + 3 + Additional 4)

### Feature 1: 점심 이후 재선별 슬롯 추가

**파일**: `backend/services/scheduler.py:1155` 부근

기존 슬롯 리스트에 `13:00`, `14:00` 추가:
```python
for _slot_hhmm, _slot_id in [
    ("09:30", "0930"),
    ("10:30", "1030"),
    ("11:30", "1130"),
    ("13:00", "1300"),  # 신규
    ("14:00", "1400"),  # 신규
]:
    ...
```

**파일**: `backend/services/engine/intraday_refresh.py`
- 동일 트리거 조건(±2~3%) 재사용 — 별도 로직 추가 불필요
- 같은 방향 중복 방지 메커니즘 자동 적용

**완료 기준**:
- [ ] 13:00, 14:00 슬롯이 APScheduler에 등록됨
- [ ] 슬롯 실행 시 기존 로직과 동일하게 트리거 평가
- [ ] 텔레그램 알림 발송 (실행 여부 + 사유)

---

### Feature 2: 섹터 회전 감지

**신규 파일**: `backend/services/engine/sector_rotation.py`

**구현 요구사항**:
1. KIS 거래량 상위 30종목 조회 (기존 `_fetch_market_snapshot()` 결과 재사용)
2. 각 종목에 대해 DB `symbols.sector` 컬럼에서 섹터 정보 조회
3. 섹터별 그룹핑 후 평균 등락률 산출
4. **회전 감지 조건**:
   ```
   상위 2개 섹터 평균 등락률 - 하위 그룹(나머지) 평균 등락률 >= 3.0%
   ```
5. 회전 감지 시 재선별 트리거 (시장 평균 트리거와 OR 결합)

**파일 수정**: `backend/services/engine/intraday_refresh.py:121-152`

기존 트리거 로직에 섹터 회전 트리거 추가:
```python
# 기존: 시장 평균 트리거
# 신규: OR sector_rotation_detected(snapshot)
should_trigger = market_avg_trigger or sector_rotation_trigger
```

**system_settings 키**:
- `intraday_refresh.sector_rotation_threshold` = `3.0` (float, 단위: %)
- `intraday_refresh.sector_rotation_enabled` = `true` (bool, kill switch)

**완료 기준**:
- [ ] `sector_rotation.py`에 `detect_sector_rotation(snapshot)` 함수 정의
- [ ] 회전 감지 시 reason 문자열 생성 (예: "반도체(+4.2%) ↔ 바이오(-1.8%)")
- [ ] 섹터 회전 이력을 DB에 저장 (Additional 3 참조)

---

### Feature 3: 포지션 교체 신호 (B 방식 — 신호만 발생)

**신규 파일**: `backend/services/engine/replacement_signal.py`

**핵심 동작**:
- 재선별 후 신규 후보 점수와 기존 보유 종목 점수 비교
- **신호 조건**: `(신규 후보 점수 - 기존 종목 점수) / 기존 종목 점수 >= 0.15` (15%)
- **신호만 발생**: 강제 매도/매수 없음
- 트레일링 스탑 발동으로 자리가 비면 후보 큐의 우선 종목 자동 진입

**파일 수정**: `backend/services/engine/decision_engine.py:701-754`

`refresh_candidates()` 마지막에 훅 추가:
```python
from .replacement_signal import evaluate_replacement_signals
await evaluate_replacement_signals(
    new_candidates=new_candidates,
    current_positions=position_manager.get_positions()
)
```

**파일 수정**: `backend/services/engine/position_manager.py`

트레일링 스탑 발동 → 매도 후, 후보 큐에 더 높은 점수 종목이 있으면 우선 진입 로직 추가. (현재 신규 후보로 교체)

**system_settings 키**:
- `intraday_refresh.replacement_score_gap` = `0.15` (float, 15%)
- `intraday_refresh.max_replacement_per_symbol` = `1` (int, 종목당 1회)
- `intraday_refresh.max_replacement_per_day` = `5` (int, 하루 5회)
- `intraday_refresh.replacement_signal_enabled` = `true` (bool, kill switch)

**완료 기준**:
- [ ] `replacement_signal.py`에 `evaluate_replacement_signals()` 함수 정의
- [ ] 신호 발생 시 텔레그램 알림 발송 (사유 포함)
- [ ] 종목당 1회/하루 5회 중복 방지
- [ ] 교체 신호 이력 DB 저장 (Additional 1 참조)
- [ ] 신호 발생 정보가 API에 노출됨 (Additional 2 참조)

---

### Additional 1: 교체 신호 이력 DB 저장

**신규 마이그레이션**: `backend/services/migrations/` 에 추가

```sql
CREATE TABLE IF NOT EXISTS replacement_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,
    slot TEXT NOT NULL,
    current_symbol TEXT NOT NULL,
    current_score REAL NOT NULL,
    current_pnl_pct REAL,
    new_symbol TEXT NOT NULL,
    new_score REAL NOT NULL,
    score_gap REAL NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_replacement_signals_date ON replacement_signals(trade_date);
```

**완료 기준**:
- [ ] 마이그레이션 실행 시 테이블 생성
- [ ] `replacement_signal.py`에서 신호 발생 시 INSERT
- [ ] 조회 함수 제공 (`get_replacement_signals(trade_date)`)

---

### Additional 2: 재선별 실행 통계 API + 교체 신호 조회 API

**파일 수정**: `backend/api/routes/trading_monitor.py`

신규 endpoint 2개 추가:

**(1) 재선별 실행 통계**
```
GET /api/v1/trading-monitor/reselection-stats?trade_date=YYYY-MM-DD
응답: {
  "ok": true,
  "payload": {
    "trade_date": "2026-05-25",
    "slots": [
      {"slot": "09:30", "triggered": true, "reason": "...", "new_candidates": 12},
      {"slot": "10:30", "triggered": false, "reason": "noise threshold"},
      ...
    ],
    "sector_rotations": [...],
    "replacement_signals": [...]
  }
}
```

**(2) 교체 신호 조회**
```
GET /api/v1/trading-monitor/replacement-signals?trade_date=YYYY-MM-DD
응답: {
  "ok": true,
  "payload": {
    "signals": [
      {
        "id": 1,
        "slot": "10:30",
        "current": {"symbol": "005930", "name": "삼성전자", "score": 0.65, "pnl_pct": -1.2},
        "new": {"symbol": "035420", "name": "NAVER", "score": 0.85},
        "score_gap": 30.7,
        "reason": "거래량 급증 + 모멘텀 상위",
        "created_at": "..."
      }
    ]
  }
}
```

**완료 기준**:
- [ ] 2개 endpoint가 정상 응답
- [ ] 빈 데이터일 때 빈 배열 반환 (에러 X)

---

### Additional 3: 섹터 회전 이력 로그

**신규 마이그레이션**:
```sql
CREATE TABLE IF NOT EXISTS sector_rotation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,
    slot TEXT NOT NULL,
    top_sectors TEXT NOT NULL,  -- JSON
    bottom_sectors TEXT NOT NULL,  -- JSON
    gap_pct REAL NOT NULL,
    triggered INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

**완료 기준**:
- [ ] 슬롯 실행 시 섹터 분석 결과 무조건 저장 (triggered와 무관)
- [ ] 위 Additional 2 통계 API에 포함

---

### Additional 4: Kill Switch (긴급 비활성화)

**system_settings 키**:
- `intraday_refresh.lunch_slots_enabled` = `true` (bool, Feature 1 끄기)
- `intraday_refresh.sector_rotation_enabled` = `true` (bool, Feature 2 끄기)
- `intraday_refresh.replacement_signal_enabled` = `true` (bool, Feature 3 끄기)
- `intraday_refresh.master_enabled` = `true` (bool, 전체 통합 kill switch)

**구현 요구사항**:
- 각 Feature 진입 시점에 `get_setting()` 확인
- `master_enabled = false` 시 모든 신기능 비활성 (기존 동작 유지)
- 개별 `*_enabled = false` 시 해당 Feature만 비활성

**완료 기준**:
- [ ] 4개 키 모두 system_settings에 자동 등록 (없으면 기본값 true로 생성)
- [ ] kill switch 토글 시 즉시 반영 (재시작 불필요 — 매 호출 시 get_setting)

---

## 텔레그램 알림 형식 (필수 준수)

호출: `from backend.services.alert_service import send_telegram_alert`

### Feature 1 (신규 슬롯 실행)
```
title: "장중 재선별 - 13:00"
body: "✅ 트리거됨 — defensive 전략 중 시장 +2.5% 상승 감지\n신규 후보 12종목, 보유 종목 3개 유지"
```
또는 (스킵 시):
```
title: "장중 재선별 - 13:00"
body: "⏭️ 스킵 — 시장 평균 +0.3% (임계치 미달)"
```

### Feature 2 (섹터 회전)
```
title: "섹터 회전 감지 - 14:00"
body: "🔄 반도체(+4.2%), 2차전지(+3.1%) ↔ 바이오(-1.8%), 통신(-1.2%) (갭 5.4%)\n재선별 트리거됨. 신규 후보 8종목."
```

### Feature 3 (교체 신호)
```
title: "교체 신호 발생"
body: "📊 현재 보유: 삼성전자(005930) 점수 0.65, 손익 -1.2%\n🎯 신규 후보: NAVER(035420) 점수 0.85 (+30.7%)\n사유: 거래량 급증 + 모멘텀 상위\n※ 강제 교체 없음. 트레일링 스탑 발동 시 자연 교체."
```

---

## 완료 기준 (전체)

1. **API 호출 테스트**
   - `GET /api/v1/trading-monitor/reselection-stats` 200 OK
   - `GET /api/v1/trading-monitor/replacement-signals` 200 OK
   - 빈 데이터 케이스 정상 처리

2. **단위 동작 검증**
   - 13:00 슬롯 cron 등록 확인 (APScheduler print)
   - `detect_sector_rotation()` 모의 데이터로 임계치 트리거 검증
   - `evaluate_replacement_signals()` 모의 데이터로 15% 갭 검증

3. **E2E 테스트 (Playwright)** — 별도 INBOX로 추가 지시 예정 (이 INBOX 완료 후)

4. **빌드 검증** — 배포 스크립트 에러 0개

5. **문서 업데이트** — `docs/manual/intraday_reselection_v2.md` 신규 작성:
   - 8개 system_settings 키 목록 + 기본값 + 설명
   - 트리거 조건 요약
   - 텔레그램 알림 형식

---

## 작업 순서 권장

1. system_settings 키 등록 (default 값 자동 생성 로직)
2. DB 마이그레이션 2개 (replacement_signals, sector_rotation_log)
3. Feature 1 (가장 단순 — 슬롯 추가)
4. Feature 2 (sector_rotation.py + intraday_refresh.py 통합)
5. Feature 3 (replacement_signal.py + decision_engine.py + position_manager.py)
6. Additional 1, 3 (이력 저장은 Feature 2, 3에 통합되어 거의 완료됨)
7. Additional 2 (API endpoint 추가)
8. Additional 4 (kill switch 검증 — 각 Feature에 통합)
9. 텔레그램 알림 검증
10. 문서 작성

---

## 출력 (OUTBOX) 요구사항

작업 완료 후 `docs/agent-comm/OUTBOX_CODEX_20260525_intraday_reselection_v2.md` 에 다음 작성:
- 변경 파일 전체 목록
- 신규 system_settings 키 목록 + 기본값
- 신규 API endpoint 목록
- 신규 DB 테이블 목록
- 발견된 이슈 / 위 INBOX와 다르게 구현한 부분 / PM에게 추가 결정 요청 사항
- 단위 동작 검증 결과 요약

---

## 절대 금지

- 강제 매도/매수 로직 추가 금지 (Q2=B 결정 사항)
- 매직넘버를 코드에 하드코딩 금지 — 반드시 system_settings 키로 노출
- 기존 09:30/10:30/11:30 슬롯 동작 변경 금지
- 기존 트리거 임계치 변경 금지 (defensive +2.0, aggressive -2.0, neutral ±3.0 유지)
