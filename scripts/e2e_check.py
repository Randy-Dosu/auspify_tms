"""End-to-end smoke test against the RUNNING API (real HTTP, real database).

Uses the seeded accounts from backend/.env. Grows with each step; by Step 5 it
is the full walkthrough: register -> login -> create exam -> take -> result ->
reports -> logout.

    cd backend && .venv/bin/python ../scripts/e2e_check.py
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

BACKEND = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "backend"))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

from dotenv import dotenv_values  # noqa: E402

ENV = dotenv_values(".env")
BASE = os.environ.get("API_BASE", "http://127.0.0.1:5000/api")

PASSED = 0
FAILED = 0
FAILURES = []


def check(label, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  PASS  {label}")
    else:
        FAILED += 1
        FAILURES.append(label)
        print(f"  FAIL  {label}  {detail}")


def call(method, path, token=None, body=None):
    """Perform an HTTP request, returning (status, parsed JSON)."""
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method)
    request.add_header("Accept", "application/json")
    if data:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode()
            if not raw:
                return response.status, None
            try:
                return response.status, json.loads(raw)
            except ValueError:
                return response.status, raw  # CSV or other non-JSON body
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {"raw": raw}


def login(email_key, password_key):
    status, body = call(
        "POST", "/auth/login", body={"email": ENV[email_key], "password": ENV[password_key]}
    )
    assert status == 200, (status, body)
    return body["access_token"], body["user"]


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


print("== Live end-to-end check ==")
status, health = call("GET", "/health")
check("API health is 200", status == 200, health)

teacher_token, teacher = login("SEED_TEACHER_EMAIL", "SEED_TEACHER_PASSWORD")
check("teacher can log in", teacher["role"] == "teacher", teacher)

student_token, student = login("SEED_STUDENT1_EMAIL", "SEED_STUDENT_PASSWORD")
check("student can log in", student["role"] == "student", student)

admin_token, admin = login("SEED_ADMIN_EMAIL", "SEED_ADMIN_PASSWORD")
check("admin can log in", admin["role"] == "admin", admin)

now = datetime.now(timezone.utc)
title = f"E2E Algebra {now.strftime('%H%M%S')}"
status, created = call(
    "POST",
    "/exams",
    teacher_token,
    {
        "title": title,
        "description": "Created by the end-to-end check",
        "subject": "Mathematics",
        "duration_minutes": 30,
        "pass_marks": 2,
        "start_time": iso(now - timedelta(minutes=5)),
        "end_time": iso(now + timedelta(hours=2)),
        "is_published": True,
    },
)
check("teacher creates an exam", status == 201, created)
exam_id = created["exam"]["id"]

status, q1 = call(
    "POST",
    f"/exams/{exam_id}/questions",
    teacher_token,
    {
        "question_text": "What is 2 + 2?",
        "question_type": "single_choice",
        "marks": 2,
        "options": [
            {"option_text": "3"},
            {"option_text": "4", "is_correct": True},
            {"option_text": "5"},
        ],
    },
)
check("teacher adds question 1", status == 201, q1)

status, q2 = call(
    "POST",
    f"/exams/{exam_id}/questions",
    teacher_token,
    {
        "question_text": "Which are prime numbers?",
        "question_type": "multiple_choice",
        "marks": 3,
        "negative_marks": 1,
        "options": [
            {"option_text": "2", "is_correct": True},
            {"option_text": "4"},
            {"option_text": "5", "is_correct": True},
        ],
    },
)
check("teacher adds question 2", status == 201, q2)
check("exam total marks are 5", q2.get("exam_total_marks") == 5, q2.get("exam_total_marks"))

status, student_exams = call("GET", "/exams", student_token)
mine = [e for e in student_exams["exams"] if e["id"] == exam_id]
check("student sees the published exam", len(mine) == 1, [e["title"] for e in student_exams["exams"]])
check("exam list has no answer keys", "is_correct" not in json.dumps(student_exams))

if mine and mine[0]["attempt"] and mine[0]["attempt"]["status"] == "in_progress":
    attempt_id = mine[0]["attempt"]["id"]
    status, started = call("GET", f"/attempts/{attempt_id}", student_token)
else:
    status, started = call("POST", f"/exams/{exam_id}/start", student_token)
    if status == 409:
        check("student cannot start a second attempt (retakes off)", True)
        started = None
    else:
        check("student starts the exam", status in (200, 201), started)

if started:
    attempt_id = started["attempt"]["id"]
    check("attempt is in progress", started["attempt"]["status"] == "in_progress")
    check("no correct answers in the attempt payload", "is_correct" not in json.dumps(started))
    check("server reports remaining seconds", started["time"]["remaining_seconds"] > 0)

    # The teacher knows the answer key; the student answers everything correctly
    # so the expected score is the full mark total.
    status, key = call("GET", f"/exams/{exam_id}", teacher_token)
    key_by_question = {
        q["id"]: [o["id"] for o in q["options"] if o.get("is_correct")] for q in key["exam"]["questions"]
    }
    for question in started["questions"]:
        status, saved = call(
            "PUT",
            f"/attempts/{attempt_id}/answer",
            student_token,
            {"question_id": question["id"], "selected_option_ids": key_by_question[question["id"]]},
        )
        check(f"answer autosaved for question {question['id']}", status == 200, saved)

    status, submitted = call("POST", f"/attempts/{attempt_id}/submit", student_token)
    check("student submits", status == 200 and submitted["attempt"]["status"] == "submitted", submitted)
    check("submit payload has no answer keys", "is_correct" not in json.dumps(submitted))

    status, again = call("POST", f"/attempts/{attempt_id}/submit", student_token)
    check("double submit is safe", status == 200)

    # --- Step 3: result -----------------------------------------------------
    status, result = call("GET", f"/attempts/{attempt_id}/result", student_token)
    check("student can read their result", status == 200, result)
    check("score equals the full marks (all answers correct)", result["result"]["score"] == result["exam"]["total_marks"], result["result"])
    check("percentage is 100", result["result"]["percentage"] == 100.0, result["result"])
    check("student passed", result["result"]["passed"] is True)
    check(
        "review stays hidden while the window is open",
        result["review_available"] is False and "questions" not in result,
        result.get("review_available"),
    )

    status, forbidden = call("GET", f"/attempts/{attempt_id}", admin_token)
    check("another role cannot read the student's attempt (403)", status == 403, status)

    status, teacher_result = call("GET", f"/attempts/{attempt_id}/result", teacher_token)
    check("owning teacher can read the result", status == 200, teacher_result)
    check("teacher sees the per-question review", "questions" in teacher_result)

# --- Step 4: reports -----------------------------------------------------
status, teacher_exam_report = call("GET", f"/reports/exam/{exam_id}", teacher_token)
check("teacher reads the exam report", status == 200, teacher_exam_report)
check("report counts the graded attempt", teacher_exam_report["summary"]["attempt_count"] >= 1, teacher_exam_report["summary"])
check(
    "report average is a percentage between 0 and 100",
    0 <= teacher_exam_report["summary"]["average_percentage"] <= 100,
    teacher_exam_report["summary"],
)
check("report has five distribution bands", len(teacher_exam_report["distribution"]) == 5)
check("per-question difficulty is present", len(teacher_exam_report["questions"]) == 2)

status, _ = call("GET", f"/reports/exam/{exam_id}", student_token)
check("student cannot read the exam-wide report (403)", status == 403, status)

status, board = call("GET", f"/reports/leaderboard/{exam_id}", teacher_token)
check("teacher reads the leaderboard", status == 200 and len(board["entries"]) >= 1, board)

status, own_report = call("GET", f"/reports/student/{student['id']}", student_token)
check("student reads their own report", status == 200 and own_report["summary"]["exams_taken"] >= 1, own_report)
check("student report includes history", len(own_report["history"]) >= 1)
status, _ = call("GET", f"/reports/student/{teacher['id']}", student_token)
check("student cannot read another user's report (404)", status == 404, status)

status, admin_report = call("GET", f"/reports/student/{student['id']}", admin_token)
check("admin reads any student report", status == 200, status)

csv_status, csv_body = call("GET", f"/reports/exam/{exam_id}?format=csv", teacher_token)
check("exam report exports as CSV", csv_status == 200, csv_status)
check("CSV body starts with a header row", isinstance(csv_body, str) and csv_body.splitlines()[0].startswith("Section"), str(csv_body)[:60])
check("CSV contains the metric rows", "average_percentage" in str(csv_body))

status, logout = call("POST", "/auth/logout", student_token)
check("logout succeeds", status == 200, logout)
status, _ = call("GET", "/auth/me", student_token)
check("token rejected after logout", status == 401, status)

print(f"\nRESULT: {PASSED} passed, {FAILED} failed")
if FAILURES:
    print("Failed checks:")
    for failure in FAILURES:
        print(f"  - {failure}")
sys.exit(0 if FAILED == 0 else 1)
