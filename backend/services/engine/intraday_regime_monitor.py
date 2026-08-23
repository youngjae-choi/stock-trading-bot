"""Intraday regime SET monitoring and transition execution."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection
from ..regime_set_service import (
    auto_create_set,
    get_match_preview,
    get_today_application,
    get_today_transitions,
    record_application,
)

logger = logging.getLogger("IntradayRegimeMonitor")
KST = ZoneInfo("Asia/Seoul")
MIN_TRANSITION_INTERVAL_MINUTES = 25


def _today() -> str:
    """Return today's KST trading date as YYYY-MM-DD."""
    return datetime.now(KST).strftime("%Y-%m-%d")


def _to_float(value: Any) -> float | None:
    """Convert a value to float when possible, otherwise return None."""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _json_loads(value: str | None) -> dict[str, Any]:
    """Parse a JSON object text column defensively."""
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _get_morning_vix(trade_date: str) -> float | None:
    """Return the VIX value stored by the morning briefing for a trade date."""
    logger.info("START: IntradayRegimeMonitor._get_morning_vix trade_date=%s", trade_date)
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT market_data FROM morning_context WHERE trade_date = ?",
                (trade_date,),
            ).fetchone()
        if row is None:
            logger.info("SKIP: IntradayRegimeMonitor morning_context missing trade_date=%s", trade_date)
            return None
        market_data = _json_loads(dict(row).get("market_data"))
        vix_data = market_data.get("vix") if isinstance(market_data.get("vix"), dict) else {}
        vix = _to_float(vix_data.get("price") or vix_data.get("value") or market_data.get("vix_value"))
        logger.info("SUCCESS: IntradayRegimeMonitor._get_morning_vix vix=%s", vix)
        return vix
    except Exception as exc:
        logger.warning("WARN: IntradayRegimeMonitor morning VIX lookup failed error=%s", exc)
        return None


def _extract_kospi_change_from_payload(payload: dict[str, Any]) -> float | None:
    """Extract KOSPI change percentage from known snapshot JSON shapes."""
    for key in ("kospi", "KOSPI", "^KS11", "KS11"):
        value = payload.get(key)
        if isinstance(value, dict):
            change = _to_float(
                value.get("change_pct")
                or value.get("change_rate")
                or value.get("chg_rate")
                or value.get("prdy_ctrt")
            )
            if change is not None:
                return change
    return _to_float(
        payload.get("kospi_change_pct")
        or payload.get("kospi_change")
        or payload.get("change_pct")
        or payload.get("change_rate")
        or payload.get("chg_rate")
        or payload.get("prdy_ctrt")
    )


def _get_current_kospi_change() -> float | None:
    """Return the latest KOSPI change percentage from market_snapshots."""
    logger.info("START: IntradayRegimeMonitor._get_current_kospi_change")
    try:
        with get_connection() as conn:
            targeted = conn.execute(
                """
                SELECT symbol, change_rate, raw_json
                FROM market_snapshots
                WHERE UPPER(symbol) IN ('KOSPI', 'KS11', '^KS11')
                ORDER BY captured_at DESC
                LIMIT 1
                """
            ).fetchone()
            row = targeted or conn.execute(
                """
                SELECT symbol, change_rate, raw_json
                FROM market_snapshots
                ORDER BY captured_at DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            logger.info("SKIP: IntradayRegimeMonitor market_snapshots empty")
            return None

        item = dict(row)
        payload_change = _extract_kospi_change_from_payload(_json_loads(item.get("raw_json")))
        change = payload_change if payload_change is not None else _to_float(item.get("change_rate"))
        logger.info(
            "SUCCESS: IntradayRegimeMonitor._get_current_kospi_change symbol=%s change=%s",
            item.get("symbol"),
            change,
        )
        return change
    except Exception as exc:
        logger.warning("WARN: IntradayRegimeMonitor KOSPI change lookup failed error=%s", exc)
        return None


def _intraday_kis_kospi_enabled() -> bool:
    """실시간 KOSPI를 KIS 지수조회로 가져올지(기본 True). 롤백: false."""
    try:
        from ..settings_store import get_setting

        return bool(get_setting("regime.intraday_kis_kospi_enabled", True))
    except Exception:
        return True


def _intraday_live_driver_enabled() -> bool:
    """장중 레짐 driver로 실시간 KIS KOSPI+VIX(_judge_regime)를 쓸지(기본 True).

    index-board regime(morning_context)은 장전 스냅샷이라 장중 갱신이 없어(intraday_json 공백)
    동결된다 → 장중 전환 판단엔 실시간 데이터를 쓴다. 장전 권위(morning SET 적용)는 유지.
    롤백(=index-board 장전값을 장중에도 유지): false.
    """
    try:
        from ..settings_store import get_setting

        return bool(get_setting("regime.intraday_live_driver_enabled", True))
    except Exception:
        return True


async def _fetch_kospi_change() -> float | None:
    """실시간 KOSPI 등락률 — KIS 지수조회(0001) 우선, 실패 시 market_snapshots 폴백.

    설계(check_intraday_regime L336): 실시간 KOSPI는 KIS 전담. market_snapshots는 채워지지
    않으므로(0행) KIS 직접조회가 실질 소스다.
    """
    if _intraday_kis_kospi_enabled():
        try:
            from ..kis.domestic.universe_service import get_market_index

            idx = await get_market_index("0001")
            change = _to_float(idx.get("change_rate"))
            if change is not None:
                logger.info("SUCCESS: IntradayRegimeMonitor KIS KOSPI 실시간 change=%.2f%%", change)
                return change
            logger.warning("WARN: IntradayRegimeMonitor KIS KOSPI change 파싱 실패 — 폴백")
        except Exception as exc:
            logger.warning("WARN: IntradayRegimeMonitor KIS KOSPI 조회 실패 — 폴백 error=%s", exc)
    return _get_current_kospi_change()


def _get_index_board_regime(trade_date: str) -> str | None:
    """오늘 최신 market_tone(index-board 단독출처)이 산출한 regime. 없으면 None.

    시황 단일출처(PM 확정): regime 권위는 market_tone(index-board)이고 SET 모니터는
    그 regime을 받아 SET 매핑만 한다. 자체 _judge_regime은 index-board 미가용 시 폴백.
    morning_context.regime은 장중 2분 폴링의 market_tone 재평가마다 갱신된다.
    """
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT regime FROM morning_context WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
                (trade_date,),
            ).fetchone()
        if row is None:
            return None
        regime = str(dict(row).get("regime") or "").strip()
        return regime or None
    except Exception as exc:
        logger.warning("WARN: IntradayRegimeMonitor index-board regime lookup failed error=%s", exc)
        return None


def _get_index_board_vix(trade_date: str) -> float | None:
    """오늘 최신 market_tone_results.parsed_numbers의 VIX(index-board 파싱). 없으면 None.

    parsed_numbers 컬럼은 배포(ALTER) 후 존재 — 미존재/빈값이면 None 반환해 morning VIX로 폴백.
    """
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT parsed_numbers FROM market_tone_results WHERE trade_date = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (trade_date,),
            ).fetchone()
        if row is None:
            return None
        nums = _json_loads(dict(row).get("parsed_numbers"))
        return _to_float(nums.get("vix"))
    except Exception as exc:
        logger.warning("WARN: IntradayRegimeMonitor index-board VIX lookup failed error=%s", exc)
        return None


def _judge_regime(vix: float | None, kospi_change: float | None) -> str:
    """Judge the intraday regime from fixed morning VIX and current KOSPI change."""
    vix_value = vix if vix is not None else 20.0
    kospi_value = kospi_change if kospi_change is not None else 0.0
    if vix_value > 28:
        return "volatile"
    if vix_value > 22 and kospi_value < -1.0:
        return "risk_off"
    if kospi_value < -1.5:
        return "risk_off"
    if kospi_value > 0.5 and vix_value < 22:
        return "risk_on"
    return "neutral"


def _latch_from_transition(transition: str | None) -> bool | None:
    """상승전환 재개 래치의 새 상태 — 순수함수.

    down_transition→True(매수중단 래치 ON), up_transition→False(재개=래치 OFF),
    None→None(불확실 = 이전 래치 유지, 미변경). 데드캣 바운스 재진입 방지(8/18).
    """
    if transition == "down_transition":
        return True
    if transition == "up_transition":
        return False
    return None


def _resolve_set_regime(kospi_change: float | None, vix: float | None,
                        ib_regime: str | None) -> tuple[str, str]:
    """SET 매칭용 regime + 출처 결정 — `regime.set_source` 스위치(§A-7#5).

    - **5tier(기본, 활성 2026-08-23)**: 설정기반 `classify_regime_5tier`(regime.down_pct 등)
      →`regime_to_set`. 드리프트 감시됨. 롤백=judge.
    - judge: 하드코딩 `_judge_regime`. 장중 live driver면 judge_live, 아니면 index-board 우선 폴백.
    반환 (new_regime, regime_source).
    """
    from ..settings_store import get_setting
    src = str(get_setting("regime.set_source", "5tier") or "5tier").lower()
    if src == "5tier":
        from .market_sensing import classify_regime_5tier, regime_to_set
        r5 = classify_regime_5tier(kospi_change, vix)
        return regime_to_set(r5), "5tier:%s" % r5
    if _intraday_live_driver_enabled():
        # 장중 driver = 실시간 KIS KOSPI+VIX. index-board regime은 장전 전용(장중 동결).
        return _judge_regime(vix, kospi_change), "judge_live"
    return (ib_regime or _judge_regime(vix, kospi_change),
            "index-board" if ib_regime else "judge_fallback")


def _persist_and_shadow_sensing(kospi_change: float | None, vix: float | None,
                                current_regime: str) -> None:
    """[SHADOW] 장중 KOSPI 시계열 저장 + market_sensing(5장세·전환) would-be 로그.

    라이브 레짐 판정(_judge_regime)은 안 바꾼다 — 비교 로그만(엔진② inc2 검증).
    KOSPI 시계열이 지금까지 미저장이라 여기서 저장부터 시작한다. 예외는 전부 삼킨다.
    """
    if kospi_change is None:
        return
    try:
        import uuid as _uuid
        from datetime import timedelta

        from ..settings_store import get_setting
        from .market_sensing import classify_regime_5tier, detect_transition
        now = datetime.now(ZoneInfo("Asia/Seoul"))
        win = int(get_setting("regime.transition_window_min", 60) or 60)
        cutoff = (now - timedelta(minutes=win)).isoformat()
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO market_snapshots (id,symbol,price,volume,change_rate,source,captured_at,raw_json) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (str(_uuid.uuid4()), "KOSPI", 0.0, 0.0, float(kospi_change),
                 "regime_monitor", now.isoformat(), "{}"),
            )
            conn.commit()
            rows = conn.execute(
                "SELECT change_rate FROM market_snapshots WHERE symbol='KOSPI' "
                "AND captured_at >= ? ORDER BY captured_at",
                (cutoff,),
            ).fetchall()
        series = [float(r["change_rate"]) for r in rows if r["change_rate"] is not None]
        regime5 = classify_regime_5tier(kospi_change, vix)
        transition = detect_transition(series)
        # 전환/5장세 상태 영속화(날짜스코프 상태값 — 대응 게이트가 읽음). INTENT 제외.
        from ..settings_store import upsert_setting
        upsert_setting("regime.current_transition", transition or "none", "string",
                       "장중 전환 상태(엔진② — down/up_transition, 상태값)", "regime_monitor")
        upsert_setting("regime.current_transition_at", now.isoformat(), "string",
                       "전환 상태 갱신 시각", "regime_monitor")
        # 상승전환 재개 래치(엔진② inc4, 2026-08-23): 하락전환 시 매수중단을 **걸어두고**,
        # up_transition(반등 확인)에서만 해제. None(불확실)은 유지 = 데드캣 바운스 재진입 방지(8/18).
        _latch = _latch_from_transition(transition)
        if _latch is not None:
            upsert_setting("regime.entry_suspended", "true" if _latch else "false", "boolean",
                           "하락전환 매수중단 래치(상승전환까지 유지)" if _latch else "상승전환 — 매수 재개(래치 해제)",
                           "regime_monitor")
            upsert_setting("regime.entry_suspended_at", now.isoformat(), "string",
                           "매수중단 래치 갱신 시각", "regime_monitor")
        # _latch None(transition None): 래치 유지(변경 안 함).
        upsert_setting("regime.current_5tier", regime5, "string",
                       "장중 5장세 판정(엔진② shadow)", "regime_monitor")
        logger.info(
            "[E2] SHADOW-REGIME 입력 kospi=%.2f vix=%s → 출력 5장세=%s 전환=%s "
            "(현재_judge=%s, window%dpt)",
            kospi_change, vix, regime5, transition or "-", current_regime, len(series),
        )
        # [E1] 전략설정 엔진: 이 레짐의 플레이북(전략 한 벌)을 꺼내 로그(shadow, 동작불변).
        try:
            from .strategy_playbook import get_playbook
            pb = get_playbook(regime5)
            logger.info(
                "[E1] SHADOW-PLAYBOOK regime=%s→SET=%s | 사이징 %.0f~%.0f%% 종목%d~%d · "
                "선정 등락%.1f/거래%.1f · 폭등티어=%s",
                regime5, pb.set_label, pb.sizing["per_position_rate_min"] * 100,
                pb.sizing["per_position_rate_max"] * 100, pb.sizing["positions_min"],
                pb.sizing["positions_max"], pb.selection["change_weight"],
                pb.selection["surge_weight"], pb.sizing["surge_tier"],
            )
        except Exception:
            pass
    except Exception as exc:
        logger.debug("shadow sensing skip: %s", exc)


def get_current_transition() -> str | None:
    """현재 하락/상승 전환 상태(신선할 때만). 엔진② 대응 게이트용. 실패·미상=None.

    레짐 틱이 오래 끊겼으면(window+15분 초과) 신선하지 않다고 보고 None(오작동 방지).
    """
    try:
        from datetime import timedelta

        from ..settings_store import get_setting
        trans = get_setting("regime.current_transition", "none")
        if not trans or str(trans) == "none":
            return None
        at_str = get_setting("regime.current_transition_at", "")
        if at_str:
            at = datetime.fromisoformat(str(at_str))
            if at.tzinfo is None:
                at = at.replace(tzinfo=ZoneInfo("Asia/Seoul"))
            win = int(get_setting("regime.transition_window_min", 60) or 60)
            if datetime.now(ZoneInfo("Asia/Seoul")) - at > timedelta(minutes=win + 15):
                return None
        return str(trans)
    except Exception:
        return None


def get_entry_suspended() -> bool:
    """상승전환 재개 래치 — 하락전환 후 매수중단 상태(신선할 때만). up_transition에서 해제.

    stateless한 `current_transition==down_transition`과 달리 **래치**다: 하락전환이 걸면
    None(불확실) 구간에도 유지되고 **up_transition에서만 풀린다**(반등 확인 후 재개, 8/18 교훈).
    래치 갱신이 window+15분 초과로 끊겼으면 False(stale — 종일·익일 차단 방지, 장초 자동해제).
    """
    try:
        from datetime import timedelta

        from ..settings_store import get_setting
        susp = get_setting("regime.entry_suspended", False)
        if isinstance(susp, str):
            susp = susp.strip().lower() in ("true", "1", "yes")
        if not susp:
            return False
        at_str = get_setting("regime.entry_suspended_at", "")
        if at_str:
            at = datetime.fromisoformat(str(at_str))
            if at.tzinfo is None:
                at = at.replace(tzinfo=ZoneInfo("Asia/Seoul"))
            win = int(get_setting("regime.transition_window_min", 60) or 60)
            if datetime.now(ZoneInfo("Asia/Seoul")) - at > timedelta(minutes=win + 15):
                return False
        return True
    except Exception:
        return False


def _should_skip_transition(trade_date: str) -> bool:
    """Return true when the most recent transition is inside the debounce window."""
    transitions = get_today_transitions(trade_date)
    if not transitions:
        return False
    last_at_str = str(transitions[-1].get("applied_at") or transitions[-1].get("created_at") or "")
    if not last_at_str:
        return False
    try:
        last_at = datetime.fromisoformat(last_at_str)
        if last_at.tzinfo is None:
            last_at = last_at.replace(tzinfo=KST)
        elapsed = (datetime.now(KST) - last_at.astimezone(KST)).total_seconds() / 60
        return elapsed < MIN_TRANSITION_INTERVAL_MINUTES
    except Exception as exc:
        logger.warning("WARN: IntradayRegimeMonitor transition interval parse failed error=%s", exc)
        return False


def _insert_transition_alert(
    trade_date: str,
    old_set_name: str,
    new_set_name: str,
    old_regime: str,
    new_regime: str,
    vix: float | None,
    kospi_change: float | None,
) -> None:
    """Insert a system alert for the operator-facing Today Control feed."""
    now = datetime.now(KST)
    detail = {
        "old_regime": old_regime,
        "new_regime": new_regime,
        "old_set_name": old_set_name,
        "new_set_name": new_set_name,
        "vix": vix,
        "kospi_change_pct": kospi_change,
    }
    title = f"[장중 레짐 전환] {now.strftime('%H:%M')} {old_regime} → {new_regime}"
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO system_alerts
                    (id, trade_date, alert_type, severity, title, detail, acknowledged, created_at)
                VALUES (?, ?, 'regime_transition', 'WARNING', ?, ?, 0, ?)
                """,
                (str(uuid.uuid4()), trade_date, title, json.dumps(detail, ensure_ascii=False), now.isoformat()),
            )
        logger.info("SUCCESS: IntradayRegimeMonitor transition alert inserted title=%s", title)
    except Exception as exc:
        logger.warning("WARN: IntradayRegimeMonitor transition alert insert failed error=%s", exc)


def is_flash_crash_defense_active(trade_date: str | None = None) -> bool:
    """오늘 급락(flash crash) 방어 모드가 활성인지 — 날짜 스코프(다음 거래일 자동 해제).

    방어 모드에서는 신규 진입이 차단되고(인버스 1x 플레이북 예외) 조회 실패 시
    False(차단 안 함) — 손절/청산 안전장치는 별도 경로.
    """
    try:
        from ..settings_store import get_setting

        if not bool(get_setting("risk.flash_crash_defense_active", False)):
            return False
        flagged_date = str(get_setting("risk.flash_crash_defense_date", "") or "")
        return flagged_date == (trade_date or _today())
    except Exception:
        return False


def _activate_flash_crash_defense(trade_date: str, kospi_change: float | None, vix: float | None) -> None:
    """급락 방어 모드 활성화 — 설정 플래그 + Alert (이미 활성이면 no-op)."""
    if is_flash_crash_defense_active(trade_date):
        return
    try:
        from ..settings_store import upsert_setting

        upsert_setting(
            "risk.flash_crash_defense_active", True, "boolean",
            "급락 방어 모드 활성 플래그 (flash crash 감지 시 자동 ON, 날짜 스코프)", "system",
        )
        upsert_setting(
            "risk.flash_crash_defense_date", trade_date, "string",
            "급락 방어 모드 활성 날짜 (당일만 유효)", "system",
        )
        logger.warning(
            "EVENT: [FlashCrash] 방어 모드 활성화 trade_date=%s kospi=%.2f%% vix=%s",
            trade_date, kospi_change if kospi_change is not None else 0.0, vix,
        )
        try:
            from .alert_center import create_alert

            kospi_str = f"{kospi_change:+.2f}%" if kospi_change is not None else "N/A"
            create_alert(
                "risk_guard",
                f"🚨 급락 방어 모드 발동 — KOSPI {kospi_str}",
                severity="CRITICAL",
                detail=(
                    f"KOSPI {kospi_str} / VIX {vix if vix is not None else 'N/A'} — "
                    "신규 진입 차단(인버스 1x 플레이북 예외), 보유 포지션은 손절/트레일링 유지"
                ),
                trade_date=trade_date,
            )
        except Exception as alert_exc:
            logger.warning("WARN: [FlashCrash] alert 생성 실패 — %s", alert_exc)
    except Exception as exc:
        logger.error("FAIL: [FlashCrash] 방어 모드 활성화 실패 — %s", exc)


def _flash_crash_detected(kospi_change: float | None, vix: float | None) -> bool:
    """KOSPI 급락 또는 VIX 급등으로 flash crash 판정 (risk.flash_crash_* 설정)."""
    try:
        from ..settings_store import get_setting

        if not bool(get_setting("risk.flash_crash_defense_enabled", True)):
            return False
        threshold = float(get_setting("risk.flash_crash_threshold_pct", -2.0) or -2.0)
    except Exception:
        return False
    if kospi_change is not None and kospi_change <= threshold:
        return True
    if vix is not None and vix > 35:
        return True
    return False


async def check_intraday_regime(slot: str = "") -> dict[str, Any]:
    """Check current market conditions and switch the active regime SET when needed.

    Args:
        slot: Scheduler slot label such as 09:30. Empty means manual invocation.
    """
    trade_date = _today()
    now_str = datetime.now(KST).strftime("%H:%M")
    logger.info("START: IntradayRegimeMonitor.check slot=%s trade_date=%s", slot or now_str, trade_date)

    current_app = get_today_application(trade_date)
    if not current_app:
        logger.info("SKIP: IntradayRegimeMonitor no active morning SET trade_date=%s", trade_date)
        return {"ok": True, "action": "skipped", "reason": "no_morning_set"}

    # 시황 단일출처(PM 확정): VIX는 index-board 파싱값 우선(미가용 시 morning VIX 폴백),
    # 실시간 KOSPI 등락은 KIS 거래데이터 유지(PM#2: 실시간가격은 KIS 전담).
    ib_vix = _get_index_board_vix(trade_date)
    vix = ib_vix if ib_vix is not None else _get_morning_vix(trade_date)
    kospi_change = await _fetch_kospi_change()

    # P3-3: flash crash 감지 — 방어 모드 활성화 + 디바운스 우회(즉시 레짐 전환 허용).
    # 폭락은 25분 디바운스를 기다릴 수 없다.
    flash_crash = _flash_crash_detected(kospi_change, vix)
    if flash_crash:
        _activate_flash_crash_defense(trade_date, kospi_change, vix)

    if not flash_crash and _should_skip_transition(trade_date):
        logger.info("SKIP: IntradayRegimeMonitor min transition interval trade_date=%s", trade_date)
        return {"ok": True, "action": "skipped", "reason": "min_interval"}

    if kospi_change is None:
        logger.info("SKIP: IntradayRegimeMonitor KOSPI change missing trade_date=%s", trade_date)
        return {"ok": True, "action": "skipped", "reason": "no_kospi_data"}

    current_set_id = current_app.get("set_id")
    current_regime = current_app.get("regime_label") or "neutral"
    # regime 권위는 market_tone(index-board); 미가용 시에만 자체 판정 폴백.
    ib_regime = _get_index_board_regime(trade_date)
    # SET 매칭 regime = `regime.set_source` 스위치(§A-7#5, 기본 5tier=설정기반 활성 2026-08-23).
    new_regime, regime_source = _resolve_set_regime(kospi_change, vix, ib_regime)
    logger.info(
        "[E2] REGIME 입력 vix=%s kospi=%s → 출력 regime=%s (source=%s)",
        vix, kospi_change, new_regime, regime_source,
    )
    # [SHADOW] 엔진② 시장감지: KOSPI 시계열 저장 + would-be 5장세/전환 로그(라이브 불변).
    _persist_and_shadow_sensing(kospi_change, vix, new_regime)
    new_match = get_match_preview(new_regime, vix, kospi_change, trade_date)
    if not new_match.get("set_id"):
        logger.warning("WARN: IntradayRegimeMonitor preview has no SET; creating auto SET regime=%s", new_regime)
        new_match = auto_create_set(new_regime, vix, kospi_change)
    new_set_id = new_match.get("set_id")

    if new_set_id == current_set_id:
        logger.info(
            "NO_CHANGE: IntradayRegimeMonitor set_id=%s regime=%s",
            current_set_id,
            current_regime,
        )
        return {"ok": True, "action": "no_change", "set_id": current_set_id, "regime": current_regime}

    logger.info(
        "SWITCH: IntradayRegimeMonitor %s -> %s (%s -> %s)",
        current_set_id,
        new_set_id,
        current_regime,
        new_regime,
    )
    record_application(
        trade_date=trade_date,
        matched_set=new_match,
        regime_label=new_regime,
        vix=vix,
        kospi_change_pct=kospi_change,
        trigger="intraday",
    )
    _insert_transition_alert(
        trade_date=trade_date,
        old_set_name=current_app.get("set_name") or str(current_set_id or ""),
        new_set_name=new_match.get("set_name") or str(new_set_id or ""),
        old_regime=current_regime,
        new_regime=new_regime,
        vix=vix,
        kospi_change=kospi_change,
    )

    logger.info("SUCCESS: IntradayRegimeMonitor switched to set_id=%s", new_set_id)
    return {
        "ok": True,
        "action": "switched",
        "from_set": current_set_id,
        "to_set": new_set_id,
        "from_regime": current_regime,
        "to_regime": new_regime,
        "vix": vix,
        "kospi_change": kospi_change,
    }
