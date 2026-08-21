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

---

## A. 의도 — 이렇게 동작해야 한다

### A-0. 핵심 철학
- **연산·판단·실행 = 결정론 시스템 / 코딩·분석·전략 = PM+Claude 수동 통제.** LLM 매매개입 0.
- **이기는 진입 = VWAP 아래 눌림목**(데이터 확증: 승률 ~60%). **고점추격 금지**(~30% 승, 손실 뿌리).
- 장세는 레벨(코스피 %)만이 아니라 **방향(가속·정체·꺾임)** 으로 판단해야 한다. → 전환 감지(§A-5, 개발 예정).
- 어떤 자동 메커니즘도 사람 확인 없이 매매 파라미터를 바꾸지 않는다(S10 LLM·loss auto-tuner 관찰전용).

### A-1. 레짐(장세) 탐지 — 30분 틱 (09:30~15:00)
탐지는 `intraday_regime_monitor._judge_regime`(KOSPI·VIX 레벨) + `risk.flash_crash_*`(즉시 방어).

| 장세 | 탐지 조건(의도) | 현재 구현 |
|---|---|---|
| **폭락** | KOSPI ≤ -2% (즉시·디바운스 우회) | ✅ flash_crash (검증 8/19) |
| **하락** | KOSPI < -1.5% (또는 VIX>22 & KOSPI<-1) | ✅ risk_off |
| **보합** | -1.5% ≤ KOSPI ≤ +0.5% | ✅ neutral |
| **상승** | KOSPI > +0.5%, VIX < 22 | ✅ risk_on (검증 8/18·8/20) |
| **폭등** | KOSPI > +2.5% — 상승의 **사이징 확대 티어**(별도 전략 아님) | ✗ 미구현 (상승에 흡수) |
| **하락전환** | 최근 30분 KOSPI **-1.0%p↓** (레벨 무관·방향) | ✗ 미구현 ← **최우선 구멍** |
| **상승전환** | 최근 30분 KOSPI **+1.0%p↑** 반등 | ✗ 미구현 |
| (VIX축) volatile | VIX > 28 | ✅ (5장세와 직교) |

> **왜 전환이 최우선인가 (8/18 실증):** +2.7%출발 → +2.77%꼭지 → +1.25%(11:00) → -0.19%(11:30) → -1.5%마감.
> 레짐은 레벨만 봐서 11:30(이미 마이너스)에야 neutral로 바뀜 → 그 사이 봇은 risk_on(공격)으로 꼭지 매수 → -2.16M.
> **레벨은 아직 +1.25%여도 방향은 하락전환.** 이걸 잡는 게 §A-5.

> ⚠ **레짐 임계는 코드 하드코딩**(`_judge_regime`: vix>28/22, kospi ±1.5/0.5) — **설정이 아니라 드리프트 감시 불가.** 바꾸려면 코드 수정 + 이 문서 갱신. 설정화는 후속 과제.

### A-2. 종목 선정
| 장세 | 선정 의도 | 현재 |
|---|---|---|
| 공통 | 거래량 순위(`quant_topup`) + VWAP 눌림목 게이트 | ✅ |
| 폭락 | 인버스1x + 급락반등주 트랙 허용 | △ 구현(효과 미검증) |
| 하락·보합 | 방어적 선정(상대강도·저변동) | ✗ 미구현 |

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

- **폭락:** 신규진입 차단(인버스1x 예외). **폭등(예정):** 눌림깊이 완화 + 사이징 확대(§A-4b). **하락전환(예정, §A-5):** 신규매수 즉시 중단.

### A-4. 매도 — 레짐 SET별 차등 + 공통 수확 (값은 B절 실측)
- **레짐 SET**이 손절/익절/트레일링/최대종목수를 레짐별 차등(risk_on 넓게 -3.5%/+8% / risk_off 타이트 -1.2%/+2.5%).
- **스케일아웃 수확**(`harvest_mode`=on): `scaleout_target_rate`(+1%)서 `scaleout_ratio`(60%) 확정 + 잔량 러너, 목표후 `scaleout_ratio_after_target`(80%). 하루 목표 `daily_target_rate`(계좌 +2%).
- **공통:** EOD 강제청산(`force_exit_time` 15:20 / `force_exit_ceiling` 15:12) · 폭락 방어모드(검증 8/19) · 무틱 손절 REST 백업(`stop_loss_backup_*`).
- **하락전환(예정):** 트레일링 즉시 조임.

### A-4b. 사이징·배포 — 예수금비중 모델 (결정4, Phase1 구현중)
**종목수가 아니라 예수금 투입비중이 기준.** 확신↑ → 종목당 비중↑ → 집중, 확신↓ → 분산.
종목수는 파생 결과. 구현: `strategy_playbook.resolve_position_sizing` (소비자 배선은 shadow 검증 후).

| 레버 | 설정키 | 값 | 의미 |
|---|---|---|---|
| 종목당 비중 | `sizing.per_position_rate_min` ~ `risk.max_position_rate_per_stock` | **5% ~ 15%** | 확신도로 보간 |
| 종목수(파생) | `sizing.positions_min` ~ `sizing.positions_max` | **6 ~ 19** | 배포/비중, 클램프 |
| 총배포 상한 | `exploration.deploy_target_rate` | 0.95 | 예수금 95% |

> 예: 확신 1.0 → 15%×6종목 집중 / 확신 0.0 → 5%×19종목 분산. (구 `risk.max_positions=5`·레짐SET 12·RulePack 10 **3출처 충돌은 이 [6,19] 범위 모델로 대체** — §A-7 #1 해소 예정)
> ⚠ `engine.exploration_mode`=on(졸업 의도 확인, §A-7 #2)

**확신도(conviction) 모델** — 위 사이징의 "확신"을 정하는 법. 구현: `strategy_playbook.resolve_conviction`.
`확신 = regime_weight × 레짐점수 + (1−regime_weight) × 눌림점수` (전부 설정 = 언제든 수정).

| 설정키 | 값 | 의미 |
|---|---|---|
| `conviction.regime_weight` | 0.5 | 장세 vs 눌림 비중 (1=장세만·0=눌림만) |
| `conviction.regime_scores` | risk_on 1.0 … risk_off 0.2 | 장세별 점수(JSON) |
| `conviction.pullback_full_dist_pct` | -3.0 | VWAP 아래 이만큼 눌리면 눌림점수 만점(위=추격=0) |

> risk_on+깊은눌림=1.0(집중) / risk_off+추격=0.1(분산). **배선 상태:** 순수함수+유닛 완료, **order_executor 배선은 shadow 검증 후**(현재 미배선=동작불변).

### A-4c. 리스크 할트·안전벨트
| 레버 | 설정키 | 현재값 |
|---|---|---|
| 일일 손실한도 | `risk.daily_loss_limit_percent` | -2% |
| 자동 정지선 | `risk.auto_halt_loss_percent` | -5% |
| 폭락 방어 발동 | `risk.flash_crash_threshold_pct`·`flash_crash_defense_enabled` | -2%·on |
| 수동 긴급정지 | `risk.emergency_halt_enabled` | off(평시) |
| 부분체결 재주문 | `risk.partial_fill_reorder_enabled` | on |

### A-5. 전환(하락/상승) 대응 — 개발 예정 (백테스트 선행)
현 레짐(레벨)에 **"최근 30~60분 KOSPI 기울기" 축**을 추가. 레벨이 아직 +면서도 급히 꺾이면 하락전환 판정 → 신규매수 중단 + 트레일 조임. 반대(바닥 반등)는 상승전환 → 진입 재개.
**착수 전 검증:** "8/18에 -1.0%p/30분 하락 시 매수중단했으면 손실이 얼마나 줄었나"를 `scripts/edge_backtest.py` 계열로 실증 후 구현.

### A-6. 검증 상태 요약
| 검증됨 ✅ | 미검증 ✗ |
|---|---|
| VWAP 눌림목 엣지(17일 백테스트+실전) · flash_crash 폭락 방어(8/19) · 30분 레짐 재판정 · churn 가드 | 전환(방향) 감지 · 폭등 티어 · 레짐별 종목선정 · 레짐 SET 값 최적성 |

### A-7. 관리 주의 — 다출처 충돌·이상 (반드시 인지, 미해결)
전략이 "새는" 지점들. 드리프트 자동감시로 못 잡는 구조적 문제이므로 여기 명시한다.

| # | 이슈 | 실태 | 해결 방향 |
|---|---|---|---|
| 1 | **max_positions 3출처 충돌** | `risk.max_positions=5` · 레짐SET(risk_on)=12 · RulePack `final_rule`≈10. **실제 주문차단은 RulePack final_rule**(order_preflight). | **Phase 2 단일출처화**. PM이 목표 종목수 확정 필요 |
| 2 | **exploration_mode=on** | 탐색 사이징 활성. 메모리상 7/4 "졸업" 의도였으나 플래그는 아직 on. | 졸업 여부 PM 확인 → off면 의도 갱신 |
| 3 | min_ai_confidence 타입 | DB에 문자열 `"0.60"` 저장(코드가 float coerce라 동작은 정상) | 숫자로 정규화(선택) |
| 4 | flash_crash 상태플래그 | `flash_crash_defense_active=true`(date 8/19). 날짜스코프라 다음 거래일 자동해제(동작 정상) | 상태값이라 INTENT 제외 |
| 5 | 레짐 임계 하드코딩 | `_judge_regime` 임계가 설정 아님 → 드리프트 감시 불가 | 설정화(후속) |
| 6 | buy_condition_framework 휴면 | 돌파/눌림/모멘텀 그룹·체결강도 55% 코드 존재하나 **메인 진입경로가 우회**(등락률+거래량만) | 엣지 게이트화 시 정리(②③ 이후) |

> **감시 범위:** INTENT 명시설정(~40)+코드기본(14)+레짐SET(3)은 드리프트 자동감시. 위 6개(특히 1·5·6)는 **구조적이라 수동 관리** — 전략 변경 시 반드시 재확인.

---

## B. 실측 — 지금 실제로 이렇게 돈다 (자동 생성, 손대지 마라)

<!-- AUTO:LIVE START -->
_자동 생성: 2026-08-21 01:14:05 · `scripts/strategy_spec_sync.py` · 손대지 마라._

**현재 활성 레짐:** `neutral` (trigger=intraday, at=2026-08-21T10:00:05)

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
| `engine.scaleout_ratio` | `0.6` | DB |
| `engine.scaleout_target_rate` | `0.01` | DB |
| `engine.scaleout_ratio_after_target` | `0.8` | DB |
| `engine.daily_target_rate` | `0.02` | DB |
| `exploration.deploy_target_rate` | `0.95` | DB |
| `risk.max_positions` | `5` | DB |
| `risk.max_position_rate_per_stock` | `0.15` | DB |
| `engine.exploration_mode` | `True` | DB |
| `engine.crash_playbook_enabled` | `True` | DB |
| `regime.evening_confidence_enabled` | `True` | DB |
| `risk.daily_loss_limit_percent` | `-2` | DB |
| `risk.force_exit_time` | `15:20` | DB |
| `risk.flash_crash_threshold_pct` | `-2.0` | DB |
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
| `sizing.per_position_rate_min` | `0.05` | 코드기본 |
| `sizing.positions_min` | `6` | 코드기본 |
| `sizing.positions_max` | `19` | 코드기본 |
| `conviction.regime_weight` | `0.5` | 코드기본 |
| `conviction.pullback_full_dist_pct` | `-3.0` | 코드기본 |

**레짐 SET별 매도 파라미터 (실측):**

| 레짐 | max종목 | 손절 | 익절 | 트레일발동 | 트레일폭 |
|---|---|---|---|---|---|
| risk_on | 12 | -0.035 | 0.08 | 0.04 | 0.02 |
| neutral | 7 | -0.02 | 0.045 | 0.025 | 0.012 |
| risk_off | 4 | -0.012 | 0.025 | 0.015 | 0.008 |

_드리프트 0건 (아래 C절 참조)_
<!-- AUTO:LIVE END -->

---

## C. 드리프트 체크 — 실측이 의도를 벗어났나 (자동 생성, 손대지 마라)

<!-- AUTO:DRIFT START -->
_자동 생성: 2026-08-21 01:14:05_

✅ **드리프트 없음** — 실측이 의도와 일치한다. 시스템이 사양대로 동작 중.
<!-- AUTO:DRIFT END -->

---

## 갱신 규칙
1. **전략을 바꿀 때:** 위 A절(의도) 서술 + `scripts/strategy_spec_sync.py`의 `INTENT_SETTINGS`/`INTENT_REGIME_SETS`를 **함께** 수정한다.
2. **실측 반영:** 설정을 바꾸거나 배포한 뒤 `python scripts/strategy_spec_sync.py` 실행 → B·C 갱신.
3. **드리프트 발견 시:** C절 각 항목은 "실측이 의도와 다르다"는 뜻. **버그면 실측을 의도대로 되돌리고, 의도가 바뀐 것이면 1번을 수행**한다. 드리프트 0을 유지한다.
