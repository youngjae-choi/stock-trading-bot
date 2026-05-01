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
        _seed_system_settings(connection)
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


def _seed_system_settings(connection: sqlite3.Connection) -> None:
    """Insert baseline settings that make the console useful on first startup."""
    now_expr = "strftime('%Y-%m-%dT%H:%M:%fZ','now')"
    defaults = [
        ("risk.daily_loss_limit_percent", -2.0, "number", "일일 손실한도(%)"),
        ("risk.max_positions", 5, "number", "최대 동시 보유 종목 수"),
        ("risk.max_position_rate_per_stock", 0.10, "number", "종목당 최대 투자 비중"),
        ("kis.rate_limit_profile", settings.KIS_RATE_LIMIT_PROFILE, "string", "KIS 호출 제한 프로필"),
        ("engine.mode", "MONITOR", "string", "자동매매 엔진 기본 운용 모드"),
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
        "CREATE INDEX IF NOT EXISTS idx_orders_symbol_requested_at ON orders(symbol, requested_at)",
        "CREATE INDEX IF NOT EXISTS idx_fills_symbol_filled_at ON fills(symbol, filled_at)",
        "CREATE INDEX IF NOT EXISTS idx_positions_symbol_captured_at ON positions(symbol, captured_at)",
        "CREATE INDEX IF NOT EXISTS idx_market_snapshots_symbol_captured_at ON market_snapshots(symbol, captured_at)",
        "CREATE INDEX IF NOT EXISTS idx_audit_events_type_created_at ON audit_events(event_type, created_at)",
    ]
