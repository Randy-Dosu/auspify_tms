"""Step 2 verification: exam CRUD, validation, student attempts, server timer.

Runs against a throw-away SQLite database.

    cd backend && .venv/bin/python ../scripts/verify_step2.py
"""

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

USERS = [
    ("Teacher A", "ta@t.test", "TeacherPass1", "teacher"),
    ("Teacher B", "tb@t.test", "TeacherPass1", "teacher"),
    ("Student One", "s1@t.test", "StudentPass1", "student"),
    ("Student Two", "s2@t.test", "StudentPass1", "student"),
    ("Admin", "admin@t.test", "AdminPass1", "admin"),
]

with app.app_context():
    db = get_db()
    for name, email, password, role in USERS:
        db.execute(
            "INSERT INTO users (full_name, email, password_hash, role, is_active, created_at)"
            " VALUES (?, ?, ?, ?, 1, ?)",
            (name, email, hash_password(password), role, to_iso(utcnow())),
        )

client = app.test_client()


def token(email, password="StudentPass1"):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    return response.get_json()["access_token"]


def auth(tok):
    return {"Authorization": f"Bearer {tok}"}


TA = token("ta@t.test", "TeacherPass1")
TB = token("tb@t.test", "TeacherPass1")
S1 = token("s1@t.test")
S2 = token("s2@t.test")
ADMIN = token("admin@t.test", "AdminPass1")

now = utcnow()
OPEN = {"start_time": to_iso(now - timedelta(hours=1)), "end_time": to_iso(now + timedelta(hours=2))}


def make_exam(**overrides):
    body = {
        "title": "Algebra Basics",
        "description": "Chapter 1 - 3",
        "subject": "Mathematics",
        "duration_minutes": 30,
        "pass_marks": 2,
        "is_published": False,
        "allow_retakes": False,
        **OPEN,
    }
    body.update(overrides)
    return client.post("/api/exams", json=body, headers=auth(TA))


def add_question(exam_id, **overrides):
    body = {
        "question_text": "What is 2 + 2?",
        "question_type": "single_choice",
        "marks": 2,
        "negative_marks": 0,
        "options": [
            {"option_text": "3", "is_correct": False},
            {"option_text": "4", "is_correct": True},
            {"option_text": "5", "is_correct": False},
        ],
    }
    body.update(overrides)
    return client.post(f"/api/exams/{exam_id}/questions", json=body, headers=auth(TA))


def has_correct_flag(payload):
    return "is_correct" in str(payload)


section("Step 0/1 regression")
check("health still 200", client.get("/api/health").status_code == 200)
check("login still works", client.post("/api/auth/login", json={"email": "s1@t.test", "password": "StudentPass1"}).status_code == 200)

section("Exam CRUD (teacher)")
created = make_exam()
check("create exam returns 201", created.status_code == 201, created.get_json())
exam_id = created.get_json()["exam"]["id"]
check("new exam starts at 0 total marks", created.get_json()["exam"]["total_marks"] == 0)
check("exam is owned by the creator", created.get_json()["exam"]["created_by"] is not None)

q1 = add_question(exam_id)
check("add single_choice question returns 201", q1.status_code == 201, q1.get_json())
q1_id = q1.get_json()["question"]["id"]
check("total marks recomputed (2)", q1.get_json()["exam_total_marks"] == 2, q1.get_json())

q2 = add_question(
    exam_id,
    question_text="Which of these are prime numbers?",
    question_type="multiple_choice",
    marks=3,
    negative_marks=1,
    options=[
        {"option_text": "2", "is_correct": True},
        {"option_text": "4", "is_correct": False},
        {"option_text": "5", "is_correct": True},
    ],
)
check("add multiple_choice question with 2 correct options", q2.status_code == 201, q2.get_json())
q2_id = q2.get_json()["question"]["id"]

q3 = add_question(
    exam_id,
    question_text="A triangle has three sides.",
    question_type="true_false",
    marks=1,
    options=[
        {"option_text": "True", "is_correct": True},
        {"option_text": "False", "is_correct": False},
    ],
)
q3_id = q3.get_json()["question"]["id"]
check("add true/false question", q3.status_code == 201, q3.get_json())
check("total marks are 6 (2+3+1)", q3.get_json()["exam_total_marks"] == 6, q3.get_json())

detail = client.get(f"/api/exams/{exam_id}", headers=auth(TA))
check("teacher GET exam returns 3 questions", len(detail.get_json()["exam"]["questions"]) == 3)
check("teacher view DOES include correct answers", has_correct_flag(detail.get_json()["exam"]["questions"]))

updated = client.put(f"/api/exams/{exam_id}", json={"title": "Algebra Basics (v2)", "is_published": True}, headers=auth(TA))
check("partial update works", updated.status_code == 200 and updated.get_json()["exam"]["title"] == "Algebra Basics (v2)", updated.get_json())

edited_q = client.put(
    f"/api/questions/{q3_id}",
    json={
        "question_text": "A triangle has exactly three sides.",
        "question_type": "true_false",
        "marks": 2,
        "options": [
            {"option_text": "True", "is_correct": True},
            {"option_text": "False", "is_correct": False},
        ],
    },
    headers=auth(TA),
)
check("question update recalculates marks (2+3+2=7)", edited_q.status_code == 200 and edited_q.get_json()["exam_total_marks"] == 7, edited_q.get_json())

section("Validation")
bad_cases = {
    "no correct option": {"options": [{"option_text": "a"}, {"option_text": "b"}]},
    "single option only": {"options": [{"option_text": "a", "is_correct": True}]},
    "seven options": {"options": [{"option_text": str(i), "is_correct": i == 0} for i in range(7)]},
    "zero marks": {"marks": 0},
    "negative marks above marks": {"marks": 1, "negative_marks": 5},
    "two correct for single_choice": {
        "options": [
            {"option_text": "a", "is_correct": True},
            {"option_text": "b", "is_correct": True},
        ]
    },
    "true_false with 3 options": {
        "question_type": "true_false",
        "options": [
            {"option_text": "a", "is_correct": True},
            {"option_text": "b"},
            {"option_text": "c"},
        ],
    },
    "unknown question type": {"question_type": "essay"},
    "short question text": {"question_text": "hi"},
}
for label, overrides in bad_cases.items():
    response = add_question(exam_id, **overrides)
    check(f"rejects: {label} (400)", response.status_code == 400, response.get_json())

exam_bad = {
    "empty title": {"title": ""},
    "zero duration": {"duration_minutes": 0},
    "end before start": {"start_time": to_iso(now + timedelta(hours=1)), "end_time": to_iso(now)},
    "unparsable start_time": {"start_time": "not-a-date"},
    "negative pass marks": {"pass_marks": -1},
}
for label, overrides in exam_bad.items():
    response = make_exam(**overrides)
    check(f"rejects exam: {label} (400)", response.status_code == 400, response.get_json())

check("malformed JSON body is 400", client.post("/api/exams", data="{nope", content_type="application/json", headers=auth(TA)).status_code == 400)
check("oversized title is 400", make_exam(title="x" * 5000).status_code == 400)
check("unknown exam id is 404", client.get("/api/exams/9999", headers=auth(TA)).status_code == 404)

section("Ownership and role rules")
check("teacher B cannot edit teacher A's exam (403)", client.put(f"/api/exams/{exam_id}", json={"title": "Hijacked"}, headers=auth(TB)).status_code == 403)
check("teacher B cannot delete teacher A's exam (403)", client.delete(f"/api/exams/{exam_id}", headers=auth(TB)).status_code == 403)
check("teacher B cannot read A's questions (403)", client.get(f"/api/exams/{exam_id}/questions", headers=auth(TB)).status_code == 403)
tb_question = client.post(f"/api/exams/{exam_id}/questions", json={
    "question_text": "Teacher B trying to add a question",
    "question_type": "single_choice",
    "marks": 1,
    "options": [{"option_text": "a", "is_correct": True}, {"option_text": "b"}],
}, headers=auth(TB))
check("teacher B cannot add questions to A's exam (403)", tb_question.status_code == 403, tb_question.get_json())
check("student cannot create an exam (403)", client.post("/api/exams", json={"title": "x", "duration_minutes": 5}, headers=auth(S1)).status_code == 403)
check("student cannot open the teacher questions endpoint (403)", client.get(f"/api/exams/{exam_id}/questions", headers=auth(S1)).status_code == 403)
check("admin can read any exam", client.get(f"/api/exams/{exam_id}", headers=auth(ADMIN)).status_code == 200)
check("anonymous access to exams is 401", client.get("/api/exams").status_code == 401)

section("Student visibility")
student_list = client.get("/api/exams", headers=auth(S1)).get_json()["exams"]
check("published exam appears in the student list", any(e["id"] == exam_id for e in student_list), [e["title"] for e in student_list])

draft = make_exam(title="Draft exam", is_published=False)
draft_id = draft.get_json()["exam"]["id"]
check("draft exam is hidden from students", all(e["id"] != draft_id for e in client.get("/api/exams", headers=auth(S1)).get_json()["exams"]))
check("student gets 404 for a draft exam", client.get(f"/api/exams/{draft_id}", headers=auth(S1)).status_code == 404)

future = make_exam(
    title="Future exam",
    is_published=True,
    start_time=to_iso(now + timedelta(hours=3)),
    end_time=to_iso(now + timedelta(hours=4)),
)
future_id = future.get_json()["exam"]["id"]
check("exam outside its window is not listed", all(e["id"] != future_id for e in client.get("/api/exams", headers=auth(S1)).get_json()["exams"]))
start_future = client.post(f"/api/exams/{future_id}/start", headers=auth(S1))
check("starting before start_time is refused (403)", start_future.status_code == 403, start_future.get_json())

closed = make_exam(
    title="Closed exam",
    is_published=True,
    start_time=to_iso(now - timedelta(hours=4)),
    end_time=to_iso(now - timedelta(hours=3)),
)
check("starting after end_time is refused (403)", client.post(f"/api/exams/{closed.get_json()['exam']['id']}/start", headers=auth(S1)).status_code == 403)

section("Starting an attempt")
started = client.post(f"/api/exams/{exam_id}/start", headers=auth(S1))
check("student can start a published exam (201)", started.status_code == 201, started.get_json())
payload = started.get_json()
attempt_id = payload["attempt"]["id"]
check("attempt starts in_progress", payload["attempt"]["status"] == "in_progress")
teacher_questions = client.get(f"/api/exams/{exam_id}/questions", headers=auth(TA)).get_json()["questions"]
check(
    f"every question is delivered ({len(teacher_questions)})",
    len(payload["questions"]) == len(teacher_questions) == 3,
    (len(payload["questions"]), len(teacher_questions)),
)
check("NO correct answers in the start payload", not has_correct_flag(payload), [q for q in payload["questions"] if has_correct_flag(q)])
check("server returns remaining seconds", payload["time"]["remaining_seconds"] > 0)
check("questions expose options with ids only", all(set(o) == {"id", "option_text"} for q in payload["questions"] for o in q["options"]))

student_view = client.get(f"/api/exams/{exam_id}", headers=auth(S1))
check("student exam detail hides correct answers", not has_correct_flag(student_view.get_json()))

section("Answering")
options = {q["id"]: q["options"] for q in payload["questions"]}
q1_opts = options[q1_id]
correct_guess = [o["id"] for o in q1_opts if o["option_text"] == "4"]
saved = client.put(f"/api/attempts/{attempt_id}/answer", json={"question_id": q1_id, "selected_option_ids": correct_guess}, headers=auth(S1))
check("autosave an answer (200)", saved.status_code == 200, saved.get_json())
check("answer is echoed back", saved.get_json()["selected_option_ids"] == correct_guess)

resume = client.get(f"/api/attempts/{attempt_id}", headers=auth(S1))
check("saved answers come back on resume", resume.get_json()["answers"].get(str(q1_id)) == correct_guess, resume.get_json()["answers"])
check("resume payload has no correct flags", not has_correct_flag(resume.get_json()))

check("student B cannot answer student A's attempt (404)", client.put(f"/api/attempts/{attempt_id}/answer", json={"question_id": q1_id, "selected_option_ids": correct_guess}, headers=auth(S2)).status_code == 404)
check("student B cannot read student A's attempt (404)", client.get(f"/api/attempts/{attempt_id}", headers=auth(S2)).status_code == 404)
check("option from another question is rejected (400)", client.put(f"/api/attempts/{attempt_id}/answer", json={"question_id": q1_id, "selected_option_ids": [o["id"] for o in options[q2_id][:1]]}, headers=auth(S1)).status_code == 400)
check("two options on single_choice rejected (400)", client.put(f"/api/attempts/{attempt_id}/answer", json={"question_id": q1_id, "selected_option_ids": [o["id"] for o in q1_opts[:2]]}, headers=auth(S1)).status_code == 400)
check("unknown question rejected (404)", client.put(f"/api/attempts/{attempt_id}/answer", json={"question_id": 999999, "selected_option_ids": []}, headers=auth(S1)).status_code == 404)

section("Second attempt is blocked")
check("starting again while in progress resumes (200)", client.post(f"/api/exams/{exam_id}/start", headers=auth(S1)).status_code == 200)
submitted = client.post(f"/api/attempts/{attempt_id}/submit", headers=auth(S1))
check("submit closes the attempt (200)", submitted.status_code == 200 and submitted.get_json()["attempt"]["status"] == "submitted", submitted.get_json())
check("second start after submit is blocked (409)", client.post(f"/api/exams/{exam_id}/start", headers=auth(S1)).status_code == 409)
check("answering after submit is refused (409)", client.put(f"/api/attempts/{attempt_id}/answer", json={"question_id": q1_id, "selected_option_ids": correct_guess}, headers=auth(S1)).status_code == 409)

resubmit = client.post(f"/api/attempts/{attempt_id}/submit", headers=auth(S1))
check("double submit is idempotent (200, same timestamp)", resubmit.status_code == 200 and resubmit.get_json()["attempt"]["submitted_at"] == submitted.get_json()["attempt"]["submitted_at"], (submitted.get_json()["attempt"], resubmit.get_json()["attempt"]))

retake_exam = make_exam(title="Retake allowed", is_published=True, allow_retakes=True)
retake_id = retake_exam.get_json()["exam"]["id"]
add_question(retake_id)
first = client.post(f"/api/exams/{retake_id}/start", headers=auth(S2))
first_id = first.get_json()["attempt"]["id"]
client.post(f"/api/attempts/{first_id}/submit", headers=auth(S2))
second = client.post(f"/api/exams/{retake_id}/start", headers=auth(S2))
check("retakes allowed -> a second attempt is created", second.status_code == 201 and second.get_json()["attempt"]["id"] != first_id, second.get_json())

section("Server-side timer (browser timer tampering)")
timer_exam = make_exam(title="Timer exam", is_published=True, duration_minutes=1)
add_question(timer_exam.get_json()["exam"]["id"])
timer_id = timer_exam.get_json()["exam"]["id"]
started_timer = client.post(f"/api/exams/{timer_id}/start", headers=auth(S1))
timer_attempt = started_timer.get_json()["attempt"]["id"]
tq = started_timer.get_json()["questions"][0]
answer_body = {"question_id": tq["id"], "selected_option_ids": [tq["options"][0]["id"]]}
check("answer accepted while the timer is valid", client.put(f"/api/attempts/{timer_attempt}/answer", json=answer_body, headers=auth(S1)).status_code == 200)

# Simulate 5 minutes passing on a 1-minute exam (as if the browser clock was frozen).
with app.app_context():
    get_db().execute(
        "UPDATE attempts SET started_at = ? WHERE id = ?",
        (to_iso(utcnow() - timedelta(minutes=5)), timer_attempt),
    )
late = client.put(f"/api/attempts/{timer_attempt}/answer", json=answer_body, headers=auth(S1))
check("late answer is rejected (409)", late.status_code == 409, late.get_json())
check("attempt is auto-submitted as expired", late.get_json()["attempt"]["status"] == "expired", late.get_json())

with app.app_context():
    closed_rows = get_db().execute("SELECT status FROM attempts WHERE id = ?", (timer_attempt,)).fetchone()
check("expired status persisted", closed_rows["status"] == "expired")

section("Frozen questions after attempts exist")
frozen = add_question(exam_id)
check("published exam with attempts rejects new questions (409)", frozen.status_code == 409, frozen.get_json())
check("published exam with attempts rejects edits (409)", client.put(f"/api/questions/{q1_id}", json={"question_text": "Changed text here", "question_type": "single_choice", "marks": 1, "options": [{"option_text": "a", "is_correct": True}, {"option_text": "b"}]}, headers=auth(TA)).status_code == 409)
check("published exam with attempts rejects deletes (409)", client.delete(f"/api/questions/{q1_id}", headers=auth(TA)).status_code == 409)
check("exam with attempts cannot be deleted (409)", client.delete(f"/api/exams/{exam_id}", headers=auth(TA)).status_code == 409)

section("Correct answers never reach students")
student_responses = [
    client.get("/api/exams", headers=auth(S1)),
    client.get(f"/api/exams/{exam_id}", headers=auth(S1)),
    client.get(f"/api/attempts/{attempt_id}", headers=auth(S1)),
    client.post(f"/api/exams/{retake_id}/start", headers=auth(S2)),
]
check("no is_correct in any student-facing payload", all(not has_correct_flag(r.get_json()) for r in student_responses))
with app.app_context():
    db = get_db()
    option_rows = db.execute("SELECT id, option_text, is_correct FROM options WHERE question_id = ?", (q1_id,)).fetchall()
check("correct option really exists in the DB (so the test is meaningful)", any(o["is_correct"] == 1 for o in option_rows))

section("Deleting a clean exam")
clean = make_exam(title="Delete me")
check("exam without attempts can be deleted (200)", client.delete(f"/api/exams/{clean.get_json()['exam']['id']}", headers=auth(TA)).status_code == 200)
check("deleted exam is gone (404)", client.get(f"/api/exams/{clean.get_json()['exam']['id']}", headers=auth(TA)).status_code == 404)

print(f"\nRESULT: {PASSED} passed, {FAILED} failed")
if FAILURES:
    print("Failed checks:")
    for failure in FAILURES:
        print(f"  - {failure}")
sys.exit(0 if FAILED == 0 else 1)
