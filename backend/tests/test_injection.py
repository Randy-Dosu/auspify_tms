"""Injection: SQL injection everywhere, plus stored/reflected XSS handling."""

import os

import pytest

from .helpers import add_question, bearer, create_exam, login, start_attempt

SQL_PAYLOADS = [
    "'; DROP TABLE users; --",
    "' OR '1'='1",
    "admin'--",
    "1; DELETE FROM exams",
    "' UNION SELECT * FROM users --",
    "\" OR \"\"=\"",
    "%27%20OR%201%3D1",
]


class TestSqlInjection:
    @pytest.mark.parametrize("payload", SQL_PAYLOADS)
    def test_login_fields_are_parameterised(self, client, payload):
        response = login(client, payload, payload)
        assert response.status_code in (400, 401), response.status_code
        assert response.status_code != 500

    @pytest.mark.parametrize("payload", SQL_PAYLOADS)
    def test_register_fields_are_parameterised(self, client, payload):
        response = client.post(
            "/api/auth/register",
            json={"full_name": payload, "email": f"a{abs(hash(payload)) % 97}@t.test", "password": "ValidPass1"},
        )
        assert response.status_code in (201, 400), response.status_code
        assert response.status_code != 500

    @pytest.mark.parametrize("payload", SQL_PAYLOADS)
    def test_path_parameters_are_not_interpolated(self, client, teacher_headers, student_headers, payload):
        quoted = payload.replace("/", "%2F").replace(" ", "%20")
        for path in (f"/api/exams/{quoted}", f"/api/reports/exam/{quoted}", f"/api/reports/student/{quoted}"):
            response = client.get(path, headers=teacher_headers)
            assert response.status_code in (400, 404), (path, response.status_code)

    @pytest.mark.parametrize("payload", SQL_PAYLOADS)
    def test_query_parameters_are_safe(self, client, teacher_headers, exam_with_attempt, payload):
        exam_id = exam_with_attempt["exam"]["id"]
        response = client.get(
            f"/api/reports/exam/{exam_id}?format={payload}&sort={payload}", headers=teacher_headers
        )
        assert response.status_code == 200  # format ignored -> JSON

    @pytest.mark.parametrize("payload", SQL_PAYLOADS)
    def test_json_bodies_are_safe(self, client, teacher_headers, student_headers, payload):
        response = client.post(
            "/api/exams",
            json={"title": payload, "subject": payload, "description": payload, "duration_minutes": 5},
            headers=teacher_headers,
        )
        assert response.status_code in (201, 400)
        assert response.status_code != 500

    def test_database_survives_injection_attempts(self, app, client, accounts):
        from app.db import get_db

        for payload in SQL_PAYLOADS:
            login(client, payload, payload)
            client.post("/api/auth/register", json={"full_name": payload, "email": "x@t.test", "password": "ValidPass1"})
        with app.app_context():
            db = get_db()
            tables = {row["name"] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            users = db.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        assert {"users", "exams", "questions", "options", "attempts", "answers"} <= tables
        assert users >= 6

    def test_sql_strings_are_stored_as_data_not_executed(self, client, teacher_headers):
        payload = "Robert'); DROP TABLE exams;--"
        exam = create_exam(client, teacher_headers, title=payload, subject=payload)
        assert exam["title"] == payload
        fetched = client.get(f"/api/exams/{exam['id']}", headers=teacher_headers).get_json()["exam"]
        assert fetched["title"] == payload
        assert client.get("/api/exams", headers=teacher_headers).status_code == 200


class TestXss:
    def test_script_payloads_round_trip_as_plain_json(self, client, teacher_headers, student_headers):
        payload = "<script>alert('xss')</script>"
        exam = create_exam(client, teacher_headers, title=payload, description=payload)
        question = add_question(client, teacher_headers, exam["id"], question_text=payload + " question")

        # Stored server-side as data, returned as JSON (never as HTML).
        response = client.get(f"/api/exams/{exam['id']}", headers=teacher_headers)
        assert response.status_code == 200
        assert response.headers["Content-Type"].startswith("application/json")
        assert "<script>" in response.get_data(as_text=True)  # JSON-escaped string literal

        # A student sees the same text but no answer key and no HTML wrapper.
        client.post(f"/api/exams/{exam['id']}/start", headers=student_headers)
        student_view = client.get("/api/exams", headers=student_headers)
        assert student_view.headers["Content-Type"].startswith("application/json")
        assert "<html" not in student_view.get_data(as_text=True).lower()

    def test_reflected_payloads_are_not_echoed_as_html(self, client):
        payload = "<img src=x onerror=alert(1)>"
        response = client.get(f"/api/exams?search={payload}")
        assert response.status_code in (401, 404) or response.status_code == 401
        body = response.get_data(as_text=True).lower()
        assert "<html" not in body

    def test_error_pages_are_json_not_html(self, client):
        for path in ("/api/does-not-exist", "/api/exams/abc"):
            response = client.get(path)
            assert response.headers["Content-Type"].startswith("application/json")
            assert "<html" not in response.get_data(as_text=True).lower()

    def test_frontend_never_uses_dangerously_set_inner_html(self):
        """Static check: React escapes by default; confirm nobody bypasses it."""
        src = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "frontend", "src")
        offenders = []
        for root, _dirs, files in os.walk(src):
            for name in files:
                if name.endswith((".js", ".jsx")):
                    with open(os.path.join(root, name), encoding="utf-8") as handle:
                        content = handle.read()
                    if "dangerouslySetInnerHTML" in content:
                        offenders.append(os.path.join(root, name))
        assert offenders == []
        assert os.path.isdir(src), "frontend source not found - check the test path"


@pytest.fixture()
def exam_with_attempt(client, teacher_headers, student_headers):
    exam = create_exam(client, teacher_headers, title="Injection Exam")
    question = add_question(client, teacher_headers, exam["id"])
    attempt = start_attempt(client, student_headers, exam["id"])
    return {"exam": exam, "question": question, "attempt": attempt}
