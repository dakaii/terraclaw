#!/bin/sh
set -e

DB_PATH="${ZEROCLAW_MEMORY_DB:-/data/workspace/memory.db}"
mkdir -p "$(dirname "$DB_PATH")"
mkdir -p /data/workspace/config

# Generate basic config.toml if it doesn't exist
# This is a simple template to wire environment variables into ZeroClaw.
CONFIG_FILE="/data/workspace/config/config.toml"
if [ ! -f "$CONFIG_FILE" ]; then
  cat <<EOF > "$CONFIG_FILE"
[agent]
name = "Terraclaw"
description = "Private AI Agent"

[providers.default]
type = "openai"
base_url = "${OPENAI_BASE_URL}"
api_key = "dummy"
model = "deepseek"

[channels.telegram]
enabled = ${TELEGRAM_ENABLED:-false}
bot_token = "${TELEGRAM_BOT_TOKEN}"

[channels.whatsapp]
enabled = ${WHATSAPP_ENABLED:-false}

[tools.web_search]
provider = "${SEARCH_PROVIDER:-tavily}"
api_key = "${TAVILY_API_KEY:-${SERPER_API_KEY}}"
EOF
fi

if [ -n "${LITESTREAM_BUCKET:-}" ]; then
  REPLICA_URL="gs://${LITESTREAM_BUCKET}/zeroclaw-memory"
  litestream restore -if-not-exists -o "$DB_PATH" "$REPLICA_URL" || true
  litestream replicate "$DB_PATH" "$REPLICA_URL" &
fi

PORT="${PORT:-8080}"
# Point ZeroClaw to the generated config
exec /usr/local/bin/zeroclaw daemon --host 0.0.0.0 -p "$PORT" --config "$CONFIG_FILE"
