#!/bin/bash
set -e

echo "Slowbooks Pro 2026 — Starting up..."

# Wait for PostgreSQL (max 30 seconds).
# Skippable: on Kubernetes the scheduler and readiness probes handle this,
# and a pod that exits is restarted anyway — the wait loop just delays the
# first CrashLoopBackOff without adding information.
if [ "${WAIT_FOR_POSTGRES:-1}" = "1" ]; then
    echo "Waiting for PostgreSQL..."
    PG_WAIT=0
    until pg_isready -h "${PGHOST:-postgres}" -p "${PGPORT:-5432}" -U "${PGUSER:-bookkeeper}" -q; do
        PG_WAIT=$((PG_WAIT + 1))
        if [ "$PG_WAIT" -ge 30 ]; then
            echo "ERROR: PostgreSQL did not become ready within 30 seconds."
            exit 1
        fi
        sleep 1
    done
    echo "PostgreSQL is ready."
fi

# Migrations + seed.
#
# Skippable because this is per-CONTAINER, and that only happens to be
# safe when there is exactly one. Compose runs a single app container, so
# the default stays 1. On Kubernetes every replica would run
# `alembic upgrade head` simultaneously on rollout; they contend for the
# same version row and the losers can exit non-zero mid-rollout. There,
# set RUN_MIGRATIONS=0 on the Deployment and run the migrate Job instead
# (k8s/migrate-job.yaml), which runs exactly once per deploy.
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
    echo "Running database migrations..."
    alembic upgrade head

    # Seed chart of accounts (idempotent — skips if accounts exist)
    echo "Seeding database..."
    python scripts/seed_database.py
else
    echo "RUN_MIGRATIONS=0 — skipping migrations/seed (expecting a migrate Job)."
fi

# Boot-time wiring self-check. Catches the rare case where the deployed
# Python image and JS bundle drifted (someone manually swapped files in
# a running container, or a local-dev container is running against a
# checked-out branch that's stale) BEFORE traffic hits.
#
# Only runs when pytest is installed — the production image ships with
# requirements.txt only (no pytest), so this is a no-op there; CI already
# gated the same check before the image was built. The check matters
# most for local dev / debug containers built off requirements-dev.txt.
#
# Set SKIP_BOOT_SELFCHECK=1 to bypass even when pytest is available.
if [ -z "${SKIP_BOOT_SELFCHECK:-}" ] && python -c "import pytest" 2>/dev/null; then
    echo "Boot self-check: SPA <-> backend wiring..."
    if ! python -m pytest tests/test_wiring.py -q --no-header 2>&1 | tail -5; then
        echo "ERROR: wiring self-check failed. Set SKIP_BOOT_SELFCHECK=1 to override." >&2
        exit 1
    fi
fi

echo "Starting Slowbooks Pro 2026 on port ${APP_PORT:-3001}..."
# Multi-worker production mode.
# uvloop + httptools come from uvicorn[standard], explicit for clarity.
# APP_WORKERS defaults to 2 (tunable via docker-compose env or .env).
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${APP_PORT:-3001}" \
    --workers "${APP_WORKERS:-2}" \
    --loop uvloop \
    --http httptools \
    --access-log
