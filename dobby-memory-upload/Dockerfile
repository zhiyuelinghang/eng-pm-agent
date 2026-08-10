# Dobby Web — Gradio Chat Interface
# Build: docker build -t dobby-web:local .
# Run:   docker run -p 7860:7860 --env-file .env dobby-web:local

FROM python:3.12-slim

LABEL org.dobby.service="web"
LABEL org.dobby.version="1.0.0"

WORKDIR /app

# ── System dependencies ──
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ── Python dependencies (cached layer) ──
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Application code ──
COPY . .

# ── Create data directories ──
RUN mkdir -p /app/data/logs

# ── Health check ──
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -sf http://localhost:7860 || exit 1

EXPOSE 7860

CMD ["python", "app.py"]
