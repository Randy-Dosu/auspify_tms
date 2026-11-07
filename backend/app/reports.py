"""Report calculations (Step 4).

All numbers are derived from the database with parameterised SQL; nothing is
cached, so a report always matches the underlying attempts. Reports only ever
include *graded* attempts (status submitted/expired).

Statistics used on the exam report:
  * average / highest / lowest percentage
  * median percentage (mean of the two middle values for an even count)
  * pass rate = passed attempts / graded attempts * 100
  * score distribution in five percentage bands
  * per-question difficulty = % of graded attempts that answered correctly
"""

import csv
import io
from statistics import median

from .db import get_db

DISTRIBUTION_BANDS = [
    ("0-20%", 0, 20),
    ("21-40%", 20, 40),
    ("41-60%", 40, 60),
    ("61-80%", 60, 80),
    ("81-100%", 80, 100.0001),
]


def _graded_attempts(exam_id):
    return get_db().execute(
        "SELECT * FROM attempts WHERE exam_id = ? AND status IN ('submitted', 'expired')"
        " ORDER BY submitted_at",
        (exam_id,),
    ).fetchall()


def exam_report(exam_id: int) -> dict:
    """Aggregate statistics for one exam. An exam without attempts -> zeros."""
    db = get_db()
    exam = db.execute("SELECT * FROM exams WHERE id = ?", (exam_id,)).fetchone()
    attempts = _graded_attempts(exam_id)
    percentages = [float(a["percentage"] or 0) for a in attempts]
    scores = [float(a["score"] or 0) for a in attempts]
    passed = sum(1 for a in attempts if a["passed"] == 1)

    if percentages:
        stats = {
            "attempt_count": len(attempts),
            "average_percentage": round(sum(percentages) / len(percentages), 2),
            "highest_percentage": round(max(percentages), 2),
            "lowest_percentage": round(min(percentages), 2),
            "median_percentage": round(float(median(percentages)), 2),
            "average_score": round(sum(scores) / len(scores), 2),
            "highest_score": round(max(scores), 2),
            "lowest_score": round(min(scores), 2),
            "passed_count": passed,
            "failed_count": len(attempts) - passed,
            "pass_rate": round(passed / len(attempts) * 100, 2),
        }
    else:
        stats = {
            "attempt_count": 0,
            "average_percentage": 0.0,
            "highest_percentage": 0.0,
            "lowest_percentage": 0.0,
            "median_percentage": 0.0,
            "average_score": 0.0,
            "highest_score": 0.0,
            "lowest_score": 0.0,
            "passed_count": 0,
            "failed_count": 0,
            "pass_rate": 0.0,
        }

    distribution = []
    for label, low, high in DISTRIBUTION_BANDS:
        count = sum(1 for p in percentages if low <= p < high)
        distribution.append({"band": label, "count": count})

    questions = db.execute(
        "SELECT id, question_text, question_type, marks, position FROM questions"
        " WHERE exam_id = ? ORDER BY position, id",
        (exam_id,),
    ).fetchall()
    difficulty = []
    for question in questions:
        row = db.execute(
            """
            SELECT COUNT(*) AS graded,
                   COALESCE(SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END), 0) AS correct
            FROM answers
            WHERE question_id = ?
              AND attempt_id IN (SELECT id FROM attempts WHERE exam_id = ?
                                 AND status IN ('submitted', 'expired'))
            """,
            (question["id"], exam_id),
        ).fetchone()
        graded = row["graded"] or 0
        correct = row["correct"] or 0
        difficulty.append(
            {
                "question_id": question["id"],
                "question_text": question["question_text"],
                "question_type": question["question_type"],
                "marks": question["marks"],
                "graded_count": graded,
                "correct_count": correct,
                # Difficulty = share of graded attempts that got it right.
                "percent_correct": round(correct / graded * 100, 2) if graded else 0.0,
            }
        )

    return {
        "exam": {
            "id": exam["id"],
            "title": exam["title"],
            "subject": exam["subject"],
            "total_marks": exam["total_marks"],
            "pass_marks": exam["pass_marks"],
            "duration_minutes": exam["duration_minutes"],
            "is_published": bool(exam["is_published"]),
            "end_time": exam["end_time"],
        },
        "summary": stats,
        "distribution": distribution,
        "questions": difficulty,
    }


def student_report(student_id: int, only_exam_owner=None) -> dict:
    """A student's attempt history and trend.

    ``only_exam_owner`` restricts the history to exams created by that teacher
    (used when a teacher -- not an admin or the student -- asks).
    """
    db = get_db()
    student = db.execute(
        "SELECT id, full_name, email, role FROM users WHERE id = ?", (student_id,)
    ).fetchone()

    rows = db.execute(
        """
        SELECT a.id, a.exam_id, a.status, a.score, a.percentage, a.passed,
               a.started_at, a.submitted_at,
               e.title, e.subject, e.total_marks, e.pass_marks, e.created_by
        FROM attempts a
        JOIN exams e ON e.id = a.exam_id
        WHERE a.student_id = ? AND a.status IN ('submitted', 'expired')
        ORDER BY a.submitted_at
        """,
        (student_id,),
    ).fetchall()

    if only_exam_owner is not None:
        rows = [row for row in rows if row["created_by"] == only_exam_owner]

    history = [
        {
            "attempt_id": row["id"],
            "exam_id": row["exam_id"],
            "exam_title": row["title"],
            "subject": row["subject"],
            "status": row["status"],
            "score": row["score"],
            "percentage": row["percentage"],
            "passed": None if row["passed"] is None else bool(row["passed"]),
            "total_marks": row["total_marks"],
            "pass_marks": row["pass_marks"],
            "submitted_at": row["submitted_at"],
        }
        for row in rows
    ]

    percentages = [float(item["percentage"] or 0) for item in history]
    passed = sum(1 for item in history if item["passed"])

    summary = {
        "exams_taken": len(history),
        "average_percentage": round(sum(percentages) / len(percentages), 2) if percentages else 0.0,
        "best_percentage": round(max(percentages), 2) if percentages else 0.0,
        "worst_percentage": round(min(percentages), 2) if percentages else 0.0,
        "passed_count": passed,
        "failed_count": len(history) - passed,
        "pass_rate": round(passed / len(history) * 100, 2) if history else 0.0,
    }

    return {
        "student": {
            "id": student["id"],
            "full_name": student["full_name"],
            "email": student["email"],
        },
        "summary": summary,
        "history": history,
        "trend": [
            {
                "label": item["exam_title"],
                "submitted_at": item["submitted_at"],
                "percentage": item["percentage"],
                "score": item["score"],
            }
            for item in history
        ],
    }


def leaderboard(exam_id: int) -> dict:
    """Ranked results for one exam (highest score first, then fastest submit)."""
    db = get_db()
    exam = db.execute("SELECT * FROM exams WHERE id = ?", (exam_id,)).fetchone()
    rows = db.execute(
        """
        SELECT a.id, a.score, a.percentage, a.passed, a.submitted_at, a.status,
               u.id AS student_id, u.full_name
        FROM attempts a
        JOIN users u ON u.id = a.student_id
        WHERE a.exam_id = ? AND a.status IN ('submitted', 'expired')
        ORDER BY a.score DESC, a.percentage DESC, a.submitted_at ASC
        """,
        (exam_id,),
    ).fetchall()

    entries = [
        {
            "rank": index + 1,
            "student_id": row["student_id"],
            "student_name": row["full_name"],
            "attempt_id": row["id"],
            "score": row["score"],
            "percentage": row["percentage"],
            "passed": None if row["passed"] is None else bool(row["passed"]),
            "submitted_at": row["submitted_at"],
        }
        for index, row in enumerate(rows)
    ]
    return {
        "exam": {
            "id": exam["id"],
            "title": exam["title"],
            "total_marks": exam["total_marks"],
            "pass_marks": exam["pass_marks"],
            "end_time": exam["end_time"],
        },
        "entries": entries,
    }


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------
def _csv_safe(value):
    """Neutralise spreadsheet formula injection (CSV injection).

    A cell starting with = + - @ can execute in Excel/Sheets, so user-supplied
    text is prefixed with an apostrophe.
    """
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def to_csv(header, rows) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([_csv_safe(cell) for cell in header])
    for row in rows:
        writer.writerow([_csv_safe(cell) for cell in row])
    return buffer.getvalue()


def csv_response(payload_text: str, filename: str):
    from flask import Response

    return Response(
        payload_text,
        mimetype="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
