# Dispatch OS

Multi-MC freight dispatch platform. One command to run everything.

## Requirements
- Docker Desktop (Mac/Windows) or Docker + Docker Compose (Linux)
- That's it

## Run

```bash
# 1. Unzip and enter folder
unzip dispatch_os.zip
cd dispatch_os

# 2. Start everything
docker compose up -d --build

# 3. Create your admin user
docker compose exec api python manage.py createsuperuser

# 4. Open the app
open http://localhost:3000
```

## URLs
| | |
|---|---|
| App | http://localhost:3000 |
| API | http://localhost:8000 |
| Django Admin | http://localhost:8000/admin |

## Login
The app shows a demo login screen with 5 sample users.
To use real users: log in at http://localhost:8000/admin and create users there.

## Add your API keys (optional)
Edit the `.env` file and add:
- `ANTHROPIC_API_KEY` — enables AI email classification and draft replies
- `SLACK_BOT_TOKEN` + channel IDs — enables Slack alerts
- `GOOGLE_*` — enables real Gmail integration

Then restart: `docker compose restart api worker`

## Stop
```bash
docker compose down
```

## Wipe everything and start fresh
```bash
docker compose down -v
docker compose up -d --build
```

## Logs
```bash
docker compose logs -f          # all services
docker compose logs -f api      # Django only
docker compose logs -f worker   # Celery only
```
# Email-Engine
# Email-Engine
# Email-Engine
