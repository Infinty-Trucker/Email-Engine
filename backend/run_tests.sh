#!/usr/bin/env bash
# Run the Email-Engine (Dispatch OS) test suite in a throwaway container built
# from the already-built `it-email-engine-api` image, with host source mounted.
#
# Uses config.test_settings (sqlite in-memory, locmem cache, non-eager Celery)
# so no Postgres/Redis is required. Pass app labels / test paths as args, e.g.
#
#     ./run_tests.sh                       # whole suite
#     ./run_tests.sh apps.users.tests      # one app
#
set -euo pipefail
cd "$(dirname "$0")"

IMAGE="${EE_TEST_IMAGE:-it-email-engine-api}"

exec docker run --rm \
  -v "$PWD":/app -w /app \
  -e SECRET_KEY="${SECRET_KEY:-test-secret-key}" \
  -e DEBUG=0 \
  -e ALLOWED_HOSTS="testserver,localhost" \
  "$IMAGE" \
  python manage.py test --settings=config.test_settings "$@"
