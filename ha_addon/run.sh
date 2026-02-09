#!/usr/bin/with-contenv bashio
# Apex Brain - HA Add-on startup script
# Reads configuration from /data/options.json and starts the server.

echo "========================================"
echo "  Apex Brain Add-on Starting..."
echo "========================================"

# Read add-on options and export as environment variables
export LITELLM_MODEL=$(bashio::config 'litellm_model')
export OPENAI_API_KEY=$(bashio::config 'openai_api_key')
export ANTHROPIC_API_KEY=$(bashio::config 'anthropic_api_key')
export EMBEDDING_MODEL=$(bashio::config 'embedding_model')
export FACT_EXTRACTION_MODEL=$(bashio::config 'fact_extraction_model')
export RECENT_TURNS=$(bashio::config 'recent_turns')
export MAX_FACTS_IN_CONTEXT=$(bashio::config 'max_facts_in_context')

# Database path (persistent volume)
export DB_PATH="/data/apex.db"

# HA connection (automatic inside add-on)
export HA_URL="http://supervisor/core"
# SUPERVISOR_TOKEN is auto-injected by HA Supervisor

echo "  Model: ${LITELLM_MODEL}"
echo "  Database: ${DB_PATH}"
echo "========================================"

# Start the server
cd /app
exec python -m uvicorn brain.server:app --host 0.0.0.0 --port 8080 --log-level info
