"""Flask application factory.

Creates and configures the API app.  Keeping this in a factory function
means tests (added in Step 5) can spin up isolated app instances.
"""

import logging
import os

from flask import Flask, Response, jsonify, request
from flask_cors import CORS
from marshmallow import ValidationError
from werkzeug.exceptions import HTTPException
from werkzeug.routing import IntegerConverter

from .config import Config
from .db import init_app as init_db_app
from .extensions import limiter
from .security import init_jwt


def create_app(config_class=Config) -> Flask:
    """Build a configured Flask application."""
    app = Flask(__name__)
    app.config.from_object(config_class)

    _guard_production_config(app)
    _ensure_instance_dir(app)
    _register_url_converters(app)
    _configure_logging(app)
    _configure_cors(app)
    _register_root_route(app)
    _register_blueprints(app)
    _register_error_handlers(app)
    _register_security_headers(app)

    # Extensions
    init_jwt(app)
    limiter.init_app(app)
    init_db_app(app)

    return app


def _guard_production_config(app: Flask) -> None:
    """Refuse to start a production profile that leaks internals.

    Debug mode returns Werkzeug tracebacks to the caller and enables the
    interactive debugger; the Flask test client would also change behaviour.
    Production must therefore run with APP_DEBUG=0 and without TESTING.
    """

    if app.config.get("ENV_NAME") != "production":
        return
    if app.config.get("DEBUG"):
        raise RuntimeError("APP_DEBUG must be 0 when APP_ENV=production.")
    if app.config.get("TESTING"):
        raise RuntimeError("TESTING must be off when APP_ENV=production.")


def _register_url_converters(app: Flask) -> None:
    """Bound every ``<int:...>`` URL variable so absurd ids cannot 500.

    SQLite cannot bind integers wider than 64 bits, so a request such as
    ``GET /api/exams/999999999999999999999`` used to raise inside the driver and
    surface as a 500.  Capping the converter turns those ids into ordinary 404s
    before any database code runs.
    """

    class BoundedIntConverter(IntegerConverter):
        def __init__(self, map, min=0, max=2**63 - 1):  # noqa: A002 - werkzeug's names
            super().__init__(map, min=min, max=max)

    # Replaces the built-in converter for every route registered afterwards.
    app.url_map.converters["int"] = BoundedIntConverter


def _ensure_instance_dir(app: Flask) -> None:
    """Make sure the folder holding the SQLite file exists."""
    directory = os.path.dirname(app.config["DATABASE_PATH"])
    if directory:
        os.makedirs(directory, exist_ok=True)


def _register_root_route(app: Flask) -> None:
    """Serve a status page to browsers and a JSON index to API clients.

    Opening the API port in a browser used to show raw JSON (or a bare 404),
    which looks like the server is down. Browsers now get a small,
    script-free HTML page; curl/axios/fetch clients still get JSON.
    """

    @app.get("/")
    def api_index():
        if _client_wants_html():
            return Response(_status_page_html(), mimetype="text/html")
        return jsonify(
            {
                "service": "auspify-tms-api",
                "message": "Online Examination System API. JSON only - use /api/*.",
                "endpoints": {"health": "/api/health"},
                "docs": "The React UI runs on the frontend origin (default :5173).",
            }
        )


def _client_wants_html() -> bool:
    """True for browsers, False for scripted clients.

    Browsers explicitly list text/html and do not ask for application/json;
    curl, fetch() and axios send */* or application/json.
    """
    accept = request.headers.get("Accept", "")
    return "text/html" in accept and "application/json" not in accept


def _status_page_html() -> str:
    """Tiny, dependency-free status page: no JavaScript, no external assets."""
    return """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Auspify TMS API</title>
    <style>
      :root { color-scheme: light; }
      body {
        margin: 0; min-height: 100vh; display: grid; place-items: center;
        font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
        background: #f5f7fb; color: #1e293b; padding: 2rem;
      }
      main {
        max-width: 34rem; background: #fff; border: 1px solid #e2e8f0;
        border-radius: 12px; padding: 1.75rem 2rem;
        box-shadow: 0 1px 2px rgba(15,23,42,.06), 0 8px 24px rgba(15,23,42,.06);
      }
      h1 { margin: 0 0 .25rem; font-size: 1.35rem; }
      p { margin: .4rem 0; color: #475569; line-height: 1.55; }
      .ok { display: inline-block; background: #dcfce7; color: #15803d;
            border: 1px solid #bbf7d0; border-radius: 999px;
            padding: .15rem .6rem; font-size: .78rem; font-weight: 600; }
      code { background: #f1f5f9; border-radius: 4px; padding: .1rem .35rem;
             font-family: ui-monospace, Menlo, Consolas, monospace; font-size: .85em; }
      ul { padding-left: 1.1rem; color: #334155; font-size: .92rem; }
      footer { margin-top: 1.25rem; font-size: .82rem; color: #64748b; }
    </style>
  </head>
  <body>
    <main>
      <span class="ok">&#9679; API is running</span>
      <h1>Auspify TMS &mdash; Online Examination System API</h1>
      <p>This port serves the JSON API, not the user interface.</p>
      <ul>
        <li><code>GET /api/health</code> &mdash; liveness check</li>
        <li><code>/api/auth/*</code>, <code>/api/exams</code>, <code>/api/reports/*</code> &mdash; added in later steps</li>
      </ul>
      <footer>The React UI runs on the frontend dev server (default port 5173).</footer>
    </main>
  </body>
</html>"""


# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------
def _configure_logging(app: Flask) -> None:
    """Plain, predictable logging.

    We only ever log request lines (method + path + status).  Request bodies
    are never logged, so passwords cannot leak into log files.
    """
    logging.basicConfig(
        level=logging.DEBUG if app.config.get("DEBUG") else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _configure_cors(app: Flask) -> None:
    """Allow only the configured frontend origin(s) to call the API.

    A wildcard ("*") is deliberately avoided: browsers must be told exactly
    which origin may read responses.
    """
    CORS(
        app,
        resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}},
        supports_credentials=False,  # tokens travel in the Authorization header
        allow_headers=["Content-Type", "Authorization"],
        methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        max_age=600,
    )


def _register_blueprints(app: Flask) -> None:
    """Attach all API blueprints under /api."""
    from .routes.attempts import bp as attempts_bp
    from .routes.auth import bp as auth_bp
    from .routes.exams import bp as exams_bp
    from .routes.health import bp as health_bp
    from .routes.reports import bp as reports_bp

    app.register_blueprint(health_bp, url_prefix="/api")
    app.register_blueprint(auth_bp)  # prefix lives on the blueprint: /api/auth
    app.register_blueprint(exams_bp)
    app.register_blueprint(attempts_bp)
    app.register_blueprint(reports_bp)  # /api/reports/*


def _register_error_handlers(app: Flask) -> None:
    """Return clean JSON errors - never HTML, never a stack trace."""

    @app.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException):
        # Werkzeug raises HTTPException for 400/401/404/405/413/429 ... etc.
        message = error.description or error.name
        return (
            jsonify({"error": {"code": error.code, "message": message}}),
            error.code,
        )

    @app.errorhandler(ValidationError)
    def handle_validation_error(error: ValidationError):
        # Defensive: route code converts schema errors itself, so this is a net
        # for anything unexpected - still a clean 400, never a 500.
        return (
            jsonify(
                {
                    "error": {
                        "code": 400,
                        "message": "Validation failed.",
                        "fields": error.messages,
                    }
                }
            ),
            400,
        )

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception):  # pragma: no cover - safety net
        # Log the detail server-side, return a generic message to the client.
        app.logger.exception("Unhandled exception on %s %s", request.method, request.path)
        return (
            jsonify(
                {
                    "error": {
                        "code": 500,
                        "message": "An unexpected error occurred. Please try again.",
                    }
                }
            ),
            500,
        )


def _register_security_headers(app: Flask) -> None:
    """Attach security headers to every response.

    Two profiles:
      * /api/*  - locked down completely. JSON only, never framed, never cached.
      * everything else - the human-facing status page. In development
        (ALLOW_PREVIEW_EMBEDDING=1) it may be framed by a hosted preview,
        because otherwise the preview pane renders blank and the app looks
        down. Scripts are always forbidden there; production keeps DENY.
    """

    strict_csp = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    page_csp = (
        "default-src 'none'; style-src 'unsafe-inline'; "
        "frame-ancestors *; base-uri 'none'; form-action 'none'"
    )

    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"

        if request.path.startswith("/api/"):
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Content-Security-Policy"] = strict_csp
            response.headers["Cache-Control"] = "no-store"
        elif app.config.get("ALLOW_PREVIEW_EMBEDDING", False):
            # Embeddable status page: no X-Frame-Options, frame-ancestors *.
            response.headers["Content-Security-Policy"] = page_csp
        else:
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Content-Security-Policy"] = strict_csp

        return response
