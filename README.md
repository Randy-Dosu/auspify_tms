# Auspify TMS — Online Examination System

A secure online examination system: administrators/teachers create exams,
students take timed tests, results are graded on the server, and performance
reports are generated.

**Status: Step 0 complete (project setup).** Steps 1–5 are built incrementally;
this README grows with them.

## Tech stack

| Layer    | Technology |
| -------- | ---------- |
| Backend  | Python 3, Flask, Flask-CORS, SQLite, python-dotenv |
| Frontend | React 19 (Vite), plain CSS |

## Repository layout

```
.
├── backend/
│   ├── app/
│   │   ├── __init__.py        # app factory: CORS, security headers, JSON errors
│   │   ├── config.py          # configuration from environment variables
│   │   └── routes/
│   │       └── health.py      # GET /api/health
│   ├── instance/              # SQLite database lives here (git-ignored)
│   ├── .env.example           # template — copy to .env
│   ├── requirements.txt
│   └── run.py                 # development entry point
├── frontend/
│   ├── src/
│   │   ├── api/client.js      # single API client (fetch wrapper)
│   │   ├── App.jsx            # Step 0 connection page
│   │   ├── index.css          # global styles / design tokens
│   │   └── main.jsx
│   ├── .env.example
│   └── vite.config.js         # dev server + /api proxy to Flask
├── .gitignore
└── README.md
```

## 1. Environment variables

Copy the template and fill in real values:

```bash
cp backend/.env.example backend/.env
# generate two independent 64-char hex keys:
python -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))"
python -c "import secrets; print('JWT_SECRET_KEY=' + secrets.token_hex(32))"
```

| Variable | Required | Purpose |
| -------- | -------- | ------- |
| `SECRET_KEY` | yes | Flask session/CSRF signing key |
| `JWT_SECRET_KEY` | yes | JWT signing key (kept separate from `SECRET_KEY`) |
| `JWT_ALGORITHM` | no (default `HS256`) | JWT signing algorithm |
| `JWT_ACCESS_TOKEN_EXPIRES_MINUTES` | no (default `30`) | Access-token lifetime |
| `APP_ENV` | no (default `development`) | Environment label |
| `APP_DEBUG` | no (default `0`) | `1` only in development |
| `DATABASE_PATH` | no | SQLite file (default `backend/instance/exam_system.db`) |
| `CORS_ORIGINS` | no | Comma-separated browser origins allowed to call the API |
| `PORT` | no (default `5000`) | API port |

`backend/.env` is git-ignored. Only `.env.example` is committed; the app
refuses to start if `SECRET_KEY` or `JWT_SECRET_KEY` is missing.

## 2. Run the backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python run.py            # http://localhost:5000
```

Health check:

```bash
curl -s http://localhost:5000/api/health
```

## 3. Run the frontend

```bash
cd frontend
npm install
npm run dev                        # http://localhost:5173
```

Open http://localhost:5173 — the page reports "API reachable" when the Flask
API answers through the Vite `/api` proxy.

## Security notes (Step 0)

- Secrets come from environment variables only; no key is hardcoded.
- CORS is restricted to the configured frontend origin(s), never `*`.
- Baseline security headers on every response: `X-Content-Type-Options`,
  `X-Frame-Options`, `Content-Security-Policy`, `Referrer-Policy`, and
  `Cache-Control: no-store` for API responses.
- Errors are returned as JSON `{"error": {"code", "message"}}` with no stack traces.
- `APP_DEBUG=1` is development-only; production runs with debug off.

## 4. Verification harness

`scripts/verify_step0.sh` re-runs the whole Step 0 checklist (25 checks:
health endpoint, security headers, JSON errors, CORS, secret hygiene,
frontend serving + proxy + production build):

```bash
# with backend on :5000 and frontend on :5173 already running
./scripts/verify_step0.sh
```

Expected final line: `RESULT: 25 passed, 0 failed`.
