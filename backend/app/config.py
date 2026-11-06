"""Application configuration.

Every secret and environment-specific value is read from environment
variables (loaded from ``backend/.env``).  Nothing sensitive is hardcoded
in this file - if a required variable is missing the app refuses to boot
instead of silently falling back to an insecure default.
"""

import os

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

    # --- Database (used from Step 1 onwards) ------------------------------
    # Stored under backend/instance/ which is git-ignored.
    DATABASE_PATH = os.environ.get(
        "DATABASE_PATH", os.path.join(BASE_DIR, "instance", "exam_system.db")
    )

    # --- Networking / CORS ------------------------------------------------
    # Only the React app origin may call the API from a browser.
    CORS_ORIGINS = env_list("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    PORT = int(os.environ.get("PORT", "5000"))

    # --- Hardening --------------------------------------------------------
    # Reject oversized request bodies early (cheap DoS guard).
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024  # 2 MB
    # Never leak stack traces / interactive debugger through the API.
    PROPAGATE_EXCEPTIONS = False
