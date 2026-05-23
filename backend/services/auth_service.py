"""Cookie-session authentication service for the operations console."""

from __future__ import annotations

import hashlib
import hmac
import base64
import io
import json
import logging
import secrets
import struct
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, urlencode

import qrcode
from qrcode.image.svg import SvgPathImage

from ..config import settings
from .db import get_connection

logger = logging.getLogger("BackendAuthService")
SESSION_COOKIE_NAME = "kairos_session"
_HASH_ITERATIONS = 260_000
_MFA_CHALLENGE_MINUTES = 10
_BACKUP_CODE_COUNT = 8


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


def hash_mfa_code(code: str) -> str:
    """Hash a short MFA backup code with the same password hashing primitive."""
    return hash_password(_normalize_mfa_code(code))


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


def verify_mfa_code(code: str, encoded_hash: str) -> bool:
    """Compare a normalized MFA code against its stored hash."""
    return verify_password(_normalize_mfa_code(code), encoded_hash)


def _normalize_mfa_code(code: str) -> str:
    """Normalize human-entered MFA codes by removing spaces and separators."""
    return str(code or "").replace(" ", "").replace("-", "").strip().upper()


def _json_dumps(value: Any) -> str:
    """Serialize MFA payloads into compact JSON text."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads(value: str | None, default: Any) -> Any:
    """Parse persisted MFA JSON with a defensive default."""
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _totp_secret() -> str:
    """Create a base32 TOTP secret compatible with authenticator apps."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _qr_svg_data_uri(value: str) -> str:
    """Render a QR code SVG as a local data URI without sending MFA secrets outside the server."""
    qr_image = qrcode.make(value, image_factory=SvgPathImage)
    output = io.BytesIO()
    qr_image.save(output)
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def _totp_code(secret: str, interval: int | None = None) -> str:
    """Return the 6-digit TOTP code for a secret and time interval."""
    counter = int(time.time() // 30) if interval is None else interval
    padded_secret = secret + "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(padded_secret, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def verify_totp(secret: str, code: str, window: int = 1) -> bool:
    """Verify a TOTP code with a small previous/next-step clock drift window."""
    normalized = _normalize_mfa_code(code)
    if not normalized.isdigit() or len(normalized) != 6:
        return False
    current = int(time.time() // 30)
    for offset in range(-window, window + 1):
        if hmac.compare_digest(_totp_code(secret, current + offset), normalized):
            return True
    return False


def _backup_code() -> str:
    """Create one readable backup code."""
    raw = secrets.token_hex(4).upper()
    return f"{raw[:4]}-{raw[4:]}"


def mfa_methods_for_user(user_id: str) -> list[dict[str, Any]]:
    """Return active MFA methods for one user."""
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, method_type, label, created_at
            FROM user_mfa_methods
            WHERE user_id = ? AND is_active = 1
            ORDER BY created_at ASC
            """,
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def create_mfa_challenge(user_id: str, purpose: str, method_type: str = "", payload: dict[str, Any] | None = None) -> str:
    """Create a short-lived MFA challenge and return its id."""
    logger.info("START: auth.create_mfa_challenge user_id=%s purpose=%s method=%s", user_id, purpose, method_type)
    now = _utc_now()
    challenge_id = secrets.token_urlsafe(24)
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO mfa_challenges
                (id, user_id, purpose, method_type, payload_json, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                challenge_id,
                user_id,
                purpose,
                method_type,
                _json_dumps(payload or {}),
                _iso(now),
                _iso(now + timedelta(minutes=_MFA_CHALLENGE_MINUTES)),
            ),
        )
    logger.info("SUCCESS: auth.create_mfa_challenge user_id=%s purpose=%s", user_id, purpose)
    return challenge_id


def _load_mfa_challenge(challenge_id: str, purpose: str) -> dict[str, Any] | None:
    """Load a valid MFA challenge row."""
    if not challenge_id:
        return None
    now = _utc_now()
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT * FROM mfa_challenges
            WHERE id = ? AND purpose = ? AND consumed_at IS NULL
            """,
            (challenge_id, purpose),
        ).fetchone()
    if row is None:
        return None
    challenge = dict(row)
    if datetime.fromisoformat(challenge["expires_at"]) <= now:
        return None
    challenge["payload"] = _json_loads(challenge.get("payload_json"), {})
    return challenge


def _consume_mfa_challenge(challenge_id: str) -> None:
    """Mark one MFA challenge as consumed."""
    with get_connection() as connection:
        connection.execute(
            "UPDATE mfa_challenges SET consumed_at = ? WHERE id = ?",
            (_iso(_utc_now()), challenge_id),
        )


def start_mfa_enrollment(challenge_id: str, method_type: str, issuer: str = "Kairos") -> dict[str, Any] | None:
    """Start enrollment for a user-selected MFA method."""
    challenge = _load_mfa_challenge(challenge_id, "enroll")
    if challenge is None:
        return None
    user = _get_user_by_id(challenge["user_id"])
    if user is None:
        return None
    if method_type == "totp":
        secret = _totp_secret()
        payload = {"secret": secret}
        new_challenge_id = create_mfa_challenge(user["id"], "enroll_totp", "totp", payload)
        label = f"{issuer}:{user['username']}"
        otpauth_uri = "otpauth://totp/" + quote(label) + "?" + urlencode(
            {
                "secret": secret,
                "issuer": issuer,
                "algorithm": "SHA1",
                "digits": 6,
                "period": 30,
            }
        )
        return {
            "challenge_id": new_challenge_id,
            "method_type": "totp",
            "secret": secret,
            "otpauth_uri": otpauth_uri,
            "qr_svg_data_uri": _qr_svg_data_uri(otpauth_uri),
        }
    if method_type == "backup_codes":
        codes = [_backup_code() for _ in range(_BACKUP_CODE_COUNT)]
        payload = {"code_hashes": [hash_mfa_code(code) for code in codes]}
        new_challenge_id = create_mfa_challenge(user["id"], "enroll_backup_codes", "backup_codes", payload)
        return {"challenge_id": new_challenge_id, "method_type": "backup_codes", "codes": codes}
    return None


def complete_mfa_enrollment(challenge_id: str, code: str = "") -> dict[str, Any] | None:
    """Verify enrollment and enable the selected MFA method."""
    totp_challenge = _load_mfa_challenge(challenge_id, "enroll_totp")
    backup_challenge = _load_mfa_challenge(challenge_id, "enroll_backup_codes")
    challenge = totp_challenge or backup_challenge
    if challenge is None:
        return None
    user_id = challenge["user_id"]
    method_type = challenge["method_type"]
    payload = challenge["payload"]

    if method_type == "totp":
        secret = str(payload.get("secret") or "")
        if not verify_totp(secret, code):
            return None
        secret_json = {"secret": secret}
        label = "Authenticator app"
    elif method_type == "backup_codes":
        code_hashes = list(payload.get("code_hashes") or [])
        normalized = _normalize_mfa_code(code)
        used_index = next(
            (index for index, code_hash in enumerate(code_hashes) if verify_mfa_code(normalized, code_hash)),
            None,
        )
        if used_index is None:
            return None
        code_hashes.pop(used_index)
        secret_json = {"code_hashes": code_hashes}
        label = "Backup codes"
    else:
        return None

    now = _iso(_utc_now())
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO user_mfa_methods
                (id, user_id, method_type, label, secret_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), user_id, method_type, label, _json_dumps(secret_json), now, now),
        )
    _consume_mfa_challenge(challenge_id)
    logger.info("SUCCESS: auth.complete_mfa_enrollment user_id=%s method=%s", user_id, method_type)
    return _get_user_by_id(user_id)


def verify_mfa_login(challenge_id: str, code: str) -> dict[str, Any] | None:
    """Verify a login MFA challenge and return the authenticated user."""
    challenge = _load_mfa_challenge(challenge_id, "login")
    if challenge is None:
        return None
    methods = mfa_methods_for_user(challenge["user_id"])
    if not methods:
        return None

    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT * FROM user_mfa_methods
            WHERE user_id = ? AND is_active = 1
            """,
            (challenge["user_id"],),
        ).fetchall()

    normalized = _normalize_mfa_code(code)
    for row in rows:
        method = dict(row)
        secret = _json_loads(method.get("secret_json"), {})
        if method["method_type"] == "totp" and verify_totp(str(secret.get("secret") or ""), normalized):
            _consume_mfa_challenge(challenge_id)
            return _get_user_by_id(challenge["user_id"])
        if method["method_type"] == "backup_codes":
            hashes = list(secret.get("code_hashes") or [])
            for index, code_hash in enumerate(hashes):
                if verify_mfa_code(normalized, code_hash):
                    hashes.pop(index)
                    with get_connection() as connection:
                        connection.execute(
                            "UPDATE user_mfa_methods SET secret_json = ?, updated_at = ? WHERE id = ?",
                            (_json_dumps({"code_hashes": hashes}), _iso(_utc_now()), method["id"]),
                        )
                    _consume_mfa_challenge(challenge_id)
                    return _get_user_by_id(challenge["user_id"])
    return None


def _get_user_by_id(user_id: str) -> dict[str, Any] | None:
    """Return a user dict by id when active."""
    with get_connection() as connection:
        row = connection.execute(
            "SELECT id, username, role, is_active FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    if row is None or not row["is_active"]:
        return None
    return {"id": row["id"], "username": row["username"], "role": row["role"]}


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
