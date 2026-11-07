"""Shared helpers for the security tests."""

from datetime import timedelta

from app.db import get_db
from app.security import hash_password, to_iso, utcnow

# email, full name, password, role
ACCOUNTS = [
    {"email": "admin@t.test", "name": "Admin", "password": "AdminPass1", "role": "admin"},
    {"email": "teacher@t.test", "name": "Teacher One", "password": "TeacherPass1", "role": "teacher"},
    {"email": "teacher2@t.test", "name": "Teacher Two", "password": "TeacherPass1", "role": "teacher"},
    {"email": "student1@t.test", "name": "Student One", "password": "StudentPass1", "role": "student"},
    {"email": "student2@t.test", "name": "Student Two", "password": "StudentPass1", "role": "student"},
    {"email": "disabled@t.test", "name": "Disabled", "password": "DisabledPass1", "role": "student", "active": 0},
]


def seed_accounts():
    """Insert the standard accounts (call inside an app context)."""
    db = get_db()
    for account in ACCOUNTS:
        db.execute(
            """
            INSERT INTO users (full_name, email, password_hash, role, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                account["name"],
                account["email"],
                hash_password(account["password"]),
                account["role"],
                account.get("active", 1),
                to_iso(utcnow()),
            ),
        )


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def login(client, email, password):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def create_exam(client, headers, **overrides):
    """Create a published, currently-open exam."""
    now = utcnow()
    body = {
        "title": "Security Test Exam",
        "subject": "Testing",
        "duration_minutes": 30,
        "pass_marks": 1,
        "is_published": True,
        "start_time": to_iso(now - timedelta(hours=1)),
        "end_time": to_iso(now + timedelta(hours=2)),
    }
    body.update(overrides)
    response = client.post("/api/exams", json=body, headers=headers)
    assert response.status_code == 201, response.get_json()
    return response.get_json()["exam"]


def add_question(client, headers, exam_id, **overrides):
    body = {
        "question_text": "What is 2 + 2?",
        "question_type": "single_choice",
        "marks": 2,
        "options": [
            {"option_text": "3"},
            {"option_text": "4", "is_correct": True},
            {"option_text": "5"},
        ],
    }
    body.update(overrides)
    response = client.post(f"/api/exams/{exam_id}/questions", json=body, headers=headers)
    assert response.status_code == 201, response.get_json()
    return response.get_json()["question"]


def correct_option(question):
    return next(option["id"] for option in question["options"] if option.get("is_correct"))


def wrong_option(question):
    return next(option["id"] for option in question["options"] if not option.get("is_correct"))


def start_attempt(client, headers, exam_id):
    response = client.post(f"/api/exams/{exam_id}/start", headers=headers)
    assert response.status_code in (200, 201), response.get_json()
    return response.get_json()


def save_answer(client, headers, attempt_id, question_id, option_ids):
    return client.put(
        f"/api/attempts/{attempt_id}/answer",
        json={"question_id": question_id, "selected_option_ids": option_ids},
        headers=headers,
    )


def submit(client, headers, attempt_id):
    return client.post(f"/api/attempts/{attempt_id}/submit", headers=headers)
