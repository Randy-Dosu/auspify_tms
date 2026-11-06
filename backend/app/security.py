"""Authentication & authorization primitives.

* bcrypt password hashing (never store or log plain passwords)
* a password policy enforced on every account creation
* JWT setup helpers and a logout blocklist
* ``role_required`` for role-based access control
"""

import re
from datetime import datetime, timezone
from functools import wraps

import bcrypt
from flask import abort, current_app, g, jsonify
from flask_jwt_extended import (
    create_access_token,
    get_jwt,
    get_jwt_identity,
    jwt_required,
    verify_jwt_in_request,
)

from .db import get_db

BCRYPT_ROUNDS = 12
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    """Return a bcrypt hash (cost 12) for a plain-text password."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time bcrypt comparison."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def password_policy_error(password: str):
    """Return a human-readable policy violation, or None when acceptable.

    Policy: >= 8 characters (and <= 72 bytes, bcrypt's input limit), at least
    one letter and at least one digit.
    """
    if not isinstance(password, str) or not password:
        return "Password is required."
    if len(password.encode("utf-8")) > 72:
        return "Password must be at most 72 characters."
    if len(password) < 8:
        return "Password must be at least 8 characters long."
    if not re.search(r"[A-Za-z]", password):
        return "Password must contain at least one letter."
    if not re.search(r"[0-9]", password):
        return "Password must contain at least one number."
    return None


def is_valid_email(email: str) -> bool:
    return bool(email) and bool(_EMAIL_RE.match(email)) and len(email) <= 254


# ---------------------------------------------------------------------------
# Time helpers (all timestamps are UTC ISO-8601)
# ---------------------------------------------------------------------------
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: datetime) -> str:
    """Serialise a datetime as UTC ISO-8601 with an explicit offset."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def from_iso(value):
    """Parse an ISO-8601 string (accepts 'Z'); returns aware UTC or None."""
    if not value:
        return None
    try:
        text = value.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
    except (ValueError, AttributeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
PUBLIC_USER_FIELDS = ("id", "full_name", "email", "role", "is_active", "created_at")


def serialise_user(row) -> dict:
    """Whitelisted user representation - never includes password_hash."""
    return {field: row[field] for field in PUBLIC_USER_FIELDS if field in row.keys()}


def find_user_by_email(email: str):
    return get_db().execute(
        "SELECT * FROM users WHERE email = ?", ((email or "").strip().lower(),)
    ).fetchone()


def find_user_by_id(user_id):
    try:
        ident = int(user_id)
    except (TypeError, ValueError):
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (ident,)).fetchone()


def current_user():
    """The authenticated user row for this request (cached on ``g``)."""
    if "current_user" in g:
        return g.current_user
    user = find_user_by_id(get_jwt_identity())
    g.current_user = user
    return user


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------
def issue_access_token(user) -> str:
    """Create a short-lived access token carrying the user id and role."""
    return create_access_token(
        identity=str(user["id"]),
        additional_claims={"role": user["role"], "email": user["email"]},
    )


def init_jwt(app) -> None:
    """Configure Flask-JWT-Extended, including the logout blocklist check."""
    from flask_jwt_extended import JWTManager

    jwt = JWTManager(app)

    @jwt.token_in_blocklist_loader
    def is_token_revoked(_header, payload) -> bool:
        """True when the token was revoked by logout."""
        row = get_db().execute(
            "SELECT 1 FROM token_blocklist WHERE jti = ?", (payload.get("jti"),)
        ).fetchone()
        return row is not None

    @jwt.revoked_token_loader
    def revoked(_header, _payload):
        return jsonify({"error": {"code": 401, "message": "Token has been revoked."}}), 401

    @jwt.unauthorized_loader
    def missing(_reason):
        return jsonify({"error": {"code": 401, "message": "Authentication required."}}), 401

    @jwt.invalid_token_loader
    def invalid(_reason):
        return jsonify({"error": {"code": 401, "message": "Invalid token."}}), 401

    @jwt.expired_token_loader
    def expired(_header, _payload):
        return jsonify({"error": {"code": 401, "message": "Token has expired."}}), 401

    return jwt


def revoke_current_token(user_id) -> None:
    """Insert the current token's jti into the blocklist (logout)."""
    claims = get_jwt()
    jti = claims.get("jti")
    exp = claims.get("exp")
    expires_at = (
        to_iso(datetime.fromtimestamp(exp, tz=timezone.utc))
        if isinstance(exp, (int, float))
        else to_iso(utcnow())
    )
    get_db().execute(
        "INSERT OR IGNORE INTO token_blocklist (jti, user_id, expires_at) VALUES (?, ?, ?)",
        (jti, user_id, expires_at),
    )


# ---------------------------------------------------------------------------
# Authorization decorators
# ---------------------------------------------------------------------------
def role_required(*roles):
    """Require a valid token AND one of ``roles``.

    Returns 401 without/with an invalid token, 403 when the role is wrong or
    the account has been deactivated. Ordered checks: authentication before
    authorization, so a wrong role never reveals whether the role exists.
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            user = current_user()
            if user is None:
                return jsonify({"error": {"code": 401, "message": "Authentication required."}}), 401
            if not user["is_active"]:
                return (
                    jsonify({"error": {"code": 403, "message": "Account is disabled."}}),
                    403,
                )
            # The role claim is only a hint; the database row is authoritative.
            if user["role"] not in roles:
                return (
                    jsonify(
                        {"error": {"code": 403, "message": "You do not have permission to do that."}}
                    ),
                    403,
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def jwt_required_json(fn):
    """``jwt_required`` that also rejects disabled accounts."""

    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        user = current_user()
        if user is None or not user["is_active"]:
            return jsonify({"error": {"code": 403, "message": "Account is unavailable."}}), 403
        return fn(*args, **kwargs)

    return wrapper


def abort_json(code: int, message: str):
    """Abort with our JSON error envelope."""
    abort(code, description=message)
