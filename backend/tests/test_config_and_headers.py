"""Configuration security: secrets, CORS, headers, debug mode, error hygiene."""

import os

from .helpers import bearer


class TestSecrets:
    def test_no_secret_values_in_any_tracked_file(self):
        """The real SECRET_KEY / JWT_SECRET_KEY must not appear in the repo."""
        backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        repo = os.path.dirname(backend)
        secrets_to_find = {
            "SECRET_KEY": os.environ.get("SECRET_KEY", ""),
            "JWT_SECRET_KEY": os.environ.get("JWT_SECRET_KEY", ""),
        }
        # The test values themselves are intentionally fake; look for the
        # development values from backend/.env instead when present.
        env_path = os.path.join(backend, ".env")
        dev_values = []
        if os.path.exists(env_path):
            with open(env_path, encoding="utf-8") as handle:
                for line in handle:
                    key, _, value = line.strip().partition("=")
                    if key in ("SECRET_KEY", "JWT_SECRET_KEY") and value:
                        dev_values.append(value.strip().strip('"'))

        tracked = []
        for root, dirs, files in os.walk(repo):
            dirs[:] = [d for d in dirs if d not in {".git", "node_modules", ".venv", "dist", "instance", "__pycache__"}]
            for name in files:
                if name.endswith((".py", ".js", ".jsx", ".md", ".json", ".sql", ".sh")):
                    tracked.append(os.path.join(root, name))

        leaks = []
        for path in tracked:
            try:
                with open(path, encoding="utf-8", errors="ignore") as handle:
                    content = handle.read()
            except OSError:
                continue
            for label, value in secrets_to_find.items():
                if value and len(value) > 20 and value in content:
                    leaks.append((path, label))
            for value in dev_values:
                if value and len(value) > 20 and value in content:
                    leaks.append((path, "backend/.env value"))
        assert leaks == [], leaks

    def test_env_file_is_git_ignored(self):
        import subprocess

        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        result = subprocess.run(
            ["git", "check-ignore", "backend/.env"], cwd=repo, capture_output=True, text=True
        )
        assert result.returncode == 0, "backend/.env must be git-ignored"

    def test_env_example_has_no_real_secrets(self):
        backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(backend, ".env.example"), encoding="utf-8") as handle:
            content = handle.read()
        assert "replace-me" in content
        # No 64-char hex strings (the shape of a real generated key).
        import re

        assert not re.search(r"[0-9a-f]{64}", content)

    def test_health_endpoint_exposes_no_configuration(self, client):
        body = client.get("/api/health").get_data(as_text=True)
        for key in ("SECRET_KEY", "JWT_SECRET_KEY", "DATABASE_PATH", "password"):
            assert key.lower() not in body.lower()

    def test_root_index_exposes_no_configuration(self, client):
        body = client.get("/", headers={"Accept": "application/json"}).get_data(as_text=True)
        assert "SECRET_KEY" not in body
        assert "DATABASE_PATH" not in body


class TestHeadersAndCors:
    def test_api_security_headers(self, client):
        response = client.get("/api/health")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert "default-src 'none'" in response.headers["Content-Security-Policy"]
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["Referrer-Policy"] == "no-referrer"

    def test_server_banner_does_not_advertise_the_stack(self, client):
        response = client.get("/api/health")
        banner = response.headers.get("Server", "").lower()
        assert "werkzeug" not in banner
        assert "python" not in banner

    def test_allowed_origin_gets_cors_header(self, app, client):
        origin = app.config["CORS_ORIGINS"][0]
        response = client.get("/api/health", headers={"Origin": origin})
        assert response.headers.get("Access-Control-Allow-Origin") == origin

    def test_unknown_origin_is_not_allowed(self, client):
        response = client.get("/api/health", headers={"Origin": "http://evil.example.com"})
        assert "Access-Control-Allow-Origin" not in response.headers

    def test_wildcard_origin_is_never_returned(self, client):
        response = client.get("/api/health", headers={"Origin": "http://evil.example.com"})
        assert response.headers.get("Access-Control-Allow-Origin") != "*"


class TestDebugAndErrors:
    def test_debug_is_off(self, app):
        assert app.config["DEBUG"] is False
        assert app.debug is False

    def test_production_profile_refuses_debug(self):
        """APP_ENV=production + APP_DEBUG=1 must fail at startup, not at runtime."""
        from .conftest import build_app

        with pytest.raises(RuntimeError, match="APP_DEBUG"):
            build_app(ENV_NAME="production", DEBUG=True)

    def test_production_profile_refuses_testing_mode(self):
        from .conftest import build_app

        with pytest.raises(RuntimeError, match="TESTING"):
            build_app(ENV_NAME="production")

    def test_errors_do_not_leak_internals(self, client, teacher_headers):
        responses = [
            client.get("/api/does-not-exist"),
            client.get("/api/exams/999"),
            client.post("/api/exams", json={"title": None}, headers=teacher_headers),
            client.get("/api/auth/me", headers=bearer("garbage.token.value")),
        ]
        for response in responses:
            body = response.get_data(as_text=True)
            assert response.status_code < 500
            assert "Traceback" not in body
            assert "/home/" not in body
            assert "sqlite3" not in body.lower()
            assert response.headers["Content-Type"].startswith("application/json")

    def test_interactive_debugger_is_not_exposed(self, client):
        response = client.get("/api/exams/not-a-number")
        assert response.status_code in (404, 400)
        assert "Werkzeug" not in response.get_data(as_text=True)
        assert "console" not in response.get_data(as_text=True).lower()

    def test_production_profile_requires_secrets(self):
        """Config must fail loudly when a secret is missing (no insecure default)."""
        import importlib

        import app.config as config_module

        saved = os.environ.pop("SECRET_KEY", None)
        try:
            with open(os.path.join(os.path.dirname(config_module.__file__), "..", ".env"), "a+"):
                pass
            # Simulate an empty environment by temporarily blanking the value.
            os.environ["SECRET_KEY"] = ""
            with pytest.raises(RuntimeError):
                importlib.reload(config_module)
        finally:
            if saved is not None:
                os.environ["SECRET_KEY"] = saved
            else:
                os.environ.pop("SECRET_KEY", None)
            importlib.reload(config_module)


import pytest  # noqa: E402  (imported late so the module-level tests stay readable)
