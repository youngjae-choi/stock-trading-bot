# Phase 3 — 콘솔 카운트 라벨링 + L/M/H/T 재배치

**발신: Sisyphus | 수신: Frontend Agent (Gemini)**
**날짜: 2026-05-26**
**우선순위: P1 — 사용자 혼동 해소**

---

## 배경

PM이 콘솔 4개 화면에서 카운트가 안 맞는다고 보고. Phase 1~2에서 백엔드 버그(이슈 ②, ④)는 이미 fix 완료. 남은 2개는 순수 UI 문제:

- **이슈 ①** — Funnel Monitor "현재 매수대기 6" vs Trading Monitor "매수대기 3종목" 라벨이 같은 단어를 쓰는데 다른 것을 셈. 운영자가 어느 숫자가 진실인지 헷갈림.
- **이슈 ③** — Today Control의 Funnel Progress에서 L/M/H/T 분포가 "보유중" 카드 안에 표시되어 마치 보유 종목의 프로파일 분포처럼 보임. 실제로는 "오늘 매수 신호" 프로파일 분포임.

---

## 구현 범위

### 항목 1 — Funnel Monitor "현재 매수대기" 라벨 명확화 (이슈 ①)

**파일:** `backend/static/console.html` (대략 line 598)

**현재:**
```html
<div class="card compact">
  <div class="card-title">현재 매수대기</div>
  <div class="metric" id="funnel-candidates">-</div>
  <div class="muted" id="funnel-candidates-detail">미수집·대기: S4 결과 확인 전</div>
</div>
```

**데이터 출처:** `funnel.signals_count` = `SELECT COUNT(*) FROM trading_signals WHERE signal_type='BUY'` (S4가 만든 모든 BUY 신호 원본 카운트)

**Trading Monitor 화면과의 차이:**
- Trading Monitor "매수대기 N종목"은 Daily Plan에 배정된 후보만 카운트 (=3)
- Funnel Monitor "현재 매수대기"는 Daily Plan 배정 전 원본 신호 (=6)

**수정 요구:**
1. 카드 타이틀을 "오늘 BUY 신호 (원본)" 또는 "S4 BUY 신호" 로 변경 (전자 선호)
2. 카드 description 영역(`#funnel-candidates-detail`)에 차이 설명 추가:
   - `"Daily Plan 배정 전 S4 원본 신호. Trading Monitor의 매수대기와 다를 수 있음."`
3. 가능하면 카드 옆에 작은 ⓘ 아이콘 + hover 툴팁으로 더 상세한 설명:
   - `"이 값은 S4 하이브리드 스크리닝이 생성한 모든 BUY 신호 수입니다. Daily Plan이 일부 종목을 제외하면 Trading Monitor에서는 더 적게 표시됩니다."`
4. JS 쪽 ([console-funnel-data-health.js:219](backend/static/js/screens/console-funnel-data-health.js#L219))의 `candDetailEl` 텍스트도 동일 맥락으로 업데이트:
   - 현재: `'오늘 생성된 BUY 신호 수'` 또는 `'데이터 없음: 오늘 BUY 신호 없음'`
   - 변경: `'S4 원본 신호 수 (Daily Plan 배정 전)'` 등

**스타일 가이드:** 기존 카드와 일관된 디자인. 새 색상/폰트 사용 자제. 툴팁은 기존 ⓘ 패턴 있으면 따르고, 없으면 단순 `title` 속성으로.

---

### 항목 2 — Today Control L/M/H/T 블록 재배치 (이슈 ③)

**파일:** `backend/static/console.html` (line 237-252 근처)

**현재 (잘못된 위치):**
```html
<div class="funnel" id="funnelProgress">
  <div class="funnel-step"><strong id="fp-total">-</strong><span>전체 종목</span></div>
  <div class="funnel-step"><strong id="fp-layer1">-</strong><span>Layer 1 Universe</span></div>
  <div class="funnel-step"><strong id="fp-layer2">-</strong><span>Layer 2 후보</span></div>
  <div class="funnel-step"><strong id="fp-signals">-</strong><span>오늘 매수 신호</span></div>
  <div class="funnel-step">
    <strong id="fp-positions">-</strong><span>보유중</span>
    <div style="display:flex; gap:8px; flex-wrap:wrap; font-size:10px; margin-top:6px; padding-top:6px; border-top:1px solid var(--line);">
      <span><span style="color:#6cb6ff;">L</span> <strong id="tc-low-vol-count">-</strong></span>
      <span><span style="color:#3fb950;">M</span> <strong id="tc-mid-vol-count">-</strong></span>
      <span><span style="color:#d29922;">H</span> <strong id="tc-high-vol-count">-</strong></span>
      <span><span style="color:#f85149;">T</span> <strong id="tc-theme-spike-count">-</strong></span>
    </div>
  </div>
</div>
```

**문제:** L/M/H/T 분포(`tc-low-vol-count` 등)는 `daily_trading_plans.symbol_assignments`에서 오는 데이터 = **오늘 매수 신호의 프로파일 분포**다. 그런데 "보유중" 카드 안에 들어있어서 마치 보유 종목 분포처럼 보임.

**검증 데이터:**
- 스크린샷 예: `보유중 0`, `L0 M1 H2 T0` (합 3) — 합 3은 `오늘 매수 신호 3`과 일치 (보유중 0과 불일치)

**수정 요구:**

L/M/H/T 블록을 **fp-signals (오늘 매수 신호)** funnel-step 안으로 이동:

```html
<div class="funnel" id="funnelProgress">
  <div class="funnel-step"><strong id="fp-total">-</strong><span>전체 종목</span></div>
  <div class="funnel-step"><strong id="fp-layer1">-</strong><span>Layer 1 Universe</span></div>
  <div class="funnel-step"><strong id="fp-layer2">-</strong><span>Layer 2 후보</span></div>
  <div class="funnel-step">
    <strong id="fp-signals">-</strong><span>오늘 매수 신호</span>
    <!-- 이동: L/M/H/T 프로파일 분포 (Daily Plan symbol_assignments) -->
    <div style="display:flex; gap:8px; flex-wrap:wrap; font-size:10px; margin-top:6px; padding-top:6px; border-top:1px solid var(--line);">
      <span><span style="color:#6cb6ff;">L</span> <strong id="tc-low-vol-count">-</strong></span>
      <span><span style="color:#3fb950;">M</span> <strong id="tc-mid-vol-count">-</strong></span>
      <span><span style="color:#d29922;">H</span> <strong id="tc-high-vol-count">-</strong></span>
      <span><span style="color:#f85149;">T</span> <strong id="tc-theme-spike-count">-</strong></span>
    </div>
  </div>
  <div class="funnel-step"><strong id="fp-positions">-</strong><span>보유중</span></div>
</div>
```

**추가 고려:** fp-positions 자체에도 보유 종목 분포를 보여주고 싶을 수도 있지만, 그건 별도 데이터 소스가 필요하므로 이번엔 라벨/위치 정정만 진행. 빈 카드는 그대로 두기.

---

## 변경 파일 목록

| 파일 경로 | 변경 유형 | 변경 이유 |
|-----------|-----------|-----------|
| `backend/static/console.html` | 텍스트 + 블록 이동 | 이슈 ① 라벨, 이슈 ③ L/M/H/T 재배치 |
| `backend/static/js/screens/console-funnel-data-health.js` | 텍스트 (line 219 근처) | 이슈 ① 카드 설명 텍스트 갱신 |

**캐시 버스팅:** 변경된 JS 파일이 있으면 `console.html` 끝부분의 `?v=N` 쿼리 파라미터를 +1 증가시켜 브라우저 캐시 우회. 다만 console.html은 캐시 버스팅 대상이 아니므로 그냥 둠.

---

## 요구사항 대조표

| 요구사항 항목 | 계획서 반영 여부 |
|---------------|-----------------|
| 이슈 ① 라벨 변경 + 설명 추가 | ✓ |
| 이슈 ① 툴팁(선택사항) | △ (가능하면) |
| 이슈 ③ L/M/H/T → fp-signals로 이동 | ✓ |
| 이슈 ③ 빈 fp-positions 처리 | △ (별도 데이터 없음, 그대로 둠) |

---

## 완료 기준

1. **이슈 ① UI 확인**: Funnel Monitor 화면에서 카드 타이틀이 "오늘 BUY 신호 (원본)"으로 표시. 설명 텍스트에 Daily Plan 차이 명시.
2. **이슈 ③ UI 확인**: Today Control의 Funnel Progress에서 L/M/H/T 분포가 "오늘 매수 신호" 카드 아래에 표시됨. "보유중" 카드 아래에는 분포 없음.
3. **브라우저 강제 새로고침 (Ctrl+Shift+R) 후 정상 표시** 확인.
4. **JS 콘솔 에러 없음** (DevTools Console 탭에서 빨간 에러 0건).
5. **기존 기능 회귀 없음**: 다른 카드(전체 종목, Layer 1, Layer 2, 보유중)의 숫자 표시 정상.

---

## OUTBOX 작성 요청

`docs/agent-comm/OUTBOX_FRONTEND_20260526_count_label_ui.md`에 다음 보고:

1. **변경 파일 diff 요약** (5-10줄)
2. **선택사항 처리 여부** — 툴팁 추가했는지, 추가 안 했으면 이유
3. **회귀 확인** — 다른 카드 정상 표시 확인 방법
4. **위험 요소** — 있다면

Sisyphus가 이어서 Playwright E2E + 시각 검증(스크린샷 비교)을 진행한다.
