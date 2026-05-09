# 자동매매 시스템 운영 가이드

> 최종 수정: 2026-05-08
> 대상: 운영자(PM) — 지금 시스템이 **어떻게 동작하는지**를 먼저 이해하기 위한 문서

---

## 목차
1. [이 문서의 읽는 법](#1-이-문서의-읽는-법)
2. [현재 시스템 구조 한눈에 보기](#2-현재-시스템-구조-한눈에-보기)
3. [백엔드 단계별 동작](#3-백엔드-단계별-동작)
4. [콘솔 화면별로 무엇을 보여주나](#4-콘솔-화면별로-무엇을-보여주나)
5. [각 화면이 부르는 API](#5-각-화면이-부르는-api)
6. [데이터가 꼬이기 쉬운 지점](#6-데이터가-꼬이기-쉬운-지점)
7. [서버 운영 명령어](#7-서버-운영-명령어)

---

## 1. 이 문서의 읽는 법

이 문서는 “무엇을 고쳐야 하는가”보다 먼저, **현재 시스템이 어떤 기준으로 움직이는지**를 정리한다.

- **백엔드**는 실제 데이터와 상태를 만들고 저장한다.
- **프론트엔드**는 그 결과를 화면에 보여준다.
- 일부 화면은 프론트엔드가 상태를 조금 계산한다.
  그래서 “backend가 준 값”과 “화면에 보이는 값”이 완전히 같지 않을 수 있다.

특히 아래 세 가지는 항상 같이 봐야 한다.

1. **KST 오늘 날짜**
2. **DB에 실제로 저장된 결과**
3. **화면이 해석한 상태값**

---

## 2. 현재 시스템 구조 한눈에 보기

### 2-1. 백엔드 큰 구조

현재 백엔드는 FastAPI 기반이다.

- `backend/main.py`
  - 앱 시작점
  - DB 초기화
  - 인증 초기화
  - 스케줄러 시작
  - `logs/server.log` 파일 로깅 연결
- `backend/services/scheduler.py`
  - S1~S11 스케줄 관리
  - `schedule_skip_today` 같은 운영 플래그 관리
- `backend/services/console_state.py`
  - Today Control 상단 요약용 상태를 만든다
  - 현재 단계, 다음 작업, funnel 요약, 로그 요약을 합쳐서 반환한다
- `backend/services/engine/pipeline_audit.py`
  - S1~S11 실행 흔적을 `pipeline_run_audit`에 기록한다
- `backend/api/routes/*`
  - 각 화면이 호출하는 API를 제공한다

### 2-2. 프론트 구조

콘솔은 React가 아니라 **정적 HTML + 분리된 classic JS** 구조다.

- `backend/static/console.html`
  - 전체 화면 shell
  - 각 screen 섹션을 포함
  - 스크립트를 마지막에 순서대로 로드
- `backend/static/js/console-main.js`
  - DOM 로드 후 초기화
- `backend/static/js/console-auth.js`
  - 로그인 상태 확인
  - Today Control 상단 요약(`bot/overview`, `bot/data-health`) 로드
  - 로그/오늘 주문도 함께 로드
- `backend/static/js/console-utils.js`
  - 오늘 날짜, timeline 상태, diagnostics 상태 계산
- `backend/static/js/console-state.js`
  - S1~S11 단계 정의와 화면용 설명 텍스트
- `backend/static/js/screens/*.js`
  - 각 화면 전용 렌더러

---

## 3. 백엔드 단계별 동작

아래는 현재 시스템이 운영상 어떻게 움직이는지 기준으로 정리한 것이다.

| 단계 | 백엔드 역할 | 저장/조회 대상 | 화면에서 보이는 곳 |
|---|---|---|---|
| S1 | KIS 토큰 갱신 | scheduler / pipeline audit | Diagnostics, Today Control timeline |
| S2 | 시장 톤 분석 | `market_tone_results` | Today Control, Funnel, Diagnostics |
| S3 | 유니버스 필터 | `universe_filter_results` | Funnel, Today Control, Diagnostics |
| S4 | 하이브리드 스크리닝 | `hybrid_screening_results` | Funnel, Today Control, Diagnostics |
| S5 | Daily Plan 생성/검증/활성화 | `daily_trading_plans` | Today Control, Trading Monitor, Funnel, Diagnostics |
| S6 | Decision Engine 활성화 | `decision` 상태 | Today Control, Trading Monitor, Diagnostics |
| S7 | 주문 실행 결과 | `orders` / `trading_signals` | Today Control, Trade History, Diagnostics |
| S8 | 포지션 감시 | `position_stop_states` / 주문 포지션 | Trading Monitor, Today Control, Diagnostics |
| S9 | 당일 청산 | 주문/포지션 후처리 | Today Control, Diagnostics |
| S10 | Review & Audit | `review_audit` / 리포트 | Today Control, Review & Audit, Diagnostics |
| S11 | Learning Memory | `learning_memory` | Today Control, Learning Memory, Diagnostics |

### 3-1. 공통 기준

- 날짜는 대부분 **Asia/Seoul(KST)** 기준이다.
- “오늘”은 UTC가 아니라 **KST 오늘**이다.
- 화면에 보이는 상태는 종종 **DB 결과 + 프론트 상태 해석**의 합이다.

### 3-2. S1~S5의 핵심 의미

이 구간은 장 시작 전 준비 단계다.

1. **S1**: 인증 토큰을 준비한다.
2. **S2**: 오늘 시장 분위기를 정한다.
3. **S3**: 거래 대상이 될 수 있는 종목 풀을 줄인다.
4. **S4**: AI가 정성 평가로 후보를 고른다.
5. **S5**: 오늘 실제로 쓸 매매 계획을 만든다.

이 5개가 잘 돌아가야, 뒤 단계(S6~S11)도 의미가 생긴다.

### 3-3. `schedule_skip_today`

`backend/services/scheduler.py`가 오늘을 거래일/비거래일로 판단해 `schedule_skip_today`를 만든다.

- 비거래일이면 S2~S6 같은 준비 단계가 스킵될 수 있다.
- 이 플래그는 Diagnostics와 Today Control timeline에도 영향을 준다.

---

## 4. 콘솔 화면별로 무엇을 보여주나

### 4-1. Today Control

이 화면은 운영자가 가장 먼저 보는 **요약 허브**다.

보여주는 내용:

- 현재 단계 / 다음 단계
- 오늘 시장 톤
- 유니버스 필터 결과
- 스크리닝 결과
- Daily Plan 상태
- Risk Profile / RulePack 상태
- 현재 포지션
- 오늘 주문
- 운영 로그
- funnel 요약

실제 특징:

- 데이터는 여러 API를 합쳐서 보여준다.
- 화면 자체가 숫자를 많이 계산한다기보다, **backend overview를 요약해서 보여주는 편**이다.
- 예전처럼 단일 카드 하나만 보고 끝나는 구조가 아니다.

### 4-2. Trading Monitor

이 화면은 **실시간 감시 화면**이다.

보여주는 내용:

- Decision Engine 활성/비활성
- 계좌 정보
  - 예수금
  - 주식 평가금액
  - 총 평가금액
  - 당일 매수/매도 금액
- 오늘 적용 정책
  - 매수 조건
  - 매도 조건
  - 현금/리스크 문구
- 매수 대기 후보
- 보유 포지션
- 실시간 tick 스트림

실제 특징:

- 후보 리스트와 포지션 리스트는 **row-by-row 갱신**을 하도록 되어 있다.
- 정책 문구는 `trading-monitor/policy-summary`에서 만든 자연어 설명을 쓴다.
- 계좌정보는 `account/balance`가 기준이다.

### 4-3. Trade History

이 화면은 **과거 주문 조회** 화면이다.

보여주는 내용:

- 기간 필터
- 주문 내역 표
- 체결/미체결 상태
- 날짜별 조회 결과

실제 특징:

- “거래를 제어하는 화면”이 아니라 **기록을 보는 화면**이다.
- 일부 요약 블록은 남아 있어도, 핵심은 주문 테이블이다.

### 4-4. Funnel Monitor

이 화면은 **S3 → S4 → S5로 얼마나 줄어드는지** 설명하는 화면이다.

보여주는 내용:

- 전체 universe
- S3 통과 수
- S4 통과 수
- 현재 매수 대기 수
- Risk Profile 배정 수
- S3 탈락 사유
- Funnel Quality 문구
- 마지막 갱신 시각

실제 특징:

- `funnel/summary`가 핵심이다.
- `daily-plan/today`, `screening/today`도 같이 읽어 종목 배정과 후보 수를 맞춘다.
- 하드코딩된 숫자가 남아 있으면 이 화면이 제일 먼저 어색해진다.

### 4-5. System Diagnostics

이 화면은 **S1~S11이 오늘 어떤 상태인지** 보여준다.

보여주는 내용:

- 각 단계의 배지(완료/대기/스킵/실행중)
- 각 단계의 raw JSON 결과
- `pipeline_run_audit` 카드
- 서버 로그

실제 특징:

- `scheduler/status`와 `engine/audit/today`를 같이 본다.
- “ok=true”만으로 완료 처리하지 않도록 설계되어 있다.
- null payload는 완료가 아니라 대기/미생성으로 보여야 한다.

### 4-6. 그 외 화면

- **Settings**: RulePack, Risk Profiles, Scheduler 시간 설정
- **Review & Audit**: S10 결과 확인
- **Learning Memory**: S11 교훈/메모리 확인
- **Alerts / Data & API / Execution & Risk**: 운영 상태 보조 화면

---

## 5. 각 화면이 부르는 API

### 5-1. Today Control

- `GET /api/v1/bot/overview`
- `GET /api/v1/bot/data-health`
- `GET /api/v1/engine/logs`
- `GET /api/v1/orders/today`
- `GET /api/v1/daily-plan/today`
- `GET /api/v1/funnel/summary`

### 5-2. Trading Monitor

- `GET /api/v1/decision/status`
- `GET /api/v1/account/balance`
- `GET /api/v1/trading-monitor/policy-summary`
- `GET /api/v1/trading-monitor/candidates`
- `GET /api/v1/trading-monitor/positions`
- `GET /api/v1/trading-monitor/stream` (SSE)

### 5-3. Trade History

- `GET /api/v1/trades/history`
- `GET /api/v1/orders/recent`
- `GET /api/v1/orders/today`

### 5-4. Funnel Monitor

- `GET /api/v1/funnel/summary`
- `GET /api/v1/daily-plan/today`
- `GET /api/v1/screening/today`
- `GET /api/v1/pipeline/S3/context-preview`
- `GET /api/v1/pipeline/S4/context-preview`
- `GET /api/v1/pipeline/S5/context-preview`

### 5-5. System Diagnostics

- `GET /api/v1/scheduler/status`
- `GET /api/v1/engine/audit/today`
- `GET /api/v1/engine/logs`
- `POST /api/v1/engine/token-refresh`

---

## 6. 데이터가 꼬이기 쉬운 지점

이 부분은 “현재 구조를 보고 수정할 때” 특히 주의해야 한다.

### 6-1. 0과 null

- **0**은 진짜 값일 수 있다.
- **null**은 데이터가 비었거나 아직 안 온 것일 수 있다.
- 화면에서 둘을 같은 값처럼 보여주면 운영자가 오해한다.

### 6-2. 오늘 날짜 기준

- KST 기준 오늘인지 확인해야 한다.
- UTC 날짜로 보면 하루가 어긋날 수 있다.

### 6-3. fallback 숫자

- `2500` 같은 고정 숫자는 보기 편하지만 실제와 다를 수 있다.
- fallback은 항상 “왜 fallback인지”가 같이 보여야 한다.

### 6-4. 프론트 계산값

- Diagnostics와 Today Control timeline은 일부 상태를 프론트가 계산한다.
- 그래서 backend가 바뀌면 프론트 상태 계산도 같이 검토해야 한다.

### 6-5. 로그와 파일 출력

- Diagnostics의 로그 패널은 `logs/server.log`를 읽는다.
- 서버가 그 파일에 실제로 쓰고 있는지 확인해야 한다.

---

## 7. 서버 운영 명령어

### 서버 상태 확인
```bash
sudo systemctl status stock-trading-bot
```

### 로그 실시간 모니터링
```bash
sudo journalctl -u stock-trading-bot -f
```

### 서버 재시작
```bash
sudo systemctl restart stock-trading-bot
```

### 서버 중지 / 시작
```bash
sudo systemctl stop stock-trading-bot
sudo systemctl start stock-trading-bot
```

### 부팅 시 자동 시작 여부 확인
```bash
sudo systemctl is-enabled stock-trading-bot
# → enabled 이면 정상
```

### 오늘 특정 단계 수동 실행 (콘솔 로그인 후)
| 단계 | API |
|------|-----|
| S1 토큰 갱신 | `POST /api/v1/engine/token-refresh` |
| S2 시장 톤 | `POST /api/v1/market-tone/analyze` |
| S3 유니버스 | `POST /api/v1/universe-filter/run` |
| S4 스크리닝 | `POST /api/v1/screening/run` |
| S5 Daily Plan | `POST /api/v1/daily-plan/generate` |
| Decision Engine ON | `POST /api/v1/decision/activate` |
| Decision Engine OFF | `POST /api/v1/decision/deactivate` |

---

## 부록: 전체 데이터 흐름 요약

```
[해외 시장/지표] ──→ S2 시장 톤 ──→ 시장 톤 결과
                                   │
[KIS 유니버스 데이터] ──→ S3 유니버스 필터 ──→ universe_filter_results
                                   │
[S3 결과 + KIS/AI 정보] ──→ S4 스크리닝 ──→ hybrid_screening_results
                                   │
[S3+S4 결과] ──→ S5 Daily Plan ──→ daily_trading_plans
                                   │
[장중] ──→ S6 Decision Engine ──→ 주문/포지션 감시
                                   │
[주문/체결] ──→ S7/S8 ──→ orders / positions / signals
                                   │
[15:20~] ──→ S9 청산 ──→ 후처리
                                   │
[16:00] ──→ S10 Review & Audit ──→ 복기 리포트
                                   │
[16:30~22:00] ──→ S11 Learning Memory ──→ 다음날 참고 데이터
```
