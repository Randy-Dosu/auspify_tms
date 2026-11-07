"""Automatic grading - server side only.

Grading rules (documented because they are a product decision):

* ``single_choice`` / ``true_false``: the selected option must be exactly the
  correct one.
* ``multiple_choice``: all-or-nothing. The selection must equal the correct set
  (no partial credit), which is the strictest, least gameable rule.
* Unanswered questions score 0 and never trigger negative marking.
* A wrong answer deducts the question's ``negative_marks`` (if any).
* The final score is floored at 0, so a student cannot go negative overall.
* ``percentage = score / total_marks * 100``; the student passes when
  ``score >= pass_marks`` (absolute marks).

Idempotency: the result is derived from the saved answers, and every run writes
the same numbers (UPDATE, never +=), so submitting twice cannot double a score.
The whole calculation runs inside one transaction.
"""

import json

from .db import get_db, transaction


def grade_attempt(attempt_id):
    """Grade an attempt in one transaction and return the updated row.

    Returns the attempt row (or None when it does not exist). An attempt that is
    still ``in_progress`` is returned untouched - it has no result yet.
    """
    db = get_db()
    attempt = db.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
    if attempt is None:
        return None
    if attempt["status"] == "in_progress":
        return attempt

    exam = db.execute("SELECT * FROM exams WHERE id = ?", (attempt["exam_id"],)).fetchone()
    if exam is None:
        return attempt

    total_marks = float(exam["total_marks"] or 0)
    pass_marks = float(exam["pass_marks"] or 0)

    with transaction() as tx:
        questions = tx.execute(
            "SELECT * FROM questions WHERE exam_id = ? ORDER BY position, id", (exam["id"],)
        ).fetchall()
        saved = {
            row["question_id"]: list(json.loads(row["selected_option_ids"] or "[]"))
            for row in tx.execute(
                "SELECT question_id, selected_option_ids FROM answers WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchall()
        }

        score = 0.0
        for question in questions:
            selected = set(saved.get(question["id"], []))
            correct = {
                row["id"]
                for row in tx.execute(
                    "SELECT id FROM options WHERE question_id = ? AND is_correct = 1",
                    (question["id"],),
                ).fetchall()
            }

            is_correct = bool(selected) and selected == correct
            if is_correct:
                awarded = float(question["marks"])
            elif selected:
                awarded = -float(question["negative_marks"] or 0)
            else:
                awarded = 0.0  # unanswered: never penalised
            score += awarded

            tx.execute(
                """
                INSERT INTO answers (attempt_id, question_id, selected_option_ids,
                                     is_correct, marks_awarded)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (attempt_id, question_id)
                DO UPDATE SET is_correct = excluded.is_correct,
                              marks_awarded = excluded.marks_awarded
                """,
                (
                    attempt_id,
                    question["id"],
                    json.dumps(sorted(selected)),
                    1 if is_correct else 0,
                    awarded,
                ),
            )

        final_score = round(max(0.0, score), 2)
        percentage = round((final_score / total_marks) * 100, 2) if total_marks > 0 else 0.0
        passed = 1 if final_score >= pass_marks else 0

        tx.execute(
            "UPDATE attempts SET score = ?, percentage = ?, passed = ? WHERE id = ?",
            (final_score, percentage, passed, attempt_id),
        )

    return db.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
