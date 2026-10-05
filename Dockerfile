# ============================================================================
# Slowbooks Pro 2026 — Docker Image
# Runs on Linux, macOS, and Windows via Docker Desktop
# ============================================================================

FROM python:3.13-alpine AS base

# ---- Python 3.13 performance env ----
# Don't write .pyc at runtime (we pre-compile at build time below)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONHASHSEED=random \
    PYTHONMALLOC=pymalloc

# System dependencies for WeasyPrint (PDF generation), PostgreSQL backup and
# OCR. Alpine's supported packages materially reduce the runtime image CVE
# surface while retaining the same cairo/pango, Poppler and Tesseract tools.
RUN apk upgrade --no-cache \
    && apk add --no-cache \
    cairo \
    pango \
    fontconfig \
    ttf-dejavu \
    gdk-pixbuf \
    libffi \
    libjpeg-turbo \
    libpng \
    libxml2 \
    libxslt \
    postgresql17-client \
    tesseract-ocr \
    tesseract-ocr-data-eng \
    poppler-utils

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt \
    # pip is a build tool, not an application runtime dependency. Removing it
    # also removes its vendored packages from the release image's CVE surface.
    && rm -rf /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13 \
        /usr/local/lib/python3.13/site-packages/pip \
        /usr/local/lib/python3.13/site-packages/pip-*.dist-info \
        /usr/local/lib/python3.13/ensurepip

COPY . .

# Pre-compile bytecode for every .py in the image (app + site-packages).
# At runtime PYTHONDONTWRITEBYTECODE=1 prevents re-writes, so this is pure startup win.
RUN python -m compileall -q -j 0 /usr/local/lib/python3.13/site-packages /app || true

RUN chmod +x docker-entrypoint.sh

# The folders docker compose mounts volumes on (backups, and the uploads
# folder releases before 2.18 wrote) exist here, owned by the app's user:
# Docker gives an empty named volume the owner of the image's folder, and a
# folder the image lacks becomes a volume owned by root, which the app can't
# write. Every backup failed with "Permission denied", and so did every
# upload before 2.18. Those failures left an existing install's volumes
# empty, so they take the right owner when the new image starts.
RUN adduser -D -u 1000 slowbooks \
    && mkdir -p /app/backups /app/app/static/uploads \
    && chown -R slowbooks:slowbooks /app
USER slowbooks

EXPOSE 3001

# Liveness probe — hits the unauthenticated /health endpoint. The script treats
# the production HTTP-to-HTTPS redirect as healthy without following it: TLS
# terminates at the external proxy, so there is no HTTPS listener in this image.
# Marks the container unhealthy after 3 consecutive failures (90s),
# which is short enough for orchestrators to restart promptly and long
# enough to ride out a single GC pause or migration replay.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python scripts/docker_healthcheck.py

ENTRYPOINT ["./docker-entrypoint.sh"]
