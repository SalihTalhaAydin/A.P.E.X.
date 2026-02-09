# Apex Brain

Personal AI assistant with persistent memory, smart home control, and semantic knowledge. Runs as a Home Assistant Add-on on a dedicated HAOS mini PC.

## Quick Start (Local Development)

```bash
cd apex

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env with your API keys and HA connection info

# Run the server
python -m brain.server
```

Test it:
```bash
# Health check
curl http://localhost:8080/health

# Chat
curl -X POST http://localhost:8080/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello Apex"}'
```

## Deploy as HA Add-on

1. Push this repo to GitHub
2. In HA: Settings > Add-ons > Add-on Store > three dots > Repositories > add your GitHub repo URL
3. Install "Apex Brain" from the store
4. Configure API keys in the add-on settings panel
5. Start the add-on

## Connect to HA Voice Pipeline

1. Install "Extended OpenAI Conversation" via HACS
2. Add the integration: Settings > Integrations > Add > Extended OpenAI Conversation
3. Set Base URL: `http://LOCAL_ADDON_HOSTNAME:8080/v1`
4. Set API Key: `apex` (dummy value)
5. Create a voice assistant: Settings > Voice Assistants > Add
6. Select the Extended OpenAI Conversation agent
7. Set wake word to "Hey Apex" (custom openWakeWord model, or use "Hey Jarvis" until trained)

## Architecture

- **brain/**: FastAPI server, conversation orchestrator, config
- **memory/**: Conversation history, knowledge store (embeddings), fact extraction, context builder
- **tools/**: Smart home, knowledge, datetime, calendar (decorator-based, auto-discovered)
- **ha_addon/**: Dockerfile, config.yaml, run.sh for HA deployment

## Adding New Tools

Create a file in `tools/`, add the `@tool` decorator:

```python
# tools/weather.py
from tools.base import tool

@tool(description="Get current weather for a location")
async def get_weather(location: str) -> str:
    # your code here
    return "72F and sunny"
```

Restart the server. Done.

## Swapping AI Models

Change `LITELLM_MODEL` in your .env or HA add-on config:
- `gpt-4o`, `gpt-4o-mini`, `gpt-4-turbo`
- `claude-sonnet-4-20250514`, `claude-opus-4-20250514`
- `gemini/gemini-2.0-flash`
- Any model LiteLLM supports: https://docs.litellm.ai/docs/providers
