#!/usr/bin/with-contenv bash
# Apex Brain - HA Add-on startup script
# Reads configuration from /data/options.json and starts the server.
# Uses with-contenv to inherit S6 container environment (SUPERVISOR_TOKEN, etc.)

echo "========================================"
echo "  Apex Brain Add-on Starting..."
echo "========================================"

# Read add-on options from /data/options.json using jq
export LITELLM_MODEL=$(jq -r '.litellm_model' /data/options.json)
export OPENAI_API_KEY=$(jq -r '.openai_api_key' /data/options.json)
export ANTHROPIC_API_KEY=$(jq -r '.anthropic_api_key' /data/options.json)
export EMBEDDING_MODEL=$(jq -r '.embedding_model' /data/options.json)
export FACT_EXTRACTION_MODEL=$(jq -r '.fact_extraction_model' /data/options.json)
export RECENT_TURNS=$(jq -r '.recent_turns' /data/options.json)
export MAX_FACTS_IN_CONTEXT=$(jq -r '.max_facts_in_context' /data/options.json)

# Database path (persistent volume)
export DB_PATH="/data/apex.db"

# HA connection (automatic inside add-on)
export HA_URL="http://supervisor/core"
# SUPERVISOR_TOKEN is injected by HA Supervisor via S6 container environment

echo "  Model: ${LITELLM_MODEL}"
echo "  Database: ${DB_PATH}"
if [ -n "$SUPERVISOR_TOKEN" ]; then
    echo "  SUPERVISOR_TOKEN: set (${#SUPERVISOR_TOKEN} chars)"
else
    echo "  WARNING: SUPERVISOR_TOKEN is NOT set!"
fi
echo "========================================"

# Start the server
cd /app
exec python -m uvicorn brain.server:app --host 0.0.0.0 --port 8080 --log-level info
