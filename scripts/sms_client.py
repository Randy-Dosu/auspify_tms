"""Reference client for the TMS student-provisioning API.

This is the code the student management system (SMS) runs: it signs each
request with the shared secret, and it verifies the TMS's signature on every
reply (including the handshake) before it trusts the answer.

Usage as a library::

    from sms_client import SmsClient
    sms = SmsClient("http://localhost:5000", client_id, secret)
    sms.handshake()                       # proves the TMS is genuine
    sms.provision("Ama Owusu", "ama@uni.edu", "BSc IT", "IT/2024/0002", "Passw0rd!")

Usage from the shell (reads backend/.env for the credentials)::

    python scripts/sms_client.py handshake
    python scripts/sms_client.py provision --name "Ama" --email ama@uni.edu \
        --course "BSc IT" --number IT/2024/0002 --password 'Passw0rd!'
    python scripts/sms_client.py status --email ama@uni.edu --inactive
    python scripts/sms_client.py lookup --email ama@uni.edu
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import pathlib
import secrets
import sys
import time
import urllib.error
import urllib.request

SIGNATURE_HEADER = "X-SMS-Signature"
RESPONSE_SIGNATURE_HEADER = "X-TMS-Signature"
SIGNATURE_VERSION = "v1"
RESPONSE_VERSION = "v1-response"
HANDSHAKE_VERSION = "v1-handshake"


class SmsError(RuntimeError):
    """The TMS refused the request (or the reply failed verification)."""

    def __init__(self, message: str, status: int | None = None, payload=None):
        super().__init__(message)
        self.status = status
        self.payload = payload


def _hmac(secret: str, message: str) -> str:
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sign_request(secret: str, method: str, path: str, timestamp: str, nonce: str, body: bytes) -> str:
    canonical = "\n".join(
        [SIGNATURE_VERSION, method.upper(), path, timestamp, nonce, _sha256(body)]
    )
    return _hmac(secret, canonical)


def verify_response(
    secret: str, method: str, path: str, status: int, timestamp: str, nonce: str, body: bytes
) -> str:
    canonical = "\n".join(
        [RESPONSE_VERSION, method.upper(), path, str(status), timestamp, nonce, _sha256(body)]
    )
    return _hmac(secret, canonical)


def verify_handshake(secret: str, client_id: str, challenge: str, server_time: str) -> str:
    return _hmac(secret, "\n".join([HANDSHAKE_VERSION, client_id, challenge, server_time]))


class SmsClient:
    """Signs outgoing calls and verifies every incoming answer."""

    def __init__(
        self,
        base_url: str,
        client_id: str,
        secret: str,
        *,
        verify_handshake_on_init: bool = False,
        timeout: float = 15.0,
    ):
        if not secret:
            raise SmsError("SMS_CLIENT_SECRET is empty: the integration is switched off.")
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.secret = secret
        self.timeout = timeout
        self.verified = False
        if verify_handshake_on_init:
            self.handshake()

    # -- transport ---------------------------------------------------------
    def request(self, path: str, payload: dict | None, *, method: str = "POST", verify: bool = True):
        """Send one signed request; verify the signed reply unless disabled."""
        body = b"" if payload is None else json.dumps(payload, separators=(",", ":")).encode()
        timestamp = str(int(time.time()))
        nonce = secrets.token_hex(16)
        signature = sign_request(self.secret, method, path, timestamp, nonce, body)

        headers = {
            "Content-Type": "application/json",
            "X-SMS-Client": self.client_id,
            "X-SMS-Timestamp": timestamp,
            "X-SMS-Nonce": nonce,
            SIGNATURE_HEADER: f"{SIGNATURE_VERSION}={signature}",
        }

        request = urllib.request.Request(
            self.base_url + path, data=body or None, headers=headers, method=method
        )
        try:
            response = urllib.request.urlopen(request, timeout=self.timeout)
            status, raw, reply_headers = response.status, response.read(), response.headers
        except urllib.error.HTTPError as exc:
            # Error replies are still signed and still carry the JSON error body.
            status, raw, reply_headers = exc.code, exc.read(), exc.headers

        if verify and reply_headers.get(RESPONSE_SIGNATURE_HEADER):
            signed_at = reply_headers.get("X-TMS-Timestamp", "")
            presented = reply_headers[RESPONSE_SIGNATURE_HEADER]
            presented = (
                presented[len(SIGNATURE_VERSION) + 1 :]
                if presented.startswith(SIGNATURE_VERSION + "=")
                else presented
            )
            expected = verify_response(self.secret, method, path, status, signed_at, nonce, raw)
            if not hmac.compare_digest(expected, presented):
                raise SmsError("The TMS reply failed signature verification.", status)

        try:
            data = json.loads(raw.decode("utf-8")) if raw else None
        except ValueError:
            data = None

        if status >= 400:
            message = "request failed"
            if isinstance(data, dict) and isinstance(data.get("error"), dict):
                message = data["error"].get("message", message)
            raise SmsError(message, status, data)

        return data

    # -- operations --------------------------------------------------------
    def handshake(self) -> dict:
        """Prove the TMS holds the shared secret before sending any student data."""
        challenge = secrets.token_hex(24)
        data = self.request("/api/integration/handshake", {"challenge": challenge}) or {}
        expected = verify_handshake(
            self.secret, self.client_id, challenge, str(data.get("server_time", ""))
        )
        if not hmac.compare_digest(expected, str(data.get("signature", ""))):
            raise SmsError("The handshake signature is invalid: this is not the expected TMS.")
        if data.get("challenge") != challenge:
            raise SmsError("The handshake echoed a different challenge.")
        self.verified = True
        return data

    def provision(
        self,
        full_name: str,
        email: str,
        course: str = "",
        student_number: str | None = None,
        password: str | None = None,
        is_active: bool = True,
    ) -> dict:
        payload = {
            "full_name": full_name,
            "email": email,
            "course": course,
            "student_number": student_number,
            "is_active": is_active,
        }
        if password:
            payload["password"] = password
        return self.request("/api/integration/students", payload) or {}

    def set_status(self, email: str, is_active: bool) -> dict:
        return self.request(
            "/api/integration/students/status", {"email": email, "is_active": is_active}
        ) or {}

    def lookup(self, email: str) -> dict:
        return self.request("/api/integration/students/lookup", {"email": email}) or {}


def _credentials() -> tuple[str, str, str]:
    """Read the integration settings from backend/.env (or the environment)."""
    env_file = pathlib.Path(__file__).resolve().parent.parent / "backend" / ".env"
    values = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    client_id = os.environ.get("SMS_CLIENT_ID") or values.get("SMS_CLIENT_ID") or "sms-gateway"
    secret = os.environ.get("SMS_CLIENT_SECRET") or values.get("SMS_CLIENT_SECRET") or ""
    base = (
        os.environ.get("SMS_BASE_URL")
        or values.get("SMS_BASE_URL")
        or f"http://127.0.0.1:{values.get('PORT', '5000')}"
    )
    return base, client_id, secret


def main(argv=None) -> int:
    base, client_id, secret = _credentials()
    parser = argparse.ArgumentParser(description="TMS student provisioning client")
    parser.add_argument("--base", default=base, help="API base URL")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("handshake", help="verify the TMS before sending student data")

    provision = sub.add_parser("provision", help="create or update a student")
    provision.add_argument("--name", required=True)
    provision.add_argument("--email", required=True)
    provision.add_argument("--course", default="")
    provision.add_argument("--number", default=None)
    provision.add_argument("--password", default=None)
    provision.add_argument("--inactive", action="store_true")

    status = sub.add_parser("status", help="activate or deactivate a student")
    status.add_argument("--email", required=True)
    status.add_argument("--inactive", action="store_true")

    lookup = sub.add_parser("lookup", help="does this student exist?")
    lookup.add_argument("--email", required=True)

    args = parser.parse_args(argv)
    client = SmsClient(args.base, client_id, secret)

    try:
        if args.command == "handshake":
            data = client.handshake()
            print(f"verified TMS {data['service']} v{data['version']} (client {data['client_id']})")
        elif args.command == "provision":
            data = client.provision(
                args.name,
                args.email,
                args.course,
                args.number,
                args.password,
                not args.inactive,
            )
            print(json.dumps({"created": data.get("created"), "student": data.get("student")}, indent=2))
        elif args.command == "status":
            print(json.dumps(client.set_status(args.email, not args.inactive), indent=2))
        else:
            print(json.dumps(client.lookup(args.email), indent=2))
    except SmsError as exc:
        print(f"error: {exc} (status={exc.status})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
