# Scripts: local run and Cloud Run deployment

TutorKid is deployed as a single Cloud Run service. The scripts in this folder deploy that service and run it locally, and the deployment covers every feature at once. Settings come from the files under [`env/`](../env/README.md).

| Script | Use it to |
|---|---|
| [`deploy-cloud-run.sh`](deploy-cloud-run.sh) | Build the current working tree and deploy it to production |
| [`upsert-secret.sh`](upsert-secret.sh) | Set or rotate a Secret Manager value |
| [`dev-firebase.sh`](dev-firebase.sh) | Run locally with real Firebase sign-in: on the host with UI auto-rebuild, or the prod image with `--docker` |
| [`lib.sh`](lib.sh) | Shared helpers sourced by the other scripts (not run directly) |

The cloud resources must exist first. See [One-time cloud setup](#one-time-cloud-setup).

## Config

The scripts never read the env files directly. They call `load_env` in `lib.sh`:

| Script | Files loaded (later wins) |
|---|---|
| `deploy-cloud-run.sh`, `upsert-secret.sh` | `env/common.env` → `env/prod.env` |
| `dev-firebase.sh` | `env/common.env` → `env/dev.env` → `env/local.env` (if present) |

`env/common.env` holds `GCP_PROJECT_ID` and `FIREBASE_CREDENTIALS_SECRET`, because the dev script reads the Firebase key from the same project. `env/prod.env` holds the Cloud Run settings and the other secret **names**, never their values. No secret is stored in the repo or on disk: the scripts read them from Secret Manager each run. `deploy-cloud-run.sh` won't run if `env/common.env` or `env/prod.env` contains `DATABASE_URL`, `FIREBASE_CREDENTIALS_JSON` or `OPENAI_API_KEY`.

## `deploy-cloud-run.sh`

```sh
./scripts/deploy-cloud-run.sh        # shows project, service and image, then asks "Deploy to PRODUCTION? [y/N]"
./scripts/deploy-cloud-run.sh -y     # no confirmation
./scripts/deploy-cloud-run.sh -h     # help
```

It deploys the files currently on disk, including uncommitted changes. Steps, in order:

1. **Checks the config.** Loads the env files, stops if a required key is missing, and refuses `AUTH_DEV_MODE=1`.
2. **Picks the image tag.** With `IMAGE_TAG=auto` (or empty) the tag is the short git sha, plus `-dirty-<YYYYmmdd-HHMMSS>` if the working tree has uncommitted changes. Any other value is used as-is. The image is `<GCP_REGION>-docker.pkg.dev/<GCP_PROJECT_ID>/<ARTIFACT_REPO>/<CLOUD_RUN_SERVICE>:<tag>`.
3. **Checks local tools.** Requires `gcloud`. Runs `gcloud auth login` if there's no valid login (`ensure_gcloud`), starts Docker Desktop if it isn't running (waits up to 2 minutes), and runs `gcloud auth configure-docker <GCP_REGION>-docker.pkg.dev` if Docker has no login for that registry yet.
4. **Prepares the cloud project.** It enables the `run`, `artifactregistry`, `secretmanager` and `sqladmin` APIs and creates the Artifact Registry Docker repo `ARTIFACT_REPO` if it's missing. Both steps are safe to repeat.
5. **Checks secrets.** For each secret name in `env/prod.env` that doesn't exist yet:
   - `DATABASE_URL_SECRET`: asks for the value (hidden input) and stops if you leave it empty.
   - `FIREBASE_CREDENTIALS_SECRET`: asks for the path of a key JSON downloaded from Firebase, uploads it, and tells you to delete the download.
   - `OPENAI_API_KEY_SECRET` (only if set): asks for the value. Leave it empty to deploy without OpenAI.

   Existing secrets are left alone. A newly created secret also needs an access grant for the runtime service account (see [Secret access](#4-secret-access)).
6. **Builds and pushes** the image with `docker buildx build --platform linux/amd64 --push`.
7. **Deploys** the image with `gcloud run deploy`:

   | Cloud Run setting | Value |
   |---|---|
   | Public access | `--allow-unauthenticated` |
   | Memory / CPU / timeout | `--memory=$CLOUD_RUN_MEMORY` (default `2Gi`), `--cpu=$CLOUD_RUN_CPU` (default `2`), `--timeout=$CLOUD_RUN_TIMEOUT` (default `300`) — sized for PaddleOCR image read |
   | Cloud SQL | `--add-cloudsql-instances=$CLOUDSQL_CONNECTION` (socket at `/cloudsql/<connection>`) |
   | Runtime identity | `--service-account=$CLOUD_RUN_SERVICE_ACCOUNT` |
   | Secrets as env vars | `DATABASE_URL`, `FIREBASE_CREDENTIALS_JSON`, `OPENAI_API_KEY` (if set), all at version `latest` |
   | Plain env vars | `AUTH_DEV_MODE=0`, `SESSION_COOKIE_SECURE` (default `1`), `FIREBASE_PROJECT_ID`, `FIREBASE_WEB_API_KEY`, `FIREBASE_AUTH_DOMAIN`, `FIREBASE_WEB_APP_ID` |

   `--set-env-vars` and `--set-secrets` **replace** the service's whole list each time. A variable set by hand in the Cloud Console disappears on the next deploy. To add a new prod variable, add it to `ENV_VARS` (or `SECRET_FLAGS`) in the script and its value to `env/prod.env` or `env/common.env`. Everything else the app reads (`SESSION_LIFETIME_DAYS`, `OPENAI_MODEL`, …) uses the default in the code.
8. **Smoke-tests** `GET <service-url>/api/auth/config`. If there's no response, it prints the logs command and exits with status 1. If the response doesn't contain `"dev_mode": false`, it prints a warning. It then prints the service URL and a reminder to add its domain to Firebase **Authorized domains**.

The database schema is updated when the server starts (`migrations/*.sql` → `schema_migrations` table), not by the script.

### Rollback and logs

```sh
gcloud run revisions list --service=$CLOUD_RUN_SERVICE --project=$GCP_PROJECT_ID --region=$GCP_REGION
gcloud run services update-traffic $CLOUD_RUN_SERVICE --to-revisions=<REVISION>=100 \
  --project=$GCP_PROJECT_ID --region=$GCP_REGION
gcloud run services logs read $CLOUD_RUN_SERVICE --project=$GCP_PROJECT_ID --region=$GCP_REGION --limit=50
```

Rolling back puts back the old code, but any database changes from new migrations stay.

## `upsert-secret.sh`

Creates the secret in `GCP_PROJECT_ID` from `env/prod.env`, or adds a new version if it already exists. Cloud Run reads the `latest` version, so the new value takes effect from the next deploy.

```sh
./scripts/upsert-secret.sh database-url                                       # prompts, hidden input
./scripts/upsert-secret.sh firebase-credentials < ~/Downloads/<key>.json     # from a file, then delete it
```

`DATABASE_URL` for Cloud SQL uses the Unix socket:
`postgresql://USER:PASSWORD@/DBNAME?host=/cloudsql/<CLOUDSQL_CONNECTION>`

## `dev-firebase.sh`

```sh
./scripts/dev-firebase.sh            # Python on the host + UI watch → http://localhost:8766
./scripts/dev-firebase.sh --docker   # prod image via Docker Compose → http://localhost:8080
```

A fresh clone needs no other setup command. You need `gcloud` (logged in with `secretAccessor` on `FIREBASE_CREDENTIALS_SECRET`), Docker Desktop, Python 3.12+ and Node.js 18+. Both modes:

- Load `common.env` → `dev.env` → `local.env`, then force `AUTH_DEV_MODE=0` and `SESSION_COOKIE_SECURE=0`.
- Run `gcloud auth login` if needed, and read the Firebase Admin key from Secret Manager into `FIREBASE_CREDENTIALS_JSON`. The key is held in memory only and never written to disk.
- Start Docker Desktop if it isn't running.

Host mode also:

- Starts the Compose `db` service if needed (Postgres on `localhost:54329`).
- Creates `.venv` if it's missing (with `python3.13`, or `python3` if it's 3.12+), installs `requirements-dev.txt` if `psycopg` or `firebase_admin` is missing, and runs `npm ci` if `node_modules` is missing.
- Runs `npm run watch` in the background (log in `$TMPDIR/tutorkid-esbuild-watch.log`) and stops it when the server exits. Hard-refresh the browser after UI changes, and restart the script after backend changes.

`--docker` runs `docker compose run --rm --build --service-ports app`. It builds the same image as prod, starts `db`, and passes the key and auth settings as container env vars (`-e`, which override the env files). The image itself never contains the key. Stop it with Ctrl+C.

A plain `docker compose up --build` still works without gcloud, using the local-dev sign-in form.

Firebase must list `localhost` under **Authorized domains**.

## `lib.sh`

Sourced by the other scripts. It provides `ROOT` / `ENV_DIR` and these helpers:

- `load_env dev|prod`: loads the env files in the order described in [Config](#config)
- `load_env_file`: reads plain `KEY=VALUE` lines, skipping blank lines and `#` comments, with no quoting or expansion
- `assert_no_raw_secrets`: stops if an env file contains a raw secret
- `ensure_docker`: makes sure Docker is running
- `ensure_gcloud`: checks that `gcloud` is installed and logged in
- `load_firebase_credentials`: exports `FIREBASE_CREDENTIALS_JSON` from Secret Manager (memory only)
- `secret_exists`, `secret_put` (value from stdin), `secret_prompt` (hidden input): Secret Manager helpers in `GCP_PROJECT_ID`
- `step`, `die`: progress and error messages

## One-time cloud setup

The deploy script handles the APIs, the Artifact Registry repo and missing secret values. Set up the rest once. The commands below use the keys from `env/prod.env`; replace them with the actual values.

### 1. Local tools

Anyone who runs `dev-firebase.sh` needs `roles/secretmanager.secretAccessor` on `FIREBASE_CREDENTIALS_SECRET` (project Owner already has it).

- `gcloud` CLI, logged in as an account that can deploy. Project **Owner** is enough. Otherwise you need Cloud Run Admin, Artifact Registry Admin, Secret Manager Admin, Service Usage Admin, Cloud SQL Admin (for setup), and **Service Account User** on the runtime service account.
- Docker Desktop with `buildx` (included).

### 2. Cloud SQL (Postgres)

```sh
gcloud sql instances create <INSTANCE> --project=$GCP_PROJECT_ID --region=$GCP_REGION \
  --database-version=POSTGRES_18 --edition=enterprise --tier=db-f1-micro
gcloud sql databases create tutorkid --instance=<INSTANCE> --project=$GCP_PROJECT_ID
gcloud sql users create tutorkid --instance=<INSTANCE> --project=$GCP_PROJECT_ID --password=<PASSWORD>
```

This creates a small shared-core Enterprise instance. The current prod instance (`lazy-parent`) is `ENTERPRISE_PLUS` / `db-perf-optimized-N-8`. To match it, use `--edition=enterprise-plus --tier=db-perf-optimized-N-8` instead.

Set `CLOUDSQL_CONNECTION=<GCP_PROJECT_ID>:<GCP_REGION>:<INSTANCE>` in `env/prod.env`. The `DATABASE_URL` secret is
`postgresql://tutorkid:<PASSWORD>@/tutorkid?host=/cloudsql/<CLOUDSQL_CONNECTION>`.

### 3. Runtime service account

```sh
gcloud iam service-accounts create <NAME> --project=$GCP_PROJECT_ID
gcloud projects add-iam-policy-binding $GCP_PROJECT_ID \
  --member="serviceAccount:$CLOUD_RUN_SERVICE_ACCOUNT" --role=roles/cloudsql.client
```

Set `CLOUD_RUN_SERVICE_ACCOUNT=<NAME>@<GCP_PROJECT_ID>.iam.gserviceaccount.com` in `env/prod.env`.

### 4. Secret access

The runtime service account reads each secret through its own access grant on that secret. Every secret named in `env/prod.env` needs one, including secrets that `deploy-cloud-run.sh` creates:

```sh
for s in $DATABASE_URL_SECRET $FIREBASE_CREDENTIALS_SECRET $OPENAI_API_KEY_SECRET; do
  gcloud secrets add-iam-policy-binding "$s" --project=$GCP_PROJECT_ID \
    --member="serviceAccount:$CLOUD_RUN_SERVICE_ACCOUNT" --role=roles/secretmanager.secretAccessor
done
```

The secret has to exist before you can grant access to it. On a brand-new setup, either upload the values with `upsert-secret.sh` first, or let the first deploy create them (that deploy will fail to start), then add the grants and deploy again.

### 5. Firebase

The Firebase project (`FIREBASE_PROJECT_ID`) can be a different Google Cloud project from `GCP_PROJECT_ID`.

1. **Authentication → Sign-in method:** enable **Google** and **Email/Password** (not email link).
2. **Project settings → Your apps:** register a web app, and copy `apiKey`, `authDomain`, `projectId` and `appId` into `env/common.env` as `FIREBASE_WEB_API_KEY`, `FIREBASE_AUTH_DOMAIN`, `FIREBASE_PROJECT_ID` and `FIREBASE_WEB_APP_ID`. These values are public browser config.
3. **Project settings → Service accounts → Generate new private key:** the first deploy asks for the path of the downloaded file and uploads it as `FIREBASE_CREDENTIALS_SECRET`. You can also run `./scripts/upsert-secret.sh firebase-credentials < <file>`. Delete the download afterwards.
4. **Authentication → Settings → Authorized domains:** add the Cloud Run domain (printed after a deploy) and `localhost`.

### 6. First deploy

Fill in `GCP_PROJECT_ID` (in `env/common.env`) and `GCP_REGION`, `CLOUD_RUN_SERVICE`, `ARTIFACT_REPO`, `CLOUDSQL_CONNECTION` and `CLOUD_RUN_SERVICE_ACCOUNT` in `env/prod.env`, then run `./scripts/deploy-cloud-run.sh`.

## Production checklist

- [ ] `AUTH_DEV_MODE=0` in `env/prod.env` (the script refuses `1`)
- [ ] Every secret in `env/prod.env` grants `secretAccessor` to the runtime service account
- [ ] Firebase authorized domains include the Cloud Run domain
- [ ] The smoke test passes (`/api/auth/config` → `"dev_mode": false`)
- [ ] Manual check: kid signup, parent adds kid, second-parent approval, logout
