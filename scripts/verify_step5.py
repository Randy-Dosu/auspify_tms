"""Step 5 - black-box security checks against the RUNNING API (real HTTP).

Complements backend/tests/ (white-box pytest suite): this script attacks the
live server the way an outsider would, without touching the database directly
except to clean up the lockout probe at the end.

    cd backend && .venv/bin/python ../scripts/verify_step5.py

NOTE: /api/auth/login is rate limited (10/min per IP) on purpose. The script
budgets its login attempts and runs the rate-limit probe last.
"""

import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request

BACKEND = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "backend"))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

from dotenv import dotenv_values  # noqa: E402

ENV = dotenv_values(".env")
BASE = os.environ.get("API_BASE", "http://127.0.0.1:5000/api")
ORIGIN = "http://localhost:5173"
DB_PATH = os.path.join(BACKEND, "instance", "exam_system.db")

PASSED = 0
FAILED = 0
FAILURES = []


def check(label, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  PASS  {label}")
    else:
        FAILED += 1
        FAILURES.append(label)
        print(f"  FAIL  {label}  {detail}")


def call(method, path, token=None, body=None, headers=None, timeout=10):
    """Perform a request, returning (status, parsed body, response headers)."""
    data = json.dumps(body).encode() if body is not None else None
    raw_request = urllib.request.Request(BASE + path, data=data, method=method)
    raw_request.add_header("Accept", "application/json")
    if data:
        raw_request.add_header("Content-Type", "application/json")
    if token:
        raw_request.add_header("Authorization", f"Bearer {token}")
    for key, value in (headers or {}).items():
        raw_request.add_header(key, value)
    try:
        with urllib.request.urlopen(raw_request, timeout=timeout) as response:
            text = response.read().decode(errors="replace")
            return response.status, _parse(text), dict(response.headers)
    except urllib.error.HTTPError as exc:
        text = exc.read().decode(errors="replace")
        return exc.code, _parse(text), dict(exc.headers)


def _parse(text):
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return {"raw": text}


def login(email, password, retries=2):
    """Log in, waiting out the per-IP login rate limiter (10/min) if needed.

    Sections [1]-[5] together exceed the default budget, so a 429 here is a
    harness artefact, not a finding: wait for the rolling window and retry.
    """
    status, payload, headers = call("POST", "/auth/login", body={"email": email, "password": password})
    attempts = 0
    # Two different 429s: the per-IP limiter ("10 per 1 minute") is a harness
    # artefact and worth waiting out; the account lockout ("Too many failed
    # attempts") is a finding and must be reported as-is.
    while status == 429 and attempts < retries and _is_rate_limit(payload):
        attempts += 1
        print("  ...  login rate limited, waiting 62s for the window to clear")
        time.sleep(62)
        status, payload, headers = call("POST", "/auth/login", body={"email": email, "password": password})
    return status, payload, headers


def _is_rate_limit(payload) -> bool:
    message = str((payload or {}).get("error", {}).get("message", "")).lower()
    return "per 1 minute" in message or "per minute" in message


def sqlite_state(email):
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            "SELECT id, failed_login_attempts, locked_until FROM users WHERE email = ?", (email,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        connection.close()


def reset_lockout(email):
    connection = sqlite3.connect(DB_PATH)
    try:
        connection.execute(
            "UPDATE users SET failed_login_attempts = 0, locked_until = NULL WHERE email = ?", (email,)
        )
        connection.commit()
    finally:
        connection.close()


print("\n[1] Authentication: generic errors, no enumeration")
unknown_email = "nobody-here@nowhere.test"
status_unknown, body_unknown, _ = login(unknown_email, "WrongPass123")
status_wrong, body_wrong, _ = login(ENV["SEED_TEACHER_EMAIL"], "definitely-wrong-1")
check("unknown email -> 401", status_unknown == 401, str(status_unknown))
check("wrong password -> 401", status_wrong == 401, str(status_wrong))
check(
    "unknown email and wrong password give the same message",
    body_unknown.get("error", {}).get("message") == body_wrong.get("error", {}).get("message"),
    f"{body_unknown} vs {body_wrong}",
)
check(
    "no 'user does not exist' style detail",
    "exist" not in json.dumps(body_unknown).lower() and "not found" not in json.dumps(body_unknown).lower(),
    json.dumps(body_unknown),
)

print("\n[2] SQL injection on the login form")
injections = [
    ("' OR '1'='1", "' OR '1'='1"),
    ("admin@auspify.test' --", "whatever"),
    ("' UNION SELECT 1,2,3 --", "x"),
]
for email, password in injections:
    status, payload, _ = login(email, password)
    check(f"login payload {email[:24]!r} rejected", status in (401, 422), f"status={status} body={payload}")
    check(
        f"login payload {email[:24]!r} does not return a token",
        "access_token" not in json.dumps(payload),
        json.dumps(payload)[:120],
    )

print("\n[3] Token tampering")
status, admin_login, _ = login(ENV["SEED_ADMIN_EMAIL"], ENV["SEED_ADMIN_PASSWORD"])
check("admin can log in", status == 200 and "access_token" in (admin_login or {}), str(status))
admin_token = (admin_login or {}).get("access_token", "")

segments = admin_token.split(".")
if len(segments) != 3:
    print("  ABORT: admin login did not return a JWT (rate limited?)")
    sys.exit(1)
forged_none = f"{segments[0]}.{segments[1]}."
status, payload, _ = call("GET", "/auth/me", token=forged_none)
check("unsigned (alg=none) token rejected", status == 401, f"{status} {payload}")

tampered = admin_token[:-4] + ("aaaa" if not admin_token.endswith("aaaa") else "bbbb")
status, payload, _ = call("GET", "/auth/me", token=tampered)
check("tampered signature rejected", status == 401, f"{status} {payload}")

status, payload, _ = call("GET", "/auth/me", token="not-a-jwt")
check("garbage token rejected", status == 401, str(status))

status, payload, headers = call("GET", "/auth/me", headers={"Authorization": "Bearer "})
check("empty bearer rejected", status == 401, str(status))

# Privilege escalation by editing the payload by hand.
import base64  # noqa: E402
import hashlib  # noqa: E402
import hmac  # noqa: E402


def b64url_decode(part):
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def b64url_encode(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


status, student_login, _ = login(ENV["SEED_STUDENT1_EMAIL"], ENV["SEED_STUDENT_PASSWORD"])
student_token = (student_login or {}).get("access_token", "")
if not student_token:
    print("  ABORT: student login failed:", student_login)
    sys.exit(1)
status, other_login, _ = login(ENV["SEED_STUDENT2_EMAIL"], ENV["SEED_STUDENT_PASSWORD"])
other_token = (other_login or {}).get("access_token", "")
if not other_token:
    print("  ABORT: second student login failed:", other_login)
    sys.exit(1)
check("second student can log in (for the horizontal-access probe)", bool(other_token), str(status))
privilege_payload = json.loads(b64url_decode(student_token.split(".")[1]))
privilege_payload["role"] = "admin"
forged = ".".join(
    [
        student_token.split(".")[0],
        b64url_encode(json.dumps(privilege_payload, separators=(",", ":")).encode()),
        student_token.split(".")[2],
    ]
)
status, payload, _ = call("GET", "/auth/me", token=forged)
check("role edited in payload is rejected (signature)", status == 401, f"{status} {payload}")

# Re-sign with a guessed secret: proves the signature actually depends on it.
signature = hmac.new(b"guess-the-secret", forged.rsplit(".", 1)[0].encode(), hashlib.sha256).digest()
status, payload, _ = call("GET", "/auth/me", token=f"{forged.rsplit('.', 1)[0]}.{b64url_encode(signature)}")
check("token re-signed with a wrong key is rejected", status == 401, f"{status} {payload}")

print("\n[4] Vertical privilege escalation (student calling staff endpoints)")
teacher_probe = {"title": "Student-made exam", "duration_minutes": 10}
status, payload, _ = call("POST", "/exams", token=student_token, body=teacher_probe)
check("student cannot create an exam", status == 403, f"{status} {payload}")

status, payload, _ = call(
    "POST",
    "/auth/users",
    token=student_token,
    body={"full_name": "Rogue", "email": "rogue@t.test", "password": "ValidPass1", "role": "admin"},
)
check("student cannot create accounts", status == 403, f"{status} {payload}")

status, payload, _ = call("GET", "/reports/exam/1", token=student_token)
check("student cannot read exam reports", status == 403, f"{status} {payload}")

# Students who sat an exam may see its leaderboard once the window closed
# (a Step 4 design decision), so probe with an exam id they never sat.
status, payload, _ = call("GET", "/reports/leaderboard/999999", token=student_token)
check("student cannot read leaderboards", status == 403, f"{status} {payload}")

status, payload, _ = call("GET", "/exams/1/questions", token=student_token)
check("student cannot read the question feed", status == 403, f"{status} {payload}")

status, payload, _ = call("GET", "/api/admin", token=admin_token)
check("unknown admin route still 404 (no route discovery help)", status in (404, 403), str(status))

print("\n[5] Lockout after repeated failures (probe account, cleaned up afterwards)")
# /api/auth/login allows 10 requests per minute per IP and the earlier sections
# already used several. Wait for the rolling window to expire so that the
# lockout probe measures the lockout, not the rate limiter.
time.sleep(61)
probe_email = ENV["SEED_STUDENT3_EMAIL"]
reset_lockout(probe_email)
attempts = [login(probe_email, f"WrongPass{i}").__getitem__(0) for i in range(5)]
check("five bad passwords are all rejected", all(code == 401 for code in attempts), str(attempts))
state = sqlite_state(probe_email)
check("lockout recorded for the account", bool(state and state["locked_until"]), str(state))
status, payload, _ = login(probe_email, ENV["SEED_STUDENT_PASSWORD"])
check("correct password is refused while locked", status in (401, 429), f"{status} {payload}")
locked_message = json.dumps(payload).lower()
check(
    "locked reply never confirms the credentials were right",
    "password is correct" not in locked_message and "welcome" not in locked_message,
    json.dumps(payload),
)
check(
    "locked reply is generic (no account existence hints)",
    "exist" not in locked_message and "not found" not in locked_message,
    json.dumps(payload),
)
reset_lockout(probe_email)
check("probe account unlocked (cleanup)", (sqlite_state(probe_email) or {}).get("locked_until") is None)

print("\n[6] Horizontal access control (student A vs student B)")
probe_attempt_ids = [1, 2, 3, 4, 5]
statuses = [call("GET", f"/attempts/{i}", token=other_token)[0] for i in probe_attempt_ids]
check("other students' attempts are never 200", 200 not in statuses, str(statuses))
check("they are 403/404, not 500", all(s in (403, 404) for s in statuses), str(statuses))
statuses = [call("GET", f"/attempts/{i}/result", token=other_token)[0] for i in probe_attempt_ids]
check("other students' results are never 200", 200 not in statuses, str(statuses))

print("\n[7] Response hygiene: security headers")
status, _, headers = call("GET", "/health")
check("X-Content-Type-Options: nosniff", headers.get("X-Content-Type-Options") == "nosniff", str(headers.get("X-Content-Type-Options")))
check("X-Frame-Options: DENY (no clickjacking)", headers.get("X-Frame-Options") == "DENY", str(headers.get("X-Frame-Options")))
check("Content-Security-Policy present", "default-src 'none'" in (headers.get("Content-Security-Policy") or ""), str(headers.get("Content-Security-Policy")))
check("Cache-Control: no-store", headers.get("Cache-Control") == "no-store", str(headers.get("Cache-Control")))
check("Referrer-Policy: no-referrer", headers.get("Referrer-Policy") == "no-referrer", str(headers.get("Referrer-Policy")))
check("no Server banner leak", "werkzeug" not in json.dumps(headers).lower(), str(headers.get("Server")))

print("\n[8] CORS: only the configured frontend origin is trusted")
status, _, headers = call("GET", "/health", headers={"Origin": ORIGIN})
check("allowed origin echoed back", headers.get("Access-Control-Allow-Origin") == ORIGIN, str(headers.get("Access-Control-Allow-Origin")))
status, _, headers = call("GET", "/health", headers={"Origin": "http://evil.example.com"})
check("foreign origin gets no CORS grant", "Access-Control-Allow-Origin" not in headers, str(headers.get("Access-Control-Allow-Origin")))
check("no wildcard CORS", headers.get("Access-Control-Allow-Origin") != "*", str(headers.get("Access-Control-Allow-Origin")))
status, _, headers = call("OPTIONS", "/exams", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST"})
check("preflight succeeds for the real origin", status in (200, 204), str(status))
status, _, headers = call("OPTIONS", "/exams", headers={"Origin": "http://evil.example.com", "Access-Control-Request-Method": "POST"})
check("preflight from a foreign origin is not granted", headers.get("Access-Control-Allow-Origin") in (None, ""), str(headers.get("Access-Control-Allow-Origin")))

print("\n[9] Error handling: no 500s, no stack traces, no internals")
fuzz = [
    ("GET", "/exams/abc", None),
    ("GET", "/exams/999999999999999999999", None),
    ("GET", "/attempts/0", None),
    ("GET", "/attempts/999999/result", None),
    ("GET", "/reports/exam/not-an-int", None),
    ("DELETE", "/auth/login", None),
    ("POST", "/exams", "{broken json"),
    ("POST", "/exams", "[]"),
    ("POST", "/exams", '{"title": null}'),
    ("PUT", "/attempts/1/answer", '{"question_id": "x"}'),
]
problems = []
for method, path, body in fuzz:
    if isinstance(body, str):
        request = urllib.request.Request(BASE + path, data=body.encode(), method=method)
        request.add_header("Content-Type", "application/json")
        request.add_header("Authorization", f"Bearer {admin_token}")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                status, text = response.status, response.read().decode(errors="replace")
        except urllib.error.HTTPError as exc:
            status, text = exc.code, exc.read().decode(errors="replace")
    else:
        status, payload, _ = call(method, path, token=admin_token)
        text = json.dumps(payload)
    if status >= 500:
        problems.append((method, path, status))
    for marker in ("Traceback", "site-packages", "/home/", "sqlite3."):
        if marker in text:
            problems.append((method, path, marker))
check("malformed requests never return 5xx or leak internals", problems == [], str(problems))

status, payload, headers = call("GET", "/does-not-exist")
check("unknown path is JSON 404", status == 404 and isinstance(payload, dict) and "error" in payload, f"{status} {payload}")
check("unknown path is not an HTML error page", (headers.get("Content-Type") or "").startswith("application/json"), str(headers.get("Content-Type")))

print("\n[10] Sensitive data never appears in API responses")
check("no password hashes in /auth/me", "password_hash" not in json.dumps(call("GET", "/auth/me", token=admin_token)[1]))
check("no bcrypt/argon markers", "$2b$" not in json.dumps(call("GET", "/auth/me", token=admin_token)[1]))
status, exams, _ = call("GET", "/exams", token=student_token)
check("student exam list has no is_correct field", "is_correct" not in json.dumps(exams), json.dumps(exams)[:120])
status, health, _ = call("GET", "/health")
check(
    "health endpoint exposes no configuration",
    not any(k in json.dumps(health).upper() for k in ("SECRET", "DATABASE_PATH", "JWT")),
    json.dumps(health)[:160],
)

print("\n[11] Debug mode / interactive debugger")
status, payload, headers = call("GET", "/exams/not-a-number")
text = json.dumps(payload)
check("no Werkzeug debugger", "werkzeug" not in text.lower() and "console" not in text.lower(), text[:120])
status, payload, _ = call("GET", "/")
check("index does not expose the config", "SECRET_KEY" not in json.dumps(payload), json.dumps(payload)[:120])

print("\n[12] Login rate limiting (deliberately trips the limiter - last check)")
hit = None
codes = []
for _ in range(20):
    # Deliberately NOT using the retrying wrapper: this section needs the raw
    # 429 to prove the limiter is active.
    status, payload, headers = call(
        "POST", "/auth/login", body={"email": unknown_email, "password": "WrongPass123"}
    )
    codes.append(status)
    if status == 429:
        hit = (payload, headers)
        break
    time.sleep(0.05)
check("repeated logins eventually return 429", hit is not None, str(codes))
if hit:
    payload, headers = hit
    check("429 body is a clean JSON error", isinstance(payload, dict) and "error" in payload, str(payload)[:120])
    check("429 tells the client when to retry", headers.get("Retry-After") is not None, str(headers.get("Retry-After")))

print("\n" + "=" * 60)
print(f"Step 5 live security checks: {PASSED} passed, {FAILED} failed")
if FAILURES:
    print("Failures:")
    for failure in FAILURES:
        print(f"  - {failure}")
print("=" * 60)
sys.exit(1 if FAILED else 0)
