# Today Control · Funnel UI 정돈 — 개발계획서 v0.1

## 원본 요구사항 (PM 발화 그대로 인용)

> 1. Today Control 화면
> - 아침브리핑은 조회후 DB에 저장해서 최소 1회는 모르지만 그 이후 부터는 DB에서 그 결과를 호출해서 화면에 표기해
> - 아침브리핑 카드왼쪽에 오렌지 줄은 없애죠 다른 카드와 동일한 UI를 유지
> - 레짐 카드도 일단 카드 프레임을 그냥 보여준채 DATA가 추가 추가되면 채워주는 형태로 하고 이또한 마찬가지로 실기간으로 메번 조회해야 하는 DATA가 아니니까 DB에 저장해서 표시해줘.
>
> 2. funnel 화면
> - "장중 선별 타임라인 모멘텀 스캔 · 장중 재선별 유입 이력" 카드에서는 모멘텀 스캔 내용만 남기고 재선별된 종목은 화면 아래 리스트를 보여주는 것으로 하고 재 선별 종목에 재선별 뱃지를 달아죠

> (3번 Daily Results/Trade Review 버그는 **별도 계획서**로 분리 — PM 결정 2026-06-15)

## 구현 범위

- [ ] **1a** 아침브리핑 index-board 원문 텍스트 DB 저장 + DB 우선 조회 (현재 10분 인메모리 재스크랩)
- [ ] **1b** 아침브리핑 카드 왼쪽 오렌지 줄 제거 (다른 카드와 동일 UI)
- [ ] **1c** 레짐 카드 프레임 상시 노출 + 데이터 없으면 스켈레톤, DB 조회 표시
- [ ] **2** 장중 선별 타임라인 카드 = momentum_scan만, 재선별(intraday_refresh)은 하단 별도 리스트 + "재선별" 뱃지

## 변경 파일 목록

| 파일 경로 | 변경 유형 | 변경 이유 |
|-----------|-----------|-----------|
| `backend/static/css/console.css` (L1592~) | 수정 | 1b: `.morning-brief-card`의 `border-left` 제거 |
| `backend/static/console.html` (L187~) | 수정 | 1c: 레짐 카드 `display:none` 제거·상시 노출 / 2: 하단 재선별 리스트 컨테이너 추가 |
| `backend/static/js/screens/console-daily-plan.js` | 수정 | 1c: 데이터 없을 때 카드 숨김 대신 스켈레톤 유지 |
| `backend/static/js/screens/console-plan-funnel.js` | 수정 | 2: trigger로 momentum_scan/intraday_refresh 분기 렌더 |
| `backend/services/engine/market_tone.py` | 수정 | 1a: morning_context에 index-board 원문 텍스트 컬럼 저장 |
| `backend/api/routes/market_briefing.py` | 수정 | 1a: DB에 저장본 있으면 DB 우선 반환, 없으면 스크랩 후 저장 |

## 요구사항 대조표

| 요구사항 항목 | 계획서 반영 | 비고 |
|---------------|------------|------|
| 1a 아침브리핑 DB 저장 후 재조회 | ✓ | 시황그리드·레짐(morning_context)은 **이미 DB화 완료**. 미충족분인 index-board **원문 텍스트**만 DB화 |
| 1b 오렌지 줄 제거 | ✓ | CSS 1줄 제거 |
| 1c 레짐 카드 프레임 상시 + DB 표시 | ✓ | 레짐 전환 이력은 이미 DB 저장. 표시 정책(상시노출)만 변경 |
| 2 모멘텀/재선별 분리 + 재선별 뱃지 | ✓ | trigger=momentum_scan / intraday_refresh 로 분기 |

## 추가 제안 항목 (PM 승인 필요)

- (없음 — 요청 범위 내에서만 구현)

## 미결 확인 (1c)

- 레짐 카드 데이터 없을 때 빈 프레임 문구: **"레짐 데이터 수집 대기 중…"** 스켈레톤으로 통일 예정 (다른 카드와 동일 톤). 이의 없으면 그대로 진행.

## 완료 기준

- [ ] 아침브리핑 2회 진입 시 2번째는 DB 조회(재스크랩 없음) 로그 확인
- [ ] 오렌지 줄 미표시, 카드 테두리 다른 카드와 동일
- [ ] 레짐 카드 데이터 0건일 때도 프레임 노출
- [ ] Funnel: momentum_scan만 상단, 재선별은 하단 뱃지 리스트
- [ ] 빌드/콘솔 에러 0개
- [ ] Playwright E2E 통과
