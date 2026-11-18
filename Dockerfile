# Catalejo Deal Desk en un solo servicio: el backend FastAPI sirve la API y el frontend (exportado como sitio
# estático) en la misma URL. Lo usa render.yaml; también funciona en cualquier plataforma que ejecute Docker.

# --- Etapa 1: compilar el frontend (Next.js -> HTML/JS estático en /web/out) -------------------------------------
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
ENV STATIC_EXPORT=1 NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# --- Etapa 2: backend Python que sirve todo ----------------------------------------------------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/ ./
COPY --from=web /web/out ./static
RUN useradd --create-home catalejo && chown -R catalejo /app
USER catalejo
ENV FRONTEND_DIR=/app/static \
    STORAGE_DIR=/tmp/catalejo-storage \
    PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
