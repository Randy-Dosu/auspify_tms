"""Authorization: vertical (role) and horizontal (ownership) access control."""

import pytest

from .helpers import add_question, create_exam, save_answer, start_attempt, submit


@pytest.fixture()
def exam_with_attempt(client, teacher_headers, student_headers):
    exam = create_exam(client, teacher_headers, title="Authorization Exam")
    question = add_question(client, teacher_headers, exam["id"])
    attempt = start_attempt(client, student_headers, exam["id"])
    return {"exam": exam, "question": question, "attempt": attempt}


class TestVerticalAccess:
    @pytest.mark.parametrize(
        "method,path,body",
        [
            ("post", "/api/exams", {"title": "Student exam", "duration_minutes": 10}),
            ("post", "/api/auth/users", {"full_name": "X", "email": "x@t.test", "password": "ValidPass1", "role": "admin"}),
            ("get", "/api/reports/exam/1", None),
            ("get", "/api/reports/leaderboard/1", None),
        ],
    )
    def test_student_is_forbidden_on_staff_endpoints(self, client, student_headers, method, path, body):
        call = getattr(client, method)
        response = call(path, json=body, headers=student_headers) if body else call(path, headers=student_headers)
        assert response.status_code == 403

    def test_student_cannot_read_teacher_question_feed(self, client, student_headers, exam_with_attempt):
        exam_id = exam_with_attempt["exam"]["id"]
        assert client.get(f"/api/exams/{exam_id}/questions", headers=student_headers).status_code == 403

    def test_teacher_cannot_create_accounts(self, client, teacher_headers):
        response = client.post(
            "/api/auth/users",
            json={"full_name": "T", "email": "t2@t.test", "password": "ValidPass1", "role": "teacher"},
            headers=teacher_headers,
        )
        assert response.status_code == 403

    def test_teacher_cannot_touch_another_teachers_exam(self, client, other_teacher_headers, exam_with_attempt):
        exam_id = exam_with_attempt["exam"]["id"]
        assert client.put(f"/api/exams/{exam_id}", json={"title": "Hijacked"}, headers=other_teacher_headers).status_code == 403
        assert client.delete(f"/api/exams/{exam_id}", headers=other_teacher_headers).status_code == 403
        assert client.get(f"/api/exams/{exam_id}/questions", headers=other_teacher_headers).status_code == 403

    def test_admin_can_use_teacher_endpoints(self, client, admin_headers, exam_with_attempt):
        exam_id = exam_with_attempt["exam"]["id"]
        assert client.get(f"/api/exams/{exam_id}", headers=admin_headers).status_code == 200
        assert client.get(f"/api/exams/{exam_id}/questions", headers=admin_headers).status_code == 200

    @pytest.mark.parametrize(
        "path",
        [
            "/api/exams",
            "/api/auth/me",
            "/api/attempts/1",
            "/api/attempts/1/result",
            "/api/reports/exam/1",
            "/api/reports/student/1",
            "/api/reports/leaderboard/1",
        ],
    )
    def test_anonymous_access_is_401(self, client, path):
        assert client.get(path).status_code == 401

    def test_mutating_endpoints_reject_anonymous(self, client):
        assert client.post("/api/exams", json={"title": "x", "duration_minutes": 5}).status_code == 401
        assert client.post("/api/exams/1/start").status_code == 401
        assert client.put("/api/attempts/1/answer", json={}).status_code == 401
        assert client.post("/api/attempts/1/submit").status_code == 401


class TestHorizontalAccess:
    def test_student_cannot_read_another_students_attempt(self, client, other_student_headers, exam_with_attempt):
        attempt_id = exam_with_attempt["attempt"]["attempt"]["id"]
        assert client.get(f"/api/attempts/{attempt_id}", headers=other_student_headers).status_code == 404

    def test_student_cannot_answer_another_students_attempt(self, client, other_student_headers, exam_with_attempt):
        attempt_id = exam_with_attempt["attempt"]["attempt"]["id"]
        question = exam_with_attempt["question"]
        response = save_answer(
            client, other_student_headers, attempt_id, question["id"], [question["options"][0]["id"]]
        )
        assert response.status_code == 404

    def test_student_cannot_submit_another_students_attempt(self, client, other_student_headers, exam_with_attempt):
        attempt_id = exam_with_attempt["attempt"]["attempt"]["id"]
        assert submit(client, other_student_headers, attempt_id).status_code == 404

    def test_student_cannot_read_another_students_result(self, client, other_student_headers, student_headers, exam_with_attempt):
        attempt_id = exam_with_attempt["attempt"]["attempt"]["id"]
        submit(client, student_headers, attempt_id)
        assert client.get(f"/api/attempts/{attempt_id}/result", headers=other_student_headers).status_code == 404

    def test_student_cannot_read_another_students_report(self, client, accounts, other_student_headers):
        victim = accounts["student1@t.test"]["id"]
        assert client.get(f"/api/reports/student/{victim}", headers=other_student_headers).status_code == 404

    def test_student_can_read_their_own_attempt_and_result(self, client, student_headers, exam_with_attempt, accounts):
        attempt_id = exam_with_attempt["attempt"]["attempt"]["id"]
        question = exam_with_attempt["question"]
        save_answer(client, student_headers, attempt_id, question["id"], [question["options"][1]["id"]])
        submit(client, student_headers, attempt_id)
        assert client.get(f"/api/attempts/{attempt_id}", headers=student_headers).status_code == 200
        assert client.get(f"/api/attempts/{attempt_id}/result", headers=student_headers).status_code == 200
        assert client.get(f"/api/reports/student/{accounts['student1@t.test']['id']}", headers=student_headers).status_code == 200

    def test_teacher_cannot_read_random_attempts(self, client, other_teacher_headers, exam_with_attempt):
        attempt_id = exam_with_attempt["attempt"]["attempt"]["id"]
        assert client.get(f"/api/attempts/{attempt_id}/result", headers=other_teacher_headers).status_code == 404
