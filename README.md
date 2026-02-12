# Apex Brain

[![Test and Lint](https://github.com/SalihTalhaAydin/A.P.E.X./actions/workflows/test-and-lint.yml/badge.svg)](https://github.com/SalihTalhaAydin/A.P.E.X./actions/workflows/test-and-lint.yml)
[![Secrets Check](https://github.com/SalihTalhaAydin/A.P.E.X./actions/workflows/check-secrets.yml/badge.svg)](https://github.com/SalihTalhaAydin/A.P.E.X./actions/workflows/check-secrets.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

Personal AI assistant with persistent memory, smart home control, and semantic knowledge. Runs as a Home Assistant **App** (formerly "add-on") on a dedicated HAOS mini PC.

## Quick Start (Local Development)

```bash
cd apex_brain

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp ../.env.example .env
# Edit .env with your API keys and HA connection info.
# All secrets (API keys, HA URL/tokens, optional SSH) live in .env; see .env.example for variable names.

# Run the server
python -m brain.server
```

**Pre-commit (secret scanning):** Commits are scanned for secrets (tokens, API keys, etc.). Install once per clone:
```bash
pip install pre-commit
pre-commit install
```
If you don't install, CI will still run the same check on push.

**Tests:** From repo root: `PYTHONPATH=apex_brain python -m pytest apex_brain/tests -v`

Test it:
```bash
# Health check
curl http://localhost:8080/health

# Chat
curl -X POST http://localhost:8080/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello Apex"}'
```

## Deploy as a Home Assistant App (Add-on)

> **Prerequisite:** You must be on **Home Assistant OS** (e.g. a dedicated mini PC running HAOS). Docker/Core-only installs do not support add-ons.

### 1. Add the Repository

1. In Home Assistant: **Settings > Add-ons > Add-on Store**
2. Click **⋮** (three dots, top right) > **Repositories**
3. Paste: `https://github.com/SalihTalhaAydin/A.P.E.X.`
4. Click **Add**, then **Close**

### 2. Install the Add-on

1. Find **Apex Brain** in the store list (refresh if needed)
2. Click it, then **Install** (builds the Docker image, ~1-2 minutes)
3. Go to the **Configuration** tab
4. Set your `openai_api_key` (or `anthropic_api_key` depending on model)
5. Adjust `litellm_model` if desired (default: `gpt-4o`)
6. Click **Save**, then go to **Info** tab and click **Start**
7. Check the **Log** tab — you should see:
   ```
   Apex Brain Add-on Starting...
   Model: gpt-4o
   Uvicorn running on http://0.0.0.0:8080
   ```

### 3. Connect to HA Voice Pipeline

The add-on exposes an OpenAI-compatible API. To use it with HA's voice system:

1. **Install "Extended OpenAI Conversation"** custom component:
   - If you have HACS: HACS > Integrations > search "Extended OpenAI Conversation" > Download
   - Without HACS: SSH into HA and run:
     ```bash
     cd /tmp
     wget -q "https://github.com/jekalmin/extended_openai_conversation/archive/refs/heads/main.tar.gz" -O eoai.tar.gz
     tar xzf eoai.tar.gz
     mkdir -p /config/custom_components
     cp -r extended_openai_conversation-main/custom_components/extended_openai_conversation /config/custom_components/
     ```
     Then restart HA Core: **Settings > System > Restart**

2. **Add the integration**: Settings > Devices & Services > **+ Add Integration** > search "Extended OpenAI Conversation"
   - **API Key:** `apex` (dummy value — the add-on doesn't check it)
   - **Base URL:** `http://14fc29d6-apex-brain:8080/v1`

   > The hostname `14fc29d6-apex-brain` is assigned by the HA Supervisor based on the repo slug. It's stable across restarts.

3. **Create a voice assistant**: Settings > Voice Assistants > Add
   - Select the Extended OpenAI Conversation agent
   - Assign to your voice devices (e.g. ATOM Echo, Voice PE)
   - Set wake word (e.g. "Hey Jarvis" or "Okay Nabu")

## Architecture

```
APEX/                           # Git root (github.com/SalihTalhaAydin/A.P.E.X.)
├── .cursor/rules/              # Cursor AI rules (credentials.mdc is gitignored)
├── .env.example                # Environment template for local dev
├── .gitignore
├── docker-compose.yml          # Local Docker dev (context: apex_brain/)
├── repository.yaml             # HA add-on repo metadata
├── README.md
└── apex_brain/                 # All source code + HA add-on build context
    ├── build.json              # Maps architectures to base Docker images
    ├── config.yaml             # HA add-on config (slug, ports, options schema)
    ├── Dockerfile              # Python 3.13, Alpine 3.21 base
    ├── run.sh                  # Add-on entrypoint (reads options.json via jq)
    ├── requirements.txt
    ├── brain/                  # FastAPI server, conversation orchestrator, config
    │   ├── server.py           # /v1/chat/completions, /api/chat, /health
    │   ├── conversation.py     # Orchestrator with tool-calling loop
    │   ├── config.py           # Pydantic Settings (env vars + .env)
    │   └── system_prompt.py    # Dynamic prompt with injected context
    ├── memory/                 # Persistent memory system
    │   ├── conversation_store.py  # SQLite conversation history
    │   ├── knowledge_store.py     # Facts + embeddings + cosine similarity
    │   ├── fact_extractor.py      # Background fact extraction (gpt-4o-mini)
    │   └── context_builder.py     # Assembles context per turn
    └── tools/                  # Auto-discovered tool modules
        ├── base.py             # @tool decorator + registry
        ├── smart_home.py       # HA entity control
        ├── knowledge.py        # remember/recall/forget
        ├── datetime_tool.py    # Current time
        └── calendar_tool.py    # Stub (Google Calendar, future)
```

## Adding New Tools

Create a file in `apex_brain/tools/`, add the `@tool` decorator:

```python
# apex_brain/tools/weather.py
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

## Updating the Add-on

After pushing changes to GitHub:
1. In HA: **Settings > Add-ons > Add-on Store** → **⋮** → **Reload** (refresh), then open **Apex Brain** and click **Update** if available.
2. Or from your machine (with `HA_TOKEN` in `.env`): `python scripts/ha_update_apex_addon.py` to reload the store and update the add-on.
3. If HA doesn't see the update, remove and re-add the repository (see Troubleshooting).
3. Click **Update** / **Rebuild** to pull the latest code

## Troubleshooting

### Add-on won't install (Docker build fails)
- Check the Supervisor logs: SSH in and run `ha supervisor logs | tail -50`
- Common cause: base image tag doesn't exist. Check available tags at [ghcr.io/home-assistant/amd64-base-python](https://github.com/home-assistant/docker-base/pkgs/container/amd64-base-python). Update `build.json` and the Dockerfile `BUILD_FROM` arg.
- HA base images only ship the **latest Python** (currently 3.13). If a new Python version drops, update the tag.

### Add-on crashes on startup (state: error)
- Check add-on logs in the HA UI (Log tab) or via `ha addons logs 14fc29d6_apex_brain`
- **`s6-overlay-suexec: fatal: can only run as pid 1`** — This is a non-fatal warning when `init: false` is set. If the server still starts after it, ignore it. If it crashes, check that `run.sh` is a valid bash script.
- **`jq: not found`** — The Dockerfile must include `RUN apk add --no-cache jq`. This is needed because `init: false` disables bashio.

### HA store doesn't see new commits
- Remove and re-add the repository: **Add-on Store > ⋮ > Repositories > remove > re-add the URL**
- Or via the Supervisor API (WebSocket): `DELETE /store/repositories/{repo_slug}` then `POST /store/repositories` with the URL

### Extended OpenAI Conversation not loading
- Custom components require an HA Core restart (not just a reload)
- SSH in and verify: `ls /config/custom_components/extended_openai_conversation/manifest.json`
- Check HA Core logs: `ha core logs | grep extended_openai`
- The warning "custom integration not tested by Home Assistant" is normal

### Key Technical Details (for future reference)
- **init: false** in `config.yaml` means the container does NOT use S6 overlay as init. The `CMD` in the Dockerfile runs directly as PID 1. This avoids S6 init conflicts. The trade-off: `bashio` and `with-contenv` are not available, so we use `jq` to read `/data/options.json` instead.
- **build.json** maps architectures to base images. Without it, the Supervisor uses the Dockerfile's `BUILD_FROM` default, which only works for one architecture.
- **Add-on hostname**: The Supervisor assigns `{repo_slug}-{addon_slug}` as the Docker hostname. For this repo, it's `14fc29d6-apex-brain`. Other add-ons/integrations reach the API at `http://14fc29d6-apex-brain:8080`.
- **SUPERVISOR_TOKEN**: Automatically injected as an env var inside the add-on container. Used for authenticating HA API calls from within the add-on.
