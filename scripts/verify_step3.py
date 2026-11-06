"""Step 3 verification: automatic grading, idempotency, result access rules.

The scoring checks use a hand-computed expectation:

    Exam: Q1 single_choice 2 marks (neg 0), Q2 multiple_choice 3 marks (neg 1),
          Q3 true_false 1 mark (neg 0.5)          -> total 6, pass 3

    Student A: Q1 correct, Q2 partial, Q3 wrong
        +2  (Q1 correct)
        -1  (Q2 wrong, all-or-nothing, negative marks)
        -0.5(Q3 wrong, negative marks)
        = 0.5  -> 0.5/6*100 = 8.33%  -> fail

    Student B: all three correct -> 6 -> 100% -> pass
    Student C: nothing answered  -> 0 -> 0%   -> fail

    cd backend && .venv/bin/python ../scripts/verify_step3.py
"""

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

client = app.test_client()


def token(email, password="StudentPass1"):
    return client.post("/api/auth/login", json={"email": email, "password": password}).get_json()["access_token"]


def auth(tok):
    return {"Authorization": f"Bearer {tok}"}


TA, TB = token("ta@t.test", "TeacherPass1"), token("tb@t.test", "TeacherPass1")
SA, SB, SC = token("a@t.test"), token("b@t.test"), token("c@t.test")
ADMIN = token("admin@t.test", "AdminPass1")

now = utcnow()


def build_exam(title, end_offset_hours=2, duration=30, pass_marks=3):
    exam = client.post(
        "/api/exams",
        json={
            "title": title,
            "duration_minutes": duration,
            "pass_marks": pass_marks,
            "is_published": True,
            "start_time": to_iso(now - timedelta(hours=1)),
            "end_time": to_iso(now + timedelta(hours=end_offset_hours)),
        },
        headers=auth(TA),
    ).get_json()["exam"]
    exam_id = exam["id"]

    q1 = client.post(
        f"/api/exams/{exam_id}/questions",
        json={
            "question_text": "What is 2 + 2?",
            "question_type": "single_choice",
            "marks": 2,
            "options": [
                {"option_text": "3"},
                {"option_text": "4", "is_correct": True},
                {"option_text": "5"},
            ],
        },
        headers=auth(TA),
    ).get_json()["question"]
    q2 = client.post(
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
    q3 = client.post(
        f"/api/exams/{exam_id}/questions",
        json={
            "question_text": "A triangle has three sides.",
            "question_type": "true_false",
            "marks": 1,
            "negative_marks": 0.5,
            "options": [
                {"option_text": "True", "is_correct": True},
                {"option_text": "False"},
            ],
        },
        headers=auth(TA),
    ).get_json()["question"]
    return exam_id, {"q1": q1, "q2": q2, "q3": q3}


def opt(question, text):
    return next(o["id"] for o in question["options"] if o["option_text"] == text)


def correct_opt(question):
    return next(o["id"] for o in question["options"] if o.get("is_correct"))


def take(student_token, exam_id, answers_for):
    started = client.post(f"/api/exams/{exam_id}/start", headers=auth(student_token))
    attempt = started.get_json()["attempt"]
    for question_id, option_ids in answers_for(attempt["id"]):
        client.put(
            f"/api/attempts/{attempt['id']}/answer",
            json={"question_id": question_id, "selected_option_ids": option_ids},
            headers=auth(student_token),
        )
    client.post(f"/api/attempts/{attempt['id']}/submit", headers=auth(student_token))
    return attempt["id"]


section("Step 1/2 regression")
check("health 200", client.get("/api/health").status_code == 200)
check("login works", client.post("/api/auth/login", json={"email": "a@t.test", "password": "StudentPass1"}).status_code == 200)
check(
    "student exam list has no answer keys",
    "is_correct" not in json.dumps(client.get("/api/exams", headers=auth(SA)).get_json()),
)

section("Known-answer grading (manual calculation)")
exam_id, q = build_exam("Graded exam")
total = client.get(f"/api/exams/{exam_id}", headers=auth(TA)).get_json()["exam"]["total_marks"]
check("exam total marks are 6", total == 6, total)

# Student A: Q1 correct, Q2 partial, Q3 wrong  -> +2 -1 -0.5 = 0.5
attempt_a = take(
    SA,
    exam_id,
    lambda _aid: [
        (q["q1"]["id"], [opt(q["q1"], "4")]),
        (q["q2"]["id"], [opt(q["q2"], "2")]),
        (q["q3"]["id"], [opt(q["q3"], "False")]),
    ],
)
result_a = client.get(f"/api/attempts/{attempt_a}/result", headers=auth(SA))
payload_a = result_a.get_json()
check("student A gets a result (200)", result_a.status_code == 200, payload_a)
check("student A score = 0.5  (2 - 1 - 0.5)", payload_a["result"]["score"] == 0.5, payload_a["result"])
check("student A percentage = 8.33", payload_a["result"]["percentage"] == 8.33, payload_a["result"])
check("student A failed (below pass marks 3)", payload_a["result"]["passed"] is False)
check("exam average would be 0.5 for this attempt", payload_a["exam"]["total_marks"] == 6)

# Student B: everything correct -> 6
attempt_b = take(
    SB,
    exam_id,
    lambda _aid: [
        (q["q1"]["id"], [opt(q["q1"], "4")]),
        (q["q2"]["id"], [opt(q["q2"], "2"), opt(q["q2"], "5")]),
        (q["q3"]["id"], [opt(q["q3"], "True")]),
    ],
)
payload_b = client.get(f"/api/attempts/{attempt_b}/result", headers=auth(SB)).get_json()
check("student B score = 6 (all correct)", payload_b["result"]["score"] == 6, payload_b["result"])
check("student B percentage = 100.0", payload_b["result"]["percentage"] == 100.0, payload_b["result"])
check("student B passed", payload_b["result"]["passed"] is True)

# Student C: nothing answered -> 0
attempt_c = take(SC, exam_id, lambda _aid: [])
payload_c = client.get(f"/api/attempts/{attempt_c}/result", headers=auth(SC)).get_json()
check("unanswered exam scores 0", payload_c["result"]["score"] == 0, payload_c["result"])
check("unanswered exam is 0%", payload_c["result"]["percentage"] == 0.0)
check("unanswered exam fails", payload_c["result"]["passed"] is False)

section("Negative marking details")
multi_review = client.get(f"/api/attempts/{attempt_a}/result", headers=auth(TA)).get_json()
q_multi = next(item for item in multi_review["questions"] if item["id"] == q["q2"]["id"])
check("multiple choice is all-or-nothing: partial answer marked wrong", q_multi["is_correct"] is False, q_multi)
check("partial answer awards -1 (negative marks)", q_multi["marks_awarded"] == -1, q_multi["marks_awarded"])
q_tf = next(item for item in multi_review["questions"] if item["id"] == q["q3"]["id"])
check("wrong true/false deducts 0.5", q_tf["marks_awarded"] == -0.5, q_tf["marks_awarded"])
q_single = next(item for item in multi_review["questions"] if item["id"] == q["q1"]["id"])
check("correct single choice awards +2", q_single["marks_awarded"] == 2, q_single["marks_awarded"])
unanswered_review = client.get(f"/api/attempts/{attempt_c}/result", headers=auth(TA)).get_json()
check(
    "unanswered questions are not penalised",
    all(item["marks_awarded"] == 0 for item in unanswered_review["questions"]),
    [item["marks_awarded"] for item in unanswered_review["questions"]],
)

section("Score floor")
floor_exam, fq = build_exam("Floor exam", pass_marks=1)
floor_exam_id = floor_exam
attempt_floor = take(
    SA,
    floor_exam_id,
    lambda _aid: [
        (fq["q2"]["id"], [opt(fq["q2"], "4")]),  # wrong on a 3-mark / 1-negative question
        (fq["q3"]["id"], [opt(fq["q3"], "False")]),  # wrong, -0.5
    ],
)
floor_payload = client.get(f"/api/attempts/{attempt_floor}/result", headers=auth(SA)).get_json()
check("score never goes below 0", floor_payload["result"]["score"] == 0, floor_payload["result"])

section("Idempotent grading")
resubmit = client.post(f"/api/attempts/{attempt_a}/submit", headers=auth(SA))
check("second submit returns 200", resubmit.status_code == 200)
after = client.get(f"/api/attempts/{attempt_a}/result", headers=auth(SA)).get_json()
check("score unchanged after a second submit", after["result"]["score"] == 0.5, after["result"])
with app.app_context():
    row = get_db().execute("SELECT score, percentage, passed FROM attempts WHERE id = ?", (attempt_a,)).fetchone()
check("score persisted once in the database", (row["score"], row["percentage"], row["passed"]) == (0.5, 8.33, 0), dict(row))
with app.app_context():
    answer_rows = get_db().execute("SELECT COUNT(*) AS c FROM answers WHERE attempt_id = ?", (attempt_a,)).fetchone()["c"]
check("answers are not duplicated by a second submit", answer_rows == 3, answer_rows)

section("Auto-submitted (expired) attempts are graded")
timer_exam_id, tq = build_exam("Expired exam", duration=1)
started = client.post(f"/api/exams/{timer_exam_id}/start", headers=auth(SB)).get_json()
expired_attempt = started["attempt"]["id"]
client.put(
    f"/api/attempts/{expired_attempt}/answer",
    json={"question_id": tq["q1"]["id"], "selected_option_ids": [opt(tq["q1"], "4")]},
    headers=auth(SB),
)
with app.app_context():
    get_db().execute(
        "UPDATE attempts SET started_at = ? WHERE id = ?",
        (to_iso(utcnow() - timedelta(minutes=10)), expired_attempt),
    )
fetched = client.get(f"/api/attempts/{expired_attempt}", headers=auth(SB))
check("resuming an expired attempt auto-submits it", fetched.get_json()["attempt"]["status"] == "expired", fetched.get_json()["attempt"])
expired_result = client.get(f"/api/attempts/{expired_attempt}/result", headers=auth(SB))
check("expired attempt has a graded result", expired_result.status_code == 200, expired_result.get_json())
check("expired attempt is graded from the saved answer (2 marks)", expired_result.get_json()["result"]["score"] == 2, expired_result.get_json()["result"])
check("expired status is reported", expired_result.get_json()["result"]["status"] == "expired")

section("Access rules")
check("student B cannot read student A's result (404)", client.get(f"/api/attempts/{attempt_a}/result", headers=auth(SB)).status_code == 404)
check("teacher who owns the exam can read results", client.get(f"/api/attempts/{attempt_a}/result", headers=auth(TA)).status_code == 200)
check("another teacher cannot read the result (404)", client.get(f"/api/attempts/{attempt_a}/result", headers=auth(TB)).status_code == 404)
check("admin can read any result", client.get(f"/api/attempts/{attempt_a}/result", headers=auth(ADMIN)).status_code == 200)
check("anonymous cannot read a result (401)", client.get(f"/api/attempts/{attempt_a}/result").status_code == 401)

open_attempt = client.post(f"/api/exams/{exam_id}/start", headers=auth(SC))
# student C already submitted -> 409 from start; use a fresh student-free exam instead
fresh_exam_id, _ = build_exam("In progress exam", pass_marks=1)
started_fresh = client.post(f"/api/exams/{fresh_exam_id}/start", headers=auth(SC))
pending = started_fresh.get_json()["attempt"]["id"]
check("result of an in-progress attempt is 409", client.get(f"/api/attempts/{pending}/result", headers=auth(SC)).status_code == 409)

section("Review visibility (exam window must be closed)")
early = client.get(f"/api/attempts/{attempt_a}/result", headers=auth(SA)).get_json()
check("student review hidden while the exam window is open", early["review_available"] is False, early["review_available"])
check("no per-question data leaks early", "questions" not in early)
check("teacher review is available immediately", "questions" in client.get(f"/api/attempts/{attempt_a}/result", headers=auth(TA)).get_json())

with app.app_context():
    get_db().execute("UPDATE exams SET end_time = ? WHERE id = ?", (to_iso(utcnow() - timedelta(minutes=1)), exam_id))
closed = client.get(f"/api/attempts/{attempt_a}/result", headers=auth(SA)).get_json()
check("review unlocks after the window closes", closed["review_available"] is True)
check("review lists every question", len(closed["questions"]) == 3)
check("review shows the student's selection", any(item["selected_option_ids"] for item in closed["questions"]))
check("review shows correct options after closing", any(o["is_correct"] for item in closed["questions"] for o in item["options"]))

section("Server cannot be tricked into changing a submitted score")
with app.app_context():
    get_db().execute(
        "INSERT INTO answers (attempt_id, question_id, selected_option_ids) VALUES (?, ?, ?)"
        " ON CONFLICT (attempt_id, question_id) DO UPDATE SET selected_option_ids = excluded.selected_option_ids",
        (attempt_a, q["q3"]["id"], json.dumps([opt(q["q3"], "True")])),
    )
    from app.grading import grade_attempt

    grade_attempt(attempt_a)
regraded = client.get(f"/api/attempts/{attempt_a}/result", headers=auth(SA)).get_json()
# Q1 +2, Q2 -1 (still partial), Q3 now correct +1  => 2.0  (2/6 = 33.33%)
check("grading is a pure function of the stored answers", regraded["result"]["score"] == 2.0, regraded["result"])
check("percentage follows the re-graded score (33.33)", regraded["result"]["percentage"] == 33.33, regraded["result"])

print(f"\nRESULT: {PASSED} passed, {FAILED} failed")
if FAILURES:
    print("Failed checks:")
    for failure in FAILURES:
        print(f"  - {failure}")
sys.exit(0 if FAILED == 0 else 1)
