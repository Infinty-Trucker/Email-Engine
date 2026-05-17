#!/usr/bin/env bash
# Postgres backup for Dispatch OS.
# Writes a timestamped, gzip-compressed dump to ./backups/.
# Add to cron:  0 3 * * * cd /path/to/dispatch-os && ./scripts/backup-db.sh

set -euo pipefail

cd "$(dirname "$0")/.."

BACKUP_DIR="./backups"
mkdir -p "$BACKUP_DIR"

TIMESTAMP="$(date +%Y-%m-%d_%H-%M-%S)"
OUT="$BACKUP_DIR/dispatch_os_${TIMESTAMP}.sql.gz"

echo "[backup] dumping Postgres → $OUT"
docker compose exec -T db pg_dump -U dispatch -d dispatch_os | gzip -9 > "$OUT"

# Keep only the last 14 daily backups
find "$BACKUP_DIR" -name "dispatch_os_*.sql.gz" -mtime +14 -delete

SIZE="$(du -h "$OUT" | awk '{print $1}')"
echo "[backup] done — $SIZE"
