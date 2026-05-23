# Kairos 자동매매 시스템 운영 가이드

> 최종 수정: 2026-05-23
> 대상: 운영자(PM)

---

## 목차
1. [시스템 구조](#1-시스템-구조)
2. [파이프라인 단계별 동작 S1~S10](#2-파이프라인-단계별-동작-s1s10)
3. [완전 자동화 동작 방식](#3-완전-자동화-동작-방식)
4. [S10 LLM 복기 프로세스](#4-s10-llm-복기-프로세스)
5. [레짐 SET 시스템](#5-레짐-set-시스템)
6. [콘솔 화면별 기능](#6-콘솔-화면별-기능)
7. [텔레그램 알림 체계](#7-텔레그램-알림-체계)
8. [데이터 흐름 및 취약 지점](#8-데이터-흐름-및-취약-지점)
9. [알려진 취약점 및 대응 현황](#9-알려진-취약점-및-대응-현황)
10. [서버 운영 명령어](#10-서버-운영-명령어)
11. [주요 API 목록](#11-주요-api-목록)
12. [변경 이력](#12-변경-이력)

---

## 1. 시스템 구조

```
KIS API (한국투자증권)
    ↕  WebSocket 실시간 틱 + REST 주문/잔고
Backend (FastAPI · Port 8000)
    ├── scheduler.py         ← S1~S10 자동 실행 심장부
    ├── services/engine/     ← 실제 매매 로직
    │   ├── decision_engine  ← S6 진입 판단 (WebSocket 틱 기반)
    │   ├── order_executor   ← KIS 주문 제출
    │   ├── fill_poller      ← 체결 확인 + 매수 체결 텔레그램
    │   ├── position_manager ← 포지션 추적 (메모리)
    │   ├── eod_liquidation  ← S9 장마감 청산
    │   ├── review_audit     ← S10 LLM 복기 + 설정 자동 조정
    │   ├── intraday_refresh ← 장중 재선별 (09:30/10:30/11:30)
    │   ├── llm_router       ← LLM 호출 라우터 (Opus 4.6 주력)
    │   ├── regime_set_service ← 레짐 SET 매칭 + 피드백 스코어링
    │   ├── technical_indicators ← pykrx 기술지표
    │   └── backtest         ← 파라미터 검증용 백테스트
    └── static/console.html  ← Kairos 운영 콘솔 UI (Port 8000)

SQLite DB: data/stock_trading_bot.sqlite3
Telegram Bot: 알림 수신 전용 (자동 처리 — 승인 버튼 없음)
```

---

## 2. 파이프라인 단계별 동작 S1~S10

| 단계 | 시간(KST) | 이름 | 핵심 동작 |
|:---:|:---:|---|---|
| **S1** | 07:45 | KIS 토큰/시장 확인 | 토큰 갱신, 거래일 여부 판단, schedule_skip_today 설정 |
| **S2** | 07:45 | 시장 시황 분석 | KOSPI/KOSDAQ 전일 동향, AI 시황 요약 |
| **S3** | 07:45 | 유니버스 필터 | 전체 종목 → 거래 가능 후보 압축 |
| **S4** | 07:45 | 하이브리드 스크리닝 | AI + 정량 필터 → 오늘 후보 선별 |
| **S5** | 07:45 | 데일리 플랜 생성/활성화 | 레짐 SET 매칭 + 종목별 리스크 프로파일 배정 |
| **S5-A** | 07:45 | 플랜 활성화 확인 | 플랜 정합성 검증 후 S6 준비 |
| **S6** | 09:00 | Decision Engine 가동 | WebSocket 실시간 틱 수신, 진입 판단 시작 |
| **S7** | 장중 | 주문 실행 | BUY 신호 발생 시 KIS 시장가 주문 |
| **S8** | 장중 | 포지션 관리 | 트레일링 스탑, 손절, 시간 청산 |
| **S9** | 15:20 | 당일 청산 | 전 포지션 시장가 청산, 엔진 비활성화 |
| **S10** | 15:20+ | LLM Review & Audit | **Opus 4.6** 복기 → 설정 자동 반영 → 텔레그램 통보 |

> **S11 (Learning Memory Builder) 2026-05-23 제거됨.**
> S10 LLM 복기가 `regime_set_feedback`을 통해 학습 기능을 직접 수행하므로 별도 S11 불필요.

### 장중 재선별 (Intraday Refresh)
- **09:30 / 10:30 / 11:30** — 시장 변화 감지 시 S3→S4→S5→S6 재실행
- 거래량 상위 종목 평균 등락률이 기준치를 벗어날 때 트리거
- 이력: `intraday_refresh_slots` 테이블 저장, Trade Review 화면에서 확인 가능

---

## 3. 완전 자동화 동작 방식

**2026-05-23 기준 완전 자동화 완료 (수동 개입 불필요)**

### 하루 흐름 요약

```
07:45  S1~S5-A  거래 준비 (시황분석 → 스크리닝 → 플랜 생성)
09:00  S6       Decision Engine 가동 (WebSocket 틱 수신 시작)
09:00  S7/S8    장중 매매 실행 + 포지션 관리
09:30~11:30     Intraday Refresh (시장 급변 시 재선별)
15:20  S9       전 포지션 청산
15:20+ S10      LLM 복기 → settings 자동 반영 → 텔레그램 통보
```

### 비거래일 처리
- S1에서 거래일이 아니면 `schedule_skip_today = true` → S2~S6 전체 스킵
- Today Control 화면은 **마지막 실제 거래일** 데이터를 표시
  - 기준 1순위: `trading_signals` / `daily_review_reports` (실제 거래 발생 날짜)
  - 기준 2순위 fallback: 파이프라인 데이터 테이블 (S1/S2 부분 실행 날짜)

### 자동 설정 조정 (S10 LLM → system_settings)
S10 LLM 복기 완료 후 `settings_overrides`를 즉시 system_settings에 반영:

| 조건 예시 | LLM 판단 후 변경 내용 |
|----------|----------------------|
| 손실 2건 평균 confidence 낮음 | `min_confidence` 상향 |
| EOD 청산 집중 발생 | `stop_loss_pct` 추가 |
| 포지션 리스크 과다 | `max_positions` 축소 |
| 레짐 적합, 승률 우수 | 파라미터 유지 또는 완화 |

- actor: `s10_llm` (Settings 화면에서 확인 가능)
- 변경 없는 경우(값 동일) → DB 기록 없이 스킵
- 텔레그램 자동 통보

---

## 4. S10 LLM 복기 프로세스

### 흐름

```
S9 청산 완료
  ↓
DB 집계 (trading_signals, fills, false_positives, missed_entries)
  ↓
MD 컨텍스트 조립 (_build_review_context_md)
  ├── 시장 시황 (S2 tone_analysis)
  ├── 레짐 SET 적용 내역 (regime_set_applications)
  ├── 매매 결과 (trade_pairs, win/loss)
  ├── 손실 종목 목록 + 진입 사유 + 청산 사유
  ├── 걸러낸 종목 목록 + 제외 사유 (missed_entries)
  └── 현재 system_settings 값
  ↓
Claude Opus 4.6 호출 (prompts/1600_opus_review.md)
  ↓
JSON 응답 파싱
  ├── regime_evaluation: {evaluation, reason, next_regime_hint}
  ├── settings_overrides: {key: value, ...}
  ├── settings_reasoning: {key: 적용 사유, ...}
  ├── narrative: 복기 서술 (전략 컨텍스트 + 분석 + 내일 방향)
  └── patterns: {winning: [...], losing: [...]}
  ↓
자동 처리
  ├── settings_overrides → upsert_setting() (actor: s10_llm)
  ├── regime_set_feedback 테이블에 레짐 평가 저장
  ├── human_approval_queue에 status='auto_applied'로 저장
  └── 텔레그램 통보 (손익 + 레짐 평가 + 반영된 설정 목록)
```

### Trade Review 화면에서 보이는 항목

| 섹션 | 내용 |
|------|------|
| LLM 복기 카드 | 레짐 평가 배지 (적절/보통/부적절) + 사유 + 내일 힌트 |
| LLM 서술 | narrative 전문 — 시황, 레짐 판단, 걸러낸 종목 평가, 손실 분석 |
| 승리/손실 패턴 | patterns.winning / patterns.losing 목록 |
| 오늘의 전략 컨텍스트 | 시황 + 전략 강도 + 주문 건수 (규칙 기반) |
| 매수 판단 결과 | 종목별 진입 사유 + 손익 (규칙 기반) |
| 손실 패턴 분석 | false_positives 개별 분석 (규칙 기반) |
| 다음 거래일 액션 플랜 | 자동 반영된 settings 내역 + 반영 시각 |

> LLM 복기는 S10 실행 버튼(또는 자동 스케줄)으로 생성됩니다.
> 이전 거래일 데이터도 Trade Review 화면에서 날짜 선택 후 "S10 실행" 버튼으로 재생성 가능.

---

## 5. 레짐 SET 시스템

### 개념
- **레짐(Regime)**: 시장 상태 (예: MILD_BULL, HIGH_VOL, BEAR 등)
- **SET**: 특정 레짐에 최적화된 매매 파라미터 묶음 (max_positions, stop_loss, take_profit 등)
- 매일 S5에서 시장 조건에 맞는 SET를 자동 매칭 → 당일 매매에 적용

### 피드백 루프
```
S5  레짐 SET 매칭 → regime_set_applications 저장
  ↓ 장중 매매
S10 LLM 복기 → regime_evaluation (good/neutral/bad)
  ↓
regime_set_feedback 저장
  ↓
다음 번 match_set() 스코어링에 반영
  ├── bad 평가: -5점/회
  └── good 평가: +3점/회
```

### Daily Plan 화면
- 현재 적용 중인 레짐 SET 표시
- 레짐 히스토리 타임라인
- S5 수동 재실행 가능

---

## 6. 콘솔 화면별 기능

### Today Control (`main`)
- 현재 파이프라인 단계, 오늘 손익, 계좌 현황
- Funnel 진행 상태 (유니버스 → 스크리닝 → 신호 건수) — 1행 5카드
- 비거래일이면 마지막 거래일 데이터 표시 + 배너 안내
- 다음 거래일 액션 플랜 + 시스템 반영 내역 통합 카드

### Trading Monitor (`live`)
- 실시간 포지션 / 당일 주문 내역
- 체결 복구 도구 (`POST /api/v1/trading/admin/recover-fills`)

### Funnel Monitor (`screening`)
- S3→S4→S5 필터링 효율 분석 (5카드 1행)
- 장중 재선별 이력 표시

### Trade Review (`review`)
- 일별 LLM 복기 리포트
- 날짜 선택 → S10 실행으로 해당일 LLM 복기 생성
- 승리/손실 패턴, 레짐 평가, 설정 자동 반영 내역 표시

### False Positive (`fp`)
- 손실 거래 분석 목록
- 확인(리뷰) 완료 시 목록에서 숨김

### Daily Plan (`plan & regime`)
- 레짐 SET 현황, Daily Plan 활성 상태
- 레짐 히스토리 타임라인

### Settings (`admin`)
- 진입 조건, 리스크 한도, 스케줄 시간 관리
- 항목별 최종 수정 시각 표시 (`updated_at · updated_by`)
- `s10_llm` 자동 조정 이력 확인 가능
- 값이 동일한 경우 변경 이력 기록 안 함

### System Diagnostics (`diag`)
- S1~S10 단계 성공/실패 상태 배지
- 실시간 서버 로그 조회

### Backtest
- `POST /api/v1/backtest/run` — 날짜 범위 + 파라미터 지정
- `GET /api/v1/backtest/quick` — 현재 설정값으로 즉시 실행
- 일봉(pykrx) 기반 시뮬레이션

---

## 7. 텔레그램 알림 체계

**수신 전용 — 버튼 없음, 자동 처리**

| 알림 종류 | 발송 시점 | 내용 |
|-----------|-----------|------|
| 단계 완료 | 각 S스텝 완료 | `[매매봇] S6 Decision Engine 완료 ✅` |
| 매수 체결 | fill_poller 체결 확인 시 | 종목, 수량, 체결가, 체결금액 |
| S10 복기 완료 | S10 완료 후 | 손익, 레짐 평가, 자동 반영된 설정 목록 |
| 배당락 알림 | 08:00, 13:00 (해당 종목만) | 배당락 D-2 이내 종목 |

---

## 8. 데이터 흐름 및 취약 지점

### 데이터 흐름

```
trading_signals (BUY 신호)
    ↓ fill_poller 체결 확인
trading_orders → fills
    ↓ trade_pairs 집계
daily_trade_summary
    ↓ S10 LLM 복기
daily_review_reports
  + human_approval_queue (status=auto_applied)
  + regime_set_feedback
    ↓ S5 다음 날 플랜 반영
레짐 SET 피드백 스코어 → match_set() 가중치
```

### 알려진 데이터 취약 지점

- **schedule_skip_today**: `true` 고착 시 다음 날도 전체 스킵. 날짜 기반 자동 리셋 로직 있음
- **날짜 기준**: 전 시스템 KST 기준. 서버 시간이 UTC면 날짜 경계에서 오작동 가능
- **비거래일 연속**: 파이프라인 테이블에만 데이터가 있고 실제 거래가 없는 날이 연속될 경우, `_latest_pipeline_data_date()` 1순위(trading_signals)가 비어 2순위(파이프라인)로 fallback — Today Control 날짜가 실거래 기준일과 다를 수 있음

---

## 9. 알려진 취약점 및 대응 현황

> 2026-05-22 전문가 감사 결과. 심각도 HIGH → MEDIUM → LOW 순 정렬.

### HIGH 취약점

#### H1. 서버 재시작 시 미청산 포지션 재진입 가능
- **위치:** `decision_engine.py:586`, `eod_liquidation.py:146`
- **현상:** 재시작 후 `_restore_positions_from_db()` 복원 시, 매도 주문이 제출됐으나 미체결인 포지션 누락 → 재진입 신호 발생 가능
- **현재 방어:** `_has_recent_submitted_buy()` (5분 내 중복 차단)
- **대응 필요:** 재시작 시 KIS 실계좌 잔고와 DB 포지션 자동 대사

#### H2. KIS 주문번호(ODNO) 미수신 시 영구 추적 불가
- **위치:** `order_executor.py:252`, `fill_poller.py:415-462`
- **현상:** KIS 응답에 ODNO 없으면 `status="submitted_without_order_no"` → fill_poller 영구 추적 불가
- **현재 방어:** 재조회 시도, `recover-fills` 수동 복구 API
- **대응 필요:** ODNO 재조회 실패 시 텔레그램 즉시 경고

#### H3. DB 연결 실패 시 신호 저장 없이 주문 제출
- **위치:** `decision_engine.py:897`
- **현상:** `_emit_signal()` DB 저장 실패 → 빈 signal_id로 주문 제출 가능
- **현재 방어:** 없음
- **대응 필요:** DB 저장 실패 시 주문 차단

#### H4. trade_pairs FIFO 페어링 미구현
- **위치:** `trade_pairs.py:114-130`
- **현상:** 동일 종목 복수 진입/청산 시 합산 단일 페어 → 개별 거래 손익 귀인 부정확
- **대응 필요:** FIFO 방식 페어링 로직 구현

---

### MEDIUM 취약점

#### M1. 일일 손실 한도 부재
- **현상:** 당일 누적 손실이 -10% 이상이어도 신규 진입 계속 처리
- **대응 필요:** 일일 손실 -3% 초과 시 당일 신규 진입 차단

#### M2. 포지션 한도 race condition
- **위치:** `order_executor.py:228-242`
- **현상:** 동시 2개 신호 처리 시 양쪽 한도 체크 통과 가능
- **대응 필요:** position 추가를 semaphore 내부로 이동

#### M3. 트레일링 활성 전 손실 확대 가능
- **위치:** `position_manager.py:203-241`
- **현상:** trailing_activate_profit 미달 시 initial_stop_loss(-3%) 고착
- **대응 필요:** 진입 후 30분 경과 시 손절선 break-even으로 상향

#### M4. S9 부분 청산 실패 후 gap 리스크
- **현상:** 일부 종목 청산 실패 시 미청산 포지션 야간 gap 리스크
- **대응 필요:** 청산 실패 종목 텔레그램 즉시 경고

#### M5. S9~S10 사이 추가 체결 누락 가능
- **현상:** S9 청산 주문 부분 체결 후 S10 시작 전 추가 체결 발생 시 review 수치 불일치
- **대응 필요:** S10 시작 직전 2회 추가 poll

---

### LOW 취약점

#### L1. 텔레그램 알림 발송 타이밍 불확실
- `asyncio.create_task()`로 예약된 알림이 즉시 실행되지 않을 수 있음 (주문 자체는 정상)

#### L2. pykrx 일봉 폴백 백테스트 정밀도 한계
- 분봉 부재로 시가/고가/저가/종가 4개 합성 bar → 실거래 대비 오차 (장중 실거래에는 무관)

---

### 우선순위 대응 로드맵

| 우선순위 | 취약점 | 예상 효과 |
|---------|--------|-----------|
| 1순위 | H1 재시작 포지션 대사 | 잘못된 재진입 완전 방지 |
| 2순위 | M1 일일 손실 한도 | 연속 손실 날 자동 보호 |
| 3순위 | H2 ODNO 미수신 경보 | 주문 미추적 즉시 인지 |
| 4순위 | M2 position race condition | 포지션 한도 초과 방지 |
| 5순위 | M3 손절선 break-even | 장기 보유 손실 제한 |

---

## 10. 서버 운영 명령어

```bash
# 서버 시작
nohup python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 > logs/server.log 2>&1 &

# 서버 상태 확인
curl http://127.0.0.1:8000/health

# 로그 확인
tail -f logs/server.log

# TOTP 코드 생성 (로그인 2차 인증)
python3 -c "
import hmac, hashlib, struct, time, base64
def totp(s): k=base64.b32decode(s.upper()); t=int(time.time())//30; h=hmac.new(k,struct.pack('>Q',t),hashlib.sha1).digest(); o=h[-1]&0xf; return str(struct.unpack('>I',h[o:o+4])[0]&0x7fffffff%1000000).zfill(6)
print(totp('CN3OQNTSTRNWWGXMBRP7466IMY4DXEXL'))
"

# 오늘 S10 LLM 복기 수동 실행
curl -X POST http://127.0.0.1:8000/api/v1/review-audit/run \
  -H "Content-Type: application/json" \
  -d '{"date": "2026-05-22"}'  # 날짜 지정 가능

# 체결 수동 복구
curl -X POST http://127.0.0.1:8000/api/v1/trading/admin/recover-fills

# 당일 스케줄 스킵 (휴장일 등)
# Settings 화면 → schedule_skip_today = true

# 백테스트 즉시 실행 (현재 설정값 기준)
curl -X POST http://127.0.0.1:8000/api/v1/backtest/quick
```

---

## 11. 주요 API 목록

| 그룹 | 엔드포인트 | 용도 |
|------|-----------|------|
| 시스템 | `GET /health` | 서버 상태 |
| 봇 상태 | `GET /api/v1/bot/overview` | Today Control 데이터 |
| 설정 | `GET/POST /api/v1/settings` | 매매 파라미터 조회/저장 |
| 스케줄러 | `GET /api/v1/scheduler/status` | 파이프라인 진행 상태 |
| 매매 | `GET /api/v1/trading/orders` | 주문 내역 |
| 체결 복구 | `POST /api/v1/trading/admin/recover-fills` | 미체결 수동 복구 |
| 복기 조회 | `GET /api/v1/review-audit/{date}` | 날짜별 복기 리포트 |
| 복기 실행 | `POST /api/v1/review-audit/run` | S10 LLM 복기 실행 |
| False Positive | `GET /api/v1/false-positive/list` | 손실 분석 목록 |
| 레짐 | `GET /api/v1/regime/day-detail` | 날짜별 레짐 SET 상세 |
| 장중 재선별 | `GET /api/v1/funnel/intraday-refresh` | 재선별 이력 |
| 백테스트 | `POST /api/v1/backtest/run` | 파라미터 백테스트 |
| 백테스트 | `GET /api/v1/backtest/quick` | 현재 설정 즉시 백테스트 |
| 진단 | `GET /api/v1/engine/audit/today` | 단계별 실행 감사 |

---

## 12. 변경 이력

### 2026-05-23 (오늘)

#### 시스템 리브랜딩
- 시스템 이름 **Dantabot → Kairos** (그리스어 "결정적 순간")
- SVG 로고 제작 (`backend/static/img/kairos-logo.svg`) — 상승 차트 아이콘 + KAIROS 텍스트
- 로그인 화면 + 사이드바 상단에 로고 적용
- 세션 쿠키: `kairos_session`, 테마 키: `kairos_theme`

#### S10 LLM 복기 구현
- 기존 규칙 기반 → **Claude Opus 4.6 LLM 복기**로 전환
- LLM 출력: `regime_evaluation`, `settings_overrides`, `narrative`, `patterns`
- `settings_overrides` 즉시 system_settings 자동 반영 (actor: `s10_llm`)
- `regime_set_feedback` 테이블 신설 → 레짐 SET 피드백 루프 구현
- 텔레그램 자동 통보 (승인 불필요)
- 구형식 데이터(2026-05-22 이전): `recommendations` 배열을 LLM narrative fallback으로 표시

#### S11 제거
- S11 Learning Memory Builder (22:00) 완전 제거
- 스케줄러, 콘솔 UI, 설정 화면, 진단 화면, 버튼 텍스트 전체 정리
- S10 LLM + `regime_set_feedback`이 학습 기능 대체

#### S12 (us_market_watch) 제거
- 22:00 US 시장 감시 job (`job_us_market_watch`) 제거

#### 비거래일 처리 개선
- `_latest_pipeline_data_date()` 2단계 우선순위 적용
  - 1순위: `trading_signals` / `daily_review_reports` (실제 거래일)
  - 2순위 fallback: `market_tone_results` 등 파이프라인 테이블
- 비거래일 연속 시 마지막 실제 거래일 데이터 정확히 표시

#### Settings 표시 버그 수정
- `upsert_setting()`: 값 동일 시 DB 기록 + audit_events 저장 스킵
- Trade Review 설정 반영 내역: `old_value === new_value` 항목 필터링

#### 브라우저 뒤로가기 / 닫기 지원
- SPA 화면 전환마다 `history.pushState()` → 브라우저 ← 버튼으로 이전 화면 복귀
- 브라우저 X(닫기) 시 "KAIROS를 종료하시겠습니까?" 확인 다이얼로그

#### UI 개선
- Funnel Monitor 요약 카드 5개 1행 레이아웃
- Dividend Entry 등록 버튼을 각 카드 오른쪽 상단으로 이동
- Trade Review: 다음 거래일 액션 플랜 + 시스템 반영 내역 통합 카드

---

### 2026-05-22 이전

→ `docs/SYSTEM_AUDIT_YYYYMMDD.md` 감사 보고서 참조
