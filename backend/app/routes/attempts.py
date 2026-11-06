"""Taking an exam: start, autosave answers, submit.

Every timing decision is made here on the server. The browser countdown is a
convenience; if it is tampered with, or the tab is suspended, these checks
still reject late writes and close the attempt.

POST /api/exams/<id>/start        create (or resume) an attempt
GET  /api/attempts/<id>           resume payload: questions, saved answers, time left
PUT  /api/attempts/<id>/answer    autosave one answer
POST /api/attempts/<id>/submit    finish the attempt
"""

from flask import Blueprint, jsonify, request
from marshmallow import ValidationError
from werkzeug.exceptions import BadRequest

from ..db import get_db, transaction
from ..schemas import AnswerSchema
from ..security import current_user, role_required, to_iso, utcnow
from ..services import (
    attempt_time_state,
    exam_is_visible_to_student,
    exam_window_state,
    fetch_answers,
    fetch_attempt,
    fetch_exam,
    fetch_options,
    find_existing_attempt,
    serialise_attempt,
    serialise_exam,
    serialise_exam_questions,
)
from .exams import error, json_body, validation_error

bp = Blueprint("attempts", __name__, url_prefix="/api")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _owned_attempt_or_none(attempt_id):
    """Fetch an attempt belonging to the caller (404 otherwise).

    404 rather than 403 so a student cannot probe which attempt ids exist.
    """
    attempt = fetch_attempt(attempt_id)
    if attempt is None or attempt["student_id"] != current_user()["id"]:
        return None
    return attempt


def _finalise_attempt(attempt, exam, status: str):
    """Close an attempt (submitted or expired).

    The UPDATE is guarded by ``status = 'in_progress'`` so a double submit
    cannot close the attempt twice.
    """
    now = to_iso(utcnow())
    with transaction() as tx:
        tx.execute(
            "UPDATE attempts SET status = ?, submitted_at = ? WHERE id = ? AND status = 'in_progress'",
            (status, now, attempt["id"]),
        )

    return fetch_attempt(attempt["id"])


def _auto_submit_if_expired(attempt, exam):
    """Close an in-progress attempt whose server-side deadline has passed."""
    if attempt["status"] != "in_progress":
        return attempt
    state = attempt_time_state(attempt, exam)
    if state["expired"]:
        return _finalise_attempt(attempt, exam, "expired")
    return attempt


def _attempt_payload(attempt, exam) -> dict:
    """Student-facing attempt state - answers always stripped of is_correct."""
    questions = serialise_exam_questions(exam["id"], include_correct=False)
    return {
        "attempt": serialise_attempt(attempt),
        "exam": {
            "id": exam["id"],
            "title": exam["title"],
            "description": exam["description"],
            "subject": exam["subject"],
            "duration_minutes": exam["duration_minutes"],
            "total_marks": exam["total_marks"],
            "pass_marks": exam["pass_marks"],
            "end_time": exam["end_time"],
        },
        "questions": questions,
        "answers": fetch_answers(attempt["id"]),
        "time": attempt_time_state(attempt, exam),
    }


# ---------------------------------------------------------------------------
# Start / resume
# ---------------------------------------------------------------------------
@bp.post("/exams/<int:exam_id>/start")
@role_required("student")
def start_attempt(exam_id):
    exam = fetch_exam(exam_id)
    if exam is None or not exam["is_published"]:
        return error(404, "Exam not found.")

    window = exam_window_state(exam)
    if not window["available"]:
        return error(403, window["reason"])

    question_count = get_db().execute(
        "SELECT COUNT(*) AS c FROM questions WHERE exam_id = ?", (exam_id,)
    ).fetchone()["c"]
    if question_count == 0:
        return error(409, "This exam has no questions yet.")

    student_id = current_user()["id"]
    existing = find_existing_attempt(exam_id, student_id)

    if existing is not None:
        if existing["status"] == "in_progress":
            existing = _auto_submit_if_expired(existing, exam)
            if existing["status"] == "in_progress":
                # Resuming an open attempt is not a "second attempt".
                return jsonify(_attempt_payload(existing, exam)), 200
        if not exam["allow_retakes"]:
            return (
                jsonify(
                    {
                        "error": {
                            "code": 409,
                            "message": "You have already attempted this exam.",
                        },
                        "attempt": serialise_attempt(existing),
                    }
                ),
                409,
            )

    # BEGIN IMMEDIATE takes the write lock, so two simultaneous "start" calls
    # cannot both create an attempt.
    with transaction() as tx:
        latest = tx.execute(
            "SELECT * FROM attempts WHERE exam_id = ? AND student_id = ?"
            " AND status = 'in_progress' LIMIT 1",
            (exam_id, student_id),
        ).fetchone()
        if latest is not None:
            attempt_id = latest["id"]
        else:
            cursor = tx.execute(
                "INSERT INTO attempts (exam_id, student_id, started_at, status)"
                " VALUES (?, ?, ?, 'in_progress')",
                (exam_id, student_id, to_iso(utcnow())),
            )
            attempt_id = cursor.lastrowid

    attempt = fetch_attempt(attempt_id)
    return jsonify(_attempt_payload(attempt, exam)), 201


@bp.get("/attempts/<int:attempt_id>")
@role_required("student")
def get_attempt(attempt_id):
    attempt = _owned_attempt_or_none(attempt_id)
    if attempt is None:
        return error(404, "Attempt not found.")

    exam = fetch_exam(attempt["exam_id"])
    if exam is None:
        return error(404, "Exam not found.")

    attempt = _auto_submit_if_expired(attempt, exam)
    payload = _attempt_payload(attempt, exam)
    if attempt["status"] != "in_progress":
        # The attempt is closed: the result endpoint (Step 3) has the detail.
        payload["result_available"] = True
    return jsonify(payload), 200


# ---------------------------------------------------------------------------
# Autosave
# ---------------------------------------------------------------------------
@bp.put("/attempts/<int:attempt_id>/answer")
@role_required("student")
def save_answer(attempt_id):
    attempt = _owned_attempt_or_none(attempt_id)
    if attempt is None:
        return error(404, "Attempt not found.")

    exam = fetch_exam(attempt["exam_id"])
    if exam is None:
        return error(404, "Exam not found.")

    if attempt["status"] != "in_progress":
        return error(409, "This attempt has already been submitted.")

    try:
        payload = AnswerSchema().load(json_body())
    except ValidationError as exc:
        return validation_error(exc)

    # Server-side timer check: reject (and close) late writes.
    attempt = _auto_submit_if_expired(attempt, exam)
    if attempt["status"] != "in_progress":
        return (
            jsonify(
                {
                    "error": {
                        "code": 409,
                        "message": "Time is up; the attempt was submitted automatically.",
                    },
                    "attempt": serialise_attempt(attempt),
                }
            ),
            409,
        )

    db = get_db()
    question = db.execute(
        "SELECT * FROM questions WHERE id = ? AND exam_id = ?",
        (payload["question_id"], exam["id"]),
    ).fetchone()
    if question is None:
        return error(404, "Question not found in this exam.")

    valid_ids = {row["id"] for row in db.execute(
        "SELECT id FROM options WHERE question_id = ?", (question["id"],)
    ).fetchall()}
    selected = list(dict.fromkeys(payload.get("selected_option_ids") or []))  # de-dupe, keep order
    if any(option_id not in valid_ids for option_id in selected):
        return error(400, "Selected option does not belong to this question.")
    if question["question_type"] in ("single_choice", "true_false") and len(selected) > 1:
        return error(400, "This question accepts a single option.")

    with transaction() as tx:
        tx.execute(
            """
            INSERT INTO answers (attempt_id, question_id, selected_option_ids)
            VALUES (?, ?, ?)
            ON CONFLICT (attempt_id, question_id)
            DO UPDATE SET selected_option_ids = excluded.selected_option_ids
            """,
            (attempt_id, question["id"], _json_dumps(selected)),
        )

    return (
        jsonify(
            {
                "question_id": question["id"],
                "selected_option_ids": selected,
                "saved_at": to_iso(utcnow()),
                "time": attempt_time_state(attempt, exam),
            }
        ),
        200,
    )


def _json_dumps(values) -> str:
    import json

    return json.dumps(values)


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------
@bp.post("/attempts/<int:attempt_id>/submit")
@role_required("student")
def submit_attempt(attempt_id):
    attempt = _owned_attempt_or_none(attempt_id)
    if attempt is None:
        return error(404, "Attempt not found.")

    exam = fetch_exam(attempt["exam_id"])
    if exam is None:
        return error(404, "Exam not found.")

    if attempt["status"] == "in_progress":
        # Late submits are accepted but recorded as expired.
        state = attempt_time_state(attempt, exam)
        attempt = _finalise_attempt(attempt, exam, "expired" if state["expired"] else "submitted")

    return jsonify(_attempt_payload(attempt, exam)), 200
