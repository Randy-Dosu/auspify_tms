"""Shared domain helpers for exams, questions and attempts.

Keeping the SQL in one place means the same access rules and serialisation are
used by the exam, attempt and report endpoints.
"""

import json
from datetime import timedelta

from .db import get_db
from .security import from_iso, to_iso, utcnow

# ---------------------------------------------------------------------------
# Exams
# ---------------------------------------------------------------------------
PUBLIC_EXAM_FIELDS = (
    "id",
    "title",
    "description",
    "subject",
    "duration_minutes",
    "total_marks",
    "pass_marks",
    "start_time",
    "end_time",
    "is_published",
    "allow_retakes",
    "created_by",
    "created_at",
)


def fetch_exam(exam_id):
    try:
        exam_id = int(exam_id)
    except (TypeError, ValueError):
        return None
    return get_db().execute("SELECT * FROM exams WHERE id = ?", (exam_id,)).fetchone()


def serialise_exam(exam) -> dict:
    data = {field: exam[field] for field in PUBLIC_EXAM_FIELDS}
    data["is_published"] = bool(exam["is_published"])
    data["allow_retakes"] = bool(exam["allow_retakes"])
    return data


def can_manage_exam(user, exam) -> bool:
    """Admins manage every exam; teachers only their own."""
    if user is None or exam is None:
        return False
    if user["role"] == "admin":
        return True
    return user["role"] == "teacher" and exam["created_by"] == user["id"]


def exam_window_state(exam, now=None) -> dict:
    """Is the exam inside its start/end window right now?"""
    now = now or utcnow()
    start = from_iso(exam["start_time"])
    end = from_iso(exam["end_time"])
    if start and now < start:
        return {"available": False, "reason": "This exam has not started yet."}
    if end and now > end:
        return {"available": False, "reason": "This exam has closed."}
    return {"available": True, "reason": None}


def exam_is_visible_to_student(exam, now=None) -> bool:
    """Students only ever see published exams."""
    return bool(exam["is_published"]) and exam_window_state(exam, now)["available"]


def recalc_exam_total_marks(exam_id) -> float:
    """total_marks = sum(question marks); keeps the exam row consistent."""
    db = get_db()
    row = db.execute(
        "SELECT COALESCE(SUM(marks), 0) AS total FROM questions WHERE exam_id = ?", (exam_id,)
    ).fetchone()
    total = float(row["total"] or 0)
    db.execute("UPDATE exams SET total_marks = ? WHERE id = ?", (total, exam_id))
    return total


def exam_has_attempts(exam_id) -> bool:
    row = get_db().execute(
        "SELECT 1 FROM attempts WHERE exam_id = ? LIMIT 1", (exam_id,)
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Questions & options
# ---------------------------------------------------------------------------
def fetch_question(question_id):
    try:
        question_id = int(question_id)
    except (TypeError, ValueError):
        return None
    return get_db().execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()


def fetch_options(question_id, include_correct=True):
    rows = get_db().execute(
        "SELECT id, option_text, is_correct FROM options WHERE question_id = ? ORDER BY id",
        (question_id,),
    ).fetchall()
    options = []
    for row in rows:
        item = {"id": row["id"], "option_text": row["option_text"]}
        if include_correct:
            item["is_correct"] = bool(row["is_correct"])
        options.append(item)
    return options


def serialise_question(question, include_correct: bool) -> dict:
    """Serialise a question.

    ``include_correct`` MUST be False for every student-facing response:
    it is the single switch that keeps correct answers out of the API.
    """
    return {
        "id": question["id"],
        "exam_id": question["exam_id"],
        "question_text": question["question_text"],
        "question_type": question["question_type"],
        "marks": question["marks"],
        "negative_marks": question["negative_marks"],
        "position": question["position"],
        "options": fetch_options(question["id"], include_correct=include_correct),
    }


def serialise_exam_questions(exam_id, include_correct: bool):
    rows = get_db().execute(
        "SELECT * FROM questions WHERE exam_id = ? ORDER BY position, id", (exam_id,)
    ).fetchall()
    return [serialise_question(row, include_correct) for row in rows]


def correct_option_ids(question_id):
    rows = get_db().execute(
        "SELECT id FROM options WHERE question_id = ? AND is_correct = 1 ORDER BY id",
        (question_id,),
    ).fetchall()
    return {row["id"] for row in rows}


# ---------------------------------------------------------------------------
# Attempts
# ---------------------------------------------------------------------------
def fetch_attempt(attempt_id):
    try:
        attempt_id = int(attempt_id)
    except (TypeError, ValueError):
        return None
    return get_db().execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()


def serialise_attempt(attempt) -> dict:
    return {
        "id": attempt["id"],
        "exam_id": attempt["exam_id"],
        "student_id": attempt["student_id"],
        "started_at": attempt["started_at"],
        "submitted_at": attempt["submitted_at"],
        "status": attempt["status"],
        "score": attempt["score"],
        "percentage": attempt["percentage"],
        "passed": None if attempt["passed"] is None else bool(attempt["passed"]),
    }


def attempt_deadline(attempt, exam):
    """Server-authoritative deadline: start + duration, capped by exam end_time.

    The browser timer is a convenience only - every mutating request is
    validated against this value.
    """
    started = from_iso(attempt["started_at"])
    deadline = started + timedelta(minutes=exam["duration_minutes"])
    end = from_iso(exam["end_time"])
    if end and end < deadline:
        deadline = end
    return deadline


def attempt_time_state(attempt, exam, now=None) -> dict:
    now = now or utcnow()
    deadline = attempt_deadline(attempt, exam)
    remaining = max(0, int((deadline - now).total_seconds()))
    return {
        "deadline": to_iso(deadline),
        "remaining_seconds": remaining,
        "expired": remaining <= 0,
        "server_time": to_iso(now),
    }


def fetch_answers(attempt_id) -> dict:
    """{question_id: [option_id, ...]} for an attempt."""
    rows = get_db().execute(
        "SELECT question_id, selected_option_ids FROM answers WHERE attempt_id = ?",
        (attempt_id,),
    ).fetchall()
    result = {}
    for row in rows:
        try:
            result[row["question_id"]] = json.loads(row["selected_option_ids"] or "[]")
        except ValueError:
            result[row["question_id"]] = []
    return result


def find_existing_attempt(exam_id, student_id):
    return get_db().execute(
        "SELECT * FROM attempts WHERE exam_id = ? AND student_id = ?"
        " ORDER BY id DESC LIMIT 1",
        (exam_id, student_id),
    ).fetchone()
