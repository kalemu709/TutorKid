FROM node:24-slim AS build
WORKDIR /src

COPY package.json package-lock.json ./
RUN npm ci

COPY app.jsx ./
RUN npm run build

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py index.html ./
COPY --from=build /src/app.js ./

EXPOSE 8080
CMD ["python", "server.py"]
