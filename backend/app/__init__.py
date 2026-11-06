"""Flask application factory.

Creates and configures the API app.  Keeping this in a factory function
means tests (added in Step 5) can spin up isolated app instances.
"""

import logging

from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from .config import Config


def create_app(config_class=Config) -> Flask:
    """Build a configured Flask application."""
    app = Flask(__name__)
    app.config.from_object(config_class)

    _configure_logging(app)
    _configure_cors(app)
    _register_blueprints(app)
    _register_error_handlers(app)
    _register_security_headers(app)

    return app


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
    from .routes.health import bp as health_bp

    app.register_blueprint(health_bp, url_prefix="/api")


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
    """Attach baseline security headers to every response."""

    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        # The API only ever returns JSON: forbid loading anything at all.
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        )
        # API responses must not be cached by browsers or proxies.
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response
