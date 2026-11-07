"""Step 4 verification: score reports, access rules and CSV export.

The three graded attempts come from fixed answers, so every statistic below is
also checked against a manual SQL calculation:

    Student A: 0.5 / 6  =  8.33%   (fail)
    Student B: 6.0 / 6  = 100.0%   (pass)
    Student C: 0.0 / 6  =   0.0%   (fail)

    average  = (8.33 + 100 + 0) / 3 = 36.11
    median   = 8.33      (middle of 0, 8.33, 100)
    pass rate= 1/3 * 100 = 33.33
    bands    = 0-20: 2, 81-100: 1

    cd backend && .venv/bin/python ../scripts/verify_step4.py
"""

import csv
import io
import json
import os
import sys
import tempfile
from datetime import timedelta

BACKEND = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "backend"))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

from app import create_app  # noqa: E402
from app.config import Config  # noqa: E402
from app.db import get_db  # noqa: E402
from app.security import hash_password, to_iso, utcnow  # noqa: E402

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


def section(title):
    print(f"\n== {title} ==")


class C(Config):
    DATABASE_PATH = tempfile.mktemp(suffix=".db")
    TESTING = True
    RATELIMIT_ENABLED = False


app = create_app(C)

with app.app_context():
    db = get_db()
    for name, email, password, role in [
        ("Teacher A", "ta@t.test", "TeacherPass1", "teacher"),
        ("Teacher B", "tb@t.test", "TeacherPass1", "teacher"),
        ("Student A", "a@t.test", "StudentPass1", "student"),
        ("Student B", "b@t.test", "StudentPass1", "student"),
        ("Student C", "c@t.test", "StudentPass1", "student"),
        ("Admin", "admin@t.test", "AdminPass1", "admin"),
    ]:
        db.execute(
            "INSERT INTO users (full_name, email, password_hash, role, is_active, created_at)"
            " VALUES (?, ?, ?, ?, 1, ?)",
            (name, email, hash_password(password), role, to_iso(utcnow())),
        )
    ids = {row["email"]: row["id"] for row in db.execute("SELECT id, email FROM users").fetchall()}

client = app.test_client()


def token(email, password="StudentPass1"):
    return client.post("/api/auth/login", json={"email": email, "password": password}).get_json()["access_token"]


def auth(tok):
    return {"Authorization": f"Bearer {tok}"}


TA, TB = token("ta@t.test", "TeacherPass1"), token("tb@t.test", "TeacherPass1")
SA, SB, SC = token("a@t.test"), token("b@t.test"), token("c@t.test")
ADMIN = token("admin@t.test", "AdminPass1")

now = utcnow()


def build_exam(title, end_offset_hours=2, pass_marks=3):
    exam = client.post(
        "/api/exams",
        json={
            "title": title,
            "subject": "Mathematics",
            "duration_minutes": 30,
            "pass_marks": pass_marks,
            "is_published": True,
            "start_time": to_iso(now - timedelta(hours=1)),
            "end_time": to_iso(now + timedelta(hours=end_offset_hours)),
        },
        headers=auth(TA),
    ).get_json()["exam"]
    exam_id = exam["id"]
    questions = {}
    questions["q1"] = client.post(
        f"/api/exams/{exam_id}/questions",
        json={
            "question_text": "What is 2 + 2?",
            "question_type": "single_choice",
            "marks": 2,
            "options": [{"option_text": "3"}, {"option_text": "4", "is_correct": True}, {"option_text": "5"}],
        },
        headers=auth(TA),
    ).get_json()["question"]
    questions["q2"] = client.post(
        f"/api/exams/{exam_id}/questions",
        json={
            "question_text": "Which are prime?",
            "question_type": "multiple_choice",
            "marks": 3,
            "negative_marks": 1,
            "options": [
                {"option_text": "2", "is_correct": True},
                {"option_text": "4"},
                {"option_text": "5", "is_correct": True},
            ],
        },
        headers=auth(TA),
    ).get_json()["question"]
    questions["q3"] = client.post(
        f"/api/exams/{exam_id}/questions",
        json={
            "question_text": "A triangle has three sides.",
            "question_type": "true_false",
            "marks": 1,
            "negative_marks": 0.5,
            "options": [{"option_text": "True", "is_correct": True}, {"option_text": "False"}],
        },
        headers=auth(TA),
    ).get_json()["question"]
    return exam_id, questions


def opt(question, text):
    return next(o["id"] for o in question["options"] if o["option_text"] == text)


def take(student_token, exam_id, answers):
    attempt = client.post(f"/api/exams/{exam_id}/start", headers=auth(student_token)).get_json()["attempt"]
    for question_id, option_ids in answers:
        client.put(
            f"/api/attempts/{attempt['id']}/answer",
            json={"question_id": question_id, "selected_option_ids": option_ids},
            headers=auth(student_token),
        )
    client.post(f"/api/attempts/{attempt['id']}/submit", headers=auth(student_token))
    return attempt["id"]


section("Step 1-3 regression")
check("health 200", client.get("/api/health").status_code == 200)
check("login works", client.post("/api/auth/login", json={"email": "a@t.test", "password": "StudentPass1"}).status_code == 200)

exam_id, q = build_exam("Reported exam")
attempt_a = take(SA, exam_id, [(q["q1"]["id"], [opt(q["q1"], "4")]), (q["q2"]["id"], [opt(q["q2"], "2")]), (q["q3"]["id"], [opt(q["q3"], "False")])])
attempt_b = take(SB, exam_id, [(q["q1"]["id"], [opt(q["q1"], "4")]), (q["q2"]["id"], [opt(q["q2"], "2"), opt(q["q2"], "5")]), (q["q3"]["id"], [opt(q["q3"], "True")])])
attempt_c = take(SC, exam_id, [])
check("step 3 still grades correctly (0.5)", client.get(f"/api/attempts/{attempt_a}/result", headers=auth(SA)).get_json()["result"]["score"] == 0.5)

section("Exam report matches manual SQL")
response = client.get(f"/api/reports/exam/{exam_id}", headers=auth(TA))
check("teacher gets the exam report (200)", response.status_code == 200, response.get_json())
report = response.get_json()
summary = report["summary"]
check("attempt_count = 3", summary["attempt_count"] == 3, summary)
check("average percentage = 36.11", summary["average_percentage"] == 36.11, summary)
check("highest = 100", summary["highest_percentage"] == 100.0, summary)
check("lowest = 0", summary["lowest_percentage"] == 0.0, summary)
check("median = 8.33", summary["median_percentage"] == 8.33, summary)
check("passed_count = 1", summary["passed_count"] == 1, summary)
check("pass rate = 33.33%", summary["pass_rate"] == 33.33, summary)
check("average score = 2.17", summary["average_score"] == 2.17, summary)

with app.app_context():
    db = get_db()
    manual = db.execute(
        "SELECT COUNT(*) c, AVG(percentage) avg_p, MAX(percentage) hi, MIN(percentage) lo,"
        " SUM(passed) passed FROM attempts WHERE exam_id = ? AND status IN ('submitted','expired')",
        (exam_id,),
    ).fetchone()
    dbs = [row["percentage"] for row in db.execute(
        "SELECT percentage FROM attempts WHERE exam_id = ? AND status IN ('submitted','expired') ORDER BY percentage",
        (exam_id,),
    ).fetchall()]
check("SQL cross-check: count", manual["c"] == summary["attempt_count"], dict(manual))
check("SQL cross-check: average", round(manual["avg_p"], 2) == summary["average_percentage"], (manual["avg_p"], summary["average_percentage"]))
check("SQL cross-check: min/max", (round(manual["lo"], 2), round(manual["hi"], 2)) == (summary["lowest_percentage"], summary["highest_percentage"]))
check("SQL cross-check: passed", manual["passed"] == summary["passed_count"])
check("SQL cross-check: median", dbs[1] == summary["median_percentage"], (dbs, summary["median_percentage"]))

distribution = {band["band"]: band["count"] for band in report["distribution"]}
check("distribution has 5 bands", len(report["distribution"]) == 5, report["distribution"])
check("band 0-20% holds 2 attempts", distribution["0-20%"] == 2, distribution)
check("band 81-100% holds 1 attempt", distribution["81-100%"] == 1, distribution)

questions = {item["question_id"]: item for item in report["questions"]}
check("every question has a difficulty row", len(questions) == 3)
check("Q1 solved by 2 of 3 (66.67%)", questions[q["q1"]["id"]]["percent_correct"] == 66.67, questions[q["q1"]["id"]])
check("Q2 solved by 1 of 3 (33.33%)", questions[q["q2"]["id"]]["percent_correct"] == 33.33, questions[q["q2"]["id"]])
check("Q3 solved by 1 of 3 (33.33%)", questions[q["q3"]["id"]]["percent_correct"] == 33.33, questions[q["q3"]["id"]])

with app.app_context():
    db = get_db()
    manual_q = db.execute(
        "SELECT COUNT(*) graded, SUM(is_correct) correct FROM answers WHERE question_id = ?",
        (q["q1"]["id"],),
    ).fetchone()
check("SQL cross-check: difficulty denominator", manual_q["graded"] == 3 and questions[q["q1"]["id"]]["graded_count"] == 3)

section("Exam with no attempts")
empty_exam, _ = build_exam("Nobody took this", pass_marks=1)
empty = client.get(f"/api/reports/exam/{empty_exam}", headers=auth(TA))
empty_body = empty.get_json()
check("returns 200, not an error", empty.status_code == 200)
check("all summary numbers are zero", all(value == 0 or value == 0.0 for value in empty_body["summary"].values()), empty_body["summary"])
check("distribution is five zero bands", [band["count"] for band in empty_body["distribution"]] == [0, 0, 0, 0, 0])
check("difficulty rows are zero", all(item["percent_correct"] == 0 for item in empty_body["questions"]))
check("leaderboard of an empty exam is an empty list", client.get(f"/api/reports/leaderboard/{empty_exam}", headers=auth(TA)).get_json()["entries"] == [])
check("CSV of an empty exam still works", client.get(f"/api/reports/exam/{empty_exam}?format=csv", headers=auth(TA)).status_code == 200)

section("Student report and trend")
student_report = client.get(f"/api/reports/student/{ids['a@t.test']}", headers=auth(SA))
body = student_report.get_json()
check("student reads their own report (200)", student_report.status_code == 200, body)
check("history contains the graded attempt", len(body["history"]) == 1, body["history"])
check("history row has the exam title", body["history"][0]["exam_title"] == "Reported exam")
check("summary average equals the attempt percentage", body["summary"]["average_percentage"] == 8.33, body["summary"])
check("trend point matches history", body["trend"][0]["percentage"] == 8.33, body["trend"])
check("student cannot read another student's report (404)", client.get(f"/api/reports/student/{ids['b@t.test']}", headers=auth(SA)).status_code == 404)
check("teacher can read a student who took their exam", client.get(f"/api/reports/student/{ids['a@t.test']}", headers=auth(TA)).status_code == 200)
check("other teacher cannot read that student (403)", client.get(f"/api/reports/student/{ids['a@t.test']}", headers=auth(TB)).status_code == 403)
check("admin can read any student report", client.get(f"/api/reports/student/{ids['a@t.test']}", headers=auth(ADMIN)).status_code == 200)
check("unknown student id is 404 for admin", client.get("/api/reports/student/9999", headers=auth(ADMIN)).status_code == 404)

section("Leaderboard")
board = client.get(f"/api/reports/leaderboard/{exam_id}", headers=auth(TA)).get_json()
check("leaderboard has all three attempts", len(board["entries"]) == 3, board["entries"])
check("rank 1 is the top score", board["entries"][0]["rank"] == 1 and board["entries"][0]["score"] == 6.0, board["entries"][0])
check("entries are ordered by score descending", [e["score"] for e in board["entries"]] == [6.0, 0.5, 0.0], [e["score"] for e in board["entries"]])
check("rank 2 is the 0.5 attempt", board["entries"][1]["score"] == 0.5)
check("student names are included", all(entry["student_name"] for entry in board["entries"]))

section("Access rules")
check("student cannot read the exam-wide report (403)", client.get(f"/api/reports/exam/{exam_id}", headers=auth(SA)).status_code == 403)
check("other teacher cannot read the exam report (403)", client.get(f"/api/reports/exam/{exam_id}", headers=auth(TB)).status_code == 403)
check("admin can read the exam report", client.get(f"/api/reports/exam/{exam_id}", headers=auth(ADMIN)).status_code == 200)
check("anonymous cannot read reports (401)", client.get(f"/api/reports/exam/{exam_id}").status_code == 401)
check("student cannot read the leaderboard while the window is open (403)", client.get(f"/api/reports/leaderboard/{exam_id}", headers=auth(SA)).status_code == 403)
with app.app_context():
    get_db().execute("UPDATE exams SET end_time = ? WHERE id = ?", (to_iso(utcnow() - timedelta(minutes=1)), exam_id))
check("student who sat the exam can read it after the window closes", client.get(f"/api/reports/leaderboard/{exam_id}", headers=auth(SA)).status_code == 200)
check("unknown exam is 404", client.get("/api/reports/exam/9999", headers=auth(TA)).status_code == 404)
check("unknown exam leaderboard is 404", client.get("/api/reports/leaderboard/9999", headers=auth(TA)).status_code == 404)

section("CSV export")
csv_exam = client.get(f"/api/reports/exam/{exam_id}?format=csv", headers=auth(TA))
check("exam report CSV is 200", csv_exam.status_code == 200)
check("CSV content type is text/csv", csv_exam.headers["Content-Type"].startswith("text/csv"), csv_exam.headers.get("Content-Type"))
check("CSV is served as an attachment", "attachment" in csv_exam.headers.get("Content-Disposition", ""), csv_exam.headers.get("Content-Disposition"))
exam_rows = list(csv.reader(io.StringIO(csv_exam.get_data(as_text=True))))
check("CSV opens as rows", len(exam_rows) > 10, len(exam_rows))
check("CSV contains the average metric", any("average_percentage" in row for row in exam_rows), exam_rows[:3])
check("CSV contains the question difficulty section", any(row and row[0].startswith("What is 2 + 2") for row in exam_rows))

csv_board = client.get(f"/api/reports/leaderboard/{exam_id}?format=csv", headers=auth(TA))
board_rows = list(csv.reader(io.StringIO(csv_board.get_data(as_text=True))))
check("leaderboard CSV has a header and 3 rows", len(board_rows) == 4, board_rows)
check("leaderboard CSV header is correct", board_rows[0][:3] == ["Rank", "Student", "Score"], board_rows[0])
check("leaderboard CSV first student is the top scorer", board_rows[1][1] == "Student B", board_rows[1])

csv_student = client.get(f"/api/reports/student/{ids['a@t.test']}?format=csv", headers=auth(SA))
student_rows = list(csv.reader(io.StringIO(csv_student.get_data(as_text=True))))
check("student CSV has header + 1 attempt", len(student_rows) == 2, student_rows)
check("student CSV row has the exam title", student_rows[1][0] == "Reported exam", student_rows[1])

section("CSV injection hardening")
evil = client.post(
    "/api/exams",
    json={"title": "=cmd|' /C calc'!A0", "duration_minutes": 5, "pass_marks": 0},
    headers=auth(TA),
).get_json()["exam"]
client.post(
    f"/api/exams/{evil['id']}/questions",
    json={"question_text": "Pick one", "question_type": "single_choice", "marks": 1,
          "options": [{"option_text": "+SUM(1,1)", "is_correct": True}, {"option_text": "b"}]},
    headers=auth(TA),
)
client.put(f"/api/exams/{evil['id']}", json={"is_published": True}, headers=auth(TA))
evil_attempt = take(SC, evil["id"], [])
evil_csv = client.get(f"/api/reports/student/{ids['c@t.test']}?format=csv", headers=auth(SC))
rows = list(csv.reader(io.StringIO(evil_csv.get_data(as_text=True))))
check("CSV cells starting with '=' are neutralised", any(row and row[0].startswith("'=") for row in rows), rows)
check("the raw formula is never the first character of a cell", all(not (cell[:1] in "=+@") for row in rows for cell in row if cell))
check("graded attempt recorded for the injection exam", evil_attempt is not None)

print(f"\nRESULT: {PASSED} passed, {FAILED} failed")
if FAILURES:
    print("Failed checks:")
    for failure in FAILURES:
        print(f"  - {failure}")
sys.exit(0 if FAILED == 0 else 1)
