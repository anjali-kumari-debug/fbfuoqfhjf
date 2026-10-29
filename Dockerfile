# One image: build the React app with Node, then serve it and the API with FastAPI.
# Build:  docker build -t wind-forecast-desk .
# Run:    docker run --rm -p 8090:8000 wind-forecast-desk   ->  http://localhost:8090

# ---- Stage 1: build the frontend into static files (frontend/dist) ----
FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Python runtime with the API, snapshot data and built frontend ----
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

# Same layout as the repo, so the code finds data/processed and frontend/dist.
COPY backend/ backend/
COPY data/ data/
COPY --from=frontend /build/dist/ frontend/dist/

# Optional: build-time retrieval instead of using committed processed data.
# docker build --build-arg DECISION_MONTH=2026-01 .
# Data is fetched once while the image is built, never per dashboard request.
ARG DECISION_MONTH=""
RUN if [ -n "$DECISION_MONTH" ]; then python -m backend.app.fetch_data --decision-month "$DECISION_MONTH"; fi \
 && test -f data/processed/manifest.json \
 || (echo "No data/processed found: commit it or build with --build-arg DECISION_MONTH=YYYY-MM" && exit 1)

# Run as an unprivileged user.
RUN useradd --create-home appuser
USER appuser

WORKDIR /app/backend
# Platforms that set $PORT are respected; default to 8000 elsewhere.
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
