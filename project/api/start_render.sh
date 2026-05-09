#!/bin/sh
set -eu

export TARGET_APP_PORT="${TARGET_APP_PORT:-8080}"
export TARGET_HOST="${TARGET_HOST:-127.0.0.1}"
export TARGET_PORT="${TARGET_PORT:-8080}"
export ALLOW_EXTERNAL_TARGETS="${ALLOW_EXTERNAL_TARGETS:-false}"
export ALLOWED_TARGETS="${ALLOWED_TARGETS:-127.0.0.1,localhost}"
export PORT="${PORT:-10000}"
export FRONTEND_DIR="${FRONTEND_DIR:-/app/frontend}"

python3 /app/target_app.py &

echo "Waiting for local target on ${TARGET_HOST}:${TARGET_PORT}..."
for i in $(seq 1 30); do
  if curl -sf "http://${TARGET_HOST}:${TARGET_PORT}/health" >/dev/null; then
    echo "Target is ready."
    exec python3 /app/app.py
  fi
  sleep 1
done

echo "Target did not become ready in time." >&2
exit 1
