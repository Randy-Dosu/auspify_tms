"""Student Management System (SMS) integration API.

Students cannot register themselves. Their accounts are created here, by the
university's student management system, over a signed server-to-server API:

    POST /api/integration/handshake       challenge-response proof of identity
    POST /api/integration/students        create or update one student
    POST /api/integration/students/status activate / deactivate a student
    POST /api/integration/students/lookup does this student exist?

Every route is HMAC-SHA256 signed (see ``app/sms.py``) - no JWT, no session,
no browser access. Every response is signed too, so the SMS can verify that the
answer came from the real TMS.

All routes are POST so the request body is always part of the signature; a path
that carries an email address would otherwise have to be re-encoded identically
on both sides.
"""

import time

from flask import Blueprint, current_app, g, jsonify, request
from marshmallow import ValidationError
from werkzeug.exceptions import BadRequest

from ..db import transaction
from ..extensions import limiter
from ..schemas import (
    SmsHandshakeSchema,
    SmsStudentLookupSchema,
    SmsStudentSchema,
    SmsStudentStatusSchema,
)
from ..security import (
    find_user_by_email,
    hash_password,
    serialise_user,
    to_iso,
    utcnow,
)
from ..sms import handshake_challenge, sign_current_response, sms_required
from .health import API_VERSION

bp = Blueprint("integration", __name__, url_prefix="/api/integration")

OPERATIONS = [
    "handshake",
    "students.provision",
    "students.status",
    "students.lookup",
]


def _json_body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise BadRequest("Request body must be a JSON object.")
    return data


def _flatten(messages):
    if isinstance(messages, dict):
        return {key: _flatten(value) for key, value in messages.items()}
    if isinstance(messages, list):
        return [str(item) for item in messages]
    return [str(messages)]


def _validate(schema, data):
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


def _error(status: int, message: str):
    return jsonify({"error": {"code": status, "message": message}}), status


def _student_payload(row) -> dict:
    """Public view of a provisioned student - never the password hash."""
    return serialise_user(row)


@bp.after_request
def _sign_response(response):
    """Every authenticated answer carries X-TMS-Signature."""
    return sign_current_response(response)


# ---------------------------------------------------------------------------
# Handshake - the SMS verifies the TMS before it releases any student data
# ---------------------------------------------------------------------------
@bp.post("/handshake")
@limiter.limit(lambda: current_app.config["SMS_RATE_LIMIT"])
@sms_required
def handshake():
    """Sign the caller's challenge so the SMS can prove this is the real TMS."""
    payload, error = _validate(SmsHandshakeSchema(), _json_body())
    if error:
        return error

    server_time = str(int(time.time()))
    return (
        jsonify(
            {
                "service": "auspify-tms",
                "version": API_VERSION,
                "client_id": g.sms_client,
                "algorithm": "HMAC-SHA256",
                "signature_version": "v1",
                "challenge": payload["challenge"],
                "server_time": server_time,
                "signature": handshake_challenge(
                    current_app.config["SMS_CLIENT_SECRET"],
                    g.sms_client,
                    payload["challenge"],
                    server_time,
                ),
                "operations": OPERATIONS,
            }
        ),
        200,
    )


# ---------------------------------------------------------------------------
# Provisioning - create or update one student
# ---------------------------------------------------------------------------
@bp.post("/students")
@limiter.limit(lambda: current_app.config["SMS_RATE_LIMIT"])
@sms_required
def provision_student():
    """Create a student account, or update the one that already exists.

    Idempotent by email: re-sending the same record is safe, and sending a new
    password rotates the credential (and clears any lockout).
    """
    payload, error = _validate(SmsStudentSchema(), _json_body())
    if error:
        return error

    email = payload["email"]
    password = payload.get("password")
    student_number = payload.get("student_number") or None
    if student_number is not None:
        student_number = student_number.strip() or None

    from ..db import get_db  # local import keeps the module import graph flat

    db = get_db()
    existing = find_user_by_email(email)

    if existing is not None and existing["role"] != "student":
        # Never let an integration turn a staff account into a student.
        return _error(
            409,
            "This email belongs to a staff account and cannot be provisioned as a student.",
        )

    if existing is None and not password:
        return _error(400, "A password is required when creating a student.")

    if student_number is not None:
        clash = db.execute(
            "SELECT email FROM users WHERE student_number = ? AND email <> ?",
            (student_number, email),
        ).fetchone()
        if clash is not None:
            return _error(
                409,
                "That student number is already assigned to another account.",
            )

    now = to_iso(utcnow())
    provisioned_by = f"sms:{g.sms_client}"

    with transaction() as tx:
        if existing is None:
            cursor = tx.execute(
                """
                INSERT INTO users (
                    full_name, email, password_hash, role, is_active, created_at,
                    course, student_number, provisioned_by, provisioned_at
                ) VALUES (?, ?, ?, 'student', ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["full_name"].strip(),
                    email,
                    hash_password(password),
                    1 if payload["is_active"] else 0,
                    now,
                    (payload.get("course") or "").strip(),
                    student_number,
                    provisioned_by,
                    now,
                ),
            )
            user_id = cursor.lastrowid
            created = True
        else:
            user_id = existing["id"]
            created = False
            if password:
                tx.execute(
                    "UPDATE users SET password_hash = ?, failed_login_attempts = 0,"
                    " locked_until = NULL WHERE id = ?",
                    (hash_password(password), user_id),
                )
            tx.execute(
                """
                UPDATE users
                   SET full_name = ?, course = ?, student_number = ?, is_active = ?,
                       provisioned_by = ?, provisioned_at = ?
                 WHERE id = ?
                """,
                (
                    payload["full_name"].strip(),
                    (payload.get("course") or "").strip(),
                    student_number,
                    1 if payload["is_active"] else 0,
                    provisioned_by,
                    now,
                    user_id,
                ),
            )

    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    current_app.logger.info(
        "sms:%s %s student %s (%s)",
        g.sms_client,
        "created" if created else "updated",
        email,
        "active" if row["is_active"] else "inactive",
    )
    return jsonify({"created": created, "student": _student_payload(row)}), (201 if created else 200)


# ---------------------------------------------------------------------------
# Status / lookup
# ---------------------------------------------------------------------------
@bp.post("/students/status")
@limiter.limit(lambda: current_app.config["SMS_RATE_LIMIT"])
@sms_required
def set_student_status():
    """Activate or deactivate a provisioned student (e.g. on withdrawal)."""
    payload, error = _validate(SmsStudentStatusSchema(), _json_body())
    if error:
        return error

    from ..db import get_db

    db = get_db()
    row = find_user_by_email(payload["email"])
    if row is None:
        return _error(404, "No student with that email has been provisioned.")
    if row["role"] != "student":
        return _error(409, "That account is not a student account.")

    active = 1 if payload["is_active"] else 0
    with transaction() as tx:
        tx.execute("UPDATE users SET is_active = ? WHERE id = ?", (active, row["id"]))
        if active:
            # Re-admitting a student must not leave them locked out.
            tx.execute(
                "UPDATE users SET failed_login_attempts = 0, locked_until = NULL WHERE id = ?",
                (row["id"],),
            )

    row = db.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
    current_app.logger.info(
        "sms:%s %s student %s", g.sms_client, "activated" if active else "deactivated", row["email"]
    )
    return jsonify({"student": _student_payload(row)}), 200


@bp.post("/students/lookup")
@limiter.limit(lambda: current_app.config["SMS_RATE_LIMIT"])
@sms_required
def lookup_student():
    """Report whether a student exists without disclosing staff accounts."""
    payload, error = _validate(SmsStudentLookupSchema(), _json_body())
    if error:
        return error

    row = find_user_by_email(payload["email"])
    if row is None or row["role"] != "student":
        return jsonify({"exists": False, "student": None}), 200
    return jsonify({"exists": True, "student": _student_payload(row)}), 200
