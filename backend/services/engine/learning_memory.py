"""S11 Learning Memory Builder — Review & Audit 결과를 구조화된 메모리로 변환."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection

logger = logging.getLogger("LearningMemory")


def _now_kst() -> datetime:
    """Return the current KST datetime for memory timestamps."""
    return datetime.now(ZoneInfo("Asia/Seoul"))


def _json_dumps(value: Any) -> str:
    """Serialize memory evidence and recommendation payloads."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads(value: str | None, default: Any) -> Any:
    """Parse JSON text columns with a defensive default for old or malformed data."""
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _auto_apply_flags(trade_count: int, avg_pnl: float) -> tuple[bool, bool]:
    """Apply S11 auto-apply policy from the approved task brief.

    Args:
        trade_count: Number of trades backing the memory.
        avg_pnl: Average PnL used as evidence.
    """
    if trade_count >= 3 and abs(avg_pnl) < 0.02:
        return True, False
    if trade_count >= 3 and abs(avg_pnl) >= 0.02:
        return False, True
    return False, False


def _make_memory(
    *,
    trade_date: str,
    scope: str,
    category: str,
    summary: str,
    evidence: dict[str, Any],
    recommendation: dict[str, Any],
    auto_apply_allowed: bool,
    requires_approval: bool,
    created_at: str,
    expires_at: str,
) -> dict[str, Any]:
    """Build a normalized learning memory row before persistence."""
    return {
        "memory_id": str(uuid.uuid4()),
        "trade_date": trade_date,
        "scope": scope,
        "category": category,
        "summary": summary,
        "evidence": evidence,
        "recommendation": recommendation,
        "auto_apply_allowed": int(auto_apply_allowed),
        "requires_approval": int(requires_approval),
        "status": "active",
        "expires_at": expires_at,
        "created_at": created_at,
    }


def _load_review_report(trade_date: str) -> dict[str, Any] | None:
    """Load the S10 report row that S11 depends on.

    Args:
        trade_date: YYYY-MM-DD trade date.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM daily_review_reports WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
            (trade_date,),
        ).fetchone()
    if not row:
        return None
    report = dict(row)
    report["missed_entries"] = _json_loads(report.get("missed_entries"), [])
    report["false_positives"] = _json_loads(report.get("false_positives"), [])
    return report


def _scope_from_missed_stage(missed_stage: str) -> str:
    """Map a missed-entry stage to the next-day RAG scope that can use it.

    Args:
        missed_stage: Stage label such as S3_FILTER, S4_SCREENING, or S5_PLAN.
    """
    upper = str(missed_stage or "").upper()
    if "S3" in upper:
        return "S3_UNIVERSE_FILTER"
    if "S4" in upper:
        return "S4_HYBRID_SCREENING"
    return "S5_DAILY_PLAN"


def _build_missed_entry_memory(
    *,
    trade_date: str,
    entry: dict[str, Any],
    created_at: str,
    expires_at: str,
) -> dict[str, Any]:
    """Build one operating-memory row from a missed-entry case.

    Args:
        trade_date: YYYY-MM-DD trade date.
        entry: Missed Entries row from S10 review output.
        created_at: KST timestamp for the memory row.
        expires_at: Expiration date for short-lived operational memory.
    """
    stage = str(entry.get("missed_stage") or "UNKNOWN")
    symbol = str(entry.get("symbol") or "")
    # max_return_until_eod 는 장중 최고가 상승률(의미 재정의), intraday_low_return 은 장중 최저가 상승률(리스크)
    high_return = entry.get("max_return_until_eod") or entry.get("max_return_eod") or entry.get("max_return_after_30m")
    low_return = entry.get("intraday_low_return")
    target_scope = _scope_from_missed_stage(stage)

    high_str = f"{float(high_return):+.1f}" if high_return is not None else "?"
    low_str = f"{float(low_return):+.1f}" if low_return is not None else "?"
    opinion = (
        f"필터에서 제외됐으나 장중 최고 {high_str}% (최저 {low_str}%) → "
        f"다음 거래일 {target_scope} 필터에서 거르지 말 것 검토"
    )
    return _make_memory(
        trade_date=trade_date,
        scope=target_scope,
        category="missed_entry",
        summary=(
            f"Missed entry {symbol or 'unknown'} at {stage}: "
            f"{entry.get('missed_reason') or 'reason unavailable'}. {opinion}"
        ),
        evidence={
            "symbol": symbol,
            "symbol_name": entry.get("symbol_name", ""),
            "missed_stage": stage,
            "missed_reason": entry.get("missed_reason", ""),
            "price_at_missed": entry.get("price_at_missed"),
            "max_return_until_eod": high_return,
            "intraday_low_return": low_return,
            "source": entry.get("source", "review_audit"),
        },
        recommendation={
            "action": "review_next_day_candidate_context",
            "opinion": opinion,
            "rag_usage": "참고 메모리로만 사용하며 모델 자체 학습이나 자동 룰 변경이 아님",
            "target_stage": target_scope,
        },
        auto_apply_allowed=False,
        requires_approval=False,
        created_at=created_at,
        expires_at=expires_at,
    )


def _build_false_positive_memory(
    *,
    trade_date: str,
    case: dict[str, Any],
    created_at: str,
    expires_at: str,
) -> dict[str, Any]:
    """Build one operating-memory row from a false-positive case.

    Args:
        trade_date: YYYY-MM-DD trade date.
        case: False Positive row from S10 review output.
        created_at: KST timestamp for the memory row.
        expires_at: Expiration date for short-lived operational memory.
    """
    symbol = str(case.get("symbol") or "")
    symbol_name = str(case.get("symbol_name") or symbol)
    fp_type = str(case.get("false_positive_type") or "entry_fail")
    pnl_pct = case.get("pnl_pct")
    confidence = case.get("original_confidence")
    loss_reason = str(case.get("loss_reason") or "")
    exit_reason = str(case.get("exit_reason") or "")
    profile = str(case.get("assigned_profile") or "-")

    # LLM이 읽기 쉬운 자연어 요약
    pnl_str = f"{pnl_pct:+.1f}%" if pnl_pct is not None else "손익미상"
    conf_str = f"{confidence:.2f}" if confidence is not None else "-"
    summary = (
        f"[{trade_date}] {symbol_name}({symbol}) 손실 진입 ({pnl_str}). "
        f"유형: {fp_type}, confidence: {conf_str}, 프로파일: {profile}. "
        f"손실 원인: {loss_reason[:120] if loss_reason else '미상'}."
    )

    return _make_memory(
        trade_date=trade_date,
        scope="S4_HYBRID_SCREENING",
        category="false_positive",
        summary=summary,
        evidence={
            "symbol": symbol,
            "symbol_name": symbol_name,
            "false_positive_type": fp_type,
            "pnl_pct": pnl_pct,
            "pnl_amount": case.get("pnl_amount"),
            "original_score": case.get("original_score"),
            "original_confidence": confidence,
            "assigned_profile": profile,
            "buy_price": case.get("buy_price"),
            "sell_price": case.get("sell_price"),
            "loss_reason": loss_reason,
            "exit_reason": exit_reason,
            "suggested_penalty": case.get("suggested_penalty"),
        },
        recommendation={
            "action": "penalize_similar_context_in_screening",
            "guidance": (
                f"{symbol_name}와 유사한 패턴(confidence {conf_str}, {fp_type})이 "
                f"발견되면 suitability_score를 낮게 평가한다."
            ),
            "rag_usage": "S4 스크리닝 LLM 컨텍스트 — 동일 종목 또는 유사 패턴 재진입 경계",
            "target_stage": "S4_HYBRID_SCREENING",
        },
        auto_apply_allowed=False,
        requires_approval=False,
        created_at=created_at,
        expires_at=expires_at,
    )


async def run_learning_memory_builder(trade_date: str) -> dict:
    """Convert the S10 review report into scoped S11 learning memories.

    Args:
        trade_date: YYYY-MM-DD trade date to process.
    """
    logger.info("START: [S11] Learning Memory Builder trade_date=%s", trade_date)
    report = _load_review_report(trade_date)
    if not report:
        logger.warning("WARN: [S11] no review report trade_date=%s", trade_date)
        return {"ok": False, "reason": "no_review_report"}

    now = _now_kst()
    created_at = now.isoformat()
    expires_at = (datetime.fromisoformat(f"{trade_date}T00:00:00") + timedelta(days=7)).date().isoformat()
    memories: list[dict[str, Any]] = []

    with get_connection() as conn:
        profile_rows = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM profile_performance_daily WHERE trade_date = ?",
                (trade_date,),
            ).fetchall()
        ]
        exit_rows = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM exit_reason_performance_daily WHERE trade_date = ?",
                (trade_date,),
            ).fetchall()
        ]
        trailing_row = conn.execute(
            "SELECT * FROM trailing_quality_daily WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
            (trade_date,),
        ).fetchone()
        confidence_rows = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM confidence_calibration_daily WHERE trade_date = ?",
                (trade_date,),
            ).fetchall()
        ]

    for profile in profile_rows:
        trade_count = int(profile.get("trade_count") or 0)
        win_count = int(profile.get("win_count") or 0)
        avg_pnl = float(profile.get("avg_pnl") or 0.0)
        win_rate = win_count / trade_count if trade_count else 0.0
        if win_rate < 0.4 and trade_count >= 3:
            auto_apply_allowed, requires_approval = _auto_apply_flags(trade_count, avg_pnl)
            memories.append(
                _make_memory(
                    trade_date=trade_date,
                    scope="S5_DAILY_PLAN",
                    category="profile_allocation",
                    summary=f"{profile['profile']} profile underperformed with win_rate={win_rate:.2f}.",
                    evidence={
                        "profile": profile["profile"],
                        "trade_count": trade_count,
                        "win_count": win_count,
                        "win_rate": win_rate,
                        "avg_pnl": avg_pnl,
                    },
                    recommendation={
                        "action": "limit_profile_position_count",
                        "profile": profile["profile"],
                        "next_day_max_positions": 1,
                    },
                    auto_apply_allowed=auto_apply_allowed,
                    requires_approval=requires_approval,
                    created_at=created_at,
                    expires_at=expires_at,
                )
            )

    if trailing_row:
        trailing = dict(trailing_row)
        early_exit_rate = float(trailing.get("early_exit_rate") or 0.0)
        total_trailing_exits = int(trailing.get("total_trailing_exits") or 0)
        if early_exit_rate > 0.5:
            auto_apply_allowed, requires_approval = _auto_apply_flags(
                total_trailing_exits,
                float(trailing.get("avg_recovery_rate") or 0.0),
            )
            memories.append(
                _make_memory(
                    trade_date=trade_date,
                    scope="S3_UNIVERSE_FILTER",
                    category="universe_filter",
                    summary=f"Trailing exits were early at rate={early_exit_rate:.2f}.",
                    evidence={
                        "early_exit_rate": early_exit_rate,
                        "avg_recovery_rate": float(trailing.get("avg_recovery_rate") or 0.0),
                        "total_trailing_exits": total_trailing_exits,
                    },
                    recommendation={
                        "action": "strengthen_screening_filter",
                        "reason": "early_trailing_exits",
                    },
                    auto_apply_allowed=auto_apply_allowed,
                    requires_approval=requires_approval,
                    created_at=created_at,
                    expires_at=expires_at,
                )
            )

    for entry in report.get("missed_entries", []):
        if not isinstance(entry, dict):
            continue
        memories.append(
            _build_missed_entry_memory(
                trade_date=trade_date,
                entry=entry,
                created_at=created_at,
                expires_at=expires_at,
            )
        )

    for case in report.get("false_positives", []):
        if not isinstance(case, dict):
            continue
        memories.append(
            _build_false_positive_memory(
                trade_date=trade_date,
                case=case,
                created_at=created_at,
                expires_at=expires_at,
            )
        )

    try:
        from .confidence_calibration import build_confidence_learning_recommendations

        memories.extend(build_confidence_learning_recommendations(trade_date, confidence_rows))
    except Exception as exc:
        logger.error("FAIL: [S11] confidence calibration memory build failed trade_date=%s reason=%s", trade_date, exc)

    with get_connection() as conn:
        conn.execute("DELETE FROM learning_memories WHERE trade_date = ?", (trade_date,))
        conn.executemany(
            """
            INSERT INTO learning_memories
                (memory_id, trade_date, scope, category, summary, evidence,
                 recommendation, auto_apply_allowed, requires_approval, status,
                 expires_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    memory["memory_id"],
                    memory["trade_date"],
                    memory["scope"],
                    memory["category"],
                    memory["summary"],
                    _json_dumps(memory["evidence"]),
                    _json_dumps(memory["recommendation"]),
                    memory["auto_apply_allowed"],
                    memory["requires_approval"],
                    memory["status"],
                    memory["expires_at"],
                    memory["created_at"],
                )
                for memory in memories
            ],
        )
        conn.execute(
            "UPDATE daily_review_reports SET memory_count = ? WHERE trade_date = ?",
            (len(memories), trade_date),
        )

    auto_count = sum(1 for memory in memories if memory["auto_apply_allowed"])
    approval_count = sum(1 for memory in memories if memory["requires_approval"])
    logger.info(
        "SUCCESS: [S11] Learning Memory Builder trade_date=%s memories=%d auto=%d approval=%d",
        trade_date,
        len(memories),
        auto_count,
        approval_count,
    )
    return {
        "ok": True,
        "trade_date": trade_date,
        "memory_count": len(memories),
        "auto_apply_count": auto_count,
        "approval_required_count": approval_count,
        "memories": memories,
    }


def _hydrate_memory(row: Any) -> dict[str, Any]:
    """Convert one learning_memories DB row into API-friendly JSON."""
    memory = dict(row)
    memory["evidence"] = _json_loads(memory.get("evidence"), {})
    memory["recommendation"] = _json_loads(memory.get("recommendation"), {})
    memory["auto_apply_allowed"] = bool(memory.get("auto_apply_allowed"))
    memory["requires_approval"] = bool(memory.get("requires_approval"))
    return memory


def get_today_memories(trade_date: str) -> list[dict]:
    """Return S11 memories generated for one trade date.

    Args:
        trade_date: YYYY-MM-DD trade date to fetch.
    """
    logger.info("START: [S11] get_today_memories trade_date=%s", trade_date)
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM learning_memories WHERE trade_date = ? ORDER BY created_at DESC",
            (trade_date,),
        ).fetchall()
    memories = [_hydrate_memory(row) for row in rows]
    logger.info("SUCCESS: [S11] get_today_memories trade_date=%s count=%d", trade_date, len(memories))
    return memories


def get_active_memories(scope: str | None = None, today: str | None = None) -> list[dict]:
    """Return active, non-expired learning memories, optionally scoped to a stage.

    만료(expires_at < 오늘)된 메모리는 비활성화 잡이 아직 돌지 않았더라도
    파이프라인이 소비하지 않도록 조회 시점에 제외한다.

    Args:
        scope: Optional S3/S4/S5 scope filter.
        today: KST 기준 오늘 날짜('YYYY-MM-DD'). 미지정 시 현재 KST 날짜 사용.
    """
    today = today or _now_kst().strftime("%Y-%m-%d")
    logger.info("START: [S11] get_active_memories scope=%s today=%s", scope or "all", today)
    with get_connection() as conn:
        if scope:
            rows = conn.execute(
                "SELECT * FROM learning_memories "
                "WHERE status = 'active' AND scope = ? "
                "AND (expires_at IS NULL OR expires_at >= ?) "
                "ORDER BY created_at DESC",
                (scope, today),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM learning_memories "
                "WHERE status = 'active' "
                "AND (expires_at IS NULL OR expires_at >= ?) "
                "ORDER BY created_at DESC",
                (today,),
            ).fetchall()
    memories = [_hydrate_memory(row) for row in rows]
    logger.info("SUCCESS: [S11] get_active_memories scope=%s count=%d", scope or "all", len(memories))
    return memories


def expire_stale_memories(today: str | None = None) -> int:
    """만료된(active + expires_at < 오늘) 메모리를 'expired'로 비활성화한다.

    Args:
        today: KST 기준 오늘 날짜('YYYY-MM-DD'). 미지정 시 현재 KST 날짜 사용.

    Returns:
        'expired'로 전환된 행 수.
    """
    today = today or _now_kst().strftime("%Y-%m-%d")
    logger.info("START: [S11] expire_stale_memories today=%s", today)
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE learning_memories SET status = 'expired' "
            "WHERE status = 'active' AND expires_at IS NOT NULL AND expires_at < ?",
            (today,),
        )
        expired_count = cursor.rowcount
    logger.info("SUCCESS: [S11] expire_stale_memories today=%s expired=%d", today, expired_count)
    return expired_count
