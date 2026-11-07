# UX review — minimal UI

**Date:** 2026‑11‑07 · **Scope:** every screen of the React client · **Method:**
the minimal stylesheet was rebuilt around a token system, then audited with
automated tools (`axe-core` in jsdom, a WCAG contrast calculator, class-coverage
and design-discipline checks) and with behaviour tests for the states a browser
test cannot reach without one.

| Evidence | Command | Result |
| --- | --- | --- |
| Accessibility (axe) on 11 screens | `cd frontend && npx vitest run src/test/a11y.test.jsx` | **12 tests pass**, 0 violations at any severity |
| Static UX/a11y audit | `cd frontend && python3 ../scripts/ux_check.py` | **56 passed, 0 failed** |
| UI behaviour suite | `cd frontend && npx vitest run` | **45 passed (8 files)** |
| Live walk through every page | `cd backend && .venv/bin/python ../scripts/ui_smoke.py` | **67 / 67** (dev and production build) |
| Dependency health | `npm audit` | **0 vulnerabilities** (was 3 high) |

---

## 1. What "minimal" changed

The previous sheet had grown by accretion (878 lines, 13 ad‑hoc colours, four
box-shadows, sixteen font sizes, one duplicated block). The new one is a single
system where every value is a token you can change once.

| Property | Before | After |
| --- | --- | --- |
| Colours outside the token block | 13 | **0** |
| Colour roles | 13 flat values | **25 role tokens** (`--text`, `--muted`, `--accent`, `--danger-on-soft`, …) |
| `box-shadow` declarations | 4 | **1** (overlays only) |
| Border radii | 4 values | **2 tokens** + pill |
| Font sizes | 16 values | **8 steps** (`--text-xs` … `--text-display`) |
| Spacing | ad-hoc px | **6 steps** (`--space-1` … `--space-6`) |
| Duplicated / conflicting selectors | 1 | 0 |
| Classes used but never styled | 3 | **0** (84/84 covered) |

Design rules the system encodes:

- **Borders instead of shadows.** Cards, tables and inputs are separated by a
  1px line; the only shadow is on the modal, where depth carries meaning.
- **One accent colour.** Blue marks the primary action, active navigation and
  selection. Green/red appear only for pass/fail and the countdown.
- **Two weights of border.** `--border` (decorative, 1.3:1) for containers and
  `--border-strong` (3.27:1) for anything interactive, so fields are visible
  without decorating the whole page.
- **No colour-only signals.** Pass/fail, correct/wrong and timer warning all
  carry text ("passed", "correct answer", "Time left"), not just a hue.

---

## 2. Contrast (WCAG 2.1 AA)

Measured from the real token values by `scripts/ux_check.py`:

| Pair | Ratio | Requirement | |
| --- | --- | --- | --- |
| Body text on cards | 16.1 : 1 | 4.5 | PASS |
| Body text on page background | 15.3 : 1 | 4.5 | PASS |
| Secondary text on cards | 7.6 : 1 | 4.5 | PASS |
| Secondary text on tinted rows | 6.9 : 1 | 4.5 | PASS |
| Links / accent on cards | 6.7 : 1 | 4.5 | PASS |
| Active nav item (accent on tint) | 6.0 : 1 | 4.5 | PASS |
| Error text | 6.6 : 1 | 4.5 | PASS |
| Success text | 5.0 : 1 | 4.5 | PASS |
| Success alert text on tint | 7.6 : 1 | 4.5 | PASS |
| Error alert text on tint | 9.1 : 1 | 4.5 | PASS |
| White on primary button | 6.7 : 1 | 4.5 | PASS |
| White on danger button | 6.6 : 1 | 4.5 | PASS |
| Input / control borders | **3.27 : 1** | 3.0 | PASS (was 1.67 : 1 — see §4) |

---

## 3. Keyboard, touch and motion

| Check | State |
| --- | --- |
| Global `:focus-visible` ring (2px accent, 2px offset) on every interactive element | PASS |
| No `outline: none` anywhere | PASS |
| Buttons ≥ 40px, answer options ≥ 44px, nav links ≥ 36px | PASS |
| `@media (pointer: coarse)` raises buttons/nav to 44px on touch devices | PASS |
| `prefers-reduced-motion` disables transitions | PASS |
| Modal: focus moves in on open, Tab/Shift+Tab cycle inside, Escape closes, focus returns to the opener | PASS (5 behaviour tests) |
| Exam timer announces changes (`aria-live="polite"`) | PASS |
| Skip-to-content link | **not present** — see §6 |

---

## 4. Findings and fixes

Every item below was found by running the checks in this review.

| # | Severity | Finding | Fix |
| --- | --- | --- | --- |
| 1 | **High (a11y)** | The confirmation dialog claimed "focus stays inside" but had no focus trap: keyboard users could Tab into the page behind the overlay, and closing it dropped focus on `<body>`. | `Modal` now records the opener, focuses the dialog on open, wraps Tab/Shift+Tab inside it, and restores focus on close. Covered by 5 new tests. |
| 2 | **Medium (a11y)** | Input, select and button borders were `#c3c9d2` — **1.67 : 1** against white, below the 3 : 1 required for control boundaries (WCAG 1.4.11). | New `--border-strong: #868f9d` (**3.27 : 1**) for interactive borders; decorative card borders keep the light tone. |
| 3 | **Medium (security)** | `npm audit` reported 3 high-severity advisories in `react-router-dom` 6.x (open redirects via untrusted paths, SSR deserialisation). | Upgraded to **react-router-dom 7.18.5**; `npm audit` → 0 vulnerabilities, all 46 UI tests still pass. |
| 4 | Medium (consistency) | 13 colours were hardcoded outside the tokens (tint borders, alert text, hover rows), so states drifted and the palette had grown to 13 shades. | All state colours became role tokens; the audit now enforces **zero** ad-hoc colours. |
| 5 | Medium (hierarchy) | 16 different font sizes and 4 shadow/radius variants competed; nothing signalled what mattered. | 8-step type scale, 2 radii, 1 shadow, 6 spacing steps — all referenced by name. |
| 6 | Low (dead code) | Three classes were used in JSX but never styled (`app-shell`, `modal-body`, `neutral`), and `.pill`, `.ok`, `.bad`, `.pending` were styled but unused. | Dead rules removed; the three real ones styled. Audit now fails on any unstyled class. |
| 7 | Low (a11y) | A stray `#fff`/`#999` literal made the palette rule unverifiable. | Tokenised as `--on-accent` and `--print-line`. |

---

## 5. Screens audited

`/login`, student dashboard, student exam list, taking an exam,
result + review, student progress, teacher exam list, exam editor, exam report,
student report, and the 404 screen — each rendered with a mocked API and run
through axe against the **loaded** state (not the spinner), with a meta-test
that proves the audit still detects real violations (`image-alt`,
`button-name`).

UX states verified per page: loading (`Spinner`), error (`Alert` with the
server's message), empty ("No exams are open right now"), destructive
confirmation (delete exam, submit exam), inline field errors with
`aria-invalid`, and the 403/404 screens.

---

## 6. Remaining recommendations

| Priority | Recommendation | Why |
| --- | --- | --- |
| High | Skip-to-content link before the app bar | Keyboard users currently tab through navigation on every page |
| High | `aria-busy` on data-fetching regions, and announce "Loaded N exams" via a live region | Screen-reader users get no signal that content arrived |
| Medium | Persist theme preference and support `prefers-color-scheme: dark` | Tokens already make this a ~20-line addition |
| Medium | Virtualise or paginate the leaderboard/report tables | They grow with attempts; the current markup renders every row |
| Medium | Replace the fixed 260px chart height with a container query | Keeps charts legible on very narrow screens |
| Low | Visible character counter on exam descriptions (server caps at 2 000) | Prevents a late 400 after typing |
| Low | Focus ring on the chart `<svg>` containers | Recharts is not keyboard reachable today |
| Low | Add `lang` changes if the UI is ever translated | Contrasts with the current single-language assumption |

---

## 7. Reproducing this review

```bash
cd frontend
npx vitest run src/test/a11y.test.jsx   # axe on all 11 screens (+ meta check)
npx vitest run                          # 46 behaviour/UI tests
python3 ../scripts/ux_check.py          # 56 static UX/a11y/design checks
npm audit                               # dependency health
cd ../backend && .venv/bin/python ../scripts/ui_smoke.py   # live walk, 62 checks
```
