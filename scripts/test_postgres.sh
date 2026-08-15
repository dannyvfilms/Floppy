#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

container_name="floppy-pr-postgres-${BASHPID}"
postgres_test_port="${POSTGRES_TEST_PORT:-55432}"
cleanup() {
  sudo docker rm -f "$container_name" >/dev/null 2>&1 || true
}
trap cleanup EXIT

sudo docker run --detach --name "$container_name" \
  --publish "127.0.0.1:${postgres_test_port}:5432" \
  --env POSTGRES_DB=floppy_test \
  --env POSTGRES_USER=floppy_test \
  --env POSTGRES_PASSWORD=floppy_test \
  postgres:16-alpine >/dev/null

until sudo docker exec "$container_name" pg_isready -U floppy_test -d floppy_test >/dev/null 2>&1; do
  sleep 1
done

PATH="$(pwd)/.venv/bin:${PATH}"
SECRET="${SECRET:-postgres-test-secret}" \
LOG_DIR="${LOG_DIR:-/tmp/floppy-postgres-test-logs}" \
DB_HOST=127.0.0.1 \
DB_NAME=floppy_test \
DB_USER=floppy_test \
DB_PASSWORD=floppy_test \
DB_PORT="$postgres_test_port" \
DB_POOL_ENABLED=false \
  python src/manage.py test \
    "${@:-app.tests.test_grouped_anime_postgres}" \
    --parallel 1
