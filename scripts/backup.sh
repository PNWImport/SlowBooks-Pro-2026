#!/bin/bash
set -eo pipefail
# ============================================================================
# Server Edition backup: pg_dump the company database to a dated file.
# ============================================================================

BACKUP_DIR="${BACKUP_DIR:-$HOME/bookkeeper-backups}"
DB_NAME="${DB_NAME:-bookkeeper}"
DB_USER="${DB_USER:-bookkeeper}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/bookkeeper_${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "Slowbooks Pro 2026 — Backup Utility"
echo "===================================="
echo "Database: $DB_NAME"
echo "Backup to: $BACKUP_FILE"
echo ""

if pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$BACKUP_FILE"; then
    SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo "Backup completed: $BACKUP_FILE ($SIZE)"

    # Keep only last 30 backups
    find "$BACKUP_DIR" -maxdepth 1 -type f -name 'bookkeeper_*.sql.gz' \
        -printf '%T@ %p\0' | sort -z -nr | tail -z -n +31 | cut -z -d ' ' -f 2- \
        | xargs -0 -r rm -f --
else
    echo "ERROR: Backup failed!"
    rm -f "$BACKUP_FILE"
    exit 1
fi
