# OUTBOX — Gemini | Coinbase DESIGN.md 기반 UI 테마 오버홀 결과

## 작업 개요
`coinbase/DESIGN.md` 디자인 시스템을 기반으로 콘솔 UI 테마를 성공적으로 업데이트했습니다. 주요 변경 사항은 색상 토큰 교체, 버튼 및 카드 라운딩 처리, 입력 필드 스타일 고도화입니다.

---

## 주요 변경 사항

### 1. `backend/static/css/console.css` 업데이트
- **Task 1: CSS 변수 교체**
  - `:root` 블록의 변수들을 Coinbase 테마에 맞게 교체했습니다.
  - `--primary: #0052ff`, `--radius: 24px`, `--radius-btn: 100px` 등이 적용되었습니다.
- **Task 2: 버튼 스타일 변경**
  - `.btn`, `.btn.primary`, `.btn.danger`, `.btn.compact`의 `border-radius`를 `var(--radius-btn)` (100px)으로 변경하여 Pill 형태를 적용했습니다.
  - `.btn.primary`에 `background: var(--primary)` 및 hover 상태의 `background: var(--primary-active)`를 명시했습니다.
- **Task 3: 입력 필드 스타일 업데이트**
  - `input, select, textarea`의 `height`를 44px로 증대했습니다.
  - focus 시 `border-color: var(--primary)`와 함께 `border-width: 2px`를 적용하여 시인성을 높였습니다.
- **Task 4: 카드 border-radius 확인**
  - `.card`가 `var(--radius)` (24px)를 사용하고 있음을 확인했습니다.
- **Task 5: 숫자 폰트 적용**
  - `.good`, `.bad` 클래스에 `font-family: var(--font-mono)` (JetBrains Mono)를 추가하여 데이터의 가독성을 향상시켰습니다.

### 2. `backend/static/console.html` 업데이트
- **Task 6: Google Fonts 링크 교체**
  - `JetBrains Mono` (400, 500) 폰트를 추가하여 고정폭 폰트 사용을 위한 기반을 마련했습니다.

---

## 완료 기준 체크리스트
- [x] `:root`에 `--primary: #0052ff`, `--bg: #ffffff`, `--radius-btn: 100px` 적용 완료
- [x] 모든 `.btn` 및 관련 클래스의 border-radius를 pill (100px)로 변경 완료
- [x] 입력 필드 height 44px, radius 12px, focus 2px border 적용 완료
- [x] `.good`, `.bad`에 JetBrains Mono 적용 완료
- [x] `console.html`에 JetBrains Mono 폰트 링크 추가 완료
- [x] `body.dark` 블록은 기존 값을 유지 (변경 없음)

---

## 참고 사항
- 작업 전 일부 값이 이미 요청된 값과 일치하는 부분이 있었으나, 누락된 클래스(`.btn.compact`) 및 세부 스타일(focus 2px, font-family 등)을 꼼꼼히 확인하여 최종 반영했습니다.
