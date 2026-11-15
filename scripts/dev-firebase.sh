#!/usr/bin/env bash
# Run TutorKid locally with real Firebase sign-in (Google / email+password).
# The Firebase Admin key is read from Secret Manager into memory; nothing is stored on disk.
# Settings: env/common.env + env/dev.env + env/local.env (optional, gitignored).
#
# Usage:
#   ./scripts/dev-firebase.sh            # Python on the host + UI watch, http://localhost:8766
#   ./scripts/dev-firebase.sh --docker   # the prod image via Docker Compose, http://localhost:8080
set -euo pipefail
source "$(dirname "$0")/lib.sh"
cd "$ROOT"

MODE=host
for arg in "$@"; do
  case "$arg" in
    --docker) MODE=docker ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) die "Unknown argument: $arg" ;;
  esac
done

load_env dev
export AUTH_DEV_MODE=0
export SESSION_COOKIE_SECURE=0

ensure_gcloud
load_firebase_credentials
ensure_docker

if [[ "$MODE" == "docker" ]]; then
  echo "Firebase project: $FIREBASE_PROJECT_ID (key from secret '$FIREBASE_CREDENTIALS_SECRET')"
  echo "Building the image and serving it on http://localhost:8080 (Ctrl+C to stop)…"
  # `run -e` overrides env_file values; values come from this shell, not the command line.
  exec docker compose run --rm --build --service-ports \
    -e AUTH_DEV_MODE -e SESSION_COOKIE_SECURE -e FIREBASE_CREDENTIALS_JSON \
    app
fi

# --- Host mode ---
if ! docker compose ps --status running db 2>/dev/null | grep -q db; then
  echo "Starting local Postgres…"
  docker compose up -d db
fi

if [[ ! -x .venv/bin/python ]]; then
  PYTHON="$(command -v python3.13 || command -v python3 || true)"
  [[ -n "$PYTHON" ]] || die "Python 3.12+ not found."
  "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 12))' || die "$PYTHON is older than 3.12."
  echo "Creating .venv with ${PYTHON}…"
  "$PYTHON" -m venv .venv
fi

if ! .venv/bin/python -c "import psycopg, firebase_admin" 2>/dev/null; then
  echo "Installing Python dependencies…"
  .venv/bin/pip install -q -r requirements-dev.txt
fi

if [[ ! -d node_modules ]]; then
  command -v npm >/dev/null || die "npm not found (install Node.js 18+)."
  npm ci
fi

echo "Firebase project: $FIREBASE_PROJECT_ID (key from secret '$FIREBASE_CREDENTIALS_SECRET')"
echo "Database: $DATABASE_URL"
echo "UI watch + server on http://localhost:8766"
echo "Hard-refresh the browser after UI rebuilds."

WATCH_LOG="${TMPDIR:-/tmp}/tutorkid-esbuild-watch.log"
npm run watch >"$WATCH_LOG" 2>&1 &
WATCH_PID=$!
cleanup() {
  # npm does not forward the signal to esbuild, so stop its children too.
  pkill -P "$WATCH_PID" 2>/dev/null || true
  kill "$WATCH_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Give esbuild a moment for the first bundle.
sleep 1
if ! kill -0 "$WATCH_PID" 2>/dev/null; then
  echo "esbuild watch failed to start. Log:"
  cat "$WATCH_LOG" || true
  exit 1
fi

# Not `exec`, so the trap still stops the watcher when the server exits.
.venv/bin/python server.py 8766
