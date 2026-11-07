"""Pytest fixtures for the security suite.

Every test runs against a fresh, throw-away SQLite database. Secrets are
injected through environment variables (never files) so the suite also runs in
CI without the development .env.
"""

import os
import sys
import tempfile

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

# Must be set before app.config is imported (it fails fast without secrets).
os.environ.setdefault("SECRET_KEY", "test-secret-key-" + "a" * 40)
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-key-" + "b" * 40)
os.environ["APP_ENV"] = "test"
os.environ["APP_DEBUG"] = "0"  # production-like: debug must be off

from app import create_app  # noqa: E402
from app.config import Config  # noqa: E402

from .helpers import ACCOUNTS, SMS_CLIENT_ID, SMS_SECRET, SmsRequester, seed_accounts  # noqa: E402


def build_app(**overrides):
    """Create an app with its own temporary database."""
    path = tempfile.mktemp(suffix=".db")

    class TestConfig(Config):
        DATABASE_PATH = path
        TESTING = True
        DEBUG = False
        RATELIMIT_ENABLED = False
        # The SMS integration is on by default in tests; individual tests
        # switch it off or rotate the secret to prove it is enforced.
        SMS_CLIENT_ID = SMS_CLIENT_ID
        SMS_CLIENT_SECRET = SMS_SECRET
        SMS_MAX_SKEW_SECONDS = 300
        SMS_ALLOWED_IPS = []

    for key, value in overrides.items():
        setattr(TestConfig, key, value)

    application = create_app(TestConfig)
    with application.app_context():
        seed_accounts()
    return application


@pytest.fixture()
def app():
    application = build_app()
    yield application


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def sms(client):
    """A signed-request client standing in for the student management system."""
    return SmsRequester(client)


@pytest.fixture()
def accounts(client):
    """email -> {id, password, role} for the seeded users."""
    from app.db import get_db

    result = {}
    with client.application.app_context():
        rows = get_db().execute("SELECT id, email, password_hash, role FROM users").fetchall()
    passwords = {item["email"]: item["password"] for item in ACCOUNTS}
    for row in rows:
        result[row["email"]] = {
            "id": row["id"],
            "role": row["role"],
            "password": passwords.get(row["email"], ""),
        }
    return result


@pytest.fixture()
def tokens(client, accounts):
    """email -> bearer token."""
    out = {}
    for email, info in accounts.items():
        response = client.post(
            "/api/auth/login", json={"email": email, "password": info["password"]}
        )
        if response.status_code == 200:
            out[email] = response.get_json()["access_token"]
    return out


@pytest.fixture()
def teacher_headers(tokens):
    return {"Authorization": f"Bearer {tokens['teacher@t.test']}"}


@pytest.fixture()
def other_teacher_headers(tokens):
    return {"Authorization": f"Bearer {tokens['teacher2@t.test']}"}


@pytest.fixture()
def student_headers(tokens):
    return {"Authorization": f"Bearer {tokens['student1@t.test']}"}


@pytest.fixture()
def other_student_headers(tokens):
    return {"Authorization": f"Bearer {tokens['student2@t.test']}"}


@pytest.fixture()
def admin_headers(tokens):
    return {"Authorization": f"Bearer {tokens['admin@t.test']}"}


@pytest.fixture()
def rate_limited_client():
    """Separate app with rate limiting ON and a low login limit."""
    application = build_app(RATELIMIT_ENABLED=True, LOGIN_RATE_LIMIT="3 per minute")
    return application.test_client()
