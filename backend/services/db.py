"""SQLite persistence layer for settings, authentication, and trading analytics data."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from ..config import settings

logger = logging.getLogger("BackendDatabase")


def _db_path() -> Path:
    """Return the configured SQLite database path and keep it relative to the project root."""
    path = Path(settings.APP_DB_PATH)
    if path.is_absolute():
        return path
    return Path.cwd() / path


def get_connection() -> sqlite3.Connection:
    """Open a SQLite connection with row dictionaries and foreign keys enabled."""
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _execute_many(connection: sqlite3.Connection, statements: Iterable[str]) -> None:
    """Execute schema statements in order within the caller's transaction."""
    for statement in statements:
        connection.execute(statement)


def initialize_database() -> None:
    """Create the local database schema needed by the console and trading archive."""
    logger.info("START: db.initialize_database")
    with get_connection() as connection:
        _execute_many(connection, _schema_statements())
        _migrate_scheduler_process_settings(connection)
        _seed_system_settings(connection)
        _migrate_s10_review_schedule_setting(connection)
        _migrate_scheduler_process_settings(connection)
        _seed_rule_system(connection)
        _seed_confidence_bins(connection)
    # 마이그레이션: 기존 테이블에 누락된 컬럼 추가
    with get_connection() as connection:
        existing_cols = {
            row[1] for row in connection.execute("PRAGMA table_info(daily_trading_plans)").fetchall()
        }
        for col_name, alter_sql in _migration_statements():
            if col_name not in existing_cols:
                connection.execute(alter_sql)
                logger.info("DB migration: added column %s to daily_trading_plans", col_name)
        signal_cols = {
            row[1] for row in connection.execute("PRAGMA table_info(trading_signals)").fetchall()
        }
        for col_name, alter_sql in _trading_signal_migration_statements():
            if col_name not in signal_cols:
                connection.execute(alter_sql)
                logger.info("DB migration: added column %s to trading_signals", col_name)
        review_cols = {
            row[1] for row in connection.execute("PRAGMA table_info(daily_review_reports)").fetchall()
        }
        for col_name, alter_sql in _daily_review_migration_statements():
            if col_name not in review_cols:
                connection.execute(alter_sql)
                logger.info("DB migration: added column %s to daily_review_reports", col_name)
    logger.info("SUCCESS: db.initialize_database path=%s", _db_path())


def database_status() -> dict[str, Any]:
    """Return a small health payload proving the database can be opened and queried."""
    logger.info("START: db.database_status")
    try:
        with get_connection() as connection:
            user_count = connection.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
            setting_count = connection.execute("SELECT COUNT(*) AS count FROM system_settings").fetchone()["count"]
        logger.info("SUCCESS: db.database_status")
        return {"ok": True, "path": str(_db_path()), "users": user_count, "settings": setting_count}
    except Exception as exc:
        logger.error("FAIL: db.database_status - %s", exc)
        return {"ok": False, "path": str(_db_path()), "error": str(exc)}


def _json_dumps(value: Any) -> str:
    """Serialize values consistently for SQLite JSON text columns."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads_setting(value_json: str | None) -> Any:
    """Decode a persisted setting value and return None when legacy data is malformed."""
    try:
        return json.loads(value_json or "null")
    except Exception:
        return None


def _is_valid_hhmm(value: Any) -> bool:
    """Return whether a scheduler setting is a valid HH:MM clock value."""
    if not isinstance(value, str):
        return False
    parts = value.strip().split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return False
    hour, minute = int(parts[0]), int(parts[1])
    return 0 <= hour <= 23 and 0 <= minute <= 59


def _seed_system_settings(connection: sqlite3.Connection) -> None:
    """Insert baseline settings that make the console useful on first startup."""
    now_expr = "strftime('%Y-%m-%dT%H:%M:%fZ','now')"
    defaults = [
        ("risk.daily_loss_limit_percent", -2.0, "number", "일일 손실한도(%)"),
        ("risk.max_positions", 5, "number", "최대 동시 보유 종목 수"),
        ("risk.max_position_rate_per_stock", 0.10, "number", "종목당 최대 투자 비중"),
        ("kis.rate_limit_profile", settings.KIS_RATE_LIMIT_PROFILE, "string", "KIS 호출 제한 프로필"),
        ("engine.mode", "MONITOR", "string", "자동매매 엔진 기본 운용 모드"),
        ("engine.min_ai_confidence", "0.60", "number", "S6 매수 신호 최소 AI confidence 임계값 (0.0~1.0)"),
        (
            "engine.min_confidence_floor",
            "0.40",
            "number",
            "AI 매수 신호 confidence 절대 하한선 (AI가 이 값 이하로 설정 불가)",
        ),
        (
            "engine.min_price_change_pct",
            "0.5",
            "number",
            "매수 진입 최소 등락률 % (AI가 이 값 이하로 설정 불가)",
        ),
        (
            "engine.max_price_change_pct",
            "8.0",
            "number",
            "매수 진입 최대 등락률 % (AI가 이 값 이상으로 설정 불가)",
        ),
        ("risk.emergency_halt_enabled", False, "boolean", "긴급정지 신규 주문 차단 상태"),
        ("schedule_trade_prep_time", "07:45", "string", "거래준비 프로세스 시작 시간 (S1~S5-A 순차 실행, HH:MM)"),
        ("schedule_s1_time", "07:45", "string", "[legacy] S1 개별 실행 시간 - scheduler 등록에는 사용하지 않음"),
        ("schedule_s2_time", "08:00", "string", "[legacy] S2 개별 실행 시간 - schedule_trade_prep_time 사용"),
        ("schedule_s3_time", "08:15", "string", "[legacy] S3 개별 실행 시간 - schedule_trade_prep_time 사용"),
        ("schedule_s4_time", "08:30", "string", "[legacy] S4 개별 실행 시간 - schedule_trade_prep_time 사용"),
        ("schedule_s5_time", "08:40", "string", "[legacy] S5 개별 실행 시간 - schedule_trade_prep_time 사용"),
        ("schedule_s5v_time", "08:45", "string", "[legacy] S5-V 개별 실행 시간 - schedule_trade_prep_time 사용"),
        ("schedule_s5a_time", "08:55", "string", "[legacy] S5-A 개별 실행 시간 - schedule_trade_prep_time 사용"),
        ("schedule_s6_time", "09:45", "string", "S6 Decision Engine 실행 시간 (HH:MM)"),
        ("schedule_s7_time", "실시간", "string", "S7 주문 실행 표시 시간"),
        ("schedule_s8_time", "실시간", "string", "S8 포지션 관리 표시 시간"),
        ("schedule_postprocess_time", "15:20", "string", "후처리 프로세스 시작 시간 (S9~S10 순차 실행, HH:MM)"),
        ("schedule_s9_time", "15:20", "string", "[legacy] S9 개별 실행 시간 - schedule_postprocess_time 사용"),
        ("schedule_s10_time", "16:00", "string", "[legacy] S10 개별 실행 시간 - schedule_postprocess_time 사용"),
        ("schedule_s11_time", "22:00", "string", "S11 Learning Memory Builder 실행 시간 (HH:MM)"),
        ("risk.force_exit_time", "15:20", "string", "당일 강제청산 시작 시간 (HH:MM)"),
        ("risk.new_entry_cutoff_time", "15:10", "string", "신규 매수 금지 시작 시간 (HH:MM)"),
    ]
    for key, value, value_type, description in defaults:
        connection.execute(
            f"""
            INSERT OR IGNORE INTO system_settings
                (key, value_json, value_type, description, updated_at, updated_by)
            VALUES (?, ?, ?, ?, {now_expr}, ?)
            """,
            (key, _json_dumps(value), value_type, description, "system"),
        )


def _migrate_scheduler_process_settings(connection: sqlite3.Connection) -> None:
    """Copy legacy custom scheduler times into process keys and refresh descriptions."""
    now_expr = "strftime('%Y-%m-%dT%H:%M:%fZ','now')"
    process_defaults = {
        "schedule_trade_prep_time": (
            "schedule_s1_time",
            "07:45",
            "거래준비 프로세스 시작 시간 (S1~S5-A 순차 실행, HH:MM)",
        ),
        "schedule_postprocess_time": (
            "schedule_s9_time",
            "15:20",
            "후처리 프로세스 시작 시간 (S9~S10 순차 실행, HH:MM)",
        ),
    }
    for process_key, (legacy_key, default_value, description) in process_defaults.items():
        existing = connection.execute("SELECT 1 FROM system_settings WHERE key = ?", (process_key,)).fetchone()
        if existing:
            continue
        legacy_row = connection.execute(
            "SELECT value_json FROM system_settings WHERE key = ?",
            (legacy_key,),
        ).fetchone()
        legacy_value = _json_loads_setting(legacy_row["value_json"]) if legacy_row else None
        value = legacy_value if _is_valid_hhmm(legacy_value) else default_value
        actor = "migration_scheduler_process_settings"
        if legacy_row and not _is_valid_hhmm(legacy_value):
            logger.warning(
                "WARN: DB migration invalid legacy schedule ignored legacy_key=%s value=%s process_key=%s default=%s",
                legacy_key,
                legacy_value,
                process_key,
                default_value,
            )
        connection.execute(
            f"""
            INSERT INTO system_settings
                (key, value_json, value_type, description, updated_at, updated_by)
            VALUES (?, ?, 'string', ?, {now_expr}, ?)
            """,
            (process_key, _json_dumps(value), description, actor),
        )
        logger.info(
            "DB migration: seeded %s from %s value=%s",
            process_key,
            legacy_key if _is_valid_hhmm(legacy_value) else "default",
            value,
        )

    descriptions = {
        "schedule_trade_prep_time": "거래준비 프로세스 시작 시간 (S1~S5-A 순차 실행, HH:MM)",
        "schedule_s1_time": "[legacy] S1 개별 실행 시간 - scheduler 등록에는 사용하지 않음",
        "schedule_s2_time": "[legacy] S2 개별 실행 시간 - schedule_trade_prep_time 사용",
        "schedule_s3_time": "[legacy] S3 개별 실행 시간 - schedule_trade_prep_time 사용",
        "schedule_s4_time": "[legacy] S4 개별 실행 시간 - schedule_trade_prep_time 사용",
        "schedule_s5_time": "[legacy] S5 개별 실행 시간 - schedule_trade_prep_time 사용",
        "schedule_s5v_time": "[legacy] S5-V 개별 실행 시간 - schedule_trade_prep_time 사용",
        "schedule_s5a_time": "[legacy] S5-A 개별 실행 시간 - schedule_trade_prep_time 사용",
        "schedule_postprocess_time": "후처리 프로세스 시작 시간 (S9~S10 순차 실행, HH:MM)",
        "schedule_s9_time": "[legacy] S9 개별 실행 시간 - schedule_postprocess_time 사용",
        "schedule_s10_time": "[legacy] S10 개별 실행 시간 - schedule_postprocess_time 사용",
    }
    for key, description in descriptions.items():
        connection.execute(
            f"""
            UPDATE system_settings
            SET description = ?, updated_at = {now_expr}, updated_by = ?
            WHERE key = ? AND description != ?
            """,
            (description, "migration_scheduler_process_settings", key, description),
        )


def _migrate_s10_review_schedule_setting(connection: sqlite3.Connection) -> None:
    """Move only the old S10 daily-summary default setting to Review Audit semantics."""
    now_expr = "strftime('%Y-%m-%dT%H:%M:%fZ','now')"
    old_description = "S10 일일 요약 및 DB 백업 실행 시간 (HH:MM)"
    row = connection.execute(
        "SELECT value_json, description FROM system_settings WHERE key = 'schedule_s10_time'",
    ).fetchone()
    if row and row["value_json"] == _json_dumps("18:00") and row["description"] == old_description:
        connection.execute(
            f"""
            UPDATE system_settings
            SET value_json = ?, description = ?, updated_at = {now_expr}, updated_by = ?
            WHERE key = 'schedule_s10_time'
            """,
            (_json_dumps("16:00"), "S10 Review & Audit 실행 시간 (HH:MM)", "migration_s10_review_audit"),
        )
        logger.info("DB migration: updated schedule_s10_time from daily summary default to Review Audit default")


def _seed_rule_system(connection: sqlite3.Connection) -> None:
    """base_rulepacks, risk_profile_packs 초기값 삽입 (이미 있으면 skip)."""
    import json as _json
    now_expr = "strftime('%Y-%m-%dT%H:%M:%fZ','now')"

    # Base RulePack v1.0
    connection.execute(
        f"""
        INSERT OR IGNORE INTO base_rulepacks
            (id, version, take_profit_enabled, force_daily_close, force_exit_time,
             stop_price_can_only_increase, order_execution, created_at, is_active)
        VALUES (?, ?, 0, 1, ?, 1, ?, {now_expr}, 1)
        """,
        (
            "base-v1.0",
            "1.0",
            "15:20:00",
            _json.dumps({"entry_order_type": "limit_or_market_by_policy",
                         "exit_order_type": "market_or_safe_limit"}, ensure_ascii=False),
        ),
    )

    # Risk Profile Pack v1.0
    profiles = {
        "LOW_VOL": {
            "initial_stop_loss": -0.02,
            "trailing_activate_profit": 0.015,
            "trailing_stop_rate": 0.018,
            "max_position_rate": 0.15,
            "max_holding_minutes": 240,
        },
        "MID_VOL": {
            "initial_stop_loss": -0.03,
            "trailing_activate_profit": 0.025,
            "trailing_stop_rate": 0.03,
            "max_position_rate": 0.12,
            "max_holding_minutes": 180,
        },
        "HIGH_VOL": {
            "initial_stop_loss": -0.045,
            "trailing_activate_profit": 0.04,
            "trailing_stop_rate": 0.05,
            "max_position_rate": 0.08,
            "max_holding_minutes": 120,
        },
        "THEME_SPIKE": {
            "initial_stop_loss": -0.06,
            "trailing_activate_profit": 0.05,
            "trailing_stop_rate": 0.06,
            "max_position_rate": 0.05,
            "max_holding_minutes": 60,
            "reentry_allowed": False,
        },
    }
    connection.execute(
        f"""
        INSERT OR IGNORE INTO risk_profile_packs
            (id, version, profiles, created_at, is_active)
        VALUES (?, ?, ?, {now_expr}, 1)
        """,
        ("profile-v1.0", "1.0", _json.dumps(profiles, ensure_ascii=False)),
    )


def _seed_confidence_bins(connection: sqlite3.Connection) -> None:
    """Insert baseline confidence calibration bins when they do not already exist."""
    now_expr = "strftime('%Y-%m-%dT%H:%M:%fZ','now')"
    bins = [
        ("ge090", 0.90, 1.01),
        ("80to90", 0.80, 0.90),
        ("70to80", 0.70, 0.80),
        ("60to70", 0.60, 0.70),
        ("lt060", 0.0, 0.60),
    ]
    for bin_label, bin_min, bin_max in bins:
        connection.execute(
            f"""
            INSERT OR IGNORE INTO confidence_calibration_bins
                (id, bin_label, bin_min, bin_max, cumulative_trades,
                 cumulative_wins, cumulative_avg_pnl, last_updated)
            VALUES (?, ?, ?, ?, 0, 0, 0.0, {now_expr})
            """,
            (bin_label, bin_label, bin_min, bin_max),
        )


def _schema_statements() -> list[str]:
    """Return normalized schema statements for local MVP persistence and future analytics."""
    return [
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS user_mfa_methods (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            method_type TEXT NOT NULL,
            label TEXT NOT NULL DEFAULT '',
            secret_json TEXT NOT NULL DEFAULT '{}',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS mfa_challenges (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            purpose TEXT NOT NULL,
            method_type TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            consumed_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            value_type TEXT NOT NULL DEFAULT 'json',
            description TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            updated_by TEXT NOT NULL DEFAULT 'system'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS symbols (
            symbol TEXT PRIMARY KEY,
            market TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL DEFAULT '',
            sector TEXT NOT NULL DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS strategy_runs (
            id TEXT PRIMARY KEY,
            strategy_key TEXT NOT NULL,
            rulepack_id TEXT NOT NULL DEFAULT '',
            mode TEXT NOT NULL DEFAULT 'monitor',
            status TEXT NOT NULL DEFAULT 'started',
            started_at TEXT NOT NULL,
            finished_at TEXT,
            input_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT NOT NULL DEFAULT '{}',
            note TEXT NOT NULL DEFAULT ''
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS signals (
            id TEXT PRIMARY KEY,
            strategy_run_id TEXT REFERENCES strategy_runs(id) ON DELETE SET NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            signal_type TEXT NOT NULL DEFAULT 'entry',
            confidence REAL,
            price REAL,
            reason_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY,
            strategy_run_id TEXT REFERENCES strategy_runs(id) ON DELETE SET NULL,
            signal_id TEXT REFERENCES signals(id) ON DELETE SET NULL,
            broker_order_id TEXT NOT NULL DEFAULT '',
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            order_type TEXT NOT NULL DEFAULT 'market',
            quantity REAL NOT NULL,
            limit_price REAL,
            status TEXT NOT NULL DEFAULT 'created',
            requested_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            request_json TEXT NOT NULL DEFAULT '{}',
            response_json TEXT NOT NULL DEFAULT '{}'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS fills (
            id TEXT PRIMARY KEY,
            order_id TEXT REFERENCES orders(id) ON DELETE SET NULL,
            broker_fill_id TEXT NOT NULL DEFAULT '',
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity REAL NOT NULL,
            price REAL NOT NULL,
            fee REAL NOT NULL DEFAULT 0,
            tax REAL NOT NULL DEFAULT 0,
            filled_at TEXT NOT NULL,
            raw_json TEXT NOT NULL DEFAULT '{}'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS positions (
            id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            quantity REAL NOT NULL,
            avg_price REAL NOT NULL,
            market_price REAL,
            realized_pnl REAL NOT NULL DEFAULT 0,
            unrealized_pnl REAL NOT NULL DEFAULT 0,
            source TEXT NOT NULL DEFAULT 'system',
            captured_at TEXT NOT NULL,
            raw_json TEXT NOT NULL DEFAULT '{}'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS account_snapshots (
            id TEXT PRIMARY KEY,
            cash REAL,
            equity REAL,
            buying_power REAL,
            day_pnl REAL,
            total_pnl REAL,
            captured_at TEXT NOT NULL,
            raw_json TEXT NOT NULL DEFAULT '{}'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS market_snapshots (
            id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            price REAL,
            volume REAL,
            change_rate REAL,
            source TEXT NOT NULL DEFAULT 'kis',
            captured_at TEXT NOT NULL,
            raw_json TEXT NOT NULL DEFAULT '{}'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS audit_events (
            id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            actor TEXT NOT NULL DEFAULT 'system',
            severity TEXT NOT NULL DEFAULT 'info',
            message TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS rulepacks (
            rulepack_id   TEXT PRIMARY KEY,
            trade_date    TEXT NOT NULL,
            mode          TEXT NOT NULL DEFAULT 'auto',
            status        TEXT NOT NULL DEFAULT 'pending',
            machine_rules TEXT NOT NULL,
            summary       TEXT NOT NULL DEFAULT '',
            changes       TEXT NOT NULL DEFAULT '',
            validation    TEXT NOT NULL DEFAULT '{}',
            created_at    TEXT NOT NULL,
            activated_at  TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_rulepacks_trade_date ON rulepacks(trade_date)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_user_mfa_methods_user_id ON user_mfa_methods(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_mfa_challenges_user_id ON mfa_challenges(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_orders_symbol_requested_at ON orders(symbol, requested_at)",
        "CREATE INDEX IF NOT EXISTS idx_fills_symbol_filled_at ON fills(symbol, filled_at)",
        "CREATE INDEX IF NOT EXISTS idx_positions_symbol_captured_at ON positions(symbol, captured_at)",
        "CREATE INDEX IF NOT EXISTS idx_market_snapshots_symbol_captured_at ON market_snapshots(symbol, captured_at)",
        "CREATE INDEX IF NOT EXISTS idx_audit_events_type_created_at ON audit_events(event_type, created_at)",
        """
CREATE TABLE IF NOT EXISTS base_rulepacks (
    id              TEXT PRIMARY KEY,
    version         TEXT NOT NULL,
    take_profit_enabled          INTEGER NOT NULL DEFAULT 0,
    force_daily_close            INTEGER NOT NULL DEFAULT 1,
    force_exit_time              TEXT NOT NULL DEFAULT '15:20:00',
    stop_price_can_only_increase INTEGER NOT NULL DEFAULT 1,
    order_execution TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1
)
""",
        """
CREATE TABLE IF NOT EXISTS risk_profile_packs (
    id          TEXT PRIMARY KEY,
    version     TEXT NOT NULL,
    profiles    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 1
)
""",
        """
CREATE TABLE IF NOT EXISTS daily_trading_plans (
    id                   TEXT PRIMARY KEY,
    trade_date           TEXT NOT NULL UNIQUE,
    market_tone          TEXT NOT NULL DEFAULT 'neutral',
    trading_intensity    TEXT NOT NULL DEFAULT 'normal',
    base_rulepack_id     TEXT NOT NULL DEFAULT 'base-v1.0',
    risk_profile_pack_id TEXT NOT NULL DEFAULT 'profile-v1.0',
    new_entry_allowed    INTEGER NOT NULL DEFAULT 1,
    daily_overrides      TEXT NOT NULL DEFAULT '{}',
    symbol_assignments   TEXT NOT NULL DEFAULT '[]',
    excluded_symbols     TEXT NOT NULL DEFAULT '[]',
    llm_summary          TEXT NOT NULL DEFAULT '',
    provider             TEXT NOT NULL DEFAULT '',
    status               TEXT NOT NULL DEFAULT 'draft',
    validation_result    TEXT NOT NULL DEFAULT '{}',
    creation_mode        TEXT NOT NULL DEFAULT 'auto',
    created_by           TEXT NOT NULL DEFAULT 'scheduler',
    trigger_source       TEXT NOT NULL DEFAULT 'auto_scheduler',
    run_audit_id         TEXT NOT NULL DEFAULT '',
    s3_result_id         TEXT NOT NULL DEFAULT '',
    s4_result_id         TEXT NOT NULL DEFAULT '',
    used_learning_memory_ids TEXT NOT NULL DEFAULT '[]',
    used_knowledge_ids   TEXT NOT NULL DEFAULT '[]',
    created_at           TEXT NOT NULL,
    activated_at         TEXT,
    validated_at         TEXT,
    superseded_at        TEXT
)
""",
        "CREATE INDEX IF NOT EXISTS idx_daily_plan_date ON daily_trading_plans(trade_date)",
        """
CREATE TABLE IF NOT EXISTS daily_plan_run_history (
    id                   TEXT PRIMARY KEY,
    plan_id              TEXT NOT NULL,
    trade_date           TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'generated',
    trigger_source       TEXT NOT NULL DEFAULT 'api_manual',
    run_audit_id         TEXT NOT NULL DEFAULT '',
    creation_mode        TEXT NOT NULL DEFAULT 'auto',
    created_by           TEXT NOT NULL DEFAULT 'scheduler',
    provider             TEXT NOT NULL DEFAULT '',
    plan_payload         TEXT NOT NULL DEFAULT '{}',
    validation_result    TEXT NOT NULL DEFAULT '{}',
    s3_result_id         TEXT NOT NULL DEFAULT '',
    s4_result_id         TEXT NOT NULL DEFAULT '',
    created_at           TEXT NOT NULL
)
""",
        "CREATE INDEX IF NOT EXISTS idx_daily_plan_history_date ON daily_plan_run_history(trade_date, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_daily_plan_history_audit ON daily_plan_run_history(run_audit_id)",
        """
CREATE TABLE IF NOT EXISTS pipeline_run_audit (
    id             TEXT PRIMARY KEY,
    trade_date     TEXT NOT NULL,
    step           TEXT NOT NULL,
    trigger_source TEXT NOT NULL DEFAULT 'api_manual',
    display_source TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'started',
    result_ref_id  TEXT NOT NULL DEFAULT '',
    message        TEXT NOT NULL DEFAULT '',
    metadata_json  TEXT NOT NULL DEFAULT '{}',
    started_at     TEXT NOT NULL,
    finished_at    TEXT
)
""",
        "CREATE INDEX IF NOT EXISTS idx_pipeline_audit_date_step ON pipeline_run_audit(trade_date, step, started_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_pipeline_audit_source ON pipeline_run_audit(trigger_source, started_at DESC)",
        """
CREATE TABLE IF NOT EXISTS symbol_overrides (
    id              TEXT PRIMARY KEY,
    symbol_code     TEXT NOT NULL UNIQUE,
    symbol_name     TEXT NOT NULL DEFAULT '',
    default_profile TEXT NOT NULL DEFAULT 'MID_VOL',
    override_values TEXT NOT NULL DEFAULT '{}',
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
)
""",
        """
CREATE TABLE IF NOT EXISTS rule_compositions (
    id                   TEXT PRIMARY KEY,
    trade_date           TEXT NOT NULL,
    symbol_code          TEXT NOT NULL,
    final_rule           TEXT NOT NULL,
    base_rulepack_id     TEXT NOT NULL,
    risk_profile_pack_id TEXT NOT NULL,
    daily_plan_id        TEXT NOT NULL,
    profile_assigned     TEXT NOT NULL,
    created_at           TEXT NOT NULL
)
""",
        "CREATE INDEX IF NOT EXISTS idx_rule_comp_date ON rule_compositions(trade_date)",
        """
CREATE TABLE IF NOT EXISTS position_stop_states (
    position_id               TEXT PRIMARY KEY,
    symbol_code               TEXT NOT NULL,
    entry_price               REAL NOT NULL DEFAULT 0.0,
    highest_price_since_entry REAL NOT NULL DEFAULT 0.0,
    initial_stop_price        REAL NOT NULL DEFAULT 0.0,
    trailing_stop_price       REAL NOT NULL DEFAULT 0.0,
    active_stop_price         REAL NOT NULL DEFAULT 0.0,
    trailing_active           INTEGER NOT NULL DEFAULT 0,
    profile_assigned          TEXT NOT NULL DEFAULT 'MID_VOL',
    last_updated_at           TEXT NOT NULL
)
""",
        """
CREATE TABLE IF NOT EXISTS trading_signals (
    id            TEXT PRIMARY KEY,
    trade_date    TEXT NOT NULL,
    symbol        TEXT NOT NULL,
    name          TEXT NOT NULL DEFAULT '',
    signal_type   TEXT NOT NULL DEFAULT 'BUY',
    trigger_price REAL NOT NULL DEFAULT 0.0,
    confidence    REAL NOT NULL DEFAULT 0.0,
    rule_matched  TEXT NOT NULL DEFAULT '{}',
    profile_assigned TEXT NOT NULL DEFAULT 'MID_VOL',
    realized_pnl  REAL,
    status        TEXT NOT NULL DEFAULT 'pending',
    created_at    TEXT NOT NULL
)
""",
        "CREATE INDEX IF NOT EXISTS idx_trading_signals_trade_date ON trading_signals(trade_date)",
        """
CREATE TABLE IF NOT EXISTS order_preflight_checks (
    id            TEXT PRIMARY KEY,
    signal_id     TEXT NOT NULL DEFAULT '',
    symbol        TEXT NOT NULL DEFAULT '',
    checks        TEXT NOT NULL DEFAULT '{}',
    block_reasons TEXT NOT NULL DEFAULT '',
    result        TEXT NOT NULL DEFAULT 'ok',
    created_at    TEXT NOT NULL
)
""",
        "CREATE INDEX IF NOT EXISTS idx_preflight_signal ON order_preflight_checks(signal_id)",
        "CREATE INDEX IF NOT EXISTS idx_preflight_symbol ON order_preflight_checks(symbol)",
        """
CREATE TABLE IF NOT EXISTS daily_review_reports (
    id               TEXT PRIMARY KEY,
    trade_date       TEXT NOT NULL,
    total_trades     INTEGER NOT NULL DEFAULT 0,
    win_count        INTEGER NOT NULL DEFAULT 0,
    loss_count       INTEGER NOT NULL DEFAULT 0,
    total_pnl        REAL NOT NULL DEFAULT 0.0,
    profile_summary  TEXT NOT NULL DEFAULT '{}',
    exit_summary     TEXT NOT NULL DEFAULT '{}',
    trailing_quality TEXT NOT NULL DEFAULT '{}',
    missed_entries   TEXT NOT NULL DEFAULT '[]',
    false_positives  TEXT NOT NULL DEFAULT '[]',
    missed_entries_count INTEGER NOT NULL DEFAULT 0,
    false_positive_count INTEGER NOT NULL DEFAULT 0,
    no_trade_count   INTEGER NOT NULL DEFAULT 0,
    memory_count     INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL
)
""",
        "CREATE INDEX IF NOT EXISTS idx_daily_review_trade_date ON daily_review_reports(trade_date)",
        """
CREATE TABLE IF NOT EXISTS learning_memories (
    memory_id          TEXT PRIMARY KEY,
    trade_date         TEXT NOT NULL,
    scope              TEXT NOT NULL,
    category           TEXT NOT NULL,
    summary            TEXT NOT NULL,
    evidence           TEXT NOT NULL DEFAULT '{}',
    recommendation     TEXT NOT NULL DEFAULT '{}',
    auto_apply_allowed INTEGER NOT NULL DEFAULT 0,
    requires_approval  INTEGER NOT NULL DEFAULT 0,
    status             TEXT NOT NULL DEFAULT 'active',
    expires_at         TEXT,
    created_at         TEXT NOT NULL
)
""",
        "CREATE INDEX IF NOT EXISTS idx_learning_memories_trade_date ON learning_memories(trade_date)",
        "CREATE INDEX IF NOT EXISTS idx_learning_memories_scope ON learning_memories(scope)",
        "CREATE INDEX IF NOT EXISTS idx_learning_memories_status ON learning_memories(status)",
        """
CREATE TABLE IF NOT EXISTS external_knowledge_sources (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'manual',
    description TEXT NOT NULL DEFAULT '',
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
)
""",
        """
CREATE TABLE IF NOT EXISTS strategy_knowledge_items (
    id              TEXT PRIMARY KEY,
    source_id       TEXT,
    title           TEXT NOT NULL,
    content         TEXT NOT NULL,
    scope           TEXT NOT NULL,
    category        TEXT NOT NULL DEFAULT 'general',
    status          TEXT NOT NULL DEFAULT 'pending',
    auto_inject     INTEGER NOT NULL DEFAULT 0,
    priority        INTEGER NOT NULL DEFAULT 5,
    created_at      TEXT NOT NULL,
    approved_at     TEXT,
    expires_at      TEXT
)
""",
        "CREATE INDEX IF NOT EXISTS idx_knowledge_items_scope ON strategy_knowledge_items(scope)",
        "CREATE INDEX IF NOT EXISTS idx_knowledge_items_status ON strategy_knowledge_items(status)",
        """
CREATE TABLE IF NOT EXISTS pdf_analyses (
    analysis_id    TEXT PRIMARY KEY,
    filename       TEXT NOT NULL,
    extracted_text TEXT NOT NULL,
    candidates     TEXT NOT NULL DEFAULT '[]',
    unmappable     TEXT NOT NULL DEFAULT '[]',
    summary        TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'pending',
    created_at     TEXT NOT NULL,
    applied_at     TEXT
)
""",
        "CREATE INDEX IF NOT EXISTS idx_pdf_analyses_created ON pdf_analyses(created_at DESC)",
        """
CREATE TABLE IF NOT EXISTS knowledge_prompt_contexts (
    id              TEXT PRIMARY KEY,
    trade_date      TEXT NOT NULL,
    scope           TEXT NOT NULL,
    knowledge_ids   TEXT NOT NULL DEFAULT '[]',
    prompt_snippet  TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL
)
""",
        "CREATE INDEX IF NOT EXISTS idx_knowledge_ctx_trade_date ON knowledge_prompt_contexts(trade_date)",
        """
CREATE TABLE IF NOT EXISTS knowledge_impact_stats (
    id              TEXT PRIMARY KEY,
    knowledge_id    TEXT NOT NULL,
    trade_date      TEXT NOT NULL,
    scope           TEXT NOT NULL,
    applied         INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
)
""",
        "CREATE INDEX IF NOT EXISTS idx_knowledge_impact_trade_date ON knowledge_impact_stats(trade_date)",
        """
CREATE TABLE IF NOT EXISTS knowledge_approval_logs (
    id              TEXT PRIMARY KEY,
    knowledge_id    TEXT NOT NULL,
    action          TEXT NOT NULL,
    reason          TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL
)
""",
        """
CREATE TABLE IF NOT EXISTS profile_performance_daily (
    id          TEXT PRIMARY KEY,
    trade_date  TEXT NOT NULL,
    profile     TEXT NOT NULL,
    trade_count INTEGER NOT NULL DEFAULT 0,
    win_count   INTEGER NOT NULL DEFAULT 0,
    total_pnl   REAL NOT NULL DEFAULT 0.0,
    avg_pnl     REAL NOT NULL DEFAULT 0.0,
    created_at  TEXT NOT NULL
)
""",
        "CREATE INDEX IF NOT EXISTS idx_profile_perf_trade_date ON profile_performance_daily(trade_date)",
        """
CREATE TABLE IF NOT EXISTS exit_reason_performance_daily (
    id          TEXT PRIMARY KEY,
    trade_date  TEXT NOT NULL,
    exit_reason TEXT NOT NULL,
    trade_count INTEGER NOT NULL DEFAULT 0,
    avg_pnl     REAL NOT NULL DEFAULT 0.0,
    created_at  TEXT NOT NULL
)
""",
        "CREATE INDEX IF NOT EXISTS idx_exit_reason_trade_date ON exit_reason_performance_daily(trade_date)",
        """
CREATE TABLE IF NOT EXISTS trailing_quality_daily (
    id                   TEXT PRIMARY KEY,
    trade_date           TEXT NOT NULL,
    avg_recovery_rate    REAL NOT NULL DEFAULT 0.0,
    early_exit_rate      REAL NOT NULL DEFAULT 0.0,
    total_trailing_exits INTEGER NOT NULL DEFAULT 0,
    created_at           TEXT NOT NULL
)
""",
        "CREATE INDEX IF NOT EXISTS idx_trailing_quality_trade_date ON trailing_quality_daily(trade_date)",
        """
CREATE TABLE IF NOT EXISTS no_trade_daily_reasons (
    id         TEXT PRIMARY KEY,
    trade_date TEXT NOT NULL,
    reason     TEXT NOT NULL,
    detail     TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
)
""",
        "CREATE INDEX IF NOT EXISTS idx_no_trade_trade_date ON no_trade_daily_reasons(trade_date)",
        """
CREATE TABLE IF NOT EXISTS candidate_no_entry_reasons (
    id         TEXT PRIMARY KEY,
    trade_date TEXT NOT NULL,
    symbol     TEXT NOT NULL,
    reason     TEXT NOT NULL,
    detail     TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
)
""",
        "CREATE INDEX IF NOT EXISTS idx_candidate_no_entry_trade_date ON candidate_no_entry_reasons(trade_date)",
        """
CREATE TABLE IF NOT EXISTS data_quality_events (
    id          TEXT PRIMARY KEY,
    trade_date  TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    severity    TEXT NOT NULL DEFAULT 'WARNING',
    symbol      TEXT,
    detail      TEXT NOT NULL DEFAULT '',
    resolved    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
)
""",
        "CREATE INDEX IF NOT EXISTS idx_dq_events_trade_date ON data_quality_events(trade_date)",
        "CREATE INDEX IF NOT EXISTS idx_dq_events_severity ON data_quality_events(severity)",
        """
CREATE TABLE IF NOT EXISTS data_quality_snapshots (
    id              TEXT PRIMARY KEY,
    trade_date      TEXT NOT NULL,
    overall_status  TEXT NOT NULL DEFAULT 'NORMAL',
    event_counts    TEXT NOT NULL DEFAULT '{}',
    worst_severity  TEXT NOT NULL DEFAULT 'INFO',
    created_at      TEXT NOT NULL
)
""",
        "CREATE INDEX IF NOT EXISTS idx_dq_snapshots_trade_date ON data_quality_snapshots(trade_date)",
        """
CREATE TABLE IF NOT EXISTS system_alerts (
    id          TEXT PRIMARY KEY,
    trade_date  TEXT NOT NULL,
    alert_type  TEXT NOT NULL,
    severity    TEXT NOT NULL DEFAULT 'WARNING',
    title       TEXT NOT NULL,
    detail      TEXT NOT NULL DEFAULT '',
    acknowledged INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
)
""",
        "CREATE INDEX IF NOT EXISTS idx_alerts_trade_date ON system_alerts(trade_date)",
        "CREATE INDEX IF NOT EXISTS idx_alerts_acknowledged ON system_alerts(acknowledged)",
        """
CREATE TABLE IF NOT EXISTS human_approval_queue (
    id           TEXT PRIMARY KEY,
    change_type  TEXT NOT NULL,
    title        TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    status       TEXT NOT NULL DEFAULT 'pending',
    created_at   TEXT NOT NULL,
    decided_at   TEXT
)
""",
        "CREATE INDEX IF NOT EXISTS idx_human_approval_status ON human_approval_queue(status)",
        "CREATE INDEX IF NOT EXISTS idx_human_approval_created_at ON human_approval_queue(created_at)",
        """
CREATE TABLE IF NOT EXISTS approval_decision_logs (
    id          TEXT PRIMARY KEY,
    request_id  TEXT NOT NULL,
    action      TEXT NOT NULL,
    reason      TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
)
""",
        "CREATE INDEX IF NOT EXISTS idx_approval_logs_request_id ON approval_decision_logs(request_id)",
        """
CREATE TABLE IF NOT EXISTS shadow_trades (
    id              TEXT PRIMARY KEY,
    trade_date      TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    symbol_name     TEXT NOT NULL DEFAULT '',
    missed_stage    TEXT NOT NULL,
    entry_price     REAL NOT NULL DEFAULT 0.0,
    entry_time      TEXT NOT NULL,
    exit_price      REAL,
    exit_time       TEXT,
    shadow_pnl      REAL,
    max_return_10m  REAL,
    max_return_30m  REAL,
    max_return_eod  REAL,
    status          TEXT NOT NULL DEFAULT 'active',
    created_at      TEXT NOT NULL
)
""",
        "CREATE INDEX IF NOT EXISTS idx_shadow_trades_trade_date ON shadow_trades(trade_date)",
        """
CREATE TABLE IF NOT EXISTS shadow_trade_events (
    id              TEXT PRIMARY KEY,
    shadow_trade_id TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    price           REAL,
    pnl             REAL,
    created_at      TEXT NOT NULL
)
""",
        """
CREATE TABLE IF NOT EXISTS missed_opportunities (
    id                  TEXT PRIMARY KEY,
    trade_date          TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    symbol_name         TEXT NOT NULL DEFAULT '',
    missed_stage        TEXT NOT NULL,
    missed_reason       TEXT NOT NULL,
    price_at_missed     REAL NOT NULL DEFAULT 0.0,
    max_return_after_10m REAL,
    max_return_after_30m REAL,
    max_return_until_eod REAL,
    improvement_candidate INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL
)
""",
        "CREATE INDEX IF NOT EXISTS idx_missed_trade_date ON missed_opportunities(trade_date)",
        """
CREATE TABLE IF NOT EXISTS false_positive_cases (
    id                  TEXT PRIMARY KEY,
    trade_date          TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    symbol_name         TEXT NOT NULL DEFAULT '',
    false_positive_type TEXT NOT NULL,
    original_score      REAL,
    original_confidence REAL,
    assigned_profile    TEXT,
    entry_reason        TEXT NOT NULL DEFAULT '',
    loss_reason         TEXT NOT NULL DEFAULT '',
    exit_reason         TEXT NOT NULL DEFAULT '',
    applied_knowledge_ids TEXT NOT NULL DEFAULT '[]',
    applied_memory_ids  TEXT NOT NULL DEFAULT '[]',
    suggested_penalty   REAL,
    created_at          TEXT NOT NULL
)
""",
        "CREATE INDEX IF NOT EXISTS idx_fp_trade_date ON false_positive_cases(trade_date)",
        """
CREATE TABLE IF NOT EXISTS confidence_calibration_daily (
    id              TEXT PRIMARY KEY,
    trade_date      TEXT NOT NULL,
    bin_label       TEXT NOT NULL,
    trade_count     INTEGER NOT NULL DEFAULT 0,
    win_count       INTEGER NOT NULL DEFAULT 0,
    avg_pnl         REAL NOT NULL DEFAULT 0.0,
    expected_win_rate REAL NOT NULL DEFAULT 0.0,
    actual_win_rate REAL NOT NULL DEFAULT 0.0,
    created_at      TEXT NOT NULL
)
""",
        "CREATE INDEX IF NOT EXISTS idx_conf_cal_trade_date ON confidence_calibration_daily(trade_date)",
        """
CREATE TABLE IF NOT EXISTS confidence_calibration_bins (
    id              TEXT PRIMARY KEY,
    bin_label       TEXT NOT NULL UNIQUE,
    bin_min         REAL NOT NULL,
    bin_max         REAL NOT NULL,
    cumulative_trades INTEGER NOT NULL DEFAULT 0,
    cumulative_wins INTEGER NOT NULL DEFAULT 0,
    cumulative_avg_pnl REAL NOT NULL DEFAULT 0.0,
    last_updated    TEXT NOT NULL
)
""",
    ]


def _migration_statements() -> list[tuple[str, str]]:
    """기존 테이블에 누락된 컬럼을 추가하는 마이그레이션 목록.
    각 항목: (컬럼 존재 확인용 컬럼명, ALTER TABLE 구문)
    """
    return [
        ("creation_mode",  "ALTER TABLE daily_trading_plans ADD COLUMN creation_mode TEXT NOT NULL DEFAULT 'auto'"),
        ("created_by",     "ALTER TABLE daily_trading_plans ADD COLUMN created_by TEXT NOT NULL DEFAULT 'scheduler'"),
        ("trigger_source", "ALTER TABLE daily_trading_plans ADD COLUMN trigger_source TEXT NOT NULL DEFAULT 'auto_scheduler'"),
        ("run_audit_id",   "ALTER TABLE daily_trading_plans ADD COLUMN run_audit_id TEXT NOT NULL DEFAULT ''"),
        ("s3_result_id",   "ALTER TABLE daily_trading_plans ADD COLUMN s3_result_id TEXT NOT NULL DEFAULT ''"),
        ("s4_result_id",   "ALTER TABLE daily_trading_plans ADD COLUMN s4_result_id TEXT NOT NULL DEFAULT ''"),
        ("used_learning_memory_ids", "ALTER TABLE daily_trading_plans ADD COLUMN used_learning_memory_ids TEXT NOT NULL DEFAULT '[]'"),
        ("used_knowledge_ids", "ALTER TABLE daily_trading_plans ADD COLUMN used_knowledge_ids TEXT NOT NULL DEFAULT '[]'"),
        ("validated_at",   "ALTER TABLE daily_trading_plans ADD COLUMN validated_at TEXT"),
        ("superseded_at",  "ALTER TABLE daily_trading_plans ADD COLUMN superseded_at TEXT"),
    ]


def _daily_review_migration_statements() -> list[tuple[str, str]]:
    """Return migrations for S10 review report fields added after Phase 3."""
    return [
        ("missed_entries", "ALTER TABLE daily_review_reports ADD COLUMN missed_entries TEXT NOT NULL DEFAULT '[]'"),
        ("false_positives", "ALTER TABLE daily_review_reports ADD COLUMN false_positives TEXT NOT NULL DEFAULT '[]'"),
        ("missed_entries_count", "ALTER TABLE daily_review_reports ADD COLUMN missed_entries_count INTEGER NOT NULL DEFAULT 0"),
        ("false_positive_count", "ALTER TABLE daily_review_reports ADD COLUMN false_positive_count INTEGER NOT NULL DEFAULT 0"),
    ]


def _trading_signal_migration_statements() -> list[tuple[str, str]]:
    """Return migrations that keep trading_signals compatible with review/calibration phases."""
    return [
        ("profile_assigned", "ALTER TABLE trading_signals ADD COLUMN profile_assigned TEXT NOT NULL DEFAULT 'MID_VOL'"),
        ("realized_pnl", "ALTER TABLE trading_signals ADD COLUMN realized_pnl REAL"),
    ]
