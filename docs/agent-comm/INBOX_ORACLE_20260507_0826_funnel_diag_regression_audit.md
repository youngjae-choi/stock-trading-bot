# INBOX_ORACLE - 2026-05-07 08:26 KST - Funnel Monitor 및 Diagnostics 회귀 감사

## 요청자

Sisyphus

## 담당 페르소나

Oracle

## 배경

PM이 2026-05-07 08:20~08:25 KST 화면을 보고 다음 이상을 보고했다.

1. Funnel Monitor 화면이 매일 변하지 않고 고정된 것처럼 보인다.
   - 화면 예: 전체 종목 2,500, Layer 1 통과 0, Layer 2 통과 0, 현재 매수대기 0.
   - Profile 배정 현황도 LOW_VOL/MID_VOL/HIGH_VOL/THEME_SPIKE 모두 0.
   - Layer 1 탈락 사유는 시가총액 500억 미만 1,120, 거래대금 10억 미만 830, 상장 60일 미만 72, 관리/투자경고 28처럼 항상 같은 값처럼 보인다.
   - 질문: 이 값이 하드코딩인지, 실제 AI/DB가 매일 바꾸는 값인지 확인 필요.

2. S1부터 사용자가 수동으로 누른 것처럼 자동 실행되는 기존 로직은 정상이어야 한다.
   - PM은 Claude가 만든 기존 UX는 정상이었다고 보고 있다.
   - 최근 수정 이후 더 심해졌다고 느끼고 있다.

3. System Diagnostics에서 각 단계를 실행하면 맨아래 서버 로그 영역에 연결되어 로그가 표시되어야 했는데 지금은 `로그가 없습니다.`로 나온다.
   - PM은 이 기능이 기존에 동작했다고 말한다.
   - 최근 상태 표시 수정 또는 관련 변경이 로그 연결을 깨뜨렸는지 확인 필요.

## 금지 사항

- 파일 수정 금지.
- git commit 금지.
- S1~S11 단계 실행 금지.
- 주문/매수/매도/청산/decision activate API 호출 금지.
- 실계좌/KIS 주문성 API 호출 금지.
- 외부 LLM/KIS 호출 금지.

## 조사 목표

### 1. Funnel Monitor 데이터 출처 확인

다음 항목이 어디서 오는지 확인하라.

- 전체 종목 2,500
- Layer 1 통과
- Layer 2 통과
- 현재 매수대기
- Profile 배정 현황
- S3/S4/S5 적용 메모리 수
- Layer 1 탈락 사유
- Funnel Quality
- 후보 선정 결과

확인할 것:

- `backend/static/console.html` 내 하드코딩/placeholder 여부
- 관련 API route 여부
- 관련 DB 테이블 여부
- S3 universe / S4 screening / S5 daily plan 결과와 연결되는지
- AI가 매일 직접 바꾸는 값인지, deterministic DB 집계인지, mock/fallback인지

### 2. 2026-05-07 현재 실제 Funnel 상태 대조

읽기 전용으로 DB를 확인해서 2026-05-07 기준 실제 값과 화면 값이 일치하는지 비교하라.

- `universe_filter_results`
- `hybrid_screening_results`
- `daily_trading_plans`
- `pipeline_run_audit`
- funnel 관련 테이블이 있으면 전부 확인

### 3. Diagnostics 실행 로그 영역 회귀 확인

다음 질문에 답하라.

- System Diagnostics 하단 서버 로그 영역은 어떤 API/함수에서 데이터를 읽는가?
- 실행 버튼을 누른 뒤 로그가 append되도록 되어 있었는가, 아니면 서버 로그를 fetch하는 구조였는가?
- 최근 `status truth display` 수정이 로그 rendering/fetch/append 로직을 건드렸는가?
- 현재 왜 `로그가 없습니다.`로 표시되는가?
- 실제 서버 로그는 남는데 UI만 못 가져오는가, 아니면 애초에 UI용 로그 저장소가 없는가?

### 4. 자동 실행을 수동 실행처럼 보이게 하는 UX 회귀 확인

PM 요구:

- 자동 스케줄러가 S1~S5를 수행해도 사용자가 수동으로 누른 것처럼 각 단계 결과를 눈으로 확인할 수 있어야 한다.
- 단, 내부 audit에는 실제 trigger_source가 보존되어야 한다.

확인할 것:

- 현재 자동 실행 결과가 Diagnostics 카드 결과 영역에 표시되는 구조인지
- 카드의 GET status와 POST run 결과 schema가 의도대로 분리되어 있는지
- 자동 실행 결과를 “수동 실행처럼 확인 가능”하게 보여주는 기능이 최근 수정으로 약해졌는지

## 출력 형식

결과를 아래 파일로 작성하라.

`docs/agent-comm/OUTBOX_ORACLE_20260507_0826_funnel_diag_regression_audit.md`

포함 항목:

- Findings 우선: P1/P2/P3, 파일/라인, 근거, 영향, 제안
- Funnel Monitor 각 값의 출처 표
- 하드코딩/DB집계/AI결과/mock 여부 판단
- 2026-05-07 실제 DB 값과 화면 값 비교
- Diagnostics 로그 영역이 깨진 원인
- 최근 수정이 만든 회귀인지 여부
- 자동 실행을 수동 실행처럼 보여주는 UX의 현재 상태
- 다음 Executor 수정 작업계획서 항목
