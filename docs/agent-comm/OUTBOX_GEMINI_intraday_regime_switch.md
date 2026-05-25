# OUTBOX: Gemini — 장중 레짐 전환 UI 구현 완료

**담당:** Gemini (Frontend Agent)  
**완료일:** 2026-05-23

---

## 작업 요약

장중 레짐 SET 전환 기능에 맞춰 Today Control 및 Daily Plan UI를 강화했습니다.

## 변경 사항

### 1. Today Control (`screen-today`) — 레짐 전환 타임라인 추가
- **파일:** `backend/static/console.html`
- **내용:** Morning Brief 카드 하단에 `tc-regime-timeline-card` (레짐 SET 타임라인) 카드 추가.
- **기능:** 
    - 오늘 발생한 모든 레짐 전환 이력을 타임라인 형태로 표시.
    - 현재 적용 중인 SET을 강조 (배지 및 텍스트 굵게).
    - 30초 간격으로 자동 갱신되도록 `console-navigation.js` 수정.

### 2. Daily Plan (`screen-rulepack`) — 미니 타임라인 추가
- **파일:** `backend/static/js/screens/console-daily-plan.js`
- **내용:** `loadDailyPlanScreen()` 내 Regime Set 카드 처리 로직에 미니 타임라인 추가.
- **기능:** 전환 이력이 2개 이상인 경우, 추론 체인(Chain) 하단에 화살표(`→`)로 연결된 미니 타임라인을 표시하여 장중 변화를 한눈에 파악 가능하게 함.

### 3. 스크립트 공통 로직 구현
- **파일:** `backend/static/js/screens/console-daily-plan.js`
- **내용:** `loadTodayRegimeTimeline()` 함수 구현.
- **기능:** `/api/v1/regime/today` API를 호출하여 타임라인 데이터를 가져오고 렌더링.

### 4. 캐시 버스팅 적용
- **파일:** `backend/static/console.html`
- **내용:** `console-navigation.js` 및 `console-daily-plan.js`의 호출 버전을 `v=6`으로 업데이트.

---

## 확인 사항
- [x] Today Control 화면에서 타임라인 카드 정상 노출 여부 (데이터 있을 때만 표시)
- [x] Daily Plan 화면에서 2회 이상 전환 시 미니 타임라인 노출 여부
- [x] JS 구문 오류 및 30초 주기 갱신 로직 확인
