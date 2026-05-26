# 자동 등록 종목 트레일링 제외 + 60초 sync 운영 로그 보강

**발신: Sisyphus | 수신: Codex (Backend Executor)**
**날짜: 2026-05-26**
**우선순위: P1 — Bug B 후속 정책 확정**

---

## 배경

직전 commit `2fb93a5`에서 KIS 실계좌를 SSOT로 통일하면서 `sync_account_position()`이 KIS-only 보유 종목을 `LOW_VOL` fallback profile로 position_manager에 자동 등록하도록 했다. PM 정책 확정:

1. **PM은 수동 매수를 절대 안 한다** — 자동 등록 시나리오는 어제 미체결→오늘 체결, 시스템 재시작 후 복원 누락 등 시스템적 케이스만 잡는 안전장치
2. **자동 등록 종목은 매수 의도 정보가 없으므로** 트레일링은 비활성. 단 LOW_VOL 초기 손절 감시는 유지하고, 15:20 KST 강제 청산도 적용 (당일매매 원칙)
3. **60초 sync 운영 데이터를 며칠 모은 뒤** rate limit / 주기 조정 결정. 그러려면 로그가 분석 친화적이어야 함

---

## 구현 범위 (2개 항목)

### 항목 A — 자동 등록 종목 트레일링 비활성 (옵션 C)

**파일:** `backend/services/engine/position_manager.py`, `backend/services/engine/decision_engine.py` (또는 S8 로직 위치)

**요구사항:**

1. **`PositionManager.sync_account_position()`이 등록하는 종목에 flag 부여**:
   - position dict에 `"auto_imported": True` 필드 추가 (직접 register/매수로 들어온 종목은 `False` 또는 미존재)
   - 다른 모든 정상 진입 경로(`register_after_fill` 등)는 명시적으로 `False` 또는 flag 미설정

2. **S8 트레일링 로직에서 이 flag 검사**:
   - `auto_imported=True`인 종목은 트레일링 stop 갱신 **비활성**
   - 초기 손절선(LOW_VOL fallback의 -2.0%)은 **그대로 적용** — 손실 방어 안전장치는 유지
   - 15:20 KST 강제 청산(S9)은 **그대로 적용** — 당일매매 원칙 일관성

3. **추가 안전장치 (Executor 재량)**:
   - 트레일링 분기 진입 시 `auto_imported` 종목이라면 명확한 로그 출력 (왜 트레일링 안 했는지 분석 가능하도록)
   - S9 청산 시에도 `auto_imported` 여부를 로그/메타데이터에 남김

**검증 시나리오:**
- pytest: mock으로 `sync_account_position(...)` 호출 후 position의 `auto_imported=True` 확인
- pytest: 그 position에 tick 들어와도 trailing stop 미갱신, 손절선은 -2%에서 발동 검증
- pytest: S9 청산 시 정상 처리되는지 검증

---

### 항목 B — 60초 sync 운영 분석용 로그 보강

**파일:** sync 호출이 일어나는 위치 (대략 `backend/services/engine/decision_engine.py`의 60초 주기 sync 부분)

**요구사항:**

분석 친화적 **구조화 로그**로 다음 정보를 기록. `logger.info` 사용, 메시지에 키=값 쌍 또는 JSON 한 줄 (Executor 재량).

#### 1. 매 sync 단위 로그
- `START: PositionSync trade_date=YYYY-MM-DD seq=N` — 시작 시각
- `SUCCESS: PositionSync seq=N kis_response_ms=XXX kis_symbols=N managed_before=N managed_after=N added=[...] removed=[...] qty_changed=[(sym,old,new),...] ws_resub=bool elapsed_ms=XXX`
- `SKIP: PositionSync seq=N reason=...` — engine 비활성 / 토큰 만료 등

#### 2. Rate Limit 로그 강화
- 기존 `RETRY: KIS API error code=EGW00201` 로그는 이미 있음
- 추가 요구: sync 함수에서 EGW00201을 만나면 별도 counter 증가, sync 끝날 때 `rate_limit_hits=N` 포함
- 만약 30분 누적 EGW00201이 임계값 (예: 50) 초과하면 `WARN: KIS rate_limit pressure high last_30m_hits=N` 로그

#### 3. 자동 등록 발생 이벤트 로그
- `sync_account_position()` 호출되는 시점:
  - `EVENT: position auto_imported symbol=XXXXXX name=YYYY qty=N entry_price=XXX profile=LOW_VOL detection_reason=kis_only_holding`

#### 4. Sync 실패 로그
- KIS 잔고 조회 실패: `FAIL: PositionSync seq=N reason=kis_balance_error exc=...`
- 토큰 만료 / WS 재시작 실패 등 케이스 구분

**왜 이렇게 자세히?**
- PM이 며칠 후 `grep "PositionSync" logs/*.log | awk '...'`로 sync 빈도, KIS 응답 시간 분포, rate limit hit 추이를 쉽게 분석할 수 있어야 함
- 자동 등록 이벤트는 `grep "auto_imported"`로 모니터링 가능해야 함

---

## 변경 파일 목록

| 파일 경로 | 변경 유형 | 변경 이유 |
|-----------|-----------|-----------|
| `backend/services/engine/position_manager.py` | `auto_imported` flag 추가 | 항목 A |
| `backend/services/engine/decision_engine.py` | 트레일링 분기 + sync 로그 보강 | 항목 A + B |
| `tests/unit/test_position_monitoring.py` | 새 시나리오 단위 테스트 | 검증 |

---

## 완료 기준

1. **항목 A pytest 통과**: 자동 등록 종목에 트레일링 미적용 + 손절선/S9 정상 동작 검증
2. **항목 B 로그 출력 확인**: 단위 테스트 또는 mock 실행에서 위 로그 패턴들이 실제 출력됨을 확인
3. **기존 정상 진입 경로 회귀 없음**: 일반 자동매매 종목은 `auto_imported=False` 또는 미설정으로 트레일링 정상 동작
4. **빌드 검증**: `py_compile` + `pytest tests/unit/test_position_monitoring.py` 통과

---

## 주의사항

- **백엔드는 살아있는 상태**다. 코드 변경 중 import side-effect나 동작 변경 주의. DB 마이그레이션이나 schema 변경은 금지. systemd가 파일 수정 시 자동 reload 하지 않으므로 변경은 다음 재시작 시 반영된다.
- 로그 패턴은 분석 친화적이어야 하므로 메시지 포맷을 일관되게 유지. `key=value` 또는 JSON 둘 중 하나 선택. 혼용 금지.

---

## OUTBOX 작성 요청

`docs/agent-comm/OUTBOX_CODEX_20260526_auto_imported_flag.md`에 보고:

1. 항목 A 구현 요약 + diff 핵심
2. 항목 B 로그 패턴 예시 (실제 출력될 메시지 샘플 3-5개)
3. 단위 테스트 결과 (pytest 출력 요약)
4. 변경된 파일 목록과 라인 수
5. 위험 요소 (있으면)

작업 완료 후 Sisyphus가 코드 리뷰 + 백엔드 재시작 + 회귀 E2E 진행.
