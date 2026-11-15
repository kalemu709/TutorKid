# TutorKid / Study Helper

Browser study helpers. Chinese character practice works today; math is a placeholder. The site stays usable anonymously. Sign-in adds accounts so progress can be saved server-side.

## What runs

| Piece | Role |
| --- | --- |
| `server.py` | Serves the UI and APIs |
| `auth/` | Authentication and user-state feature |
| `migrations/` | Postgres schema, applied on startup |
| `app.jsx` + `auth-ui.jsx` | React source |
| `app.js` | Bundled UI (git-ignored; built by `npm run build`) |
| `docker-compose.yml` | Local Postgres + app on Docker Desktop |

Practice APIs:

| Endpoint | Purpose |
| --- | --- |
| `GET /api/tts-status` | Whether an API key is configured |
| `POST /api/extract` | Read characters from an uploaded PDF |
| `POST /api/ai-example` | Generate pinyin, meaning, example word, sentence |
| `POST /api/speech` | Generate Mandarin speech (MP3) |

Auth APIs (require `DATABASE_URL`):

| Endpoint | Purpose |
| --- | --- |
| `GET /api/auth/config` | Public Firebase / dev-mode config |
| `GET /api/auth/me` | Current session |
| `POST /api/auth/session` | Exchange identity token for session cookie |
| `POST /api/auth/dev-token` | Mint a local-dev token (`AUTH_DEV_MODE` only) |
| `POST /api/auth/logout` | Revoke session |
| `GET/POST /api/auth/kids` | List / add kids (parent) |
| `POST /api/auth/kids/select` | Select a kid account |
| `GET /api/auth/guardian-requests` | Pending guardian requests |
| `POST /api/auth/guardian-requests/{id}/decide` | Approve or decline |

Mutating auth requests need header `X-Requested-With: TutorKid`.

Design: [docs/features/authentication-and-user-state/design.md](docs/features/authentication-and-user-state/design.md)  
Run and deploy: [scripts/README.md](scripts/README.md)

## Config (dev + prod, same keys)

All app and deploy settings live under `env/`. Shared values are in `common.env`, per-environment values are in `dev.env` / `prod.env`, and personal overrides go in a gitignored `local.env`. Nothing needs to be copied first. See [env/README.md](env/README.md).

## Quick start with Docker Desktop

```sh
docker compose up --build
```

Open [http://localhost:8080](http://localhost:8080). By default (`AUTH_DEV_MODE=1`) you sign in with the local-dev form. For real Firebase sign-in in the container, run `./scripts/dev-firebase.sh --docker` instead.

To test **Firebase** login methods locally with UI watch:

```sh
./scripts/dev-firebase.sh   # reads the Firebase Admin key from Secret Manager; needs gcloud logged in
```

Open [http://localhost:8766/signin](http://localhost:8766/signin). Add `localhost` under Firebase authorized domains.

Stop with `docker compose down`.

## Deploy to Cloud Run

```sh
./scripts/deploy-cloud-run.sh
```

This deploys the current working tree in one step: it builds and pushes the image, creates any missing Secret Manager secrets, deploys, and runs a smoke test. Usage and one-time cloud setup: [scripts/README.md](scripts/README.md).

## Local Python + Docker Postgres

Requires Python 3.12+ and Node.js 18+.

```sh
docker compose up -d db
python3.13 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
npm ci
npm run build
set -a; source env/common.env; source env/dev.env; set +a
.venv/bin/python server.py
```

Open [http://localhost:8766](http://localhost:8766).

Optional OpenAI key for AI examples/voice: set `OPENAI_API_KEY=` in `env/local.env` and also `source env/local.env`, or prefix the command with `OPENAI_API_KEY=...`.

## Integration tests

```sh
docker compose up -d db
.venv/bin/pip install -r requirements-dev.txt
DATABASE_URL=postgresql://tutorkid:tutorkid@127.0.0.1:54329/tutorkid \
AUTH_DEV_MODE=1 AUTH_DEV_SECRET=test-secret-for-integration SESSION_COOKIE_SECURE=0 \
.venv/bin/pytest -q tests/test_auth_scenarios.py
```

## Using Chinese practice

Choose a daily PDF, or paste characters such as `山水火木人`, then **Start practice**. While practising, **Stop practice** reveals the list again so you can edit it. **Save for review** keeps hard characters in this browser until account-backed storage is added for practice data.
