# Apex Brain

Personal AI assistant with persistent memory, smart home control, and semantic knowledge. Runs as a Home Assistant **App** (formerly "add-on") on a dedicated HAOS mini PC.

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

## Deploy as a Home Assistant App (add-on)

**Where to find it:** In Home Assistant, "add-ons" are now called **Apps**. You manage them in **Settings → Apps** (or in some versions **Settings → Add-ons**). You must be on **Home Assistant OS** (e.g. a dedicated mini PC running HAOS); Docker/Core-only installs do not have Apps.

**Steps:**

1. Push this repo to GitHub.
2. In Home Assistant: open **Settings** (gear icon in the sidebar), then **Apps** (or **Add-ons**).  
   - If you don’t see **Apps**, you may be on a non-OS install (no add-ons support).
3. Open the **App store** / **Install app** tab (or the store icon).  
   - Use the **⋮** (three dots) or **Add repository** (or similar) and paste:  
     `https://github.com/SalihTalhaAydin/A.P.E.X.`  
   - Click **Add**. The Apex Brain repository should appear in the store.
4. Find **Apex Brain** in the list, open it, then **Install**.
5. After installation: open **Apex Brain** → **Configuration**, set your API keys (and model if needed), **Save**, then **Start**.
6. Check **Log** to confirm it’s running (e.g. "Apex Brain is online").

## Connect to HA Voice Pipeline

1. Install "Extended OpenAI Conversation" via HACS
2. Add the integration: Settings > Integrations > Add > Extended OpenAI Conversation
3. Set Base URL: `http://LOCAL_ADDON_HOSTNAME:8080/v1`
4. Set API Key: `apex` (dummy value)
5. Create a voice assistant: Settings > Voice Assistants > Add
6. Select the Extended OpenAI Conversation agent
7. Set wake word (e.g. "Hey Jarvis" or "Okay Nabu") on your Voice PE devices

## Architecture

- **brain/**: FastAPI server, conversation orchestrator, config
- **memory/**: Conversation history, knowledge store (sqlite-vec), fact extraction, context builder
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
    return "72°F and sunny"
```

Restart the server. Done.

## Swapping AI Models

Change `LITELLM_MODEL` in your .env or HA add-on config:
- `gpt-4o`, `gpt-4o-mini`, `gpt-4-turbo`
- `claude-sonnet-4-20250514`, `claude-opus-4-20250514`
- `gemini/gemini-2.0-flash`
- Any model LiteLLM supports: https://docs.litellm.ai/docs/providers
