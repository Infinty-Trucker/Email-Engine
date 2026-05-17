#!/bin/bash
# Dispatch OS — hot-update script
# Copies changed files into running containers without a full rebuild
# Usage:
#   bash update.sh          — update everything
#   bash update.sh backend  — backend only (Python files + restart)
#   bash update.sh frontend — frontend only (build + copy to nginx)

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MODE=${1:-all}

echo "=== Dispatch OS Hot Update ==="
echo "Mode: $MODE"
echo ""

# ── Backend ────────────────────────────────────────────────────────────────────
update_backend() {
  echo "📦 Copying backend files..."

  FILES=(
    "backend/apps/mailboxes/tasks.py:api:/app/apps/mailboxes/tasks.py"
    "backend/apps/mailboxes/tasks.py:worker:/app/apps/mailboxes/tasks.py"
    "backend/apps/mailboxes/webhook_urls.py:api:/app/apps/mailboxes/webhook_urls.py"
    "backend/apps/settings/views.py:api:/app/apps/settings/views.py"
    "backend/apps/settings/views.py:worker:/app/apps/settings/views.py"
    "backend/apps/settings/gmail_oauth.py:api:/app/apps/settings/gmail_oauth.py"
    "backend/apps/settings/gmail_oauth.py:worker:/app/apps/settings/gmail_oauth.py"
    "backend/apps/conversations/views.py:api:/app/apps/conversations/views.py"
    "backend/apps/conversations/serializers.py:api:/app/apps/conversations/serializers.py"
    "backend/apps/conversations/tasks.py:api:/app/apps/conversations/tasks.py"
    "backend/apps/conversations/tasks.py:worker:/app/apps/conversations/tasks.py"
    "backend/apps/conversations/urls.py:api:/app/apps/conversations/urls.py"
    "backend/apps/conversations/models.py:api:/app/apps/conversations/models.py"
    "backend/apps/users/views.py:api:/app/apps/users/views.py"
    "backend/apps/users/serializers.py:api:/app/apps/users/serializers.py"
    "backend/apps/users/models.py:api:/app/apps/users/models.py"
    "backend/config/settings.py:api:/app/config/settings.py"
    "backend/config/settings.py:worker:/app/config/settings.py"
    "backend/config/urls.py:api:/app/config/urls.py"
  )

  for entry in "${FILES[@]}"; do
    src="${entry%%:*}"
    rest="${entry#*:}"
    container="${rest%%:*}"
    dest="${rest#*:}"
    if [ -f "$SCRIPT_DIR/$src" ]; then
      docker compose cp "$SCRIPT_DIR/$src" "$container:$dest" 2>/dev/null && echo "  ✓ $src → $container" || echo "  ⚠ skipped $src ($container not running?)"
    fi
  done

  echo ""
  echo "🗄  Running migrations..."
  docker compose exec api python manage.py migrate --noinput 2>&1 | grep -E "Apply|OK|No migrations|error" || true

  echo ""
  echo "🔄 Restarting api, worker, beat..."
  docker compose restart api worker beat
  
  echo ""
  echo "⏳ Waiting for api to be ready..."
  sleep 5
  curl -s http://localhost:8000/api/system/health/ > /dev/null && echo "✓ API is up" || echo "⚠ API not responding yet — check: docker compose logs api"
}

# ── Frontend ───────────────────────────────────────────────────────────────────
update_frontend() {
  echo "⚛️  Building frontend..."
  
  cd "$SCRIPT_DIR/frontend"
  
  # Install deps if needed
  if [ ! -d "node_modules" ]; then
    echo "  Installing npm packages..."
    npm install --silent
  fi
  
  # Build
  npm run build 2>&1 | tail -3
  
  echo ""
  echo "📤 Copying built files to nginx container..."
  docker compose cp "$SCRIPT_DIR/frontend/dist/." frontend:/usr/share/nginx/html/
  docker compose cp "$SCRIPT_DIR/frontend/nginx.conf" frontend:/etc/nginx/conf.d/default.conf
  
  echo "🔄 Reloading nginx..."
  docker compose exec frontend nginx -s reload
  
  echo "✓ Frontend updated — http://localhost:3000"
}

# ── Run ────────────────────────────────────────────────────────────────────────
case "$MODE" in
  backend)  update_backend ;;
  frontend) update_frontend ;;
  *)        update_backend; echo ""; update_frontend ;;
esac

echo ""
echo "=== Done ==="
