# Security report — Auspify TMS (Online Examination System)

**Date:** 2026‑11‑07 · **Scope:** the whole application as built in Steps 0–5
(Flask API + React SPA + SQLite) · **Method:** automated tests plus manual
attack attempts against the *running* server — every result below was produced
by executing the code, not by inspection.

| Evidence | Command | Result |
| --- | --- | --- |
| White‑box suite (149 tests) | `cd backend && .venv/bin/python -m pytest` | **149 passed, 0 failed** (`backend/tests/pytest_report.txt`) |
| Black‑box attack script (56 checks) | `cd backend && .venv/bin/python ../scripts/verify_step5.py` | **56 passed, 0 failed** |
| Functional regression | `scripts/verify_step0.sh` … `verify_step4.py`, `scripts/e2e_check.py` | 30 / 54 / 79 / 44 / 68 and 43 — all green |
| Browser session (all pages, over the UI origin) | `cd backend && .venv/bin/python ../scripts/ui_smoke.py` | **61 passed, 0 failed** |
| Frontend tests | `cd frontend && npx vitest run` | 29 passed (6 files) |
| Static analysis | `npx oxlint src`, `npm run build` | 0 warnings / build OK |

---

## 1. Test inventory

| Module | Tests | Focus |
| --- | --- | --- |
| `tests/test_auth_security.py` | 25 | brute force, lockout, token forgery/expiry/revocation, password policy, mass assignment, enumeration, secrets in responses |
| `tests/test_authorization.py` | 23 | vertical (role) and horizontal (ownership) access control, anonymous access |
| `tests/test_injection.py` | 41 | SQL injection (login, register, path/query/body), XSS payload round‑trips, error‑page format, frontend `innerHTML` audit |
| `tests/test_exam_integrity.py` | 17 | answer‑key leakage, server‑side timer, replay/double submit, retakes, post‑submission edits, review gating |
| `tests/test_validation.py` | 27 | malformed JSON, wrong types, out‑of‑range values, oversized bodies, absurd/negative ids, method override |
| `tests/test_config_and_headers.py` | 16 | secrets in repo, `.env` git‑ignored, CORS allow‑list, security headers, debug off, production guards, internals in errors |

Each test runs against a **throw‑away SQLite database** (`tests/conftest.py`),
so the suite is safe to run against a machine with real data.

---

## 2. Control‑by‑control results

### 2.1 Authentication

| Control | Expected | Verified by |
| --- | --- | --- |
| Passwords stored as bcrypt hashes | `$2b$…`, never plaintext | `test_passwords_are_stored_as_bcrypt`, live check "no bcrypt markers" |
| Password policy ≥ 8 chars incl. letter + digit | weak inputs → 400 | `test_weak_passwords_are_rejected` (5 payloads) |
| Single sign‑in message for bad credentials | unknown email ≡ wrong password | `test_unknown_email_and_wrong_password_are_indistinguishable` |
| Disabled accounts behave like bad credentials | same 401 message | `test_disabled_account_matches_the_generic_message` |
| No user enumeration on registration | duplicate email → generic 409 | `test_duplicate_email_is_rejected`, `test_register_does_not_reveal_the_existing_role` |
| Registration cannot self‑assign a role | forced `student` | `test_mass_assignment_of_role_is_ignored` |
| Brute force: lock after 5 failures for 15 min | 5 × 401 then locked | `TestBruteForce` (3 tests) + live checks [5] |
| Brute force: per‑IP rate limit on `/api/auth/login` | 429 + `Retry-After` | `test_rate_limit_blocks_repeated_logins`, live check [12] |
| Successful login clears the failure counter | counter back to 0 | `test_successful_login_resets_the_counter` |

### 2.2 Session / token handling

| Control | Expected | Verified by |
| --- | --- | --- |
| Short‑lived JWT (30 min, HS256, configurable) | expired token → 401 | `test_expired_token_is_rejected` |
| Signature cannot be forged | tampered / `alg=none` / re‑signed with guessed key → 401 | `test_tampered_signature_is_rejected`, `test_unsigned_alg_none_token_is_rejected`, live checks [3] |
| Role claim is not trusted from the token | role re‑read from the database | `test_role_claim_cannot_be_trusted_over_the_database` |
| Logout revokes the token (`jti` blocklist) | replayed token → 401 | `test_token_is_rejected_after_logout` |
| Missing/garbage `Authorization` handled | 401, never 500 | `test_missing_and_malformed_authorization_headers` |

### 2.3 Authorization

| Control | Expected | Verified by |
| --- | --- | --- |
| Students cannot reach staff endpoints | 403 | `test_student_is_forbidden_on_staff_endpoints` (4 routes), live checks [4] |
| Only admins create accounts | teacher/student → 403 | `test_teacher_cannot_create_accounts` |
| Teachers are confined to their own exams | 403 on another teacher's exam | `test_teacher_cannot_touch_another_teachers_exam` |
| Students cannot read another student's attempt/result/report | 403/404 | `TestHorizontalAccess` (7 tests), live checks [6] |
| Teachers cannot read arbitrary attempts | 403/404 | `test_teacher_cannot_read_random_attempts` |
| Anonymous access | 401 on every protected route | `test_anonymous_access_is_401`, `test_mutating_endpoints_reject_anonymous` |
| Own attempt / own result still works | 200 | `test_student_can_read_their_own_attempt_and_result` |

### 2.4 Injection & cross‑site scripting

| Control | Expected | Verified by |
| --- | --- | --- |
| All SQL parameterised (`?` placeholders) | injection payloads are inert | `TestSqlInjection` (7 tests), live checks [2] |
| Payloads stored as data, survive a DB read intact | text round‑trips unchanged | `test_sql_strings_are_stored_as_data_not_executed` |
| No HTML reflection | API is JSON‑only, `<script>` never rendered | `test_reflected_payloads_are_not_echoed_as_html` |
| Errors are JSON, not HTML | every error body is `application/json` | `test_error_pages_are_json_not_html` |
| Frontend never uses `dangerouslySetInnerHTML` | React escapes all user text | `test_frontend_never_uses_dangerously_set_inner_html` |
| Strict CSP on the API | `default-src 'none'` | live checks [7] |

### 2.5 Exam integrity

| Control | Expected | Verified by |
| --- | --- | --- |
| Answer key never leaves the server before grading | no `is_correct` in list/detail/start/answer/submit payloads | `TestAnswerLeakage` (5 tests) |
| Timer is server‑side | old `started_at` → answers rejected, attempt expired | `test_answers_after_the_deadline_are_rejected` |
| Expiry still grades what was saved | auto‑submit + score | `test_expired_attempt_is_graded_from_saved_answers` |
| One attempt per student unless retakes are allowed | 409 / same attempt / new attempt | `TestAttemptReplay` (4 tests incl. 5 concurrent starts → 1 row) |
| Answers frozen after submission | 409 | `test_answers_cannot_be_changed_after_submission` |
| Re‑submitting cannot change the score | identical score after data tampering | `test_double_submit_cannot_change_the_score` |
| Published exam with attempts is immutable | 409 on edit/delete | `test_published_exam_with_attempts_is_frozen` |
| Correct answers revealed only after the window closes | `review_available` false → true | `test_review_is_hidden_until_the_window_closes` |

### 2.6 Input validation / robustness

| Control | Expected | Verified by |
| --- | --- | --- |
| Broken JSON, arrays, `null`, wrong content type | clean 400/415 | `TestMalformedJson` (4 tests) |
| Wrong field types, missing fields | 400 with `error.fields` | `TestFieldValidation` (2 tests, 8 payloads) |
| Out‑of‑range and oversized values | 400 | `test_oversized_and_out_of_range_values_are_400` |
| > 2 MB request body | 413 | `test_huge_body_is_rejected_by_max_content_length` |
| Question/option rules (2–6 options, 1 correct, marks > 0, negative ≤ marks) | 400 | `test_question_validation_errors` (8 payloads) |
| Answer payloads (`question_id`, option ids, 1–6 ids) | 400/404 | `test_answer_validation` (6 payloads) |
| Absurd and negative ids | 404/405, never 500 | `test_absurd_numeric_ids_are_404_not_500`, `test_negative_ids_are_404` |
| Fuzzed live endpoints | no 5xx, no traceback, no paths | live checks [9] |

### 2.7 Configuration, transport & data exposure

| Control | Expected | Verified by |
| --- | --- | --- |
| Secrets only in `backend/.env`, which is git‑ignored | no key in any tracked file | `test_no_secret_values_in_any_tracked_file`, `test_env_file_is_git_ignored` |
| `.env.example` holds placeholders only | `replace-me`, no 64‑hex keys | `test_env_example_has_no_real_secrets` |
| Missing secret → refuse to start | `RuntimeError` | `test_production_profile_requires_secrets` |
| Production profile refuses debug / testing | startup error | `test_production_profile_refuses_debug`, `test_production_profile_refuses_testing_mode` |
| Debug mode off | `app.debug is False` | `test_debug_is_off`, live checks [11] |
| Security headers on every API response | nosniff, DENY, CSP, no‑store, no‑referrer | `TestHeadersAndCors`, live checks [7] |
| CORS allow‑list only, no wildcard, no credentials | foreign origin gets no grant | `test_unknown_origin_is_not_allowed`, `test_wildcard_origin_is_never_returned`, live checks [8] |
| Health/index endpoints expose no configuration | no keys, paths or version banners | `test_health_endpoint_exposes_no_configuration`, live checks [10] |
| No framework banner | `Server: auspify-tms` | `test_server_banner_does_not_advertise_the_stack`, live checks [7] |
| Errors leak no internals | no traceback, no absolute path, no `sqlite3` | `test_errors_do_not_leak_internals` |

---

## 3. Findings and fixes

Every finding below was discovered **by running the checks in this step**, then
fixed, then re‑tested. The suite that proves each fix is listed.

| ID | Severity | Finding | Fix | Re‑verified by |
| --- | --- | --- | --- | --- |
| **F1** | Medium | `GET /api/exams/999999999999999999999` raised `OverflowError: Python int too large to convert to SQLite INTEGER` → HTTP 500 and a logged traceback. Any integer URL longer than 64 bits reached the driver. | Added a bounded URL converter (`app/__init__.py::_register_url_converters`) that caps every `<int:…>` variable at `0 … 2^63-1`, so such ids 404 before touching the database. | `test_absurd_numeric_ids_are_404_not_500`, `test_negative_ids_are_404`, live checks [9] |
| **F2** | Low | Responses advertised `Server: Werkzeug/3.1.9 Python/3.11.2` (and duplicated the header when overridden in `after_request`). | `run.py` serves through `ApiRequestHandler`, a `WSGIRequestHandler` subclass returning `auspify-tms`. Deployment note: configure the same in the production WSGI server. | `test_server_banner_does_not_advertise_the_stack`, live checks [7] (`Server: auspify-tms`) |
| **F3** | Medium | The development profile shipped `APP_DEBUG=1`, and the running server logged `Debug mode: on` — with the debugger reachable from the preview host. | `APP_DEBUG=0` in `.env` and `.env.example`; `create_app` now refuses `APP_ENV=production` combined with `APP_DEBUG=1` or `TESTING=True`. | `test_debug_is_off`, `test_production_profile_refuses_debug`, live checks [11] |
| **F4** | Low | Report endpoints checked *existence* before *role*: a student probing `/api/reports/exam/<id>` got 404 for unknown ids but 403 for real ones, leaking which exam ids exist. | Students are now rejected before the database lookup in `exam_report_endpoint`; `leaderboard_endpoint` answers 403 for students whether or not the exam exists. | `test_student_is_forbidden_on_staff_endpoints`, live checks [4] |
| **F5** | Low (accepted) | After 5 failures an *existing* account answers 429 (locked) while an unknown email always answers 401 — a weak enumeration signal once an attacker is willing to burn 5 attempts per address. | Accepted and documented: the per‑IP login rate limit (10/min) is the primary control; the 429 message is generic (`Too many failed attempts`) and never confirms that a password was correct. Levelling this fully would require failure counters for non‑existent addresses (see §5). | live checks [5] |

Also fixed during this step (functional, not security): the Step 4 CSV export
raised `KeyError: 'answered_count'` → HTTP 500 for any exam with graded
attempts; the field is now `graded_count` and the CSV header reads
"Graded attempts" (`scripts/verify_step4.py`, 68/68).

---

## 4. Accepted residual risks

1. **Account lockout is observable** (F5) — by design, so that a locked user is
   told to wait instead of retrying forever. Mitigated by IP rate limiting.
2. **Tokens are stored in `localStorage`** on the client (needed because the API
   is a separate origin). A successful XSS would therefore be able to read them;
   the app ships no `dangerouslySetInnerHTML`, React escapes all interpolated
   text, and the API sends a strict CSP. Moving to httpOnly cookies + CSRF
   tokens is the recommended hardening (see §5).
3. **No CSRF tokens** — not exploitable today, because the API authenticates
   with an `Authorization: Bearer` header rather than cookies, and CORS grants
   no credentials. This changes the day cookies are introduced.
4. **No HTTPS in development** — the dev server speaks plain HTTP on
   `localhost`. Production must terminate TLS (HSTS then becomes meaningful).
5. **SQLite** is single‑writer; it is a fine fit for a course project's scale but
   not for concurrent high load, and it has no row‑level privileges (all
   authorization is enforced in the app layer, which is why §2.3 matters).
6. **No antivirus/content scanning** — the API accepts only JSON (2 MB cap) and
   stores no uploads, so the attack surface is limited to text.

---

## 5. Recommended next steps (security roadmap)

| Priority | Improvement | Why |
| --- | --- | --- |
| High | httpOnly + Secure + SameSite cookies with double‑submit CSRF tokens | Removes the XSS‑to‑token‑theft path entirely |
| High | HTTPS/TLS termination, HSTS, `Secure` cookies | Protects credentials and tokens in transit |
| High | Per‑email failure counters that also apply to unknown addresses | Closes the F5 enumeration signal |
| Medium | Refresh tokens with rotation + reuse detection | Shorter access tokens, no repeated logins |
| Medium | Email verification and password reset (single‑use, expiring tokens) | Prevents mistyped/foreign email registration, gives users a recovery path |
| Medium | TOTP 2FA for admin/teacher accounts | Staff accounts can read the whole gradebook |
| Medium | Audit log (who changed what, when) + alerting on repeated 401/403 | Detection, not just prevention |
| Medium | `pip-audit` / `npm audit` in CI, dependency pinning review | Known‑CVE hygiene. `npm audit` is clean of high‑severity advisories after the react‑router 6.30.x patch; the two remaining moderate ones are SSR‑hydration only and need the react‑router v7 major |
| Low | Question and option randomisation, one‑question‑per‑page, focus‑loss tracking | Reduces collusion during an exam |
| Low | Essay questions with manual grading (needs a rubric + review workflow) | Extends the exam model |
| Low | Docker + Postgres + `waitress`/gunicorn, secrets from a vault | Production deployment story |
| Low | `pytest-cov` with a coverage gate in CI | Keeps the suite honest as the app grows |

---

## 6. Deployment checklist (production)

1. `APP_ENV=production`, `APP_DEBUG=0`, `TESTING` off — the app refuses to start otherwise.
2. Generate fresh `SECRET_KEY` and `JWT_SECRET_KEY` (`secrets.token_hex(32)`); never reuse the dev values.
3. Serve behind HTTPS with `waitress`/gunicorn; set the WSGI server's own `Server` banner to `auspify-tms`.
4. Set `CORS_ORIGINS` to the exact production frontend origin (no wildcard, no `localhost`).
5. Move rate‑limit storage from `memory://` to Redis so limits survive restarts and apply across workers.
6. Keep `DATABASE_PATH` outside the web root and back it up; run with a dedicated, unprivileged OS user.
7. Turn `ALLOW_PREVIEW_EMBEDDING` **off** so nothing can frame the app.
8. Run `cd backend && .venv/bin/python -m pytest` and `scripts/verify_step5.py` after every deployment.

---

## 7. Reproducing this report

```bash
# 1. White-box suite (fresh temp DB per test; ~6 minutes, bcrypt is deliberately slow)
cd backend && .venv/bin/python -m pytest            # -> tests/pytest_report.txt

# 2. Black-box attacks against the running API (Flask on :5000)
cd backend && .venv/bin/python ../scripts/verify_step5.py

# 3. Functional regression across all steps
./scripts/verify_step0.sh            # 30 checks  (backend + frontend running)
backend/.venv/bin/python scripts/verify_step1.py   # 54
backend/.venv/bin/python scripts/verify_step2.py   # 79
backend/.venv/bin/python scripts/verify_step3.py   # 44
backend/.venv/bin/python scripts/verify_step4.py   # 68
cd backend && .venv/bin/python ../scripts/e2e_check.py  # 43 live

# 4. Frontend
cd frontend && npx vitest run && npx oxlint src && npm run build
```

Note: `verify_step5.py` intentionally trips the login rate limiter as its last
check. If it runs within a minute of other login‑heavy scripts, wait ~60 s or
the first few login attempts may answer 429.
