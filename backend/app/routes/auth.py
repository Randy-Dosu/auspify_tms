"""Authentication endpoints.

POST /api/auth/register  DISABLED - students are provisioned by the SMS API
POST /api/auth/login     rate limited, account lockout after N failures
POST /api/auth/logout    revokes the presented token
GET  /api/auth/me        the caller's profile
POST /api/auth/users     admin only - create admin/teacher/student accounts
"""

from datetime import timedelta

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt, jwt_required
from marshmallow import ValidationError
from werkzeug.exceptions import BadRequest

from ..db import transaction, get_db
from ..extensions import limiter
from ..schemas import CreateUserSchema, LoginSchema
from ..security import (
    current_user,
    find_user_by_email,
    from_iso,
    hash_password,
    issue_access_token,
    revoke_current_token,
    role_required,
    serialise_user,
    to_iso,
    utcnow,
    verify_password,
)

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

# Constant dummy hash: verifying against it when the email does not exist keeps
# the response time similar, so login cannot be used as a fast user-enumeration
# oracle.
_DUMMY_HASH = "$2b$12$C6UzMDM.H6dfI/f/IKcEe.7WQ4gk5sRhB9v0ZbXmaMQnI0wZddrLu"

# One message for every credential failure - wrong email, wrong password and
# "no such user" are indistinguishable.
_INVALID_CREDENTIALS = {"error": {"code": 401, "message": "Invalid email or password."}}
_LOCKED = {
    "error": {
        "code": 429,
        "message": "Too many failed attempts. Please try again later.",
    }
}


def json_body() -> dict:
    """Parse a JSON body, rejecting malformed or non-object payloads with 400."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise BadRequest("Request body must be a JSON object.")
    return data


def _flatten(messages) -> dict:
    if isinstance(messages, dict):
        return {key: _flatten(value) for key, value in messages.items()}
    if isinstance(messages, list):
        return [str(item) for item in messages]
    return [str(messages)]


def _validate(schema, data):
    """Return (payload, error_response)."""
    try:
        return schema.load(data), None
    except ValidationError as exc:
        return None, (
            jsonify(
                {
                    "error": {
                        "code": 400,
                        "message": "Validation failed.",
                        "fields": _flatten(exc.messages),
                    }
                }
            ),
            400,
        )


def _token_response(user, status: int = 200):
    """Standard login/register success payload."""
    return (
        jsonify(
            {
                "access_token": issue_access_token(user),
                "token_type": "Bearer",
                "expires_in_minutes": current_app.config["JWT_ACCESS_TOKEN_EXPIRES_MINUTES"],
                "user": serialise_user(user),
            }
        ),
        status,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
@bp.post("/register")
@limiter.limit(lambda: current_app.config["REGISTER_RATE_LIMIT"])
def register():
    """Self-registration is disabled.

    Students are provisioned by the university's student management system
    (``POST /api/integration/students``). The route is kept so older clients get
    a clear, actionable answer instead of a confusing 404.
    """
    return (
        jsonify(
            {
                "error": {
                    "code": 403,
                    "message": (
                        "Self-registration is disabled. Student accounts are issued by "
                        "your school's student management system; staff accounts are "
                        "created by an administrator."
                    ),
                }
            }
        ),
        403,
    )


# ---------------------------------------------------------------------------
# Login / logout / me
# ---------------------------------------------------------------------------
@bp.post("/login")
@limiter.limit(lambda: current_app.config["LOGIN_RATE_LIMIT"])
def login():
    """Authenticate and return a short-lived access token."""
    payload, error = _validate(LoginSchema(), json_body())
    if error:
        return error

    email = payload["email"].strip().lower()
    password = payload["password"]
    now = utcnow()
    user = find_user_by_email(email)

    if user is not None:
        locked_until = from_iso(user["locked_until"])
        if locked_until and locked_until > now:
            return jsonify(_LOCKED), 429
        if not user["is_active"]:
            # Same generic message: a disabled account must not be discoverable.
            return jsonify(_INVALID_CREDENTIALS), 401

    candidate_hash = user["password_hash"] if user is not None else _DUMMY_HASH
    password_ok = verify_password(password, candidate_hash)

    if user is None or not password_ok:
        if user is not None:
            _record_failed_attempt(user, now)
        return jsonify(_INVALID_CREDENTIALS), 401

    # Success: clear the lockout counters.
    get_db().execute(
        "UPDATE users SET failed_login_attempts = 0, locked_until = NULL WHERE id = ?",
        (user["id"],),
    )
    user = get_db().execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    return _token_response(user)


def _record_failed_attempt(user, now) -> None:
    """Increment the failure counter, locking the account at the threshold."""
    max_attempts = current_app.config["MAX_FAILED_LOGINS"]
    lock_minutes = current_app.config["LOCKOUT_MINUTES"]
    attempts = user["failed_login_attempts"] + 1

    if attempts >= max_attempts:
        locked_until = to_iso(now + timedelta(minutes=lock_minutes))
        get_db().execute(
            "UPDATE users SET failed_login_attempts = 0, locked_until = ? WHERE id = ?",
            (locked_until, user["id"]),
        )
        current_app.logger.warning(
            "Account locked after %s failed logins (user id %s)", max_attempts, user["id"]
        )
    else:
        get_db().execute(
            "UPDATE users SET failed_login_attempts = ? WHERE id = ?",
            (attempts, user["id"]),
        )


@bp.post("/logout")
@jwt_required()
def logout():
    """Revoke the presented token so it cannot be replayed."""
    claims = get_jwt()
    revoke_current_token(claims.get("sub") or 0)
    return jsonify({"message": "Logged out."}), 200


@bp.get("/me")
@jwt_required()
def me():
    """Return the authenticated user's own profile."""
    user = current_user()
    if user is None or not user["is_active"]:
        return jsonify(_INVALID_CREDENTIALS), 401
    return jsonify({"user": serialise_user(user)}), 200


# ---------------------------------------------------------------------------
# Admin: account creation
# ---------------------------------------------------------------------------
@bp.post("/users")
@role_required("admin")
def create_user():
    """Admin-only account creation for teachers, admins and students."""
    payload, error = _validate(CreateUserSchema(), json_body())
    if error:
        return error

    if find_user_by_email(payload["email"]) is not None:
        return (
            jsonify(
                {"error": {"code": 409, "message": "An account with this email already exists."}}
            ),
            409,
        )

    with transaction() as tx:
        cursor = tx.execute(
            """
            INSERT INTO users (full_name, email, password_hash, role, is_active, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (
                payload["full_name"].strip(),
                payload["email"],
                hash_password(payload["password"]),
                payload["role"],
                to_iso(utcnow()),
            ),
        )
        user_id = cursor.lastrowid

    user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return jsonify({"user": serialise_user(user)}), 201
