# Build log

- Step 0: setup (health endpoint, CORS, security headers, Vite proxy) — verifies with scripts/verify_step0.sh
- Step 1: authentication (bcrypt, JWT + logout blocklist, lockout, rate limiting, RBAC) — scripts/verify_step1.py + frontend vitest
