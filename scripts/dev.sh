#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# One-command development stack for Auspify TMS.
#
#   ./scripts/dev.sh            # API on :5000 + UI on :5173
#   ./scripts/dev.sh --no-install
#
# It is a convenience wrapper around the Quick start in README §3. Everything it
# does is idempotent, so re-running it never destroys data:
#   * creates backend/.venv and installs the pinned requirements if missing
#   * creates backend/.env from .env.example with freshly generated secrets
#   * seeds the database (1 admin, 1 teacher, 3 students) when it is empty
#   * installs frontend/node_modules if missing
#   * starts Flask and the Vite dev server, and stops both on Ctrl-C
# ---------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
PYTHON="${PYTHON:-python3}"
INSTALL=1

for arg in "$@"; do
  case "$arg" in
    --no-install) INSTALL=0 ;;
    -h|--help) sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

say() { printf '\033[36m==>\033[0m %s\n' "$*"; }
die() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

command -v "$PYTHON" >/dev/null 2>&1 || die "python3 is required"
command -v npm >/dev/null 2>&1 || die "npm is required"

# --- Backend environment ---------------------------------------------------
if [ ! -x "$BACKEND/.venv/bin/python" ]; then
  say "creating backend/.venv"
  "$PYTHON" -m venv "$BACKEND/.venv"
  INSTALL=1
fi
if [ "$INSTALL" -eq 1 ]; then
  say "installing backend requirements"
  "$BACKEND/.venv/bin/pip" install --quiet --upgrade pip
  "$BACKEND/.venv/bin/pip" install --quiet -r "$BACKEND/requirements.txt"
fi

if [ ! -f "$BACKEND/.env" ]; then
  say "creating backend/.env with freshly generated secrets"
  "$BACKEND/.venv/bin/python" - "$BACKEND" <<'PY'
import pathlib
import secrets
import sys

backend = pathlib.Path(sys.argv[1])
text = (backend / ".env.example").read_text()
for placeholder, value in {
    "replace-me-with-64-random-hex-chars": secrets.token_hex(32),
    "replace-me-with-another-64-random-hex-chars": secrets.token_hex(32),
    "replace-with-a-strong-password": secrets.token_urlsafe(12),
}.items():
    text = text.replace(placeholder, value)
(backend / ".env").write_text(text)
PY
fi

# --- Database --------------------------------------------------------------
if [ ! -f "$BACKEND/instance/exam_system.db" ]; then
  say "seeding the database (admin, teacher, 3 students)"
  ( cd "$BACKEND" && .venv/bin/python seed.py )
else
  say "database already present - leaving it untouched"
fi

# --- Frontend dependencies -------------------------------------------------
if [ ! -d "$FRONTEND/node_modules" ]; then
  say "installing frontend dependencies"
  ( cd "$FRONTEND" && npm install --silent )
fi

# --- Run both servers ------------------------------------------------------
pids=()
cleanup() {
  trap - INT TERM EXIT
  for pid in "${pids[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

say "starting the API on http://localhost:5000"
( cd "$BACKEND" && exec .venv/bin/python run.py ) &
pids+=($!)

say "starting the UI on http://localhost:5173 (Ctrl-C stops both)"
( cd "$FRONTEND" && exec npm run dev ) &
pids+=($!)

say "health check: curl -s http://localhost:5000/api/health"

# Exit as soon as either server dies so a failure is visible immediately.
while :; do
  for pid in "${pids[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      wait "$pid" 2>/dev/null || true
      die "a server stopped; shutting down"
    fi
  done
  sleep 1
done
