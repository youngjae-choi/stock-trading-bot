# 시스템 모듈 지도 (MODULE_MAP)

> Kairos 시스템의 논리 모듈 전체 지도. "어떤 모듈이 무슨 일을 하나"를 한눈에 보는 문서.
> 스냅샷 기준일: **2026-06-07** (engine 58 · 서비스 10 · 라우트 51 · 콘솔 화면 22).
> 상세 동작 규격은 `SYSTEM_GUIDE.md` / `OPERATION_SPEC.md`, 단계 흐름은 파이프라인 S1~S11을 따른다.

---

## 0. 한 장 요약

```
[셸 스크립트 6]  →  기동·점검 도구 (두뇌 아님)
       │
       ▼
[엔트리 main.py / config.py]  →  FastAPI 앱 + 설정
       │
       ├── [scheduler.py] ── 시각 트리거 (29 잡)
       │
       ▼
[engine 58 모듈]  ─ S1~S11 파이프라인 (선정→실행→복기) ← 시스템의 두뇌
       │
       ├── [services 10] DB·인증·상태·저장소
       ├── [kis / strategy / autotrade] 외부연동·전략
       │
       ├── [api/routes 51] REST 인터페이스
       └── [static/js/screens 22] 콘솔 화면
            ▲
      [ops_watchdog] 5분 틱으로 위 단계들을 감시 → Alert Center
```

핵심: **셸 스크립트는 운영 도구일 뿐**, 실제 논리는 Python 백엔드(engine·services·routes)에 있다.

---

## 1. 운영 셸 스크립트 (6개) — "어떻게 띄우나"

| 스크립트 | 역할 |
|----------|------|
| `run.sh` | FastAPI 백엔드 기동/검증 (포트 8000) |
| `setup_env.sh` | 환경 부트스트랩 (.venv·의존성·.env) |
| `scripts/install_systemd_service.sh` | systemd 서비스 설치/미리보기 |
| `scripts/service_healthcheck.sh` | `/health` + systemd 유닛 상태 점검 |
| `scripts/run-playwright-e2e.sh` | Playwright E2E 테스트 실행 |
| `scripts/verify_strategy_layers_sample.sh` | 전략 레이어 샘플 검증 |

> 운영 재기동은 셸 직접 실행이 아니라 `systemctl restart stock-trading-bot.service` (단일 인스턴스, Restart=always).

---

## 2. 엔트리포인트

| 파일 | 역할 |
|------|------|
| `backend/main.py` | FastAPI 앱 — 라우터 등록·lifespan·스케줄러 기동 |
| `backend/config.py` | 전역 설정(settings) — APP_DB_PATH·KIS·스케줄 시각 등 |

실행 경로: **systemd → uvicorn → `main.app`**.

---

## 3. 파이프라인 엔진 `backend/services/engine/` (58 모듈)

시스템의 두뇌. 단계별 그룹(이름 기준 분류):

### 선정 (S1~S5)
| 모듈 | 역할 |
|------|------|
| `universe_filter` | S3 유니버스 필터 (등락률·거래량 등) |
| `hybrid_screening` | S4 정량+LLM 하이브리드 스크리닝 (선정 출처 마킹: llm / quant_topup) |
| `sector_rotation` | 섹터 회전 분석 |
| `market_tone` | S2 프리마켓 시장 톤 판정 |
| `daily_plan` | S5 Daily Plan 생성·활성화 |
| `rulepack_generation` / `rulepack_store` | 룰팩 생성·저장 |
| `rule_resolver` | 룰 해석/매칭 |
| `buy_condition_framework` | 원자조건·조건그룹 매수 판정 프레임워크 |
| `expert_knowledge` | 전문가 지식 주입 |
| `confidence_calibration` | confidence 보정 |

### 매매 실행 (S6~S9)
| 모듈 | 역할 |
|------|------|
| `decision_engine` | S6 매수 판정 엔진 (최대 모듈, 1,513줄) |
| `order_preflight` | 주문 전 차단 검사 (block_reasons) |
| `order_executor` | KIS 주문 실행 |
| `fill_poller` | 체결 폴링 |
| `position_manager` / `position_integrity` | 포지션 관리·정합성 |
| `intraday_bar_engine` | 틱→봉 집계 (체결강도·VWAP) |
| `intraday_refresh` / `intraday_regime_monitor` | 장중 재선별·레짐 감시 |
| `replacement_signal` | 교체 매매 신호 |
| `eod_liquidation` | S9 장 마감 전량 청산 |

### 학습·복기 (S10~S11)
| 모듈 | 역할 |
|------|------|
| `review_audit` | 일별 복기 리포트 (SYSTEM_AUDIT 문서 연계) |
| `daily_summary` | 일일 거래 요약 |
| `learning_memory` | 학습 메모리 (만료 필터 적용) |
| `missed_opportunity` | 미진입 후보·수익률 추적 (장중 최고가 기준) |
| `false_positive` | 오탐 분석 |
| `ev_pruning` | EV 기반 가지치기 |
| `trade_tagging` / `trade_pairs` | 통짜 태깅·매매 페어 |
| `backtest` / `shadow_trading` | 백테스트·섀도 트레이딩 |

### 감시·안전
| 모듈 | 역할 |
|------|------|
| `ops_watchdog` | **운영 감시봇** — 5분 틱 단계 감시 → Alert Center (규칙기반, LLM·자동수정 없음) |
| `alert_center` | 시스템 알림 생성(system_alerts) |
| `data_quality_guard` | 데이터 결손 가드 |
| `human_approval` | 휴먼 승인 게이트 |

### 공통
| 모듈 | 역할 |
|------|------|
| `technical_indicators` | 기술 지표 |
| `llm_router` | LLM 라우팅 |
| `daily_capital` | 예수금 baseline 캡처 |

---

## 4. 서비스 최상위 `backend/services/` (10 모듈)

| 모듈 | 역할 |
|------|------|
| `scheduler` | APScheduler 시각 트리거 (29 잡, KST) |
| `db` | SQLite 연결·초기화 |
| `auth_service` | 인증(콘솔 로그인·2FA) |
| `console_state` | 화면 기준일·파이프라인 데이터 판정 |
| `settings_store` | 설정 저장소 |
| `trading_store` / `sim_store` | 거래·모의 데이터 저장소 |
| `stock_master` | 종목 마스터 |
| `regime_set_service` | 레짐 세트 |
| `alert_service` | 알림(텔레그램 등) 전송 |

---

## 5. 외부 연동·전략 서브패키지

| 경로 | 모듈 | 역할 |
|------|------|------|
| `services/kis/` | `realtime_ws` | KIS 실시간 WebSocket (틱 수신) |
| `services/strategy/` | `pipeline` · `investor_buy_leaders` · `filter_mapping` · `domestic_filter_console` | 전략 파이프라인·투자자 매수 상위·필터 매핑 |
| `services/autotrade/` | `workflow` | 자동매매 워크플로 |

---

## 6. 인터페이스 계층

| 계층 | 경로 | 규모 |
|------|------|------|
| REST API | `backend/api/routes/` | **51 라우트** (account·trading_monitor·funnel·alert_center·scheduler·review_audit 등) |
| 콘솔 프론트 | `backend/static/js/screens/` | **22 화면** + `css/console.css` · `console.html` |

---

## 7. 시각 트리거 요약 (scheduler 주요 잡, KST)

| 시각 | 잡 | 단계 |
|------|----|----|
| 08:30 | 프리마켓 시장 톤 | S2 |
| 08:50 | 예수금 baseline 캡처 | — |
| ~09:01 | 거래준비(유니버스→스크리닝→플랜) | S1~S5-A |
| ~09:10 | 매수 엔진 시작 | S6 |
| 09:15 | 아침 자가진단 | — |
| 09~15시 /2분 | 매수 엔진 자동복구 워치독 | — |
| **08~15시 /5분** | **운영 감시봇(ops_watchdog)** | 전 단계 감시 |
| 15:20 | EOD 청산 | S9 |
| ~15:25 | 후처리(청산·리뷰) | S9~S10 |
| 15:35 | 미진입 수익률 업데이트 | S11 |

> 정확한 시각·가드(개장 가드, 비거래일 스킵)는 `scheduler.py`와 `OPERATION_SPEC.md`가 단일 진실원.

---

## 변경 이력
- 2026-06-07: 최초 작성 (모듈 지도 스냅샷). `ops_watchdog` 신규 반영.
