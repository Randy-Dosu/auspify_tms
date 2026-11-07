"""Student provisioning via a signed Student Management System (SMS) API.

Students can no longer create their own accounts, so this API *is* the account
creation surface. These tests treat it as hostile ground: they cover the
signature scheme (tampering, replay, clock skew, wrong secret, wrong client),
the provisioning rules (role escalation, staff accounts, duplicate matriculation
numbers, password rotation, lockouts) and the mutual-verification handshake.
"""

import json
import logging
import secrets
import time

import pytest

from .conftest import build_app
from .helpers import SMS_CLIENT_ID, SMS_SECRET, SmsRequester, bearer, login, sign_request

STUDENT = {
    "full_name": "Efua Mensah",
    "email": "efua@t.test",
    "course": "BSc Statistics",
    "student_number": "ST/2024/0100",
    "password": "St@ts2024x",
}


# ---------------------------------------------------------------------------
# 1. Self-registration is gone
# ---------------------------------------------------------------------------
class TestSelfRegistrationDisabled:
    @pytest.mark.parametrize(
        "email", ["brand.new@t.test", "student1@t.test", "teacher@t.test", "admin@t.test"]
    )
    def test_register_is_always_refused(self, app, client, email):
        response = client.post(
            "/api/auth/register",
            json={"full_name": "Self Service", "email": email, "password": "ValidPass1"},
        )
        assert response.status_code == 403
        message = response.get_json()["error"]["message"].lower()
        assert "student management system" in message
        # No account is created and no role is disclosed.
        assert "student1" not in response.get_data(as_text=True)

    def test_register_never_creates_a_user(self, app, client):
        from app.db import get_db

        before = None
        with app.app_context():
            before = get_db().execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        client.post(
            "/api/auth/register",
            json={"full_name": "Ghost", "email": "ghost@t.test", "password": "ValidPass1"},
        )
        with app.app_context():
            after = get_db().execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        assert before == after

    def test_register_ignores_a_role_field(self, app, client):
        from app.db import get_db

        client.post(
            "/api/auth/register",
            json={
                "full_name": "Sneaky",
                "email": "sneaky@t.test",
                "password": "Sneaky1234",
                "role": "admin",
            },
        )
        with app.app_context():
            row = get_db().execute("SELECT role FROM users WHERE email = ?", ("sneaky@t.test",)).fetchone()
        assert row is None  # the route is a stub: it creates nothing at all


# ---------------------------------------------------------------------------
# 2. Request authentication
# ---------------------------------------------------------------------------
class TestRequestSigning:
    def test_handshake_signs_the_callers_challenge(self, sms):
        challenge = secrets.token_hex(24)
        response = sms.post("/api/integration/handshake", {"challenge": challenge})
        assert response.status_code == 200
        body = response.get_json()
        assert body["challenge"] == challenge
        assert body["client_id"] == SMS_CLIENT_ID
        assert body["algorithm"] == "HMAC-SHA256"
        # The handshake signature must be checkable by the SMS with its own copy
        # of the secret (this is what "verify the TMS before approving usage"
        # means in practice).
        import hashlib
        import hmac as hmac_lib

        canonical = "\n".join(
            ["v1-handshake", SMS_CLIENT_ID, challenge, body["server_time"]]
        )
        expected_sig = hmac_lib.new(
            SMS_SECRET.encode(), canonical.encode(), hashlib.sha256
        ).hexdigest()
        assert body["signature"] == expected_sig

    def test_handshake_rejects_a_bad_challenge(self, sms):
        assert sms.post("/api/integration/handshake", {"challenge": "short"}).status_code == 400

    @pytest.mark.parametrize(
        "headers",
        [
            {},
            {"X-SMS-Client": "", "X-SMS-Timestamp": "", "X-SMS-Nonce": "", "X-SMS-Signature": ""},
        ],
    )
    def test_unsigned_requests_are_refused(self, client, headers):
        response = client.post("/api/integration/students", json=STUDENT, headers=headers)
        assert response.status_code == 401
        assert "Signed request required" in response.get_json()["error"]["message"]

    def test_jwt_cannot_authorise_the_provisioning_api(self, client, tokens):
        response = client.post(
            "/api/integration/students",
            json=STUDENT,
            headers=bearer(tokens["admin@t.test"]),
        )
        assert response.status_code == 401

    def test_wrong_secret_is_refused(self, sms):
        response = sms.post(
            "/api/integration/students/lookup", {"email": STUDENT["email"]}, secret="x" * 40
        )
        assert response.status_code == 401
        assert response.get_json()["error"]["message"] == "Invalid signature."

    def test_unknown_client_id_is_refused(self, sms):
        response = sms.post(
            "/api/integration/students/lookup", {"email": STUDENT["email"]}, client_id="someone-else"
        )
        assert response.status_code == 401

    def test_tampered_body_is_refused(self, sms):
        """The signature covers the exact bytes, so any field change is caught."""
        path = "/api/integration/students"
        headers, body = sms.headers(path, STUDENT)
        tampered = json.dumps({**STUDENT, "email": "attacker@t.test"}, separators=(",", ":")).encode()
        response = sms.client.post(path, data=tampered, headers=headers)
        assert response.status_code == 401
        assert response.get_json()["error"]["message"] == "Invalid signature."

    def test_tampered_signature_is_refused(self, sms):
        path = "/api/integration/students/lookup"
        headers, body = sms.headers(path, {"email": STUDENT["email"]})
        headers["X-SMS-Signature"] = "v1=" + "0" * 64
        assert sms.client.post(path, data=body, headers=headers).status_code == 401

    @pytest.mark.parametrize("offset", [-3600, 3600])
    def test_clock_skew_is_refused(self, sms, offset):
        response = sms.post(
            "/api/integration/students/lookup",
            {"email": STUDENT["email"]},
            timestamp=int(time.time()) + offset,
        )
        assert response.status_code == 401
        assert "window" in response.get_json()["error"]["message"]

    def test_malformed_timestamp_is_refused(self, client):
        headers, body = SmsRequester(client).headers(
            "/api/integration/students/lookup", {"email": "a@b.c"}
        )
        headers["X-SMS-Timestamp"] = "not-a-number"
        response = client.post("/api/integration/students/lookup", data=body, headers=headers)
        assert response.status_code == 401

    def test_nonce_cannot_be_replayed(self, sms):
        path = "/api/integration/students/lookup"
        payload = {"email": STUDENT["email"]}
        nonce = secrets.token_hex(16)
        timestamp = int(time.time())
        first = sms.post(path, payload, nonce=nonce, timestamp=timestamp)
        second = sms.post(path, payload, nonce=nonce, timestamp=timestamp)
        assert first.status_code == 200
        assert second.status_code == 401
        assert "replayed" in second.get_json()["error"]["message"].lower()

    def test_short_nonce_is_refused(self, sms):
        response = sms.post(
            "/api/integration/students/lookup", {"email": STUDENT["email"]}, nonce="abcd"
        )
        assert response.status_code == 401

    def test_responses_are_signed_for_the_sms_to_verify(self, sms):
        """Every answer carries a signature the SMS can recompute."""
        import hashlib
        import hmac as hmac_lib

        path = "/api/integration/students/lookup"
        headers, body = sms.headers(path, {"email": STUDENT["email"]})
        nonce = headers["X-SMS-Nonce"]
        fresh = sms.client.post(path, data=body, headers=headers)
        canonical = "\n".join(
            [
                "v1-response",
                "POST",
                path,
                str(fresh.status_code),
                fresh.headers["X-TMS-Timestamp"],
                nonce,
                hashlib.sha256(fresh.get_data()).hexdigest(),
            ]
        )
        expected = hmac_lib.new(SMS_SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()
        assert fresh.headers["X-TMS-Signature"] == f"v1={expected}"

    def test_integration_disabled_returns_503(self):
        app = build_app(SMS_CLIENT_SECRET="")
        client = app.test_client()
        requester = SmsRequester(client)
        for call in (
            lambda: requester.handshake(),
            lambda: requester.provision("nobody@t.test"),
            lambda: requester.lookup("nobody@t.test"),
            lambda: requester.status("nobody@t.test", False),
        ):
            response = call()
            assert response.status_code == 503
            assert "not configured" in response.get_json()["error"]["message"]

    def test_ip_allow_list_is_enforced(self):
        app = build_app(SMS_ALLOWED_IPS=["10.9.9.9"])
        client = app.test_client()
        response = SmsRequester(client).lookup("nobody@t.test")
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# 3. Provisioning rules
# ---------------------------------------------------------------------------
class TestProvisioning:
    def test_creates_a_student_with_the_supplied_data(self, app, sms):
        from app.db import get_db

        response = sms.provision(
            STUDENT["email"],
            name=STUDENT["full_name"],
            password=STUDENT["password"],
            course=STUDENT["course"],
            student_number=STUDENT["student_number"],
        )
        assert response.status_code == 201
        body = response.get_json()
        assert body["created"] is True
        assert body["student"]["role"] == "student"
        assert body["student"]["course"] == STUDENT["course"]
        assert body["student"]["student_number"] == STUDENT["student_number"]
        assert "password" not in json.dumps(body).lower()

        with app.app_context():
            row = get_db().execute("SELECT * FROM users WHERE email = ?", (STUDENT["email"],)).fetchone()
        assert row["role"] == "student"
        assert row["provisioned_by"] == f"sms:{SMS_CLIENT_ID}"
        assert row["password_hash"].startswith("$2b$12$")

    def test_the_student_can_then_log_in(self, sms, client):
        sms.provision(STUDENT["email"], password=STUDENT["password"])
        response = login(client, STUDENT["email"], STUDENT["password"])
        assert response.status_code == 200
        assert response.get_json()["user"]["role"] == "student"

    def test_login_response_includes_the_provisioned_fields(self, sms, client):
        sms.provision(
            STUDENT["email"],
            password=STUDENT["password"],
            course=STUDENT["course"],
            student_number=STUDENT["student_number"],
        )
        body = login(client, STUDENT["email"], STUDENT["password"]).get_json()
        assert body["user"]["course"] == STUDENT["course"]
        assert body["user"]["student_number"] == STUDENT["student_number"]
        assert "password_hash" not in json.dumps(body)

    def test_provisioning_is_idempotent(self, app, sms):
        from app.db import get_db

        first = sms.provision(STUDENT["email"], password=STUDENT["password"])
        second = sms.provision(STUDENT["email"], password=STUDENT["password"], course="BSc Maths")
        assert (first.status_code, second.status_code) == (201, 200)
        assert second.get_json()["created"] is False
        with app.app_context():
            rows = get_db().execute(
                "SELECT COUNT(*) AS c FROM users WHERE email = ?", (STUDENT["email"],)
            ).fetchone()["c"]
        assert rows == 1
        assert second.get_json()["student"]["course"] == "BSc Maths"

    def test_password_rotation_and_lockout_clear(self, app, sms, client):
        sms.provision(STUDENT["email"], password="OldPass123")
        # Lock the account with five failures (MAX_FAILED_LOGINS default).
        for _ in range(5):
            login(client, STUDENT["email"], "WrongPass1")
        assert login(client, STUDENT["email"], "OldPass123").status_code == 429

        rotated = sms.provision(STUDENT["email"], password="NewPass123")
        assert rotated.status_code == 200
        assert login(client, STUDENT["email"], "NewPass123").status_code == 200
        assert login(client, STUDENT["email"], "OldPass123").status_code == 401

    def test_password_is_required_for_a_new_account(self, sms):
        response = sms.post(
            "/api/integration/students", {"full_name": "No Password", "email": "nopass@t.test"}
        )
        assert response.status_code == 400
        assert "password" in response.get_json()["error"]["message"]

    @pytest.mark.parametrize("password", ["short1", "onlyletters", "12345678", "a" * 73])
    def test_weak_passwords_are_rejected(self, sms, password):
        response = sms.provision(f"weak{abs(hash(password)) % 1000}@t.test", password=password)
        assert response.status_code == 400
        assert "password" in response.get_json()["error"]["fields"]

    @pytest.mark.parametrize("email", ["not-an-email", "a@", "@b.c", "x" * 300 + "@t.test"])
    def test_invalid_emails_are_rejected(self, sms, email):
        response = sms.provision(email, password="ValidPass1")
        assert response.status_code == 400

    def test_duplicate_student_number_is_rejected(self, sms):
        assert sms.provision("first@t.test", student_number="CS/1").status_code == 201
        clash = sms.provision("second@t.test", student_number="CS/1")
        assert clash.status_code == 409
        assert "student number" in clash.get_json()["error"]["message"].lower()

    def test_staff_accounts_cannot_be_turned_into_students(self, app, sms):
        from app.db import get_db

        for staff in ("teacher@t.test", "admin@t.test"):
            response = sms.provision(staff, password="ValidPass1")
            assert response.status_code == 409
        with app.app_context():
            rows = get_db().execute(
                "SELECT role FROM users WHERE email IN ('teacher@t.test', 'admin@t.test')"
            ).fetchall()
        assert {row["role"] for row in rows} == {"teacher", "admin"}

    def test_role_escalation_through_the_body_is_ignored(self, app, sms):
        from app.db import get_db

        response = sms.provision(
            "sneaky@t.test", password="Sneaky1234", role="admin", is_active=0, id=999
        )
        assert response.status_code == 201
        assert response.get_json()["student"]["role"] == "student"
        with app.app_context():
            row = get_db().execute("SELECT role, id FROM users WHERE email = ?", ("sneaky@t.test",)).fetchone()
        assert row["role"] == "student" and row["id"] != 999

    def test_plain_text_password_is_never_logged(self, app, sms, caplog):
        caplog.set_level(logging.DEBUG)
        sms.provision("logged@t.test", password="SuperSecret123")
        assert "SuperSecret123" not in caplog.text

    def test_invalid_json_body_is_a_clean_400(self, sms):
        path = "/api/integration/students"
        headers, _ = sms.headers(path, {}, body=b"{not json")
        response = sms.client.post(path, data=b"{not json", headers=headers)
        assert response.status_code == 400
        assert response.headers["Content-Type"].startswith("application/json")


# ---------------------------------------------------------------------------
# 4. Status and lookup
# ---------------------------------------------------------------------------
class TestStudentStatus:
    def test_deactivation_blocks_login_and_reactivation_restores_it(self, app, sms, client):
        sms.provision(STUDENT["email"], password=STUDENT["password"])
        assert login(client, STUDENT["email"], STUDENT["password"]).status_code == 200

        off = sms.status(STUDENT["email"], False)
        assert off.status_code == 200
        assert off.get_json()["student"]["is_active"] == 0
        assert login(client, STUDENT["email"], STUDENT["password"]).status_code == 401

        on = sms.status(STUDENT["email"], True)
        assert on.status_code == 200
        assert login(client, STUDENT["email"], STUDENT["password"]).status_code == 200

    def test_reactivation_clears_an_existing_lockout(self, app, sms, client):
        sms.provision(STUDENT["email"], password=STUDENT["password"])
        for _ in range(5):
            login(client, STUDENT["email"], "WrongPass1")
        assert login(client, STUDENT["email"], STUDENT["password"]).status_code == 429
        sms.status(STUDENT["email"], False)
        sms.status(STUDENT["email"], True)
        assert login(client, STUDENT["email"], STUDENT["password"]).status_code == 200

    def test_status_of_an_unknown_student_is_404(self, sms):
        assert sms.status("ghost@t.test", False).status_code == 404

    def test_status_of_a_staff_account_is_409(self, sms):
        assert sms.status("teacher@t.test", False).status_code == 409

    def test_lookup_reports_existence(self, sms):
        assert sms.lookup("ghost@t.test").get_json() == {"exists": False, "student": None}
        sms.provision(STUDENT["email"], password=STUDENT["password"])
        body = sms.lookup(STUDENT["email"]).get_json()
        assert body["exists"] is True
        assert body["student"]["email"] == STUDENT["email"]
        assert "password_hash" not in json.dumps(body)

    def test_lookup_does_not_disclose_staff_accounts(self, sms):
        assert sms.lookup("teacher@t.test").get_json()["exists"] is False
        assert sms.lookup("admin@t.test").get_json()["exists"] is False
