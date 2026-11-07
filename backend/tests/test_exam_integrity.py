"""Exam integrity: answer leakage, server timer, replay, post-submit edits."""

from datetime import timedelta

import pytest

from app.db import get_db
from app.security import to_iso, utcnow

from .helpers import add_question, correct_option, create_exam, save_answer, start_attempt, submit, wrong_option


def contains_answer_key(payload) -> bool:
    return "is_correct" in str(payload)


class TestAnswerLeakage:
    def test_student_exam_list_has_no_answers(self, client, student_headers, exam_with_questions):
        response = client.get("/api/exams", headers=student_headers)
        assert response.status_code == 200
        assert not contains_answer_key(response.get_json())

    def test_student_exam_detail_has_no_answers(self, client, student_headers, exam_with_questions):
        exam_id = exam_with_questions["exam"]["id"]
        response = client.get(f"/api/exams/{exam_id}", headers=student_headers)
        assert response.status_code == 200
        assert not contains_answer_key(response.get_json())

    def test_start_payload_has_no_answers(self, client, student_headers, exam_with_questions):
        payload = start_attempt(client, student_headers, exam_with_questions["exam"]["id"])
        assert not contains_answer_key(payload)
        for question in payload["questions"]:
            for option in question["options"]:
                assert set(option) == {"id", "option_text"}

    def test_attempt_and_submit_payloads_have_no_answers(self, client, student_headers, exam_with_questions):
        payload = start_attempt(client, student_headers, exam_with_questions["exam"]["id"])
        attempt_id = payload["attempt"]["id"]
        question = payload["questions"][0]
        answer = save_answer(client, student_headers, attempt_id, question["id"], [question["options"][0]["id"]])
        assert not contains_answer_key(answer.get_json())
        submitted = submit(client, student_headers, attempt_id)
        assert not contains_answer_key(submitted.get_json())

    def test_answer_key_exists_in_the_database(self, app, exam_with_questions):
        with app.app_context():
            row = get_db().execute(
                "SELECT COUNT(*) AS c FROM options WHERE is_correct = 1"
            ).fetchone()
        assert row["c"] >= 1  # the checks above are meaningful


class TestServerTimer:
    def test_answers_after_the_deadline_are_rejected(self, app, client, student_headers, exam_with_questions):
        payload = start_attempt(client, student_headers, exam_with_questions["exam"]["id"])
        attempt_id = payload["attempt"]["id"]
        question = payload["questions"][0]

        # Simulate a tampered browser clock: the attempt really started long ago.
        with app.app_context():
            get_db().execute(
                "UPDATE attempts SET started_at = ? WHERE id = ?",
                (to_iso(utcnow() - timedelta(minutes=120)), attempt_id),
            )
        response = save_answer(client, student_headers, attempt_id, question["id"], [question["options"][0]["id"]])
        assert response.status_code == 409
        assert response.get_json()["attempt"]["status"] == "expired"

    def test_expired_attempt_is_graded_from_saved_answers(self, app, client, student_headers, exam_with_questions):
        exam_id = exam_with_questions["exam"]["id"]
        question = exam_with_questions["question"]
        payload = start_attempt(client, student_headers, exam_id)
        attempt_id = payload["attempt"]["id"]
        save_answer(client, student_headers, attempt_id, question["id"], [correct_option(question)])

        with app.app_context():
            get_db().execute(
                "UPDATE attempts SET started_at = ? WHERE id = ?",
                (to_iso(utcnow() - timedelta(minutes=120)), attempt_id),
            )
        client.get(f"/api/attempts/{attempt_id}", headers=student_headers)  # triggers auto-submit
        result = client.get(f"/api/attempts/{attempt_id}/result", headers=student_headers)
        assert result.status_code == 200
        assert result.get_json()["result"]["status"] == "expired"
        assert result.get_json()["result"]["score"] == 2

    def test_remaining_time_is_server_calculated(self, client, student_headers, exam_with_questions):
        payload = start_attempt(client, student_headers, exam_with_questions["exam"]["id"])
        assert 0 < payload["time"]["remaining_seconds"] <= 30 * 60


class TestAttemptReplay:
    def test_second_attempt_is_blocked(self, client, student_headers, exam_with_questions):
        exam_id = exam_with_questions["exam"]["id"]
        first = start_attempt(client, student_headers, exam_id)
        submit(client, student_headers, first["attempt"]["id"])
        assert client.post(f"/api/exams/{exam_id}/start", headers=student_headers).status_code == 409

    def test_replaying_start_while_in_progress_returns_the_same_attempt(self, app, client, student_headers, exam_with_questions):
        exam_id = exam_with_questions["exam"]["id"]
        first = start_attempt(client, student_headers, exam_id)
        second = client.post(f"/api/exams/{exam_id}/start", headers=student_headers)
        assert second.status_code == 200
        assert second.get_json()["attempt"]["id"] == first["attempt"]["id"]
        with app.app_context():
            count = get_db().execute(
                "SELECT COUNT(*) AS c FROM attempts WHERE exam_id = ?", (exam_id,)
            ).fetchone()["c"]
        assert count == 1

    def test_concurrent_start_does_not_create_two_attempts(self, app, client, student_headers, exam_with_questions):
        exam_id = exam_with_questions["exam"]["id"]
        responses = [client.post(f"/api/exams/{exam_id}/start", headers=student_headers) for _ in range(5)]
        ids = {r.get_json().get("attempt", {}).get("id") for r in responses if r.status_code in (200, 201)}
        assert len(ids) == 1
        with app.app_context():
            count = get_db().execute(
                "SELECT COUNT(*) AS c FROM attempts WHERE exam_id = ?", (exam_id,)
            ).fetchone()["c"]
        assert count == 1

    def test_retakes_create_a_new_attempt_when_allowed(self, client, teacher_headers, student_headers):
        exam = create_exam(client, teacher_headers, title="Retake Exam", allow_retakes=True)
        add_question(client, teacher_headers, exam["id"])
        first = start_attempt(client, student_headers, exam["id"])
        submit(client, student_headers, first["attempt"]["id"])
        second = client.post(f"/api/exams/{exam['id']}/start", headers=student_headers)
        assert second.status_code == 201
        assert second.get_json()["attempt"]["id"] != first["attempt"]["id"]


class TestPostSubmissionProtection:
    def test_answers_cannot_be_changed_after_submission(self, client, student_headers, exam_with_questions):
        payload = start_attempt(client, student_headers, exam_with_questions["exam"]["id"])
        attempt_id = payload["attempt"]["id"]
        question = payload["questions"][0]
        submit(client, student_headers, attempt_id)
        response = save_answer(client, student_headers, attempt_id, question["id"], [question["options"][0]["id"]])
        assert response.status_code == 409

    def test_double_submit_cannot_change_the_score(self, app, client, student_headers, exam_with_questions):
        exam_id = exam_with_questions["exam"]["id"]
        question = exam_with_questions["question"]
        payload = start_attempt(client, student_headers, exam_id)
        attempt_id = payload["attempt"]["id"]
        save_answer(client, student_headers, attempt_id, question["id"], [correct_option(question)])
        submit(client, student_headers, attempt_id)
        first = client.get(f"/api/attempts/{attempt_id}/result", headers=student_headers).get_json()["result"]

        # Change the stored answer behind the API's back, then re-submit.
        with app.app_context():
            get_db().execute(
                "UPDATE answers SET selected_option_ids = ? WHERE attempt_id = ? AND question_id = ?",
                (f"[{wrong_option(question)}]", attempt_id, question["id"]),
            )
        submit(client, student_headers, attempt_id)
        second = client.get(f"/api/attempts/{attempt_id}/result", headers=student_headers).get_json()["result"]
        assert first["score"] == second["score"]

    def test_published_exam_with_attempts_is_frozen(self, client, teacher_headers, student_headers, exam_with_questions):
        exam_id = exam_with_questions["exam"]["id"]
        question = exam_with_questions["question"]
        first = start_attempt(client, student_headers, exam_id)
        submit(client, student_headers, first["attempt"]["id"])

        new_question = {
            "question_text": "Sneaky late question",
            "question_type": "single_choice",
            "marks": 5,
            "options": [{"option_text": "a", "is_correct": True}, {"option_text": "b"}],
        }
        assert client.post(f"/api/exams/{exam_id}/questions", json=new_question, headers=teacher_headers).status_code == 409
        assert client.delete(f"/api/questions/{question['id']}", headers=teacher_headers).status_code == 409
        assert client.delete(f"/api/exams/{exam_id}", headers=teacher_headers).status_code == 409

    def test_review_is_hidden_until_the_window_closes(self, app, client, student_headers, exam_with_questions):
        exam_id = exam_with_questions["exam"]["id"]
        payload = start_attempt(client, student_headers, exam_id)
        attempt_id = payload["attempt"]["id"]
        submit(client, student_headers, attempt_id)

        early = client.get(f"/api/attempts/{attempt_id}/result", headers=student_headers).get_json()
        assert early["review_available"] is False
        assert "questions" not in early

        with app.app_context():
            get_db().execute(
                "UPDATE exams SET end_time = ? WHERE id = ?",
                (to_iso(utcnow() - timedelta(minutes=1)), exam_id),
            )
        late = client.get(f"/api/attempts/{attempt_id}/result", headers=student_headers).get_json()
        assert late["review_available"] is True
        assert len(late["questions"]) >= 1

    def test_result_is_not_available_while_in_progress(self, client, student_headers, exam_with_questions):
        payload = start_attempt(client, student_headers, exam_with_questions["exam"]["id"])
        response = client.get(f"/api/attempts/{payload['attempt']['id']}/result", headers=student_headers)
        assert response.status_code == 409


@pytest.fixture()
def exam_with_questions(client, teacher_headers):
    exam = create_exam(client, teacher_headers, title="Integrity Exam", duration_minutes=30)
    question = add_question(client, teacher_headers, exam["id"])
    return {"exam": exam, "question": question}
