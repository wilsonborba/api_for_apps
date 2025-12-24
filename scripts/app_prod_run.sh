#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR/.."

source .venv/bin/activate
export PYTHONPATH="$(pwd)"

HOST=${HOST:-0.0.0.0}
PORT=${PORT:-8000}
WORKERS=${WORKERS:-4}

echo "Starting Gunicorn + Uvicorn workers on ${HOST}:${PORT} with ${WORKERS} workers…"

exec gunicorn \
  "main:app" \
  -k uvicorn.workers.UvicornWorker \
  -b "${HOST}:${PORT}" \
  -w "${WORKERS}" \
  --log-level info \
  --access-logfile - \
  --error-logfile - \
  --forwarded-allow-ips="*"

