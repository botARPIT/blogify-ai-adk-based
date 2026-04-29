#!/bin/bash
# PostgreSQL backup script for Blogify AI
# Usage: ./backup-db.sh [retention_days]

set -e

RETENTION_DAYS="${1:-7}"
BACKUP_DIR="/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/blogify_${TIMESTAMP}.sql.gz"

DB_NAME="${POSTGRES_DB:-blogify}"
DB_USER="${POSTGRES_USER:-blogify}"
DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5432}"

echo "Starting database backup..."
echo "Database: ${DB_NAME}"
echo "Host: ${DB_HOST}:${DB_PORT}"

pg_dump -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" | \
    gzip > "${BACKUP_FILE}"

if [ -f "${BACKUP_FILE}" ]; then
    SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
    echo "Backup created: ${BACKUP_FILE} (${SIZE})"

    echo "Cleaning up backups older than ${RETENTION_DAYS} days..."
    find "${BACKUP_DIR}" -name "blogify_*.sql.gz" -mtime "+${RETENTION_DAYS}" -delete

    echo "Backup complete!"
else
    echo "ERROR: Backup file not created"
    exit 1
fi