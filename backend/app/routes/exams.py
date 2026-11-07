"""Exam, question and option management.

Staff (teacher/admin) endpoints - full CRUD, ownership enforced:
    GET    /api/exams                 list (staff see their own, admin all)
    POST   /api/exams                 create
    GET    /api/exams/<id>            detail (+ questions with is_correct)
    PUT    /api/exams/<id>            update
    DELETE /api/exams/<id>            delete (refused once attempts exist)
    GET    /api/exams/<id>/questions  questions (answers included - staff only)
    POST   /api/exams/<id>/questions  add question + options
    PUT    /api/questions/<qid>       replace a question + options
    DELETE /api/questions/<qid>       delete a question

Student endpoints:
    GET    /api/exams                 published + currently open exams only
    GET    /api/exams/<id>            published exam, answers stripped

Correct answers are included in a response only when the caller is staff.
"""

from flask import Blueprint, jsonify, request
from marshmallow import ValidationError
from werkzeug.exceptions import BadRequest

from ..db import get_db, transaction
from ..schemas import ExamSchema, QuestionSchema
from ..security import current_user, jwt_required_json, role_required, to_iso, utcnow
from ..services import (
    can_manage_exam,
    exam_has_attempts,
    exam_is_visible_to_student,
    exam_window_state,
    fetch_exam,
    fetch_question,
    find_existing_attempt,
    recalc_exam_total_marks,
    serialise_exam,
    serialise_exam_questions,
)

bp = Blueprint("exams", __name__, url_prefix="/api")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def json_body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise BadRequest("Request body must be a JSON object.")
    return data


def validation_error(exc: ValidationError):
    return (
        jsonify(
            {
                "error": {
                    "code": 400,
                    "message": "Validation failed.",
                    "fields": exc.messages,
                }
            }
        ),
        400,
    )


def error(code: int, message: str):
    return jsonify({"error": {"code": code, "message": message}}), code


def load_exam_for_staff(exam_id):
    """Return (exam, error_response). Enforces existence + ownership."""
    exam = fetch_exam(exam_id)
    if exam is None:
        return None, error(404, "Exam not found.")
    if not can_manage_exam(current_user(), exam):
        # 403 (not 404): the caller is authenticated staff, just not the owner.
        return None, error(403, "You can only manage exams you created.")
    return exam, None


def _exam_summary(exam, include_counts: bool) -> dict:
    data = serialise_exam(exam)
    if include_counts:
        db = get_db()
        data["question_count"] = db.execute(
            "SELECT COUNT(*) AS c FROM questions WHERE exam_id = ?", (exam["id"],)
        ).fetchone()["c"]
        data["attempt_count"] = db.execute(
            "SELECT COUNT(*) AS c FROM attempts WHERE exam_id = ?", (exam["id"],)
        ).fetchone()["c"]
    return data


def _validate_exam_payload(payload: dict, existing=None):
    """Business validation applied after schema shape validation."""
    merged = dict(payload)
    if existing is not None:
        # Partial update: validate the *result*, not just the patch.
        merged = {
            "title": existing["title"],
            "description": existing["description"],
            "subject": existing["subject"],
            "duration_minutes": existing["duration_minutes"],
            "pass_marks": existing["pass_marks"],
            "start_time": existing["start_time"],
            "end_time": existing["end_time"],
            "is_published": bool(existing["is_published"]),
            "allow_retakes": bool(existing["allow_retakes"]),
        }
        merged.update(payload)

    if existing is None:
        capped = None
    else:
        capped = existing["total_marks"]

    pass_marks = merged.get("pass_marks", 0)
    if capped is not None and not merged.get("is_published") and pass_marks > capped:
        # Draft exams may be prepared ahead of their questions; only published
        # ones must be internally consistent.
        return merged, None
    if capped is not None and pass_marks > capped and capped > 0:
        return merged, error(400, "Pass marks cannot exceed the exam total marks.")
    return merged, None


# ---------------------------------------------------------------------------
# Exam collection
# ---------------------------------------------------------------------------
@bp.get("/exams")
@jwt_required_json
def list_exams():
    """Role-aware exam list."""
    user = current_user()
    db = get_db()
    now = utcnow()

    if user["role"] == "student":
        rows = db.execute(
            "SELECT * FROM exams WHERE is_published = 1 ORDER BY COALESCE(start_time, created_at) DESC"
        ).fetchall()
        exams = []
        for row in rows:
            if not exam_is_visible_to_student(row, now):
                continue
            item = _exam_summary(row, include_counts=False)
            attempt = find_existing_attempt(row["id"], user["id"])
            item["attempt"] = None
            if attempt is not None:
                item["attempt"] = {
                    "id": attempt["id"],
                    "status": attempt["status"],
                    "submitted_at": attempt["submitted_at"],
                }
            exams.append(item)
        return jsonify({"exams": exams}), 200

    if user["role"] == "admin":
        rows = db.execute("SELECT * FROM exams ORDER BY created_at DESC").fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM exams WHERE created_by = ? ORDER BY created_at DESC", (user["id"],)
        ).fetchall()
    return jsonify({"exams": [_exam_summary(row, include_counts=True) for row in rows]}), 200


@bp.post("/exams")
@role_required("teacher", "admin")
def create_exam():
    try:
        payload = ExamSchema().load(json_body())
    except ValidationError as exc:
        return validation_error(exc)

    if payload["pass_marks"] and payload["pass_marks"] <= 0:
        return error(400, "Pass marks must be greater than zero.")

    with transaction() as tx:
        cursor = tx.execute(
            """
            INSERT INTO exams (title, description, subject, duration_minutes, total_marks,
                               pass_marks, start_time, end_time, is_published, allow_retakes,
                               created_by, created_at)
            VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["title"].strip(),
                payload["description"] or "",
                payload["subject"] or "",
                payload["duration_minutes"],
                payload["pass_marks"],
                payload["start_time"] or None,
                payload["end_time"] or None,
                1 if payload["is_published"] else 0,
                1 if payload["allow_retakes"] else 0,
                current_user()["id"],
                to_iso(utcnow()),
            ),
        )
        exam_id = cursor.lastrowid

    return jsonify({"exam": _exam_summary(fetch_exam(exam_id), include_counts=True)}), 201


# ---------------------------------------------------------------------------
# Single exam
# ---------------------------------------------------------------------------
@bp.get("/exams/<int:exam_id>")
@jwt_required_json
def get_exam(exam_id):
    exam = fetch_exam(exam_id)
    if exam is None:
        return error(404, "Exam not found.")

    user = current_user()
    staff = user["role"] in ("teacher", "admin")

    if staff:
        if not can_manage_exam(user, exam):
            return error(403, "You can only view exams you created.")
        data = _exam_summary(exam, include_counts=True)
        data["questions"] = serialise_exam_questions(exam["id"], include_correct=True)
        return jsonify({"exam": data}), 200

    # Student view: only published/available exams, never with answers.
    if user["role"] != "student" or not exam_is_visible_to_student(exam):
        return error(404, "Exam not found.")
    data = _exam_summary(exam, include_counts=False)
    data["questions"] = serialise_exam_questions(exam["id"], include_correct=False)
    data["attempt"] = None
    attempt = find_existing_attempt(exam["id"], user["id"])
    if attempt is not None:
        data["attempt"] = {
            "id": attempt["id"],
            "status": attempt["status"],
            "submitted_at": attempt["submitted_at"],
        }
    return jsonify({"exam": data}), 200


@bp.put("/exams/<int:exam_id>")
@role_required("teacher", "admin")
def update_exam(exam_id):
    exam, failure = load_exam_for_staff(exam_id)
    if failure:
        return failure

    body = json_body()
    try:
        payload = ExamSchema().load(body, partial=True)
    except ValidationError as exc:
        return validation_error(exc)

    if not payload:
        return error(400, "No editable fields supplied.")

    merged, failure = _validate_exam_payload(payload, existing=exam)
    if failure:
        return failure

    # Window ordering must hold against the merged result.
    from ..security import from_iso

    start, end = from_iso(merged.get("start_time")), from_iso(merged.get("end_time"))
    if start and end and end <= start:
        return error(400, "end_time must be after start_time.")

    if merged.get("is_published") and not exam_has_attempts(exam_id):
        # Publishing is fine; guard is only about changing questions later.
        pass

    with transaction() as tx:
        tx.execute(
            """
            UPDATE exams SET title = ?, description = ?, subject = ?, duration_minutes = ?,
                             pass_marks = ?, start_time = ?, end_time = ?, is_published = ?,
                             allow_retakes = ?
            WHERE id = ?
            """,
            (
                str(merged["title"]).strip(),
                merged.get("description") or "",
                merged.get("subject") or "",
                int(merged["duration_minutes"]),
                float(merged.get("pass_marks") or 0),
                merged.get("start_time") or None,
                merged.get("end_time") or None,
                1 if merged.get("is_published") else 0,
                1 if merged.get("allow_retakes") else 0,
                exam_id,
            ),
        )

    return jsonify({"exam": _exam_summary(fetch_exam(exam_id), include_counts=True)}), 200


@bp.delete("/exams/<int:exam_id>")
@role_required("teacher", "admin")
def delete_exam(exam_id):
    exam, failure = load_exam_for_staff(exam_id)
    if failure:
        return failure

    if exam_has_attempts(exam_id):
        # Deleting would destroy student records; require an explicit archive.
        return error(409, "This exam has attempts and cannot be deleted.")

    with transaction() as tx:
        tx.execute("DELETE FROM exams WHERE id = ?", (exam_id,))
    return jsonify({"message": "Exam deleted."}), 200


# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------
def _assert_questions_mutable(exam):
    """A published exam with attempts is frozen (exam integrity)."""
    if exam["is_published"] and exam_has_attempts(exam["id"]):
        return error(
            409,
            "This exam is published and has attempts; its questions can no longer be changed.",
        )
    return None


@bp.get("/exams/<int:exam_id>/questions")
@role_required("teacher", "admin")
def list_questions(exam_id):
    exam, failure = load_exam_for_staff(exam_id)
    if failure:
        return failure
    return jsonify({"questions": serialise_exam_questions(exam_id, include_correct=True)}), 200


@bp.post("/exams/<int:exam_id>/questions")
@role_required("teacher", "admin")
def create_question(exam_id):
    exam, failure = load_exam_for_staff(exam_id)
    if failure:
        return failure
    failure = _assert_questions_mutable(exam)
    if failure:
        return failure

    try:
        payload = QuestionSchema().load(json_body())
    except ValidationError as exc:
        return validation_error(exc)

    db = get_db()
    position = payload.get("position")
    if position is None:
        row = db.execute(
            "SELECT COALESCE(MAX(position), 0) AS p FROM questions WHERE exam_id = ?", (exam_id,)
        ).fetchone()
        position = int(row["p"]) + 1

    with transaction() as tx:
        cursor = tx.execute(
            """
            INSERT INTO questions (exam_id, question_text, question_type, marks,
                                   negative_marks, position)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                exam_id,
                payload["question_text"].strip(),
                payload["question_type"],
                payload["marks"],
                payload.get("negative_marks") or 0,
                position,
            ),
        )
        question_id = cursor.lastrowid
        for option in payload["options"]:
            tx.execute(
                "INSERT INTO options (question_id, option_text, is_correct) VALUES (?, ?, ?)",
                (question_id, option["option_text"].strip(), 1 if option["is_correct"] else 0),
            )
    recalc_exam_total_marks(exam_id)

    question = fetch_question(question_id)
    from ..services import serialise_question

    return (
        jsonify(
            {
                "question": serialise_question(question, include_correct=True),
                "exam_total_marks": fetch_exam(exam_id)["total_marks"],
            }
        ),
        201,
    )


def _load_question_for_staff(question_id):
    question = fetch_question(question_id)
    if question is None:
        return None, None, error(404, "Question not found.")
    exam, failure = load_exam_for_staff(question["exam_id"])
    if failure:
        return None, None, failure
    failure = _assert_questions_mutable(exam)
    if failure:
        return None, None, failure
    return question, exam, None


@bp.put("/questions/<int:question_id>")
@role_required("teacher", "admin")
def update_question(question_id):
    question, exam, failure = _load_question_for_staff(question_id)
    if failure:
        return failure

    try:
        payload = QuestionSchema().load(json_body())
    except ValidationError as exc:
        return validation_error(exc)

    with transaction() as tx:
        tx.execute(
            """
            UPDATE questions SET question_text = ?, question_type = ?, marks = ?,
                                 negative_marks = ?, position = ?
            WHERE id = ?
            """,
            (
                payload["question_text"].strip(),
                payload["question_type"],
                payload["marks"],
                payload.get("negative_marks") or 0,
                payload.get("position") or question["position"],
                question_id,
            ),
        )
        # Replace the option set: create / update / delete in one statement set.
        tx.execute("DELETE FROM options WHERE question_id = ?", (question_id,))
        for option in payload["options"]:
            tx.execute(
                "INSERT INTO options (question_id, option_text, is_correct) VALUES (?, ?, ?)",
                (question_id, option["option_text"].strip(), 1 if option["is_correct"] else 0),
            )
    recalc_exam_total_marks(exam["id"])

    from ..services import serialise_question

    return (
        jsonify(
            {
                "question": serialise_question(fetch_question(question_id), include_correct=True),
                "exam_total_marks": fetch_exam(exam["id"])["total_marks"],
            }
        ),
        200,
    )


@bp.delete("/questions/<int:question_id>")
@role_required("teacher", "admin")
def delete_question(question_id):
    question, exam, failure = _load_question_for_staff(question_id)
    if failure:
        return failure

    with transaction() as tx:
        tx.execute("DELETE FROM questions WHERE id = ?", (question_id,))
    recalc_exam_total_marks(exam["id"])
    return jsonify({"message": "Question deleted.", "exam_total_marks": fetch_exam(exam["id"])["total_marks"]}), 200
