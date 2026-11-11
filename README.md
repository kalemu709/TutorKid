# Chinese Character Practice

A browser app for speaking and writing character practice. It imports text-based PDF sheets, `.txt` files, screenshots and photos of teaching material, and pasted character lists. PDF, text, and image reading and the device voice work offline; AI meanings and examples and the warm AI voice need an OpenAI API key and internet access.

A single Python server (`server.py`) serves the page (`index.html`, `app.js`) and the API the browser calls:


| Endpoint               | Purpose                                              |
| ---------------------- | ---------------------------------------------------- |
| `GET /api/tts-status`  | Whether an API key is configured                     |
| `POST /api/extract`    | Read the characters from an uploaded PDF, text file, or image |
| `POST /api/ai-example` | Generate pinyin, meaning, example word, and sentence |
| `POST /api/speech`     | Generate Mandarin speech (MP3)                       |


The API key stays on the server and is never sent to the browser.

## `Project` layout


| Path               | Purpose                                               |
| ------------------ | ----------------------------------------------------- |
| `server.py`        | Python backend and static file server                 |
| `requirements.txt` | Python dependencies (`pypdf`)                         |
| `app.jsx`          | React source                                          |
| `app.js`           | Bundled React app, built from `app.jsx` (git-ignored) |
| `index.html`       | Page shell that loads `app.js`                        |
| `Dockerfile`       | Builds the React app, then packages the Python server |




## Setup

Requires Python 3.12+ and Node.js 18+.

Python from the python.org installer has no CA certificates until you run its `Install Certificates.command` once. Without it, AI requests fail with `CERTIFICATE_VERIFY_FAILED`:

```sh
"/Applications/Python 3.12/Install Certificates.command"
```

Then create the virtual environment:

> ```sh
> cd "/Users/hanwenwang/Desktop/3500常用汉字_30天/web"
> python3.12 -m venv .venv
> .venv/bin/pip install -r requirements.txt
> ```

This installs PaddlePaddle and PaddleOCR for image reading, about 1 GB.

Build the frontend bundle (`app.js` is generated, not committed):

> ```sh
> npm ci
> npm run build
> ```



## Run locally

Without an API key (device voice only, no meanings or examples):

```sh
.venv/bin/python server.py
```

With the API key stored in macOS Keychain:

```sh
OPENAI_API_KEY=$(security find-generic-password -s chinese-character-practice-openai -w) .venv/bin/python server.py
```

Then open [http://localhost:8766](http://localhost:8766). Press Control-C to stop. Use another port with `.venv/bin/python server.py 9000` or `PORT=9000`.

### Store the API key in Keychain

Copy the key to the clipboard, then run:

```sh
security add-generic-password -U -a "$USER" -s chinese-character-practice-openai -l "Chinese Character Practice OpenAI API key" -w "$(pbpaste)"
```

The key is read from the clipboard, so it never appears in your shell history. Don't use `-w` without a value: its interactive prompt keeps only the first 128 characters, which cuts off OpenAI keys.

Check that the full key was saved (OpenAI project keys are about 164 characters):

```sh
security find-generic-password -s chinese-character-practice-openai -w | tr -d '\n' | wc -c
```

To replace the key, run the same command again. To remove it:

```sh
security delete-generic-password -s chinese-character-practice-openai
```



## Using the app

Choose a practice file, paste a screenshot, or type characters such as `山水火木人`, then choose **Start practice**.

| Input | How characters are found |
| --- | --- |
| PDF | Selectable text is read on the server. Scanned or image-only PDFs have no text; take a screenshot of the page instead. |
| `.txt` | Every Chinese character in the file, in order, without repeats. UTF-8, UTF-16 (with BOM), and GB18030/GBK are supported. |
| PNG, JPEG, WebP, GIF | [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) (PP-OCRv5 server models) reads the characters on the server, top to bottom and left to right. No API key needed. Up to 10 MB. |
| Screenshot | Copy a screenshot (on macOS, ⌘⌃⇧4 copies a selected area), then press ⌘V on the **Today** tab. |

Every Chinese character in the image is imported, including titles and other visible text, so crop the screenshot to the material you want. A full page of 117 characters takes about 20 seconds on a laptop CPU; a small screenshot takes a few seconds. The first image after the server starts also loads the models (a few seconds). The models are downloaded to `~/.paddlex` the first time (about 165 MB); the Docker image includes them.

While practising, select **Save for review** to keep a difficult character. The **Review** tab lists saved characters and starts a review session. Remove characters with the × beside them, or toggle the save button during practice.

### AI meanings, examples, and voice

With a key configured, **AI meaning + example** asks OpenAI for an entry for the current character (default model `gpt-4.1-mini`). The reader uses OpenAI text-to-speech with the `coral` voice and gentle, warm Mandarin delivery. Without a key, or if the service is unavailable, the browser's installed Mandarin voice is used.

Each request sends only the current character or practice prompt. API use is billed to your OpenAI account. Optional overrides:


| Variable           | Default           |
| ------------------ | ----------------- |
| `OPENAI_MODEL`     | `gpt-4.1-mini`    |
| `OPENAI_TTS_MODEL` | `gpt-4o-mini-tts` |
| `OPENAI_TTS_VOICE` | `coral`           |


The server limits each client to 20 example, 45 speech, and 10 image requests per minute, with at most 4 AI requests running at once. Images are read one at a time.

### Where data is stored

The server stores nothing. The review list and generated examples are kept in the browser's `localStorage`, so they are per browser and per device, and clearing site data removes them. A generated example is reused for the same character; speech is generated again each time it plays.

## Change the frontend

Edit `app.jsx`, then rebuild `app.js`:

```sh
npm install
npm run build
```

Refresh the browser to load the new bundle. The Docker image runs this build itself.

## Docker

The `Dockerfile` builds `app.js` from source in a Node stage, then copies it into a Python image with the dependencies from `requirements.txt` and the PaddleOCR models. The container listens on port 8080.

The image is `linux/amd64` only (about 2.6 GB): PaddlePaddle crashes on `linux/arm64`. On Apple Silicon, Docker runs it under emulation, so image reading is several times slower than with `.venv` (about 2 minutes for a full page).

```sh
docker build -t chinese-character-practice:local .
docker run --rm -p 8080:8080 \
  -e OPENAI_API_KEY="$(security find-generic-password -s chinese-character-practice-openai -w)" \
  chinese-character-practice:local
```

Then open [http://localhost:8080](http://localhost:8080).

## Deploy to Cloud Run



### One-time setup

```sh
export HANZI_PROJECT_ID="hanzi-practice-hw-2026"
export HANZI_REGION="us-west2"
export HANZI_REPO="hanzi"
export HANZI_SERVICE="hanzi-practice"
export HANZI_RUNTIME_SA="hanzi-practice-runtime"

gcloud config set project "$HANZI_PROJECT_ID"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com

gcloud artifacts repositories create "$HANZI_REPO" \
  --repository-format=docker \
  --location="$HANZI_REGION"

gcloud iam service-accounts create "$HANZI_RUNTIME_SA" \
  --display-name="Chinese practice runtime"

security find-generic-password -s chinese-character-practice-openai -w | \
  gcloud secrets create openai-api-key --data-file=-

gcloud secrets add-iam-policy-binding openai-api-key \
  --member="serviceAccount:${HANZI_RUNTIME_SA}@${HANZI_PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud auth configure-docker "${HANZI_REGION}-docker.pkg.dev"
```

To rotate the key later, add a new secret version and update the version number in `--set-secrets` below:

```sh
security find-generic-password -s chinese-character-practice-openai -w | \
  gcloud secrets versions add openai-api-key --data-file=-
```



### Build, push, and deploy

Cloud Run needs a `linux/amd64` image, so build for that platform even on Apple Silicon. Image reading needs about 1.3 GB of memory while it runs, hence `--memory=2Gi`; a full page can take over a minute on Cloud Run CPUs, hence `--timeout=300`. Increase the tag (`v2`, `v3`, …) for each release.

```sh
export HANZI_IMAGE="${HANZI_REGION}-docker.pkg.dev/${HANZI_PROJECT_ID}/${HANZI_REPO}/${HANZI_SERVICE}:v2"

docker buildx build --platform linux/amd64 --load -t "$HANZI_IMAGE" .
docker push "$HANZI_IMAGE"

gcloud run deploy "$HANZI_SERVICE" \
  --image="$HANZI_IMAGE" \
  --region="$HANZI_REGION" \
  --allow-unauthenticated \
  --max=1 \
  --memory=2Gi \
  --cpu=2 \
  --timeout=300 \
  --concurrency=8 \
  --service-account="${HANZI_RUNTIME_SA}@${HANZI_PROJECT_ID}.iam.gserviceaccount.com" \
  --set-secrets="OPENAI_API_KEY=openai-api-key:1"
```

Cloud Run sets `PORT` automatically.