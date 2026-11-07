"""Input validation: malformed input must produce clean 4xx, never a 500."""

import json

import pytest

from .helpers import add_question, create_exam, start_attempt


def assert_clean_error(response, allowed=(400, 401, 403, 404, 405, 409, 413, 415, 422)):
    assert response.status_code in allowed, response.get_data(as_text=True)[:300]
    assert response.status_code < 500
    body = response.get_data(as_text=True)
    assert "Traceback" not in body
    assert "site-packages" not in body
    assert response.headers["Content-Type"].startswith("application/json")


class TestMalformedJson:
    @pytest.mark.parametrize(
        "path,method",
        [
            ("/api/auth/login", "post"),
            ("/api/auth/register", "post"),
            ("/api/exams", "post"),
            ("/api/attempts/1/answer", "put"),
        ],
    )
    def test_broken_json_is_400(self, client, teacher_headers, path, method):
        call = getattr(client, method)
        response = call(path, data="{not valid json", content_type="application/json", headers=teacher_headers)
        assert_clean_error(response, allowed=(400, 401, 403))

    def test_json_array_body_is_rejected(self, client, teacher_headers):
        response = client.post("/api/exams", json=["not", "an", "object"], headers=teacher_headers)
        assert_clean_error(response, allowed=(400, 403))

    def test_json_null_body_is_rejected(self, client, teacher_headers):
        response = client.post("/api/exams", data="null", content_type="application/json", headers=teacher_headers)
        assert_clean_error(response, allowed=(400, 403))

    def test_wrong_content_type_is_rejected_cleanly(self, client, teacher_headers):
        response = client.post(
            "/api/exams", data="title=x", content_type="application/x-www-form-urlencoded", headers=teacher_headers
        )
        assert_clean_error(response, allowed=(400, 403, 415))


class TestFieldValidation:
    def test_missing_required_fields(self, client, teacher_headers):
        response = client.post("/api/exams", json={"subject": "only subject"}, headers=teacher_headers)
        assert response.status_code == 400
        fields = response.get_json()["error"]["fields"]
        assert "title" in fields and "duration_minutes" in fields

    @pytest.mark.parametrize(
        "body",
        [
            {"title": 123, "duration_minutes": 10},
            {"title": "Valid title", "duration_minutes": "ten"},
            {"title": "Valid title", "duration_minutes": 10, "is_published": "maybe"},
            {"title": "Valid title", "duration_minutes": 10, "pass_marks": "free"},
            {"title": "Valid title", "duration_minutes": 10, "start_time": "yesterday"},
        ],
    )
    def test_wrong_types_are_400(self, client, teacher_headers, body):
        response = client.post("/api/exams", json=body, headers=teacher_headers)
        assert response.status_code == 400
        assert response.status_code < 500

    @pytest.mark.parametrize(
        "body",
        [
            {"title": "x" * 5000, "duration_minutes": 10},
            {"title": "Valid", "duration_minutes": 10, "description": "d" * 100000},
            {"title": "Valid", "duration_minutes": -5},
            {"title": "Valid", "duration_minutes": 0},
            {"title": "Valid", "duration_minutes": 100000},
        ],
    )
    def test_oversized_and_out_of_range_values_are_400(self, client, teacher_headers, body):
        response = client.post("/api/exams", json=body, headers=teacher_headers)
        assert response.status_code == 400

    def test_huge_body_is_rejected_by_max_content_length(self, client, teacher_headers):
        big = json.dumps({"title": "x", "duration_minutes": 5, "description": "a" * (3 * 1024 * 1024)})
        response = client.post("/api/exams", data=big, content_type="application/json", headers=teacher_headers)
        assert response.status_code in (400, 413)
        assert response.status_code < 500

    def test_question_validation_errors(self, client, teacher_headers):
        exam = create_exam(client, teacher_headers, title="Validation exam")
        cases = [
            {"options": [{"option_text": "a"}, {"option_text": "b"}]},  # no correct option
            {"options": [{"option_text": "a", "is_correct": True}]},  # too few options
            {"options": [{"option_text": str(i), "is_correct": i == 0} for i in range(7)]},  # too many
            {"marks": 0},
            {"marks": "two"},
            {"question_type": "essay"},
            {"options": "not-a-list"},
            {"options": [{"option_text": 5, "is_correct": "yes"}, {"option_text": "b"}]},
        ]
        for overrides in cases:
            body = {
                "question_text": "Valid question text",
                "question_type": "single_choice",
                "marks": 1,
                "options": [{"option_text": "a", "is_correct": True}, {"option_text": "b"}],
                **overrides,
            }
            response = client.post(f"/api/exams/{exam['id']}/questions", json=body, headers=teacher_headers)
            assert response.status_code == 400, (overrides, response.get_data(as_text=True)[:200])

    def test_answer_validation(self, client, teacher_headers, student_headers):
        exam = create_exam(client, teacher_headers, title="Answer validation")
        question = add_question(client, teacher_headers, exam["id"])
        attempt = start_attempt(client, student_headers, exam["id"])["attempt"]

        bad_bodies = [
            {},
            {"question_id": "one", "selected_option_ids": []},
            {"question_id": question["id"], "selected_option_ids": "all"},
            {"question_id": question["id"], "selected_option_ids": [999999]},
            {"question_id": question["id"], "selected_option_ids": [{"id": 1}]},
            {"question_id": question["id"], "selected_option_ids": [1, 2, 3, 4, 5, 6, 7]},
        ]
        for body in bad_bodies:
            response = client.put(f"/api/attempts/{attempt['id']}/answer", json=body, headers=student_headers)
            assert response.status_code in (400, 404), (body, response.status_code)

    def test_unicode_and_emoji_are_accepted(self, client, teacher_headers):
        title = "数学考试 📘 – Algebra"
        exam = create_exam(client, teacher_headers, title=title)
        fetched = client.get(f"/api/exams/{exam['id']}", headers=teacher_headers).get_json()["exam"]
        assert fetched["title"] == title

    def test_unknown_fields_are_ignored_not_fatal(self, client, teacher_headers):
        response = client.post(
            "/api/exams",
            json={"title": "Extra fields", "duration_minutes": 10, "unexpected": {"nested": True}},
            headers=teacher_headers,
        )
        assert response.status_code == 201

    def test_invalid_ids_are_404_not_500(self, client, teacher_headers):
        for path in ("/api/exams/0", "/api/exams/999999"):
            assert client.get(path, headers=teacher_headers).status_code == 404
        assert client.delete("/api/questions/999999", headers=teacher_headers).status_code == 404
        assert client.delete("/api/exams/999999", headers=teacher_headers).status_code == 404

    def test_absurd_numeric_ids_are_404_not_500(self, client, teacher_headers):
        """Wider-than-64-bit ids must not reach SQLite (OverflowError -> 500)."""
        huge = "9" * 40
        for path in (
            f"/api/exams/{huge}",
            f"/api/exams/{huge}/questions",
            f"/api/attempts/{huge}",
            f"/api/attempts/{huge}/result",
            f"/api/reports/exam/{huge}",
            f"/api/reports/leaderboard/{huge}",
            f"/api/reports/student/{huge}",
        ):
            response = client.get(path, headers=teacher_headers)
            assert response.status_code == 404, (path, response.status_code)
        # DELETE routes may answer 405 (Werkzeug's method-vs-path precedence)
        # instead of 404; both are clean 4xx and neither touches the database.
        for path in (f"/api/exams/{huge}", f"/api/questions/{huge}"):
            code = client.delete(path, headers=teacher_headers).status_code
            assert code in (404, 405), (path, code)

    def test_negative_ids_are_404(self, client, teacher_headers):
        assert client.get("/api/exams/-1", headers=teacher_headers).status_code == 404

    def test_method_not_allowed_is_json(self, client, teacher_headers):
        response = client.delete("/api/auth/login", headers=teacher_headers)
        assert_clean_error(response, allowed=(405, 401))
