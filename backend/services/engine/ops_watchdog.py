"""운영 감시봇(Ops Watchdog) — 규칙기반 5분 틱.

스케줄·매매 단계가 "됐나·잘했나"를 출력 테이블/audit로 감시하고, 이상이면 규칙·DB
조회로 컨텍스트를 모아 Alert Center(system_alerts)에 기록한다. **LLM 안 씀, 코드 자동수정 안 함.**
PM이 Alert Center에서 보고 수정 판단. 같은 이상은 하루 1회만(미확인 알림 dedup).

설계서: docs/superpowers/specs/2026-06-07-ops-watchdog-design.md
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable, NamedTuple
from zoneinfo import ZoneInfo

from ..db import get_connection
from ..settings_store import get_setting, upsert_setting
from .alert_center import create_alert
from .order_preflight import _observed_daily_loss_percent
from .trading_calendar import is_trading_day

logger = logging.getLogger("OpsWatchdog")
KST = ZoneInfo("Asia/Seoul")

# 적용 시각(분). 거래일에 이 시각이 지나면 해당 단계가 됐어야 함.
_M0835 = 8 * 60 + 35
_M0905 = 9 * 60 + 5
_M0906 = 9 * 60 + 6
_M0910 = 9 * 60 + 10
_M1520 = 15 * 60 + 20
_M1530 = 15 * 60 + 30
_M1525 = 15 * 60 + 25


def _now_kst() -> datetime:
    return datetime.now(KST)


def _count(conn, sql: str, params: tuple = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0] or 0) if row and row[0] is not None else 0


def _audit_fail_suffix(conn, trade_date: str, steps: list[str]) -> str:
    """해당 단계의 실패 audit 메시지를 best-effort로 덧붙인다(없으면 빈 문자열)."""
    try:
        ph = ",".join("?" * len(steps))
        rows = conn.execute(
            f"SELECT step, status, message FROM pipeline_run_audit"
            f" WHERE trade_date = ? AND step IN ({ph}) ORDER BY started_at DESC",
            (trade_date, *steps),
        ).fetchall()
        for r in rows:
            if str(r["status"]) == "failed":
                return f" · audit[{r['step']}]: {r['message']}"
    except Exception:
        return ""
    return ""


# ── 개별 체크: (title, detail) 반환 시 이상, None이면 정상 ───────────────────

def _chk_s2_premarket(conn, td):
    if _count(conn, "SELECT COUNT(*) FROM market_tone_results WHERE trade_date=?", (td,)) > 0:
        return None
    return ("프리마켓 S2 시장톤 미실행",
            "08:30 프리마켓 시장톤(market_tone_results)이 오늘 기록되지 않음."
            + _audit_fail_suffix(conn, td, ["S2"]))


def _chk_trade_prep(conn, td):
    active = _count(
        conn,
        "SELECT COUNT(*) FROM daily_trading_plans WHERE trade_date=? AND status='active'",
        (td,),
    )
    if active > 0:
        return None
    return ("거래준비(S1~S5-A) 미완료/미활성",
            "오늘 활성(active) Daily Plan이 없음 — 거래준비 파이프라인이 미완료이거나 활성화 실패."
            + _audit_fail_suffix(conn, td, ["S1", "S5-V", "S5-A"]))


def _chk_quality_universe(conn, td):
    row = conn.execute(
        "SELECT filtered_count FROM universe_filter_results WHERE trade_date=? ORDER BY created_at DESC LIMIT 1",
        (td,),
    ).fetchone()
    if row is None:
        return ("S3 유니버스 결과 없음", "오늘 universe_filter_results가 없음 — S3 미실행 의심.")
    if int(row["filtered_count"] or 0) < 1:
        return ("S3 유니버스 0건", "S3 유니버스 필터 통과 종목이 0건 — 데이터 결손/필터 과도 의심.")
    return None


def _chk_quality_screening(conn, td):
    row = conn.execute(
        "SELECT output_count, overall_confidence FROM hybrid_screening_results"
        " WHERE trade_date=? ORDER BY created_at DESC LIMIT 1",
        (td,),
    ).fetchone()
    if row is None:
        return ("S4 스크리닝 결과 없음", "오늘 hybrid_screening_results가 없음 — S4 미실행 의심.")
    if int(row["output_count"] or 0) < 1 or float(row["overall_confidence"] or 0) <= 0:
        return ("S4 스크리닝 결과 부실",
                f"S4 후보 {row['output_count']}건, confidence {row['overall_confidence']} — 결과 부실/LLM 실패 의심.")
    return None


def _chk_baseline(conn, td):
    if _count(conn, "SELECT COUNT(*) FROM daily_capital_baseline WHERE trade_date=?", (td,)) > 0:
        return None
    return ("09:00 예수금 baseline 미캡처",
            "daily_capital_baseline에 오늘 09:00 예수금 스냅이 없음 — 레짐 예산 사이징 영향 가능.")


def _chk_buy_not_executed(conn, td):
    signals = _count(
        conn, "SELECT COUNT(*) FROM trading_signals WHERE trade_date=? AND signal_type='BUY'", (td,)
    )
    if signals == 0:
        return None
    orders = _count(
        conn,
        "SELECT COUNT(*) FROM trading_orders WHERE trade_date=? AND side='buy'"
        " AND status IN ('submitted','filled','submitted_without_order_no')",
        (td,),
    )
    if orders > 0:
        return None
    # 매수신호는 있는데 주문이 0 — preflight 차단 사유 동봉
    reasons = []
    try:
        rows = conn.execute(
            "SELECT symbol, block_reasons, result FROM order_preflight_checks"
            " WHERE substr(created_at,1,10)=? ORDER BY created_at DESC LIMIT 10",
            (td,),
        ).fetchall()
        for r in rows:
            br = r["block_reasons"]
            if br and str(br) not in ("[]", "null", ""):
                reasons.append(f"{r['symbol']}: {br}")
    except Exception:
        pass
    detail = f"매수신호 {signals}건인데 매수주문 0건. "
    detail += ("preflight 차단 사유 — " + " / ".join(reasons[:5])) if reasons else \
        "preflight 차단 기록 없음 — 신규매수금지시간·예수금·DE비활성·리스크게이트 확인 필요."
    return ("매수신호 있으나 주문 미발생", detail)


def _chk_postprocess(conn, td):
    if _count(conn, "SELECT COUNT(*) FROM daily_review_reports WHERE trade_date=?", (td,)) > 0:
        return None
    return ("S9~S10 후처리 미완료",
            "15:20 후처리(청산·리뷰) 결과(daily_review_reports)가 오늘 없음."
            + _audit_fail_suffix(conn, td, ["S9", "POSTPROCESS"]))


def _chk_auto_halt(conn, td):
    """일중손실 자동 긴급정지 — 관측 손실%가 임계 이하이면 신규 매수 차단(emergency halt).

    자동 청산은 하지 않는다(PM 정책 — 신규 매수 차단만).
    관측 불가(None)면 아무것도 안 함(fail-open — preflight 쪽 fail-closed가 별도 담당).
    """
    try:
        threshold = float(get_setting("risk.auto_halt_loss_percent", -5.0))
    except (TypeError, ValueError):
        logger.warning("WARN: [OpsWatchdog] risk.auto_halt_loss_percent 값 비정상 — auto_halt 비활성")
        return None
    if threshold >= 0:
        return None  # 0 또는 양수면 비활성
    if bool(get_setting("risk.emergency_halt_enabled", False)):
        return None  # 이미 긴급정지 상태 — 중복 발동 방지

    percent, source = _observed_daily_loss_percent(td)
    if percent is None:
        return None  # 관측 불가 — fail-open
    if percent > threshold:
        return None  # 임계 미달 — 정상

    # 발동: 신규 매수 차단 설정 ON (기존 preflight가 이 설정을 읽어 매수 차단)
    upsert_setting(
        "risk.emergency_halt_enabled",
        True,
        "boolean",
        f"자동 긴급정지 — 일중손실 {percent:.2f}% ≤ {threshold:.2f}% (source={source})",
        "ops_watchdog_auto_halt",
    )
    logger.warning(
        "OPS-AUTO-HALT: 일중손실 %.2f%% ≤ %.2f%% — emergency_halt_enabled=True (source=%s)",
        percent, threshold, source,
    )
    return ("자동 긴급정지 발동 — 일중손실 한도 도달",
            f"일중손실 {percent:.2f}% ≤ 임계 {threshold:.2f}% (source={source}) — "
            "신규 매수 차단(risk.emergency_halt_enabled=True). 자동 청산은 하지 않음. "
            "해제하려면 설정에서 emergency_halt_enabled를 끄세요.")


class Check(NamedTuple):
    id: str
    severity: str
    start_min: int
    end_min: int  # 24*60 이면 종일
    fn: Callable


_REGISTRY: list[Check] = [
    Check("s2_premarket", "WARNING", _M0835, 24 * 60, _chk_s2_premarket),
    Check("trade_prep", "CRITICAL", _M0906, 24 * 60, _chk_trade_prep),
    Check("quality_universe", "WARNING", _M0906, 24 * 60, _chk_quality_universe),
    Check("quality_screening", "WARNING", _M0906, 24 * 60, _chk_quality_screening),
    Check("baseline_capture", "WARNING", _M0905, 24 * 60, _chk_baseline),
    Check("buy_not_executed", "CRITICAL", _M0910, _M1530, _chk_buy_not_executed),
    Check("postprocess", "CRITICAL", _M1525, 24 * 60, _chk_postprocess),
    # 일중손실 자동 긴급정지 — 장중(09:05~15:20)만 적용
    Check("auto_halt", "CRITICAL", _M0905, _M1520, _chk_auto_halt),
]


def _alert_exists(trade_date: str, title: str) -> bool:
    """같은 이상(미확인)이 오늘 이미 있으면 True — 5분 틱 도배 방지."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM system_alerts WHERE trade_date=? AND alert_type='ops_watch'"
            " AND title=? AND acknowledged=0 LIMIT 1",
            (trade_date, title),
        ).fetchone()
    return row is not None


def run_ops_watchdog(now: datetime | None = None) -> dict:
    """5분 틱: 현재 시각 기준 적용 가능한 체크를 돌려 이상을 Alert Center에 기록한다.

    Returns:
        {"skipped": <reason>} 또는 {"checks": n, "anomalies": n, "created": n}.
    """
    now = now or _now_kst()
    td = now.strftime("%Y-%m-%d")
    if not is_trading_day(td):
        logger.info("SKIP: [OpsWatchdog] 비거래일 — trade_date=%s", td)
        return {"skipped": "non_trading_day", "created": 0}

    mins = now.hour * 60 + now.minute
    anomalies: list[tuple[Check, str, str]] = []
    checks_run = 0
    with get_connection() as conn:
        for chk in _REGISTRY:
            if not (chk.start_min <= mins <= chk.end_min):
                continue
            checks_run += 1
            try:
                res = chk.fn(conn, td)
            except Exception as exc:
                logger.warning("WARN: [OpsWatchdog] check=%s 실패 — %s", chk.id, exc)
                continue
            if res:
                anomalies.append((chk, res[0], res[1]))

    created = 0
    for chk, title, detail in anomalies:
        if _alert_exists(td, title):
            continue
        try:
            create_alert("ops_watch", title, chk.severity, detail, trade_date=td)
            created += 1
            logger.warning("OPS-ANOMALY: [%s] %s — %s", chk.severity, title, detail[:160])
        except Exception as exc:
            logger.warning("WARN: [OpsWatchdog] alert 생성 실패 title=%s — %s", title, exc)

    logger.info(
        "SUCCESS: [OpsWatchdog] td=%s checks=%d anomalies=%d created=%d",
        td, checks_run, len(anomalies), created,
    )
    return {"checks": checks_run, "anomalies": len(anomalies), "created": created}
