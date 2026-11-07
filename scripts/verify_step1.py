"""Step 1 verification: authentication, RBAC, lockout, rate limiting, hashing.

Students are provisioned by the student management system (SMS) over a signed
API, so the account-creation checks here run through that path and prove that
self-registration is dead.

Runs against throw-away SQLite databases so it never touches dev data.

    cd backend && .venv/bin/python ../scripts/verify_step1.py
"""

import hashlib
import hmac
import json
import os
import secrets
import sys
import tempfile
import time
from datetime import timedelta

BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "backend")
sys.path.insert(0, os.path.abspath(BACKEND))
os.chdir(os.path.abspath(BACKEND))

from app import create_app  # noqa: E402
from app.config import Config  # noqa: E402
from app.db import get_db  # noqa: E402
from app.security import hash_password, to_iso, utcnow  # noqa: E402

PASSED = 0
FAILED = 0
FAILURES = []

# Shared secret for the SMS integration in this throw-away app.
SMS_CLIENT_ID = "verify-sms"
SMS_SECRET = "verify-sms-secret-" + "e" * 40


def sms_post(client, path, payload, *, secret=SMS_SECRET, timestamp=None, nonce=None):
    """Sign and send one provisioning request, the way the SMS would."""
    body = json.dumps(payload, separators=(",", ":")).encode()
    timestamp = str(int(time.time())) if timestamp is None else str(timestamp)
    nonce = secrets.token_hex(16) if nonce is None else nonce
    canonical = "\n".join(
        ["v1", "POST", path, timestamp, nonce, hashlib.sha256(body).hexdigest()]
    )
    signature = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-SMS-Client": SMS_CLIENT_ID,
        "X-SMS-Timestamp": timestamp,
        "X-SMS-Nonce": nonce,
        "X-SMS-Signature": f"v1={signature}",
    }
    return client.post(path, data=body, headers=headers)


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


def make_config(**overrides):
    """Fresh temp DB + optional config overrides."""
    path = tempfile.mktemp(suffix=".db")

    class C(Config):
        DATABASE_PATH = path
        TESTING = True

    for key, value in overrides.items():
        setattr(C, key, value)
    return C


def seed(app, accounts):
    """accounts: list of (full_name, email, password, role, active)"""
    with app.app_context():
        db = get_db()
        for full_name, email, password, role, active in accounts:
            db.execute(
                "INSERT INTO users (full_name, email, password_hash, role, is_active, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (full_name, email, hash_password(password), role, active, to_iso(utcnow())),
            )
    return app


USERS = [
    ("Admin User", "admin@t.test", "AdminPass1", "admin", 1),
    ("Teacher User", "teacher@t.test", "TeacherPass1", "teacher", 1),
    ("Student One", "s1@t.test", "StudentPass1", "student", 1),
    ("Student Two", "s2@t.test", "StudentPass1", "student", 1),
    ("Student Three", "s3@t.test", "StudentPass1", "student", 1),
    ("Disabled User", "off@t.test", "DisabledPass1", "student", 0),
]


def login(client, email, password):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def token_for(client, email, password):
    response = login(client, email, password)
    assert response.status_code == 200, response.get_json()
    return response.get_json()["access_token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def main():
    # ------------------------------------------------------------------
    # Rate limiting (separate app: needs limits ON and a low threshold)
    # ------------------------------------------------------------------
    section("Rate limiting")
    rate_app = seed(create_app(make_config(RATELIMIT_ENABLED=True, LOGIN_RATE_LIMIT="3 per minute")), USERS)
    with rate_app.test_client() as client:
        codes = [login(client, "s1@t.test", "wrongpass1").status_code for _ in range(4)]
        check("login returns 401 for the first attempts", codes[:3] == [401, 401, 401], codes)
        check("4th attempt within the window is rate limited (429)", codes[3] == 429, codes)
        body = login(client, "s1@t.test", "StudentPass1").get_json()
        check("rate-limit response is clean JSON", "error" in body, body)

    # ------------------------------------------------------------------
    # Functional app: rate limits off so we can test lockout deterministically
    # ------------------------------------------------------------------
    app = seed(
        create_app(
            make_config(
                RATELIMIT_ENABLED=False,
                SMS_CLIENT_ID=SMS_CLIENT_ID,
                SMS_CLIENT_SECRET=SMS_SECRET,
            )
        ),
        USERS,
    )

    with app.test_client() as client:
        section("Login / me / logout")
        check("Step 0 regression: /api/health still 200", client.get("/api/health").status_code == 200)
        response = login(client, "s1@t.test", "StudentPass1")
        check("valid login returns 200 + access_token", response.status_code == 200 and "access_token" in response.get_json(), response.get_json())
        student_token = response.get_json()["access_token"]

        me = client.get("/api/auth/me", headers=auth(student_token))
        payload = me.get_json()
        check("GET /api/auth/me returns the caller", me.status_code == 200 and payload["user"]["email"] == "s1@t.test", payload)
        check("me never returns password_hash", "password_hash" not in str(payload), payload)
        check("me without a token is 401", client.get("/api/auth/me").status_code == 401)
        check("401 body is JSON with an error message", client.get("/api/auth/me").get_json()["error"]["code"] == 401)

        section("Generic credential errors (no user enumeration)")
        wrong_pw = login(client, "s1@t.test", "WrongPass1")
        unknown = login(client, "nobody@t.test", "WrongPass1")
        check("wrong password is 401", wrong_pw.status_code == 401)
        check("unknown email is 401", unknown.status_code == 401)
        check(
            "both failures return the identical message",
            wrong_pw.get_json() == unknown.get_json(),
            (wrong_pw.get_json(), unknown.get_json()),
        )
        check(
            "message does not reveal which field was wrong",
            wrong_pw.get_json()["error"]["message"] == "Invalid email or password.",
            wrong_pw.get_json(),
        )

        section("Self-registration is disabled")
        for email in ("new@t.test", "s1@t.test", "admin@t.test"):
            refused = client.post(
                "/api/auth/register",
                json={"full_name": "Self Service", "email": email, "password": "ValidPass1"},
            )
            check(
                f"POST /api/auth/register is refused for {email}",
                refused.status_code == 403,
                refused.get_json(),
            )
        check(
            "the refusal explains the SMS hand-off",
            "student management system"
            in refused.get_json()["error"]["message"].lower(),
            refused.get_json(),
        )
        with app.app_context():
            ghost = get_db().execute(
                "SELECT id FROM users WHERE email = 'new@t.test'"
            ).fetchone()
        check("no account was created by the refused request", ghost is None)

        section("Students are provisioned by the SMS")
        created = sms_post(
            client,
            "/api/integration/students",
            {
                "full_name": "Provisioned Student",
                "email": "new@t.test",
                "password": "Provision1",
                "course": "BSc Computer Science",
                "student_number": "CS/2024/0100",
            },
        )
        check("signed provisioning returns 201", created.status_code == 201, created.get_json())
        check(
            "the provisioned account is a student",
            created.get_json()["student"]["role"] == "student",
            created.get_json(),
        )
        check(
            "course and student number are stored",
            created.get_json()["student"]["course"] == "BSc Computer Science"
            and created.get_json()["student"]["student_number"] == "CS/2024/0100",
            created.get_json(),
        )
        check(
            "the response never echoes the password",
            "Provision1" not in created.get_data(as_text=True),
            created.get_json(),
        )

        section("Provisioning is authenticated")
        unsigned = client.post(
            "/api/integration/students",
            json={"full_name": "No Sig", "email": "nosig@t.test", "password": "ValidPass1"},
        )
        check("unsigned provisioning is 401", unsigned.status_code == 401, unsigned.get_json())
        forged = sms_post(
            client,
            "/api/integration/students",
            {"full_name": "Bad Sig", "email": "bad@t.test", "password": "ValidPass1"},
            secret="wrong-secret-" + "x" * 32,
        )
        check("a bad signature is 401", forged.status_code == 401, forged.get_json())
        stale = sms_post(
            client,
            "/api/integration/students",
            {"full_name": "Stale", "email": "stale@t.test", "password": "ValidPass1"},
            timestamp=int(time.time()) - 7200,
        )
        check("a stale timestamp is 401", stale.status_code == 401, stale.get_json())

        section("Provisioned student can sign in")
        provisioned_login = login(client, "new@t.test", "Provision1")
        check(
            "provisioned student logs in with the SMS password",
            provisioned_login.status_code == 200,
            provisioned_login.get_json(),
        )
        check(
            "the login payload carries the SMS data",
            provisioned_login.get_json()["user"]["course"] == "BSc Computer Science",
            provisioned_login.get_json(),
        )

        section("Provisioning validation")
        weak = [
            ("short", "Ab1"),
            ("no digit", "onlyletters"),
            ("no letter", "12345678"),
        ]
        for label, password in weak:
            response = sms_post(
                client,
                "/api/integration/students",
                {
                    "full_name": "Weak User",
                    "email": f"weak{abs(hash(label)) % 1000}@t.test",
                    "password": password,
                },
            )
            check(f"weak password rejected ({label})", response.status_code == 400, response.get_json())

        duplicate = sms_post(
            client,
            "/api/integration/students",
            {
                "full_name": "Provisioned Student",
                "email": "new@t.test",
                "password": "Provision1",
                "course": "BSc Computer Science",
                "student_number": "CS/2024/0100",
            },
        )
        check(
            "re-sending the same record updates it instead of duplicating it",
            duplicate.status_code == 200 and duplicate.get_json()["created"] is False,
            duplicate.get_json(),
        )
        with app.app_context():
            count = get_db().execute(
                "SELECT COUNT(*) AS c FROM users WHERE email = 'new@t.test'"
            ).fetchone()["c"]
        check("no duplicate row was created", count == 1, count)

        mass = sms_post(
            client,
            "/api/integration/students",
            {
                "full_name": "Sneaky User",
                "email": "sneaky@t.test",
                "password": "SneakyPass1",
                "role": "admin",
                "is_active": 0,
            },
        )
        check("provisioning with role=admin still returns 201", mass.status_code == 201, mass.get_json())
        check("mass assignment ignored: role is student", mass.get_json()["student"]["role"] == "student", mass.get_json())
        with app.app_context():
            row = get_db().execute("SELECT role FROM users WHERE email = ?", ("sneaky@t.test",)).fetchone()
        check("mass assignment ignored in the database", row["role"] == "student", dict(row))

        section("Password storage")
        with app.app_context():
            rows = get_db().execute("SELECT email, password_hash FROM users").fetchall()
        check("every password is bcrypt-hashed", all(r["password_hash"].startswith("$2b$") for r in rows), [r["password_hash"][:7] for r in rows])
        check("no plain-text passwords stored", all(r["password_hash"] != "StudentPass1" for r in rows))
        with app.app_context():
            check("bcrypt cost is 12", rows[0]["password_hash"].split("$")[2] == "12", rows[0]["password_hash"][:7])

        section("Account lockout")
        for attempt in range(1, 6):
            r = login(client, "s3@t.test", "Nope12345")
            check(f"failed login {attempt}/5 returns 401", r.status_code == 401, r.status_code)
        locked = login(client, "s3@t.test", "StudentPass1")
        check("correct password is refused once locked (429)", locked.status_code == 429, locked.get_json())
        with app.app_context():
            row = get_db().execute("SELECT failed_login_attempts, locked_until FROM users WHERE email = ?", ("s3@t.test",)).fetchone()
        check("lockout is stored on the user row", row["locked_until"] is not None, dict(row))
        from app.security import from_iso

        remaining = (from_iso(row["locked_until"]) - utcnow()).total_seconds()
        check("lockout lasts ~15 minutes", 840 < remaining <= 900, f"{remaining:.0f}s")

        # Unlock manually and confirm the account recovers.
        with app.app_context():
            get_db().execute("UPDATE users SET locked_until = NULL, failed_login_attempts = 0 WHERE email = ?", ("s3@t.test",))
        check("account works again after the lock expires", login(client, "s3@t.test", "StudentPass1").status_code == 200)

        section("Role-based access control")
        admin_token = token_for(client, "admin@t.test", "AdminPass1")
        teacher_token = token_for(client, "teacher@t.test", "TeacherPass1")
        student_token = token_for(client, "s1@t.test", "StudentPass1")

        new_user = {"full_name": "New Teacher", "email": "newteacher@t.test", "password": "TeachPass1", "role": "teacher"}
        no_token = client.post("/api/auth/users", json=new_user)
        check("admin-only endpoint without token is 401", no_token.status_code == 401, no_token.status_code)
        as_student = client.post("/api/auth/users", json=new_user, headers=auth(student_token))
        check("student calling admin endpoint is 403", as_student.status_code == 403, as_student.status_code)
        as_teacher = client.post("/api/auth/users", json=new_user, headers=auth(teacher_token))
        check("teacher calling admin endpoint is 403", as_teacher.status_code == 403, as_teacher.status_code)
        as_admin = client.post("/api/auth/users", json=new_user, headers=auth(admin_token))
        check("admin can create a teacher", as_admin.status_code == 201 and as_admin.get_json()["user"]["role"] == "teacher", as_admin.get_json())
        created = client.post(
            "/api/auth/users",
            json={"full_name": "Bad Role", "email": "badrole@t.test", "password": "ValidPass1", "role": "superuser"},
            headers=auth(admin_token),
        )
        check("admin cannot create an unknown role", created.status_code == 400, created.get_json())

        section("Token integrity")
        tampered = student_token[:-3] + ("abc" if not student_token.endswith("abc") else "xyz")
        check("tampered token rejected (401)", client.get("/api/auth/me", headers=auth(tampered)).status_code == 401)
        check("unsigned/garbage token rejected (401)", client.get("/api/auth/me", headers={"Authorization": "Bearer not.a.jwt"}).status_code == 401)

        with app.app_context():
            from flask_jwt_extended import create_access_token

            expired = create_access_token(identity="3", expires_delta=timedelta(seconds=-10))
        expired_response = client.get("/api/auth/me", headers=auth(expired))
        check("expired token rejected (401)", expired_response.status_code == 401, expired_response.get_json())
        check("expired message is explicit", "expired" in expired_response.get_json()["error"]["message"].lower(), expired_response.get_json())

        section("Logout revokes the token")
        fresh = token_for(client, "s2@t.test", "StudentPass1")
        check("token works before logout", client.get("/api/auth/me", headers=auth(fresh)).status_code == 200)
        check("logout returns 200", client.post("/api/auth/logout", headers=auth(fresh)).status_code == 200)
        after = client.get("/api/auth/me", headers=auth(fresh))
        check("token is rejected after logout (401)", after.status_code == 401, after.get_json())

        section("Disabled accounts")
        disabled = login(client, "off@t.test", "DisabledPass1")
        check("disabled account cannot log in (401)", disabled.status_code == 401, disabled.get_json())
        check("disabled message matches the generic one", disabled.get_json()["error"]["message"] == "Invalid email or password.")

        section("Input handling")
        check("malformed JSON body is 400", client.post("/api/auth/login", data="{not json", content_type="application/json").status_code == 400)
        check("missing fields are 400", client.post("/api/auth/login", json={"email": "s1@t.test"}).status_code == 400)
        check("wrong types are 400", client.post("/api/auth/login", json={"email": 123, "password": ["x"]}).status_code == 400)
        check("JSON array body is 400", client.post("/api/auth/login", json=["a"]).status_code == 400)

    section("Database")
    with app.app_context():
        db = get_db()
        check("foreign keys are enabled", db.execute("PRAGMA foreign_keys").fetchone()[0] == 1)
        indexes = {r["name"] for r in db.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        check("unique index on users.email exists", "idx_users_email" in indexes, indexes)
        schema = db.execute("SELECT sql FROM sqlite_master WHERE name='users'").fetchone()["sql"]
        check("users table has the required columns", all(c in schema for c in ["role", "is_active", "failed_login_attempts", "locked_until", "created_at"]))

    print(f"\nRESULT: {PASSED} passed, {FAILED} failed")
    if FAILURES:
        print("Failed checks:")
        for failure in FAILURES:
            print(f"  - {failure}")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
