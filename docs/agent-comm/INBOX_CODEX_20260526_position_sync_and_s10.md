# 콘솔 카운트 불일치 fix + S10 EOD 배치 복구

**발신: Sisyphus | 수신: Codex (Backend Executor)**
**날짜: 2026-05-26**
**우선순위: P0 — 실거래 안전성 직결**

---

## 배경

PM 보고로 4가지 데이터 불일치 발견. Phase 1 진단 완료. 그 중 코드 수정이 필요한 3가지 항목을 한 번에 처리.

특히 어제(2026-05-25) S10 후처리가 발동되지 않아 미진입 26건이 전혀 추적되지 않았고, Sisyphus가 backfill을 수동 실행해서 **11건이 EOD +2% 이상 상승**한 것을 확인 (062970 +29.9%, 011230 +29.85% 등). 학습 루프(`project_auto_learning_loop`)가 차단된 상태였음.

---

## 구현 범위 (3개 항목)

### 항목 1 — Bug A: `funnel.py:139` import 경로 오타 (P0, 1글자 수정)

**파일:** `backend/api/routes/funnel.py:139`

**증상:** `/api/v1/funnel/summary`의 `positions_count`가 항상 0 반환. `/api/v1/bot/overview`의 `open_positions`와 같은 값을 반환해야 하지만, import 실패로 `except Exception: pass` 폴백.

**확인:**
```python
# funnel.py는 backend/api/routes/ 위치
# .  = backend.api.routes
# .. = backend.api
# ...= backend
# 같은 파일 line 13-14는 ...services.db 사용 (점 3개)
# 그런데 line 139만 ..services.engine.position_manager (점 2개)
```

**수정:**
```python
# 변경 전 (line 139)
from ..services.engine.position_manager import position_manager

# 변경 후
from ...services.engine.position_manager import position_manager
```

**검증:**
- `python3 -c "from backend.api.services.engine.position_manager import position_manager"` → ModuleNotFoundError (현재)
- `python3 -c "from backend.services.engine.position_manager import position_manager"` → 성공

수정 후 백엔드 재시작하고 `/api/v1/bot/overview`의 `open_positions`와 `/api/v1/funnel/summary`의 `positions_count`가 같은 값을 반환하는지 확인.

---

### 항목 2 — Bug B: position_manager ↔ KIS 실계좌 SSOT 통일 (P0)

**배경:**
- `position_manager._sync_managed_positions_with_account()` ([decision_engine.py:175-218](backend/services/engine/decision_engine.py#L175-L218))는 **S6 활성화 시 1회만** 실행되며, 기존 관리 포지션의 수량만 업데이트하고 **KIS에만 있고 메모리에 없는 종목은 추가하지 않음**.
- 결과: 운영자가 KIS HTS로 직접 산 종목, 또는 어제 미체결 → 오늘 체결된 종목 등이 `position_manager`에 없어 콘솔에 안 보임.
- 실거래 위험: S7이 "보유 종목"으로 인지 못 해 **중복 매수**, S8이 손절선 감시에서 누락.

**PM 결정:** KIS 실계좌를 SSOT로.

**수정 방향 (Executor 재량 + 보고):**

1. **`_sync_managed_positions_with_account()` 정책 변경**: KIS에 있고 메모리에 없는 종목도 `position_manager`에 자동 등록. 단, 자동 등록된 종목은 기본 risk_profile을 어떻게 설정할지 결정 필요(아마 매수 시점 정보가 없으니 보수적으로 `LOW_VOL` 또는 별도 `IMPORTED` 프로파일).
2. **주기적 sync 추가**: S6 활성화 시 1회만이 아니라 일정 주기로 (예: 1분마다 또는 매 매수/매도 직후) KIS 잔고와 position_manager를 sync.
3. **자동 등록된 종목의 S8 손절선 처리**: 매수가 정보가 없으므로 KIS의 평균매입가를 entry_price로 사용. 손절선은 active Risk Profile Pack의 기본값 적용.

**검토 요청 사항 (Codex가 구현 전 OUTBOX에 답변):**
- 위 (1), (2), (3)에 대한 구체적 구현 방안과 트레이드오프
- KIS API rate limit 고려한 sync 주기
- 자동 등록된 종목을 S7이 신규 매수 후보에서 제외하는 로직 추가 여부

**관련 파일:**
- `backend/services/engine/position_manager.py:354` — 싱글톤
- `backend/services/engine/decision_engine.py:175-218` — `_sync_managed_positions_with_account`
- `backend/api/routes/trading_monitor.py:539-603` — 현재 KIS 잔고 직접 조회 (참고 모델)

---

### 항목 3 — 이슈 ④: S10 EOD 배치 미실행 원인 확정 + 무거래일 가드 (P0)

**증상:** 어제(2026-05-25) 15:20에 `job_postprocess_pipeline`이 발동되지 않음.

**증거 (server.log):**
- 15:10~15:25 시간대 로그에 `START: [PostProcess]` 시작 메시지 없음
- 스케줄러는 running, jobs=23으로 정상
- `schedule_skip_today=false` (실행 허용)
- 어제 시점 `basis_source=last_available_pipeline_data, last actual trading day=2026-05-22` (어제는 매매 신호 없음)

**원인 후보 (Codex가 확정):**
- a) APScheduler misfire / 서버 재시작 누락
- b) `_apply_market_open_schedule_guards()` 가드가 어제 postprocess를 skip시켰을 가능성 ([scheduler.py 근처 검색](backend/services/scheduler.py))
- c) 무거래일 자동 skip 설계 (의도적이라면 정상, 그러나 미진입 추적이 누락되는 부작용)

**조치 요구사항:**
1. **원인 a/b/c 중 어느 것인지 확정** (server.log 분석, scheduler 코드 트레이스).
2. **무거래일에도 `update_missed_returns()`는 반드시 실행되도록 보장**:
   - 매매가 없어도 미진입 종목은 기록되므로 추적 수익률 계산은 필요
   - 옵션: `job_postprocess_pipeline()` 안에서 S9/S10 review는 skip하되 `update_missed_returns()`는 항상 실행되도록 분리, 또는
   - 새로운 독립 job `job_missed_returns_update()` 추가 (예: 15:35 KST cron)
3. **misfire 방지**: APScheduler `misfire_grace_time` 설정 적정값 확인 (서버 재시작 등으로 누락된 job 보호).

**참고:** Sisyphus가 어제분(2026-05-25) `update_missed_returns()`는 이미 수동 backfill 완료 (updated=26). 결과: 11건 improvement_candidate, 최고 062970 EOD +29.9%.

---

## 변경 파일 목록

| 파일 경로 | 변경 유형 | 변경 이유 |
|-----------|-----------|-----------|
| `backend/api/routes/funnel.py` | 1글자 수정 (line 139) | Bug A — import 경로 오타 |
| `backend/services/engine/position_manager.py` | 신규 sync 메소드 추가 가능 | Bug B — KIS SSOT 통일 |
| `backend/services/engine/decision_engine.py` | `_sync_managed_positions_with_account` 정책 변경 | Bug B |
| `backend/services/scheduler.py` | postprocess job 분리 또는 misfire 가드 | 이슈 ④ |

---

## 요구사항 대조표

| 요구사항 항목 | 계획서 반영 여부 | 비고 |
|---------------|-----------------|------|
| Bug A funnel.py import fix | ✓ | 1글자 |
| Bug B KIS SSOT 통일 | ✓ | 사전 설계안 OUTBOX 요청 |
| 이슈 ④ 원인 확정 | ✓ | a/b/c 후보 중 확정 |
| 이슈 ④ 무거래일 가드 | ✓ | update_missed_returns 분리 |
| 어제분 backfill | N/A | Sisyphus 직접 완료 (26건) |
| 이슈 ① 라벨링 | ✗ | Phase 3에서 별도 처리 |
| 이슈 ③ UI 재배치 | ✗ | Phase 3에서 별도 처리 |

---

## 완료 기준

1. **funnel.py:139 import 수정** + 백엔드 재시작 + `/api/v1/funnel/summary` 호출하여 `positions_count`가 `/api/v1/bot/overview`의 `open_positions`와 일치
2. **position_manager KIS sync 구현**: KIS HTS에 직접 종목 추가 후 콘솔에 해당 종목이 "현재 포지션"에 자동 등장
3. **postprocess job 원인 확정 + 무거래일 가드**: 어제처럼 매매 신호 없는 날에도 `update_missed_returns()` 자동 실행되는지 시나리오 검증
4. **회귀 테스트**: 기존 매매 정상일(2026-05-22 등)에 S9 → S10 → missed_returns 흐름 정상 동작 확인
5. **빌드 검증** + **API smoke 통과**

---

## OUTBOX 작성 요청

`docs/agent-comm/OUTBOX_CODEX_20260526_position_sync_and_s10.md`에 다음 항목 보고:

1. **항목 1 fix 완료** — 변경 라인 / 검증 결과
2. **항목 2 설계안** — Codex가 검토한 (1)(2)(3) 구현 방안과 트레이드오프. 구현 전 PM 승인 필요한 사항이 있으면 명시.
3. **항목 3 원인 확정** — a/b/c 중 어느 것인지 + 어떻게 결론지었는지 (로그 인용 / 코드 인용)
4. **변경 파일 diff 요약** — 핵심 변경점만 (5-10줄)
5. **회귀 테스트 결과** — pytest/api_smoke 결과
6. **위험 요소** — 이번 변경으로 깨질 가능성 있는 기존 기능 (있다면)

작업 완료 후 Sisyphus가 코드 리뷰 + 백엔드 재시작 + Playwright E2E 검증을 진행한다.
