"""Application configuration.

Every secret and environment-specific value is read from environment
variables (loaded from ``backend/.env``).  Nothing sensitive is hardcoded
in this file - if a required variable is missing the app refuses to boot
instead of silently falling back to an insecure default.
"""

import os
from datetime import timedelta

from dotenv import load_dotenv

# Absolute path of the backend/ directory (this file lives in backend/app/).
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))

# Load backend/.env (git-ignored) before reading any variable.
load_dotenv(os.path.join(BASE_DIR, ".env"))


def require_env(name: str) -> str:
    """Return an env var or fail loudly.

    Used for secrets so the app can never start with an empty/guessable key.
    """
    value = os.environ.get(name)
    if not value or not value.strip():
        raise RuntimeError(
            f"Missing required environment variable '{name}'. "
            "Copy backend/.env.example to backend/.env and fill it in."
        )
    return value


def env_bool(name: str, default: bool = False) -> bool:
    """Parse a boolean-ish environment variable ("1", "true", "yes", "on")."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    """Parse a comma-separated environment variable into a clean list."""
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


class Config:
    """Base configuration shared by all environments."""

    # --- Core -------------------------------------------------------------
    SECRET_KEY = require_env("SECRET_KEY")
    DEBUG = env_bool("APP_DEBUG", default=False)  # must be False in production
    ENV_NAME = os.environ.get("APP_ENV", "development")

    # --- JWT settings (used from Step 1 onwards) --------------------------
    # Kept separate from SECRET_KEY so tokens can be rotated independently.
    JWT_SECRET_KEY = require_env("JWT_SECRET_KEY")
    JWT_ACCESS_TOKEN_EXPIRES_MINUTES = int(
        os.environ.get("JWT_ACCESS_TOKEN_EXPIRES_MINUTES", "30")
    )
    JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
    # Flask-JWT-Extended settings: tokens only travel in the Authorization
    # header ("Bearer <token>"), never in cookies or query strings.
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRES_MINUTES)
    JWT_TOKEN_LOCATION = ["headers"]
    JWT_HEADER_TYPE = "Bearer"

    # --- Authentication hardening -----------------------------------------
    MAX_FAILED_LOGINS = int(os.environ.get("MAX_FAILED_LOGINS", "5"))
    LOCKOUT_MINUTES = int(os.environ.get("LOCKOUT_MINUTES", "15"))
    # Brute-force protection per client IP (Flask-Limiter).
    LOGIN_RATE_LIMIT = os.environ.get("LOGIN_RATE_LIMIT", "10 per minute")
    REGISTER_RATE_LIMIT = os.environ.get("REGISTER_RATE_LIMIT", "20 per minute")
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_ENABLED = env_bool("RATELIMIT_ENABLED", default=True)
    RATELIMIT_HEADERS_ENABLED = True

    # --- Database (used from Step 1 onwards) ------------------------------
    # Stored under backend/instance/ which is git-ignored.
    _db_env = os.environ.get(
        "DATABASE_PATH", os.path.join(BASE_DIR, "instance", "exam_system.db")
    )
    # Relative paths are resolved against backend/ so the app can be started
    # from any working directory.
    DATABASE_PATH = _db_env if os.path.isabs(_db_env) else os.path.join(BASE_DIR, _db_env)

    # --- Networking / CORS ------------------------------------------------
    # Only the React app origin may call the API from a browser.
    CORS_ORIGINS = env_list("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    PORT = int(os.environ.get("PORT", "5000"))

    # --- Hardening --------------------------------------------------------
    # Reject oversized request bodies early (cheap DoS guard).
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024  # 2 MB
    # Never leak stack traces / interactive debugger through the API.
    PROPAGATE_EXCEPTIONS = False

    # Allow the human-facing status page at "/" to be shown inside an iframe
    # (hosted dev previews embed the app). API responses are NEVER embeddable,
    # and this is off by default in production.
    ALLOW_PREVIEW_EMBEDDING = env_bool(
        "ALLOW_PREVIEW_EMBEDDING", default=(ENV_NAME != "production")
    )
