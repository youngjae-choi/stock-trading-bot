# Phase 3 — 콘솔 카운트 라벨링 + L/M/H/T 재배치 결과 보고

**발신: Frontend Agent (Gemini) | 수신: Sisyphus**
**날짜: 2026-05-26**

---

## 작업 개요

Funnel Monitor의 매수대기 라벨을 명확화하고, Today Control의 L/M/H/T 프로파일 분포 블록의 위치를 정정하였습니다.

## 변경 사항 요약

### 1. Funnel Monitor "현재 매수대기" 라벨 명확화 (이슈 ①)
- **파일:** `backend/static/console.html`
  - 카드 타이틀을 `"현재 매수대기"` → `"오늘 BUY 신호 (원본)"`으로 변경.
  - 카드 타이틀에 ⓘ 아이콘과 상세 설명 툴팁(`title` 속성)을 추가했습니다.
  - 카드 하단 설명(`funnel-candidates-detail`)의 초기 텍스트를 Daily Plan과의 차이를 명시하도록 수정했습니다.
- **파일:** `backend/static/js/screens/console-funnel-data-health.js`
  - `loadFunnelData()` 시점에 업데이트되는 `candDetailEl`의 텍스트를 `"S4 원본 BUY 신호 수 (Daily Plan 배정 전)"`로 변경하였습니다.

### 2. Today Control L/M/H/T 블록 재배치 (이슈 ③)
- **파일:** `backend/static/console.html`
  - "보유중"(`fp-positions`) 항목 안에 잘못 배치되어 있던 L/M/H/T 분포 블록을 "오늘 매수 신호"(`fp-signals`) 항목 안으로 이동하였습니다.
  - "보유중" 항목은 이제 숫자만 단독으로 표시됩니다.

### 3. 캐시 버스팅 적용
- **파일:** `backend/static/console.html`
  - `console-funnel-data-health.js` 스크립트 태그에 `?v=1` 파라미터를 추가하여 브라우저 캐시 문제를 예방했습니다.

## 선택사항 및 세부 사항 처리

- **툴팁 추가:** 요구사항대로 카드 타이틀에 `title` 속성을 사용하여 툴팁을 추가하였으며, 시각적 힌트로 `ⓘ` 아이콘을 병기했습니다.
- **빈 fp-positions 처리:** "보유중" 카드는 데이터 소스 부재로 인해 추가 분포 정보 없이 숫자만 표시되도록 두었습니다.

## 검증 결과 및 회귀 확인

- **JS 구문 검사:** `node -c`를 통해 `console-funnel-data-health.js`의 구문 오류 없음을 확인했습니다.
- **코드 리뷰:** 수정된 HTML 구조가 Funnel Progress의 레이아웃을 깨뜨리지 않는지, 이동된 `div`가 올바른 부모 요소 안에 위치하는지 재검토했습니다.
- **회귀 확인:** 다른 카드(`fp-total`, `fp-layer1`, `fp-layer2`)의 ID나 구조는 건드리지 않았으므로 기존 데이터 표시 기능은 유지됩니다.

## 위험 요소

- 특이사항 없습니다. 백엔드 서버는 유지된 상태에서 정적 파일만 안전하게 수정되었습니다.

---
**Sisyphus는 이어서 Playwright E2E 시각 검증을 진행해 주시기 바랍니다.**
