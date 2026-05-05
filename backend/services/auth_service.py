"""Cookie-session authentication service for the operations console."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import settings
from .db import get_connection

logger = logging.getLogger("BackendAuthService")
SESSION_COOKIE_NAME = "dantabot_session"
_HASH_ITERATIONS = 260_000


def _utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    """Serialize a datetime for SQLite storage."""
    return value.isoformat()


def hash_password(password: str) -> str:
    """Hash a password with PBKDF2-SHA256 and a per-user salt."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), _HASH_ITERATIONS)
    return f"pbkdf2_sha256${_HASH_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, encoded_hash: str) -> bool:
    """Compare a password with the stored PBKDF2 hash without leaking timing details."""
    try:
        algorithm, iterations_text, salt, expected_hex = encoded_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations_text))
        return hmac.compare_digest(digest.hex(), expected_hex)
    except Exception:
        return False


def initialize_auth() -> None:
    """Create the first admin user when APP_ADMIN_PASSWORD is configured."""
    logger.info("START: auth.initialize_auth")
    with get_connection() as connection:
        user_count = connection.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
        if user_count > 0:
            logger.info("SUCCESS: auth.initialize_auth existing_users=%s", user_count)
            return

        if not settings.APP_ADMIN_PASSWORD:
            logger.warning("WARN: APP_ADMIN_PASSWORD is empty. Login is disabled until an admin password is configured.")
            return

        now = _iso(_utc_now())
        connection.execute(
            """
            INSERT INTO users (id, username, password_hash, role, is_active, created_at, updated_at)
            VALUES (?, ?, ?, 'admin', 1, ?, ?)
            """,
            (str(uuid.uuid4()), settings.APP_ADMIN_USERNAME, hash_password(settings.APP_ADMIN_PASSWORD), now, now),
        )
    logger.info("SUCCESS: auth.initialize_auth admin_username=%s", settings.APP_ADMIN_USERNAME)


def authenticate_user(username: str, password: str) -> dict[str, Any] | None:
    """Return an active user row when username and password are valid."""
    logger.info("START: auth.authenticate_user username=%s", username)
    if not username or not password:
        logger.warning("WARN: auth.authenticate_user empty credentials username=%s", username)
        return None

    with get_connection() as connection:
        row = connection.execute(
            "SELECT id, username, password_hash, role, is_active FROM users WHERE username = ?",
            (username,),
        ).fetchone()

    if row is None or not row["is_active"]:
        logger.warning("WARN: auth.authenticate_user user not found or inactive username=%s", username)
        return None

    if not verify_password(password, row["password_hash"]):
        logger.warning("WARN: auth.authenticate_user wrong password username=%s", username)
        return None

    logger.info("SUCCESS: auth.authenticate_user username=%s", username)
    return {"id": row["id"], "username": row["username"], "role": row["role"]}


def create_session(user_id: str) -> str:
    """Create a database-backed session and return its opaque session id."""
    logger.info("START: auth.create_session user_id=%s", user_id)
    now = _utc_now()
    expires_at = now + timedelta(hours=max(1, settings.APP_SESSION_TTL_HOURS))
    session_id = secrets.token_urlsafe(32)
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO sessions (id, user_id, created_at, expires_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, user_id, _iso(now), _iso(expires_at), _iso(now)),
        )
    logger.info("SUCCESS: auth.create_session user_id=%s", user_id)
    return session_id


def get_session_user(session_id: str | None) -> dict[str, Any] | None:
    """Resolve a valid session cookie into the current user."""
    if not session_id:
        return None
    now = _utc_now()
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT sessions.id AS session_id, sessions.expires_at, users.id, users.username, users.role, users.is_active
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.id = ?
            """,
            (session_id,),
        ).fetchone()
        if row is None or not row["is_active"]:
            return None
        expires_at = datetime.fromisoformat(row["expires_at"])
        if expires_at <= now:
            connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            return None
        connection.execute("UPDATE sessions SET last_seen_at = ? WHERE id = ?", (_iso(now), session_id))
    return {"id": row["id"], "username": row["username"], "role": row["role"]}


def delete_session(session_id: str | None) -> None:
    """Delete one session id when a user logs out."""
    if not session_id:
        return
    logger.info("START: auth.delete_session")
    with get_connection() as connection:
        connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    logger.info("SUCCESS: auth.delete_session")
