"""엔진 모니터 API — 6엔진 상태를 한 번에 (콘솔 Engine Monitor 화면용).

monitor_engines.py(CLI)의 웹 버전. 각 엔진의 상태·라이브 값 + SSOT 드리프트/
conformance를 JSON으로. 읽기 전용.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter

from ...services.db import get_connection

logger = logging.getLogger("EngineMonitorAPI")
router = APIRouter(prefix="/api/v1/engine-monitor", tags=["engine-monitor"])


def _get(conn, key, default=None):
    row = conn.execute("SELECT value_json FROM system_settings WHERE key=?", (key,)).fetchone()
    if row:
        try:
            return json.loads(row["value_json"])
        except Exception:
            return row["value_json"]
    try:
        from ...services.engine.strategy_spec import INTENT_CODE_DEFAULTS
        if key in INTENT_CODE_DEFAULTS:
            return INTENT_CODE_DEFAULTS[key]
    except Exception:
        pass
    return default


# 설정 키 → 사람이 읽는 라벨·설명·입력형(전략 엔진 설정 섹션 UX). kind: num|bool|enum
_SETTING_META = {
    # ① 전략설정(확신도)
    "conviction.regime_weight": ("레짐 가중치", "확신도 = 레짐점수×이 값 + 눌림점수×(1−값). 0=눌림만·1=레짐만", "num", "0~1"),
    "conviction.pullback_full_dist_pct": ("눌림 만점 거리", "VWAP 아래로 이 %만큼이면 눌림 점수 만점", "num", "%(음수)"),
    # ② 시장감지·전환
    "regime.down_pct": ("하락장 기준", "KOSPI 등락률이 이 값 이하면 하락장", "num", "%"),
    "regime.up_pct": ("상승장 기준", "KOSPI 등락률이 이 값 이상이면 상승장", "num", "%"),
    "regime.surge_pct": ("폭등장 기준", "KOSPI 등락률이 이 값 이상이면 폭등장", "num", "%"),
    "regime.vix_volatile": ("변동성장 VIX 기준", "VIX가 이 값 이상이면 변동성장", "num", "지수"),
    "regime.down_transition_pp": ("하락전환 기준", "감지창 내 KOSPI가 이만큼(%p) 꺾이면 하락전환", "num", "%p"),
    "regime.up_transition_pp": ("상승전환 기준", "감지창 내 KOSPI가 이만큼 오르면 상승전환", "num", "%p"),
    "regime.transition_window_min": ("전환 감지 창", "최근 몇 분의 KOSPI 기울기로 전환 판단", "num", "분"),
    "regime.transition_response_active": ("전환 대응 활성", "하락전환 시 신규매수 중단·트레일 조임 (감지 검증 후 ON)", "bool", None),
    "regime.transition_trail_tighten_factor": ("전환 트레일 조임 배수", "하락전환 시 트레일 스탑 폭 × 이 값 (1=변화없음)", "num", "배수"),
    # ③ 종목선정 (미배선)
    "selection.change_weight": ("등락률 가중치", "종목 점수의 등락률 비중  ⚠️미배선(매매 미반영)", "num", "0~1"),
    "selection.surge_weight": ("거래량 가중치", "종목 점수의 거래량 비중  ⚠️미배선(매매 미반영)", "num", "0~1"),
    # ④ 매수(게이트)
    "engine.entry_vwap_pullback_mode": ("VWAP 눌림 게이트", "고점추격 차단. enforce=차단·shadow=로그만·off=해제", "enum", ["enforce", "shadow", "off"]),
    "engine.entry_max_vwap_dist_pct": ("진입 최대 VWAP 이격", "VWAP보다 이 % 넘게 위면 추격으로 보고 차단", "num", "%"),
    "engine.max_price_change_pct": ("진입 최대 등락률", "당일 등락률 상한 (가드레일; RulePack 밴드와 교집합)", "num", "%"),
    "engine.min_price_change_pct": ("진입 최소 등락률", "당일 등락률 하한 (가드레일)", "num", "%"),
    "engine.min_volume_ratio": ("최소 거래량비", "전일 대비 거래량 배수 하한", "num", "배수"),
    "engine.confidence_gate_mode": ("확신도 게이트", "off=관찰만·regime_defensive=방어레짐만 강제·always=항상 강제", "enum", ["off", "regime_defensive", "always"]),
    "engine.min_ai_confidence": ("최소 확신도", "진입 confidence 하한", "num", "0~1"),
    "engine.intraday_max_stoploss_per_symbol": ("종목당 당일 손절 한도", "이 횟수 손절 시 당일 재진입 차단", "num", "회"),
    "engine.leverage_restriction_mode": ("레버리지 제한", "exclude=레버리지/인버스2x 진입 차단·off=허용", "enum", ["exclude", "off"]),
    # ⑤ 매도(수확)
    "engine.harvest_mode": ("수확 모드", "목표 도달 시 부분 확정(하루 수익 실현)", "bool", None),
    "engine.scaleout_ratio": ("1차 확정 비율", "목표 도달 시 이 비율만큼 매도 (0.6=60%)", "num", "비율 0~1"),
    "engine.scaleout_target_rate": ("1차 수확 목표", "이 수익률에서 부분 확정 (0.01=+1%)", "num", "비율(0.01=1%)"),
    "engine.scaleout_ratio_after_target": ("잔량 재확정 비율", "목표 후 잔량에서 추가 확정 비율", "num", "비율 0~1"),
    "engine.daily_target_rate": ("일일 목표 수익률", "계좌 대비 하루 목표(복리, 0.02=2%)", "num", "비율(0.02=2%)"),
    "engine.stop_source": ("손절/트레일 출처", "profile=종목 변동성별 프로필 · regime=시장국면 레짐SET 단일. Phase3 통합 스위치(기본 profile=현행)", "enum", ["profile", "regime"]),
    # ⑥ 매매(사이징)
    "sizing.model_active": ("사이징 모델 활성", "예수금 비중 기반 신모델 사용", "bool", None),
    "sizing.per_position_rate_min": ("종목당 최소 비중", "확신도 낮을 때 예수금 대비 종목당 하한 (0.05=5%)", "num", "비율(0.05=5%)"),
    "risk.max_position_rate_per_stock": ("종목당 최대 비중", "확신도 높을 때 예수금 대비 종목당 상한 (0.15=15%)", "num", "비율(0.15=15%)"),
    "sizing.positions_min": ("최소 종목 수", "동시 보유 종목 수 하한", "num", "개"),
    "sizing.positions_max": ("최대 종목 수", "동시 보유 종목 수 상한", "num", "개"),
    "exploration.deploy_target_rate": ("예수금 투입 목표비율", "총 예수금 중 배포 목표 (0.95=95%)", "num", "비율(0.95=95%)"),
    "sizing.surge_per_position_rate_max": ("폭등장 종목당 상한", "폭등 티어에서 종목당 비중 상한", "num", "비율 0~1"),
    # 리스크(공통 안전벨트)
    "risk.daily_loss_limit_percent": ("일일 손실 한도", "당일 손실이 이 %면 신규 진입 차단", "num", "%"),
    "risk.auto_halt_loss_percent": ("자동 긴급정지 손실", "이 손실률 도달 시 자동 긴급정지", "num", "%"),
    "risk.flash_crash_threshold_pct": ("급락 방어 기준", "KOSPI가 이 % 급락 시 방어모드 발동", "num", "%"),
}


def _engine_setting_groups():
    """설정 그룹을 6엔진과 일치 — 각 엔진 모듈의 SETTING_KEYS를 단일 출처로."""
    from ...services.engine.buy_engine import GATE_SETTING_KEYS
    from ...services.engine.execution_engine import EXEC_SETTING_KEYS
    from ...services.engine.sell_engine import SELL_SETTING_KEYS
    return [
        ("① 전략설정(확신도)", ["conviction.regime_weight", "conviction.pullback_full_dist_pct"]),
        ("② 시장감지·전환", ["regime.down_pct", "regime.up_pct", "regime.surge_pct", "regime.vix_volatile",
                        "regime.down_transition_pp", "regime.up_transition_pp",
                        "regime.transition_window_min", "regime.transition_response_active",
                        "regime.transition_trail_tighten_factor"]),
        ("③ 종목선정 (미배선·참고용)", ["selection.change_weight", "selection.surge_weight"]),
        ("④ 매수(게이트)", GATE_SETTING_KEYS),
        ("⑤ 매도(수확)", SELL_SETTING_KEYS),
        ("⑥ 매매(사이징)", EXEC_SETTING_KEYS),
        # 포트폴리오 손실 안전벨트 단일화(2026-08-22) — 흩어진 손절/손실 설정을 전략엔진 한 곳으로.
        ("리스크(공통 안전벨트)", ["risk.daily_loss_limit_percent",
                          "risk.auto_halt_loss_percent",
                          "risk.flash_crash_threshold_pct"]),
    ]


@router.get("/settings")
async def engine_settings() -> dict:
    """전략 엔진 설정(SSOT 추적) — Settings 화면 '전략 엔진 설정' 섹션용. 값+의도+그룹."""
    from ...services.engine.strategy_spec import INTENT_CODE_DEFAULTS, INTENT_SETTINGS
    intent = {**INTENT_CODE_DEFAULTS, **INTENT_SETTINGS}
    with get_connection() as conn:
        groups = []
        for title, keys in _engine_setting_groups():
            items = []
            for k in keys:
                cur = _get(conn, k, None)
                meta = _SETTING_META.get(k)
                label, desc, kind, opts = (meta if meta else (k, "", "num", None))
                items.append({
                    "key": k, "value": cur, "intent": intent.get(k),
                    "label": label, "desc": desc, "kind": kind, "options": opts,
                    "in_db": conn.execute("SELECT 1 FROM system_settings WHERE key=?", (k,)).fetchone() is not None,
                })
            groups.append({"title": title, "items": items})
    return {"ok": True, "payload": {"groups": groups}}


@router.get("/status")
async def engine_status() -> dict:
    """6엔진 상태 + SSOT 정합 스냅샷."""
    try:
        from ...services.engine.strategy_spec import check_conformance, check_drift
        drift, conf = check_drift(), check_conformance()
    except Exception as exc:
        drift, conf = [f"체크 실패: {exc}"], []

    with get_connection() as conn:
        # Alert Center 요약(미확인 경고 — PM이 Alert 화면 안 봐도 여기서 감지)
        try:
            arow = conn.execute(
                "SELECT COUNT(*) n, SUM(CASE WHEN severity='CRITICAL' THEN 1 ELSE 0 END) crit "
                "FROM system_alerts WHERE acknowledged=0"
            ).fetchone()
            alerts = {"unacked": arow["n"] or 0, "critical": arow["crit"] or 0}
        except Exception:
            alerts = {"unacked": 0, "critical": 0}
        # 엔진② KOSPI 시계열(최근 거래일)
        series = conn.execute(
            "SELECT substr(captured_at,12,5) t, change_rate v FROM market_snapshots "
            "WHERE symbol='KOSPI' AND substr(captured_at,1,10)="
            "(SELECT MAX(substr(captured_at,1,10)) FROM market_snapshots WHERE symbol='KOSPI') "
            "ORDER BY captured_at"
        ).fetchall()
        # 엔진④매수·⑤매도 — 현재 레짐으로 라이브 파라미터 해석(실매 소비 경로와 동일 권위)
        _r5 = str(_get(conn, "regime.current_5tier", "flat") or "flat")
        try:
            from ...services.engine.buy_engine import resolve_buy_gates
            from ...services.engine.sell_engine import resolve_sell_params
            _g, _s = resolve_buy_gates(_r5), resolve_sell_params(_r5)
        except Exception:
            _g, _s = {}, {}
        _e4 = {
            "regime": _r5,
            "vwap_mode": _g.get("vwap_pullback_mode"),
            "max_vwap_dist": _g.get("entry_max_vwap_dist_pct"),
            "band_min": _g.get("min_price_change_pct"),
            "band_max": _g.get("max_price_change_pct"),
            "min_vol": _g.get("min_volume_ratio"),
            "leverage": _g.get("leverage_restriction"),
            "wired": True,  # decision_engine VWAP게이트 + _entry_gate_block 경유
        }
        _e5 = {
            "harvest": _s.get("harvest_mode"),
            "scaleout_target": _s.get("scaleout_target_rate"),
            "scaleout_ratio": _s.get("scaleout_ratio"),
            "stop_loss": _s.get("stop_loss_rate"),
            "trail": _s.get("trailing_stop_rate"),
            "wired": True,  # position_manager 스케일아웃 + 트레일 경유
        }
        payload = {
            "ssot": {"drift": len(drift), "conformance": len(conf),
                     "ok": not drift and not conf,
                     "items": (drift + conf)[:8]},
            "alerts": alerts,
            "engine1_sizing": {
                "active": _get(conn, "sizing.model_active", False),
                "per_rate_min": _get(conn, "sizing.per_position_rate_min", 0.05),
                "per_rate_max": _get(conn, "risk.max_position_rate_per_stock", 0.15),
                "positions_min": _get(conn, "sizing.positions_min", 6),
                "positions_max": _get(conn, "sizing.positions_max", 19),
                "surge_rate_max": _get(conn, "sizing.surge_per_position_rate_max", 0.15),
            },
            "engine2_regime": {
                "current_5tier": _get(conn, "regime.current_5tier", "-"),
                "current_transition": _get(conn, "regime.current_transition", "-"),
                "response_active": _get(conn, "regime.transition_response_active", False),
                "trail_tighten_factor": _get(conn, "regime.transition_trail_tighten_factor", 1.0),
                "thresholds": {
                    "down": _get(conn, "regime.down_pct", -1.5),
                    "up": _get(conn, "regime.up_pct", 0.5),
                    "surge": _get(conn, "regime.surge_pct", 2.5),
                    "down_transition_pp": _get(conn, "regime.down_transition_pp", -1.0),
                    "up_transition_pp": _get(conn, "regime.up_transition_pp", 1.0),
                },
                "kospi_series": [{"t": r["t"], "v": r["v"]} for r in series],
            },
            "engine3_selection": {
                "change_weight": _get(conn, "selection.change_weight", 0.5),
                "surge_weight": _get(conn, "selection.surge_weight", 0.5),
                "wired": False,
            },
            "engine4_buy": _e4,
            "engine5_sell": _e5,
            "engine6_execution": {
                "model_active": _get(conn, "sizing.model_active", False),
                "conviction": "레짐×눌림 결합",
                "wired": True,  # order_executor._compute_new_model_sizing 경유
            },
            "engines_todo": ["엔진③ 종목선정 배선(감지검증 후)", "decision_engine 분해(점진적)"],
        }
    return {"ok": True, "payload": payload}
