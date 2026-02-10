# Changelog

All notable changes to Apex Brain are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/).

---

## [0.1.2] - 2026-02-10

### Fixed
- **Smart home tools ignoring service data (brightness, temperature, volume, etc.)** -- GPT-4o consistently skips the nested optional `data` object in `call_service`, so brightness_pct, temperature, volume_level, etc. were never sent to Home Assistant. Lights would receive `turn_on` with no brightness, so already-on lights showed no visible change. Root cause: LLMs reliably fill flat top-level parameters but skip nested optional objects. Key files: `apex_brain/tools/smart_home.py`, `apex_brain/brain/system_prompt.py`.

### Added
- **Domain-specific smart home tools** with flat parameters that the AI can't miss: `control_light` (brightness_pct, color, color_temp_kelvin, transition), `control_climate` (temperature, hvac_mode, preset_mode, fan_mode), `control_media` (volume_level, source, play/pause/stop), `control_cover` (position, tilt_position), `control_fan` (percentage, direction). Key file: `apex_brain/tools/smart_home.py`.
- **State verification** after every service call -- tools read back the entity state from HA and include it in the result (e.g. "Done. Kitchen Light: on, 50% brightness"). Gives the AI honest feedback if the change didn't take effect.
- **Anti-hallucination rule** in system prompt -- "NEVER say you controlled a device unless you actually called a tool." Key file: `apex_brain/brain/system_prompt.py`.
- **Improved tool logging** -- tool call args now logged up to 500 chars (was 200), tool results logged (300 chars), and AI text responses without tool calls are explicitly logged for debugging. Key file: `apex_brain/brain/conversation.py`.

### Changed
- **`call_service` is now a generic fallback** for domains without dedicated tools (locks, switches, scenes, scripts, vacuums). `data` parameter renamed to `service_data` with clearer description. Still works for any HA service call.
- **System prompt** now includes a SMART HOME section guiding the AI on which tool to use for each domain and requiring tool calls before confirming actions.

---

## [0.1.1] - 2026-02-10

### Fixed
- **SUPERVISOR_TOKEN not available to smart home tools** -- S6 overlay runs in the container even with `init: false` in config.yaml. The old `#!/bin/bash` shebang in `run.sh` meant S6 started the script with a clean environment, stripping the Supervisor-injected token. All HA API calls from tools (list_entities, call_service, etc.) failed with 401 Unauthorized. Key files: `apex_brain/run.sh`, `apex_brain/brain/config.py`, `apex_brain/tools/smart_home.py`, `apex_brain/config.yaml`.

### Changed
- **run.sh shebang** changed from `#!/bin/bash` to `#!/usr/bin/with-contenv bash` so S6 injects SUPERVISOR_TOKEN and other container environment variables into the process.
- **config.py** now has a fallback that reads SUPERVISOR_TOKEN from S6 container environment files (`/run/s6/container_environment/` and `/var/run/s6/container_environment/`) if the env var is missing.
- **smart_home.py** `_ha_request()` now logs the HTTP method, URL, token status, and any non-200 responses to the add-on logs for easier debugging.
- **run.sh** prints whether SUPERVISOR_TOKEN is set (and its length) at startup for quick diagnosis.
- **config.yaml** comments updated to reflect that S6 still runs from the base image; `init: false` only disables bashio, not S6 itself.

---

## [0.1.0] - 2026-02-09

### Added
- **Core AI system** -- FastAPI server with OpenAI-compatible `/v1/chat/completions` endpoint and simple `/api/chat` for testing. Orchestrated by `brain/conversation.py` with LiteLLM for model abstraction (GPT-4o default).
- **Persistent memory** -- SQLite-backed conversation store (never deleted) and knowledge store with numpy cosine similarity over OpenAI embeddings. Background fact extraction via gpt-4o-mini after each conversation turn.
- **Context builder** -- Assembles current time, recent conversation turns, and semantically relevant facts into a dynamic system prompt for each AI call.
- **Tool system** -- Decorator-based (`@tool`) with auto-discovery. Tools in `apex_brain/tools/` are auto-imported on startup and registered in `TOOL_REGISTRY` with OpenAI function schemas generated from type hints.
- **Smart home tools** (`tools/smart_home.py`) -- list_entities, get_entity_state, call_service, get_areas. Uses HA REST API via Supervisor proxy with SUPERVISOR_TOKEN auth.
- **Knowledge tools** (`tools/knowledge.py`) -- remember, recall, forget. Backed by knowledge_store with semantic search.
- **DateTime tool** (`tools/datetime_tool.py`) -- get_current_datetime.
- **Calendar tool stub** (`tools/calendar_tool.py`) -- Placeholder for Google Calendar integration.
- **HA Add-on packaging** -- Dockerfile (Python 3.13 Alpine base), config.yaml, build.json (amd64 + aarch64), run.sh entrypoint, repository.yaml.
- **Voice pipeline integration** -- Connected to HA via Extended OpenAI Conversation custom component. Whisper STT and Piper TTS added as Wyoming integrations. "Apex" voice assistant pipeline created and set as preferred.
- **Extended OpenAI Conversation** custom component installed on HAOS (manually via SSH). Its `manifest.json` was patched to require `openai==2.15.0` (matching HA Core's installed version) to resolve a `RequirementsNotFound` error.
- **SSH access** configured on HA Terminal & SSH add-on (port 22 enabled, temporary password set) for debugging and file manipulation on HAOS.

### Technical Notes
- Add-on hostname: `14fc29d6-apex-brain` (stable across restarts).
- Extended OpenAI Conversation configured with base URL `http://14fc29d6-apex-brain:8080/v1` and dummy API key `apex`.
- Whisper STT: Wyoming integration, host `core-whisper`, port 10300.
- Piper TTS: Wyoming integration, host `core-piper`, port 10200.
- HA Core version at time of integration: 2026.2.1.
