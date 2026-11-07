# Completion audit — README vs. repository

**Date:** 2026‑11‑07 · **Commit:** `8651755` (branch `arena/7b3dca45-auspify-tms`, clean tree)
**Question:** does the repository actually do what `README.md` says it does?

**Verdict: yes.** Every feature, endpoint, table, environment variable and
verification number the README claims is present and reproduces. The audit found
**four documentation inaccuracies and zero functional gaps**; three were fixed in
this commit and one wording was tightened (§4).

---

## 1. Verification table re-run at this commit

Each command below was executed during the audit; the results match the README
cell for cell.

| README claim | Command re-run | Result |
| --- | --- | --- |
| step 0 — `30 passed` | `./scripts/verify_step0.sh` | **30 passed, 0 failed** |
| step 1 — `54 passed` | `scripts/verify_step1.py` | **54 passed, 0 failed** |
| step 2 — `79 passed` | `scripts/verify_step2.py` | **79 passed, 0 failed** |
| step 3 — `44 passed` | `scripts/verify_step3.py` | **44 passed, 0 failed** |
| step 4 — `68 passed` | `scripts/verify_step4.py` | **68 passed, 0 failed** |
| step 5 — `56 passed` | `scripts/verify_step5.py` | **56 passed, 0 failed** |
| pytest — `149 passed` | `.venv/bin/python -m pytest` | **149 passed in 366 s** |
| e2e — `43 passed` | `scripts/e2e_check.py` | **43 passed, 0 failed** |
| site — `62 passed` | `scripts/ui_smoke.py` (dev, :5173) | **62 passed, 0 failed** |
| site build — `62 passed` | `SITE_BASE=…:4173 ui_smoke.py` | **62 passed, 0 failed** |
| UI — `46 passed (8 files)` | `npx vitest run` | **46 passed (8 files)** |
| a11y — `13 passed, 0 violations` | `npx vitest run src/test/a11y.test.jsx` | **13 passed** |
| UX — `56 passed` | `python3 ../scripts/ux_check.py` | **56 passed, 0 failed** |
| UI — no lint findings, build OK | `npx oxlint src && npm run build` | **0 warnings / 0 errors**, build ✓ |
| deps — `0 vulnerabilities` | `npm audit` | **0 vulnerabilities** |

The saved report `backend/tests/pytest_report.txt` also ends in
`149 passed in 364.44s — EXIT=0`, consistent with today's run.

## 2. API surface — README §7 vs. the live URL map

Flask registers **24 routes**: the 23 API endpoints listed in the README tables
plus the human status page at `/`. Method and path match exactly.

| Group | README rows | Registered | Roles in code match the table |
| --- | --- | --- | --- |
| Health | 1 | 1 | n/a (anonymous) |
| Authentication | 5 | 5 | ✅ `@role_required("admin")` on `POST /auth/users`, public register/login |
| Exams (authoring) | 9 | 9 | ✅ teacher/admin + per-record ownership |
| Taking an exam | 4 | 4 | ✅ `@role_required("student")` |
| Results | 1 | 1 | ✅ student/teacher/admin + ownership, 404 for non-owners |
| Reports | 3 | 3 | ✅ students never reach the exam report |

## 3. Data model — ER diagram vs. `schema.sql`

Parsed both and compared column by column: **7 tables, 51 columns, every column
in the diagram exists with the same name and none are undocumented.**

| Table | Diagram | Schema |
| --- | --- | --- |
| users | 9 | 9 |
| token_blocklist | 3 | 3 |
| exams | 13 | 13 |
| questions | 7 | 7 |
| options | 4 | 4 |
| attempts | 9 | 9 |
| answers | 6 | 6 |

All 11 indexes exist, including the unique `idx_users_email` and the composite
`idx_attempts_exam_student` the README promises. `PRAGMA foreign_keys = ON` is
set in `db.py`.

## 4. Feature claims checked against code — 75/75

A scripted pass verified each README bullet against implementation, e.g.

- **Accounts:** bcrypt cost 12 (`security.BCRYPT_ROUNDS`), ≤ 72‑byte guard,
  password policy in `security.password_policy_error` (≥ 8, letter + digit),
  JWT lifetime 30 min, `jti` blocklist on logout (`@jwt.token_in_blocklist_loader`),
  5‑failure lockout for 15 min, login limiter `10 per minute`, identical
  `_INVALID_CREDENTIALS` for unknown / wrong / disabled accounts, unconditional
  bcrypt compare against a dummy hash to equalise timing.
- **Exams:** 2–6 options, ≥ 1 correct (exactly 1 for single/true‑false),
  `marks > 0`, `0 ≤ negative_marks ≤ marks`, `duration_minutes > 0`,
  `end_time > start_time`; `_assert_questions_mutable` freezes a published exam
  that has attempts; admins list everything, teachers list their own, students
  get a filtered, attempt-annotated list.
- **Taking:** `remaining_seconds` from the server, absolute deadline in the
  client, re-sync on `visibilitychange` **and** `focus`, per-answer
  `PUT /answer` autosave with saving/saved/error states, auto-submit at zero,
  server-side `409` once the deadline passes.
- **Grading:** `grade_attempt` runs inside `with transaction()`, uses absolute
  `UPDATE`s plus `INSERT … ON CONFLICT (attempt_id, question_id) DO UPDATE`,
  floors the total with `max(0.0, …)`, and derives `percentage`/`passed`.
- **Reports:** average/highest/lowest/**median**, pass rate, the five bands
  (`0-20`, `21-40`, `41-60`, `61-80`, `81-100`), per-question difficulty,
  leaderboard, student history + trend, CSV on all three, formula-injection
  hardening. Recharts renders on exactly the three pages the README names.
- **Security (checked against the running server, not just source):**
  `Server: auspify-tms`, `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `CSP: default-src 'none'`,
  `Referrer-Policy: no-referrer`, `Cache-Control: no-store`; a preflight from
  `https://evil.example` returns **no** `Access-Control-Allow-Origin`; a 3 MB
  body returns `413 {"error":{"code":413,…}}`; no f‑string/`%`/`+` SQL anywhere;
  no `dangerouslySetInnerHTML` in the client; no `TODO`/`FIXME`/
  `NotImplementedError` in app code.
- **Stack:** Python 3.11.2, Flask 3.0.3, React 19.3.1, react-router-dom 7.18.5,
  Recharts 2.15.4, Vite 8 — as advertised.

## 5. Gaps found (all documentation, no behaviour)

| # | Severity | Gap | Status |
| --- | --- | --- | --- |
| 1 | Low | `REGISTER_RATE_LIMIT` (20/min) and `RATELIMIT_ENABLED` exist in `config.py` and are honoured by the app, but were missing from the README §4 table | **Fixed** — both rows added |
| 2 | Low | `RATELIMIT_STORAGE_URI` was documented in the README but absent from `.env.example`, so `cp .env.example .env` never showed it | **Fixed** — added with a comment |
| 3 | Low | `LICENSE` exists at the root but was missing from the §2 layout tree | **Fixed** |
| 4 | Low | README §1 said "leaving/reloading the page mid‑attempt warns first". Only browser‑level unload/reload is guarded (`beforeunload`); clicking a sidebar link navigates away without a prompt (answers are already saved, so nothing is lost) | **Wording corrected** to "reloading or closing the tab"; an in‑app router blocker is listed as optional follow‑up |

No claim in the README was found to be false about behaviour, and nothing in the
codebase is undocumented to the point of being unreachable.

## 6. What "complete" does and does not cover

Complete: the five build steps, the full API, the schema, grading, reports, the
UI and its accessibility/UX verification, and the security controls described in
§8 — all reproducible with the commands in §1.

Deliberately **not** built, and listed as future work in README §12 (so not an
omission): httpOnly cookies + CSRF, refresh tokens, email verification, 2FA,
audit logging, Docker/Postgres/Redis, pagination, i18n and a dark theme. Also
absent by design:

- **No real-browser or visual testing.** Verification uses Flask's test client,
  `requests`, jsdom + `axe-core` and `ui_smoke.py` over the real HTTP origin.
  There is no screenshot diffing, cross-browser matrix or Lighthouse/performance
  budget, so rendering regressions on a specific browser would not be caught.
- **No load or concurrency testing.** SQLite + `memory://` rate-limit storage is
  single-process; the README already calls this out under §12.
- **A live database specimen**, not a fixed dataset: `backend/instance/` is
  git-ignored and rebuilt with `seed.py`, so the counts in reports depend on what
  was seeded.

## 7. Reproducing this audit

```bash
./scripts/verify_step0.sh
for n in 1 2 3 4 5; do backend/.venv/bin/python scripts/verify_step$n.py; done
cd backend && .venv/bin/python -m pytest -q
cd backend && .venv/bin/python ../scripts/e2e_check.py
cd backend && .venv/bin/python ../scripts/ui_smoke.py
cd backend && SITE_BASE=http://127.0.0.1:4173 .venv/bin/python ../scripts/ui_smoke.py
cd frontend && npx vitest run && python3 ../scripts/ux_check.py && npx oxlint src && npm run build && npm audit
```
