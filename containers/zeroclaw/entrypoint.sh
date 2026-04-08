#!/bin/sh
set -e

DB_PATH="${ZEROCLAW_MEMORY_DB:-/data/workspace/memory.db}"
mkdir -p "$(dirname "$DB_PATH")"

if [ -n "${LITESTREAM_BUCKET:-}" ]; then
  REPLICA_URL="gs://${LITESTREAM_BUCKET}/zeroclaw-memory"
  litestream restore -if-not-exists -o "$DB_PATH" "$REPLICA_URL" || true
  litestream replicate "$DB_PATH" "$REPLICA_URL" &
fi

# Cloud Run sets PORT; bind gateway for HTTP health + dashboard.
PORT="${PORT:-8080}"
exec /usr/local/bin/zeroclaw daemon --host 0.0.0.0 -p "$PORT"
