#!/usr/bin/env bash
# Create a Secret Manager secret or add a new version, in the prod GCP project.
# Usage:
#   ./scripts/upsert-secret.sh SECRET_NAME                 # prompts, hidden input
#   ./scripts/upsert-secret.sh SECRET_NAME < value-file    # e.g. a downloaded Firebase key
set -euo pipefail
source "$(dirname "$0")/lib.sh"

NAME="${1:?Usage: $0 SECRET_NAME [< value-file]}"
load_env prod
: "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID in env/common.env}"
echo "Using GCP project: $GCP_PROJECT_ID"

if [[ -t 0 ]]; then
  secret_prompt "$NAME" "the value" || die "No value entered."
else
  secret_put "$NAME"
fi
