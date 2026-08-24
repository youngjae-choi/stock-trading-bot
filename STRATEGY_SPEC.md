# STRATEGY_SPEC.md — 전략 동작 사양서 (SSOT)

> 이 시스템이 **어떻게 동작해야 하는가(의도)** 와 **지금 실제로 어떻게 도는가(실측)** 를
> 한 곳에 모은 단일 진실원천(Single Source of Truth)이다.
>
> - **A. 의도** = 사람(PM+Claude)이 저작한다. **전략을 바꾸면 여기부터 고친다.**
> - **B. 실측 / C. 드리프트** = `scripts/strategy_spec_sync.py`가 라이브 DB에서 **자동 생성**한다. 손대지 마라.
> - **모든 세션은 시작 시 이 문서를 읽는다.** C(드리프트)에 경고가 있으면
>   실측이 의도를 벗어난 것이니 **되돌리거나(버그) 의도를 갱신(전략변경)** 한다.
>
> 갱신: `python scripts/strategy_spec_sync.py` (실측·드리프트 재작성) ·
> `--check` (드리프트만 검사, 있으면 exit 1 → watchdog/CI용).
>
> **스코프 경계:** 이 문서 = **전략 값·엔진 동작**(SSOT). **운영 흐름·진단**(일일 사이클·학습루프·정합가드)은
> [`docs/manual/OPERATION_SPEC.md`](docs/manual/OPERATION_SPEC.md). 전략 값 중복 금지 — 값은 여기만.

---

## A. 의도 — 이렇게 동작해야 한다

### A-0. 핵심 철학
- **연산·판단·실행 = 결정론 시스템 / 코딩·분석·전략 = PM+Claude 수동 통제.** LLM 매매개입 0.
- **이기는 진입 = VWAP 아래 눌림목**(데이터 확증: 승률 ~60%). **고점추격 금지**(~30% 승, 손실 뿌리).
- 장세는 레벨(코스피 %)만이 아니라 **방향(가속·정체·꺾임)** 으로 판단해야 한다. → 전환 감지(§A-5, 개발 예정).
- 어떤 자동 메커니즘도 사람 확인 없이 매매 파라미터를 바꾸지 않는다(S10 LLM·loss auto-tuner 관찰전용).

### A-0b. 하루 운영 흐름 — 시각 · 데이터소스 · 설정 · 판단 (전체 파이프라인)
> 시각은 설정(`schedule_*`)으로 조정. 아래는 현재값. 비거래일은 Job1이 `schedule_skip_today`로 자동잡 전면 스킵.
> **매수 신호 = baseline S4/S5 경로만**(탐색모드 완전제거 2026-08-22, 모멘텀스캐너 no-op).

**① 장전 준비 (시장톤 → 후보)**
| 시각 | 단계(잡) | 데이터 소스 | 판단·설정 | 산출 |
|---|---|---|---|---|
| 09:01 | S2 프리마켓 시장톤 (`job_premarket_market_tone`) | index-board 브리핑 텍스트 + 장전 선행지표 21종(나스닥/S&P선물·VIX·금·BTC·달러·미국채, Yahoo) | `classify_regime_heuristic`(결정론) — 코스피200선물%·필라델피아반도체·선행지표→`li_lean` | 아침 regime(참고) + `morning_context` DB |
| 09:05 | 거래준비 S1~S5-A (`job_trade_preparation_pipeline`) | KIS 유니버스·거래량/거래대금 순위 | S1 토큰→S3 유니버스→**S4 스크리닝**→S5 Daily Plan | 후보 + 종목별 변동성 프로필 배정 |

**S4 스크리닝**: candidates_30(거래량·거래대금 순위·change_rate) → 정량 블렌드 `0.4×TSI + 0.4×유니버스점수 + 0.2×suitability` → `suitability_score`. 진입밴드 `engine.min/max_price_change_pct`(1.5~4%) 참조.

**② 장중 시장감지 (레짐 — 상시)**
| 주기 | 단계 | 데이터 소스 | 판단·설정 | 반응 |
|---|---|---|---|---|
| 08~15시 매2분 | index-board 브리핑 폴링 (`job_intraday_briefing_poll`) | index-board(httpx) | 새 장중 브리핑 시 `check_intraday_regime` 트리거 | 브리핑 DB + 레짐 재평가 |
| ↑트리거 | 장중 레짐 판정 (`intraday_regime_monitor._resolve_set_regime`) | 실시간 KOSPI(KIS 직접조회) + VIX(index-board/아침) + li_lean | **SET 매칭 regime** = `regime.set_source` 스위치: **5tier(기본·활성 2026-08-23)** = 설정기반 `classify_regime_5tier`→`regime_to_set`(regime.down_pct 등, 드리프트 감시) / judge(폴백)=하드코딩 `_judge_regime` | `match_set`→`record_application`(SET 재매칭) |
| ↑동시(shadow/부분live) | 5장세·전환 계산 (`market_sensing`) | 위와 동일 | `classify_regime_5tier`: KOSPI vs `regime.down_pct`(-1.5)/`up_pct`(0.5)/`surge_pct`(2.5)·VIX vs `regime.vix_volatile`(28)·+li_lean×`li_lean_weight`(0.25). `detect_transition`: `transition_window_min` 창 KOSPI **기울기** vs `down_transition_pp`(-1.0)/`up_transition_pp`(1.0) — 레벨무관·방향 | `regime.current_5tier`/`current_transition` 영속화 → **사이징⑥이 5tier 읽음(live)**, SET매칭엔 shadow, 전환 대응 gated |
| 즉시 | 급락 방어 | KOSPI/VIX | `risk.flash_crash_threshold_pct`(**-5**, 변동성장 적응)·VIX 임계 | 인버스1x 외 신규매수 차단 |

**③ 전략선택**: `match_set(regime,vix,kospi_change)` → 오늘 Regime SET(risk_on/neutral/risk_off/volatile) → `get_playbook` → 진입게이트·손절/트레일·사이징 한 벌. (아침 S6 activate 시 최초 매칭, 장중 전환 시 재매칭)

**④ 매수 — S6 실시간 틱 (09:20~, 최소 09:10)**
WS 틱마다 후보 평가(단일 길목 `_emit_signal`):
- `_evaluate_rules`(decision_rules): 게이트값 = `rule_resolver._settings_gate_rules`(settings 단일출처, RulePack 제거) — confidence(`min_ai_confidence` 0.60 + `min_confidence_floor` 0.40 + `confidence_gate_mode` regime_defensive→방어레짐 강제) · 등락률밴드(`min/max_price_change_pct` 1.5~4) · 거래량(`min_volume_ratio` 1.5) · 시간창(`entry_start/end_time`) · TSI>0 · Layer3(vwap/ma/rsi/spread, `_add_layer3_evaluation`)
- `_entry_gate_block_reason`(6게이트 순서): 손실3연패 하드차단 → 급락방어(인버스1x 예외) → **하락전환 매수중단 래치**(`get_entry_suspended` — down_transition서 걸고 up_transition서만 해제, `regime.transition_response_active` **활성 2026-08-23**) → new_entry_allowed → 칼리브레이션 → entry_fail 쿨다운 → 장중재진입(`intraday_max_stoploss_per_symbol` 2회)
- VWAP 눌림 게이트: `entry_vwap_pullback_mode`(enforce)·`entry_max_vwap_dist_pct` / 레버리지: `leverage_restriction_mode`(exclude)
- 통과→**사이징** `execution_engine.resolve_execution_sizing`: 확신도=`conviction.regime_weight`×레짐 + (1-w)×눌림 → 종목당 `sizing.per_position_rate_min`(5%)~`risk.max_position_rate_per_stock`(15%), 종목수 `sizing.positions_min/max`(6~19), 배포한도 `exploration.deploy_target_rate`(95%)

**⑤ 매도·모니터링 — S7 실행 / S8 Position Manager (실시간)**
진입 즉시 손절/트레일 세팅(**출처 `engine.stop_source`=regime** → 당일 Regime SET `applied_settings`). **★ 변동성 재보정(2026-08-23)**: 종목 장중 9.4% 출렁 실측 → 손절을 노이즈(편도 4.7%) 밖으로 넓힘, 트레일도 넓게(러너 극대화), 방어=포지션수↓. `take_profit_rate`는 **항상 비활성**(rule_resolver `take_profit_enabled=False`) — 실익절=트레일+scaleout.

| Regime SET | 초기손절 | 트레일활성 | 트레일폭 | (take_profit 표시용·비활성) |
|---|---|---|---|---|
| 상승 risk_on (상승·**폭등**) | -4.5% | +4% | **3.0%(넓게=러너)** | +12% |
| 보합 neutral | -4.0% | +3.5% | 2.5% | +8% |
| 하락 risk_off (하락·**폭락**) | -4.0% | +3% | 2.5% | +7% |
| 변동성 volatile (VIX>28) | -5.0% | +4% | 3.0% | +10% |

- 초기손절 `stop_loss_rate` → `초기손절가=진입가×(1+손절)`, `stop_price_can_only_increase`(하향금지)
- 트레일 `trailing_activate_profit` 도달→활성, `trailing_stop_rate` 되돌림 시 청산. **하락전환 시 트레일폭 ×`transition_trail_tighten_factor`(0.5)=절반조임**(러너 이익잠금)
- 수확 `engine.harvest_mode`: `scaleout_target_rate`(**+2%**)서 `scaleout_ratio`(**50%**) 확정+잔량 러너(트레일), `daily_target_rate`(계좌 2%). = PM "부분익절+트레일링 극대화"
- 안전망: 손절 REST 백업(30초)·주문 정합(3분)·10초봉 저장(1분)

**⑥ 후처리·복기**
| 시각 | 단계 |
|---|---|
| 15:12 | S9 강제청산 스윕(동시호가 전 미체결 방지) |
| 15:20 | 후처리 S9~S10: 청산 백스톱→복기(`daily_review_reports`·day_score·exit성과·calibration)→`SYSTEM_AUDIT.md` |
| 15:35 | 미진입 수익률 소급 · 23:00 장후 브리핑(evening sentiment, 다음날 신뢰도 보정) · 18:00 백업 |

> ⚠ **레짐 판정 이중구조(정확히)**: (a) **레짐 SET 매칭**(전략 SET 선택)은 `regime.set_source` 스위치 — **5tier(기본·활성 2026-08-23)** = 설정기반 `classify_regime_5tier`→`regime_to_set`(regime.down_pct 등, 드리프트 감시), judge(폴백) = 하드코딩 `_judge_regime`/index-board. `_resolve_set_regime`이 dispatch. (b) `classify_regime_5tier`+`detect_transition`은 `regime.current_5tier`를 영속화 → **사이징⑥이 읽음(live)**, 이제 SET매칭도 live(5tier). (c) 전환 대응(`regime.transition_response_active`) **활성(2026-08-23)** — 하락전환 감지 시 신규매수 중단+트레일 절반조임.

> ⚠ **폭등·폭락은 별도 SET 아님** — 4-SET에 흡수(`_SET_MAP`): 폭등(+2.5%↑)→**risk_on SET**+사이징 확대(`surge_per_position_rate_max`), 폭락(-5%↓)→**risk_off SET**+flash_crash 방어(신규매수 봉쇄, 인버스1x만). 추세전환은 방향성 오버레이(SET 불변, 진입·트레일만 수정).

> ⚠ **포지션 수 단일출처 = 사이징모델**(`sizing.positions_min/max` 6~19). `sizing.model_active=True`면 `order_executor`가 신모델 qty로 **override** → 레짐 SET `max_positions`(12/7/4/2)·`risk.max_positions`(5)는 **死**(표시/드리프트 대조용만). 방어=게이트 통과 감소+conviction 비중↓로 자연 축소.

### A-1. 레짐(장세) 탐지 — 30분 틱 (09:30~15:00)
탐지는 `intraday_regime_monitor._judge_regime`(KOSPI·VIX 레벨) + `risk.flash_crash_*`(즉시 방어).

| 장세 | 탐지 조건(의도) | 매핑 SET / 대응 |
|---|---|---|
| **폭락** | KOSPI ≤ **-5%** (즉시·디바운스 우회, 변동성장 적응) | ✅ **risk_off SET**(-4%손절) + flash_crash 방어(신규봉쇄, 인버스1x) |
| **하락** | KOSPI < -1.5% (또는 VIX>22 & KOSPI<-1) | ✅ **risk_off SET**(-4%) |
| **보합** | -1.5% ≤ KOSPI ≤ +0.5% | ✅ **neutral SET**(-4%) |
| **상승** | KOSPI > +0.5%, VIX < 22 | ✅ **risk_on SET**(-4.5%, 검증 8/18·8/20) |
| **폭등** | KOSPI > +2.5% — 상승의 **사이징 확대 티어**(별도 전략 아님) | ✅ **risk_on SET** + 사이징 확대(`surge_per_position_rate_max`). SET매칭엔 risk_on |
| **하락전환** | 최근 window(`transition_window_min`) KOSPI **-1.0%p↓** (레벨 무관·방향) | ✅ 대응 활성: 신규매수 중단(**래치**) + 트레일 절반조임(`transition_trail_tighten_factor` 0.5) |
| **상승전환** | 최근 window KOSPI **+1.0%p↑** 반등 | ✅ **재개 래치(2026-08-23)**: 하락전환 매수중단을 걸어두고 **up_transition에서만 해제**(None 구간 유지=데드캣 방지). `get_entry_suspended` 신선도 75분 |
| (VIX축) volatile | VIX > 28 | ✅ **volatile SET**(-5%손절·최소포지션, 5장세와 직교) |

> **왜 전환이 최우선인가 (8/18 실증):** +2.7%출발 → +2.77%꼭지 → +1.25%(11:00) → -0.19%(11:30) → -1.5%마감.
> 레짐은 레벨만 봐서 11:30(이미 마이너스)에야 neutral로 바뀜 → 그 사이 봇은 risk_on(공격)으로 꼭지 매수 → -2.16M.
> **레벨은 아직 +1.25%여도 방향은 하락전환.** 이걸 잡는 게 §A-5.

> ⚠ **레짐 임계 — 5tier 활성(2026-08-23)**: 기본 SET매칭 = 설정기반 `classify_regime_5tier`(regime.down_pct/up_pct/surge_pct/vix_volatile, **드리프트 감시됨**). 롤백=`regime.set_source`=judge(하드코딩 `_judge_regime`). judge와 차이는 vix22~28+얕은딥 구간뿐(judge=risk_off vs 5tier=neutral)이나 재보정 후 두 SET 손절 모두 -4%라 실질 영향 미미. **월요일 첫 실전 — SET 매칭 타당성 관찰**.

### A-2. 종목 선정 (엔진③)
선정 점수 = `selection.change_weight`×등락률점수 + `selection.surge_weight`×거래량급증점수 (`universe_filter._score_and_rank`). **배선 완료(2026-08-23)**: `selection.weights_source`=settings(기본)면 이 설정을 **라이브 소비**(Engine Monitor ③에서 편집→선정 반영). 롤백=tone(구 `_TONE_WEIGHTS` 0.5/0.5).

| 장세 | 선정 의도 | 현재 |
|---|---|---|
| 공통 | 거래량 순위(`quant_topup`) + VWAP 눌림목 게이트 + 설정 가중치(라이브) | ✅ 배선 |
| 폭락 | 인버스1x + 급락반등주 트랙 허용 | △ 구현(효과 미검증) |
| 하락·보합 | 방어적 선정(상대강도·저변동, 레짐별 가중치) | 🟡 토대 완료(설정 라이브) — 레짐별 값 차등은 get_playbook 통합(Phase4)서 |

### A-3. 매수 — 진입 게이트 (전 레짐 공통, 값은 B절 실측)
진입은 아래 게이트를 **모두** 통과해야 한다. (레버=설정키, 현재값)

| 게이트 | 설정키 | 현재 의도값 | 의미 |
|---|---|---|---|
| **눌림목** | `entry_vwap_pullback_mode` / `entry_max_vwap_dist_pct` | enforce / 0.0 | VWAP 위 이격 매수(추격) 차단 ★핵심엣지 |
| 고점추격 상한 | `max_price_change_pct` | 4.0 | 시가대비 +4% 초과 매수 차단 |
| 등락률 하한 | `min_price_change_pct` | 1.5 | +1.5% 미만 진입 안 함 |
| 거래량 | `min_volume_ratio` | 1.5 | 평균 대비 1.5배 미만 제외 |
| 유동성 | `min_liquidity_krw` | 1억 | 거래대금 미달 제외 |
| confidence | `confidence_gate_mode`·`min_ai_confidence`·`min_confidence_floor` | regime_defensive·0.60·0.5 | 방어레짐만 강화 |
| 캘리브레이션 | `calibration_gate_*` | on·gap0.15·n30 | 표본부족·과신 차단 |
| churn 재진입 | `intraday_max_stoploss_per_symbol`·`intraday_reentry_block_enabled` | 2·on | 당일 2회 손절 종목 당일 차단 |
| 3연패 | `loss_streak_hard_block_enabled` | on | 3연패 종목 하드블록 |
| 진입실패 쿨다운 | `entry_fail_cooldown_*` | on·3일·2회 | 반복 실패 종목 냉각 |
| 레버리지 | `leverage_restriction_mode` | exclude | 레버리지·인버스2x 차단 |
| 밴드역전 가드 | `band_inversion_guard_enabled` | on | 진입밴드 역전 마비 방지 |
| 실행 시간창 | `entry_execute_start_time`·`entry_end_time`·`new_entry_cutoff_time` | 09:30·15:00·15:10 | 이전은 shadow |

- **폭락:** 신규진입 차단(인버스1x 예외). **폭등:** 눌림깊이 완화 + 사이징 확대(§A-4b). **하락전환(활성 2026-08-23, §A-5):** 신규매수 즉시 중단.

### A-4. 매도 — 레짐 SET별 차등 + 공통 수확 (값은 B절 실측)
- **레짐 SET**이 손절/트레일을 레짐별 차등. **★변동성 재보정(2026-08-23)**: 종목 장중 9.4% 실측 → 손절 전부 노이즈 밖으로(risk_on -4.5% / neutral·risk_off -4% / volatile -5%), 트레일도 넓게(러너). `take_profit_rate`는 비활성(표시용).
- **스케일아웃 수확**(`harvest_mode`=on): `scaleout_target_rate`(**+2%**)서 `scaleout_ratio`(**50%**) 확정 + 잔량 러너(넓은 트레일), 목표후 `scaleout_ratio_after_target`(80%). 하루 목표 `daily_target_rate`(계좌 +2%). = PM "부분익절+트레일링 극대화".
- **공통:** EOD 강제청산(`force_exit_time` 15:20 / `force_exit_ceiling` 15:12) · 폭락 방어모드(검증 8/19) · 무틱 손절 REST 백업(`stop_loss_backup_*`).
- **하락전환(활성):** 트레일폭 ×`transition_trail_tighten_factor`(0.5) 절반조임(러너 이익잠금) + 신규매수 중단.

### A-4a. 전략설정 엔진① — 레짐→플레이북 권위 (`get_playbook`)
**시장분위기(5장세)를 판단하면 그 장세의 전략 한 벌을 통째로 꺼낸다.** 구현: `strategy_playbook.get_playbook(regime5)` → `Playbook{선정·매수게이트(9)·매도(레짐SET)·사이징}`. 폭등=상승SET+사이징확대. 레짐 틱마다 `[E1] SHADOW-PLAYBOOK` 로그.
- **소비자 배선:** ⑤매도(`resolve_sell_params`)·⑥사이징(`resolve_execution_sizing`)·VWAP게이트는 get_playbook 경유. ④매수 게이트(밴드·확신도)는 `decision_rules`가 `final_rule`에서 읽되, **RulePack 제거(2026-08-23 PM) 후 `rule_resolver._settings_gate_rules`가 `engine.*` settings에서 직접 주입**(단일출처).
- **★ RulePack 전면 제거 완료(2026-08-23 PM):** 구 daily RulePack(rulepacks 테이블·매일생성)은 `engine.*` settings의 **복사본**이라 중복·드리프트만 유발(LLM시절 종목별·Layer3 기능은 8/5 LLM제거 때 이미 소실). **매매는 RulePack 완전 무의존** — `rule_resolver._settings_gate_rules`가 settings에서 게이트 주입(밴드 1.5~4.0·확신 0.60·거래량 1.5).
  - **Stage1**: rule_resolver rulepacks 주입 제거→settings. **Stage2a**: `reconcile_buy_gates` shadow·`buy_gates_source` 스위치 제거(발산 대상 소멸). **Stage2b**: 생성 중단(hybrid_screening)·모듈 삭제(rulepack_generation/store/validator)·API 삭제(rulepack·rulepack_gen)·rulepacks 테이블 DROP·db 스키마 제거·표시소비자 neutralize·프론트 라벨 정리.
  - **유지**: `base_rulepack`(base-v1.0, 정적 order/exit·force_exit·take_profit_enabled 설정) + `/api/v1/rule/base` API. 손절/트레일=프로필/레짐SET(RulePack과 별개).

### A-4b. 사이징·배포 — 예수금비중 모델 (결정4, Phase1 구현중)
**종목수가 아니라 예수금 투입비중이 기준.** 확신↑ → 종목당 비중↑ → 집중, 확신↓ → 분산.
종목수는 파생 결과. 구현: `strategy_playbook.resolve_position_sizing` + `order_executor._compute_new_model_sizing`(가용현금 캡). **`sizing.model_active`=on (2026-08-21 활성)** — 매수 사이징이 확신도→예수금비중으로 결정. 롤백=off. 검증: 8/21 실매수 종목당 투입비 5~12% = 신모델 5~15% 범위 내(과투입 아님).

| 레버 | 설정키 | 값 | 의미 |
|---|---|---|---|
| 종목당 비중 | `sizing.per_position_rate_min` ~ `risk.max_position_rate_per_stock` | **5% ~ 15%** | 확신도로 보간 |
| 종목수(파생) | `sizing.positions_min` ~ `sizing.positions_max` | **6 ~ 19** | 배포/비중, 클램프 |
| 총배포 상한 | `exploration.deploy_target_rate` | 0.95 | 예수금 95% |

> 예: 확신 1.0 → 15%×6종목 집중 / 확신 0.0 → 5%×19종목 분산. **포지션 수 단일출처 = 이 [6,19] 사이징모델**(`sizing.model_active`=on이면 `order_executor`가 override). 구 `risk.max_positions=5`·레짐SET `max_positions`(12/7/4/2)·RulePack은 **死**(표시/드리프트 대조용). PM 결정 2026-08-23: 사이징모델 통일.
> ✅ `engine.exploration_mode` **완전 제거**(2026-08-22) — 매수=baseline S4/S5만. `exploration.deploy_target_rate`(95%)만 사이징 배포한도로 잔존(=⑥ 예수금투입목표). §A-7 #2 해소.

**확신도(conviction) 모델** — 위 사이징의 "확신"을 정하는 법. 구현: `strategy_playbook.resolve_conviction`.
`확신 = regime_weight × 레짐점수 + (1−regime_weight) × 눌림점수` (전부 설정 = 언제든 수정).

| 설정키 | 값 | 의미 |
|---|---|---|
| `conviction.regime_weight` | 0.5 | 장세 vs 눌림 비중 (1=장세만·0=눌림만) |
| `conviction.regime_scores` | risk_on 1.0 … risk_off 0.2 | 장세별 점수(JSON) |
| `conviction.pullback_full_dist_pct` | -3.0 | VWAP 아래 이만큼 눌리면 눌림점수 만점(위=추격=0) |

> risk_on+깊은눌림=1.0(집중) / risk_off+추격=0.1(분산). **배선 상태:** `sizing.model_active`=on(2026-08-21) — 실매수 사이징에 확신도 반영. 롤백=off.

### A-4c. 리스크 할트·안전벨트
| 레버 | 설정키 | 현재값 |
|---|---|---|
| 일일 손실한도 | `risk.daily_loss_limit_percent` | **-5%** (변동성장 적응) |
| 자동 정지선 | `risk.auto_halt_loss_percent` | -5% |
| 폭락 방어 발동 | `risk.flash_crash_threshold_pct`·`flash_crash_defense_enabled` | **-5%**·on (변동성장 적응) |
| 수동 긴급정지 | `risk.emergency_halt_enabled` | off(평시) |
| 부분체결 재주문 | `risk.partial_fill_reorder_enabled` | on |

### A-5. 시장감지 엔진② — 5장세 판정 + 전환(방향) 감지 (감지+대응 활성 2026-08-23)
**레벨(5장세) + 방향(전환)** 두 축 결정론 판단. 구현: `market_sensing.py`(순수함수+유닛10, **전부 설정 임계**).
- **`classify_regime_5tier`**: KOSPI(+VIX·선행지표 lean)로 폭락/하락/보합/상승/폭등. 임계 `regime.{crash(=flash),down,up,surge}_pct`·`vix_volatile`.
- **`detect_transition`**: 최근 window KOSPI 기울기로 하락전환(`regime.down_transition_pp` -1.0%p)/상승전환(+1.0%p). **레벨 무관** — 8/18(+2.77→+1.25=-1.52%p) 하락전환 검증됨.
- 코스 백테스트: 8/18 하락전환 11:00 발화 → 전환後 매수 2건 차단 + 전환前 8건 매도조임 대상.

**배선 상태:**
- **감지(shadow)**: `_persist_and_shadow_sensing` — 레짐 틱마다 KOSPI 시계열 저장 + 전환/5장세 상태 영속화 + `SHADOW-REGIME` 로그. 라이브 `_judge_regime` 불변. 검증도구 `scripts/analyze_shadow_regime.py`.
- **대응 활성(2026-08-23 PM)**:
  - **하락전환 매수중단**: `_entry_gate_block_reason` + `get_current_transition`(신선도). `regime.transition_response_active`=**on**.
  - **하락전환 트레일조임**: `_update_trailing`이 트레일폭 축소(이익잠금). `regime.transition_trail_tighten_factor`=**0.5**(절반조임).
  - **폭등 사이징확대**: 5장세=surge면 종목당 상한↑. `sizing.surge_per_position_rate_max`(기본 0.15=무변, ↑로 확대).
- **상승전환 재개 래치(✅ 2026-08-23)**: `_latch_from_transition`+`get_entry_suspended` — 하락전환 매수중단을 걸고 up_transition에서만 해제(None 유지). 진입게이트가 stateless→래치로 전환.
- **SET매칭 5tier 활성(✅ 2026-08-23)**: `set_source`=5tier 기본 — `_resolve_set_regime`이 설정기반 `classify_regime_5tier` 사용(judge 롤백).
- **⚠ 월요일(2026-08-25) 관찰**: 전환 감지 오발 가능성 — 첫 활성이므로 하락전환 발화 빈도·타당성 모니터. 과발동 시 `transition_window_min`/`down_transition_pp` 조정.

### A-6. 검증 상태 요약
| 검증됨 ✅ | 미검증 ✗ |
|---|---|
| VWAP 눌림목 엣지(17일 백테스트+실전) · flash_crash 폭락 방어(8/19) · 30분 레짐 재판정 · churn 가드 · **손절/트레일 변동성 재보정(9.4% 실측+데이트레이더 관행, 2026-08-23)** | 전환(방향) 대응 실전(월 첫 활성) · 폭등 티어 · 레짐별 종목선정 · 재보정 손절값 실전검증 |

### A-7. 관리 주의 — 다출처 충돌·이상 (반드시 인지, 미해결)
전략이 "새는" 지점들. 드리프트 자동감시로 못 잡는 구조적 문제이므로 여기 명시한다.

| # | 이슈 | 실태 | 해결 방향 |
|---|---|---|---|
| 1 | ~~max_positions 다출처~~ **해소(2026-08-23 PM: 사이징모델 통일)** | 포지션 수 단일출처 = `sizing.positions_min/max`([6,19]). `sizing.model_active`=on이면 `order_executor`가 신모델 qty로 override → 레짐SET `max_positions`(12/7/4/2)·`risk.max_positions`(5)는 死(표시/드리프트 대조용). 주력 제약은 95% 배포캡. | ✅ 완료 |
| 2 | ~~exploration_mode~~ **완전 제거(2026-08-22)** | `is_exploration_allowed`=하드False, 매수경로·UI·死설정 제거. 매수=baseline S4/S5만. | ✅ 완료 |
| 3 | min_ai_confidence 타입 | DB에 문자열 `"0.60"` 저장(코드가 float coerce라 동작은 정상) | 숫자로 정규화(선택) |
| 4 | flash_crash 상태플래그 | `flash_crash_defense_active=true`(date 8/19). 날짜스코프라 다음 거래일 자동해제(동작 정상) | 상태값이라 INTENT 제외 |
| 5 | ~~레짐 임계 하드코딩~~ **해소(2026-08-23 활성)** | `regime.set_source`=**5tier(기본)** — SET매칭이 설정기반 `classify_regime_5tier`→`regime_to_set`(드리프트 감시). `_resolve_set_regime` dispatch. 롤백=judge. **월요일 첫 실전 관찰** | ✅ 완료 |
| 6 | buy_condition_framework 태깅잔존 | 탐색 OR **매수경로 제거**(2026-08-22). 프레임워크는 `_record_exploration_tag`(진입 조건발화 기록·계측)만 잔존. 원자조건/조건그룹 UI 삭제. | 계측 데이터 활용 시 게이트화 검토 |

> **감시 범위:** INTENT 명시설정(~40)+코드기본(14)+레짐SET(**4**, volatile 추가 2026-08-23)은 드리프트 자동감시. 위 6개(특히 1·5·6)는 **구조적이라 수동 관리** — 전략 변경 시 반드시 재확인.

---

## B. 실측 — 지금 실제로 이렇게 돈다 (자동 생성, 손대지 마라)

<!-- AUTO:LIVE START -->
_자동 생성: 2026-08-24 03:11:11 · `scripts/strategy_spec_sync.py` · 손대지 마라._

**현재 활성 레짐:** `risk_off` (trigger=intraday, at=2026-08-24T11:00:10)

**전략 게이트/설정 (system_settings 실측 · 출처):**

| 설정 | 실측값 | 출처 |
|---|---|---|
| `engine.entry_vwap_pullback_mode` | `enforce` | DB |
| `engine.max_price_change_pct` | `4.0` | DB |
| `engine.min_price_change_pct` | `1.5` | DB |
| `engine.min_volume_ratio` | `1.5` | DB |
| `engine.confidence_gate_mode` | `regime_defensive` | DB |
| `engine.min_ai_confidence` | `0.60` | DB |
| `engine.min_confidence_floor` | `0.5` | DB |
| `engine.calibration_gate_enabled` | `True` | DB |
| `engine.calibration_gate_gap` | `0.15` | DB |
| `engine.calibration_gate_min_samples` | `30` | DB |
| `engine.band_inversion_guard_enabled` | `True` | DB |
| `engine.exclude_etf_enabled` | `True` | DB |
| `engine.enforce_new_entry_allowed` | `True` | DB |
| `engine.entry_fail_cooldown_enabled` | `True` | DB |
| `engine.entry_fail_cooldown_days` | `3` | DB |
| `engine.entry_fail_cooldown_min_count` | `2` | DB |
| `engine.regime_confidence_bonus_risk_off` | `0.05` | DB |
| `engine.regime_confidence_bonus_volatile` | `0.1` | DB |
| `engine.entry_execute_start_time` | `09:30` | DB |
| `engine.entry_start_time` | `09:00` | DB |
| `engine.entry_end_time` | `15:00` | DB |
| `risk.new_entry_cutoff_time` | `15:10` | DB |
| `engine.harvest_mode` | `True` | DB |
| `engine.scaleout_ratio` | `0.5` | DB |
| `engine.scaleout_target_rate` | `0.02` | DB |
| `engine.scaleout_ratio_after_target` | `0.8` | DB |
| `engine.daily_target_rate` | `0.02` | DB |
| `engine.stop_source` | `regime` | DB |
| `exploration.deploy_target_rate` | `0.95` | DB |
| `risk.max_positions` | `5` | DB |
| `risk.max_position_rate_per_stock` | `0.15` | DB |
| `engine.crash_playbook_enabled` | `True` | DB |
| `regime.evening_confidence_enabled` | `True` | DB |
| `risk.daily_loss_limit_percent` | `-5` | DB |
| `risk.force_exit_time` | `15:20` | DB |
| `risk.flash_crash_threshold_pct` | `-5` | DB |
| `risk.flash_crash_defense_enabled` | `True` | DB |
| `risk.emergency_halt_enabled` | `False` | DB |
| `engine.s10_llm_review_enabled` | `False` | DB |
| `engine.loss_autotune_apply_enabled` | `False` | DB |
| `engine.entry_max_vwap_dist_pct` | `0.0` | 코드기본 |
| `engine.intraday_max_stoploss_per_symbol` | `2` | 코드기본 |
| `engine.intraday_reentry_block_enabled` | `True` | 코드기본 |
| `engine.leverage_restriction_mode` | `exclude` | 코드기본 |
| `engine.loss_streak_hard_block_enabled` | `True` | 코드기본 |
| `engine.min_liquidity_krw` | `100000000` | 코드기본 |
| `risk.auto_halt_loss_percent` | `-5.0` | 코드기본 |
| `risk.force_exit_ceiling` | `15:12:00` | 코드기본 |
| `risk.partial_fill_reorder_enabled` | `True` | 코드기본 |
| `risk.stop_loss_backup_enabled` | `True` | 코드기본 |
| `risk.stop_loss_backup_stale_sec` | `45` | 코드기본 |
| `regime.intraday_kis_kospi_enabled` | `True` | 코드기본 |
| `regime.intraday_live_driver_enabled` | `True` | 코드기본 |
| `exploration.weight_floor` | `0.2` | 코드기본 |
| `regime.down_pct` | `-1.5` | 코드기본 |
| `regime.up_pct` | `0.5` | 코드기본 |
| `regime.surge_pct` | `2.5` | 코드기본 |
| `regime.vix_volatile` | `28.0` | 코드기본 |
| `regime.down_transition_pp` | `-1.0` | 코드기본 |
| `regime.up_transition_pp` | `1.0` | 코드기본 |
| `regime.li_lean_weight` | `0.25` | 코드기본 |
| `regime.transition_window_min` | `60` | 코드기본 |
| `regime.transition_response_active` | `True` | DB(오버라이드) |
| `regime.transition_trail_tighten_factor` | `0.5` | DB(오버라이드) |
| `regime.set_source` | `5tier` | DB(오버라이드) |
| `selection.weights_source` | `settings` | 코드기본 |
| `selection.change_weight` | `0.5` | 코드기본 |
| `selection.surge_weight` | `0.5` | 코드기본 |
| `sizing.per_position_rate_min` | `0.05` | 코드기본 |
| `sizing.positions_min` | `6` | 코드기본 |
| `sizing.positions_max` | `19` | 코드기본 |
| `sizing.surge_per_position_rate_max` | `0.15` | 코드기본 |
| `conviction.regime_weight` | `0.5` | 코드기본 |
| `conviction.pullback_full_dist_pct` | `-3.0` | 코드기본 |
| `engine.conviction_gate_min` | `0.0` | 코드기본 |
| `sizing.model_active` | `True` | DB(오버라이드) |

**레짐 SET별 매도 파라미터 (실측):**

| 레짐 | max종목 | 손절 | 익절 | 트레일발동 | 트레일폭 |
|---|---|---|---|---|---|
| risk_on | 12 | -0.035 | 0.08 | 0.04 | 0.02 |
| neutral | 7 | -0.04 | 0.08 | 0.035 | 0.025 |
| risk_off | 4 | -0.04 | 0.07 | 0.03 | 0.025 |

_드리프트 4건 (아래 C절 참조)_
<!-- AUTO:LIVE END -->

---

## C. 드리프트 체크 — 실측이 의도를 벗어났나 (자동 생성, 손대지 마라)

<!-- AUTO:DRIFT START -->
_자동 생성: 2026-08-24 03:11:11_

🔴 **드리프트 4건** — 실측이 의도를 벗어났다. 각 항목을 의도대로 되돌리거나, 의도가 바뀐 것이면 A절+INTENT를 갱신하라.

- 🔴 SET `risk_on.stop_loss_rate` 불일치 — 의도 `-0.045` vs 실측 `-0.035`
- 🔴 SET `risk_on.take_profit_rate` 불일치 — 의도 `0.12` vs 실측 `0.08`
- 🔴 SET `risk_on.trailing_stop_rate` 불일치 — 의도 `0.03` vs 실측 `0.02`
- ⚠ 레짐 SET `volatile` 실측 없음 — 의도 존재
<!-- AUTO:DRIFT END -->

---

## 개발 사이클 — SSOT ↔ 구현 완전 맞물림 (PM 원칙)

> **SSOT부터 수정 → 개발 → 완료 후 SSOT대로 됐는지 검증.** 이 폐루프가 완성이다.
> 나중에 뭔가 잘못되면 **A절(의도)부터 고치고** 그다음 구현을 바꾼다. 코드가 SSOT를 앞서지 않는다.

```
① SSOT 수정(A절 의도 + INTENT + CONFORMANCE)
      ↓
② 개발(구현 + 유닛테스트, TDD)
      ↓
③ 검증: python scripts/strategy_spec_sync.py --check
      - 드리프트(설정 값)  = 실측 == 의도 ?
      - conformance(맞물림) = SSOT가 말하는 구현·설정이 실제 존재하나 ?
      둘 다 ✅ 라야 "SSOT대로 됨" 확정. (라이브 워치독도 5분마다 같은 검사)
```

**두 층위 검증:**
- **드리프트** = 설정 *값* 일치 (`INTENT_SETTINGS`/`CODE_DEFAULTS`/레짐SET vs 라이브 DB).
- **conformance** = SSOT 주장의 *구현* 존재 (`CONFORMANCE` 매핑의 코드심볼·설정키). 코드가 사라지거나 이름 바뀌면 여기서 깨진다.

**규칙:**
1. **전략/구현을 바꿀 때:** A절 서술 + `strategy_spec.py`의 `INTENT_*` + (새 구현이면) `CONFORMANCE` 매핑을 **함께** 갱신.
2. **개발 완료 후:** `--check`로 드리프트 0 **그리고** conformance 0 확인. 하나라도 깨지면 미완료.
3. **실측 반영:** `python scripts/strategy_spec_sync.py` 실행 → B·C 갱신(멱등).
4. **어긋남 발견 시:** 버그면 구현을 SSOT대로 되돌리고, 의도가 바뀐 것이면 1번(SSOT부터 수정). **드리프트·conformance 0을 항상 유지.**
