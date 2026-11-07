"""Authentication security: brute force, lockout, tokens, enumeration."""

import logging
from datetime import timedelta

import pytest
from flask_jwt_extended import create_access_token

from app.db import get_db
from app.security import from_iso, utcnow

from .helpers import bearer, login


class TestBruteForce:
    def test_lockout_after_five_failures(self, client, accounts):
        for attempt in range(4):
            response = login(client, "student1@t.test", "WrongPass1")
            assert response.status_code == 401, f"attempt {attempt + 1}"
        # 5th failure trips the lock
        assert login(client, "student1@t.test", "WrongPass1").status_code == 401

        locked = login(client, "student1@t.test", "StudentPass1")
        assert locked.status_code == 429
        assert "too many" in locked.get_json()["error"]["message"].lower()

    def test_lockout_is_stored_for_fifteen_minutes(self, app, client):
        from app.db import get_db

        for _ in range(5):
            login(client, "student2@t.test", "WrongPass1")
        with app.app_context():
            row = get_db().execute(
                "SELECT locked_until FROM users WHERE email = ?", ("student2@t.test",)
            ).fetchone()
        remaining = (from_iso(row["locked_until"]) - utcnow()).total_seconds()
        assert 840 < remaining <= 900

    def test_successful_login_resets_the_counter(self, app, client):
        from app.db import get_db

        for _ in range(3):
            login(client, "student2@t.test", "WrongPass1")
        assert login(client, "student2@t.test", "StudentPass1").status_code == 200
        with app.app_context():
            row = get_db().execute(
                "SELECT failed_login_attempts, locked_until FROM users WHERE email = ?",
                ("student2@t.test",),
            ).fetchone()
        assert row["failed_login_attempts"] == 0 and row["locked_until"] is None

    def test_rate_limit_blocks_repeated_logins(self, rate_limited_client):
        codes = [
            login(rate_limited_client, "student1@t.test", "WrongPass1").status_code
            for _ in range(4)
        ]
        assert codes[:3] == [401, 401, 401]
        assert codes[3] == 429
        # A clean JSON error, not an HTML page.
        body = login(rate_limited_client, "student1@t.test", "StudentPass1").get_json()
        assert body["error"]["code"] == 429


class TestTokens:
    def test_expired_token_is_rejected(self, app, client, accounts):
        with app.app_context():
            expired = create_access_token(
                identity=str(accounts["student1@t.test"]["id"]),
                expires_delta=timedelta(seconds=-5),
            )
        response = client.get("/api/auth/me", headers=bearer(expired))
        assert response.status_code == 401
        assert "expired" in response.get_json()["error"]["message"].lower()

    def test_tampered_signature_is_rejected(self, client, tokens):
        token = tokens["student1@t.test"]
        header, payload, signature = token.split(".")
        tampered = ".".join([header, payload, signature[:-4] + "AAAA"])
        assert client.get("/api/auth/me", headers=bearer(tampered)).status_code == 401

    def test_unsigned_alg_none_token_is_rejected(self, client, accounts):
        import base64
        import json

        def segment(data):
            return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

        forged = ".".join(
            [
                segment({"alg": "none", "typ": "JWT"}),
                segment({"sub": str(accounts["admin@t.test"]["id"]), "role": "admin", "type": "access"}),
                "",
            ]
        )
        assert client.get("/api/auth/me", headers=bearer(forged)).status_code == 401

    def test_token_is_rejected_after_logout(self, client, tokens):
        headers = bearer(tokens["student1@t.test"])
        assert client.get("/api/auth/me", headers=headers).status_code == 200
        assert client.post("/api/auth/logout", headers=headers).status_code == 200
        assert client.get("/api/auth/me", headers=headers).status_code == 401

    def test_missing_and_malformed_authorization_headers(self, client):
        assert client.get("/api/auth/me").status_code == 401
        assert client.get("/api/auth/me", headers={"Authorization": "Token abc"}).status_code == 401
        assert client.get("/api/auth/me", headers={"Authorization": "Bearer"}).status_code == 401

    def test_role_claim_cannot_be_trusted_over_the_database(self, app, client, accounts):
        """A forged role claim must not grant admin rights (DB is authoritative)."""
        with app.app_context():
            forged = create_access_token(
                identity=str(accounts["student1@t.test"]["id"]),
                additional_claims={"role": "admin"},
            )
        response = client.post(
            "/api/auth/users",
            json={"full_name": "Ghost Admin", "email": "ghost@t.test", "password": "Ghost1234", "role": "admin"},
            headers=bearer(forged),
        )
        assert response.status_code == 403


class TestRegistration:
    @pytest.mark.parametrize(
        "password",
        ["short1", "onlyletters", "12345678", "a" * 73],
    )
    def test_weak_passwords_are_rejected(self, client, password):
        response = client.post(
            "/api/auth/register",
            json={"full_name": "Weak User", "email": "weak@t.test", "password": password},
        )
        assert response.status_code == 400
        assert "password" in response.get_json()["error"]["fields"]

    def test_duplicate_email_is_rejected(self, client):
        response = client.post(
            "/api/auth/register",
            json={"full_name": "Copy Cat", "email": "student1@t.test", "password": "ValidPass1"},
        )
        assert response.status_code == 409

    def test_mass_assignment_of_role_is_ignored(self, app, client):
        from app.db import get_db

        response = client.post(
            "/api/auth/register",
            json={
                "full_name": "Sneaky",
                "email": "sneaky@t.test",
                "password": "SneakyPass1",
                "role": "admin",
                "is_active": 0,
                "failed_login_attempts": 0,
                "id": 999,
            },
        )
        assert response.status_code == 201
        assert response.get_json()["user"]["role"] == "student"
        with app.app_context():
            row = get_db().execute(
                "SELECT role, is_active FROM users WHERE email = ?", ("sneaky@t.test",)
            ).fetchone()
        assert row["role"] == "student" and row["is_active"] == 1

    def test_invalid_email_is_rejected(self, client):
        response = client.post(
            "/api/auth/register",
            json={"full_name": "No At", "email": "not-an-email", "password": "ValidPass1"},
        )
        assert response.status_code == 400


class TestEnumeration:
    def test_unknown_email_and_wrong_password_are_indistinguishable(self, client):
        unknown = login(client, "nobody@t.test", "WrongPass1")
        wrong = login(client, "student1@t.test", "WrongPass1")
        assert unknown.status_code == wrong.status_code == 401
        assert unknown.get_json() == wrong.get_json()

    def test_register_does_not_reveal_the_existing_role(self, client):
        response = client.post(
            "/api/auth/register",
            json={"full_name": "Probe", "email": "teacher@t.test", "password": "ValidPass1"},
        )
        assert response.status_code == 409
        assert "teacher" not in response.get_data(as_text=True).lower()

    def test_disabled_account_matches_the_generic_message(self, client):
        response = login(client, "disabled@t.test", "DisabledPass1")
        assert response.status_code == 401
        assert response.get_json()["error"]["message"] == "Invalid email or password."


class TestSecretsInResponses:
    @pytest.mark.parametrize("endpoint", ["/api/auth/login", "/api/auth/register", "/api/auth/me"])
    def test_passwords_never_appear_in_responses(self, client, tokens, endpoint):
        if endpoint == "/api/auth/me":
            response = client.get(endpoint, headers=bearer(tokens["student1@t.test"]))
        else:
            response = client.post(
                endpoint,
                json={"full_name": "Fresh User", "email": "fresh@t.test", "password": "StudentPass1"},
            )
        body = response.get_data(as_text=True)
        assert "password_hash" not in body
        assert "StudentPass1" not in body

    def test_password_hashes_are_not_logged(self, client, caplog):
        caplog.set_level(logging.DEBUG)
        login(client, "student1@t.test", "SuperSecret9")
        assert "SuperSecret9" not in caplog.text
        assert "$2b$" not in caplog.text

    def test_passwords_are_stored_as_bcrypt(self, app):
        from app.db import get_db

        with app.app_context():
            rows = get_db().execute("SELECT password_hash FROM users").fetchall()
        assert all(row["password_hash"].startswith("$2b$") for row in rows)
        assert all("StudentPass1" != row["password_hash"] for row in rows)
