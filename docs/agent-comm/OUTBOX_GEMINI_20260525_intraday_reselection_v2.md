# OUTBOX — Frontend : 장중 재선별 시스템 시각화 v2 (Pivot 완료)

작성일: 2026-05-25 (재작성 — Pivot 후)
담당: **Claude Code (Gemini fallback)** — PM 승인 하 일회성 직접 구현

---

## 경위 (요약)

1. Codex 백엔드 작업 중에 **자체 판단으로** console.html(Today Control) + console-intraday-v2.js를 일부 만들어 둠 (INBOX 외 작업)
2. 처음에 Streamlit(`frontend/sections/intraday_reselection.py`)에 페이지 추가 — **잘못된 위치**
3. PM이 "Funnel Monitor에 넣자" 지시 → Pivot
4. Streamlit 변경 제거 + console.html "Today Control"의 카드 제거 + Funnel Monitor로 이동 + Kill Switch 신규 추가

---

## 최종 변경 파일

| 파일 | 변경 유형 | 내용 |
|------|---------|------|
| `frontend/sections/intraday_reselection.py` | **삭제** | Streamlit 페이지 제거 (PM Q1=A) |
| `frontend/app.py` | 수정 (rollback) | import 제거 + sidebar 옵션 제거 |
| `backend/static/console.html` | 수정 | Today Control 카드 2개 제거 + Funnel Monitor에 카드 3개 추가 |
| `backend/static/js/console-navigation.js` | 수정 | today 핸들러에서 호출 제거 + funnel 핸들러에 호출 추가 |
| `backend/static/js/screens/console-intraday-v2.js` | 수정 | Kill Switch 함수 `loadIntradayKillSwitches()` 신규 추가 |
| `backend/static/js/screens/console-funnel-data-health.js` | 수정 | `loadFunnelData()` 새로고침 시 신규 카드 3개도 함께 갱신 |

---

## Funnel Monitor에 추가된 카드 3개

위치: `screen-funnel` 화면 내, 기존 "장중 재선별 이력" 테이블을 교체

### 1. `tc-intraday-reselection-card` — 장중 재선별 타임라인 (Task 1 + 2)
- 5개 슬롯 (`09:30 / 10:30 / 11:30 / 13:00 / 14:00`)
- 슬롯별 상태: ✅ 트리거됨 / ⏭️ 스킵 / 🕒 대기
- 사유 + 신규 후보 수 표시
- **섹터 회전 정보 인라인 표시** (top/bottom sectors + 갭%)
- `loadIntradayReselectionTimeline()` 호출

### 2. `tc-replacement-signal-card` — 포지션 교체 신호 (Task 3)
- 헤더에 총 신호 수 표시 (`N건` 배지)
- 신호별 `<details>` expander
- 보유 종목 ➔ 신규 후보 비교 (점수 0~100 스케일 표시 — PM Q3=OK)
- 사유 텍스트
- **"강제 교체 없음. 트레일링 스탑 발동 시 자연 교체" 안내** (필수 문구)
- `loadReplacementSignals()` 호출

### 3. `tc-kill-switch-card` — Kill Switch (Task 4)
- 4개 토글:
  - `intraday_refresh.master_enabled` (마스터)
  - `intraday_refresh.lunch_slots_enabled` (sub)
  - `intraday_refresh.sector_rotation_enabled` (sub)
  - `intraday_refresh.replacement_signal_enabled` (sub)
- **마스터 OFF 시 sub 토글 disabled**
- 변경 시 즉시 `POST /api/v1/settings` 호출
- 마지막 변경자/시각 표시 (`updated_at`, `updated_by`)
- `loadIntradayKillSwitches()` 호출

---

## 점수 스케일 (PM Q3)

- Backend: 0~1 그대로 저장 (변경 없음)
- Frontend: 표시할 때만 `* 100` 변환 → "85" 형식
- Codex가 만든 코드도 이미 적용됨 (`(sig.current.score * 100).toFixed(0)`)
- 갭(score_gap)은 그대로 % 값 사용

---

## API 호출 매핑

| 카드 | API |
|------|-----|
| 재선별 타임라인 | `GET /api/v1/trading-monitor/reselection-stats?trade_date=YYYY-MM-DD` |
| 교체 신호 | `GET /api/v1/trading-monitor/replacement-signals?trade_date=YYYY-MM-DD` |
| Kill Switch (조회) | `GET /api/v1/settings` |
| Kill Switch (변경) | `POST /api/v1/settings` (`{key, value, value_type: "bool", description}`) |

---

## 호출 트리거

1. 사용자가 사이드바 "Funnel Monitor" 클릭 → `console-navigation.js`가 자동 호출:
   - `loadFunnelData()`
   - `loadIntradayReselectionTimeline(td)`
   - `loadReplacementSignals(td)`
   - `loadIntradayKillSwitches()`
2. "새로고침" 버튼 클릭 → `loadFunnelData()` 내부에서 위 3개 함수 같이 호출

---

## 단위 동작 검증

- `python3 -m py_compile frontend/app.py` → ✅ 통과
- `node -c backend/static/js/console-navigation.js` → ✅ 통과
- `node -c backend/static/js/screens/console-intraday-v2.js` → ✅ 통과
- `node -c backend/static/js/screens/console-funnel-data-health.js` → ✅ 통과
- console.html에 3개 카드 ID 모두 존재 확인

---

## 절대 금지 준수 확인

- ✅ Backend API 응답 구조 그대로 사용
- ✅ 강제 교체 가능 UI 요소 없음
- ✅ 매직넘버 하드코딩 없음 (15% 임계치는 백엔드 설정값)
- ✅ Streamlit 변경 완전 rollback

---

## 알려진 한계 / 후속 결정 필요

1. **Layer 1 탈락 사유 등 기존 Funnel 카드와 시각적 일관성 일부 미흡**: 신규 3개 카드는 별도 디자인 패턴. 향후 통일 가능.
2. **점수 갭(score_gap)의 백엔드 단위**: 백엔드가 `30.7` 같은 % 숫자로 직접 주는지, 0.307로 주는지 확인 필요 (현재 JS는 그대로 % 사용)
3. **Kill Switch 변경 권한**: `/api/v1/settings`가 `require_console_user` 의존성을 가짐 → 로그인 안 한 사용자는 토글 안 됨 (정상 보안 동작)

---

## 다음 단계 (E2E Playwright)

- 시나리오 1: Funnel Monitor 화면 진입 → 3개 카드 표시 확인
- 시나리오 2: 새로고침 버튼 → 모든 카드 갱신
- 시나리오 3: Kill Switch 마스터 OFF → sub 토글 disabled
- 시나리오 4: 빈 데이터 케이스 (오늘 신호 없음 메시지)
- 스크린샷 4장: `tests/e2e/img/funnel_intraday_v2_*.png`
