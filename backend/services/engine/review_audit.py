"""S10 Review & Audit service with deterministic DB aggregation and LLM review."""

from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection
from .order_executor import get_today_orders
from .position_integrity import create_integrity_alert_once, json_compact, summarize_order_integrity

logger = logging.getLogger("ReviewAudit")
_DOCS_DIR = Path(__file__).resolve().parents[3] / "docs"


def _now_kst_iso() -> str:
    """Return the current KST timestamp for audit rows."""
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def _json_dumps(value: Any) -> str:
    """Serialize review payloads into compact JSON text."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads(value: str | None, default: Any) -> Any:
    """Parse JSON text columns and return a stable default on malformed data."""
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _setting_value_type(value: Any) -> str:
    """Return the system_settings value_type that matches an LLM override value.

    Args:
        value: LLM-proposed setting value to persist.
    """
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    return "json"


def _build_review_context_md(result: dict[str, Any], trade_date: str) -> str:
    """LLM에게 전달할 오늘 매매 컨텍스트 MD를 조립한다.

    Args:
        result: S10 deterministic review aggregation payload.
        trade_date: YYYY-MM-DD trade date to analyze.
    """
    lines: list[str] = []

    with get_connection() as conn:
        mc = conn.execute(
            "SELECT regime, risk_level, market_data FROM morning_context WHERE trade_date=?",
            (trade_date,),
        ).fetchone()
        app = conn.execute(
            """
            SELECT set_name, set_id, regime_label, vix_value, kospi_change_pct,
                   match_reason, applied_settings
            FROM regime_set_applications
            WHERE trade_date=? AND current_flag=1
            ORDER BY applied_at DESC LIMIT 1
            """,
            (trade_date,),
        ).fetchone()

    lines.append(f"# {trade_date} 매매 복기")
    lines.append("\n## 시장 상황")
    if mc:
        mc_dict = dict(mc)
        lines.append(f"- 레짐: {mc_dict.get('regime')} / 리스크레벨: {mc_dict.get('risk_level')}")
        market_data = _json_loads(mc_dict.get("market_data"), {})
        vix = (market_data.get("vix") or {}).get("price")
        kospi = (market_data.get("kospi") or {}).get("change_pct")
        if vix:
            lines.append(f"- VIX: {vix}")
        if kospi:
            lines.append(f"- KOSPI 등락: {kospi}%")

    lines.append("\n## 선택된 레짐 SET")
    if app:
        app_dict = dict(app)
        lines.append(f"- SET: {app_dict.get('set_name')} ({app_dict.get('set_id')})")
        lines.append(f"- 레짐 라벨: {app_dict.get('regime_label')}")
        lines.append(f"- 선택 이유: {app_dict.get('match_reason', '-')}")
        settings = _json_loads(app_dict.get("applied_settings"), {})
        if settings:
            lines.append(
                "- 적용 파라미터: "
                f"max_positions={settings.get('max_positions')}, "
                f"stop_loss={settings.get('stop_loss_rate')}, "
                f"take_profit={settings.get('take_profit_rate')}"
            )

    lines.append("\n## 매매 결과")
    lines.append(f"- 총 거래: {result.get('total_trades', 0)}건")
    lines.append(f"- 승/패: {result.get('win_count', 0)}/{result.get('loss_count', 0)}")
    pnl = _safe_float(result.get("total_pnl"))
    pnl_pct = _safe_float(result.get("realized_pnl_pct"))
    lines.append(f"- 총 손익: {pnl:.0f}원 ({pnl_pct:+.2f}%)")

    profile_summary = result.get("profile_summary") or {}
    if profile_summary:
        lines.append("\n## Risk Profile별 성과")
        for profile, data in profile_summary.items():
            count = _safe_int(data.get("count"))
            win_rate = _safe_int(data.get("win")) / count * 100 if count else 0
            lines.append(f"- {profile}: {count}건, 승률 {win_rate:.0f}%, PnL {_safe_float(data.get('pnl')):+.0f}원")

    false_positives = result.get("false_positives") or []
    if false_positives:
        lines.append(f"\n## 손실 종목 ({len(false_positives)}건)")
        for fp in false_positives[:5]:
            lines.append(
                f"- {fp.get('symbol', '-')}: {_safe_float(fp.get('pnl_pct')):+.2f}% / "
                f"진입이유: {fp.get('entry_reason', '-')}"
            )

    missed = result.get("missed_entries") or []
    if missed:
        lines.append(f"\n## 걸러낸 종목 중 상승 ({len(missed)}건)")
        for item in missed[:5]:
            stage = item.get("filtered_at_stage") or item.get("missed_stage") or item.get("source") or "-"
            actual_change = item.get("actual_change_pct")
            if actual_change is None:
                actual_change = item.get("max_return_until_eod") or item.get("max_return_eod") or 0
            lines.append(f"- {item.get('symbol', '-')}: {stage} 단계 탈락, 실제 등락 {_safe_float(actual_change):+.2f}%")

    return "\n".join(lines)


def _build_review_markdown(result: dict[str, Any]) -> str:
    """Render the S10 review payload into a diary-style markdown artifact."""
    trade_date = str(result.get("trade_date") or "")
    market_tone = result.get("market_tone") or "-"
    rulepack_id = result.get("rulepack_id") or "-"
    realized_pnl = _safe_float(result.get("realized_pnl"))
    realized_pnl_pct = _safe_float(result.get("realized_pnl_pct"))
    pnl_sign = "+" if realized_pnl >= 0 else ""
    pnl_pct_sign = "+" if realized_pnl_pct >= 0 else ""

    lines: list[str] = [
        f"# 트레이딩 복기 — {trade_date}",
        "",
        "---",
        "",
        "## 📊 오늘 거래 요약",
        "",
        "| 항목 | 값 |",
        "|------|-----|",
        f"| 거래일 | {trade_date} |",
        f"| 시장 톤 | {market_tone} |",
        f"| RulePack | {rulepack_id} |",
        f"| 총 주문 | {result.get('total_orders', 0)}건 |",
        f"| 매수 / 매도 / 실패 | {result.get('buy_orders', 0)} / {result.get('sell_orders', 0)} / {result.get('failed_orders', 0)}건 |",
        f"| 실현 손익 | {pnl_sign}{realized_pnl:,.0f}원 ({pnl_pct_sign}{realized_pnl_pct:.2f}%) |",
        f"| 손익 검증 | {result.get('pnl_status', '-')} ({result.get('pnl_source', '-')}) |",
        f"| 놓친 기회 | {result.get('missed_entries_count', 0)}건 |",
        f"| 손실 거래 | {result.get('false_positive_count', 0)}건 |",
        "",
    ]

    # ── 거래 상세 ────────────────────────────────────────────────────────────
    trade_pairs = result.get("trade_pairs") or []
    lines.extend(["## 📈 거래 상세", ""])
    if trade_pairs:
        completed = [p for p in trade_pairs if p.get("status") == "매도완료"]
        in_progress = [p for p in trade_pairs if p.get("status") != "매도완료"]

        if completed:
            lines.extend(["### 완료된 거래", ""])
            lines.append("| 종목 | 매수가 | 매도가 | 수익률 | 금액 | 청산사유 |")
            lines.append("|------|--------|--------|--------|------|---------|")
            for p in completed:
                pnl_pct = p.get("pnl_pct")
                pnl_amt = p.get("pnl_amount")
                pnl_pct_str = f"{pnl_pct:+.2f}%" if pnl_pct is not None else "-"
                pnl_amt_str = f"{pnl_amt:+,.0f}원" if pnl_amt is not None else "-"
                buy_p = p.get("buy_price") or 0
                sell_p = p.get("sell_price") or 0
                lines.append(
                    f"| **{p.get('name', '')}** ({p.get('symbol', '')}) "
                    f"| {buy_p:,.0f}원 | {sell_p:,.0f}원 "
                    f"| {pnl_pct_str} | {pnl_amt_str} "
                    f"| {p.get('exit_reason', '-')} |"
                )
            lines.append("")

        if in_progress:
            lines.extend(["### 보유 중 / 매수 완료", ""])
            for p in in_progress:
                buy_p = p.get("buy_price") or 0
                lines.append(
                    f"- **{p.get('name', '')}** ({p.get('symbol', '')}) "
                    f"— 상태: {p.get('status', '-')}, 매수가: {buy_p:,.0f}원"
                )
            lines.append("")
    else:
        lines.extend(["거래 데이터 없음", ""])

    # ── 놓친 기회 ────────────────────────────────────────────────────────────
    missed = result.get("missed_entries") or []
    lines.extend(["## ❌ 놓친 기회", ""])
    if missed:
        lines.append("| 종목 | 단계 | 사유 |")
        lines.append("|------|------|------|")
        for m in missed[:15]:
            symbol = m.get("symbol") or m.get("name") or "-"
            stage = m.get("missed_stage") or m.get("source") or "-"
            reason = (m.get("reason") or m.get("missed_reason") or "-")[:80]
            lines.append(f"| {symbol} | {stage} | {reason} |")
        lines.append("")
    else:
        lines.extend(["없음 — 모든 기회를 포착했거나 아직 데이터가 없습니다.", ""])

    # ── 손실 분석 ────────────────────────────────────────────────────────────
    fp_list = result.get("false_positives") or []
    lines.extend(["## ⚠️ 손실 거래 분석 (False Positive)", ""])
    if fp_list:
        lines.append("| 종목 | 유형 | 매수가→매도가 | 손실률 | 손실 원인 |")
        lines.append("|------|------|-------------|--------|---------|")
        for fp in fp_list:
            name_str = f"{fp.get('symbol_name', '')} ({fp.get('symbol', '')})"
            fp_type = fp.get("false_positive_type", "-")
            buy_p = fp.get("buy_price")
            sell_p = fp.get("sell_price")
            price_str = f"{buy_p:,.0f}→{sell_p:,.0f}원" if buy_p and sell_p else "-"
            pnl_pct_v = fp.get("pnl_pct")
            pnl_str = f"{pnl_pct_v:+.1f}%" if pnl_pct_v is not None else "-"
            loss_r = (fp.get("loss_reason") or fp.get("exit_reason") or "-")[:60]
            lines.append(f"| {name_str} | {fp_type} | {price_str} | {pnl_str} | {loss_r} |")
        lines.append("")
    else:
        lines.extend(["없음 — 손실 거래가 없습니다.", ""])

    # ── 무결성 경고 ──────────────────────────────────────────────────────────
    warnings = result.get("integrity_warnings") or []
    if warnings:
        lines.extend(["## ⚡ 무결성 경고", ""])
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    # ── 내일 전략 방향 ───────────────────────────────────────────────────────
    exit_summary = result.get("exit_summary") or {}
    fp_count = len(fp_list)
    missed_count = len(missed)
    recommendations: list[str] = []

    if realized_pnl < 0:
        recommendations.append(f"⚠️ 오늘 손실 ({realized_pnl_pct:+.2f}%) — 내일 포지션 크기 축소 또는 매매 유보 검토")
    elif realized_pnl_pct > 5:
        recommendations.append(f"✅ 오늘 수익 ({realized_pnl_pct:+.2f}%) — 현재 전략 유지")
    else:
        recommendations.append(f"📊 손익 {realized_pnl_pct:+.2f}% — 현재 전략 유지하며 모니터링")

    if fp_count >= 2:
        recommendations.append(f"⚠️ 손실 거래 {fp_count}건 — 진입 조건 confidence 임계값 상향 또는 종목 필터 강화 검토")
    elif fp_count == 1:
        recommendations.append("📌 손실 거래 1건 — 단발 변수 가능성, 진입 조건 재확인")

    if missed_count > 3:
        recommendations.append(f"📌 놓친 기회 {missed_count}건 — S3/S4 필터 조건 일부 완화 또는 RulePack 조정 검토")
    elif missed_count > 0:
        recommendations.append(f"📌 놓친 기회 {missed_count}건 — 원인 확인 후 필요 시 조건 조정")

    eod_count = (exit_summary.get("eod") or {}).get("count", 0)
    trailing_count = (exit_summary.get("trailing_stop") or {}).get("count", 0)
    if eod_count > 0 and eod_count > trailing_count:
        recommendations.append("📌 EOD 청산 비중 높음 — 트레일링 파라미터 점검 또는 장중 청산 조건 추가 검토")

    if warnings:
        recommendations.append(f"🔴 무결성 경고 {len(warnings)}건 — 체결 검증 후 오더북 정리 필요")

    if not recommendations:
        recommendations.append("✅ 특이사항 없음 — 현재 설정 유지")

    lines.extend(["## 🔮 내일 전략 방향", ""])
    for rec in recommendations:
        lines.append(f"- {rec}")
    lines.extend(["", "---", "", "*S10 자동 생성 복기 보고서*", ""])

    return "\n".join(lines)


def _review_markdown_path(trade_date: str) -> Path:
    """Return the deterministic markdown backup path for one S10 review date."""
    return _DOCS_DIR / f"SYSTEM_AUDIT_{trade_date.replace('-', '')}.md"


def _write_review_markdown(result: dict[str, Any]) -> str:
    """Persist the S10 review report as a markdown file in docs/."""
    _DOCS_DIR.mkdir(parents=True, exist_ok=True)
    trade_date = str(result.get("trade_date") or _now_kst_iso()[:10])
    md_path = _review_markdown_path(trade_date)
    md_path.write_text(_build_review_markdown(result), encoding="utf-8")
    logger.info("SUCCESS: [S10] review markdown saved path=%s", md_path)
    return str(md_path)


def _table_columns(table_name: str) -> set[str]:
    """Read SQLite column names for defensive compatibility with older schemas."""
    with get_connection() as conn:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row["name"]) for row in rows}


def _table_exists(table_name: str) -> bool:
    """Return whether a SQLite table exists before optional review queries.

    Args:
        table_name: Table name to inspect.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
    return row is not None


def _signal_value(row: dict[str, Any], column: str, default: Any) -> Any:
    """Return a signal field only when the current trading_signals schema exposes it."""
    value = row.get(column)
    return default if value in (None, "") else value


def _safe_float(value: Any) -> float:
    """Convert numeric DB values to float while treating missing values as zero."""
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: Any) -> int:
    """Convert numeric DB values to int while treating missing values as zero."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _load_review_signals(trade_date: str) -> list[dict[str, Any]]:
    """Load reviewable trading signals for the requested trade date.

    Args:
        trade_date: YYYY-MM-DD trade date to review.
    """
    columns = _table_columns("trading_signals")
    select_columns = [
        "id",
        "trade_date",
        "symbol",
        "status",
        "created_at",
    ]
    for optional in ("realized_pnl", "risk_profile", "profile_assigned", "exit_reason", "entry_price", "trigger_price"):
        if optional in columns:
            select_columns.append(optional)

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT {", ".join(select_columns)}
            FROM trading_signals
            WHERE trade_date = ?
              AND status IN (
                  'executed', 'failed', 'preflight_blocked',
                  'filled', 'partial_fill', 'cancelled'
              )
            ORDER BY created_at ASC
            """,
            (trade_date,),
        ).fetchall()
    return [dict(row) for row in rows]


def _load_daily_plan_context(trade_date: str) -> dict[str, Any]:
    """Load daily_trading_plans + market_tone_results for rich context.

    Returns a dict with keys: daily_plan, tone_analysis.
    """
    result: dict[str, Any] = {"daily_plan": None, "tone_analysis": None}
    with get_connection() as conn:
        # daily_trading_plans
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_trading_plans'").fetchone():
            row = conn.execute(
                """SELECT trade_date, market_tone, trading_intensity, base_rulepack_id,
                          risk_profile_pack_id, new_entry_allowed, daily_overrides,
                          symbol_assignments, excluded_symbols, llm_summary,
                          status, creation_mode, activated_at
                   FROM daily_trading_plans WHERE trade_date = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (trade_date,),
            ).fetchone()
            if row:
                d = dict(row)
                for key in ("daily_overrides", "symbol_assignments", "excluded_symbols"):
                    raw = d.get(key)
                    if isinstance(raw, str):
                        try:
                            d[key] = json.loads(raw)
                        except Exception:
                            d[key] = []
                result["daily_plan"] = d

        # market_tone_results
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='market_tone_results'").fetchone():
            row = conn.execute(
                """SELECT trade_date, tone, confidence, summary, key_factors, risk_factors
                   FROM market_tone_results WHERE trade_date = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (trade_date,),
            ).fetchone()
            if row:
                d = dict(row)
                for key in ("key_factors", "risk_factors"):
                    raw = d.get(key)
                    if isinstance(raw, str):
                        try:
                            d[key] = json.loads(raw)
                        except Exception:
                            d[key] = []
                result["tone_analysis"] = d
    return result


def _load_daily_trade_summary(trade_date: str) -> dict[str, Any]:
    """Load S10 order summary values when daily_trade_summary already exists.

    Args:
        trade_date: YYYY-MM-DD trade date to load.
    """
    with get_connection() as conn:
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_trade_summary'"
        ).fetchone()
        if not table_exists:
            return {}
        row = conn.execute(
            "SELECT * FROM daily_trade_summary WHERE trade_date = ? ORDER BY updated_at DESC LIMIT 1",
            (trade_date,),
        ).fetchone()
    summary = dict(row) if row else {}
    summary["symbols_traded"] = _json_loads(summary.get("symbols_traded"), [])
    summary["integrity_warnings"] = _json_loads(summary.get("integrity_warnings"), [])
    return summary


def _ensure_review_integrity_columns() -> None:
    """Add S10 integrity columns when a DB predates the latest migration."""
    migrations = [
        ("pnl_status", "ALTER TABLE daily_review_reports ADD COLUMN pnl_status TEXT NOT NULL DEFAULT 'unverified'"),
        ("pnl_source", "ALTER TABLE daily_review_reports ADD COLUMN pnl_source TEXT NOT NULL DEFAULT 'orders_without_fills'"),
        ("integrity_warnings", "ALTER TABLE daily_review_reports ADD COLUMN integrity_warnings TEXT NOT NULL DEFAULT '[]'"),
        (
            "legacy_residual_positions",
            "ALTER TABLE daily_review_reports ADD COLUMN legacy_residual_positions TEXT NOT NULL DEFAULT '[]'",
        ),
    ]
    with get_connection() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(daily_review_reports)").fetchall()}
        for column, statement in migrations:
            if column not in columns:
                conn.execute(statement)


def _order_summary(trade_date: str) -> dict[str, Any]:
    """Summarize trading_orders for Review & Audit card compatibility.

    Args:
        trade_date: YYYY-MM-DD trade date to summarize.
    """
    orders = get_today_orders(trade_date)
    status_counts: dict[str, int] = defaultdict(int)
    for order in orders:
        status_counts[str(order.get("status") or "unknown")] += 1

    return {
        "total_orders": len(orders),
        "buy_orders": sum(1 for order in orders if order.get("side") == "buy"),
        "sell_orders": sum(1 for order in orders if order.get("side") == "sell"),
        "failed_orders": status_counts.get("failed", 0),
        "submitted_orders": status_counts.get("submitted", 0),
        "filled_orders": status_counts.get("filled", 0) + status_counts.get("partial_fill", 0),
        "order_status_counts": dict(status_counts),
        "symbols_traded": sorted({str(order.get("symbol")) for order in orders if order.get("symbol")}),
    }


def _signal_status_counts(signals: list[dict[str, Any]]) -> dict[str, int]:
    """Count review signal statuses for diagnostics and UI detail text."""
    counts: dict[str, int] = defaultdict(int)
    for signal in signals:
        counts[str(signal.get("status") or "unknown")] += 1
    return dict(counts)


def _load_missed_entries(trade_date: str) -> list[dict[str, Any]]:
    """Load Missed Entries and shadow missed-entry evidence for S10 review.

    Args:
        trade_date: YYYY-MM-DD trade date to analyze.
    """
    missed: list[dict[str, Any]] = []
    with get_connection() as conn:
        if _table_exists("missed_opportunities"):
            rows = conn.execute(
                """
                SELECT id, symbol, symbol_name, missed_stage, missed_reason,
                       price_at_missed, max_return_after_10m, max_return_after_30m,
                       max_return_until_eod, improvement_candidate, created_at
                FROM missed_opportunities
                WHERE trade_date = ?
                ORDER BY created_at DESC
                """,
                (trade_date,),
            ).fetchall()
            for row in rows:
                item = dict(row)
                item["source"] = "missed_opportunities"
                missed.append(item)
        if _table_exists("shadow_trades"):
            rows = conn.execute(
                """
                SELECT id, symbol, symbol_name, missed_stage, entry_price,
                       max_return_10m, max_return_30m, max_return_eod,
                       shadow_pnl, status, created_at
                FROM shadow_trades
                WHERE trade_date = ?
                ORDER BY created_at DESC
                """,
                (trade_date,),
            ).fetchall()
            for row in rows:
                item = dict(row)
                item["source"] = "shadow_trades"
                item["missed_reason"] = item.get("status") or "shadow_tracking"
                item["price_at_missed"] = item.get("entry_price")
                item["max_return_until_eod"] = item.get("max_return_eod")
                missed.append(item)
    return missed


def _load_false_positives(trade_date: str) -> list[dict[str, Any]]:
    """Load False Positive validation cases for S10 review.

    Args:
        trade_date: YYYY-MM-DD trade date to analyze.
    """
    if not _table_exists("false_positive_cases"):
        return []
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, symbol, symbol_name, false_positive_type, original_score,
                   original_confidence, assigned_profile, entry_reason, loss_reason,
                   exit_reason, suggested_penalty, created_at,
                   buy_price, sell_price, pnl_amount, pnl_pct
            FROM false_positive_cases
            WHERE trade_date = ?
            ORDER BY created_at DESC
            """,
            (trade_date,),
        ).fetchall()
    return [dict(row) for row in rows]


def _fallback_exit_reason(signal: dict[str, Any]) -> str:
    """Derive an actionable exit bucket when exit_reason is absent from the signal schema."""
    explicit = str(_signal_value(signal, "exit_reason", "")).strip().lower()
    if explicit:
        return explicit
    status = str(signal.get("status") or "unknown").lower()
    if status == "executed":
        return "executed_no_exit"
    if status == "failed":
        return "signal_failed"
    if status == "preflight_blocked":
        return "preflight_blocked"
    return status or "unknown"


def _replace_daily_rows(table_name: str, trade_date: str, rows: list[tuple[Any, ...]], columns: str) -> None:
    """Replace date-scoped aggregate rows in one transaction.

    Args:
        table_name: Target aggregate table name.
        trade_date: YYYY-MM-DD trade date whose rows should be replaced.
        rows: Positional values matching ``columns``.
        columns: Comma-separated target columns for the INSERT statement.
    """
    placeholders = ",".join("?" for _ in columns.split(","))
    with get_connection() as conn:
        conn.execute(f"DELETE FROM {table_name} WHERE trade_date = ?", (trade_date,))
        if rows:
            conn.executemany(
                f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})",
                rows,
            )


def _sync_realized_pnl_from_trade_pairs(trade_date: str) -> None:
    """Update BUY trading_signals realized_pnl from completed trade pair fills.

    Args:
        trade_date: YYYY-MM-DD trade date whose completed pairs should be synced.
    """
    if "realized_pnl" not in _table_columns("trading_signals"):
        logger.warning("WARN: [S10] trading_signals.realized_pnl column missing, pnl sync skipped")
        return

    try:
        from .trade_pairs import get_trade_pairs as _get_pairs
        from .technical_indicators import update_signal_outcome as _update_signal_outcome

        start_date = (datetime.fromisoformat(trade_date) - timedelta(days=7)).strftime("%Y-%m-%d")
        pairs = _get_pairs(start_date, trade_date)
        updated_count = 0
        outcome_updates: list[tuple[str, float, float]] = []
        with get_connection() as conn:
            for pair in pairs:
                if (
                    pair.get("status") != "매도완료"
                    or pair.get("trade_date") != trade_date
                    or pair.get("pnl_amount") is None
                ):
                    continue
                buy_date = _pair_buy_date(pair) or trade_date
                cursor = conn.execute(
                    """
                    UPDATE trading_signals
                    SET realized_pnl = ?
                    WHERE symbol = ?
                      AND trade_date = ?
                      AND signal_type = 'BUY'
                    """,
                    (pair["pnl_amount"], pair["symbol"], buy_date),
                )
                updated_count += cursor.rowcount
                if pair.get("pnl_pct") is None:
                    continue

                sig = conn.execute(
                    """
                    SELECT id
                    FROM trading_signals
                    WHERE symbol = ?
                      AND trade_date = ?
                      AND signal_type = 'BUY'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (pair["symbol"], buy_date),
                ).fetchone()
                if sig:
                    outcome_updates.append((sig["id"], float(pair["pnl_pct"]), _pair_hold_minutes(pair)))
        outcome_count = sum(
            1 for signal_id, pnl_pct, hold_minutes in outcome_updates
            if _update_signal_outcome(signal_id, pnl_pct, hold_minutes)
        )
        logger.info(
            "INFO: [S10] trading_signals.realized_pnl 업데이트 완료 pairs=%d updated=%d sti_outcomes=%d",
            len(pairs),
            updated_count,
            outcome_count,
        )
    except Exception as pnl_exc:
        logger.warning("WARN: [S10] trading_signals.realized_pnl 업데이트 실패 reason=%s", pnl_exc)


def _pair_buy_date(pair: dict[str, Any]) -> str | None:
    """Return the earliest buy order date from a trade pair.

    Args:
        pair: Trade pair dictionary returned by get_trade_pairs().
    """
    buy_dates = [
        str(order.get("trade_date"))
        for order in pair.get("orders", [])
        if order.get("side") == "buy" and order.get("trade_date")
    ]
    return min(buy_dates) if buy_dates else None


def _pair_hold_minutes(pair: dict[str, Any]) -> float:
    """Calculate holding minutes from the first buy order to the last sell order.

    Args:
        pair: Trade pair dictionary returned by get_trade_pairs().
    """
    buy_times: list[datetime] = []
    sell_times: list[datetime] = []
    for order in pair.get("orders", []):
        created_at = order.get("created_at")
        if not created_at:
            continue
        try:
            parsed = datetime.fromisoformat(str(created_at))
        except ValueError:
            continue
        if order.get("side") == "buy":
            buy_times.append(parsed)
        elif order.get("side") == "sell":
            sell_times.append(parsed)

    if not buy_times or not sell_times:
        return 0.0
    hold_seconds = (max(sell_times) - min(buy_times)).total_seconds()
    return round(max(hold_seconds, 0.0) / 60, 2)


async def _send_action_plan_for_approval(result: dict[str, Any]) -> None:
    """LLM으로 복기 분석 후 Settings 자동 반영 + 텔레그램 통보."""
    from ..settings_store import upsert_setting
    from .llm_router import call_llm

    trade_date = str(result.get("trade_date") or "")
    now_iso = _now_kst_iso()

    context_md = _build_review_context_md(result, trade_date)

    try:
        from .prompt_loader import load_prompt_template

        template = load_prompt_template("1600_opus_review.md", include_common_guard=False)
    except Exception:
        prompt_path = Path(__file__).resolve().parents[2] / "prompts" / "1600_opus_review.md"
        template = prompt_path.read_text(encoding="utf-8")

    prompt = template.replace("{context_md}", context_md)

    llm_result: dict[str, Any] = {"ok": False, "raw": ""}
    llm_response: dict[str, Any] = {}
    try:
        import re

        llm_result = await call_llm(prompt, task_name="s10_review")
        raw = str(llm_result.get("raw") or llm_result.get("response") or "")
        json_match = re.search(r"\{[\s\S]*\}", raw)
        if json_match:
            parsed = json.loads(json_match.group())
            if isinstance(parsed, dict):
                llm_response = parsed
        parsed_regime_eval = llm_response.get("regime_evaluation")
        parsed_eval = parsed_regime_eval.get("evaluation") if isinstance(parsed_regime_eval, dict) else None
        logger.info(
            "INFO: [S10-LLM] 복기 분석 완료 provider=%s regime_eval=%s",
            llm_result.get("provider", "none"),
            parsed_eval,
        )
    except Exception as exc:
        logger.warning("WARN: [S10-LLM] LLM 호출 실패 - fallback to empty reason=%s", exc)

    regime_eval = llm_response.get("regime_evaluation") or {}
    if not isinstance(regime_eval, dict):
        regime_eval = {}
    evaluation = str(regime_eval.get("evaluation") or "neutral")
    if evaluation not in {"good", "neutral", "bad"}:
        evaluation = "neutral"

    try:
        with get_connection() as conn:
            table_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='regime_set_feedback'"
            ).fetchone()
            if table_exists:
                app_row = conn.execute(
                    """
                    SELECT set_id, regime_label, vix_value, kospi_change_pct
                    FROM regime_set_applications
                    WHERE trade_date=? AND current_flag=1
                    ORDER BY applied_at DESC LIMIT 1
                    """,
                    (trade_date,),
                ).fetchone()
                if app_row:
                    app = dict(app_row)
                    total = _safe_int(result.get("total_trades"))
                    win = _safe_int(result.get("win_count"))
                    win_rate = win / total if total else 0.0
                    conn.execute(
                        """
                        INSERT INTO regime_set_feedback
                            (id, trade_date, set_id, regime_label, vix_value, kospi_change_pct,
                             win_rate, total_pnl, trades_count, evaluation, reason, next_action, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(uuid.uuid4()),
                            trade_date,
                            app["set_id"],
                            app["regime_label"],
                            app.get("vix_value"),
                            app.get("kospi_change_pct"),
                            win_rate,
                            _safe_float(result.get("total_pnl")),
                            total,
                            evaluation,
                            regime_eval.get("reason", ""),
                            regime_eval.get("next_regime_hint", "same"),
                            now_iso,
                        ),
                    )
                    logger.info("INFO: [S10-LLM] regime_set_feedback saved trade_date=%s eval=%s", trade_date, evaluation)
    except Exception as exc:
        logger.warning("WARN: [S10-LLM] regime_set_feedback 저장 실패 reason=%s", exc)

    settings_overrides = llm_response.get("settings_overrides") or {}
    if not isinstance(settings_overrides, dict):
        settings_overrides = {}
    settings_reasoning = llm_response.get("settings_reasoning") or {}
    if not isinstance(settings_reasoning, dict):
        settings_reasoning = {}

    applied_settings: list[str] = []
    for key, new_val in settings_overrides.items():
        reason = str(settings_reasoning.get(key) or "S10 LLM 자동 반영")
        try:
            upsert_setting(
                key=str(key),
                value=new_val,
                value_type=_setting_value_type(new_val),
                description=reason,
                actor="s10_llm",
            )
            applied_settings.append(f"{key} -> {new_val} ({reason})")
            logger.info("INFO: [S10-LLM] setting applied key=%s value=%s", key, new_val)
        except Exception as exc:
            logger.warning("WARN: [S10-LLM] setting apply failed key=%s reason=%s", key, exc)

    narrative = str(llm_response.get("narrative") or "")
    payload_json = json.dumps(
        {
            "trade_date": trade_date,
            "regime_evaluation": regime_eval,
            "settings_overrides": settings_overrides,
            "applied_settings": applied_settings,
            "narrative": narrative,
            "llm_confidence": llm_response.get("confidence", 0),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )

    with get_connection() as conn:
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='human_approval_queue'"
        ).fetchone()
        if table_exists:
            conn.execute(
                """
                INSERT INTO human_approval_queue
                    (id, change_type, title, description, payload_json, status, created_at)
                VALUES (?, 'next_day_action_plan', ?, ?, ?, 'auto_applied', ?)
                """,
                (
                    str(uuid.uuid4()),
                    f"[{trade_date}] 다음 거래일 액션 플랜",
                    narrative[:200] if narrative else "LLM 복기 완료",
                    payload_json,
                    now_iso,
                ),
            )

    result["llm_review"] = {
        "narrative": narrative,
        "regime_evaluation": regime_eval,
        "settings_overrides": settings_overrides,
        "applied_settings": applied_settings,
        "patterns": llm_response.get("patterns") if isinstance(llm_response.get("patterns"), dict) else {},
        "applied_at": now_iso,
    }

    try:
        from ..alert_service import send_telegram_alert

        pnl_pct = _safe_float(result.get("realized_pnl_pct"))
        sign = "+" if pnl_pct >= 0 else ""
        body = f"손익: {sign}{pnl_pct:.2f}% | 레짐 평가: {evaluation}\n"
        if applied_settings:
            body += "설정 자동 반영:\n" + "\n".join(f"  - {item}" for item in applied_settings[:3])
        else:
            body += "설정 변경 없음"
        await send_telegram_alert(f"매매봇 S10 복기 완료 [{trade_date}]", body)
    except Exception as exc:
        logger.warning("WARN: [S10-LLM] 텔레그램 통보 실패 reason=%s", exc)


async def run_review_audit(trade_date: str) -> dict[str, Any]:
    """Run S10 daily review aggregation and persist the report.

    Args:
        trade_date: YYYY-MM-DD trade date to analyze.
    """
    logger.info(
        "START: [S10] deterministic Review & Audit trade_date=%s prompt_template=1600_opus_review.md",
        trade_date,
    )
    _ensure_review_integrity_columns()
    now_iso = _now_kst_iso()
    _sync_realized_pnl_from_trade_pairs(trade_date)
    signals = _load_review_signals(trade_date)
    orders = _order_summary(trade_date)
    integrity = summarize_order_integrity(trade_date)
    missed_entries = _load_missed_entries(trade_date)
    false_positives = _load_false_positives(trade_date)
    status_counts = _signal_status_counts(signals)
    if integrity.get("pnl_status") == "unverified":
        create_integrity_alert_once(
            trade_date,
            alert_type="fill_missing",
            severity="WARNING",
            title="체결/손익 검증 미완료",
            detail=json_compact(
                {
                    "pnl_source": integrity.get("pnl_source"),
                    "submitted_only_orders": integrity.get("submitted_only_orders"),
                    "pending_buy_orders": integrity.get("pending_buy_orders", []),
                    "submitted_without_order_no": integrity.get("submitted_without_order_no"),
                    "incomplete_fill_orders": integrity.get("incomplete_fill_orders", []),
                    "net_negative_positions": integrity.get("net_negative_positions", []),
                    "duplicate_sell_orders": integrity.get("duplicate_sell_orders", []),
                    "sell_qty_exceeds_buy_qty": integrity.get("sell_qty_exceeds_buy_qty", []),
                    "warnings": integrity.get("warnings", []),
                }
            ),
        )
    if (
        integrity.get("net_negative_positions")
        or integrity.get("duplicate_sell_orders")
        or integrity.get("sell_qty_exceeds_buy_qty")
    ):
        create_integrity_alert_once(
            trade_date,
            alert_type="risk_guard",
            severity="WARNING",
            title="중복 매도/순매도 이상 감지",
            detail=json_compact(
                {
                    "net_negative_positions": integrity.get("net_negative_positions", []),
                    "duplicate_sell_orders": integrity.get("duplicate_sell_orders", []),
                    "sell_qty_exceeds_buy_qty": integrity.get("sell_qty_exceeds_buy_qty", []),
                    "warnings": integrity.get("warnings", []),
                }
            ),
        )

    total_trades = len(signals)
    total_pnl = 0.0
    win_count = 0
    loss_count = 0
    profile_bucket: dict[str, dict[str, float]] = defaultdict(
        lambda: {"count": 0, "win": 0, "pnl": 0.0, "executed": 0, "failed": 0, "preflight_blocked": 0}
    )
    exit_bucket: dict[str, dict[str, float]] = defaultdict(lambda: {"count": 0, "pnl": 0.0})
    trailing_recovery_rates: list[float] = []
    early_trailing_count = 0

    for signal in signals:
        pnl = _safe_float(signal.get("realized_pnl"))
        total_pnl += pnl
        if pnl > 0:
            win_count += 1
        else:
            loss_count += 1

        profile = str(
            _signal_value(signal, "risk_profile", _signal_value(signal, "profile_assigned", "UNKNOWN"))
        )
        profile_bucket[profile]["count"] += 1
        profile_bucket[profile]["pnl"] += pnl
        status = str(signal.get("status") or "").lower()
        if status in profile_bucket[profile]:
            profile_bucket[profile][status] += 1
        if pnl > 0:
            profile_bucket[profile]["win"] += 1

        exit_reason = _fallback_exit_reason(signal)
        exit_bucket[exit_reason]["count"] += 1
        exit_bucket[exit_reason]["pnl"] += pnl

        if exit_reason == "trailing_stop":
            entry_price = _safe_float(_signal_value(signal, "entry_price", _signal_value(signal, "trigger_price", 0.0)))
            recovery_rate = (pnl / entry_price * 100.0) if entry_price > 0 else 0.0
            trailing_recovery_rates.append(recovery_rate)
            if recovery_rate < 0.5:
                early_trailing_count += 1

    profile_summary = {
        profile: {
            "count": int(data["count"]),
            "win": int(data["win"]),
            "pnl": data["pnl"],
            "executed_count": int(data["executed"]),
            "failed_count": int(data["failed"]),
            "preflight_blocked_count": int(data["preflight_blocked"]),
        }
        for profile, data in profile_bucket.items()
    }
    exit_summary = {
        reason: {
            "count": int(data["count"]),
            "avg_pnl": data["pnl"] / data["count"] if data["count"] else 0.0,
        }
        for reason, data in exit_bucket.items()
    }
    trailing_quality = {
        "avg_recovery_rate": sum(trailing_recovery_rates) / len(trailing_recovery_rates)
        if trailing_recovery_rates
        else 0.0,
        "early_exit_rate": early_trailing_count / len(trailing_recovery_rates)
        if trailing_recovery_rates
        else 0.0,
    }

    profile_rows = [
        (
            str(uuid.uuid4()),
            trade_date,
            profile,
            int(data["count"]),
            int(data["win"]),
            data["pnl"],
            data["pnl"] / data["count"] if data["count"] else 0.0,
            now_iso,
        )
        for profile, data in profile_bucket.items()
    ]
    _replace_daily_rows(
        "profile_performance_daily",
        trade_date,
        profile_rows,
        "id,trade_date,profile,trade_count,win_count,total_pnl,avg_pnl,created_at",
    )

    exit_rows = [
        (
            str(uuid.uuid4()),
            trade_date,
            reason,
            int(data["count"]),
            data["pnl"] / data["count"] if data["count"] else 0.0,
            now_iso,
        )
        for reason, data in exit_bucket.items()
    ]
    _replace_daily_rows(
        "exit_reason_performance_daily",
        trade_date,
        exit_rows,
        "id,trade_date,exit_reason,trade_count,avg_pnl,created_at",
    )

    _replace_daily_rows(
        "trailing_quality_daily",
        trade_date,
        [
            (
                str(uuid.uuid4()),
                trade_date,
                trailing_quality["avg_recovery_rate"],
                trailing_quality["early_exit_rate"],
                len(trailing_recovery_rates),
                now_iso,
            )
        ],
        "id,trade_date,avg_recovery_rate,early_exit_rate,total_trailing_exits,created_at",
    )

    no_trade_count = 1 if total_trades == 0 else 0
    with get_connection() as conn:
        conn.execute("DELETE FROM no_trade_daily_reasons WHERE trade_date = ?", (trade_date,))
        if no_trade_count:
            conn.execute(
                """
                INSERT INTO no_trade_daily_reasons (id, trade_date, reason, detail, created_at)
                VALUES (?, ?, 'no_candidates', ?, ?)
                """,
                (str(uuid.uuid4()), trade_date, "S10 review found no completed trading signals.", now_iso),
            )
        conn.execute("DELETE FROM daily_review_reports WHERE trade_date = ?", (trade_date,))
        conn.execute(
            """
            INSERT INTO daily_review_reports
                (id, trade_date, total_trades, win_count, loss_count, total_pnl,
                 profile_summary, exit_summary, trailing_quality, missed_entries,
                 false_positives, missed_entries_count, false_positive_count,
                 no_trade_count, memory_count, pnl_status, pnl_source, integrity_warnings,
                 legacy_residual_positions, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                trade_date,
                total_trades,
                win_count,
                loss_count,
                total_pnl,
                _json_dumps(profile_summary),
                _json_dumps(exit_summary),
                _json_dumps(trailing_quality),
                _json_dumps(missed_entries),
                _json_dumps(false_positives),
                len(missed_entries),
                len(false_positives),
                no_trade_count,
                integrity.get("pnl_status", "unverified"),
                integrity.get("pnl_source", "orders_without_fills"),
                json_compact(integrity.get("warnings", [])),
                json_compact(integrity.get("legacy_residual_positions", [])),
                now_iso,
            ),
        )

    # 시장 톤 · RulePack — 마크다운 포함을 위해 미리 로드
    daily_summary = _load_daily_trade_summary(trade_date)

    # trade_pairs — 완료/진행 중 거래 상세 (마크다운 + 화면 표시용)
    trade_pairs: list[dict[str, Any]] = []
    try:
        from .trade_pairs import get_trade_pairs as _get_pairs
        from datetime import timedelta

        _dt = datetime.fromisoformat(trade_date)
        _start = (_dt - timedelta(days=7)).strftime("%Y-%m-%d")
        _all_pairs = _get_pairs(_start, trade_date)
        trade_pairs = [
            p for p in _all_pairs
            if p.get("trade_date") == trade_date
            or any(o.get("trade_date") == trade_date for o in p.get("orders", []))
        ]
    except Exception as _tp_exc:
        logger.warning("WARN: [S10] trade_pairs load failed reason=%s", _tp_exc)

    result = {
        "ok": True,
        "trade_date": trade_date,
        "total_trades": total_trades,
        "total_orders": orders["total_orders"],
        "buy_orders": orders["buy_orders"],
        "sell_orders": orders["sell_orders"],
        "failed_orders": orders["failed_orders"],
        "submitted_orders": orders["submitted_orders"],
        "filled_orders": orders["filled_orders"],
        "order_status_counts": orders["order_status_counts"],
        "signal_status_counts": status_counts,
        "win_count": win_count,
        "loss_count": loss_count,
        "total_pnl": total_pnl,
        "realized_pnl": _safe_float(daily_summary.get("realized_pnl") or total_pnl),
        "realized_pnl_pct": _safe_float(daily_summary.get("realized_pnl_pct")),
        "pnl_status": integrity.get("pnl_status", "unverified"),
        "pnl_source": integrity.get("pnl_source", "orders_without_fills"),
        "integrity_warnings": integrity.get("warnings", []),
        "pending_buy_orders": integrity.get("pending_buy_orders", []),
        "incomplete_fill_orders": integrity.get("incomplete_fill_orders", []),
        "net_negative_positions": integrity.get("net_negative_positions", []),
        "duplicate_sell_orders": integrity.get("duplicate_sell_orders", []),
        "sell_qty_exceeds_buy_qty": integrity.get("sell_qty_exceeds_buy_qty", []),
        "legacy_residual_positions": integrity.get("legacy_residual_positions", []),
        "profile_summary": profile_summary,
        "exit_summary": exit_summary,
        "trailing_quality": trailing_quality,
        "missed_entries": missed_entries,
        "false_positives": false_positives,
        "missed_entries_count": len(missed_entries),
        "false_positive_count": len(false_positives),
        "no_trade_count": no_trade_count,
        "market_tone": daily_summary.get("market_tone", ""),
        "rulepack_id": daily_summary.get("rulepack_id", ""),
        "trade_pairs": trade_pairs,
        "llm_review": {},
        **_load_daily_plan_context(trade_date),
    }
    logger.info(
        "SUCCESS: [S10] Review & Audit trade_date=%s trades=%d orders=%d missed=%d fp=%d pnl=%.4f pnl_status=%s",
        trade_date,
        total_trades,
        orders["total_orders"],
        len(missed_entries),
        len(false_positives),
        total_pnl,
        integrity.get("pnl_status"),
    )
    result["md_path"] = _write_review_markdown(result)
    # 액션 플랜 승인 요청 전송 (비동기, 실패해도 리뷰 결과에 영향 없음)
    try:
        await _send_action_plan_for_approval(result)
    except Exception as _ap_exc:
        logger.warning("WARN: [S10] action plan approval send failed reason=%s", _ap_exc)
    return result


def get_review_report(trade_date: str) -> dict[str, Any] | None:
    """Return the persisted S10 review report for a trade date.

    Args:
        trade_date: YYYY-MM-DD trade date to fetch.
    """
    logger.info("START: [S10] get_review_report trade_date=%s", trade_date)
    with get_connection() as conn:
        report = conn.execute(
            "SELECT * FROM daily_review_reports WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
            (trade_date,),
        ).fetchone()
        if not report:
            logger.info("INFO: [S10] report not found trade_date=%s", trade_date)
            return None

        profile_rows = conn.execute(
            "SELECT * FROM profile_performance_daily WHERE trade_date = ? ORDER BY profile ASC",
            (trade_date,),
        ).fetchall()
        exit_rows = conn.execute(
            "SELECT * FROM exit_reason_performance_daily WHERE trade_date = ? ORDER BY exit_reason ASC",
            (trade_date,),
        ).fetchall()
        trailing_row = conn.execute(
            "SELECT * FROM trailing_quality_daily WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
            (trade_date,),
        ).fetchone()

    payload = dict(report)
    daily_summary = _load_daily_trade_summary(trade_date)
    orders = _order_summary(trade_date)
    payload["profile_summary"] = _json_loads(payload.get("profile_summary"), {})
    payload["exit_summary"] = _json_loads(payload.get("exit_summary"), {})
    payload["trailing_quality"] = _json_loads(payload.get("trailing_quality"), {})
    payload["missed_entries"] = _json_loads(payload.get("missed_entries"), [])
    payload["false_positives"] = _json_loads(payload.get("false_positives"), [])
    payload["integrity_warnings"] = _json_loads(payload.get("integrity_warnings"), [])
    payload["legacy_residual_positions"] = _json_loads(payload.get("legacy_residual_positions"), [])
    payload["total_orders"] = _safe_int(daily_summary.get("total_orders") or orders.get("total_orders"))
    payload["buy_orders"] = _safe_int(daily_summary.get("buy_orders") or orders.get("buy_orders"))
    payload["sell_orders"] = _safe_int(daily_summary.get("sell_orders") or orders.get("sell_orders"))
    payload["failed_orders"] = _safe_int(daily_summary.get("failed_orders") or orders.get("failed_orders"))
    payload["submitted_orders"] = _safe_int(orders.get("submitted_orders"))
    payload["filled_orders"] = _safe_int(orders.get("filled_orders"))
    payload["order_status_counts"] = orders.get("order_status_counts", {})
    payload["signal_status_counts"] = _signal_status_counts(_load_review_signals(trade_date))
    md_path = _review_markdown_path(trade_date)
    payload["md_path"] = str(md_path)
    payload["md_backup_exists"] = md_path.exists()
    payload["review_source"] = "daily_review_reports"
    payload["md_backup_source"] = "docs/SYSTEM_AUDIT_YYYYMMDD.md"
    payload["realized_pnl"] = _safe_float(daily_summary.get("realized_pnl") or payload.get("total_pnl"))
    payload["realized_pnl_pct"] = _safe_float(daily_summary.get("realized_pnl_pct"))
    payload["pnl_status"] = daily_summary.get("pnl_status") or payload.get("pnl_status") or "unverified"
    payload["pnl_source"] = daily_summary.get("pnl_source") or payload.get("pnl_source") or "orders_without_fills"
    if daily_summary.get("integrity_warnings"):
        payload["integrity_warnings"] = daily_summary.get("integrity_warnings")
    payload["symbols_traded"] = daily_summary.get("symbols_traded") or orders.get("symbols_traded", [])
    payload["market_tone"] = daily_summary.get("market_tone", "")
    payload["rulepack_id"] = daily_summary.get("rulepack_id", "")
    ctx = _load_daily_plan_context(trade_date)
    payload["daily_plan"] = ctx.get("daily_plan")
    payload["tone_analysis"] = ctx.get("tone_analysis")

    with get_connection() as conn:
        queue_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='human_approval_queue'"
        ).fetchone()
        aq_row = None
        if queue_exists:
            aq_row = conn.execute(
                """
                SELECT payload_json, created_at FROM human_approval_queue
                WHERE change_type='next_day_action_plan' AND title LIKE ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (f"[{trade_date}]%",),
            ).fetchone()
    if aq_row:
        aq_dict = dict(aq_row)
        llm_payload = _json_loads(aq_dict.get("payload_json"), {})
        if not isinstance(llm_payload, dict):
            llm_payload = {}
        payload["llm_review"] = {
            "narrative": llm_payload.get("narrative", ""),
            "regime_evaluation": llm_payload.get("regime_evaluation", {}),
            "settings_overrides": llm_payload.get("settings_overrides", {}),
            "applied_settings": llm_payload.get("applied_settings", []),
            "applied_at": aq_dict.get("created_at", ""),
            "patterns": llm_payload.get("patterns", {}),
            # 구형식 fallback — LLM 미실행 시 rules-based recommendations 표시용
            "recommendations": llm_payload.get("recommendations", []),
        }
    else:
        payload["llm_review"] = {}

    payload["profile_performance"] = []
    for row in profile_rows:
        profile_row = dict(row)
        profile_stats = payload["profile_summary"].get(str(profile_row.get("profile")), {})
        payload["profile_performance"].append(
            {
                **profile_row,
                "total_orders": _safe_int(profile_row.get("trade_count")),
                "filled_orders": _safe_int(profile_stats.get("executed_count")),
                "failed_orders": _safe_int(profile_stats.get("failed_count")),
                "preflight_blocked_orders": _safe_int(profile_stats.get("preflight_blocked_count")),
                "avg_pnl_pct": _safe_float(profile_row.get("avg_pnl")),
            }
        )
    payload["exit_reason_performance"] = [
        {
            **dict(row),
            "count": _safe_int(dict(row).get("trade_count")),
            "avg_pnl_pct": _safe_float(dict(row).get("avg_pnl")),
        }
        for row in exit_rows
    ]
    payload["trailing_quality_daily"] = dict(trailing_row) if trailing_row else None

    # trade_pairs — 화면 표시용 (조회 시점에 최신 fill 상태 반영)
    try:
        from .trade_pairs import get_trade_pairs as _get_pairs
        from datetime import timedelta

        _dt = datetime.fromisoformat(trade_date)
        _start = (_dt - timedelta(days=7)).strftime("%Y-%m-%d")
        _all_pairs = _get_pairs(_start, trade_date)
        payload["trade_pairs"] = [
            p for p in _all_pairs
            if p.get("trade_date") == trade_date
            or any(o.get("trade_date") == trade_date for o in p.get("orders", []))
        ]
    except Exception as _tp_exc:
        logger.warning("WARN: [S10] get_review_report trade_pairs load failed reason=%s", _tp_exc)
        payload["trade_pairs"] = []

    logger.info("SUCCESS: [S10] get_review_report trade_date=%s", trade_date)
    return payload


def apply_next_day_overrides(trade_date: str, overrides: dict[str, Any]) -> dict[str, Any]:
    """다음 거래일 daily_trading_plans.daily_overrides에 파라미터 추천값을 1회성으로 저장한다.

    trade_date가 존재하면 UPDATE, 없으면 빈 플랜 레코드를 INSERT 후 저장한다.

    Args:
        trade_date: 적용 대상 거래일 YYYY-MM-DD (다음 거래일).
        overrides: {param_key: value} 딕셔너리.

    Returns:
        {"applied": True, "trade_date": trade_date, "overrides": overrides}
    """
    logger.info("START: apply_next_day_overrides trade_date=%s overrides=%s", trade_date, overrides)
    overrides_json = json.dumps(overrides, ensure_ascii=False, separators=(",", ":"))
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id, daily_overrides FROM daily_trading_plans WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
            (trade_date,),
        ).fetchone()
        if existing:
            # 기존 override와 머지
            existing_overrides = _json_loads(existing["daily_overrides"], {})
            existing_overrides.update(overrides)
            merged_json = json.dumps(existing_overrides, ensure_ascii=False, separators=(",", ":"))
            conn.execute(
                "UPDATE daily_trading_plans SET daily_overrides = ? WHERE id = ?",
                (merged_json, existing["id"]),
            )
            logger.info("INFO: apply_next_day_overrides UPDATE id=%s trade_date=%s", existing["id"], trade_date)
        else:
            # 새 플랜 레코드 생성 (override 전용 최소 레코드)
            plan_id = str(uuid.uuid4())
            conn.execute(
                """INSERT INTO daily_trading_plans
                   (id, trade_date, status, daily_overrides, created_at)
                   VALUES (?, ?, 'override_pending', ?, ?)""",
                (plan_id, trade_date, overrides_json, _now_kst_iso()),
            )
            logger.info("INFO: apply_next_day_overrides INSERT id=%s trade_date=%s", plan_id, trade_date)
        conn.commit()
    logger.info("SUCCESS: apply_next_day_overrides trade_date=%s", trade_date)
    return {"applied": True, "trade_date": trade_date, "overrides": overrides}
