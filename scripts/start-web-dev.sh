#!/usr/bin/env bash
set -e

# Floppy Web Distrobox Development Environment Starter
echo "Starting Floppy Web development environment..."

# 1. Resolve project root reliably
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 2. Setup cleanup trap for reliable shutdown
cleanup() {
    echo -e "\nShutting down Floppy Web environment..."
    kill $CELERY_PID1 $CELERY_PID2 $TAILWIND_PID 2>/dev/null || true
    redis-cli -p 6380 shutdown 2>/dev/null || true
}
trap cleanup EXIT

# 3. Start Redis on isolated port (6380) in the background
echo "Starting Redis on port 6380..."
redis-server --port 6380 --daemonize yes --save "" --appendonly no

# 4. Source the web-dev environment variables
if [ -f "$PROJECT_ROOT/.env.web-dev" ]; then
    set -a
    source "$PROJECT_ROOT/.env.web-dev"
    set +a
fi

cd "$PROJECT_ROOT/src" || exit 1

# 5. Ensure the virtual environment is activated
if [ -d "$PROJECT_ROOT/.venv" ]; then
    source "$PROJECT_ROOT/.venv/bin/activate"
fi

# 6. Start Celery in the background
echo "Starting Celery workers..."
celery -A config worker --queues interactive --hostname celery-interactive@%h --loglevel INFO &
CELERY_PID1=$!
celery -A config worker --queues celery --beat --scheduler django --hostname celery@%h --loglevel INFO &
CELERY_PID2=$!

# 7. Start Tailwind in the background (using v3 syntax per AGENTS.md)
echo "Starting Tailwind watcher..."
npx tailwindcss -i ./static/css/input.css -o ./static/css/main.css --watch &
TAILWIND_PID=$!

echo "Starting Django Development Server on port 8080..."
python manage.py runserver 8080
