"""Health check endpoint.

Used by the React app (and by any deployment platform) to confirm the API is
up and that no secrets are exposed in the response.
"""

from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify

bp = Blueprint("health", __name__)

# Bumped per step so the frontend can display what is deployed.
API_VERSION = "1.0.0"


@bp.get("/health")
def health():
    """GET /api/health -> liveness probe.

    Returns only non-sensitive metadata.  Note what is *missing* on purpose:
    no secret key, no JWT key, no database path, no configuration dump.
    """
    return jsonify(
        {
            "status": "ok",
            "service": "auspify-tms-api",
            "version": API_VERSION,
            "environment": current_app.config["ENV_NAME"],
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    )
