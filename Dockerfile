# ── Base image ────────────────────────────────────────────────────────────────
FROM python:3.11-slim

# Set environment defaults
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# ── System dependencies ───────────────────────────────────────────────────────
# WeasyPrint: libpango, libcairo, libgdk-pixbuf (Cairo/Pango for PDF rendering)
# python-magic: libmagic1
# gcc for building some Python C extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    libmagic1 \
    gcc \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ── App directory ─────────────────────────────────────────────────────────────
WORKDIR /app

# ── Python dependencies ───────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# ── Application code ──────────────────────────────────────────────────────────
COPY . .

# ── Runtime ───────────────────────────────────────────────────────────────────
EXPOSE 5000

# Default command (overridden per-service in docker-compose.yml)
CMD ["flask", "run", "--host=0.0.0.0", "--port=5000"]
