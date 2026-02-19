# Apex Brain -- Architecture Document

> **Version:** 0.5.2
> **Last updated:** 2026-02-18
> **Scope:** Current architecture AND proposed Generic Tools redesign

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Key Components](#2-key-components)
3. [Proposed Redesign: Generic Tools Architecture](#3-proposed-redesign-generic-tools-architecture)
4. [Voice Pipeline Architecture](#4-voice-pipeline-architecture)
5. [Data Flow Diagrams](#5-data-flow-diagrams)
6. [Technology Stack](#6-technology-stack)
7. [Appendix: Current Tool Inventory](#appendix-current-tool-inventory)

---

## 1. System Overview

Apex Brain is a personal AI assistant that runs as a Home Assistant add-on (or standalone FastAPI server). It combines persistent memory, semantic knowledge retrieval, and direct smart-home control through an LLM-powered conversation loop.

### Directory Layout

```
APEX/                               # Git root
├── .env.example                    # Environment template (local dev)
├── docker-compose.yml              # Local Docker dev (context: apex_brain/)
├── repository.yaml                 # HA add-on repo metadata
├── README.md
│
└── apex_brain/                     # All source + HA add-on build context
    ├── Dockerfile                  # Python 3.13, Alpine 3.21 base
    ├── build.json                  # Multi-arch base image map
    ├── config.yaml                 # HA add-on config (slug, ports, options)
    ├── run.sh                      # Add-on entrypoint (reads options.json via jq)
    ├── requirements.txt
    │
    ├── brain/                      # Core server + orchestration
    │   ├── server.py               # FastAPI app, endpoints, rate limiter
    │   ├── conversation.py         # Tool-loop orchestrator (the "heart")
    │   ├── config.py               # Pydantic Settings (env + .env)
    │   ├── event_handler.py        # Webhook receiver, cooldown, priority
    │   ├── system_prompt.py        # Dynamic prompt builder (per-turn)
    │   └── version.py              # __version__ string
    │
    ├── memory/                     # Persistent memory system
    │   ├── conversation_store.py   # SQLite conversation history
    │   ├── knowledge_store.py      # Facts + embeddings + cosine similarity
    │   ├── fact_extractor.py       # Background AI fact extraction
    │   └── context_builder.py      # Assembles system prompt context
    │
    ├── tools/                      # Auto-discovered tool modules (60+ tools)
    │   ├── __init__.py             # discover_tools() via pkgutil
    │   ├── base.py                 # @tool decorator + TOOL_REGISTRY
    │   ├── smart_home.py           # Entity control (light, climate, media, cover, fan, area)
    │   ├── ha_helpers.py           # Shared HA API client + helpers (no @tool)
    │   ├── automation.py           # Automation CRUD, scenes
    │   ├── vacuum.py               # Vacuum control + room cleaning
    │   ├── notify.py               # Notifications + Alexa announcements
    │   ├── knowledge.py            # remember / recall / forget
    │   ├── routines.py             # Named multi-step routines
    │   ├── calendar_tool.py        # Google Calendar (service account)
    │   ├── datetime_tool.py        # Current time
    │   ├── weather.py              # Weather forecasts
    │   ├── presence.py             # Who is home / away
    │   ├── lock.py                 # Door lock control
    │   ├── switch.py               # Switch + input_boolean control
    │   ├── security.py             # Alarm panel + camera snapshots
    │   ├── energy.py               # Power/energy monitoring
    │   ├── history.py              # State change history + logbook
    │   ├── template.py             # Jinja2 template evaluation
    │   ├── system_info.py          # HA info, devices, integrations, services
    │   ├── input_helpers.py        # input_number/select/text/datetime
    │   ├── todo.py                 # Shopping/todo list management
    │   ├── script.py               # HA script listing + execution
    │   ├── config_reload.py        # HA config reload
    │   ├── webhook.py              # Fire webhooks + custom events
    │   └── wait_tool.py            # Timed delays between tool calls
    │
    └── tests/                      # 18 test files
        ├── test_config.py
        ├── test_smart_home.py
        ├── test_vacuum.py
        ├── test_webhook.py
        ├── test_ha_helpers.py
        └── ...
```

### High-Level Architecture Diagram

```
                    ┌──────────────────────────────────────────────┐
                    │            Home Assistant (HAOS)              │
                    │                                              │
                    │  ┌─────────────┐    ┌─────────────────────┐  │
                    │  │  Supervisor  │    │   HA Core REST API  │  │
                    │  │  (manages    │    │   /api/states       │  │
                    │  │   add-ons)   │    │   /api/services     │  │
                    │  └──────┬───────┘    │   /api/template     │  │
                    │         │            │   /api/history       │  │
                    │         ▼            └────────▲────────────┘  │
                    │  ┌──────────────┐            │               │
                    │  │  Apex Brain  │────────────┘               │
                    │  │  (Docker)    │   httpx + SUPERVISOR_TOKEN  │
                    │  │             │                              │
                    │  │  :8080      │◄──────── Wyoming Protocol   │
                    │  └──────┬───────┘    (voice satellites)      │
                    │         │                                    │
                    └─────────┼────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
              ▼               ▼               ▼
    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
    │  /v1/chat/   │  │  /api/chat   │  │ /api/webhook │
    │  completions │  │  (test UI)   │  │ (HA events)  │
    │  (HA voice)  │  │              │  │              │
    └──────────────┘  └──────────────┘  └──────────────┘
```

### Deployment Modes

| Mode | HA URL | Auth Token | Database |
|------|--------|-----------|----------|
| **HA Add-on** | `http://supervisor/core` | `SUPERVISOR_TOKEN` (auto-injected) | `/data/apex.db` (persistent volume) |
| **Local Dev** | `http://<HA_IP>:8123` | Long-lived token in `.env` | `./apex.db` (local file) |
| **Docker Compose** | Configurable | `.env` file | Volume mount |

---

## 2. Key Components

### 2.1 FastAPI Server (`brain/server.py`)

The entry point. Exposes four endpoint groups:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/chat/completions` | POST | OpenAI-compatible API. Used by HA's Extended OpenAI Conversation integration for voice and chat. |
| `/api/chat` | POST | Simple JSON chat for testing (`{"message": "...", "session_id": "..."}`) |
| `/api/webhook` | POST | Receives events from HA automations (motion, door, temperature, state changes) |
| `/health` | GET | Health check with HA connectivity status, uptime, loaded tools |
| `/api/debug/ha` | GET | Diagnostic: is HA Core reachable? |
| `/api/webhook/config` | GET | Returns supported event types and example HA automation YAML |

**Startup lifecycle** (via FastAPI `lifespan`):

```
1. Configure logging
2. Set API keys in environment
3. Initialize ConversationStore (SQLite)
4. Initialize KnowledgeStore (SQLite + embeddings)
5. Initialize FactExtractor (background AI)
6. Initialize ContextBuilder
7. discover_tools() -- auto-import all tool modules
8. Inject KnowledgeStore into tools that need it
9. Create Conversation orchestrator
10. Create EventHandler (if webhooks enabled)
11. Server ready
```

**Rate limiting** is applied via middleware:
- `/api/chat`: 30 requests/minute per client IP
- `/api/webhook`: 60 requests/minute per client IP

### 2.2 Conversation Loop (`brain/conversation.py`)

The orchestrator. Every user message flows through this pipeline:

```
User message
    │
    ▼
┌─────────────────────┐
│ 1. Save user turn   │  ConversationStore.save_turn()
│    to history        │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ 2. Build context     │  ContextBuilder.build()
│    (system prompt)   │  - Current time + season
│                      │  - Recent conversation (10 turns)
│                      │  - Semantic fact search
│                      │  - High-confidence core facts
│                      │  - Presence (who's home)
│                      │  - Device summary (entity IDs)
│                      │  - Calendar (if configured)
│                      │  - Proactive hints
│                      │  - Last action trace
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ 3. LLM call with    │  litellm.acompletion()
│    tool definitions  │  - model from settings
│                      │  - temperature 0.7
│                      │  - max_tokens 2000
└─────────┬───────────┘
          │
          ▼
┌─────────────────────────────────────────────────┐
│ 4. Tool execution loop (max 15 iterations)       │
│                                                   │
│    ┌─── Has tool_calls? ───┐                      │
│    │ YES                   │ NO                    │
│    ▼                       ▼                       │
│  Execute each tool     Return text response        │
│  via execute_tool()    (with confabulation check)  │
│    │                                               │
│    ▼                                               │
│  Append tool results                               │
│  to messages                                       │
│    │                                               │
│    └──── Loop back to LLM call ────►               │
└─────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────┐
│ 5. Save assistant    │  ConversationStore.save_turn()
│    response          │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ 6. Background fact   │  asyncio.create_task()
│    extraction        │  FactExtractor (gpt-4o-mini)
│    (user doesn't     │  - Extracts preferences, people,
│     wait)            │    events, habits, corrections
└─────────────────────┘
```

**Confabulation guard**: If the LLM responds with text claiming it performed a device action (e.g., "I've turned off the lights") but made zero tool calls, the orchestrator detects this and nudges the model: "You must use the tools to perform the action." This prevents the AI from pretending to control devices.

**Explainability**: After each response, an action trace is stored mapping which tools were called and which memory facts were used. If the user later asks "why did you do that?", the trace is injected into the next system prompt.

### 2.3 Memory System

Apex has a dual-layer memory architecture -- both layers stored in a single SQLite database.

#### Layer 1: Conversation History (`memory/conversation_store.py`)

```
┌──────────────────────────────────────────────┐
│  conversations table                          │
├──────────────────────────────────────────────┤
│  id         INTEGER PRIMARY KEY AUTOINCREMENT │
│  role       TEXT (user | assistant)            │
│  content    TEXT                               │
│  timestamp  TEXT (ISO 8601 UTC)                │
│  session_id TEXT (default: 'default')          │
├──────────────────────────────────────────────┤
│  Indexes: timestamp DESC, (session_id, ts)    │
└──────────────────────────────────────────────┘
```

- Every turn is saved permanently (never pruned).
- `get_recent(n=10)` retrieves the last N turns for context.
- `search(query)` enables keyword search across all history.
- `get_turns_since(hours=24)` for time-windowed retrieval.

#### Layer 2: Semantic Knowledge (`memory/knowledge_store.py`)

```
┌──────────────────────────────────────────────────────┐
│  facts table                                          │
├──────────────────────────────────────────────────────┤
│  id               INTEGER PRIMARY KEY AUTOINCREMENT   │
│  category          TEXT (preference|person|event|      │
│                         fact|habit|reminder)           │
│  key              TEXT (e.g. "favorite cuisine")       │
│  value            TEXT (e.g. "loves sushi")            │
│  confidence       REAL (0.0-1.0)                      │
│  source           TEXT (auto | user)                   │
│  embedding        BLOB (float32 vector, serialized)   │
│  created_at       TEXT (ISO 8601)                      │
│  updated_at       TEXT (ISO 8601)                      │
│  last_mentioned_at TEXT                                │
│  expires_at       TEXT (nullable, for temp facts)      │
├──────────────────────────────────────────────────────┤
│  Indexes: category, key                               │
└──────────────────────────────────────────────────────┘
```

**Search strategy** (cascading fallback):

```
1. Semantic search (cosine similarity over embeddings)
   └── Falls back to:
2. Keyword search (SQL LIKE on key + value columns)
```

**Deduplication**: Before inserting, the store checks:
1. Exact key match in same category -- updates if new confidence >= old
2. Semantic duplicate (cosine similarity >= 0.92) -- just touches timestamp
3. Otherwise inserts as new fact

**Confidence decay**: Facts not mentioned for 30+ days have their confidence reduced by `(1 - 0.01)^periods`. User-stated facts (source='user') never decay. Minimum confidence floor is 0.3.

**Temporal facts**: Facts with `expires_at` are automatically excluded from queries after expiration and can be cleaned up via `cleanup_expired()`.

#### Fact Extractor (`memory/fact_extractor.py`)

Runs as a background `asyncio.Task` after every conversation response. Uses a cheap model (default: `gpt-4o-mini`) to extract structured facts:

```json
[
  {"category": "preference", "key": "favorite cuisine", "value": "loves sushi", "confidence": 0.9},
  {"category": "person", "key": "Sarah", "value": "friend, birthday March 15", "confidence": 0.8},
  {"category": "event", "key": "dentist", "value": "Thursday 2pm", "confidence": 0.95, "expires": "2026-02-20"},
  {"category": "preference", "key": "thermostat", "value": "prefers 70F", "confidence": 1.0, "correction": true}
]
```

Corrections (user explicitly overriding a previous fact) are detected by the extractor and force-updated regardless of existing confidence.

#### Context Builder (`memory/context_builder.py`)

Assembles the complete system prompt each turn by gathering:

```
┌──────────────────────────────────────┐
│         Context Builder              │
│                                      │
│  1. Time context (time, season)      │──► _build_time_context()
│  2. Recent conversation (10 turns)   │──► conversation_store.get_recent()
│  3. Semantic facts (query-matched)   │──► knowledge_store.search_semantic()
│  4. Core facts (confidence >= 0.9)   │──► knowledge_store.get_all_facts()
│  5. Presence summary                 │──► tools.presence.get_presence_summary()
│  6. Device summary                   │──► tools.ha_helpers.get_device_summary()
│  7. Calendar (if configured)         │──► tools.calendar_tool.get_today_schedule()
│                                      │
│  All sections injected into:         │
│  SYSTEM_PROMPT_TEMPLATE              │
│  + proactive hints                   │
│  + device block                      │
└──────────────────────────────────────┘
```

### 2.4 System Prompt (`brain/system_prompt.py`)

The system prompt is dynamically rebuilt for every turn. It contains:

1. **Persona**: Apex's personality (J.A.R.V.I.S.-inspired, dry wit, anticipatory, reliable)
2. **Context block**: Time, presence, calendar, known facts, recent conversation
3. **Smart home instructions**: Per-tool usage guide with examples
4. **Device block**: Current entity IDs and states (injected from HA)
5. **Routines section**: How to define and execute routines
6. **Rules**: Conciseness, natural knowledge reference, no fabrication
7. **Proactive behavior guidelines**: Time-aware, context-aware suggestions
8. **Explainability**: How to trace and explain decisions
9. **Proactive hints**: Dynamic hints based on time of day, presence, calendar

### 2.5 Tool System

#### Registration

Tools use a decorator-based auto-discovery system:

```python
# tools/base.py
@tool(description="Get current weather for a location")
async def get_weather(location: str) -> str:
    ...
```

The `@tool` decorator:
1. Auto-generates an OpenAI-compatible JSON Schema from type hints (or accepts an explicit `parameters` dict)
2. Registers the function in `TOOL_REGISTRY` (a global dict)
3. Tracks whether the function is async

**Auto-discovery** (`tools/__init__.py`): On startup, `discover_tools()` uses `pkgutil.iter_modules` to import every `.py` file in the `tools/` directory (except `base.py`). Importing a module triggers its `@tool` decorators, which register functions in the global registry.

#### Execution

```python
# tools/base.py
async def execute_tool(name: str, arguments: dict) -> str:
    info = TOOL_REGISTRY[name]
    func = info["function"]
    if info["is_async"]:
        result = await func(**arguments)
    else:
        result = func(**arguments)
    return str(result)
```

All tool results are stringified. Errors are caught and returned as `"Tool error (name): message"`.

#### HA API Access Pattern

All HA-calling tools share a common HTTP client via `tools/ha_helpers.py`:

```
Tool function
    │
    ▼
ha_helpers.call_ha_service(domain, service, entity_id, data)
    │
    ▼
ha_helpers.ha_request(method, path, json_data)
    │
    ▼
httpx.AsyncClient (shared, module-level, 15s timeout)
    │
    ▼
HA Core REST API (http://supervisor/core/api/...)
    with Bearer token (SUPERVISOR_TOKEN or HA_TOKEN)
```

Most domain-specific tools follow the pattern:
1. Map user-friendly action to HA service name
2. Build service data from flat parameters
3. Call `call_ha_service()`
4. Read back state for verification (`verify_generic()` or domain-specific verifier)
5. Return human-readable confirmation

### 2.6 Event Handler (`brain/event_handler.py`)

Processes webhook events from HA automations:

```
HA Automation (state change trigger)
    │
    ▼
POST /api/webhook
{event_type, entity_id, new_state, old_state, attributes}
    │
    ▼
┌─────────────────────────────┐
│ Redundancy filter           │
│ - Same old/new state?       │──► Drop (no real change)
│ - Unavailable bounce?       │──► Drop (connectivity noise)
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│ Cooldown check              │
│ key = event_type:entity_id  │──► Drop if within cooldown
│ default: 60 seconds         │    (prevents reaction storms)
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│ Build natural language msg   │
│ "Motion detected: Hallway   │
│  Sensor changed to 'on'."   │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│ Conversation.handle()        │  Full AI pipeline
│ session_id = "apex_events"   │  (context, LLM, tools)
└─────────────┬───────────────┘
              │
              ▼
WebhookResponse {status, message, actions_taken}
```

**High-priority detection**: Door, alarm, and late-night motion events are flagged as high-priority for voice announcements.

**Optional shared-secret auth**: Webhook requests can include a `secret` in attributes, validated with `hmac.compare_digest` against the configured `webhook_secret`.

### 2.7 Configuration (`brain/config.py`)

Uses Pydantic Settings for type-safe configuration from environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `LITELLM_MODEL` | `claude-sonnet-4-20250514` | AI model for conversation |
| `OPENAI_API_KEY` | (empty) | OpenAI API key |
| `ANTHROPIC_API_KEY` | (empty) | Anthropic API key |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Model for semantic embeddings |
| `FACT_EXTRACTION_MODEL` | `gpt-4o-mini` | Cheap model for background extraction |
| `HA_URL` | `http://supervisor/core` | HA Core URL |
| `HA_TOKEN` | (empty) | Long-lived token (local dev) |
| `DB_PATH` | `./apex.db` | SQLite database path |
| `RECENT_TURNS` | 10 | Conversation turns in context |
| `MAX_FACTS_IN_CONTEXT` | 20 | Max facts per AI call |
| `TIMEZONE` | `America/Chicago` | Timezone (must match HA) |
| `WEBHOOK_ENABLED` | true | Enable webhook endpoint |
| `WEBHOOK_COOLDOWN_SECONDS` | 60 | Per-entity cooldown |
| `WEBHOOK_SECRET` | (empty) | Optional HMAC secret |
| `ANNOUNCE_ON_EVENTS` | true | Voice announcements on events |
| `ANNOUNCE_TARGET` | `alexa_all` | Default announcement target |
| `PORT` | 8080 | Server port |

Auth token resolution order:
1. `SUPERVISOR_TOKEN` env var (injected by HA Supervisor inside add-on)
2. `HA_TOKEN` from settings / `.env`
3. S6 container environment file (fallback for edge cases)

---

## 3. Proposed Redesign: Generic Tools Architecture

### 3.1 The Problem

The current system has **60+ individual tools** -- each HA domain gets its own tool with hardcoded parameters, enum values, and verification logic. Examples:

- `control_light(entity_id, action, brightness_pct, color, color_temp_kelvin, transition)`
- `control_climate(entity_id, temperature, hvac_mode, preset_mode, fan_mode)`
- `control_media(entity_id, action, volume_level, source)`
- `control_cover(entity_id, action, position, tilt_position)`
- `control_fan(entity_id, action, percentage, direction)`
- `control_vacuum(entity_id, action, fan_speed)`
- `control_lock(entity_id, action)`
- `control_switch(entity_id, action)`
- `control_alarm(entity_id, action, code)`
- ...and 50 more

**Problems with this approach:**

1. **Finite capability**: The AI can only do what we pre-built tools for. New HA integrations, services, or entity types require new tool code.
2. **Token bloat**: 60+ tool definitions consume a significant portion of the context window. Every turn sends all tool schemas to the LLM.
3. **Parameter rigidity**: Each tool's parameters are frozen at development time. HA services often accept additional data fields that the tool doesn't expose.
4. **Maintenance burden**: Every HA update that adds services or changes schemas requires updating tool code, tests, and system prompt instructions.
5. **Confabulation surface**: With so many similar tools, the LLM sometimes picks the wrong one or invents parameters that don't exist.

### 3.2 The Solution: ~7 Generic Power Tools

Replace all domain-specific tools with a small set of generic tools that give the AI direct, unrestricted access to the HA API. The AI uses its knowledge of HA service schemas (injected into the system prompt) to construct the right calls.

```
┌────────────────────────────────────────────────────────────────────┐
│                     CURRENT (60+ tools)                            │
│                                                                    │
│  control_light   control_climate   control_media   control_cover  │
│  control_fan     control_vacuum    control_lock    control_switch  │
│  control_alarm   control_area      call_service    list_entities   │
│  get_entity_state  query_sensors   get_areas       get_weather     │
│  get_presence    manage_todo       send_notification  announce     │
│  list_automations  trigger_automation  toggle_automation           │
│  create_automation  update_automation  delete_automation           │
│  list_scenes     activate_scene    list_scripts    execute_script  │
│  get_energy_summary  get_entity_power  evaluate_template          │
│  get_history     get_logbook       get_ha_info     list_devices    │
│  list_integrations  list_services  reload_config   fire_webhook    │
│  fire_event      set_input_helper  list_input_helpers  ...         │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘

                              │
                              ▼

┌────────────────────────────────────────────────────────────────────┐
│                     PROPOSED (~7 tools)                             │
│                                                                    │
│      do()      query()    discover()    history()                  │
│      automate()   notify()   remember()/recall()/forget()          │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

### 3.3 Tool Specifications

#### `do(domain, service, targets, data)` -- Universal Service Caller

**Replaces:** `control_light`, `control_climate`, `control_fan`, `control_cover`, `control_lock`, `control_switch`, `control_alarm`, `control_vacuum`, `control_media`, `control_area`, `call_service`, `set_input_helper`, `activate_scene`, `trigger_automation`, `toggle_automation`, `execute_script`, `reload_config`

```python
@tool(description="Call ANY Home Assistant service. Use service schemas from context to build the correct call.")
async def do(
    domain: str,           # e.g. "light", "climate", "vacuum"
    service: str,          # e.g. "turn_on", "set_temperature"
    targets: dict = None,  # {"entity_id": "..."} or {"area_id": "..."} or {"device_id": "..."}
    data: dict = None,     # Service-specific data, e.g. {"brightness_pct": 50, "color_temp_kelvin": 3000}
) -> str:
    """
    1. Call POST /api/services/{domain}/{service} with targets + data
    2. Wait 500ms for state to settle
    3. Read back entity state for verification
    4. Return: "Done. {entity_friendly_name}: {new_state} ({relevant_attributes})"
    """
```

**Key behavior:**
- Automatic post-action verification: after calling the service, reads the entity state back and reports it
- Accepts `area_id` or `device_id` targeting (not just `entity_id`)
- No hardcoded parameter validation -- the AI uses the service schema (injected in system prompt) to construct correct `data`
- Error messages include the HA response body for debugging

#### `query(target)` -- Universal State Reader

**Replaces:** `get_entity_state`, `query_sensors`, `get_weather`, `get_presence`, `get_energy_summary`, `get_entity_power`, `evaluate_template`

```python
@tool(description="Read entity state or evaluate a Jinja2 template against HA.")
async def query(
    target: str,  # entity_id (e.g. "light.kitchen") OR a Jinja2 template string
) -> str:
    """
    If target looks like an entity_id (contains a dot, no curly braces):
        GET /api/states/{target}
        Return formatted state + key attributes

    If target looks like a Jinja2 template (contains {{ or {%):
        POST /api/template {"template": target}
        Return rendered result

    Smart fallback: if entity_id returns 404, try template evaluation
    """
```

**Examples:**
- `query("climate.living_room")` -- returns state, target temp, current temp, mode
- `query("{{ states.sensor.outdoor_temperature.state }}°F")` -- evaluates template
- `query("{{ states.weather.home.attributes.forecast[:3] | to_json }}")` -- weather forecast
- `query("{% for e in states.light if e.state == 'on' %}{{ e.name }}\n{% endfor %}")` -- all lights that are on

#### `discover(what, filter)` -- Universal Discovery

**Replaces:** `list_entities`, `list_services`, `get_areas`, `list_devices`, `list_integrations`, `get_ha_info`, `list_input_helpers`, `list_automations`, `list_scenes`, `list_scripts`

```python
@tool(description="Find entities, services, areas, devices, or integrations in HA.")
async def discover(
    what: str,      # "entities", "services", "areas", "devices", "integrations", "info"
    filter: str = "",  # domain, area name, device type, or keyword
) -> str:
    """
    what="entities" + filter="light"    -> list all light.* entities
    what="entities" + filter="kitchen"  -> entities matching "kitchen"
    what="services" + filter="light"    -> all light.* services with schemas
    what="services" + filter=""         -> all service domains
    what="areas"                        -> all rooms/areas
    what="devices" + filter="kitchen"   -> physical devices in kitchen
    what="integrations"                 -> all loaded integrations
    what="info"                         -> HA version, location, timezone
    """
```

**Critical for the redesign**: When `what="services"`, the response includes full service schemas (field names, types, required/optional). This is how the AI learns what parameters `do()` accepts for any given service.

#### `history(entity_id, hours)` -- State History + Logbook

**Replaces:** `get_history`, `get_logbook`

```python
@tool(description="Get state change history or logbook entries for an entity.")
async def history(
    entity_id: str,
    hours: int = 24,
    mode: str = "changes",  # "changes" (state history) or "logbook" (human-readable events)
) -> str:
    """
    mode="changes": GET /api/history/period with entity filter
    mode="logbook": GET /api/logbook with entity filter
    """
```

#### `automate(action, config)` -- Automation/Scene/Script CRUD

**Replaces:** `create_automation`, `update_automation`, `delete_automation`, `list_automations`, `trigger_automation`, `toggle_automation`, `list_scenes`, `activate_scene`, `list_scripts`, `execute_script`

```python
@tool(description="Create, update, delete, trigger, or list automations, scenes, and scripts.")
async def automate(
    action: str,    # "list", "create", "update", "delete", "trigger", "toggle"
    type: str = "automation",  # "automation", "scene", "script"
    id: str = "",   # entity_id for existing items
    config: dict = None,  # Full config for create/update (triggers, conditions, actions)
) -> str:
    """
    action="list"     -> list all of {type}
    action="create"   -> create new automation/scene/script from config
    action="update"   -> update existing by id with new config
    action="delete"   -> delete by id
    action="trigger"  -> fire/execute by id
    action="toggle"   -> enable/disable automation by id
    """
```

#### `notify(target, message, data)` -- Notifications + Announcements

**Replaces:** `send_notification`, `announce`

```python
@tool(description="Send a notification or make a voice announcement.")
async def notify(
    message: str,
    target: str = "alexa_all",  # notify service target or "phone", "alexa_all", etc.
    data: dict = None,          # Extra data (title, image, actions, tts options)
) -> str:
    """
    Resolves friendly target names to actual notify service entities.
    Supports: Alexa announcements, phone push, specific speakers, groups.
    """
```

#### Memory Tools (keep as-is)

`remember(key, value)`, `recall(query)`, `forget(key)` -- These are already clean and generic. Keep them unchanged, along with the routine tools (`define_routine`, `list_routines`, `run_routine`, `delete_routine`).

### 3.4 Service Schema Injection

The key enabler for generic tools is injecting HA service schemas into the system prompt. Without this, the AI would not know what parameters `light.turn_on` accepts.

**Implementation:**

```python
# On startup or periodically (cached):
# GET /api/services -> list of all domains + services + field schemas

# Injected into system prompt:
"""
HA SERVICE SCHEMAS (use with do() tool):

## light
- light.turn_on: entity_id, brightness_pct (0-100), color_temp_kelvin,
  rgb_color [r,g,b], transition (seconds), flash (short|long)
- light.turn_off: entity_id, transition
- light.toggle: entity_id

## climate
- climate.set_temperature: entity_id, temperature, hvac_mode
- climate.set_hvac_mode: entity_id, hvac_mode (heat|cool|auto|off|...)
- climate.set_preset_mode: entity_id, preset_mode
...
"""
```

This replaces the current approach of hardcoding service knowledge into each tool's parameter schema. The AI reads the schema and constructs the correct `data` dict for `do()`.

**Token budget**: The full service schema for a typical HA instance is ~2000-4000 tokens. This is significantly less than the current 60+ tool definitions (~8000-12000 tokens).

### 3.5 Automatic Post-Action Verification

Currently, each domain tool has its own verification function (`_verify_light`, `_verify_climate`, `_verify_media`). In the redesign, `do()` includes a generic verifier:

```python
async def _verify_action(domain: str, entity_id: str) -> str:
    """Read back state after service call. Domain-aware formatting."""
    state = await read_state(entity_id)
    attrs = state.get("attributes", {})
    fn = attrs.get("friendly_name", entity_id)
    st = state.get("state", "unknown")

    # Domain-aware attribute extraction
    extras = []
    if domain == "light":
        if attrs.get("brightness") is not None:
            extras.append(f"{round(attrs['brightness']/255*100)}%")
        if attrs.get("color_temp_kelvin"):
            extras.append(f"{attrs['color_temp_kelvin']}K")
    elif domain == "climate":
        if attrs.get("temperature"):
            extras.append(f"target {attrs['temperature']}deg")
        if attrs.get("current_temperature"):
            extras.append(f"current {attrs['current_temperature']}deg")
    # ... etc

    detail = f" ({', '.join(extras)})" if extras else ""
    return f"{fn}: {st}{detail}"
```

### 3.6 Error Handling as Middleware

Instead of try/except in every tool, errors are handled in `execute_tool()`:

```python
async def execute_tool(name: str, arguments: dict) -> str:
    try:
        result = await func(**arguments)
        return str(result)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return f"Entity not found. Use discover(what='entities') to find valid IDs."
        return f"HA API error {e.response.status_code}: {e.response.text[:200]}"
    except httpx.TimeoutException:
        return "HA API timed out. The server may be busy."
    except Exception as e:
        return f"Tool error ({name}): {e}"
```

### 3.7 Migration Path

```
Phase 1: Build generic tools alongside existing tools
         ├── do() coexists with control_light, control_climate, etc.
         ├── AI can use either
         └── Validate behavior parity

Phase 2: Deprecate old tools
         ├── Old tools become thin wrappers: control_light() calls do("light", ...)
         ├── System prompt updated to prefer generic tools
         └── Monitor for regressions

Phase 3: Remove old tools
         ├── Delete domain-specific tool files
         ├── System prompt simplified (no per-tool instructions)
         └── Service schemas become the single source of truth
```

### 3.8 Comparison Summary

| Aspect | Current (60+ tools) | Proposed (~7 tools) |
|--------|-------------------|-------------------|
| **Tool count** | 60+ | ~7 + memory tools |
| **Token usage** (tool defs) | ~8,000-12,000 | ~2,000-4,000 (incl. schemas) |
| **New HA service support** | Requires new code | Automatic (schema injection) |
| **Parameter accuracy** | Hardcoded, may drift | Live from HA API |
| **Verification** | Per-domain functions | Generic with domain hints |
| **Error handling** | Per-tool try/except | Centralized middleware |
| **LLM confusion risk** | High (similar tool names) | Low (clear separation) |
| **Maintenance** | High (update each tool) | Low (schemas auto-update) |

---

## 4. Voice Pipeline Architecture

Apex integrates into Home Assistant's voice pipeline via the Wyoming protocol and Extended OpenAI Conversation integration.

```
┌──────────┐     ┌──────────────────────────────────┐     ┌──────────┐
│Microphone│     │        Wyoming Satellite          │     │ Speaker  │
│          │────►│                                    │────►│          │
└──────────┘     │  1. Wake Word (openWakeWord)       │     └──────────┘
                 │     "Hey Jarvis" / "Okay Nabu"     │          ▲
                 │                                    │          │
                 │  2. STT (Whisper / faster-whisper)  │          │
                 │     audio ──► text                  │          │
                 │                                    │          │
                 │  3. Intent / Conversation Agent     │          │
                 │     ┌──────────────────────────┐   │          │
                 │     │  Extended OpenAI          │   │          │
                 │     │  Conversation             │   │          │
                 │     │                          │   │          │
                 │     │  POST /v1/chat/           │   │          │
                 │     │  completions              │   │          │
                 │     │  ──────────────►          │   │          │
                 │     │  Apex Brain (:8080)       │   │          │
                 │     │  ◄──────────────          │   │          │
                 │     │  response text            │   │          │
                 │     └──────────────────────────┘   │          │
                 │                                    │          │
                 │  4. TTS (Piper)                     │          │
                 │     text ──► audio ─────────────────┼──────────┘
                 │                                    │
                 └──────────────────────────────────┘
```

### Pipeline Components

| Component | Technology | Location |
|-----------|-----------|----------|
| **Wake Word** | openWakeWord | Wyoming satellite device (ESP32-S3, Pi, etc.) |
| **STT** (Speech-to-Text) | Whisper / faster-whisper | HA add-on or satellite |
| **Conversation Agent** | Apex Brain (via Extended OpenAI Conversation) | HA add-on |
| **TTS** (Text-to-Speech) | Piper | HA add-on |
| **Audio I/O** | Wyoming protocol | Satellite device per room |

### Connection Details

- **Apex hostname inside HA**: `14fc29d6-apex-brain` (derived from repo slug by Supervisor)
- **API endpoint**: `http://14fc29d6-apex-brain:8080/v1`
- **API key**: `apex` (dummy -- Apex doesn't validate it)
- **Extended OpenAI Conversation** bridges HA's voice pipeline to Apex's OpenAI-compatible endpoint
- Audio output is routed to the originating satellite's speaker or a configured whole-home speaker group

### Satellite Deployment

```
                    ┌─────────────┐
                    │   HA Core   │
                    │  + Apex     │
                    │  + Piper    │
                    │  + Whisper  │
                    └──────┬──────┘
                           │ Wyoming Protocol (TCP)
              ┌────────────┼────────────┐
              │            │            │
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ Kitchen  │ │ Bedroom  │ │ Office   │
        │ ESP32-S3 │ │ Voice PE │ │ ATOM     │
        │ Sat.     │ │          │ │ Echo     │
        └──────────┘ └──────────┘ └──────────┘
```

---

## 5. Data Flow Diagrams

### 5.1 Chat Request Flow (User Types or Speaks)

```
User ──[voice/text]──►  HA / Client
                           │
                           ▼
                    POST /v1/chat/completions
                    (or POST /api/chat)
                           │
                           ▼
                   ┌───────────────┐
                   │  server.py     │
                   │  Extract user  │
                   │  message +     │
                   │  session_id    │
                   └───────┬───────┘
                           │
                           ▼
                   ┌───────────────┐
                   │conversation.py│
                   │  .handle()    │
                   └───────┬───────┘
                           │
                ┌──────────┼──────────┐
                ▼          │          ▼
        ┌──────────┐       │   ┌──────────────┐
        │ Save     │       │   │ Build system │
        │ user     │       │   │ prompt       │
        │ turn     │       │   │ (context     │
        │ (SQLite) │       │   │  builder)    │
        └──────────┘       │   └──────┬───────┘
                           │          │
                           │    ┌─────┼─────┬─────────┬──────────┐
                           │    ▼     ▼     ▼         ▼          ▼
                           │  Time  Facts  History  Presence  Devices
                           │  ctx   search (10     summary   summary
                           │        (semantic)turns)
                           │    └─────┬─────┴─────────┴──────────┘
                           │          │
                           │          ▼
                           │   System prompt assembled
                           │          │
                           ▼          ▼
                   ┌───────────────────────┐
                   │    LLM Call           │
                   │    (litellm)          │
                   │    model + messages   │
                   │    + tool defs        │
                   └───────────┬───────────┘
                               │
                     ┌─────────┴─────────┐
                     │ Tool calls?       │
                     │                   │
                ┌────┴────┐        ┌─────┴─────┐
                │   YES   │        │    NO     │
                ▼         │        ▼           │
         ┌───────────┐   │  ┌───────────┐     │
         │ Execute   │   │  │ Return    │     │
         │ tool(s)   │   │  │ text      │     │
         │ via HA    │   │  │ response  │     │
         │ REST API  │   │  └─────┬─────┘     │
         └─────┬─────┘   │       │            │
               │         │       ▼            │
               ▼         │  Save assistant    │
         Append results  │  turn (SQLite)     │
         to messages     │       │            │
               │         │       ▼            │
               └─────────┘  Background fact   │
                            extraction        │
                            (async task)      │
                                 │            │
                                 ▼            │
                            Return to client ◄┘
```

### 5.2 Webhook Event Flow (HA State Change --> Apex Reaction)

```
HA Entity state changes
        │
        ▼
HA Automation triggers
(configured by user)
        │
        ▼
POST /api/webhook
{
  "event_type": "motion",
  "entity_id": "binary_sensor.hallway",
  "new_state": "on",
  "old_state": "off"
}
        │
        ▼
┌───────────────────────┐
│  Shared-secret auth   │──► 403 if secret mismatch
│  (if configured)      │
└───────────┬───────────┘
            │
            ▼
┌───────────────────────┐
│  Redundancy filter    │──► Drop: same state, unavailable bounce
└───────────┬───────────┘
            │
            ▼
┌───────────────────────┐
│  Cooldown check       │──► Drop: within 60s of same event
│  (per event:entity)   │
└───────────┬───────────┘
            │
            ▼
┌───────────────────────┐
│  Build natural        │
│  language message     │
│  "Motion detected:    │
│   Hallway Sensor      │
│   changed to 'on'."   │
└───────────┬───────────┘
            │
            ▼
┌───────────────────────┐
│  conversation.handle()│  Full AI pipeline
│  session = apex_events│  (may call tools,
│                       │   send notifications,
│                       │   control devices)
└───────────┬───────────┘
            │
            ▼
WebhookResponse
{status: "processed", message: "...", actions_taken: [...]}
```

### 5.3 Memory Cycle (Conversation --> Fact Extraction --> Future Context)

```
Turn N: User says "My sister Sarah is visiting next Thursday"
        │
        ├──► Saved to conversation_store (immediate)
        │
        └──► After response, background task fires:
             │
             ▼
      ┌─────────────────────┐
      │  FactExtractor       │
      │  (gpt-4o-mini)      │
      │                     │
      │  Input: last 4 turns│
      │  Output: JSON array │
      └─────────┬───────────┘
                │
                ▼
      [{"category": "person",
        "key": "Sarah",
        "value": "sister, visiting next Thursday",
        "confidence": 0.85,
        "expires": "2026-02-26"}]
                │
                ▼
      ┌─────────────────────────────┐
      │  KnowledgeStore.store_fact()│
      │                             │
      │  1. Generate embedding      │
      │     (text-embedding-3-small)│
      │                             │
      │  2. Check for duplicates    │
      │     - Exact key match?      │
      │     - Semantic sim >= 0.92? │
      │                             │
      │  3. Insert or update        │
      │     (confidence wins)       │
      └─────────────────────────────┘
                │
                ▼
Turn N+5: User says "What's happening this week?"
        │
        ▼
      ┌─────────────────────────────┐
      │  ContextBuilder.build()     │
      │                             │
      │  Semantic search: "week"    │
      │  ──► Finds Sarah fact       │
      │      (cosine similarity)    │
      │                             │
      │  Injected into prompt:      │
      │  "WHAT YOU KNOW:            │
      │   - Sarah: sister,          │
      │     visiting next Thursday" │
      └─────────────────────────────┘
                │
                ▼
      AI naturally references:
      "Your sister Sarah is coming Thursday --
       shall I adjust the guest room thermostat?"
```

---

## 6. Technology Stack

### Runtime

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| **Language** | Python | 3.9+ (prod: 3.13) | Core runtime |
| **Web framework** | FastAPI | latest | HTTP server + endpoints |
| **ASGI server** | Uvicorn | latest | Production server |
| **LLM gateway** | LiteLLM | latest | Multi-provider AI calls (Claude, GPT-4o, Gemini) |
| **HTTP client** | httpx | latest | Async HA API calls (shared client) |
| **Database** | SQLite | (stdlib) | Conversations + knowledge + embeddings |
| **SQLite driver** | aiosqlite | latest | Async SQLite access |
| **Embeddings** | numpy | latest | Cosine similarity computation |
| **Config** | Pydantic Settings | latest | Type-safe env var config |
| **Validation** | Pydantic | v2 | Request/response models |

### Deployment

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Container base** | Alpine 3.21 + Python 3.13 | HA base image |
| **Container runtime** | Docker (managed by HA Supervisor) | Isolation + lifecycle |
| **Init system** | None (`init: false`) | Direct CMD execution, no S6 overlay |
| **Config reader** | jq | Reads `/data/options.json` (replaces bashio) |
| **Persistent storage** | `/data/` volume | SQLite database survives restarts |

### AI Models (configurable via `LITELLM_MODEL`)

| Provider | Models | Use Case |
|----------|--------|----------|
| **Anthropic** | claude-sonnet-4, claude-opus-4 | Primary conversation |
| **OpenAI** | gpt-4o, gpt-4o-mini | Conversation + fact extraction |
| **Google** | gemini-2.0-flash | Alternative conversation |
| **OpenAI** | text-embedding-3-small | Semantic embeddings (knowledge store) |

### Voice Pipeline

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Protocol** | Wyoming | HA voice satellite communication |
| **Wake word** | openWakeWord | "Hey Jarvis", "Okay Nabu", etc. |
| **STT** | Whisper / faster-whisper | Speech to text |
| **TTS** | Piper | Text to speech (natural voices) |
| **Bridge** | Extended OpenAI Conversation | Connects HA voice to Apex's API |

### Development & CI

| Tool | Purpose |
|------|---------|
| **pytest** | Test framework |
| **pre-commit** | Secret scanning on commits |
| **GitHub Actions** | CI: test + lint + secret check |

---

## Appendix: Current Tool Inventory

Complete list of all registered `@tool` functions as of v0.5.2, organized by module.

### smart_home.py (14 tools)
| Tool | Description |
|------|-------------|
| `list_entities` | List entities, optionally filtered by domain |
| `get_entity_state` | Get detailed state + attributes of a specific entity |
| `get_areas` | List all rooms/areas in HA |
| `query_sensors` | Query sensors by type, area, or specific entity_id |
| `control_light` | Light control: on/off/toggle, brightness, color, color temp |
| `cycle_light_timed` | Blink a light N times with delay (server-side) |
| `control_climate` | Thermostat: temperature, HVAC mode, preset, fan mode |
| `control_media` | Media player: play/pause/stop, volume, source |
| `control_cover` | Blinds/shades/garage: open/close/stop, position, tilt |
| `control_fan` | Fan: on/off/toggle, speed percentage, direction |
| `control_area` | Control all devices of a domain in an area by name |
| `call_service` | Generic HA service call (fallback for uncovered domains) |

### automation.py (8 tools)
| Tool | Description |
|------|-------------|
| `list_automations` | List all automations with on/off status |
| `trigger_automation` | Manually fire an automation |
| `toggle_automation` | Enable or disable an automation |
| `create_automation` | Create a new automation (triggers, conditions, actions) |
| `update_automation` | Modify an existing automation |
| `delete_automation` | Remove an automation |
| `list_scenes` | List all available scenes |
| `activate_scene` | Trigger a scene |

### vacuum.py (2 tools)
| Tool | Description |
|------|-------------|
| `control_vacuum` | Vacuum actions: start, pause, stop, return_to_base, locate |
| `clean_rooms` | Send vacuum to clean specific rooms by name |

### notify.py (2 tools)
| Tool | Description |
|------|-------------|
| `send_notification` | Send notification to a specific notify service target |
| `announce` | Voice announcement via Alexa or phone notification |

### knowledge.py (3 tools)
| Tool | Description |
|------|-------------|
| `remember` | Store a fact the user explicitly asks to remember |
| `recall` | Search knowledge base by query |
| `forget` | Delete a remembered fact by key |

### routines.py (4 tools)
| Tool | Description |
|------|-------------|
| `define_routine` | Create a named multi-step routine |
| `list_routines` | View all defined routines |
| `run_routine` | Execute a routine by name |
| `delete_routine` | Remove a routine |

### calendar_tool.py (4 tools)
| Tool | Description |
|------|-------------|
| `get_today_schedule` | Today's calendar events |
| `get_upcoming_events` | Events in next N days |
| `create_event` | Create a calendar event |
| `delete_event` | Delete a calendar event |

### energy.py (3 tools)
| Tool | Description |
|------|-------------|
| `get_energy_entities` | List all power/energy sensor entities |
| `get_entity_power` | Current power/energy reading for a specific sensor |
| `get_energy_summary` | Overview of power consumption and solar generation |

### history.py (2 tools)
| Tool | Description |
|------|-------------|
| `get_history` | State change history for an entity |
| `get_logbook` | Human-readable event log |

### security.py (3 tools)
| Tool | Description |
|------|-------------|
| `control_lock` | Lock/unlock/open a door lock |
| `control_alarm` | Arm/disarm an alarm panel |
| `get_camera_snapshot` | Get a camera snapshot URL |

### system_info.py (4 tools)
| Tool | Description |
|------|-------------|
| `get_ha_info` | HA version, location, timezone, units |
| `list_devices` | Physical devices with manufacturer, model, area |
| `list_integrations` | All loaded integrations/platforms |
| `list_services` | Available service calls by domain |

### Other modules (1 tool each)
| Module | Tool | Description |
|--------|------|-------------|
| `switch.py` | `control_switch` | Switch + input_boolean: on/off/toggle |
| `presence.py` | `get_presence` | Who is home or away |
| `weather.py` | `get_weather` | Weather forecast (daily/hourly) |
| `datetime_tool.py` | `get_current_datetime` | Current date/time in configured timezone |
| `template.py` | `evaluate_template` | Evaluate Jinja2 template against HA |
| `input_helpers.py` | `set_input_helper` + `list_input_helpers` | Control input_number/select/text/datetime |
| `todo.py` | `manage_todo` | Shopping/todo list CRUD |
| `script.py` | `list_scripts` + `execute_script` | HA script listing and execution |
| `config_reload.py` | `reload_config` | Reload HA YAML configuration |
| `webhook.py` | `fire_webhook` + `fire_event` + `fire_custom_event` | Trigger webhooks and custom events |
| `wait_tool.py` | `wait_seconds` | Timed delay between tool calls |

**Total: ~60+ registered tools across 20 modules**
