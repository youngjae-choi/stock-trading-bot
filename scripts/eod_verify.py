#!/usr/bin/env python3
"""EOD 자동 검증 스크립트.

매 거래일 18:30 KST 실행. EOD_CHECKLIST.md의 각 항목을 SQL/명령으로 검증하고
docs/eod-reports/{YYYY-MM-DD}_eod_report.md 에 결과 기록.

종료 코드:
  0 = 정상 실행 (PASS 여부 무관)
  2 = 자동 종료 기간 (2026-05-31 이후) → 5일 자율 운영 완료
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "stock_trading_bot.sqlite3"
REPORTS_DIR = ROOT / "docs" / "eod-reports"
LOG_PATH = ROOT / "logs" / "server.log"

KST = ZoneInfo("Asia/Seoul")
AUTO_RUN_DEADLINE = date(2026, 5, 31)  # 5/27~5/31 (5일)


def kst_now() -> datetime:
    return datetime.now(KST)


def kst_today() -> str:
    return kst_now().strftime("%Y-%m-%d")


def is_trading_day(today: str) -> tuple[bool, str]:
    """schedule_skip_today + 요일 기반 거래일 판단."""
    wd = datetime.strptime(today, "%Y-%m-%d").weekday()  # 0=Mon
    if wd >= 5:
        return False, f"weekend (wd={wd})"
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT value_json FROM system_settings WHERE key='schedule_skip_today'"
            ).fetchone()
        if row:
            v = json.loads(row["value_json"])
            if v is True or str(v).lower() == "true":
                return False, "schedule_skip_today=true"
    except Exception as exc:
        return True, f"skip_today_check_failed: {exc}"
    return True, "weekday + skip_today=false"


def q(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    cur = conn.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def fmt_row(r: dict) -> str:
    return "  " + " ".join(f"{k}={v}" for k, v in r.items())


class Result:
    """체크 항목 결과."""

    def __init__(
        self,
        code: str,
        title: str,
        priority: str,
        status: str,
        details: str,
        evidence: list[dict] | None = None,
    ):
        self.code = code
        self.title = title
        self.priority = priority  # Critical | High | Medium | Low
        self.status = status  # PASS | FAIL | WARN | SKIP | INFO
        self.details = details
        self.evidence = evidence or []

    def to_md(self) -> str:
        emoji = {
            "PASS": "✅",
            "FAIL": "❌",
            "WARN": "⚠️",
            "SKIP": "⏭️",
            "INFO": "ℹ️",
        }[self.status]
        prio_emoji = {"Critical": "🔴", "High": "🟠", "Medium": "🟡", "Low": "🟢"}.get(
            self.priority, ""
        )
        lines = [f"### {emoji} {self.code} {prio_emoji} {self.title} — {self.status}"]
        if self.details:
            lines.append(f"- **결과**: {self.details}")
        if self.evidence:
            lines.append("- **증거**:")
            for r in self.evidence[:10]:
                lines.append(f"  - `{r}`")
            if len(self.evidence) > 10:
                lines.append(f"  - ... ({len(self.evidence) - 10}건 생략)")
        lines.append("")
        return "\n".join(lines)


def check_a1_server_alive() -> Result:
    """A1. 서버 살아있음."""
    try:
        ps = subprocess.run(
            ["pgrep", "-f", "uvicorn backend.main"], capture_output=True, text=True
        )
        pids = [p for p in ps.stdout.strip().split("\n") if p]
        health = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://127.0.0.1:8000/health"],
            capture_output=True, text=True, timeout=5,
        )
        ok = bool(pids) and health.stdout.strip() == "200"
        return Result(
            "A1", "서버 프로세스 + health", "Critical",
            "PASS" if ok else "FAIL",
            f"pids={pids}, health={health.stdout.strip()}",
        )
    except Exception as exc:
        return Result("A1", "서버 프로세스 + health", "Critical", "FAIL", f"check_error: {exc}")


def check_a2_server_start_time() -> Result:
    """A2. 서버 시작 시간 vs 최근 scheduler 커밋."""
    try:
        ps = subprocess.run(
            ["sh", "-c", "ps -o lstart= -p $(pgrep -f 'uvicorn backend.main' | head -1) 2>/dev/null"],
            capture_output=True, text=True,
        )
        server_start = ps.stdout.strip()
        commit = subprocess.run(
            ["git", "log", "-1", "--format=%cI", "backend/services/scheduler.py"],
            capture_output=True, text=True, cwd=ROOT,
        )
        return Result(
            "A2", "서버 시작 시간 vs 코드 커밋", "Critical",
            "INFO",
            f"server_started={server_start} | scheduler.py last_commit={commit.stdout.strip()}",
        )
    except Exception as exc:
        return Result("A2", "서버 시작 시간 vs 코드 커밋", "Critical", "FAIL", f"check_error: {exc}")


def check_a3_scheduler_jobs() -> Result:
    """A3. APScheduler 등록 job 수 — 로그 기반 검증."""
    try:
        # scheduler 시작 로그에서 등록된 job 카운트 추출
        result = subprocess.run(
            ["sh", "-c", f"grep -E 'add_job|scheduler.*started|Job .* registered' {LOG_PATH} | tail -50"],
            capture_output=True, text=True, timeout=10,
        )
        # APScheduler 실행 흔적 (job_xxx 실행 로그)
        exec_count = subprocess.run(
            ["sh", "-c", f"grep -c 'START: \\[Job\\|START: \\[PostProcess\\|START: \\[IntradayRefresh' {LOG_PATH} || true"],
            capture_output=True, text=True, timeout=10,
        )
        n_exec = int(exec_count.stdout.strip() or 0)
        return Result(
            "A3", "APScheduler 등록 job", "High",
            "PASS" if n_exec >= 1 else "WARN",
            f"recent_job_executions={n_exec}",
        )
    except Exception as exc:
        return Result("A3", "APScheduler 등록 job", "High", "FAIL", f"check_error: {exc}")


def check_b1_s2_morning(conn, today: str) -> Result:
    rows = q(conn,
        "SELECT trade_date, tone, confidence, summary, provider, created_at "
        "FROM market_tone_results WHERE trade_date=? ORDER BY created_at ASC LIMIT 1",
        (today,),
    )
    if not rows:
        return Result("B1", "S2 아침 실행", "Critical", "FAIL", "no row")
    r = rows[0]
    ok = r["tone"] in ("positive", "neutral", "negative", "mixed") and float(r["confidence"] or 0) >= 0.3
    return Result(
        "B1", "S2 아침 실행", "Critical",
        "PASS" if ok else "WARN",
        f"tone={r['tone']}, conf={r['confidence']}, provider={r['provider']}",
        rows,
    )


def check_b2_morning_data_keys(conn, today: str) -> Result:
    rows = q(conn,
        "SELECT market_data FROM morning_context WHERE trade_date=? "
        "ORDER BY created_at ASC LIMIT 1",
        (today,),
    )
    if not rows:
        return Result("B2", "야간 데이터 핵심 키", "High", "FAIL", "no morning_context")
    try:
        md = json.loads(rows[0]["market_data"])
        required = {"sp500", "nasdaq", "vix", "usdkrw", "kospi"}
        missing = required - set(md.keys())
        return Result(
            "B2", "야간 데이터 핵심 키", "High",
            "PASS" if not missing else "WARN",
            f"missing={sorted(missing)}, present={sorted(set(md.keys()) & required)}",
        )
    except Exception as exc:
        return Result("B2", "야간 데이터 핵심 키", "High", "FAIL", str(exc))


def check_c1_schedule_skip(conn) -> Result:
    rows = q(conn, "SELECT value_json FROM system_settings WHERE key='schedule_skip_today'")
    if not rows:
        return Result("C1", "schedule_skip_today", "Critical", "WARN", "not set")
    return Result("C1", "schedule_skip_today", "Critical", "INFO", f"value={rows[0]['value_json']}")


def check_c2_universe(conn, today: str) -> Result:
    rows = q(conn,
        "SELECT trade_date, raw_count, filtered_count, created_at "
        "FROM universe_filter_results WHERE trade_date=? ORDER BY created_at DESC LIMIT 1",
        (today,),
    )
    if not rows:
        return Result("C2", "S3 Universe Filter", "Critical", "FAIL", "no row")
    r = rows[0]
    ok = int(r["filtered_count"] or 0) >= 20
    return Result("C2", "S3 Universe Filter", "Critical",
        "PASS" if ok else "WARN",
        f"raw={r['raw_count']}, filtered={r['filtered_count']}",
        rows,
    )


def check_c3_screening(conn, today: str) -> Result:
    rows = q(conn,
        "SELECT trade_date, output_count, overall_confidence, provider, created_at "
        "FROM hybrid_screening_results WHERE trade_date=? ORDER BY created_at DESC LIMIT 1",
        (today,),
    )
    if not rows:
        return Result("C3", "S4 Hybrid Screening", "Critical", "FAIL", "no row")
    r = rows[0]
    ok = int(r["output_count"] or 0) >= 5 and float(r["overall_confidence"] or 0) >= 0.4
    return Result("C3", "S4 Hybrid Screening", "Critical",
        "PASS" if ok else "WARN",
        f"output={r['output_count']}, conf={r['overall_confidence']}, provider={r['provider']}",
        rows,
    )


def check_c4_daily_plan(conn, today: str) -> Result:
    rows = q(conn,
        "SELECT trade_date, market_tone, trading_intensity, "
        "  json_array_length(symbol_assignments) as assignments, "
        "  new_entry_allowed, created_at "
        "FROM daily_trading_plans WHERE trade_date=? ORDER BY created_at DESC LIMIT 1",
        (today,),
    )
    if not rows:
        return Result("C4", "S5 Daily Plan", "Critical", "FAIL", "no row")
    r = rows[0]
    ok = int(r["assignments"] or 0) >= 5 and r["trading_intensity"] in ("aggressive", "normal", "defensive")
    return Result("C4", "S5 Daily Plan", "Critical",
        "PASS" if ok else "WARN",
        f"intensity={r['trading_intensity']}, assignments={r['assignments']}, tone={r['market_tone']}",
        rows,
    )


def check_e1_slots(conn, today: str) -> Result:
    rows = q(conn,
        "SELECT key, value_json FROM system_settings WHERE key LIKE ? ORDER BY key",
        (f"intraday_refresh.{today}.%",),
    )
    expected = {f"intraday_refresh.{today}.{s}" for s in ("09:30", "10:30", "11:30", "13:00", "14:00")}
    actual = {r["key"] for r in rows}
    missing = expected - actual
    ev = []
    for r in rows:
        d = json.loads(r["value_json"])
        ev.append({
            "slot": r["key"].split(".")[-1],
            "ran": d.get("ran"),
            "triggered": d.get("triggered"),
            "avg_change": d.get("avg_change"),
            "reason": (d.get("reason") or "")[:60],
        })
    return Result("E1", "장중 슬롯 5건 실행", "High",
        "PASS" if not missing else "WARN",
        f"executed={len(actual)}/5, missing={sorted([m.split('.')[-1] for m in missing])}",
        ev,
    )


def check_e2_intraday_s2(conn, today: str) -> Result:
    rows = q(conn,
        "SELECT COUNT(*) as cnt FROM morning_context WHERE trade_date=?",
        (today,),
    )
    n = rows[0]["cnt"] if rows else 0
    return Result("E2", "매 슬롯 S2 장중 실행", "High",
        "PASS" if n >= 6 else "WARN",
        f"morning_context_rows={n} (expected ≥6 = 아침1 + 슬롯5)",
    )


def check_e3_kospi_in_snapshot(conn, today: str) -> Result:
    rows = q(conn,
        "SELECT created_at, market_data FROM morning_context "
        "WHERE trade_date=? ORDER BY created_at DESC LIMIT 5",
        (today,),
    )
    ev = []
    valid_n = 0
    for r in rows:
        try:
            md = json.loads(r["market_data"])
            k = md.get("kospi", {})
            q_ = md.get("kosdaq", {})
            cr_k = k.get("change_rate") if isinstance(k, dict) else None
            cr_q = q_.get("change_rate") if isinstance(q_, dict) else None
            if cr_k is not None and cr_k != 0.0:
                valid_n += 1
            ev.append({"created_at": r["created_at"], "kospi": cr_k, "kosdaq": cr_q})
        except Exception:
            pass
    return Result("E3", "슬롯 스냅샷 KIS 지수", "Medium",
        "PASS" if valid_n >= 1 else "WARN",
        f"non_zero_kospi_count={valid_n}/{len(rows)}",
        ev,
    )


def check_e4_sector_rotation(conn, today: str) -> Result:
    rows = q(conn,
        "SELECT slot, top_sectors, bottom_sectors, gap_pct, triggered "
        "FROM sector_rotation_log WHERE trade_date=? ORDER BY slot",
        (today,),
    )
    if not rows:
        return Result("E4", "sector_rotation", "Medium", "WARN", "no log rows")
    n_insufficient = sum(1 for r in rows if "insufficient" in (r["top_sectors"] or ""))
    return Result("E4", "sector_rotation", "Medium",
        "PASS" if n_insufficient < len(rows) else "FAIL",
        f"rows={len(rows)}, insufficient={n_insufficient}",
        rows,
    )


def check_f1_buy_signals(conn, today: str) -> Result:
    rows = q(conn,
        "SELECT COUNT(*) as cnt FROM trading_signals "
        "WHERE signal_type='BUY' AND trade_date=?",
        (today,),
    )
    n = rows[0]["cnt"] if rows else 0
    return Result("F1", "매수 신호 발행", "High",
        "PASS" if n >= 1 else "WARN",
        f"buy_signals={n}",
    )


def check_f2_order_fill_rate(conn, today: str) -> Result:
    rows = q(conn,
        "SELECT side, status, COUNT(*) as cnt FROM trading_orders "
        "WHERE trade_date=? GROUP BY side, status",
        (today,),
    )
    summary = {f"{r['side']}/{r['status']}": r["cnt"] for r in rows}
    return Result("F2", "주문 체결 분포", "High", "INFO",
        json.dumps(summary, ensure_ascii=False), rows)


def check_g1_s9(conn, today: str) -> Result:
    start = f"{today} 00:00:00"
    rows = q(conn,
        "SELECT step, status, message, started_at, finished_at FROM pipeline_run_audit "
        "WHERE step='S9' AND started_at >= ? ORDER BY started_at DESC LIMIT 5",
        (start,),
    )
    if not rows:
        return Result("G1", "S9 EOD 청산", "Critical", "WARN", "no S9 row today")
    ok = any(r["status"] == "success" for r in rows)
    return Result("G1", "S9 EOD 청산", "Critical",
        "PASS" if ok else "FAIL",
        f"S9 statuses={[r['status'] for r in rows]}", rows)


def check_g3_postprocess(conn, today: str) -> Result:
    start = f"{today} 00:00:00"
    rows = q(conn,
        "SELECT step, status, message, started_at FROM pipeline_run_audit "
        "WHERE step='POSTPROCESS' AND started_at >= ? ORDER BY started_at DESC LIMIT 5",
        (start,),
    )
    if not rows:
        return Result("G3", "POSTPROCESS", "Critical", "WARN", "no POSTPROCESS row today")
    ok = any(r["status"] in ("success", "partial_failed") for r in rows)
    return Result("G3", "POSTPROCESS", "Critical",
        "PASS" if ok else "FAIL",
        f"statuses={[r['status'] for r in rows]}, msg={[r['message'] for r in rows[:1]]}", rows)


def check_h1_missed_returns(conn, today: str) -> Result:
    rows = q(conn,
        "SELECT COUNT(*) as total, "
        "  SUM(CASE WHEN max_return_until_eod IS NOT NULL THEN 1 ELSE 0 END) as tracked, "
        "  SUM(CASE WHEN improvement_candidate=1 THEN 1 ELSE 0 END) as improvements "
        "FROM missed_opportunities WHERE trade_date=?",
        (today,),
    )
    r = rows[0]
    total = r["total"] or 0
    tracked = r["tracked"] or 0
    if total == 0:
        return Result("H1", "missed_returns 추적", "Critical", "WARN", "missed_opportunities=0")
    pct = tracked / total
    return Result("H1", "missed_returns 추적", "Critical",
        "PASS" if pct >= 0.9 else "FAIL",
        f"total={total}, tracked={tracked} ({pct*100:.1f}%), improvements={r['improvements']}",
    )


def check_h3_top_missed(conn, today: str) -> Result:
    rows = q(conn,
        "SELECT symbol, symbol_name, max_return_until_eod, missed_stage, missed_reason "
        "FROM missed_opportunities WHERE trade_date=? "
        "ORDER BY max_return_until_eod DESC NULLS LAST LIMIT 10",
        (today,),
    )
    return Result("H3", "미진입 상승 TOP10", "Low", "INFO",
        f"top10_count={len(rows)}", rows)


def check_i1_false_positives(conn, today: str) -> Result:
    sum_row = q(conn,
        "SELECT realized_pnl, "
        "  (SELECT COUNT(*) FROM false_positive_cases WHERE trade_date=?) as fp_cases "
        "FROM daily_trade_summary WHERE trade_date=?",
        (today, today),
    )
    if not sum_row:
        return Result("I1", "false_positive 분석", "High", "WARN", "no daily_trade_summary")
    pnl = sum_row[0]["realized_pnl"] or 0
    fp = sum_row[0]["fp_cases"] or 0
    return Result("I1", "false_positive 분석", "High",
        "PASS" if (pnl >= 0 or fp >= 1) else "FAIL",
        f"realized_pnl={pnl}, fp_cases={fp}",
    )


def check_i2_review_report(conn, today: str) -> Result:
    rows = q(conn,
        "SELECT total_trades, total_pnl, false_positive_count, memory_count, "
        "  missed_entries_count, pnl_status, created_at "
        "FROM daily_review_reports WHERE trade_date=?",
        (today,),
    )
    if not rows:
        return Result("I2", "daily_review_reports", "Critical", "FAIL", "no row")
    r = rows[0]
    return Result("I2", "daily_review_reports", "Critical", "PASS",
        f"trades={r['total_trades']}, pnl={r['total_pnl']}, fp={r['false_positive_count']}, "
        f"memory={r['memory_count']}, missed={r['missed_entries_count']}, pnl_status={r['pnl_status']}",
        rows,
    )


def check_i3_learning_memories(conn, today: str) -> Result:
    rows = q(conn,
        "SELECT scope, category, COUNT(*) as total "
        "FROM learning_memories WHERE trade_date=? GROUP BY scope, category",
        (today,),
    )
    total = sum(r["total"] for r in rows)
    return Result("I3", "learning_memories 생성", "High",
        "PASS" if total >= 1 else "WARN",
        f"total={total}", rows,
    )


def check_j1_daily_summary(conn, today: str) -> Result:
    rows = q(conn,
        "SELECT total_orders, realized_pnl, realized_pnl_pct, "
        "  symbols_traded, pnl_status, integrity_warnings, created_at "
        "FROM daily_trade_summary WHERE trade_date=?",
        (today,),
    )
    if not rows:
        return Result("J1", "daily_trade_summary", "High", "FAIL", "no row")
    r = rows[0]
    warns = json.loads(r["integrity_warnings"] or "[]")
    return Result("J1", "daily_trade_summary", "High", "PASS",
        f"orders={r['total_orders']}, pnl={r['realized_pnl']}, status={r['pnl_status']}, "
        f"warnings={len(warns)}",
        [r] + [{"warn": w} for w in warns[:5]],
    )


def check_k1_active_memories(conn, today: str) -> Result:
    rows = q(conn,
        "SELECT scope, COUNT(*) as cnt FROM learning_memories "
        "WHERE status='active' AND (expires_at IS NULL OR expires_at >= ?) "
        "GROUP BY scope",
        (today,),
    )
    total = sum(r["cnt"] for r in rows)
    return Result("K1", "활성 learning_memories", "High",
        "PASS" if total >= 1 else "WARN",
        f"active_total={total}", rows,
    )


def check_l1_weekly_review(conn, today: str) -> Result:
    rows = q(conn,
        "SELECT date(created_at) as d, COUNT(*) as cnt FROM daily_review_reports "
        "WHERE created_at >= datetime(?, '-7 days') GROUP BY d ORDER BY d DESC",
        (today,),
    )
    return Result("L1", "7일 review 동작", "Critical", "INFO",
        f"days_with_report={len(rows)}", rows,
    )


def check_l2_weekly_missed_tracking(conn, today: str) -> Result:
    rows = q(conn,
        "SELECT trade_date, COUNT(*) as total, "
        "  SUM(CASE WHEN max_return_until_eod IS NOT NULL THEN 1 ELSE 0 END) as tracked "
        "FROM missed_opportunities WHERE trade_date >= date(?, '-7 days') "
        "GROUP BY trade_date ORDER BY trade_date DESC",
        (today,),
    )
    failures = sum(1 for r in rows if (r["total"] or 0) > 0 and (r["tracked"] or 0) / (r["total"] or 1) < 0.9)
    return Result("L2", "7일 missed 추적률", "High",
        "PASS" if failures == 0 else "WARN",
        f"days_with_low_tracking={failures}/{len(rows)}", rows,
    )


def check_l4_weekly_buys(conn, today: str) -> Result:
    rows = q(conn,
        "SELECT trade_date, COUNT(*) as cnt FROM trading_signals "
        "WHERE signal_type='BUY' AND trade_date >= date(?, '-7 days') "
        "GROUP BY trade_date ORDER BY trade_date DESC",
        (today,),
    )
    avg = sum(r["cnt"] for r in rows) / max(len(rows), 1)
    return Result("L4", "7일 매수 신호 추세", "Medium",
        "PASS" if avg >= 3 else "WARN",
        f"avg_buys_per_day={avg:.1f}, days={len(rows)}", rows,
    )


def check_l5_missed_to_buys_ratio(conn, today: str) -> Result:
    a = q(conn, "SELECT COUNT(*) as c FROM missed_opportunities WHERE trade_date >= date(?, '-7 days')", (today,))
    b = q(conn, "SELECT COUNT(*) as c FROM trading_signals WHERE signal_type='BUY' AND trade_date >= date(?, '-7 days')", (today,))
    m = a[0]["c"] or 0
    bs = b[0]["c"] or 1
    ratio = m / bs
    return Result("L5", "missed/매수 비율 (보수성)", "Medium",
        "PASS" if ratio <= 5 else "WARN",
        f"missed={m}, buys={bs}, ratio={ratio:.1f}",
    )


def scan_silent_failures() -> Result:
    """M2. 최근 로그에서 silent failure 패턴 검색."""
    try:
        result = subprocess.run(
            ["sh", "-c", f"tail -10000 {LOG_PATH} | grep -iE 'NameError|is not defined|AttributeError|TypeError' | tail -20"],
            capture_output=True, text=True, timeout=10,
        )
        lines = [l for l in result.stdout.strip().split("\n") if l]
        return Result("M2", "silent failure 로그 스캔", "High",
            "PASS" if not lines else "WARN",
            f"recent_errors={len(lines)}",
            [{"log": l[:200]} for l in lines[:10]],
        )
    except Exception as exc:
        return Result("M2", "silent failure 로그 스캔", "High", "FAIL", str(exc))


def main():
    # CLI: 첫 인자로 날짜 YYYY-MM-DD 가능 (수동 회고용)
    if len(sys.argv) >= 2 and sys.argv[1] != "--auto":
        today = sys.argv[1]
    else:
        today = kst_today()
    today_date = datetime.strptime(today, "%Y-%m-%d").date()

    # 자동 종료
    if today_date > AUTO_RUN_DEADLINE:
        print(f"[AUTO-STOP] today={today} > deadline={AUTO_RUN_DEADLINE}")
        sys.exit(2)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"{today}_eod_report.md"

    trading, reason = is_trading_day(today)

    results: list[Result] = []
    results.append(check_a1_server_alive())
    results.append(check_a2_server_start_time())
    results.append(check_a3_scheduler_jobs())
    results.append(scan_silent_failures())

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        results.append(check_c1_schedule_skip(conn))

        if trading:
            results.append(check_b1_s2_morning(conn, today))
            results.append(check_b2_morning_data_keys(conn, today))
            results.append(check_c2_universe(conn, today))
            results.append(check_c3_screening(conn, today))
            results.append(check_c4_daily_plan(conn, today))
            results.append(check_e1_slots(conn, today))
            results.append(check_e2_intraday_s2(conn, today))
            results.append(check_e3_kospi_in_snapshot(conn, today))
            results.append(check_e4_sector_rotation(conn, today))
            results.append(check_f1_buy_signals(conn, today))
            results.append(check_f2_order_fill_rate(conn, today))
            results.append(check_g1_s9(conn, today))
            results.append(check_g3_postprocess(conn, today))
            results.append(check_h1_missed_returns(conn, today))
            results.append(check_h3_top_missed(conn, today))
            results.append(check_i1_false_positives(conn, today))
            results.append(check_i2_review_report(conn, today))
            results.append(check_i3_learning_memories(conn, today))
            results.append(check_j1_daily_summary(conn, today))

        # 거래일/비거래일 무관 — 누적 메트릭
        results.append(check_k1_active_memories(conn, today))
        results.append(check_l1_weekly_review(conn, today))
        results.append(check_l2_weekly_missed_tracking(conn, today))
        results.append(check_l4_weekly_buys(conn, today))
        results.append(check_l5_missed_to_buys_ratio(conn, today))

    # 집계
    counts = {"PASS": 0, "FAIL": 0, "WARN": 0, "SKIP": 0, "INFO": 0}
    for r in results:
        counts[r.status] += 1
    crit_fail = [r for r in results if r.priority == "Critical" and r.status == "FAIL"]

    # 보고서 작성
    md_lines = [
        f"# EOD 검증 리포트 — {today}",
        "",
        f"- 생성: {kst_now().isoformat()}",
        f"- 거래일: {'YES' if trading else 'NO'} ({reason})",
        f"- 결과: PASS {counts['PASS']} / WARN {counts['WARN']} / FAIL {counts['FAIL']} / "
        f"SKIP {counts['SKIP']} / INFO {counts['INFO']}",
        f"- Critical FAIL: **{len(crit_fail)}건**" + (
            " — 즉시 조치 필요" if crit_fail else ""
        ),
        "",
        "---",
        "",
    ]
    if crit_fail:
        md_lines.append("## 🔴 Critical FAIL 요약")
        for r in crit_fail:
            md_lines.append(f"- **{r.code}**: {r.title} → {r.details}")
        md_lines.append("")
        md_lines.append("---")
        md_lines.append("")

    md_lines.append("## 전체 검증 결과")
    md_lines.append("")
    for r in results:
        md_lines.append(r.to_md())

    report_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"[OK] report saved: {report_path}")
    print(f"PASS={counts['PASS']} WARN={counts['WARN']} FAIL={counts['FAIL']} INFO={counts['INFO']} CritFAIL={len(crit_fail)}")


if __name__ == "__main__":
    main()
