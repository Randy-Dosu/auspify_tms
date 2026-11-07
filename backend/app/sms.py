"""HMAC-SHA256 request signing for the Student Management System (SMS) API.

Students no longer create their own accounts: the university's student
management system provisions them server-to-server. That API can create
accounts, so it must not be reachable with a password or a JWT - it is
authenticated with a shared secret that only the two servers hold.

Scheme (``v1``):

    canonical = "v1" \\n METHOD \\n PATH \\n TIMESTAMP \\n NONCE \\n SHA256(body)
    X-SMS-Signature = "v1=" + hex(HMAC-SHA256(secret, canonical))

* The **body digest** pins every byte of the payload: changing one field
  invalidates the signature, so there is no need to trust TLS alone.
* The **timestamp** bounds the validity to ``SMS_MAX_SKEW_SECONDS`` and the
  **nonce** is stored once, so a captured request cannot be replayed.
* Responses are signed the same way (``v1-response``) and echo the request
  nonce, which lets the SMS prove it is talking to the real TMS and not to a
  proxy or an impersonator.
* The handshake signs a challenge *chosen by the SMS*, so the SMS can verify
  the TMS before it releases any student data.
"""

import hashlib
import hmac
import secrets
import time
from datetime import timedelta
from functools import wraps

from flask import current_app, g, jsonify, request

from .db import get_db
from .security import to_iso, utcnow

HEADER_CLIENT = "X-SMS-Client"
HEADER_TIMESTAMP = "X-SMS-Timestamp"
HEADER_NONCE = "X-SMS-Nonce"
HEADER_SIGNATURE = "X-SMS-Signature"

HEADER_RESPONSE_TIMESTAMP = "X-TMS-Timestamp"
HEADER_RESPONSE_SIGNATURE = "X-TMS-Signature"

SIGNATURE_VERSION = "v1"
RESPONSE_VERSION = "v1-response"
HANDSHAKE_VERSION = "v1-handshake"

# A nonce is only useful until the timestamp window closes; keeping it for
# twice that window means a replay on either side of the window is refused.
NONCE_TTL_MULTIPLIER = 2


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac(secret: str, message: str) -> str:
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def canonical_request(method: str, path: str, timestamp: str, nonce: str, body: bytes) -> str:
    """The exact string both sides sign for a request."""
    return "\n".join(
        [SIGNATURE_VERSION, method.upper(), path, timestamp, nonce, sha256_hex(body)]
    )


def sign_request(secret: str, method: str, path: str, timestamp: str, nonce: str, body: bytes) -> str:
    return _hmac(secret, canonical_request(method, path, timestamp, nonce, body))


def canonical_response(method: str, path: str, status: int, timestamp: str, nonce: str, body: bytes) -> str:
    return "\n".join(
        [RESPONSE_VERSION, method.upper(), path, str(status), timestamp, nonce, sha256_hex(body)]
    )


def sign_response(secret: str, method: str, path: str, status: int, timestamp: str, nonce: str, body: bytes) -> str:
    return _hmac(secret, canonical_response(method, path, status, timestamp, nonce, body))


def handshake_challenge(secret: str, client_id: str, challenge: str, server_time: str) -> str:
    """Signature the SMS checks to prove it is talking to the real TMS."""
    return _hmac(
        secret, "\n".join([HANDSHAKE_VERSION, client_id, challenge, server_time])
    )


def new_nonce() -> str:
    return secrets.token_hex(16)


def new_challenge() -> str:
    return secrets.token_hex(24)


def _error(status: int, message: str):
    return jsonify({"error": {"code": status, "message": message}}), status


def _remember_nonce(client_id: str, nonce: str, ttl_seconds: int) -> bool:
    """Store a nonce; return False when it was already used (a replay)."""
    expires = to_iso(utcnow() + timedelta(seconds=ttl_seconds))
    cursor = get_db().execute(
        "INSERT OR IGNORE INTO sms_nonces (nonce, client_id, seen_at, expires_at)"
        " VALUES (?, ?, ?, ?)",
        (nonce, client_id, to_iso(utcnow()), expires),
    )
    return cursor.rowcount == 1


def sms_required(view):
    """Authorise a signed SMS request, or answer 401/403/503.

    Checks run cheapest-first and the nonce is stored only *after* the
    signature verifies, so unauthenticated traffic cannot fill the nonce
    table.
    """

    @wraps(view)
    def wrapper(*args, **kwargs):
        config = current_app.config
        secret = config["SMS_CLIENT_SECRET"]
        if not secret:
            return _error(
                503,
                "The student management system integration is not configured.",
            )

        allowed = config["SMS_ALLOWED_IPS"]
        if allowed and request.remote_addr not in allowed:
            return _error(403, "This address is not allowed to use the integration API.")

        client_id = (request.headers.get(HEADER_CLIENT) or "").strip()
        timestamp = (request.headers.get(HEADER_TIMESTAMP) or "").strip()
        nonce = (request.headers.get(HEADER_NONCE) or "").strip()
        signature = (request.headers.get(HEADER_SIGNATURE) or "").strip()

        if not (client_id and timestamp and nonce and signature):
            return _error(
                401,
                "Signed request required: send X-SMS-Client, X-SMS-Timestamp,"
                " X-SMS-Nonce and X-SMS-Signature.",
            )

        if not hmac.compare_digest(client_id, config["SMS_CLIENT_ID"]):
            return _error(401, "Unknown integration client.")

        try:
            sent_at = int(timestamp)
        except ValueError:
            return _error(401, "Malformed X-SMS-Timestamp.")

        skew = abs(time.time() - sent_at)
        if skew > config["SMS_MAX_SKEW_SECONDS"]:
            return _error(401, "Request timestamp is outside the allowed window.")

        if len(nonce) < 16 or len(nonce) > 128:
            return _error(401, "Invalid nonce.")

        expected = sign_request(secret, request.method, request.path, timestamp, nonce, request.get_data())
        presented = signature[len(SIGNATURE_VERSION) + 1 :] if signature.startswith(SIGNATURE_VERSION + "=") else signature
        if not hmac.compare_digest(expected, presented):
            return _error(401, "Invalid signature.")

        ttl = config["SMS_MAX_SKEW_SECONDS"] * NONCE_TTL_MULTIPLIER
        if not _remember_nonce(client_id, nonce, ttl):
            return _error(401, "This request has already been used (replayed nonce).")

        g.sms_client = client_id
        g.sms_nonce = nonce
        return view(*args, **kwargs)

    return wrapper


def sign_current_response(response):
    """Attach X-TMS-Timestamp / X-TMS-Signature to a successful response."""
    nonce = getattr(g, "sms_nonce", None)
    secret = current_app.config.get("SMS_CLIENT_SECRET")
    if not nonce or not secret:
        return response
    timestamp = str(int(time.time()))
    response.direct_passthrough = False
    signature = sign_response(
        secret,
        request.method,
        request.path,
        response.status_code,
        timestamp,
        nonce,
        response.get_data(),
    )
    response.headers[HEADER_RESPONSE_TIMESTAMP] = timestamp
    response.headers[HEADER_RESPONSE_SIGNATURE] = f"{SIGNATURE_VERSION}={signature}"
    return response
