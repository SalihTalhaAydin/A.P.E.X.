# Changelog

All notable changes to Apex Brain are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/).

---

## [0.1.4] - 2026-02-11

### Added
- **Ruff lint and format** — pyproject.toml: Ruff lint (E, F, I, B, C4, UP, ARG; E501 ignored) and format; pre-commit hook enabled for Ruff. Key files: `pyproject.toml`, `.pre-commit-config.yaml`.
- **Unit tests** — pytest, pytest-asyncio, pytest-cov; `apex_brain/tests/` with conftest (temp DB, mock embed), test_config, test_tools_base, test_knowledge_store, test_server (14 tests). Key files: `apex_brain/tests/*.py`, `pyproject.toml`.
- **CI test-and-lint** — GitHub Action runs ruff check, ruff format --check, pytest on push/PR to main. Key file: `.github/workflows/test-and-lint.yml`.
- **README badges** — Test and Lint, Secrets Check, Python 3.12+ badges; tests run command documented. Key file: `README.md`.
- **wait_seconds tool** — Enables timed sequences (e.g. "turn kitchen lights on/off three times with 10-second delay"). AI can call control_light and wait_seconds in sequence; max wait 300s. Key file: `apex_brain/tools/wait_tool.py`.

### Changed
- **Docstrings and version** — Settings and KnowledgeStore class docstrings; change-tracking documents config.yaml as canonical version (pyproject matches). Key files: `apex_brain/brain/config.py`, `apex_brain/memory/knowledge_store.py`, `.cursor/rules/change-tracking.mdc`.
- **Lint fixes** — Unused vars and loop var in conversation_store and ha_assign_devices; lifespan arg renamed to _app. Key files: `apex_brain/memory/conversation_store.py`, `apex_brain/brain/server.py`, `scripts/ha_assign_devices.py`.
- **System prompt: full control and honesty** — Explicit "you have full control" and instructions to use wait_seconds for timed/repeated actions; never refuse with "not allowed" when tools can do it. Stronger rule: if a tool fails, say so clearly; never claim you did the action anyway. Key file: `apex_brain/brain/system_prompt.py`.
- **Cleanup** — Removed unused `.prettierrc`; added `.coverage`, `htmlcov/`, `.pytest_cache/` to .gitignore. Key file: `.gitignore`.
- **HA errors surfaced to the model** — Smart home control tools now catch httpx.HTTPStatusError and return short, model-friendly messages (e.g. "Entity not found: light.xyz", "HA error 422: ...") so the AI can report real failures instead of generic or false excuses. Key file: `apex_brain/tools/smart_home.py`.

---

## [0.1.3] - 2026-02-11

### Fixed
- **Security: remove hardcoded HA refresh token** -- Removed the fallback refresh token from `scripts/ha_assign_devices.py`; the script now requires `REFRESH_TOKEN` in the environment and exits with a clear error if unset. If this repo was ever pushed with the old code, rotate the token in HA (Profile → Security) and update `.cursor/rules/credentials.mdc`. Key file: `scripts/ha_assign_devices.py`.
- **HA_TOKEN support in ha_assign_devices** -- Script accepts `HA_TOKEN` (long-lived access token) or `REFRESH_TOKEN`; prefer `HA_TOKEN` from Profile → Security → Long-Lived Access Tokens. Key file: `scripts/ha_assign_devices.py`.
- **Security: no hardcoded private IP in scripts** -- `ha_assign_devices.py` default HA_URL changed from a specific local IP to `http://homeassistant.local:8123` so the repo does not expose your network. Key file: `scripts/ha_assign_devices.py`.
- **Lights not accessible / turn on-off not working properly** -- `list_entities` was capped at 50 entities for all calls, so when the user had many lights (or many entities), only the first 50 were visible to the model and later ones were never controlled. Now when a domain filter is used (e.g. `domain="light"`), up to 200 entities are returned (cap 50 when no domain). When truncated, the response includes "(Showing first N of M entities)" and logs show `[list_entities] domain=... total=... showing=...` for debugging. Key files: `apex_brain/tools/smart_home.py`, `apex_brain/brain/system_prompt.py`.

### Added
- **Pre-commit and CI secret scanning** -- Pre-commit hook (gitleaks) blocks commits that contain tokens, API keys, or passwords. Optional: `pip install pre-commit && pre-commit install`. `.gitleaks.toml` allowlists `.env.example`. GitHub Action `.github/workflows/check-secrets.yml` runs the same check on push/PR to main. Project rule `.cursor/rules/apex-no-secrets-in-code.mdc` forbids secrets in code and fallbacks; env or gitignored files only. Key files: `.pre-commit-config.yaml`, `.gitleaks.toml`, `.github/workflows/check-secrets.yml`, `.cursor/rules/apex-no-secrets-in-code.mdc`, `README.md`.
- **HA device setup checklist** -- `docs/ha-device-setup-checklist.md` lists device types (Sengled, IKEA Dirigera, Hampton Bay/Tuya, Echo, temp sensors, Nest, BroadLink RM4 Pro), integration names, naming examples, and integration steps for fan/projector/curtains/laundry/basement. Wi‑Fi/Bluetooth-focused; Zigbee skipped for now. Key file: `docs/ha-device-setup-checklist.md`.
- **Nest thermostat setup guide** -- `docs/nest-setup.md` step-by-step for adding Google Nest to HA (Cloud project, OAuth, Device Access $5, Pub/Sub topic, link account). Apex already supports climate entities via `control_climate`. Key file: `docs/nest-setup.md`.
- **Device naming convention** -- Room + Fixture/Level + Description (friendly_name Title Case, entity_id snake_case when editable). Documented in `.cursor/rules/apex-device-naming.mdc`, `docs/device-naming.md`; system prompt and smart_home tool examples updated. Optional `scripts/suggest_device_names.py` (REST, suggests names only) and `scripts/ha_assign_devices.py` now supports `--dry-run` and a confirmation prompt before applying area/name updates in HA. Key files: `apex_brain/brain/system_prompt.py`, `apex_brain/tools/smart_home.py`, `docs/device-naming.md`, `scripts/ha_assign_devices.py`, `scripts/suggest_device_names.py`.

### Changed
- **Entity friendly names: abbreviation expansion** -- `scripts/ha_assign_devices.py` now expands abbreviations and typos when building friendly names from entity_id (e.g. bsmnt → Basement, ent → Entrance, bedr → Bedroom, upstaris → Upstairs, Mark S → Mark's, Adguard → AdGuard). All lights, switches, and other entities get readable names. Key file: `scripts/ha_assign_devices.py`.
- **Cursor IDE orchestration (user + project level only, no code changes)** -- User-level rules file at `%USERPROFILE%\.cursor\cursor-user-rules-recommended.md` for pasting into Cursor Settings → User Rules (parallel, hands-off, auto-rule creation, zero repetition). Project-level: `.cursor/rules/apex-orchestration.mdc`, `AGENTS.md`, one-line reminder in `apex-project.mdc`, and `docs/cursor-user-rules-recommended.md` pointing to the user-level file. Key files: `.cursor/rules/apex-orchestration.mdc`, `AGENTS.md`, `docs/cursor-user-rules-recommended.md`.
- **HA connectivity diagnostic** -- `/health` now includes `ha_reachable` (and `ha_error` on failure). New `GET /api/debug/ha` returns whether the add-on can reach the Home Assistant Core API (same URL/token as smart home tools), for quick diagnosis when "light didn't work". Key file: `apex_brain/brain/server.py`.

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

### Changed
- **Repository restructured** -- Promoted `apex/` from a subfolder of `Random/` to a standalone project at `APEX/`. Moved `.cursor/rules/` into the project so rules are portable across machines. Deleted `jarvis-demo/`, browser fix MDs, old plan files, and `nul`. Updated all path references in rules, README, .env.example, and CHANGELOG. Added `credentials.mdc` to `.gitignore` (contains secrets). Added HA interaction documentation (browser + terminal methods) to `credentials.mdc`. Key files: `.cursor/rules/*.mdc`, `README.md`, `.env.example`, `.gitignore`, `CHANGELOG.md`.

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
