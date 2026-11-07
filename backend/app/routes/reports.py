"""Score reports (Step 4).

GET /api/reports/exam/<id>        aggregate stats for one exam
GET /api/reports/student/<id>     one student's history and trend
GET /api/reports/leaderboard/<id> ranked results for one exam

Every endpoint accepts ``?format=csv`` for a spreadsheet download.

Access rules:
  * students: only their own student report; never the exam-wide report
  * teachers: only exams they created (and students who took them)
  * admin: everything
"""

from flask import Blueprint, jsonify, request

from ..db import get_db
from ..reports import csv_response, exam_report, leaderboard, student_report, to_csv
from ..security import current_user, jwt_required_json, from_iso, utcnow
from ..services import fetch_exam

bp = Blueprint("reports", __name__, url_prefix="/api/reports")


def error(code: int, message: str):
    return jsonify({"error": {"code": code, "message": message}}), code


def wants_csv() -> bool:
    return request.args.get("format", "").lower() == "csv"


def _exam_access(exam, user):
    """Return None when allowed, otherwise an error response."""
    if user["role"] == "admin":
        return None
    if user["role"] == "teacher" and exam["created_by"] == user["id"]:
        return None
    # Students never get the exam-wide report: it would reveal other students'
    # results and the answer key via the difficulty table.
    if user["role"] == "student":
        return error(403, "Students cannot view exam-wide reports.")
    return error(403, "You can only view reports for exams you created.")


@bp.get("/exam/<int:exam_id>")
@jwt_required_json
def exam_report_endpoint(exam_id):
    user = current_user()
    exam = fetch_exam(exam_id)
    if exam is None:
        return error(404, "Exam not found.")

    failure = _exam_access(exam, user)
    if failure:
        return failure

    report = exam_report(exam_id)

    if wants_csv():
        rows = [("Metric", "Value")]
        for key, value in report["summary"].items():
            rows.append((key, value))
        rows.append(("", ""))
        rows.append(("Score band", "Attempts"))
        for band in report["distribution"]:
            rows.append((band["band"], band["count"]))
        rows.append(("", ""))
        rows.append(("Question", "Difficulty % correct", "Graded attempts", "Correct"))
        for question in report["questions"]:
            rows.append(
                (
                    question["question_text"],
                    question["percent_correct"],
                    question["graded_count"],
                    question["correct_count"],
                )
            )
        csv_text = to_csv(("Section", "Value", "", ""), rows)
        return csv_response(csv_text, f"exam-{exam_id}-report.csv")

    return jsonify(report), 200


@bp.get("/student/<int:student_id>")
@jwt_required_json
def student_report_endpoint(student_id):
    user = current_user()
    db = get_db()
    student = db.execute(
        "SELECT id, role FROM users WHERE id = ?", (student_id,)
    ).fetchone()
    if student is None or student["role"] != "student":
        return error(404, "Student not found.")

    if user["role"] == "student":
        if user["id"] != student_id:
            # 404 keeps other student ids unguessable.
            return error(404, "Student not found.")
        report = student_report(student_id)
    elif user["role"] == "admin":
        report = student_report(student_id)
    else:
        report = student_report(student_id, only_exam_owner=user["id"])
        if not report["history"]:
            return error(403, "This student has no results for your exams.")

    if wants_csv():
        rows = [
            (
                item["exam_title"],
                item["score"],
                item["total_marks"],
                item["percentage"],
                "yes" if item["passed"] else "no",
                item["status"],
                item["submitted_at"],
            )
            for item in report["history"]
        ]
        csv_text = to_csv(
            ("Exam", "Score", "Total marks", "Percentage", "Passed", "Status", "Submitted at"),
            rows,
        )
        return csv_response(csv_text, f"student-{student_id}-report.csv")

    return jsonify(report), 200


@bp.get("/leaderboard/<int:exam_id>")
@jwt_required_json
def leaderboard_endpoint(exam_id):
    user = current_user()
    exam = fetch_exam(exam_id)
    if exam is None:
        return error(404, "Exam not found.")

    if user["role"] == "admin":
        allowed = True
    elif user["role"] == "teacher":
        allowed = exam["created_by"] == user["id"]
    else:
        # A student may see the leaderboard only for an exam they sat, and only
        # after the exam window closes (so it cannot help anyone still sitting).
        end = from_iso(exam["end_time"])
        took_it = get_db().execute(
            "SELECT 1 FROM attempts WHERE exam_id = ? AND student_id = ?"
            " AND status IN ('submitted', 'expired')",
            (exam_id, user["id"]),
        ).fetchone()
        allowed = bool(took_it) and end is not None and utcnow() > end

    if not allowed:
        return error(403, "You cannot view this leaderboard.")

    board = leaderboard(exam_id)

    if wants_csv():
        rows = [
            (
                entry["rank"],
                entry["student_name"],
                entry["score"],
                entry["percentage"],
                "yes" if entry["passed"] else "no",
                entry["submitted_at"],
            )
            for entry in board["entries"]
        ]
        csv_text = to_csv(
            ("Rank", "Student", "Score", "Percentage", "Passed", "Submitted at"), rows
        )
        return csv_response(csv_text, f"leaderboard-{exam_id}.csv")

    return jsonify(board), 200
