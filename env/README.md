# Environment config

Every environment uses the same keys. Each value is defined once, and later files override earlier ones:

| File | Holds | Loaded for | Git |
|---|---|---|---|
| `common.env` | Values shared by all environments: `GCP_PROJECT_ID`, the Firebase key's secret name, Firebase web config | dev + prod | committed |
| `dev.env` | Local defaults: Docker Postgres URL, `AUTH_DEV_MODE=1` | dev | committed |
| `prod.env` | Cloud Run settings and Secret Manager **names** (no secret values) | prod | committed |
| `local.env` | Your personal overrides and local secrets, e.g. `AUTH_DEV_MODE=0`, `OPENAI_API_KEY=` | dev | **ignored** |

Load order: `common.env` → `dev.env` | `prod.env` → `local.env` (dev only).
The shell scripts load these files through `load_env` in [`scripts/lib.sh`](../scripts/lib.sh), and `docker-compose.yml` lists the same files in the same order.

Keep values as plain `KEY=VALUE` lines, with no quotes and no multi-line values. The scripts read each value literally, so these files also work with `set -a; source …`.

## Secrets

| | Dev | Prod |
|---|---|---|
| `DATABASE_URL` | `dev.env` (local Docker DB, not secret) | Secret Manager (`DATABASE_URL_SECRET`) |
| Firebase Admin key | Secret Manager, read into memory by `dev-firebase.sh` | Secret Manager (`FIREBASE_CREDENTIALS_SECRET`) |
| `OPENAI_API_KEY` | `local.env` | Secret Manager (`OPENAI_API_KEY_SECRET`) |

On Cloud Run, Secret Manager values are injected as the normal env vars (`DATABASE_URL`, `FIREBASE_CREDENTIALS_JSON`, `OPENAI_API_KEY`), so the app code is the same in both environments. The deploy script won't run if `common.env` or `prod.env` contains one of those raw secret keys. No key file is kept in the repo: the scripts read the Firebase Admin key from Secret Manager on every run (you need `gcloud` logged in with access to that secret).

`./scripts/deploy-cloud-run.sh` creates any missing secret on its own. To set or rotate one yourself:

```sh
./scripts/upsert-secret.sh database-url                                 # prompts, hidden input
./scripts/upsert-secret.sh firebase-credentials < ~/Downloads/<key>.json   # then delete the download
```

## Commands

| Goal | Command |
|---|---|
| Local, full stack in Docker | `docker compose up --build` |
| Local, real Firebase sign-in + UI watch | `./scripts/dev-firebase.sh` |
| Local, prod image with real Firebase sign-in | `./scripts/dev-firebase.sh --docker` |
| Deploy to Cloud Run | `./scripts/deploy-cloud-run.sh` |
