# OUTBOX: Gemini — 매매 계획 통합 화면 구현 (Set 개념 포함) 완료

**작성:** Gemini (Frontend Agent) 2026-05-23
**상태:** SUCCESS

---

## 1. 수정 파일 목록

1. `backend/static/console.html`
   - 사이드바 "레짐 분석" 제거, "Daily Plan" → "매매 계획" (plan & regime) 변경
   - 모바일 메뉴 및 하단 탭바 레이블 변경 ("매매 계획")
   - `#screen-rulepack` 내부: 오늘의 Regime Set 카드 + 레짐 분석 섹션(`id="dp-regime-analytics-section"`) 추가
   - `#screen-regime-analytics` 섹션 `display:none` 처리
   - 스크립트 버전 업데이트 (cache busting)
2. `backend/static/js/screens/console-daily-plan.js`
   - `loadDailyPlanScreen()`: `/api/v1/regime/today` 호출 및 Set 카드 데이터 렌더링 로직 추가
3. `backend/static/js/screens/console-regime-analytics.js`
   - `loadRegimeAnalyticsScreen()`: 렌더링 타깃을 `#dp-regime-analytics-section` 으로 우선하도록 수정
4. `backend/static/js/console-navigation.js`
   - `showScreen("rulepack")`: `loadDailyPlanScreen()` 와 `loadRegimeAnalyticsScreen()` 을 동시에 호출하도록 변경
5. `backend/static/css/console.css`
   - `#dp-set-settings` (monospace 폰트) 스타일 추가

---

## 2. 통합 화면 DOM 구조 요약 (`#screen-rulepack`)

```html
<section id="screen-rulepack">
  <div class="page-head">... (제목: 매매 계획)</div>
  
  <!-- [NEW] 오늘의 Regime Set 카드 -->
  <div id="dp-regime-set-card" class="card">
    <div id="dp-set-name">...</div>
    <div id="dp-set-regime">...</div>
    <div id="dp-set-reason">...</div>
    <pre id="dp-set-settings">...</pre>
  </div>
  
  <!-- [NEW] 레짐 분석 (통합 섹션) -->
  <div id="dp-regime-analytics-section">
    <!-- console-regime-analytics.js 가 렌더링 -->
  </div>
  
  <!-- [EXISTING] Daily Plan 내용 -->
  <div class="grid cols-4">... (시장 톤, 신규매수 등)</div>
  ...
</section>
```

---

## 3. 확인 사항

- 사이드바에서 "레짐 분석" 버튼이 제거되었으며, "매매 계획" 클릭 시 두 화면의 데이터가 한 번에 로드됨을 확인했습니다.
- `/api/v1/regime/today` 응답이 있을 경우 오늘의 Set 정보(이름, 사유, 점수, 적용 설정)가 카드에 정상 표시됩니다.
- 레짐 분석 화면이 기존 독립 화면이 아닌 매매 계획 화면 내부 섹션에 정상적으로 렌더링됩니다.
- 스크립트 버전 업데이트를 통해 브라우저 캐시 문제를 방지했습니다.
