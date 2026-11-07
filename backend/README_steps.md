# Build log

- Step 0: setup (health endpoint, CORS, security headers, Vite proxy) — verifies with scripts/verify_step0.sh
- Step 1: authentication (bcrypt, JWT + logout blocklist, lockout, rate limiting, RBAC) — scripts/verify_step1.py + frontend vitest
- Step 2: exams (teacher/admin CRUD for exams, questions and options; validation rules; student list/start/answer/submit with a server-side timer and window enforcement; React builder, list and take-exam views) — scripts/verify_step2.py
  - Schema: `exams`, `questions`, `options`, `attempts`, `answers` (+ indexes on exam_id, student_id, attempt_id).
  - Question rules enforced in `app/schemas.py`: 2–6 options, ≥1 correct, exactly 1 for `single_choice`/`true_false`, `marks > 0`, `0 <= negative_marks <= marks`, `duration_minutes > 0`, `end_time > start_time`.
  - Integrity: a published exam with attempts becomes read-only (409 on edit/delete); one attempt per student unless `allow_retakes`; `start` is idempotent inside a transaction.
  - Timer: `remaining_seconds` is computed from the stored `started_at`; late answers are rejected and converted to a graded `expired` attempt.
- Step 3: grading + results (server-side, transactional, idempotent) — scripts/verify_step3.py
  - `app/grading.py`: single/true-false exact match, multiple-choice all-or-nothing, unanswered = 0 and never penalised, wrong answers deduct `negative_marks`, total floored at 0, `percentage = score / total_marks * 100`, pass when `score >= pass_marks`.
  - Runs on submit *and* on auto-expiry; uses `INSERT … ON CONFLICT DO UPDATE` with absolute values so re-running cannot double-count.
  - `GET /api/attempts/<id>/result` returns own results only (404 otherwise), 409 while in progress, and hides the per-question review until the exam window closes.
- Step 4: reports + analytics + CSV export — scripts/verify_step4.py
  - Endpoints: `GET /api/reports/exam/<id>`, `GET /api/reports/student/<id>`, `GET /api/reports/leaderboard/<id>`; each accepts `?format=csv`.
  - Exam report: average/high/low/median percentage, pass rate, 5-band distribution (0–20 % … 81–100 %), per-question difficulty (`graded_count`, `correct_count`, `percent_correct`).
  - Student report: history plus a per-exam trend series. Leaderboard: ranked attempts for one exam.
  - Access: admin unrestricted; teachers only their own exams (403 otherwise); students only their own student report (404 otherwise), never the exam report, and a leaderboard only for an exam they sat once its window has closed.
  - CSV hardening: `_csv_safe()` prefixes `= + - @` with `'` so exported cells cannot become spreadsheet formulas.
  - UI: `ExamReportPage`, `StudentReportPage`, `ProgressPage` (Recharts bar/line charts, difficulty table, leaderboard), CSV buttons that fetch with the bearer token and download a blob.
- Step 5: security verification pass — pytest suite (149 tests) + live attack script (56 checks)
  - `backend/tests/`: `conftest.py` (temp DB per test, env secrets, client + role fixtures, low-limit client), `helpers.py` (account seeding, exam/question/attempt builders), `test_auth_security.py` (25), `test_authorization.py` (23), `test_injection.py` (41), `test_exam_integrity.py` (17), `test_validation.py` (27), `test_config_and_headers.py` (16).
  - `scripts/verify_step5.py`: black-box attacks against the running API — enumeration, SQL injection, token tampering, vertical/horizontal escalation, lockout, headers, CORS, fuzzing, secrets, debug mode, rate limiting.
  - Fixed (details in `SECURITY_REPORT.md`): bounded `<int:…>` URL converter so 64-bit-overflow ids 404 instead of 500; `Server: auspify-tms` instead of the Werkzeug/Python banner; `APP_DEBUG=0` plus a startup guard that refuses production with debug/testing on; report endpoints deny students before disclosing whether an exam exists; `requirements.txt` completed with every runtime and test dependency.
  - Results: pytest **149/149**, live checks **56/56**, `verify_step0…4` and `e2e_check.py` re-run green, frontend vitest 18/18, oxlint 0/0, production build OK.

- Step 5 (site QA pass): debugged and exercised the running website
  - New `scripts/ui_smoke.py` (61 checks): loads the app shell and assets from the UI origin, asserts SPA deep-link fallbacks, then walks every page's real requests (register → teacher creates/publishes an exam → student starts/answers/submits → result → progress → exam report / leaderboard / student report / CSV) and checks the exact JSON fields each component renders.
  - New `frontend/src/test/{dashboard,exam-timer}.test.jsx` (10 tests): dashboard counters, graceful failure, 404/403 screens with client-side navigation, mm:ss countdown from the server value, `beforeunload` guard, and re-sync when the tab regains focus.
  - Bugs fixed: `FullPageMessage` used a raw `<a href>` (full page reload → lost session state, now a router `<Link>`); dashboards still advertised "arrives in Step 2/3/4" placeholder copy (now live counters and links); the exam countdown decremented a local number instead of an absolute deadline and never re-synced after a sleeping tab (now deadline-based + `visibilitychange`/`focus` re-sync); the README promised a leave-page warning that did not exist (now implemented); `vite.config.js` had no `preview` block, so `npm run preview` could not reach the API (now proxied on 4173); `api/health` still reported `0.1.0 (step 0)` (now `1.0.0`); harness fixes in `verify_step5.py` (429 retry that distinguishes the IP limiter from a real account lockout).
  - Verified: `ui_smoke.py` 61/61, vitest 28/28 (6 files), oxlint 0/0, `npm run build` OK, production preview (`vite preview` on :4173) serves the bundle + deep links + `/api` proxy, and step0 30 / step1 54 / step2 79 / step3 44 / step4 68 / e2e 43 / verify_step5 56 all still green.

- Step 5 (ops repair): resumed the production preview on port 4173
  - Inspected the running processes: Flask (:5000) and the Vite dev server (:5173) were healthy, but 4173 was an orphaned `vite preview` no longer tracked, and the Flask process was serving stale code (`/api/health` still reported `0.1.0 (step 0)` because `use_reloader=False`).
  - Fixed: killed the orphan, restarted Flask (`/api/health` → `1.0.0` on 5000, 5173 and 4173), rebuilt the bundle and started a tracked preview.
  - Root cause of the recurring 404s: the preview's document root was `frontend/dist`, and hosted sandboxes wipe folders named `dist`/`build`/`out` between snapshots. `vite.config.js` now takes `VITE_OUT_DIR` (default `dist`) and `package.json` gained `preview:build` / `preview:serve` (`--outDir preview-dist`), which is git-ignored and survives snapshots.
  - `scripts/ui_smoke.py` is now build-aware: it reads the entry `<script src>` from the shell, so the same 62 checks pass against the dev server (`/src/main.jsx`) and the built app (`/assets/index-*.js`), via `SITE_BASE`.
  - Verified: `SITE_BASE=http://127.0.0.1:4173` ui_smoke 62/62, dev ui_smoke 62/62, e2e 43/43, step0 30/30, preview shell/assets/deep-links/API all 200.
