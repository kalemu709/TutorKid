FROM node:24-slim AS build
WORKDIR /src

COPY package.json package-lock.json ./
RUN npm ci

COPY app.jsx ./
RUN npm run build

# paddlepaddle segfaults on linux/arm64, and 3.3.x fails on x86 oneDNN; 3.2.2 on amd64 works.
FROM --platform=linux/amd64 python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
    PORT=8080
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Keep the model names in sync with OCR_DETECTION_MODEL and OCR_RECOGNITION_MODEL in server.py.
RUN python -c "from paddleocr import TextDetection, TextRecognition; TextDetection(model_name='PP-OCRv5_server_det'); TextRecognition(model_name='PP-OCRv5_server_rec')"

COPY server.py index.html ./
COPY --from=build /src/app.js ./

EXPOSE 8080
CMD ["python", "server.py"]
