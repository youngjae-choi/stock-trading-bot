# INBOX — Gemini | DESIGN.md 기반 전체 UI 오버홀

## 배경
PM이 `DESIGN.md` (Cursor 디자인 시스템) 규격에 맞게 콘솔 UI 전체를 변경하도록 지시했다.
두 가지 추가 수정도 함께 처리한다.

---

## Task A — 월별 배당금 막대그래프 간격 넓히기

**파일:** `backend/static/js/screens/console-dividend-stats.js`

현재 차트 파라미터:
```js
const W = 480, H = 180, PAD_T = 28, PAD_B = 22, BAR_GAP = 4;
const barW = Math.floor((W - BAR_GAP * 13) / 12);
```

**변경:** BAR_GAP을 4 → 8로, 전체 width도 넓혀서 막대 사이 여백이 시각적으로 더 넓게 보이도록 한다.

아래 값으로 변경하라:
```js
const W = 560, H = 200, PAD_T = 32, PAD_B = 24, BAR_GAP = 8;
const barW = Math.floor((W - BAR_GAP * 13) / 12);
```
SVG viewBox와 height도 W, H에 맞게 업데이트.

---

## Task B — DESIGN.md 기반 전체 CSS 테마 오버홀

**파일:** `backend/static/css/console.css`

### 배경
현재 CSS는 다크 테마 기반(--bg: #0f141b)이고, `body.light`로 라이트모드를 지원한다.
`DESIGN.md`를 읽고 해당 디자인 시스템을 콘솔에 적용하라.

**DESIGN.md 위치:** `DESIGN.md` (프로젝트 루트)

### 적용 규칙

#### 1. 라이트 모드를 기본값(`:root`)으로 변경
DESIGN.md 팔레트를 CSS 변수로 매핑:

| CSS 변수 | DESIGN.md 값 |
|----------|-------------|
| `--bg` | `#f7f7f4` (canvas — 크림 베이지) |
| `--panel` | `#ffffff` (surface-card) |
| `--panel-2` | `#fafaf7` (canvas-soft) |
| `--panel-3` | `#e6e5e0` (surface-strong) |
| `--text` | `#26251e` (ink) |
| `--muted` | `#807d72` (muted) |
| `--line` | `#e6e5e0` (hairline) |
| `--line-soft` | `#efeee8` (hairline-soft) |
| `--green` | `#1f8a65` (semantic-success) |
| `--green-soft` | `rgba(31,138,101,0.12)` |
| `--yellow` | `#c08532` (timeline-done 색 재활용) |
| `--yellow-soft` | `rgba(192,133,50,0.13)` |
| `--red` | `#cf2d56` (semantic-error) |
| `--red-soft` | `rgba(207,45,86,0.12)` |
| `--blue` | `#5b8def` (기존 유지 — DESIGN.md에 blue 없음) |
| `--blue-soft` | `rgba(91,141,239,0.14)` |
| `--primary` | `#f54e00` (Cursor Orange) |
| `--primary-active` | `#d04200` |
| `--shadow` | `none` (DESIGN.md: 그림자 없음, hairline만 사용) |
| `--radius` | `12px` (rounded.lg — cards) |
| `--radius-sm` | `8px` (rounded.md — buttons/inputs) |
| `--font` | `'Inter', system-ui, 'Helvetica Neue', Arial, sans-serif` |

#### 2. 다크 모드 (`body.dark` or `@media prefers-color-scheme: dark`)
현재 `:root`에 있던 다크 팔레트를 `body.dark`로 이동. 기존 `body.light`는 제거.

다크 모드 유지 값 (기존과 동일):
```css
body.dark {
  --bg: #0f141b;
  --panel: #151b24;
  --panel-2: #1b2430;
  --panel-3: #202b38;
  --text: #e7edf5;
  --muted: #8f9bae;
  --line: #2b3646;
  --line-soft: #222c3a;
  --green: #35b779;
  --green-soft: rgba(53,183,121,0.13);
  --yellow: #d9a441;
  --yellow-soft: rgba(217,164,65,0.14);
  --red: #e35d5d;
  --red-soft: rgba(227,93,93,0.14);
  --blue: #5b8def;
  --blue-soft: rgba(91,141,239,0.14);
  --primary: #f54e00;
  --primary-active: #d04200;
  --shadow: 0 12px 36px rgba(0,0,0,0.22);
}
```

#### 3. 버튼 스타일 업데이트
- `.btn.primary`: background `var(--primary)` (#f54e00), color white, border-radius `var(--radius-sm)` (8px)
- `.btn.primary:hover` / `.btn.primary:active`: background `var(--primary-active)` (#d04200)
- `.btn` (기본): background `var(--panel)`, color `var(--text)`, border 1px solid `var(--line)`, border-radius `var(--radius-sm)`
- `.btn.danger`: background `var(--red)` (#cf2d56), color white

#### 4. 카드 스타일 업데이트
- `.card`: background `var(--panel)` (#fff), border 1px solid `var(--line)` (#e6e5e0), border-radius `var(--radius)` (12px), **box-shadow: none**
- 카드 내부 header/title: `color: var(--text)`, font-weight 600

#### 5. 폰트 업데이트
- `--font` 를 Inter 계열로 변경 (위 참조)
- Google Fonts에서 Inter를 로드하려면 `console.html` `<head>`에 아래 추가:
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
```

#### 6. 입력 필드 스타일 업데이트
- `input`, `select`, `textarea`: background `var(--panel)`, border 1px solid `var(--line)`, border-radius `var(--radius-sm)` (8px), height 40px, padding 10px 14px

#### 7. 상단 바 / 사이드바 스타일
- topbar: background `var(--panel)`, border-bottom 1px solid `var(--line)`, **shadow 제거**
- sidebar: background `var(--panel)`, border-right 1px solid `var(--line)`
- 활성 메뉴 항목: background 없이 `var(--primary)` 색상 텍스트 또는 left border accent

#### 8. 그림자 완전 제거
DESIGN.md 원칙: "No drop shadows. Hairlines + ink-on-cream contrast carry the depth."
CSS에서 `box-shadow` 사용하는 모든 곳을 `box-shadow: none` 또는 `border 1px solid var(--line)` 으로 교체.

#### 9. 테이블 스타일 업데이트
- `thead`: background `var(--panel-2)`, border-bottom 1px solid `var(--line)`
- `tbody tr:hover`: background `var(--panel-2)`
- border 색: `var(--line)`

---

## 완료 기준
- [ ] `console.css` — `:root`가 DESIGN.md 라이트 팔레트로 변경됨
- [ ] `console.css` — `body.dark`에 다크 팔레트 보존됨
- [ ] `console.css` — box-shadow 전면 제거, hairline border로 대체됨
- [ ] `console.css` — `.btn.primary`가 Cursor Orange (#f54e00)로 변경됨
- [ ] `console.css` — font를 Inter로 변경
- [ ] `console.html` — Inter Google Fonts 링크 추가
- [ ] `console-dividend-stats.js` — 차트 W/H/BAR_GAP 넓혀짐

결과를 `docs/agent-comm/OUTBOX_GEMINI_20260516_design_md_ui_overhaul.md` 에 작성하라.
