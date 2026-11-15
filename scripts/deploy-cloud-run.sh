#!/usr/bin/env bash
# One-command deploy of the current working tree to Cloud Run (prod).
#
# Usage:
#   ./scripts/deploy-cloud-run.sh        # asks for confirmation before deploying
#   ./scripts/deploy-cloud-run.sh -y     # no confirmation
#
# Settings come from env/common.env + env/prod.env (non-secret values + Secret Manager *names*).
# The script takes care of everything else it can:
#   - gcloud login / Docker Desktop / Artifact Registry docker auth
#   - enabling required GCP APIs and creating the Artifact Registry repo
#   - creating missing secrets (asks once: DATABASE_URL / OPENAI_API_KEY with hidden
#     input, Firebase Admin key as the path of the JSON downloaded from Firebase)
#   - a unique image tag per deploy (git sha, plus timestamp if uncommitted changes)
#   - build + push + deploy + smoke test
# DB migrations run automatically when the server starts.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

ASSUME_YES=0
for arg in "$@"; do
  case "$arg" in
    -y|--yes) ASSUME_YES=1 ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "Unknown argument: $arg"; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
assert_no_raw_secrets "$ENV_DIR/common.env" "$ENV_DIR/prod.env"
load_env prod

: "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID in env/common.env}"
: "${GCP_REGION:?Set GCP_REGION in env/prod.env}"
: "${CLOUD_RUN_SERVICE:?Set CLOUD_RUN_SERVICE in env/prod.env}"
: "${ARTIFACT_REPO:?Set ARTIFACT_REPO in env/prod.env}"
: "${CLOUDSQL_CONNECTION:?Set CLOUDSQL_CONNECTION in env/prod.env}"
: "${CLOUD_RUN_SERVICE_ACCOUNT:?Set CLOUD_RUN_SERVICE_ACCOUNT in env/prod.env}"
: "${FIREBASE_PROJECT_ID:?Set FIREBASE_PROJECT_ID in env/common.env}"
: "${FIREBASE_WEB_API_KEY:?Set FIREBASE_WEB_API_KEY in env/common.env}"
: "${FIREBASE_AUTH_DOMAIN:?Set FIREBASE_AUTH_DOMAIN in env/common.env}"
: "${FIREBASE_WEB_APP_ID:?Set FIREBASE_WEB_APP_ID in env/common.env}"
: "${DATABASE_URL_SECRET:?Set DATABASE_URL_SECRET in env/prod.env}"
: "${FIREBASE_CREDENTIALS_SECRET:?Set FIREBASE_CREDENTIALS_SECRET in env/common.env}"

if [[ "${AUTH_DEV_MODE:-0}" == "1" ]]; then
  die "Refusing to deploy with AUTH_DEV_MODE=1. Set AUTH_DEV_MODE=0 in env/prod.env."
fi

# Image tag: explicit IMAGE_TAG wins unless it is empty or "auto".
if [[ -z "${IMAGE_TAG:-}" || "${IMAGE_TAG}" == "auto" ]]; then
  if git -C "$ROOT" rev-parse --short HEAD >/dev/null 2>&1; then
    IMAGE_TAG="$(git -C "$ROOT" rev-parse --short HEAD)"
    if [[ -n "$(git -C "$ROOT" status --porcelain)" ]]; then
      IMAGE_TAG+="-dirty-$(date +%Y%m%d-%H%M%S)"
    fi
  else
    IMAGE_TAG="build-$(date +%Y%m%d-%H%M%S)"
  fi
fi

REGISTRY_HOST="${GCP_REGION}-docker.pkg.dev"
IMAGE="${REGISTRY_HOST}/${GCP_PROJECT_ID}/${ARTIFACT_REPO}/${CLOUD_RUN_SERVICE}:${IMAGE_TAG}"

echo "Project:  $GCP_PROJECT_ID ($GCP_REGION)"
echo "Service:  $CLOUD_RUN_SERVICE"
echo "Image:    $IMAGE"
if [[ "$IMAGE_TAG" == *-dirty-* ]]; then
  echo "Note:     deploying uncommitted changes from the working tree."
fi

if [[ "$ASSUME_YES" != "1" ]]; then
  read -r -p "Deploy to PRODUCTION? [y/N] " answer
  [[ "$answer" == "y" || "$answer" == "Y" ]] || { echo "Aborted."; exit 1; }
fi

# ---------------------------------------------------------------------------
# Local tooling
# ---------------------------------------------------------------------------
step "Checking local tools"
ensure_gcloud

ensure_docker

if ! grep -q "\"${REGISTRY_HOST}\"" "${HOME}/.docker/config.json" 2>/dev/null; then
  echo "Configuring docker auth for ${REGISTRY_HOST}…"
  gcloud auth configure-docker "$REGISTRY_HOST" --quiet
fi

# ---------------------------------------------------------------------------
# Cloud prerequisites (idempotent)
# ---------------------------------------------------------------------------
step "Ensuring GCP APIs are enabled"
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  sqladmin.googleapis.com \
  --project="$GCP_PROJECT_ID"

step "Ensuring Artifact Registry repo '$ARTIFACT_REPO'"
if ! gcloud artifacts repositories describe "$ARTIFACT_REPO" \
    --project="$GCP_PROJECT_ID" --location="$GCP_REGION" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$ARTIFACT_REPO" \
    --project="$GCP_PROJECT_ID" --location="$GCP_REGION" \
    --repository-format=docker
fi

step "Checking Secret Manager secrets"
if ! secret_exists "$DATABASE_URL_SECRET"; then
  secret_prompt "$DATABASE_URL_SECRET" \
    "DATABASE_URL (postgresql://USER:PASSWORD@/DBNAME?host=/cloudsql/${CLOUDSQL_CONNECTION})" \
    || die "No value entered for '$DATABASE_URL_SECRET'."
fi

if ! secret_exists "$FIREBASE_CREDENTIALS_SECRET"; then
  echo "Secret '$FIREBASE_CREDENTIALS_SECRET' is missing."
  echo "Download a key in Firebase Console → Project settings → Service accounts → Generate new private key."
  read -r -p "Path to the downloaded JSON: " creds_path
  creds_path="${creds_path/#\~/$HOME}"
  [[ -f "$creds_path" ]] || die "File not found: $creds_path"
  secret_put "$FIREBASE_CREDENTIALS_SECRET" < "$creds_path"
  echo "Uploaded. You can delete $creds_path now; scripts read the key from Secret Manager."
fi

if [[ -n "${OPENAI_API_KEY_SECRET:-}" ]] && ! secret_exists "$OPENAI_API_KEY_SECRET"; then
  if ! secret_prompt "$OPENAI_API_KEY_SECRET" "OPENAI_API_KEY (empty = skip OpenAI)"; then
    echo "Skipping OpenAI for this deploy."
    OPENAI_API_KEY_SECRET=""
  fi
fi
echo "Secrets OK."

# ---------------------------------------------------------------------------
# Build, push, deploy
# ---------------------------------------------------------------------------
step "Building and pushing $IMAGE"
docker buildx build --platform linux/amd64 --push -t "$IMAGE" "$ROOT"

SECRET_FLAGS="DATABASE_URL=${DATABASE_URL_SECRET}:latest"
SECRET_FLAGS+=",FIREBASE_CREDENTIALS_JSON=${FIREBASE_CREDENTIALS_SECRET}:latest"
if [[ -n "${OPENAI_API_KEY_SECRET:-}" ]]; then
  SECRET_FLAGS+=",OPENAI_API_KEY=${OPENAI_API_KEY_SECRET}:latest"
fi

ENV_VARS="AUTH_DEV_MODE=0"
ENV_VARS+=",SESSION_COOKIE_SECURE=${SESSION_COOKIE_SECURE:-1}"
ENV_VARS+=",FIREBASE_PROJECT_ID=${FIREBASE_PROJECT_ID}"
ENV_VARS+=",FIREBASE_WEB_API_KEY=${FIREBASE_WEB_API_KEY}"
ENV_VARS+=",FIREBASE_AUTH_DOMAIN=${FIREBASE_AUTH_DOMAIN}"
ENV_VARS+=",FIREBASE_WEB_APP_ID=${FIREBASE_WEB_APP_ID}"

CLOUD_RUN_MEMORY="${CLOUD_RUN_MEMORY:-2Gi}"
CLOUD_RUN_CPU="${CLOUD_RUN_CPU:-2}"
CLOUD_RUN_TIMEOUT="${CLOUD_RUN_TIMEOUT:-300}"

step "Deploying Cloud Run service ${CLOUD_RUN_SERVICE}"
echo "  secrets → $SECRET_FLAGS"
echo "  resources → memory=${CLOUD_RUN_MEMORY} cpu=${CLOUD_RUN_CPU} timeout=${CLOUD_RUN_TIMEOUT}s"
gcloud run deploy "$CLOUD_RUN_SERVICE" \
  --project="$GCP_PROJECT_ID" \
  --region="$GCP_REGION" \
  --image="$IMAGE" \
  --allow-unauthenticated \
  --memory="$CLOUD_RUN_MEMORY" \
  --cpu="$CLOUD_RUN_CPU" \
  --timeout="$CLOUD_RUN_TIMEOUT" \
  --add-cloudsql-instances="$CLOUDSQL_CONNECTION" \
  --service-account="$CLOUD_RUN_SERVICE_ACCOUNT" \
  --set-secrets="$SECRET_FLAGS" \
  --set-env-vars="$ENV_VARS" \
  --quiet

SERVICE_URL="$(gcloud run services describe "$CLOUD_RUN_SERVICE" \
  --project="$GCP_PROJECT_ID" \
  --region="$GCP_REGION" \
  --format='value(status.url)')"

# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------
step "Smoke test"
config="$(curl -fsS --max-time 30 "${SERVICE_URL}/api/auth/config" || true)"
if [[ -z "$config" ]]; then
  echo "WARNING: ${SERVICE_URL}/api/auth/config did not respond. Check logs:"
  echo "  gcloud run services logs read $CLOUD_RUN_SERVICE --project=$GCP_PROJECT_ID --region=$GCP_REGION --limit=50"
  exit 1
fi
if echo "$config" | grep -q '"dev_mode": *false'; then
  echo "/api/auth/config OK (Firebase sign-in active)."
else
  echo "WARNING: unexpected /api/auth/config response: $config"
fi

echo
echo "Deployed $IMAGE_TAG → $SERVICE_URL"
echo "Make sure ${SERVICE_URL#https://} is in Firebase Console → Authentication → Settings → Authorized domains."
