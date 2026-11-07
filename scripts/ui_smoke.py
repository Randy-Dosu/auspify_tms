"""Browser-session test: walk every page the way the running UI does.

There is no browser in this sandbox, so instead of clicking, this script speaks
to the SAME origin the browser uses (the Vite dev server on :5173, whose /api
proxy forwards to Flask) and asserts every field each React page renders. A
missing/renamed field breaks the page silently in a browser; here it fails the
check.

    cd frontend && ../backend/.venv/bin/python ../scripts/ui_smoke.py

It is idempotent: it reuses a fixed smoke account (registering it once) and
creates one fresh smoke exam per run, which it unpublishes when finished so
seeded students never see it. The smoke account therefore accumulates one
attempt per run - that is what makes its progress page worth checking.
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

BACKEND = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "backend"))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

from dotenv import dotenv_values  # noqa: E402

ENV = dotenv_values(".env")
SITE = os.environ.get("SITE_BASE", "http://127.0.0.1:5173")
API = f"{SITE}/api"

SMOKE_EMAIL = "ui-smoke@t.test"
SMOKE_PASSWORD = "SmokeTest123"

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


def http(method, path, token=None, body=None, raw=False):
    """Request a SITE path (not just API) so static + SPA checks use the same code."""
    url = path if path.startswith("http") else SITE + path
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Accept", "text/html,application/json,*/*")
    if data:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            text = response.read().decode(errors="replace")
            return response.status, text, dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace"), dict(exc.headers)


def api(method, path, token=None, body=None):
    status, text, headers = http(method, "/api" + path, token=token, body=body)
    try:
        payload = json.loads(text) if text else None
    except ValueError:
        payload = {"raw": text}
    return status, payload, headers


def login(email, password, retries=2):
    """Log in, waiting out the login rate limiter (10/min per IP) if needed."""
    status, payload, headers = api("POST", "/auth/login", body={"email": email, "password": password})
    attempts = 0
    while status == 429 and attempts < retries:
        attempts += 1
        wait = 62
        print(f"  ...  login rate limited, waiting {wait}s for the window to clear")
        time.sleep(wait)
        status, payload, headers = api("POST", "/auth/login", body={"email": email, "password": password})
    return status, payload, headers


def header(headers, name):
    """Case-insensitive header lookup: HTTP/2 and Node proxies lower-case names."""
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return ""


def keys(obj):
    return set(obj.keys()) if isinstance(obj, dict) else set()


def missing(obj, required):
    return sorted(set(required) - keys(obj))


# ---------------------------------------------------------------------------
print(f"\n[A] The site itself loads ({SITE})")
status, html, headers = http("GET", "/")
check("/ serves the app shell", status == 200 and 'id="root"' in html, str(status))
check("shell has the product title", "Auspify TMS" in html, html[:200])
# The dev server injects /src/main.jsx; the production build (vite preview)
# references a hashed /assets/index-*.js. Accept either and fetch whatever the
# shell actually points at - that is the file the browser would load.
# dev serves /src/main.jsx (Vite also injects an inline refresh preamble);
# the production build references /assets/index-<hash>.js
entry = re.search(r'<script[^>]+src="([^"]+\.(?:m?js|jsx))"', html)
check("shell references a JavaScript entry point", entry is not None, html[:200])
if entry:
    entry_path = entry.group(1)
    status, js_body, js_headers = http("GET", entry_path)
    check(f"entry {entry_path} is served as JavaScript",
          status == 200 and "javascript" in header(js_headers, "Content-Type"),
          f"{status} {header(js_headers, 'Content-Type')}")
    check("the entry bundle has content", len(js_body) > 1000, f"{len(js_body)} bytes")
check("favicon exists (no 404 in the console)", http("GET", "/favicon.svg")[0] == 200)
for route in ("/login", "/register", "/student", "/student/progress", "/teacher", "/teacher/exams/1",
              "/teacher/reports/1", "/teacher/students/1", "/does-not-exist"):
    status, body, _ = http("GET", route)
    check(f"deep link {route} falls back to the SPA", status == 200 and 'id="root"' in body, str(status))
status, health, _ = api("GET", "/health")
check("/api is proxied to Flask from the UI origin", status == 200 and health.get("status") in ("ok", "healthy"),
      f"{status} {health}")

print("\n[B] Anonymous state and the login screen")
status, me, _ = api("GET", "/auth/me")
check("no token -> 401 (AuthProvider clears the session)", status == 401, str(status))
status, bad, _ = login(SMOKE_EMAIL, "definitely-wrong-1")
check("wrong password -> generic 401 shown in the Alert", status == 401 and "error" in bad, f"{status} {bad}")

status, created, _ = api("POST", "/auth/register",
                         body={"full_name": "UI Smoke", "email": SMOKE_EMAIL, "password": SMOKE_PASSWORD})
student_token = None
if status == 201:
    check("register page flow creates a student", created.get("user", {}).get("role") == "student", str(created)[:160])
    student_token = created.get("access_token")
else:
    check("smoke account already exists (re-runnable)", status == 409, f"{status} {created}")

status, student_login, _ = login(SMOKE_EMAIL, SMOKE_PASSWORD)
student_user = (student_login or {}).get("user") or {}
student_token = (student_login or {}).get("access_token") or student_token
check("smoke student can sign in", status == 200 and bool(student_token), f"{status} {student_login}")
check("login payload has the fields AppLayout renders",
      not missing(student_user, ["id", "full_name", "email", "role", "created_at"]),
      str(missing(student_user, ["id", "full_name", "email", "role", "created_at"])))

status, teacher_login, _ = login(ENV["SEED_TEACHER_EMAIL"], ENV["SEED_TEACHER_PASSWORD"])
teacher_token = (teacher_login or {}).get("access_token")
check("teacher can sign in", status == 200 and bool(teacher_token), str(status))
status, admin_login, _ = login(ENV["SEED_ADMIN_EMAIL"], ENV["SEED_ADMIN_PASSWORD"])
admin_token = (admin_login or {}).get("access_token")
check("admin can sign in", status == 200 and bool(admin_token), str(status))

status, me, _ = api("GET", "/auth/me", token=student_token)
check("/auth/me returns the session the layout renders",
      status == 200 and not missing(me.get("user", {}), ["id", "full_name", "email", "role"]), str(me)[:160])

print("\n[C] Teacher: exam list, "+"+ New exam"+", the builder, and the report page")
status, listing, _ = api("GET", "/exams", token=teacher_token)
exams = (listing or {}).get("exams", [])
check("teacher exam list loads", status == 200 and isinstance(exams, list), str(status))
if exams:
    fields = ["id", "title", "subject", "total_marks", "is_published", "question_count", "attempt_count"]
    check("rows have every column TeacherExamsPage renders", not missing(exams[0], fields),
          str(missing(exams[0], fields)))

status, new_exam, _ = api("POST", "/exams", token=teacher_token,
                          body={"title": "UI smoke exam", "duration_minutes": 30, "pass_marks": 0,
                                "is_published": False})
check('"+ New exam" creates a draft and the editor can open it',
      status == 201 and (new_exam or {}).get("exam", {}).get("id"), f"{status} {new_exam}")
exam_id = ((new_exam or {}).get("exam") or {}).get("id")

if exam_id:
    status, detail, _ = api("GET", f"/exams/{exam_id}", token=teacher_token)
    exam = (detail or {}).get("exam", {})
    check("editor loads the exam with its questions",
          status == 200 and "questions" in exam and "is_published" in exam, str(status))

    # Exactly the payload the editor sends when saving settings.
    status, saved, _ = api("PUT", f"/exams/{exam_id}", token=teacher_token,
                           body={"title": "UI smoke exam", "subject": "Smoke", "duration_minutes": 20,
                                 "pass_marks": 2, "is_published": False})
    check("saving exam settings works", status == 200, f"{status} {saved}")

    question_body = {
        "question_text": "2 + 2 = ?",
        "question_type": "single_choice",
        "marks": 2,
        "negative_marks": 0,
        "options": [
            {"option_text": "4", "is_correct": True},
            {"option_text": "5", "is_correct": False},
        ],
    }
    status, added, _ = api("POST", f"/exams/{exam_id}/questions", token=teacher_token, body=question_body)
    check("the builder can add a question", status == 201, f"{status} {added}")
    question = (added or {}).get("question", {})
    check("added question echoes the option shapes the editor renders",
          not missing(question, ["id", "question_text", "question_type", "marks", "negative_marks", "options"])
          and not missing((question.get("options") or [{}])[0], ["id", "option_text", "is_correct"]),
          str(question)[:200])

    options = (question.get("options") or [])
    correct_id = next((o["id"] for o in options if o.get("is_correct")), None)
    check("the correct option is exposed to the owning teacher", correct_id is not None, str(options))

    status, publish, _ = api("PUT", f"/exams/{exam_id}", token=teacher_token, body={"is_published": True})
    check("publishing the exam works", status == 200 and publish["exam"]["is_published"] is True, str(status))

    print("\n[D] Student: My exams -> taking the exam -> result -> progress")
    status, student_list, _ = api("GET", "/exams", token=student_token)
    mine = [e for e in (student_list or {}).get("exams", []) if e["id"] == exam_id]
    check("the published exam appears in My exams", status == 200 and len(mine) == 1, str(student_list)[:200])
    if mine:
        card = mine[0]
        check("exam card has the fields the page renders",
              not missing(card, ["id", "title", "description", "subject", "duration_minutes",
                                 "total_marks", "pass_marks", "end_time", "attempt"]),
              str(missing(card, ["id", "title", "description", "subject", "duration_minutes",
                                 "total_marks", "pass_marks", "end_time", "attempt"])))
        check("a fresh exam shows no attempt yet", card["attempt"] is None, str(card["attempt"]))

    status, started, _ = api("POST", f"/exams/{exam_id}/start", token=student_token)
    attempt_id = ((started or {}).get("attempt") or {}).get("id")
    check("Start exam opens an attempt", status == 201 and attempt_id, f"{status} {started}")
    check("the taking page gets questions + answers + time",
          not missing(started, ["attempt", "exam", "questions", "answers", "time"]),
          str(missing(started, ["attempt", "exam", "questions", "answers", "time"])))
    check("the countdown value is present",
          isinstance(((started or {}).get("time") or {}).get("remaining_seconds"), int),
          str(((started or {}).get("time") or {})))
    check("the answer key is NOT in the student payload", "is_correct" not in json.dumps(started), "leak!")

    if attempt_id:
        question_payload = (started or {}).get("questions", [{}])[0]
        check("question payload matches what the page maps over",
              not missing(question_payload, ["id", "question_text", "question_type", "marks", "options"])
              and not missing((question_payload.get("options") or [{}])[0], ["id", "option_text"]),
              str(question_payload)[:200])

        status, saved_answer, _ = api("PUT", f"/attempts/{attempt_id}/answer", token=student_token,
                                      body={"question_id": question_payload["id"],
                                            "selected_option_ids": [correct_id]})
        check("autosave accepts a click", status == 200, f"{status} {saved_answer}")

        status, resumed, _ = api("GET", f"/attempts/{attempt_id}", token=student_token)
        check("resume returns the saved answer (answers keyed by question id)",
              str(question_payload["id"]) in (resumed or {}).get("answers", {}), str((resumed or {}).get("answers")))

        status, submitted, _ = api("POST", f"/attempts/{attempt_id}/submit", token=student_token)
        check("Submit exam grades it", status == 200, f"{status} {submitted}")

        status, result, _ = api("GET", f"/attempts/{attempt_id}/result", token=student_token)
        check("the result page can render",
              status == 200
              and not missing(result, ["attempt", "exam", "result", "review_available"])
              and not missing(result.get("result", {}), ["score", "percentage", "passed", "status"])
              and not missing(result.get("exam", {}), ["title", "subject", "total_marks", "pass_marks"]),
              json.dumps(result)[:200])
        check("the score is correct (2/2)", (result or {}).get("result", {}).get("score") == 2,
              str((result or {}).get("result")))
        check("review is withheld while the window is open",
              (result or {}).get("review_available") is False
              and "questions" not in (result or {}), str((result or {}).get("review_available")))

        status, mine_after, _ = api("GET", "/exams", token=student_token)
        card = next((e for e in (mine_after or {}).get("exams", []) if e["id"] == exam_id), {})
        check("My exams now shows the attempt as completed",
              (card.get("attempt") or {}).get("status") == "submitted", str(card.get("attempt")))

        status, progress, _ = api("GET", f"/reports/student/{student_user['id']}", token=student_token)
        check("My progress loads",
              status == 200
              and not missing(progress, ["student", "summary", "history", "trend"])
              and not missing(progress.get("summary", {}),
                              ["exams_taken", "average_percentage", "best_percentage", "pass_rate"]),
              json.dumps(progress)[:200])
        summary = (progress or {}).get("summary", {})
        check("the trend has one point per graded attempt",
              len((progress or {}).get("trend", [])) == summary.get("exams_taken")
              and len((progress or {}).get("history", [])) == summary.get("exams_taken"),
              f"trend={len((progress or {}).get('trend', []))} history={len((progress or {}).get('history', []))} summary={summary}")
        if (progress or {}).get("history"):
            check("history rows match the table columns",
                  not missing(progress["history"][0],
                              ["attempt_id", "exam_title", "score", "total_marks", "percentage",
                               "passed", "submitted_at"]),
                  str(progress["history"][0]))
        status, csv_text, csv_headers = http("GET", f"/api/reports/student/{student_user['id']}?format=csv",
                                             token=student_token)
        check("Export CSV downloads a file",
              status == 200 and "text/csv" in header(csv_headers, "Content-Type")
              and "attachment" in header(csv_headers, "Content-Disposition"),
              f"{status} {header(csv_headers, 'Content-Type')}")

    print("\n[E] Teacher report page (charts, difficulty, leaderboard)")
    status, report, _ = api("GET", f"/reports/exam/{exam_id}", token=teacher_token)
    check("exam report loads",
          status == 200
          and not missing(report, ["exam", "summary", "distribution", "questions"])
          and not missing(report.get("summary", {}),
                          ["attempt_count", "average_percentage", "highest_percentage",
                           "lowest_percentage", "median_percentage", "pass_rate"]),
          json.dumps(report)[:200])
    check("distribution has 5 bands for the bar chart",
          len((report or {}).get("distribution", [])) == 5, str((report or {}).get("distribution")))
    if (report or {}).get("questions"):
        row = report["questions"][0]
        check("difficulty row has what the table renders",
              not missing(row, ["question_id", "question_text", "question_type", "marks",
                                "graded_count", "correct_count", "percent_correct"]),
              str(row))
    status, board, _ = api("GET", f"/reports/leaderboard/{exam_id}", token=teacher_token)
    check("leaderboard loads", status == 200 and "entries" in (board or {}), json.dumps(board)[:160])
    if (board or {}).get("entries"):
        entry = board["entries"][0]
        check("leaderboard row matches the table columns",
              not missing(entry, ["rank", "student_id", "student_name", "score", "percentage",
                                  "passed", "submitted_at"]),
              str(entry))
    status, student_report, _ = api("GET", f"/reports/student/{student_user['id']}", token=teacher_token)
    check("the teacher can open a student report page", status == 200, f"{status} {student_report}")

    print("\n[F] Role guards behave like the UI expects")
    status, _, _ = api("GET", f"/reports/exam/{exam_id}", token=student_token)
    check("student hitting a teacher page gets 403 (not a redirect loop)", status == 403, str(status))
    status, _, _ = api("GET", f"/exams/{exam_id}", token=admin_token)
    check("admin can open any exam in the builder", status == 200, str(status))
    status, _, _ = api("GET", "/attempts/999999", token=teacher_token)
    check("unknown attempt is a clean 404 for the result page", status in (403, 404), str(status))

    print("\n[G] Cleanup: hide the smoke exam again")
    status, hidden, _ = api("PUT", f"/exams/{exam_id}", token=teacher_token, body={"is_published": False})
    check("smoke exam unpublished", status == 200 and hidden["exam"]["is_published"] is False, str(status))
    if status != 200:
        print(f"    note: leave it to the teacher to delete exam {exam_id} manually")

print("\n" + "=" * 60)
print(f"Browser-session checks: {PASSED} passed, {FAILED} failed")
if FAILURES:
    print("Failures:")
    for failure in FAILURES:
        print(f"  - {failure}")
print("=" * 60)
sys.exit(1 if FAILED else 0)
