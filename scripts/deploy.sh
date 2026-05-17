#!/usr/bin/env bash
# Deploy/redeploy Dispatch OS in production.
# Pulls latest code, rebuilds, runs migrations, restarts services with zero downtime where possible.

set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "Missing .env — copy .env.production.example to .env and fill in values." >&2
  exit 1
fi

COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"

echo "[deploy] pulling code..."
git pull --ff-only

echo "[deploy] building images..."
$COMPOSE build api worker worker-send beat frontend

echo "[deploy] taking pre-deploy DB backup..."
./scripts/backup-db.sh

echo "[deploy] running migrations..."
$COMPOSE run --rm api python manage.py migrate --noinput

echo "[deploy] restarting services..."
$COMPOSE up -d --remove-orphans

echo "[deploy] waiting for API health..."
for i in {1..30}; do
  if $COMPOSE exec -T api curl -sf http://localhost:8000/api/auth/csrf/ >/dev/null 2>&1; then
    echo "[deploy] API is healthy."
    break
  fi
  sleep 2
done

echo "[deploy] done. Tail logs with:  $COMPOSE logs -f --tail=50"
