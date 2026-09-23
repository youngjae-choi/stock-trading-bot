"""전략 사양서(STRATEGY_SPEC.md) 단일 진실원천 — 의도 vs 실측 대조 로직.

이 모듈이 **전략 의도(INTENT)의 단일 소스**다. CLI(`scripts/strategy_spec_sync.py`)와
서버 워치독(ops_watchdog)이 이 모듈을 import해 같은 기준으로 드리프트를 판단한다.

- `check_drift()`  : 라이브 DB 실측 ≠ 의도 불일치 목록(문장) 반환. 파일 미수정. 워치독용.
- `sync_strategy_spec(write=True)` : STRATEGY_SPEC.md의 B(실측)·C(드리프트) 블록 재작성.
  멱등 — 타임스탬프 외 변화가 없으면 파일 미수정(git 노이즈 방지). CLI/EOD용.

읽기 전용(라이브 DB mode=ro) + STRATEGY_SPEC.md 파일 쓰기만. KIS 호출 없음.

★ 전략을 바꾸면: STRATEGY_SPEC.md의 A절(의도) + 아래 INTENT 딕셔너리를 함께 고친다.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "data" / "stock_trading_bot.sqlite3"
SPEC = ROOT / "STRATEGY_SPEC.md"

# ─────────────────────────────────────────────────────────────────────────
# 의도(INTENT) — 이 시스템이 이렇게 동작해야 한다. 드리프트 대조의 기준값.
# 전략을 바꾸면 여기와 STRATEGY_SPEC.md A절을 함께 수정한다.
# ─────────────────────────────────────────────────────────────────────────
INTENT_SETTINGS: dict[str, object] = {
    # ── 매수: 진입 게이트/선별 ──
    "engine.entry_vwap_pullback_mode": "enforce",   # 눌림목 게이트 활성(고점추격 차단)
    "engine.max_price_change_pct": 4.0,             # 고점추격 상한(시가대비 +4% 초과 매수 차단)
    "engine.min_price_change_pct": 1.5,             # 진입 최소 등락률
    "engine.min_volume_ratio": 1.5,                 # 진입 최소 거래량 배수
    "engine.confidence_gate_mode": "regime_defensive",  # 컨피던스 게이트(방어레짐만 강화)
    "engine.min_ai_confidence": "0.60",             # 최소 confidence(문자열 저장·float coerce)
    "engine.min_confidence_floor": 0.5,             # confidence 하한
    "engine.calibration_gate_enabled": True,        # 캘리브레이션 게이트
    "engine.calibration_gate_gap": 0.15,
    "engine.calibration_gate_min_samples": 30,
    "engine.band_inversion_guard_enabled": True,    # 밴드역전 마비 가드
    "engine.exclude_etf_enabled": True,             # ETF 제외
    "engine.enforce_new_entry_allowed": True,       # 신규진입 플래그 강제
    "engine.entry_fail_cooldown_enabled": True,     # 진입실패 쿨다운
    "engine.entry_fail_cooldown_days": 3,
    "engine.entry_fail_cooldown_min_count": 2,
    "engine.regime_confidence_bonus_risk_off": 0.05,
    "engine.regime_confidence_bonus_volatile": 0.1,
    # ── 매수: 실행 시간창 ──
    "engine.entry_execute_start_time": "09:30",     # 실매매 시작(이전은 shadow)
    "engine.entry_start_time": "09:00",             # 후보 로깅 시작
    "engine.entry_end_time": "15:00",               # 진입 종료
    "risk.new_entry_cutoff_time": "15:10",          # 신규진입 컷오프
    # ── 매도: 스케일아웃/수확 ──
    "engine.harvest_mode": True,                    # 스케일아웃 수확 모드(부분익절+러너)
    "engine.scaleout_ratio": 0.5,                   # 1차 확정 비율(2026-08-23: 0.6→0.5, 러너 절반 확보)
    "engine.scaleout_target_rate": 0.02,            # 스케일아웃 발동 수익률(2026-08-23: +1%→+2%, 노이즈 밖 수확)
    "engine.scaleout_ratio_after_target": 0.8,
    "engine.daily_target_rate": 0.02,               # 하루 목표(계좌 대비)
    "engine.stop_source": "regime",                 # 손절/트레일 출처: regime(국면SET·결정된 단일출처, 2026-08-22)|profile(폴백). 롤백스위치
    # ── 사이징/배포 ──
    "exploration.deploy_target_rate": 0.95,         # 예수금 배포 목표(95%)
    # risk.max_positions 제거(2026-09-01, 9e9e51d) — 死 중복 count 설정. 단일출처=resolve_max_positions
    # (sizing.positions_max 19, 안전 fallback), 주 제어=배포캡 95%. INTENT에서도 제거해 드리프트 오탐 방지.
    "risk.max_position_rate_per_stock": 0.15,       # 종목당 비중 상한(15%)
    # 탐색모드 제거(2026-08-22) — engine.exploration_mode 死키. is_exploration_allowed 하드 False.
    # ── 레짐/시황 ──
    "engine.crash_playbook_enabled": True,
    "regime.evening_confidence_enabled": True,
    # ── 리스크 할트/방어 ──
    "risk.daily_loss_limit_percent": -5,            # 일일 손실 한도(변동성장 적응 -2→-5, admin 2026-08-23 — -2%면 10%출렁장 과조기 할트)
    "risk.force_exit_time": "15:20",                # 강제청산 시각
    "risk.flash_crash_threshold_pct": -5.0,         # 폭락 방어모드 발동선(변동성장 적응 — 2% 순간이동 오발 방지, PM 2026-08-23)
    "risk.flash_crash_defense_enabled": True,
    "risk.emergency_halt_enabled": False,           # 수동 긴급정지(평시 off)
    # ── AI/자동화 제거(수동통제) ──
    "engine.s10_llm_review_enabled": False,         # LLM 복기 제거
    "engine.loss_autotune_apply_enabled": False,    # 손실 auto-tuner 관찰전용
}
# 코드기본값에 숨은 전략 레버 — DB에 없어도 코드가 이 값으로 돈다(의도=코드기본).
# DB에 다른 값으로 오버라이드되면 그때만 드리프트(의도 이탈)로 잡는다. 가시화용.
INTENT_CODE_DEFAULTS: dict[str, object] = {
    "engine.entry_max_vwap_dist_pct": -1.0,         # 눌림목 천장(보합/하락) — VWAP 1%↓ 눌림만 (2026-09-01 조임)
    "engine.entry_max_vwap_dist_pct_riskon": 0.0,   # 눌림목 천장(상승장) 완화 — VWAP까지 허용 (2026-09-05 BackDB)
    "engine.entry_min_vwap_dist_pct": -5.0,         # 눌림목 바닥 — 딥눌림(<-5% falling knife) 차단 (2026-09-05)
    "engine.buy_submit_retry_enabled": True,        # 매수 접수 실패 재시도+ODNO 복구 (2026-09-05)
    "engine.entry_change_from_open_mode": "shadow",  # 시가대비 추격금지 게이트(관찰중, enforce전환 예정) (2026-09-05)
    "engine.entry_max_change_from_open_pct": 2.0,    # 오늘 시가 +2% 초과 진입=갭추격 차단(엣지: 승률33%)
    # ── E6 강세근접VWAP: 상승장 필승패턴(2026-09-18 uptrend_pattern 22일 백테스트: 상승장 76%승·EV+0.63%) ──
    #   강세종목(시가대비>0)이 VWAP 0~+1% 위로 얕게 눌릴 때 매수 + 타이트 트레일 청산. 상승장 전용.
    #   현행 게이트는 상승장서도 VWAP 위 매수를 구조적 차단(entry_max_vwap_dist_pct_riskon=0.0)해 승리구간 봉쇄.
    #   보합/하락은 기존 눌림 게이트가 이김 → 절대 불변(전부 상승장 전용, 롤백=uptrend_entry_mode off).
    "engine.uptrend_entry_mode": "enforce",          # off|shadow|enforce — E6 진입 마스터 롤백
    "engine.entry_vwap_ceiling_riskon": 1.0,         # 상승장 VWAP 밴드 천장(%) — +1=VWAP 1% 위까지 허용
    "engine.entry_vwap_floor_riskon": 0.0,           # 상승장 VWAP 밴드 바닥(%) — 0=VWAP 이상만(상승장선 아래눌림 배제)
    "engine.entry_require_strength_riskon": True,     # 상승장 강세요건(시가대비>0=오른 종목만) 강제
    "engine.exit_riskon_trail_activate": 0.02,       # 상승장(비폭등) 트레일 발동(+2%)
    "engine.exit_riskon_trail_stop": 0.015,          # 상승장 트레일 폭(1.5%)
    "engine.exit_surge_trail_activate": 0.03,        # 폭등장 트레일 발동(+3%, 더 태움)
    "engine.exit_surge_trail_stop": 0.02,            # 폭등장 트레일 폭(2%)
    "engine.exit_hybrid_mode": "enforce",            # off|enforce — 상승/폭등 트레일 오버라이드 롤백
    "momentum.enabled": True,                        # 리더 진입(실전) 활성 — 눌림과 독립 경로. 롤백 스위치 (2026-09-07)
    "momentum.entry_mode": "pullback",               # pullback=E6 강세근접VWAP(상승장 전용·09-18 필승패턴) | breakout=구 ORB추격(꼭지매수·기본비활)
    "momentum.rs_min": 4.0,                          # (breakout전용) 상대강도 임계(시가대비≥+4%). 백테스트: 강세4=승률83%·순+1.36%
    "momentum.entry_premium_pct": 1.5,               # 돌파가 +1.5% 지정가(빠른 리더 체결력, 호가 스냅) — order_style=limit일 때만 사용
    "momentum.order_style": "market",                # 진입 주문방식: market=시장가(감지 즉시 체결 보장·빠른 리더 추격) / limit=지정가+프리미엄(체결 미보장) (2026-09-18)
    "momentum.buy_spacing_sec": 1.5,                 # 모멘텀 매수 간격(KIS 초당한도 EGW00215 회피)
    "momentum.max_attempts": 3,                      # #1 일시적 실패(rate-limit) 당일 재시도 상한 (2026-09-09)
    "momentum.max_late_chase_pct": 2.0,              # #2 돌파가 대비 현재가 +2%↑면 뒷북=보류 (2026-09-09)
    "engine.intraday_max_stoploss_per_symbol": 2,   # churn 가드 N회
    "engine.intraday_reentry_block_enabled": True,
    "engine.leverage_restriction_mode": "exclude",  # 레버리지/인버스2x 진입 차단
    "engine.loss_streak_hard_block_enabled": True,  # 3연패 하드블록
    "engine.min_liquidity_krw": 100_000_000,        # 최소 유동성 1억
    "risk.auto_halt_loss_percent": -5.0,            # 자동 정지 손실선
    "risk.force_exit_ceiling": "15:12:00",          # 강제청산 상한 시각
    "risk.partial_fill_reorder_enabled": True,
    "risk.stop_loss_backup_enabled": True,          # 무틱 종목 손절 REST 백업
    "risk.stop_loss_backup_stale_sec": 45,
    "regime.intraday_kis_kospi_enabled": True,      # 장중 KOSPI KIS 직접조회
    "regime.intraday_live_driver_enabled": True,    # 장중 실시간 레짐 드라이버
    "exploration.weight_floor": 0.2,                # 탐색 비중 하한
    # ── 시장감지 엔진② 5장세·전환 임계(설정화, A-7#5 해소) ──
    "regime.down_pct": -1.5,                        # 하락 임계
    "regime.up_pct": 0.5,                           # 상승 임계
    "regime.surge_pct": 2.5,                        # 폭등 임계
    "regime.vix_volatile": 28.0,                    # volatile VIX 임계
    "regime.down_transition_pp": -1.0,              # 하락전환: window 내 -1.0%p
    "regime.up_transition_pp": 1.0,                 # 상승전환: window 내 +1.0%p
    "regime.li_lean_weight": 0.25,                  # 선행지표 lean 바이어스 가중
    "regime.transition_window_min": 60,             # 전환 판단 window(분)
    "regime.transition_response_active": True,      # 전환 대응 활성(2026-08-23 PM) — 하락전환 매수중단+트레일조임
    "regime.transition_trail_tighten_factor": 0.5,  # 하락전환시 트레일폭 배수(0.5=절반조임, 러너 이익잠금)
    "regime.set_source": "5tier",                   # SET 선택 regime 출처: 5tier(설정기반 classify_regime_5tier, 활성 2026-08-23)|judge(하드코딩 폴백). §A-7#5 롤백스위치
    # ── 종목선정 엔진③ 점수 가중치(배선 완료 2026-08-23 — universe_filter가 라이브 소비) ──
    "selection.weights_source": "settings",         # settings=아래 가중치 라이브 소비(배선)|tone=구 _TONE_WEIGHTS. 롤백스위치
    "selection.change_weight": 0.5,                 # 등락률 가중(라이브 — 선정에 반영)
    "selection.surge_weight": 0.5,                  # 거래량급증 가중(라이브 — 선정에 반영)
    # ── 사이징 모델(결정4, Phase1) — 예수금비중: 종목당 5~15%, 종목수 6~19 ──
    "sizing.per_position_rate_min": 0.05,           # (레거시·표시용) 종목당 최소 비중
    "sizing.positions_min": 6,                      # (레거시) 무결성 백스톱용
    "sizing.positions_max": 19,                     # (레거시) 무결성 백스톱용
    "sizing.surge_per_position_rate_max": 0.15,     # 폭등 티어 종목당 상한(비율, max_krw 확대 판정)
    # 2026-08-29 PM: 종목수 결정 폐지 → 종목당 절대금액으로 통제(투입율 + [min,max] 금액). 종목수는 파생.
    "sizing.per_position_min_krw": 5_000_000,       # 종목당 최소 금액 500만 (확신 0 = 분산)
    "sizing.per_position_max_krw": 20_000_000,      # 종목당 최대 금액 2000만 (확신 1 = 집중)
    # ── 확신도 모델(레짐×눌림 결합, 전부 설정화 = 언제든 수정) ──
    "conviction.regime_weight": 0.5,                # 장세 vs 눌림 비중(1=장세만·0=눌림만)
    "conviction.pullback_full_dist_pct": -3.0,      # 이만큼 눌리면 눌림점수 만점
    "engine.conviction_gate_min": 0.0,              # ④ 품질게이트 최소 conviction(0=OFF·기본). suitability sparse 대체, >0시 활성. 롤백스위치
    "sizing.model_active": True,                    # 예수금비중 신모델 활성(2026-08-21 검증후 on)
}
# 레짐 SET별 매도 파라미터 의도 (regime SET applied_settings 와 대조)
# ★ 변동성 재보정(2026-08-23): 종목 장중 9.4% 출렁 실측 + 데이트레이더 관행(ATR·inverse-vol) →
#   손절을 노이즈(편도 4.7%) 밖으로 넓히고, 트레일도 넓게(러너 극대화). 방어=포지션수↓(사이징모델).
#   take_profit_rate는 표시용(rule_resolver가 take_profit_enabled=False 강제) — 실익절=트레일+scaleout.
#   max_positions는 死(사이징모델 6~19가 order_executor에서 override) — 표시/드리프트 대조용만 유지.
INTENT_REGIME_SETS: dict[str, dict[str, float]] = {
    "risk_on":  {"max_positions": 12, "stop_loss_rate": -0.045, "take_profit_rate": 0.12,
                 "trailing_activate_profit": 0.04, "trailing_stop_rate": 0.03},
    "neutral":  {"max_positions": 7,  "stop_loss_rate": -0.04,  "take_profit_rate": 0.08,
                 "trailing_activate_profit": 0.035, "trailing_stop_rate": 0.025},
    "risk_off": {"max_positions": 4,  "stop_loss_rate": -0.04,  "take_profit_rate": 0.07,
                 "trailing_activate_profit": 0.03, "trailing_stop_rate": 0.025},
    "volatile": {"max_positions": 2,  "stop_loss_rate": -0.05,  "take_profit_rate": 0.10,
                 "trailing_activate_profit": 0.04, "trailing_stop_rate": 0.03},
}
_FLOAT_TOL = 1e-9


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def read_live_settings(conn) -> dict[str, object]:
    """system_settings에서 의도 대상 키(명시+코드기본)의 실측값(파싱)을 읽는다. 없으면 미포함."""
    keys = list(INTENT_SETTINGS) + list(INTENT_CODE_DEFAULTS)
    out: dict[str, object] = {}
    rows = conn.execute(
        "SELECT key, value_json FROM system_settings WHERE key IN (%s)"
        % ",".join("?" * len(keys)),
        tuple(keys),
    ).fetchall()
    for r in rows:
        try:
            out[r["key"]] = json.loads(r["value_json"])
        except (json.JSONDecodeError, TypeError):
            out[r["key"]] = r["value_json"]
    return out


def read_live_regime_sets(conn) -> dict[str, dict]:
    """레짐 라벨별 SET **정의**(regime_sets.settings)를 읽는다 — 구성된 전략(=다음 적용 시 스냅샷될 값).

    구현: 정의(regime_sets) 기준. 구 방식(regime_set_applications 최신 적용값)은 재보정 후 해당
    레짐이 아직 재적용 안 되면 forward-only 오탐(예: risk_on이 오늘 미발생 시 옛 스냅샷과 비교)이
    발생했다. SSOT '정의 vs 실측'의 실측 = 지금 구성된 SET 정의로 본다(2026-08-24).
    """
    rows = conn.execute(
        "SELECT id, settings FROM regime_sets WHERE is_active = 1"
    ).fetchall()
    out: dict[str, dict] = {}
    for r in rows:
        label = str(r["id"] or "").replace("SET-", "").replace("set-", "").lower()
        if not label:
            continue
        try:
            out[label] = json.loads(r["settings"])
        except (json.JSONDecodeError, TypeError):
            continue
    return out


def read_current_regime(conn) -> dict:
    """현재 활성(current_flag=1) 레짐 1건."""
    r = conn.execute(
        "SELECT trade_date, applied_at, regime_label, trigger, kospi_change_pct "
        "FROM regime_set_applications WHERE current_flag=1 ORDER BY applied_at DESC LIMIT 1"
    ).fetchone()
    return dict(r) if r else {}


def _num_eq(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) <= _FLOAT_TOL
    except (TypeError, ValueError):
        return a == b


def _eq(want, got) -> bool:
    if isinstance(want, (int, float)) and not isinstance(want, bool):
        return _num_eq(got, want)
    return got == want


def compute_drift(intent_settings, live_settings, intent_sets, live_sets,
                  intent_code_defaults=None) -> list[str]:
    """의도 ≠ 실측 불일치 목록(사람이 읽는 문장). 대조 로직의 단일 소스.

    - intent_settings: DB에 명시돼야 하고 그 값이어야 하는 레버(미설정=⚠, 값다름=🔴).
    - intent_code_defaults: 코드기본으로 도는 레버. DB 미설정=정상(코드기본과 일치),
      DB에 다른 값으로 오버라이드=🔴(의도이탈).
    """
    drift: list[str] = []
    for key, want in intent_settings.items():
        if key not in live_settings:
            drift.append(f"⚠ `{key}` 미설정 — 의도 `{want}` (DB 명시 권장)")
        elif not _eq(want, live_settings[key]):
            drift.append(f"🔴 `{key}` 불일치 — 의도 `{want}` vs 실측 `{live_settings[key]}`")
    for key, default in (intent_code_defaults or {}).items():
        if key in live_settings and not _eq(default, live_settings[key]):
            drift.append(
                f"🔴 `{key}` 코드기본 오버라이드 — 의도(코드기본) `{default}` vs DB `{live_settings[key]}`")
    for label, want in intent_sets.items():
        got = live_sets.get(label)
        if got is None:
            drift.append(f"⚠ 레짐 SET `{label}` 실측 없음 — 의도 존재")
            continue
        for field, wv in want.items():
            gv = got.get(field)
            if gv is None or not _num_eq(gv, wv):
                drift.append(f"🔴 SET `{label}.{field}` 불일치 — 의도 `{wv}` vs 실측 `{gv}`")
    return drift


def check_drift() -> list[str]:
    """라이브 실측을 의도와 대조한 드리프트 목록. 파일 미수정 — 워치독/CI용."""
    with _conn() as conn:
        live_settings = read_live_settings(conn)
        live_sets = read_live_regime_sets(conn)
    return compute_drift(INTENT_SETTINGS, live_settings, INTENT_REGIME_SETS, live_sets,
                         INTENT_CODE_DEFAULTS)


# ─────────────────────────────────────────────────────────────────────────
# Conformance — SSOT 주장 ↔ 구현(코드·설정)이 실제로 맞물리는지 검증.
# 드리프트(설정 '값')와 별개로, SSOT가 말하는 구현이 **존재하는지**를 본다.
# 개발할 때마다 여기 (주장, 구현심볼, 설정키)를 등록 → 구현↔SSOT 자동 맞물림.
# 심볼이 사라지거나 이름 바뀌면 여기서 잡혀 "SSOT부터 고치고 개발" 사이클을 강제.
# ─────────────────────────────────────────────────────────────────────────
CONFORMANCE: list[tuple[str, str | None, str | None]] = [
    # (SSOT 주장, 구현 코드 심볼(def/class/모듈), 대표 설정키)
    ("눌림목 게이트", "_vwap_pullback_gate", "engine.entry_vwap_pullback_mode"),
    ("예수금비중 사이징", "resolve_position_sizing", "sizing.per_position_rate_min"),
    ("확신도 모델", "resolve_conviction", "conviction.regime_weight"),
    ("사이징 shadow 배선", "_shadow_new_sizing", None),
    ("예수금비중 사이징 활성 토글", "_compute_new_model_sizing", "sizing.model_active"),
    ("max_positions 단일 출처", "resolve_max_positions", "sizing.positions_max"),
    ("레짐별 플레이북 조립", "build_playbook", None),
    ("레짐 판정(30분)", "_judge_regime", None),
    ("시장감지 5장세 판정", "classify_regime_5tier", "regime.surge_pct"),
    ("전환(방향) 감지", "detect_transition", "regime.down_transition_pp"),
    ("시장감지 shadow 배선", "_persist_and_shadow_sensing", "regime.transition_window_min"),
    ("하락전환 매수중단 대응", "get_current_transition", "regime.transition_response_active"),
    ("하락전환 트레일조임", "_update_trailing", "regime.transition_trail_tighten_factor"),
    ("폭등 사이징 확대 티어", "resolve_position_sizing", "sizing.surge_per_position_rate_max"),
    ("폭락 방어", "is_flash_crash_defense_active", "risk.flash_crash_threshold_pct"),
    ("churn 재진입 가드", "intraday_stoploss_count", "engine.intraday_max_stoploss_per_symbol"),
    ("EOD 강제청산", "run_eod_liquidation", "risk.force_exit_time"),
    ("전략설정 엔진(플레이북)", "strategy_playbook", None),
    ("레짐→플레이북 권위", "get_playbook", None),
    ("매수 엔진④", "resolve_buy_gates", None),
    ("매도 엔진⑤", "resolve_sell_params", None),
    ("매매 엔진⑥", "resolve_execution_sizing", None),
    ("종목선정 점수", "selection_score", "selection.change_weight"),
]


def _code_symbols() -> set[str]:
    """backend/services/engine의 def/class 이름 + 모듈명 집합(구현 심볼 존재 확인용)."""
    syms: set[str] = set()
    eng = ROOT / "backend" / "services" / "engine"
    for p in eng.glob("*.py"):
        syms.add(p.stem)
        try:
            for m in re.finditer(r"^\s*(?:async\s+)?(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)",
                                 p.read_text(encoding="utf-8"), re.M):
                syms.add(m.group(1))
        except OSError:
            continue
    return syms


def check_conformance() -> list[str]:
    """SSOT 주장의 구현 심볼·설정키가 실제 존재하는지 검증. 값이 아닌 '맞물림'."""
    issues: list[str] = []
    syms = _code_symbols()
    known = set(INTENT_SETTINGS) | set(INTENT_CODE_DEFAULTS)
    for claim, sym, key in CONFORMANCE:
        if sym and sym not in syms:
            issues.append(f"🔴 '{claim}' 구현 `{sym}` 미존재 — SSOT↔코드 불일치(개발 필요/이름변경)")
        if key and key not in known:
            issues.append(f"⚠ '{claim}' 설정 `{key}` INTENT 미등록 — 감시 누락")
    return issues


def _fmt_live_block(live_settings, live_sets, current, drift_count) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    L = [f"_자동 생성: {ts} · `scripts/strategy_spec_sync.py` · 손대지 마라._", ""]
    cur = current.get("regime_label", "?")
    at = str(current.get("applied_at", ""))[:19]
    trg = current.get("trigger", "")
    L += [f"**현재 활성 레짐:** `{cur}` (trigger={trg}, at={at})", "",
          "**전략 게이트/설정 (system_settings 실측 · 출처):**", "",
          "| 설정 | 실측값 | 출처 |", "|---|---|---|"]
    for key in INTENT_SETTINGS:
        if key in live_settings:
            L.append(f"| `{key}` | `{live_settings[key]}` | DB |")
        else:
            L.append(f"| `{key}` | `(미설정)` | ⚠ 미설정 |")
    for key, default in INTENT_CODE_DEFAULTS.items():
        if key in live_settings:
            L.append(f"| `{key}` | `{live_settings[key]}` | DB(오버라이드) |")
        else:
            L.append(f"| `{key}` | `{default}` | 코드기본 |")
    L += ["", "**레짐 SET별 매도 파라미터 (실측):**", "",
          "| 레짐 | max종목 | 손절 | 익절 | 트레일발동 | 트레일폭 |", "|---|---|---|---|---|---|"]
    for label in ("risk_on", "neutral", "risk_off", "volatile"):
        s = live_sets.get(label)
        if not s:
            continue
        L.append("| {} | {} | {} | {} | {} | {} |".format(
            label, s.get("max_positions", "-"), s.get("stop_loss_rate", "-"),
            s.get("take_profit_rate", "-"), s.get("trailing_activate_profit", "-"),
            s.get("trailing_stop_rate", "-")))
    L += ["", f"_드리프트 {drift_count}건 (아래 C절 참조)_"]
    return "\n".join(L)


def _fmt_drift_block(drift) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not drift:
        return (f"_자동 생성: {ts}_\n\n✅ **드리프트 없음** — 실측이 의도와 일치한다. "
                "시스템이 사양대로 동작 중.")
    body = "\n".join(f"- {d}" for d in drift)
    return (f"_자동 생성: {ts}_\n\n🔴 **드리프트 {len(drift)}건** — 실측이 의도를 벗어났다. "
            "각 항목을 의도대로 되돌리거나, 의도가 바뀐 것이면 A절+INTENT를 갱신하라.\n\n" + body)


def _replace_block(text: str, tag: str, new_body: str) -> str:
    pat = re.compile(rf"(<!-- AUTO:{tag} START -->)(.*?)(<!-- AUTO:{tag} END -->)", re.DOTALL)
    if not pat.search(text):
        raise ValueError(f"STRATEGY_SPEC.md에 AUTO:{tag} 마커가 없다.")
    return pat.sub(lambda m: f"{m.group(1)}\n{new_body}\n{m.group(3)}", text)


def _strip_timestamps(text: str) -> str:
    """멱등 비교용 — 타임스탬프 줄만 제거(실질 내용 변화만 감지)."""
    return re.sub(r"_자동 생성:[^\n]*", "", text)


def sync_strategy_spec(write: bool = True) -> dict:
    """실측·드리프트를 계산하고, 실질 변화가 있을 때만 STRATEGY_SPEC.md를 재작성한다.
    멱등 — 타임스탬프 외 변화가 없으면 파일을 건드리지 않는다(git 노이즈 방지).
    반환: {drift, changed, drift_items}.
    """
    with _conn() as conn:
        live_settings = read_live_settings(conn)
        live_sets = read_live_regime_sets(conn)
        current = read_current_regime(conn)
    drift = compute_drift(INTENT_SETTINGS, live_settings, INTENT_REGIME_SETS, live_sets,
                          INTENT_CODE_DEFAULTS)
    old = SPEC.read_text(encoding="utf-8")
    new = _replace_block(old, "LIVE", _fmt_live_block(live_settings, live_sets, current, len(drift)))
    new = _replace_block(new, "DRIFT", _fmt_drift_block(drift))
    changed = _strip_timestamps(old) != _strip_timestamps(new)
    if write and changed:
        SPEC.write_text(new, encoding="utf-8")
    return {"drift": len(drift), "changed": changed, "drift_items": drift}
