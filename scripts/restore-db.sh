#!/usr/bin/env bash
# Restore a Dispatch OS Postgres backup.
# Usage:  ./scripts/restore-db.sh ./backups/dispatch_os_2026-04-23_03-00-00.sql.gz

set -euo pipefail

if [ -z "${1:-}" ]; then
  echo "Usage: $0 <backup-file.sql.gz>" >&2
  exit 1
fi

BACKUP="$1"
if [ ! -f "$BACKUP" ]; then
  echo "Backup file not found: $BACKUP" >&2
  exit 1
fi

cd "$(dirname "$0")/.."

echo "⚠  This will DROP and REPLACE the dispatch_os database."
read -rp "Type 'yes' to continue: " confirm
[ "$confirm" = "yes" ] || { echo "Aborted."; exit 1; }

echo "[restore] dropping existing database..."
docker compose exec -T db psql -U dispatch -d postgres -c "DROP DATABASE IF EXISTS dispatch_os;"
docker compose exec -T db psql -U dispatch -d postgres -c "CREATE DATABASE dispatch_os OWNER dispatch;"

echo "[restore] importing $BACKUP..."
gunzip -c "$BACKUP" | docker compose exec -T db psql -U dispatch -d dispatch_os

echo "[restore] running migrations..."
docker compose exec -T api python manage.py migrate --noinput

echo "[restore] done."
