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
_M0900 = 9 * 60
_M0905 = 9 * 60 + 5
_M0906 = 9 * 60 + 6
_M0910 = 9 * 60 + 10
_M0940 = 9 * 60 + 40
_M1520 = 15 * 60 + 20
_M1530 = 15 * 60 + 30
_M1535 = 15 * 60 + 35
_M1525 = 15 * 60 + 25


def _gate_min_from_schedule(setting_key: str, *, default_min: int, grace_min: int) -> int:
    """스케줄 설정("HH:MM") + grace 로 게이트 시작 분을 동적 산출.

    S1~S5 실행시간이 설정으로 이동 가능해지면서(6/10: 09:01/09:05) 하드코딩 게이트가
    실행 전 시간대에 허위 anomaly를 내던 문제를 막는다. 설정 누락/형식 오류는 default.
    """
    try:
        raw = str(get_setting(setting_key, "") or "")
        hh, mm = raw.split(":")
        return int(hh) * 60 + int(mm) + grace_min
    except Exception:
        return default_min


def _now_kst() -> datetime:
    return datetime.now(KST)


def _to_kst(iso_str: str | None) -> datetime | None:
    """ISO 타임스탬프를 KST aware datetime으로. tz 없으면 KST 가정, 'Z'는 UTC. 실패는 None."""
    if not iso_str:
        return None
    try:
        ts = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=KST)
        return ts.astimezone(KST)
    except Exception:
        return None


def _kst_minute_of_day(iso_str: str | None) -> int | None:
    ts = _to_kst(iso_str)
    return ts.hour * 60 + ts.minute if ts else None


def _min_to_hhmm(m: int) -> str:
    return f"{int(m) // 60:02d}:{int(m) % 60:02d}"


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
    """거래준비 완료 여부 — 활성 Plan 없으면 '미실행', 늦게라도 됐으면 '지연'으로 구분(2026-08-29).

    라벨 정교화: 08-28처럼 준비가 2.5h '지연 완료'된 날을 "미실행(never ran)"으로 오탐 프레이밍
    하지 않는다. ①활성 Plan이 늦게(게이트 이후) 활성화 → '지연 완료' WARNING. ②아직 없지만 준비
    런이 방금 시작 → '지연 진행중' WARNING. ③런 흔적도 없음 → '미실행' CRITICAL(기본).
    """
    row = conn.execute(
        "SELECT created_at FROM daily_trading_plans WHERE trade_date=? AND status='active'"
        " ORDER BY created_at DESC LIMIT 1",
        (td,),
    ).fetchone()
    deadline = _gate_trade_prep()  # 정상 완료 기대 시각(스케줄+grace)
    if row is not None:
        m = _kst_minute_of_day(row["created_at"])
        if m is not None and m > deadline:
            return ("거래준비 지연 완료 — 늦게 활성화",
                    f"활성 Daily Plan이 {_min_to_hhmm(m)}에야 활성화됨(기대 {_min_to_hhmm(deadline)} 이내, "
                    f"{m - deadline}분 지연). 서버 지연기동/파이프라인 지연으로 오전 매매 공백 가능.",
                    "WARNING")
        return None
    # 활성 Plan 없음 — 준비 런이 진행중이면 '지연', 아니면 '미실행'
    try:
        run = conn.execute(
            "SELECT created_at, status FROM daily_plan_run_history WHERE trade_date=?"
            " ORDER BY created_at DESC LIMIT 1",
            (td,),
        ).fetchone()
    except Exception:
        run = None
    if run is not None:
        age = _age_minutes(run["created_at"])
        status = str(run["status"] or "").lower()
        grace = _wnum("watchdog.prep_inprogress_grace_min", 20.0)
        if age is not None and age <= grace and status not in ("failed", "error", "aborted"):
            return ("거래준비 지연 — 진행중",
                    f"활성 Plan 아직 없음 — 준비 런이 {age:.0f}분 전 시작(status={run['status']}), 완료 대기. "
                    "정상 지연이면 곧 활성화됨(미실행 아님).",
                    "WARNING")
    return ("거래준비(S1~S5-A) 미완료/미활성",
            "현재 시각까지 활성(active) Daily Plan이 없음 — 거래준비 파이프라인 미완료/활성화 실패 의심."
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


# ══ 정합성 감시(Sanity Watchdog) — "시스템 믿음 vs 현실" 괴리 감지 (2026-08-24) ══
# PM이 눈으로 잡던 "이거 이상해"를 규칙화한 6종. 운영 단계 점검(_chk_s2 등)이 "스텝이
# 돌았나"를 본다면, 이 6종은 "시스템의 내부 판단이 실제 시장·계좌·설정과 어긋난 순간"을
# 잡는다. 규칙마다 watchdog.<rule>_enabled 킬스위치. LLM·자동수정 없음 — Alert만.

def _enabled(rule: str) -> bool:
    """규칙별 킬스위치 watchdog.<rule>_enabled (기본 True). 설정 오류/부재는 활성 유지."""
    try:
        return bool(get_setting(f"watchdog.{rule}_enabled", True))
    except Exception:
        return True


def _wnum(key: str, default: float) -> float:
    """watchdog 임계 설정 읽기 — 설정 오류/부재는 default (unit 테스트 settings 테이블 부재 대응)."""
    try:
        return float(get_setting(key, default))
    except Exception:
        return default


def _latest_kospi_change(conn) -> float | None:
    """market_snapshots 최신 KOSPI 등락률(%). 없거나 파싱 실패면 None. (KIS 호출 없음 — DB만)"""
    try:
        row = conn.execute(
            "SELECT change_rate FROM market_snapshots"
            " WHERE UPPER(symbol) IN ('KOSPI','KS11','^KS11')"
            " ORDER BY captured_at DESC LIMIT 1"
        ).fetchone()
        if not row or row["change_rate"] is None:
            return None
        return float(row["change_rate"])
    except Exception:
        return None


def _age_minutes(iso_str: str | None) -> float | None:
    """ISO 타임스탬프의 현재(_now_kst) 대비 경과 분. tz 없으면 KST 가정. 파싱 실패면 None."""
    if not iso_str:
        return None
    try:
        ts = datetime.fromisoformat(str(iso_str))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=KST)
        return (_now_kst() - ts).total_seconds() / 60.0
    except Exception:
        return None


def _entry_suspended(td: str) -> bool:
    """하락전환 래치 등 의도된 진입중단 상태인지(래치 최신성 가드 포함). 실패는 False."""
    try:
        from .intraday_regime_monitor import get_entry_suspended
        return bool(get_entry_suspended())  # 무인자(래치는 설정 기반) — td는 인터페이스 일관용
    except Exception:
        return False


def _active_max_positions(td: str) -> int | None:
    """오늘 유효 최대 종목수(단일출처 strategy_playbook). 실패면 None(대조 스킵)."""
    try:
        from .daily_capital import get_active_max_positions
        return int(get_active_max_positions(td))
    except Exception:
        return None


def _blocked_symbol_count(conn) -> int:
    """현재 유효한 하드차단 종목 수(symbol_entry_blocks). 테이블 부재/실패는 0(대조 스킵)."""
    try:
        now_iso = _now_kst().isoformat()
        return _count(
            conn,
            "SELECT COUNT(*) FROM symbol_entry_blocks WHERE expires_at IS NULL OR expires_at > ?",
            (now_iso,),
        )
    except Exception:
        return 0


def _entry_funnel(conn, td) -> tuple[int, int, int, int, int]:
    """진입 전환 퍼널: (S3유니버스, S4스크리닝, 매수신호, 실매수, 하드차단종목).

    "선정→신호→매수" 어느 칸에서 깔때기가 막히는지 국소화. 각 조회는 방어적(테이블 부재는 0).
    (거부사유 테이블 candidate_no_entry_reasons/approval_decision_logs는 死 → 살아있는 산출물로 대체)
    """
    def _latest_int(sql: str, col: str) -> int:
        try:
            r = conn.execute(sql, (td,)).fetchone()
            return int(r[col] or 0) if r and r[col] is not None else 0
        except Exception:
            return 0

    s3 = _latest_int(
        "SELECT filtered_count FROM universe_filter_results WHERE trade_date=?"
        " ORDER BY created_at DESC LIMIT 1", "filtered_count")
    s4 = _latest_int(
        "SELECT output_count FROM hybrid_screening_results WHERE trade_date=?"
        " ORDER BY created_at DESC LIMIT 1", "output_count")
    try:
        signals = _count(
            conn, "SELECT COUNT(*) FROM trading_signals WHERE trade_date=? AND signal_type='BUY'", (td,))
    except Exception:
        signals = 0
    try:
        buys = _count(
            conn, "SELECT COUNT(*) FROM fills WHERE substr(filled_at,1,10)=? AND side='buy'", (td,))
    except Exception:
        buys = 0
    return s3, s4, signals, buys, _blocked_symbol_count(conn)


# 상승/중립으로 보는 레짐 라벨 vs 방어로 보는 라벨 (regime_set_applications.regime_label 실측값)
_BULLISH_REGIMES = {"risk_on", "neutral"}
_BEARISH_REGIMES = {"risk_off"}


def _chk_regime_reality(conn, td):
    """R1 레짐↔현실 괴리 — 적용 레짐 판단이 라이브 코스피와 반대 방향.

    2026-08-24 재기동 되돌림 사고(하락장에 neutral 재적용→공격매수)를 사후에도 잡는 backstop.
    적용 후 sustain_min(기본20) 미만이면 신선한 전환으로 보고 억제(전환 직후 오탐 방지).
    """
    if not _enabled("regime_reality"):
        return None
    row = conn.execute(
        "SELECT regime_label, applied_at FROM regime_set_applications"
        " WHERE trade_date=? AND current_flag=1 ORDER BY applied_at DESC, created_at DESC LIMIT 1",
        (td,),
    ).fetchone()
    if not row or not row["regime_label"]:
        return None
    regime = str(row["regime_label"]).strip().lower()
    kospi = _latest_kospi_change(conn)
    if kospi is None:
        return None
    age = _age_minutes(row["applied_at"])
    if age is not None and age < _wnum("watchdog.regime_div_sustain_min", 20.0):
        return None  # 방금 전환 — 지속조건 미충족, 억제
    band = _wnum("watchdog.regime_div_kospi_pct", 1.5)
    if regime in _BULLISH_REGIMES and kospi <= -band:
        return ("레짐↔현실 괴리 — 시스템은 상승/중립인데 시장 하락",
                f"적용 레짐={regime}인데 코스피 {kospi:+.2f}% (임계 -{band:.1f}%). "
                "레짐 되돌림/오분류 의심 — 방어 레짐 적용 여부 확인 필요.")
    if regime in _BEARISH_REGIMES and kospi >= band:
        return ("레짐↔현실 괴리 — 시스템은 방어인데 시장 급반등",
                f"적용 레짐={regime}인데 코스피 {kospi:+.2f}% (임계 +{band:.1f}%). "
                "기회상실 의심 — 상승전환 재개 여부 확인 필요.")
    return None


def _chk_order_reject_streak(conn, td):
    """R2 매수주문 연속 실패 — 오늘 매수주문이 임계N건 이상 전부 실패(성공 0).

    2026-07-13 40910000 주문거부→봇 정지 재발 방지. 계좌만료/토큰 사망 조기경보.
    """
    if not _enabled("order_reject"):
        return None
    n = int(_wnum("watchdog.order_reject_streak_n", 3.0))
    failed = _count(
        conn,
        "SELECT COUNT(*) FROM trading_orders WHERE trade_date=? AND side='buy' AND status='failed'",
        (td,),
    )
    if failed < n:
        return None
    ok = _count(
        conn,
        "SELECT COUNT(*) FROM trading_orders WHERE trade_date=? AND side='buy'"
        " AND status IN ('submitted','filled','submitted_without_order_no')",
        (td,),
    )
    if ok > 0:
        return None  # 일부 성공 → 계좌 살아있음, streak 아님
    reason = ""
    try:
        r = conn.execute(
            "SELECT reason FROM trading_orders WHERE trade_date=? AND side='buy' AND status='failed'"
            " AND reason IS NOT NULL AND reason<>'' ORDER BY created_at DESC LIMIT 1",
            (td,),
        ).fetchone()
        reason = str(r["reason"]) if r and r["reason"] else ""
    except Exception:
        reason = ""
    return ("매수주문 연속 실패 — 계좌/토큰 의심",
            f"오늘 매수주문 {failed}건 전부 실패, 성공 0건. 최근 사유: {reason[:120] or '기록없음'} "
            "(40910000=계좌만료 등 KIS 거부 확인 필요).")


def _chk_market_data_stale(conn, td):
    """R3 코스피 시세 정체 — 장중 KOSPI 스냅샷 갱신이 임계(기본10분)보다 오래됨/아예 없음.

    2026-07-11 index-board 사망→시세피드 정체(레짐이 옛 값 고착)를 조기 감지.
    """
    if not _enabled("market_stale"):
        return None
    row = conn.execute(
        "SELECT captured_at FROM market_snapshots"
        " WHERE UPPER(symbol) IN ('KOSPI','KS11','^KS11') ORDER BY captured_at DESC LIMIT 1"
    ).fetchone()
    threshold = _wnum("watchdog.market_stale_min", 10.0)
    if not row or not row["captured_at"]:
        return ("장중 코스피 시세 없음",
                "market_snapshots에 오늘 KOSPI 스냅샷이 없음 — 시세피드/폴링잡 사망 의심.")
    age = _age_minutes(row["captured_at"])
    if age is None:
        return None
    if age > threshold:
        return ("코스피 시세 정체 — 시세피드 사망 의심",
                f"마지막 KOSPI 갱신 {age:.0f}분 전 (임계 {threshold:.0f}분). "
                "index-board/폴링 정체 — 레짐 판단이 옛 값에 고착될 수 있음.")
    return None


def _chk_entry_paralysis(conn, td):
    """R4 진입 마비 — S3 후보는 있는데 매수신호 0, 긴급정지·의도된 진입중단도 아님.

    2026-07-23 밴드역전 매매마비 재발 방지. (buy_not_executed는 신호>0·주문0을, 이건 신호=0을 본다)
    """
    if not _enabled("entry_paralysis"):
        return None
    row = conn.execute(
        "SELECT filtered_count FROM universe_filter_results WHERE trade_date=? ORDER BY created_at DESC LIMIT 1",
        (td,),
    ).fetchone()
    candidates = int(row["filtered_count"] or 0) if row else 0
    if candidates < 1:
        return None  # 후보 없으면 신호 없는 게 정상
    signals = _count(
        conn, "SELECT COUNT(*) FROM trading_signals WHERE trade_date=? AND signal_type='BUY'", (td,)
    )
    if signals > 0:
        return None  # 신호 나옴 → 마비 아님
    try:
        if bool(get_setting("risk.emergency_halt_enabled", False)):
            return None  # 긴급정지 = 의도된 차단
    except Exception:
        pass
    if _entry_suspended(td):
        return None  # 하락전환 래치 등 의도된 진입중단
    s3, s4, sig, buys, blocked = _entry_funnel(conn, td)
    return ("진입 마비 의심 — 후보 있으나 신호 0",
            f"S3 후보 {candidates}건인데 매수신호 0건. "
            f"[퍼널] S3 {s3} → S4 {s4} → 신호 {sig} → 매수 {buys} (하드차단 {blocked}종). "
            "긴급정지·진입중단(하락전환 래치)도 아님 — 진입밴드 역전/게이트 과도 차단 의심 "
            "(S4는 있는데 신호 0이면 진입게이트 과도, S4가 급감이면 선정 문제).")


def _chk_selection_starved(conn, td):
    """R7 선정 빈약 — 오늘 S4 후보수가 최근 중앙값 대비 급감(선정 단계 붕괴 조기감지, 2026-08-29).

    "종목선정이 잘못된 건 아닐까"(PM 가설)를 수치화. S4 미실행(0행)은 quality_screening이 담당.
    """
    if not _enabled("selection_starved"):
        return None
    today_row = conn.execute(
        "SELECT MAX(output_count) AS oc FROM hybrid_screening_results WHERE trade_date=?", (td,)
    ).fetchone()
    if not today_row or today_row["oc"] is None:
        return None  # 미실행 — quality_screening이 담당
    today = int(today_row["oc"] or 0)
    rows = conn.execute(
        "SELECT MAX(output_count) AS oc FROM hybrid_screening_results WHERE trade_date < ?"
        " GROUP BY trade_date ORDER BY trade_date DESC LIMIT 10", (td,)
    ).fetchall()
    vals = sorted(int(r["oc"] or 0) for r in rows if r["oc"] is not None)
    if len(vals) < 3:
        return None  # baseline 표본 부족 — 판단 보류
    median = vals[len(vals) // 2]
    if median <= 0:
        return None
    ratio = _wnum("watchdog.selection_starved_ratio", 0.4)
    if today < median * ratio:
        return ("선정 빈약 — S4 후보 급감",
                f"오늘 S4 후보 {today}건 < 최근 중앙값 {median}건 × {ratio:.0%}. "
                "데이터 결손/필터 과도/유니버스 축소로 선정 단계가 굶주림 의심.")
    return None


def _chk_position_conflict(conn, td):
    """R5 포지션↔설정 모순 — 실보유 종목수가 max_positions를 초과(과다 노출).

    KIS 잔고 스냅샷(daily_holdings_snapshot) 기준 — fresh KIS 호출 없음.
    """
    if not _enabled("position_conflict"):
        return None
    held = _count(
        conn, "SELECT COUNT(*) FROM daily_holdings_snapshot WHERE trade_date=? AND qty>0", (td,)
    )
    if held < 1:
        return None
    max_pos = _active_max_positions(td)
    if not max_pos or max_pos <= 0:
        return None
    if held > max_pos:
        return ("보유 종목수 초과 — 과다 노출",
                f"실보유 {held}종목 > max_positions {max_pos}. 설정 초과 노출 — 교체/청산 로직 점검 필요.")
    return None


def _chk_qty_drift(conn, td):
    """R6 DB↔KIS 수량 드리프트 — DB 원장(position_cost_basis) 보유 > KIS 실보유(스냅샷).

    유령보유(유령매도의 뿌리) 조기경보. 오늘 원장·스냅샷이 모두 있을 때만 대조(오탐 억제).
    KIS>DB(외부매수 미반영)는 유령 아님 → 발동 안 함.
    """
    if not _enabled("qty_drift"):
        return None
    kis_rows = conn.execute(
        "SELECT norm_symbol, qty FROM daily_holdings_snapshot WHERE trade_date=?", (td,)
    ).fetchall()
    if not kis_rows:
        return None  # 스냅샷 없음 — R3가 별도 감지
    kis = {str(r["norm_symbol"]): int(r["qty"] or 0) for r in kis_rows}
    ledger_rows = conn.execute(
        "SELECT norm_symbol, qty FROM position_cost_basis WHERE trade_date=?", (td,)
    ).fetchall()
    if not ledger_rows:
        return None  # 오늘 원장 갱신 없음 — 대조 스킵(오탐 억제)
    drifts = []
    for r in ledger_rows:
        sym = str(r["norm_symbol"])
        dq = int(r["qty"] or 0)
        kq = kis.get(sym, 0)
        if dq > kq:
            drifts.append(f"{sym}: DB {dq} > KIS {kq}")
    if drifts:
        return ("DB↔KIS 수량 드리프트 — 유령보유 의심",
                f"{len(drifts)}종목 DB원장>KIS실보유: " + " / ".join(drifts[:5]) +
                " — 유령매도/미체결 잔여 의심, KIS 정합 확인 필요.")
    return None


# ══ 자기 죽음 감시(heartbeat) + 외부 dead-man switch (2026-08-29) ══════════════
# in-process 감시봇은 서버가 죽으면 같이 죽어 "자기 사망"을 실시간 못 잡는다(08-28 리부팅
# 참사=오전 내내 봇 사망을 되살아난 뒤에야 인지). ①매 틱 heartbeat 기록 → 되살아난 첫 틱이
# 장중 공백을 역산해 경보. ②외부 URL로 dead-man ping → 완전 다운도 외부에서 포착.

def _read_last_heartbeat() -> str | None:
    """직전 틱 시각(ISO). 테이블 부재/최초 틱은 None."""
    try:
        with get_connection() as conn:
            row = conn.execute("SELECT last_tick_at FROM watchdog_heartbeat WHERE id=1").fetchone()
            return str(row["last_tick_at"]) if row and row["last_tick_at"] else None
    except Exception:
        return None


def _write_heartbeat(now: datetime) -> None:
    """현재 틱 시각을 단일행 upsert(WAL-safe). 자체 CREATE로 스키마 미초기화 DB도 자립."""
    try:
        with get_connection() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS watchdog_heartbeat"
                " (id INTEGER PRIMARY KEY CHECK (id=1), last_tick_at TEXT NOT NULL)"
            )
            conn.execute(
                "INSERT INTO watchdog_heartbeat(id, last_tick_at) VALUES(1, ?)"
                " ON CONFLICT(id) DO UPDATE SET last_tick_at=excluded.last_tick_at",
                (now.isoformat(),),
            )
            conn.commit()
    except Exception as exc:
        logger.warning("WARN: [OpsWatchdog] heartbeat 기록 실패 — %s", exc)


def _ping_deadman() -> None:
    """외부 dead-man switch(healthchecks.io식)로 생존 핑. URL 미설정이면 no-op. 실패는 무시.

    ops_watch.deadman_ping_url 설정. 감시봇 크론(매일 08~15시 5분)과 같은 주기이므로 외부는
    스케줄 `*/5 8-15 * * *`(Asia/Seoul)·grace 10~15분으로 맞추면 서버 완전 다운도 외부 경보.
    """
    try:
        url = str(get_setting("ops_watch.deadman_ping_url", "") or "").strip()
    except Exception:
        url = ""
    if not url:
        return
    try:
        import httpx
        httpx.get(url, timeout=3.0)
    except Exception as exc:
        logger.debug("[OpsWatchdog] deadman ping 실패(무시) — %s", exc)


def _market_gap_overlap_min(prev_iso: str | None, now: datetime) -> float | None:
    """직전 틱→현재 공백 중 '장중(09:00~15:30)'과 겹치는 분. 야간·주말 공백은 자동 제외.

    prev가 전 거래일이어도 오늘 09:00부터만 세므로 08-28식 '오전 내내 사망'을 정확히 계량.
    """
    prev = _to_kst(prev_iso)
    if prev is None:
        return None
    open_dt = now.replace(hour=9, minute=0, second=0, microsecond=0)
    close_dt = now.replace(hour=15, minute=30, second=0, microsecond=0)
    gap_start = max(prev, open_dt)
    gap_end = min(now, close_dt)
    return max(0.0, (gap_end - gap_start).total_seconds() / 60.0)


def _heartbeat_gap_alert(prev_iso: str | None, now: datetime, mins: int):
    """장중 감시봇 틱 공백 → 프로세스 사망/재기동 경보. 되살아난 첫 틱이 역산해 발화."""
    if not _enabled("heartbeat"):
        return None
    if not (_M0900 <= mins <= _M1535):
        return None  # 장중 창에서만 평가(야간/후처리 시각 오탐 방지)
    overlap = _market_gap_overlap_min(prev_iso, now)
    if overlap is None:
        return None  # 최초 틱 — 비교 대상 없음
    threshold = _wnum("watchdog.heartbeat_gap_min", 15.0)
    if overlap <= threshold:
        return None
    prev_disp = _to_kst(prev_iso)
    prev_hhmm = prev_disp.strftime("%m-%d %H:%M") if prev_disp else "?"
    return ("장중 봇 공백 — 프로세스 사망/재기동 의심",
            f"감시봇 틱이 장중 약 {overlap:.0f}분 끊김(직전 {prev_hhmm} → 현재 {now:%H:%M}). "
            "서버 다운/재기동 의심 — 그 사이 매매·손절 감시 공백. 외부 dead-man switch·systemd 상태 확인.",
            "CRITICAL")


class Check(NamedTuple):
    id: str
    severity: str
    start_min: int | Callable[[], int]  # callable이면 실행 시점에 스케줄 설정으로 동적 산출
    end_min: int  # 24*60 이면 종일
    fn: Callable


# 스케줄 이동 가능 단계는 설정 연동 게이트 사용 (6/11: 08:35 하드코딩이 09:01 S2에 허위 anomaly)
def _gate_s2() -> int:
    return _gate_min_from_schedule("schedule_s2_time", default_min=_M0835, grace_min=10)


def _gate_trade_prep() -> int:
    return _gate_min_from_schedule("schedule_trade_prep_time", default_min=_M0906, grace_min=15)


_REGISTRY: list[Check] = [
    Check("s2_premarket", "WARNING", _gate_s2, 24 * 60, _chk_s2_premarket),
    Check("trade_prep", "CRITICAL", _gate_trade_prep, 24 * 60, _chk_trade_prep),
    Check("quality_universe", "WARNING", _gate_trade_prep, 24 * 60, _chk_quality_universe),
    Check("quality_screening", "WARNING", _gate_trade_prep, 24 * 60, _chk_quality_screening),
    Check("baseline_capture", "WARNING", _gate_trade_prep, 24 * 60, _chk_baseline),
    Check("buy_not_executed", "CRITICAL", _M0910, _M1530, _chk_buy_not_executed),
    Check("postprocess", "CRITICAL", _M1525, 24 * 60, _chk_postprocess),
    # 일중손실 자동 긴급정지 — 장중(09:05~15:20)만 적용
    Check("auto_halt", "CRITICAL", _M0905, _M1520, _chk_auto_halt),
    # ── 정합성 감시(Sanity Watchdog) — 시스템 믿음 vs 현실 괴리, 장중만 적용 (2026-08-24) ──
    Check("regime_reality", "WARNING", _M0940, _M1520, _chk_regime_reality),
    Check("order_reject_streak", "CRITICAL", _M0910, _M1520, _chk_order_reject_streak),
    Check("market_data_stale", "WARNING", _M0940, _M1520, _chk_market_data_stale),
    Check("entry_paralysis", "WARNING", _M0940, _M1520, _chk_entry_paralysis),
    Check("position_conflict", "CRITICAL", _M0910, _M1520, _chk_position_conflict),
    Check("qty_drift", "WARNING", _M0940, _M1520, _chk_qty_drift),
    # 선정 빈약 — S4 후보 급감(선정 단계 붕괴 조기감지, 2026-08-29)
    Check("selection_starved", "WARNING", _gate_trade_prep, _M1520, _chk_selection_starved),
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

    # 자기 죽음 감시 — 거래일 가드 이전에 처리(공백 역산·외부 dead-man ping은 매일 수행).
    prev_tick = _read_last_heartbeat()
    _write_heartbeat(now)
    _ping_deadman()

    if not is_trading_day(td):
        logger.info("SKIP: [OpsWatchdog] 비거래일 — trade_date=%s", td)
        return {"skipped": "non_trading_day", "created": 0}

    mins = now.hour * 60 + now.minute
    # (title, detail, severity)
    anomalies: list[tuple[str, str, str]] = []
    checks_run = 0
    with get_connection() as conn:
        for chk in _REGISTRY:
            start_min = chk.start_min() if callable(chk.start_min) else chk.start_min
            if not (start_min <= mins <= chk.end_min):
                continue
            checks_run += 1
            try:
                res = chk.fn(conn, td)
            except Exception as exc:
                logger.warning("WARN: [OpsWatchdog] check=%s 실패 — %s", chk.id, exc)
                continue
            if res:
                # 체크가 3-튜플이면 severity 오버라이드(예: 미실행 CRITICAL vs 지연 WARNING)
                sev = res[2] if len(res) >= 3 else chk.severity
                anomalies.append((res[0], res[1], sev))

    # 장중 감시봇 공백(자기 죽음) — prev_tick은 덮어쓰기 전 값
    hb = _heartbeat_gap_alert(prev_tick, now, mins)
    if hb:
        anomalies.append((hb[0], hb[1], hb[2]))

    created = 0
    for title, detail, severity in anomalies:
        if _alert_exists(td, title):
            continue
        try:
            create_alert("ops_watch", title, severity, detail, trade_date=td)
            created += 1
            logger.warning("OPS-ANOMALY: [%s] %s — %s", severity, title, detail[:160])
        except Exception as exc:
            logger.warning("WARN: [OpsWatchdog] alert 생성 실패 title=%s — %s", title, exc)

    # 전략 사양 드리프트 감지 — 실측(라이브 설정/레짐 SET)이 STRATEGY_SPEC.md의 의도를
    # 벗어났나. 파일은 수정하지 않는다(작업트리 청결) — 벗어났으면 Alert만 남긴다.
    # "이렇게 동작해야 하는데 안 그러면 고쳐라"를 사람 없이 잡는 장치. LLM/자동수정 없음.
    try:
        from .strategy_spec import check_conformance, check_drift

        drift = check_drift()
        if drift:
            title = "전략 사양 드리프트 — 실측이 의도와 다름"
            if not _alert_exists(td, title):
                detail = f"드리프트 {len(drift)}건: " + " / ".join(drift[:5])
                create_alert("ops_watch", title, "WARNING", detail, trade_date=td)
                created += 1
                logger.warning("OPS-DRIFT: [전략] 드리프트 %d건 — %s", len(drift), detail[:160])
        # conformance: SSOT 주장의 구현(코드·설정)이 실제 존재하나 (값 아닌 맞물림)
        conf = check_conformance()
        if conf:
            title = "전략 사양 불일치 — SSOT↔구현 맞물림 깨짐"
            if not _alert_exists(td, title):
                detail = f"conformance {len(conf)}건: " + " / ".join(conf[:5])
                create_alert("ops_watch", title, "CRITICAL", detail, trade_date=td)
                created += 1
                logger.warning("OPS-CONFORM: [전략] 불일치 %d건 — %s", len(conf), detail[:160])
    except Exception as exc:
        logger.warning("WARN: [OpsWatchdog] 전략 사양 체크 실패 — %s", exc)

    logger.info(
        "SUCCESS: [OpsWatchdog] td=%s checks=%d anomalies=%d created=%d",
        td, checks_run, len(anomalies), created,
    )
    return {"checks": checks_run, "anomalies": len(anomalies), "created": created}
