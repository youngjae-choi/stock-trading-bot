# INBOX — Gemini | Coinbase DESIGN.md 기반 UI 테마 오버홀

## 배경
`coinbase/DESIGN.md` 디자인 시스템 기준으로 콘솔 UI 테마를 변경한다.
현재 CSS는 Cursor 디자인 시스템(크림 캔버스 #f7f7f4, 오렌지 #f54e00) 기반이다.

---

## Task 1 — `backend/static/css/console.css` CSS 변수 토큰 교체

`:root` 블록의 CSS 변수를 아래 값으로 교체하라:

```css
:root {
  --bg: #ffffff;
  --panel: #ffffff;
  --panel-2: #f7f7f7;
  --panel-3: #eef0f3;
  --text: #0a0b0d;
  --muted: #7c828a;
  --line: #dee1e6;
  --line-soft: #eef0f3;
  --green: #05b169;
  --green-soft: rgba(5, 177, 105, 0.12);
  --yellow: #f4b000;
  --yellow-soft: rgba(244, 176, 0, 0.13);
  --red: #cf202f;
  --red-soft: rgba(207, 32, 47, 0.12);
  --bad: var(--red);
  --blue: #0052ff;
  --blue-soft: rgba(0, 82, 255, 0.12);
  --primary: #0052ff;
  --primary-active: #003ecc;
  --shadow: none;
  --radius: 24px;
  --radius-sm: 12px;
  --radius-btn: 100px;
  --sidebar: 244px;
  --header: 64px;
  --font: 'Inter', system-ui, 'Helvetica Neue', Arial, sans-serif;
  --font-mono: 'JetBrains Mono', 'Fira Code', monospace;
}
```

`body.dark` 블록은 **수정하지 않는다** (기존 값 유지).

---

## Task 2 — 버튼 border-radius를 pill로 변경

CSS에서 `.btn` 관련 `border-radius` 값을 `var(--radius-btn)` (100px)으로 변경하라.

구체적으로:
- `.btn` — `border-radius: var(--radius-btn);`
- `.btn.primary` — `border-radius: var(--radius-btn); background: var(--primary);`
- `.btn.primary:hover, .btn.primary:active` — `background: var(--primary-active);`
- `.btn.danger` — `border-radius: var(--radius-btn);`
- `.btn.compact` — `border-radius: var(--radius-btn);`

---

## Task 3 — 입력 필드 스타일 업데이트

`input, select, textarea` 스타일:
- `border-radius: var(--radius-sm);` (12px)
- `height: 44px;`
- focus 시: `border-color: var(--primary); border-width: 2px;`

---

## Task 4 — 카드 border-radius 확인

`.card` 클래스의 `border-radius`가 `var(--radius)` (24px)를 사용하는지 확인하고, 하드코딩된 값이 있으면 `var(--radius)`로 교체하라.

---

## Task 5 — 숫자 폰트 적용

`.good`, `.bad` 클래스에 `font-family: var(--font-mono);` 추가하라.

---

## Task 6 — `backend/static/console.html` Google Fonts 업데이트

`<head>` 내 Google Fonts 링크를 아래와 같이 교체 (JetBrains Mono 추가):

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
```

---

## 완료 기준
- [ ] `:root`에 `--primary: #0052ff`, `--bg: #ffffff`, `--radius-btn: 100px` 적용
- [ ] 모든 `.btn` border-radius가 pill (100px)
- [ ] 입력 필드 height 44px, radius 12px
- [ ] `.good`, `.bad`에 JetBrains Mono 적용
- [ ] `console.html`에 JetBrains Mono 폰트 링크 추가
- [ ] `body.dark` 블록은 변경 없음

결과를 `docs/agent-comm/OUTBOX_GEMINI_20260517_coinbase_theme.md`에 작성하라.
