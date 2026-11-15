# Shared helpers for scripts/*.sh. Source it; do not run it.
#   source "$(dirname "$0")/lib.sh"
#
# Env layout (see env/README.md): common.env → <env>.env → local.env (dev only).

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_DIR="$ROOT/env"

step() { printf '\n==> %s\n' "$*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

# Load KEY=VALUE lines from a file into the exported environment.
# Blank lines and # comments are skipped; values are taken literally (no quotes/expansion).
load_env_file() {
  local file="$1" line key value
  [[ -f "$file" ]] || die "Missing $file"
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -z "$line" || "$line" == \#* ]] && continue
    key="${line%%=*}"
    value="${line#*=}"
    key="${key%"${key##*[![:space:]]}"}"
    key="${key#"${key%%[![:space:]]*}"}"
    [[ -z "$key" ]] && continue
    printf -v "$key" '%s' "$value"
    export "$key"
  done < "$file"
}

# load_env dev|prod — load the env files for that environment, later files win.
load_env() {
  local name="$1"
  load_env_file "$ENV_DIR/common.env"
  load_env_file "$ENV_DIR/$name.env"
  if [[ "$name" != "prod" && -f "$ENV_DIR/local.env" ]]; then
    load_env_file "$ENV_DIR/local.env"
  fi
}

# Fail if a committed env file contains a raw secret value.
assert_no_raw_secrets() {
  local file
  for file in "$@"; do
    if grep -qE '^[[:space:]]*(DATABASE_URL|FIREBASE_CREDENTIALS_JSON|OPENAI_API_KEY)=' "$file"; then
      die "$file must not contain DATABASE_URL, FIREBASE_CREDENTIALS_JSON or OPENAI_API_KEY. Store them in Secret Manager (see env/README.md)."
    fi
  done
}

# Make sure the Docker daemon is up, starting Docker Desktop on macOS if needed.
ensure_docker() {
  command -v docker >/dev/null || die "docker not installed (install Docker Desktop)."
  docker info >/dev/null 2>&1 && return 0
  if [[ "$(uname)" == "Darwin" ]]; then
    echo "Starting Docker Desktop…"
    open -a Docker || true
  fi
  local _
  for _ in $(seq 1 60); do
    docker info >/dev/null 2>&1 && return 0
    sleep 2
  done
  die "Docker is not running. Start Docker Desktop and retry."
}

# Make sure gcloud is installed and logged in (opens the browser login if needed).
ensure_gcloud() {
  command -v gcloud >/dev/null || die "gcloud not installed (brew install --cask google-cloud-sdk)."
  if ! gcloud auth print-access-token >/dev/null 2>&1; then
    echo "gcloud is not logged in; opening browser login…"
    gcloud auth login
  fi
}

# --- Secret Manager (needs GCP_PROJECT_ID) ---

secret_exists() {
  gcloud secrets describe "$1" --project="$GCP_PROJECT_ID" >/dev/null 2>&1
}

# Create the secret or add a new version, reading the value from stdin.
secret_put() {
  local name="$1"
  if secret_exists "$name"; then
    gcloud secrets versions add "$name" --project="$GCP_PROJECT_ID" --data-file=- >/dev/null
    echo "Added new version to secret '$name'."
  else
    gcloud secrets create "$name" --project="$GCP_PROJECT_ID" --data-file=- >/dev/null
    echo "Created secret '$name'."
  fi
}

# Export FIREBASE_CREDENTIALS_JSON from Secret Manager (FIREBASE_CREDENTIALS_SECRET).
# The key stays in memory only; it is never written to disk.
load_firebase_credentials() {
  : "${FIREBASE_CREDENTIALS_SECRET:?Set FIREBASE_CREDENTIALS_SECRET in env/common.env}"
  FIREBASE_CREDENTIALS_JSON="$(gcloud secrets versions access latest \
    --secret="$FIREBASE_CREDENTIALS_SECRET" --project="$GCP_PROJECT_ID")" \
    || die "Could not read secret '$FIREBASE_CREDENTIALS_SECRET' in $GCP_PROJECT_ID (needs roles/secretmanager.secretAccessor)."
  export FIREBASE_CREDENTIALS_JSON
  unset FIREBASE_CREDENTIALS_FILE || true
}

# Prompt (hidden input) for a secret value and store it. Returns 1 if left empty.
secret_prompt() {
  local name="$1" description="$2" value
  read -r -s -p "Enter $description for secret '$name' (input hidden): " value
  echo
  [[ -n "$value" ]] || return 1
  printf '%s' "$value" | secret_put "$name"
}
