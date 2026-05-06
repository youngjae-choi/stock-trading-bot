# OUTBOX_ORACLE - 2026-05-07 08:26 KST - Funnel Monitor 및 Diagnostics 회귀 감사

## 감사 범위

- 역할: Oracle(Codex CLI)
- 방식: 읽기 전용 회귀 감사
- 금지 준수: S1~S11 실행 안 함, 주문/매수/매도/청산/decision activate 호출 안 함, 외부 LLM/KIS 호출 안 함, git commit 안 함
- 확인 방법: 파일 조회, `data/stock_trading_bot.sqlite3`를 Python `sqlite3` `mode=ro`로 읽기 전용 조회

## Findings

### P1. Diagnostics 서버 로그 패널은 현재 실제 서버 로그를 읽지 못한다

- 위치:
  - `backend/api/routes/engine_test.py:21`
  - `backend/api/routes/engine_test.py:54-91`
  - `backend/static/console.html:3946-3958`
  - `backend/main.py:60-63`
  - `run.sh:62-68`
- 근거:
  - UI는 `engineTestLoadLogs()`에서 `GET /api/v1/engine/logs`를 호출한다.
  - 백엔드는 고정 경로 `logs/server.log`만 읽는다.
  - 현재 `logs/server.log`는 존재하지만 0라인이다.
  - `backend/main.py`의 `logging.basicConfig()`에는 `FileHandler`가 없고, `run.sh`도 `uvicorn` stdout/stderr를 `logs/server.log`로 리다이렉트하지 않는다.
  - 현재 실행 중인 서버 프로세스는 `python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --log-level info` 형태이며 파일 출력 대상이 보이지 않는다.
- 영향:
  - 서버 내부 로그가 stdout 또는 다른 과거 로그 파일로 흐르면 Diagnostics 패널은 항상 빈 파일을 읽고 `로그가 없습니다.`를 표시한다.
  - PM이 기대한 “실행 후 하단 로그에서 연결 확인” UX가 현재 깨져 있다.
- 최근 회귀 여부:
  - 최근 커밋 `853c824 Fix pipeline status truth display`는 Diagnostics 상태 판정/배지 로직을 수정했지만 `engineTestLoadLogs()`와 `/api/v1/engine/logs`의 파일 경로 구조는 바꾸지 않았다.
  - 따라서 “상태 표시 수정이 로그 fetch 코드를 직접 깨뜨린 회귀”는 아니다.
  - 다만 현재 운영 프로세스의 로그 출력 대상과 `/api/v1/engine/logs`가 읽는 파일이 불일치하는 운영/구성 회귀가 있다.
- 제안:
  - 서버 시작 시 `logs/server.log`에 실제 Python logging과 uvicorn access log가 기록되도록 FileHandler 또는 run script 리다이렉트를 명시한다.
  - `/api/v1/engine/logs`는 `log_path`, `total`, `lines`를 그대로 UI에 표시하고, 빈 경우 “서버 로그 파일은 비어 있음: 경로 …”처럼 원인을 구분해 보여준다.

### P1. Funnel Monitor의 Layer 1 탈락 사유와 Funnel Quality는 하드코딩이다

- 위치:
  - `backend/static/console.html:1330-1358`
- 근거:
  - `시가총액 500억 미만 1,120`, `거래대금 10억 미만 830`, `상장 60일 미만 72`, `관리/투자경고 28`은 정적 HTML이다.
  - `Funnel Quality`의 “최근 20거래일 평균 유니버스 188개 대비 오늘 200개”, “데이터 누락 없음”도 정적 HTML이다.
  - `GET /api/v1/funnel/summary` payload에는 rejection reason breakdown 또는 quality 판정 필드가 없다.
- 영향:
  - 페이지 문구는 “숫자는 매일 달라집니다”라고 말하지만, 이 구역은 매일 변하지 않는다.
  - PM이 “항상 같은 값처럼 보인다”고 판단한 직접 원인이다.
- 제안:
  - S3 저장 결과에 탈락 사유별 카운트를 저장하거나, 현재 산출 불가하면 “아직 집계 미구현”으로 표시한다.
  - Funnel Quality는 최근 N거래일 DB 집계 기반으로 계산하거나 숨김/대기 상태로 바꾼다.

### P2. `전체 종목 2,500`은 DB 집계가 아니라 API/프론트 fallback 하드코딩이다

- 위치:
  - `backend/api/routes/funnel.py:103-116`
  - `backend/static/console.html:5132-5139`
- 근거:
  - `/api/v1/funnel/summary`는 `total_universe: 2500`을 상수로 반환한다.
  - 프론트도 `fp.total_universe || 2500`으로 fallback 한다.
  - 실제 2026-05-07 S3 DB `raw_count`는 30이다.
- 영향:
  - 화면의 “전체 종목 2,500”은 실제 DB의 오늘 수집 raw universe와 다르다.
  - KRX 전체 종목 수 개념을 보여주려는 의도라면 별도 출처가 필요하고, Funnel 집계값으로 보이면 오해를 만든다.
- 제안:
  - `total_universe`를 실제 KRX 종목 마스터 집계로 연결하거나, 라벨을 “표시 기준값”으로 분리한다.
  - DB 기반 Funnel 단계에는 `layer1_raw`를 함께 보여준다.

### P2. 2026-05-07 현재 Funnel의 0 값은 대체로 실제 DB 상태와 일치하지만, 화면은 왜 0인지 설명하지 않는다

- 위치:
  - `backend/api/routes/funnel.py:56-90`
  - `backend/api/routes/funnel.py:103-116`
  - `backend/static/console.html:5111-5192`
- 근거:
  - 2026-05-07 DB에는 S3 결과 1건만 존재한다.
  - `universe_filter_results`: `raw_count=30`, `filtered_count=0`, `items=[]`
  - `hybrid_screening_results`: 2026-05-07 없음
  - `daily_trading_plans`: 2026-05-07 없음
  - `trading_signals`: 2026-05-07 없음
  - `position_stop_states`: `date(last_updated_at)=2026-05-07` 없음
- 영향:
  - Layer 1 통과 0, Layer 2 통과 0, 현재 매수대기 0, Profile 0은 오늘 DB 상태와 일치한다.
  - 하지만 화면은 “S3 결과는 있었으나 필터 결과 0이라 S4/S5 미생성”이라는 원인을 표시하지 않아 고정/오류처럼 보인다.
- 제안:
  - Funnel summary에 `layer1_raw`, `layer1_rejected`, `has_s3`, `has_s4`, `has_s5`, `last_updated_at`, `empty_reason`을 포함하고 UI에 표시한다.

### P2. 자동 실행을 수동 실행처럼 확인하는 구조는 일부 살아 있지만, run audit과 Diagnostics 카드가 연결되어 있지 않다

- 위치:
  - `backend/services/scheduler.py:200-258`
  - `backend/services/engine/pipeline_audit.py:36-75`
  - `backend/static/console.html:3815-3855`
  - `backend/static/console.html:3874-3943`
- 근거:
  - 스케줄러는 S3/S4/S5를 `trigger_source="auto_scheduler"`로 실행한다.
  - 수동 버튼은 `trigger_source=console_manual`로 POST 실행한다.
  - `pipeline_run_audit`에는 실제 `trigger_source`와 `display_source`가 저장된다.
  - Diagnostics 화면 진입 시 `engineTestLoadTodayResults()`가 GET `/today` 결과를 읽어 카드 결과 영역에 표시한다.
  - 그러나 카드에는 `pipeline_run_audit`의 최근 실행 시각, trigger_source, display_source, result_ref_id가 보이지 않는다.
- 영향:
  - DB 산출물이 있으면 자동 실행 결과도 카드에 보이지만, 사용자는 “자동으로 된 것인지”, “수동으로 누른 것과 같은 단계 결과인지”, “언제 실행됐는지”를 한눈에 확인하기 어렵다.
  - 내부 audit에는 source가 보존되지만 UI 확인성은 약하다.
- 최근 회귀 여부:
  - `853c824`는 GET 상태를 `ok:true`만으로 성공 처리하던 문제를 고쳤고, 자동 결과 표시 자체를 제거하지는 않았다.
  - 다만 성공/대기 판정이 엄격해지면서 “빈 payload도 성공처럼 보이던” 이전 착시는 사라졌다. PM 입장에서는 더 비어 보일 수 있다.
- 제안:
  - Diagnostics 카드에 최신 `pipeline_run_audit` row를 병합 표시한다.
  - 예: `마지막 실행: 08:15 auto_scheduler success raw=30 filtered=0`, `표시 모드: 자동 실행 결과를 수동 카드에 표시 중`.

### P3. 후보 선정 결과 테이블은 S4/S5 JSON 키 불일치로 일부 값이 비어 보일 수 있다

- 위치:
  - `backend/static/console.html:5161-5182`
  - `backend/services/engine/hybrid_screening.py:419-433`
  - `backend/services/engine/daily_plan.py:390-397`
- 근거:
  - S4 후보 JSON은 `ticker`를 사용한다.
  - S5 profile assignment fallback은 `code`를 사용한다.
  - 프론트는 후보에서 `c.symbol`, assignment에서 `a.symbol`만 찾는다.
- 영향:
  - 2026-05-06처럼 S4/S5 결과가 있는 날에도 후보 테이블의 종목코드, profile 매칭이 비거나 `-`로 표시될 수 있다.
- 제안:
  - 프론트 매핑을 `symbol || ticker || code`로 통일하고, assignment 매칭도 `symbol/code/ticker`를 모두 허용한다.

## Funnel Monitor 값 출처 표

| 화면 값 | 현재 출처 | 판단 | 2026-05-07 실제 DB와 비교 |
|---|---|---|---|
| 전체 종목 2,500 | `/api/v1/funnel/summary`의 `total_universe: 2500`, 프론트 fallback도 2500 | 하드코딩 | DB S3 `raw_count=30`과 다름 |
| Layer 1 통과 | `universe_filter_results.filtered_count` 최신 row | DB 집계 | 0, 일치 |
| Layer 2 통과 | `hybrid_screening_results.output_count` 최신 row | DB 집계 | 오늘 row 없음 → 0, 일치 |
| 현재 매수대기 | `trading_signals`에서 오늘 `signal_type='BUY'` count | DB 집계 | 0, 일치 |
| Profile 배정 현황 | `/api/v1/funnel/summary`의 active/validated `daily_trading_plans.symbol_assignments` profile count | DB 집계 | 오늘 plan 없음 → 모두 0, 일치 |
| S3 적용 메모리 수 | `/api/v1/pipeline/S3/context-preview`의 `payload.count` | DB 집계(learning_memories만) | active S3 memory 0, approved knowledge 3은 표시 안 됨 |
| S4 적용 메모리 수 | `/api/v1/pipeline/S4/context-preview`의 `payload.count` | DB 집계(learning_memories만) | active S4 memory 0, approved knowledge 7은 표시 안 됨 |
| S5 적용 메모리 수 | `/api/v1/pipeline/S5/context-preview`의 `payload.count` | DB 집계(learning_memories만) | active S5 memory 3 |
| Layer 1 탈락 사유 | 정적 HTML | 하드코딩/mock | DB에 해당 breakdown 없음 |
| Funnel Quality | 정적 HTML | 하드코딩/mock | DB 집계 아님 |
| 후보 선정 결과 | `/api/v1/screening/today`의 `hybrid_screening_results.candidates` + `/api/v1/daily-plan/today` assignments | DB/AI 결과 | 오늘 S4/S5 없음 → 빈 결과 |

## 2026-05-07 실제 DB 값

| 테이블 | 2026-05-07 상태 |
|---|---|
| `universe_filter_results` | 1건. `id=d501cc2c-d509-4f02-8e09-2c27b130857f`, `raw_count=30`, `filtered_count=0`, `items=[]`, `created_at=2026-05-06T23:15:32.836Z` |
| `hybrid_screening_results` | 없음 |
| `daily_trading_plans` | 없음 |
| `pipeline_run_audit` | 2026-05-07 없음. 전체 최신 audit는 2026-05-06 수동 실행 S2~S5 4건 |
| `trading_signals` | 2026-05-07 없음 |
| `position_stop_states` | `date(last_updated_at)=2026-05-07` 없음 |

## 화면 값이 고정처럼 보이는 이유

1. `전체 종목 2,500`은 실제 DB 집계가 아니라 상수다.
2. Layer 1 탈락 사유 4개 숫자와 Funnel Quality 문구는 정적 HTML이다.
3. 2026-05-07에는 S3 결과가 `filtered_count=0`이라 S4/S5가 생성될 수 없는 상태다.
4. UI가 “오늘 S3는 실행됐지만 통과 종목이 0이라 후속 단계가 비어 있음”을 설명하지 않는다.
5. 로그 패널이 실제 서버 로그를 표시하지 못해, PM이 원인을 화면에서 확인할 수 없다.

## 자동 실행 UX 현재 상태

- 자동 스케줄러 실행 자체는 `trigger_source=auto_scheduler`로 보존된다.
- 수동 버튼 실행은 `trigger_source=console_manual`로 보존된다.
- `display_source` 필드도 있으나 현재 Diagnostics UI가 이를 읽지 않는다.
- Diagnostics 카드는 화면 진입 시 GET `/today` 결과를 표시하므로 “결과 산출물이 존재하면” 자동 실행 결과도 카드에 나타난다.
- 그러나 실행 로그, audit row, trigger_source, 실행 시각이 카드에 결합되어 있지 않아 PM이 자동 실행을 수동 실행처럼 검증하는 UX는 불완전하다.

## 다음 Executor 수정 작업계획서 항목

1. `/api/v1/engine/logs` 로그 소스 정합화
   - `logs/server.log`에 실제 backend/uvicorn 로그가 기록되도록 서버 logging 설정 또는 run script를 수정한다.
   - UI는 `total=0`과 파일 누락/빈 파일을 구분해 표시한다.

2. Funnel summary API 확장
   - `total_universe` 상수 제거 또는 명확한 source 필드 추가.
   - `layer1_raw`, `layer1_rejected`, `has_s3`, `has_s4`, `has_s5`, `empty_reason`, `last_updated_at` UI 노출.
   - Layer 1 탈락 사유는 실제 저장/계산 전까지 mock 문구 제거.

3. Funnel Monitor 정적/mock 영역 제거
   - Layer 1 탈락 사유, Funnel Quality를 DB 기반 렌더링으로 전환.
   - 데이터가 없으면 “집계 없음/미구현” 상태로 표시.

4. Diagnostics 카드와 `pipeline_run_audit` 연결
   - GET status 결과와 별도로 최신 audit row를 조회해 카드에 실행 시각, source, status, message 표시.
   - 내부 `trigger_source`는 보존하고, UI에는 “자동 실행 결과를 수동 카드에 표시”처럼 PM 친화 문구를 제공.

5. 후보/assignment 키 정규화
   - S4 후보 `ticker`, S3/구버전 `symbol`, S5 assignment `code`를 프론트에서 공통 키로 normalize.
   - 후보 테이블 profile 매칭 누락을 회귀 테스트에 추가.
