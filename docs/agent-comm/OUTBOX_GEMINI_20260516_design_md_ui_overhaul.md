# OUTBOX — Gemini | DESIGN.md 기반 전체 UI 오버홀 완료 보고

## 작업 요약
`DESIGN.md` 규격 및 PM 지시에 따라 콘솔 UI 전체를 오버홀하고 요청된 추가 수정을 완료함.

## 작업 상세

### Task A — 월별 배당금 막대그래프 간격 넓히기
- **대상:** `backend/static/js/screens/console-dividend-stats.js`
- **결과:** 이미 요청된 값(`W=560, H=200, BAR_GAP=8`)으로 구현되어 있음을 확인. SVG `viewBox`와 `height` 역시 변수를 사용하여 동적으로 적용되고 있음을 검증함.

### Task B — DESIGN.md 기반 전체 CSS 테마 오버홀
- **대상:** `backend/static/css/console.css`, `backend/static/console.html`
- **결과:**
    1. **기본 테마 변경:** `:root`를 DESIGN.md의 라이트 팔레트(Cream Canvas #f7f7f4, Ink #26251e 등)로 설정.
    2. **다크 모드:** 기존 다크 팔레트를 `body.dark`로 이동 및 보존. `body.light` 스타일 제거.
    3. **그림자 완전 제거:** `--shadow`를 `none`으로 설정하고, `.card` 및 `.login-panel`의 `box-shadow` 속성을 `none`으로 명시하여 Hairline border만 남김.
    4. **버튼 스타일:** `.btn.primary`를 Cursor Orange (#f54e00)로 변경하고, `border-radius: 8px` 적용.
    5. **카드 및 테이블:** `.card`에서 그림자를 제거하고 Hairline border 강조. 테이블 `thead`에 `border-bottom: 1px solid var(--line)` 및 `tr:hover` 시 `var(--panel-2)` 배경색 적용.
    6. **내비게이션:** 활성 메뉴 항목(`.nav button.active`)에 배경색을 제거하고 `var(--primary)` 텍스트 색상 및 `border-left` 액센트 적용.
    7. **폰트:** `console.html`에 Inter 구글 폰트 링크가 이미 존재함을 확인하였으며, CSS의 `--font`를 Inter 계열로 유지.

## 완료 체크리스트
- [x] `console.css` — `:root`가 DESIGN.md 라이트 팔레트로 변경됨
- [x] `console.css` — `body.dark`에 다크 팔레트 보존됨 (그림자 제외)
- [x] `console.css` — box-shadow 전면 제거, hairline border로 대체됨
- [x] `console.css` — `.btn.primary`가 Cursor Orange (#f54e00)로 변경됨
- [x] `console.css` — font를 Inter로 유지
- [x] `console.html` — Inter Google Fonts 링크 확인됨
- [x] `console-dividend-stats.js` — 차트 W/H/BAR_GAP 확장 확인됨
