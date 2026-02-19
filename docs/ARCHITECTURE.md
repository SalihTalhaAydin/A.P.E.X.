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
7. [Architectural Risks & Open Questions](#7-architectural-risks--open-questions)
8. [Appendix: Current Tool Inventory](#appendix-current-tool-inventory)

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
    └── tests/                      # 21 test files
        ├── test_config.py
        ├── test_conversation.py      # 39 tests — orchestrator coverage
        ├── test_context_builder.py   # 17 tests — context assembly coverage
        ├── test_fact_extractor.py    # 25 tests — background extraction coverage
        ├── test_smart_home.py
        ├── test_vacuum.py
        ├── test_webhook.py
        ├── test_ha_helpers.py
        └── ...
```

### High-Level Architecture Diagram

```
                    ┌───────────────────────────────────────────────────────────┐
                    │                  Home Assistant (HAOS)                     │
                    │                                                           │
                    │  ┌─────────────────────┐    ┌─────────────────────────┐   │
                    │  │  HA Supervisor API   │    │   HA Core REST API      │   │
                    │  │                     │    │   /api/states            │   │
                    │  │  /backups           │    │   /api/services          │   │
                    │  │   (create, restore, │    │   /api/template          │   │
                    │  │    list, delete)    │    │   /api/history           │   │
                    │  │  /addons            │    │   /api/config            │   │
                    │  │   (install, update, │    └────────────▲────────────┘   │
                    │  │    restart, config) │                 │                │
                    │  │  /core             │                 │                │
                    │  │   (update, restart, │    ┌────────────────────────┐    │
                    │  │    check)          │    │  HA WebSocket API      │    │
                    │  │  /os               │    │  ws://ha:8123/api/ws   │    │
                    │  │   (update, info,   │    │                        │    │
                    │  │    disk, memory)   │    │  config/entity_registry │    │
                    │  │  /network          │    │  config/device_registry │    │
                    │  │  /hardware         │    │  config/area_registry   │    │
                    │  └─────────▲──────────┘    │  config/config_entries  │    │
                    │            │               └────────────▲───────────┘    │
                    │            │                            │                │
                    │  ┌─────────┴────────────────────────────┴──────────┐     │
                    │  │              Apex Brain (Docker)                 │     │
                    │  │                                                  │     │
                    │  │  httpx ──► Core REST API (states, services)     │     │
                    │  │  httpx ──► Supervisor API (backups, addons, OS) │     │
                    │  │  websocket ──► WS API (registry, config ops)    │     │
                    │  │                                                  │     │
                    │  │  :8080  ◄──────── Wyoming Protocol              │     │
                    │  │                   (voice satellites)             │     │
                    │  └──────────────────────┬──────────────────────────┘     │
                    │                         │                                │
                    └─────────────────────────┼────────────────────────────────┘
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

> **Note on API surfaces:** Apex communicates with three distinct HA APIs.
> The **Core REST API** handles entity state reads and service calls (the primary interface today).
> The **Supervisor API** (`http://supervisor/<endpoint>`) handles system operations -- backups,
> add-on management, OS/core updates, and hardware/network info. The **WebSocket API**
> (`ws://supervisor/core/websocket`) is required for config/registry operations (entity rename,
> area management, device registry, config entries) that are not exposed via REST.

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
| `PHONE_NOTIFY_TARGET` | `mobile_app_salih_iphone` | Phone notification entity name |
| `PORT` | 8080 | Server port |

Auth token resolution order:
1. `SUPERVISOR_TOKEN` env var (injected by HA Supervisor inside add-on)
2. `HA_TOKEN` from settings / `.env`
3. S6 container environment file (fallback for edge cases)

**Supervisor API auth note:** The `SUPERVISOR_TOKEN` already grants full access to the Supervisor API (`http://supervisor/*`) -- no additional credentials are needed. When running as an HA add-on, Apex can call Supervisor endpoints (backups, add-ons, core/OS updates, hardware info) using the same token that authenticates Core REST API requests. The token is passed as `Authorization: Bearer <SUPERVISOR_TOKEN>` to both APIs. In local dev mode, the Supervisor API is not available (it only exists inside HAOS), so `manage()` operations will return an appropriate error message.

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

### 3.2 The Solution: ~9 Generic Power Tools

Replace all domain-specific tools with a small set of generic tools that give the AI direct, unrestricted access to the HA API and system management. The AI uses its knowledge of HA service schemas (injected into the system prompt) to construct the right calls, and gains system administration capabilities via the Supervisor and WebSocket APIs.

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
│                     PROPOSED (~9 tools)                             │
│                                                                    │
│      do()      query()    discover()    history()                  │
│      automate()   notify()   manage()   configure()               │
│      remember()/recall()/forget()                                  │
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

**Security considerations (IMPORTANT):**

Giving the LLM unrestricted access to call any HA service is powerful but dangerous. A single hallucinated or misinterpreted service call could disarm the alarm, unlock the front door, or disable security cameras. Mitigations:

1. **Sensitive domain gate**: Maintain a configurable list of security-critical domains that require extra safeguards:
   - `lock` (door locks)
   - `alarm_control_panel` (arm/disarm)
   - `camera` (disable/snapshot)
   - `cover` (garage doors)
   - `automation` (delete/disable safety automations)
2. **Confirmation step**: For actions on gated domains, `do()` should return a confirmation prompt ("About to unlock front_door. Confirm?") instead of executing immediately. The LLM must relay this to the user and only execute on explicit approval.
3. **Allowlist/denylist config**: Add `PROTECTED_DOMAINS` and `BLOCKED_SERVICES` to `config.py` so the user can customize which actions require confirmation or are outright forbidden (e.g., `lock.unlock` from voice commands while away).
4. **Audit log**: Every `do()` call should be logged with timestamp, domain, service, targets, and the originating session (voice vs. chat vs. webhook). This enables post-incident review.

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

#### `manage(action, target, config)` -- System Operations via Supervisor API

**Replaces:** nothing (new capability -- extends Apex from device control to full system administration)

```python
@tool(description="Manage HA system: backups, add-ons, updates, and system health.")
async def manage(
    action: str,    # "backup", "update", "restart", "install", "health", "logs"
    target: str = "",  # "core", "os", "addon:<slug>", "supervisor", or specific backup ID
    config: dict = None,  # Extra config (e.g., backup name, addon config options)
) -> str:
    """
    Routes to the appropriate Supervisor API endpoint:

    action="backup"   + target="create"          -> POST /backups/new/full (or /partial with config)
    action="backup"   + target="list"            -> GET /backups
    action="backup"   + target="restore"         -> POST /backups/{config['backup_id']}/restore
    action="backup"   + target="delete"          -> DELETE /backups/{config['backup_id']}

    action="update"   + target="core"            -> POST /core/update
    action="update"   + target="os"              -> POST /os/update
    action="update"   + target="addon:<slug>"    -> POST /addons/<slug>/update

    action="restart"  + target="core"            -> POST /core/restart
    action="restart"  + target="addon:<slug>"    -> POST /addons/<slug>/restart
    action="restart"  + target="supervisor"      -> POST /supervisor/restart

    action="install"  + target="addon:<slug>"    -> POST /addons/<slug>/install (with config)

    action="health"   + target="" (default)      -> GET /core/info + /os/info + /supervisor/info
                                                    Returns: CPU, memory, disk, network, versions

    action="logs"     + target="core"            -> GET /core/logs
    action="logs"     + target="supervisor"      -> GET /supervisor/logs
    action="logs"     + target="addon:<slug>"    -> GET /addons/<slug>/logs

    All calls use SUPERVISOR_TOKEN via http://supervisor/<endpoint>.
    Returns human-readable summary of the result.
    """
```

**Security considerations (IMPORTANT):**

| Operation | Risk Level | Confirmation Required? |
|-----------|-----------|----------------------|
| `backup/create` | **Safe** | No -- creating a backup is non-destructive |
| `backup/list` | **Safe** | No -- read-only |
| `health` | **Safe** | No -- read-only diagnostics |
| `logs` | **Safe** | No -- read-only |
| `backup/restore` | **DESTRUCTIVE** | **Yes** -- wipes current state and restores from snapshot |
| `backup/delete` | **Destructive** | **Yes** -- permanently removes a backup |
| `update/core` | **Disruptive** | **Yes** -- triggers HA restart, causes downtime |
| `update/os` | **Disruptive** | **Yes** -- triggers OS-level reboot |
| `update/addon` | **Disruptive** | **Yes** -- restarts the add-on |
| `restart/core` | **Disruptive** | **Yes** -- causes HA downtime |
| `restart/addon` | **Disruptive** | **Yes** -- add-on temporarily unavailable |
| `install/addon` | **Moderate** | **Yes** -- installs new software on the system |

For destructive/disruptive operations, `manage()` returns a confirmation prompt instead of executing immediately. The LLM relays the prompt to the user and only executes on explicit approval.

#### `configure(action, target, data)` -- Entity/Device/Area Registry Management via WebSocket API

**Replaces:** nothing (new capability -- enables Apex to organize and maintain the HA instance)

```python
@tool(description="Organize HA: rename entities, manage areas, configure integrations, clean up stale devices.")
async def configure(
    action: str,     # "rename", "assign_area", "disable", "enable", "create_area",
                     # "delete_area", "remove", "list_stale"
    target: str = "",  # entity_id, device_id, or area name
    data: dict = None,  # e.g., {"name": "Kitchen Light", "area_id": "kitchen"}
) -> str:
    """
    Uses HA WebSocket API for registry operations not available via REST:

    action="rename"       + target=entity_id  -> config/entity_registry/update {entity_id, name}
    action="assign_area"  + target=entity_id  -> config/entity_registry/update {entity_id, area_id}
                          + target=device_id  -> config/device_registry/update {device_id, area_id}
    action="disable"      + target=entity_id  -> config/entity_registry/update {disabled_by: "user"}
    action="enable"       + target=entity_id  -> config/entity_registry/update {disabled_by: null}
    action="create_area"  + data={"name": ..} -> config/area_registry/create {name}
    action="delete_area"  + target=area_name  -> config/area_registry/delete {area_id}
    action="remove"       + target=device_id  -> config/device_registry/remove {device_id}
    action="list_stale"                       -> config/entity_registry/list, filter by
                                                 unavailable/unknown for 7+ days

    Opens a transient WebSocket connection per operation.
    Returns human-readable confirmation of what changed.
    """
```

**Security considerations (IMPORTANT):**

| Operation | Risk Level | Confirmation Required? |
|-----------|-----------|----------------------|
| `rename` | **Safe** | No -- cosmetic change, easily reversible |
| `assign_area` | **Safe** | No -- organizational, easily reversible |
| `enable` | **Safe** | No -- restores functionality |
| `create_area` | **Safe** | No -- additive, no side effects |
| `list_stale` | **Safe** | No -- read-only |
| `disable` | **Moderate** | **Yes** -- disabling a critical entity (e.g., alarm sensor) could have safety implications |
| `delete_area` | **Moderate** | **Yes** -- unassigns all entities from the area |
| `remove` | **Destructive** | **Yes** -- permanently removes a device and its entities from HA |

For operations that require confirmation, `configure()` first performs a **dry-run** that shows what would change (e.g., "This will disable binary_sensor.front_door_contact and remove it from automations X and Y. Confirm?") before applying.

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

**Caveats and filtering strategy:**

The ~2,000-4,000 token estimate assumes a moderately-sized HA instance. This number can grow significantly with many integrations -- large installations with 30+ integrations and custom components could push schema sizes to 8,000+ tokens, erasing the token savings. Mitigations:

1. **Domain filtering**: Only inject schemas for domains that have actual entities on the instance. If the user has no `vacuum` entities, omit vacuum service schemas entirely. This is the simplest and highest-impact optimization.
2. **On-demand discovery**: Instead of injecting all schemas into every system prompt, the AI calls `discover(what="services", filter="climate")` before calling `do()` when it encounters an unfamiliar domain. This trades one extra tool call for significant token savings.
3. **Schema compression**: Strip verbose field descriptions and only inject field names + types + enums. Full descriptions can be fetched on demand via `discover()`.
4. **Startup measurement**: On first boot, measure the actual token count of the full schema dump and log it. If it exceeds a configurable threshold (e.g., `MAX_SCHEMA_TOKENS = 4000`), automatically fall back to domain filtering or on-demand mode.
5. **Caching**: Schema data changes rarely. Cache the compressed schema and only refresh on HA restart or config reload (listen for `homeassistant.restart` event or check on a 1-hour interval).

### 3.5 WebSocket API Requirements

Some HA registry operations required by `configure()` are **only available via the WebSocket API**, not REST. These include:

- `config/entity_registry/update` -- rename entities, disable/enable, assign areas
- `config/device_registry/update` -- assign devices to areas, remove devices
- `config/area_registry/create` / `delete` / `list` -- area CRUD
- `config/config_entries/get` -- integration configuration entries

**Implementation approach -- two options:**

| Approach | Complexity | Pros | Cons |
|----------|-----------|------|------|
| **Persistent WebSocket connection** | Higher | Real-time events, reuse connection, lower latency for rapid operations | Must handle reconnection, keepalive, concurrent message routing |
| **Transient connection per operation** | Lower | Simple, no state management, easy error handling | ~200ms overhead per operation (connect + auth + send + close) |

**Recommendation: Start with transient connections.** Config/registry operations are infrequent (a few per day at most, typically during setup or maintenance sessions). The ~200ms overhead per operation is negligible for this use case. The implementation pattern:

```python
async def ws_command(command: dict) -> dict:
    """Open a transient WebSocket connection, send one command, return the result."""
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(f"{WS_URL}/api/websocket") as ws:
            # 1. Receive auth_required
            await ws.receive_json()
            # 2. Send auth
            await ws.send_json({"type": "auth", "access_token": TOKEN})
            auth_result = await ws.receive_json()
            if auth_result["type"] != "auth_ok":
                raise AuthError(auth_result)
            # 3. Send command
            await ws.send_json({"id": 1, **command})
            # 4. Receive result
            result = await ws.receive_json()
            return result
```

A persistent connection can be added later (Phase 2+) if Apex needs real-time event subscriptions (e.g., listening for state changes without polling, or receiving `config_entry` update events).

### 3.6 Automatic Post-Action Verification

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

### 3.7 Error Handling as Middleware

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

### 3.8 Migration Path

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

### 3.9 Comparison Summary

| Aspect | Current (60+ tools) | Proposed (~9 tools) |
|--------|-------------------|-------------------|
| **Tool count** | 60+ | ~9 + memory tools |
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

## 7. Architectural Risks & Open Questions

Known risks, technical debt, and unresolved design decisions that should be addressed during implementation.

### 7.1 Test Coverage (Critical -- Phase 0 Blocker)

Overall coverage is **40%** (209 tests, 0 failing). The critical modules now have strong coverage:

| Module | Risk Level | Coverage | Target | Status |
|--------|-----------|----------|--------|--------|
| `conversation.py` | **Critical** | **100%** | 60%+ | **DONE** -- 39 tests covering tool loop, confabulation guard, explainability, background tasks |
| `context_builder.py` | **High** | **96%** | 60%+ | **DONE** -- 17 tests covering semantic search, fallback, core facts, presence/device/calendar integration |
| `fact_extractor.py` | **High** | **100%** | 60%+ | **DONE** -- 25 tests covering JSON parsing, corrections, expiry, input validation, error handling |
| `event_handler.py` | **Medium** | **84%** | 50%+ | **DONE** -- webhook processing, cooldowns, filtering, redundancy checks |

**Phase 0 gate: PASSED.** The three critical modules now have regression tests protecting them. Phase 1 (Generic Tools) can safely proceed -- the tool dispatch loop in `conversation.py` and context assembly in `context_builder.py` are covered.

### 7.2 Confabulation Surface in Generic Tools

The current confabulation guard detects when the LLM claims it performed a device action without making tool calls. With generic tools, a new confabulation vector emerges: the LLM constructs a plausible-looking `do()` call with **invented parameters** that the HA API silently ignores.

Example: `do("light", "turn_on", {"entity_id": "light.kitchen"}, {"mood": "romantic"})` -- HA ignores the unknown `mood` field, turns on the light at default settings, and the AI reports success. The user thinks "romantic mode" was applied.

**Mitigations:**
- **Schema-diff validation**: Before executing, `do()` should diff the requested `data` keys against the cached service schema for `{domain}.{service}`. Any key not present in the schema is flagged: "Warning: field 'mood' is not a known parameter for light.turn_on -- it will be ignored by HA." This catches hallucinated parameters before they reach the API.
- **Post-action state diff**: After executing, compare the requested `data` values against the actual resulting state and flag discrepancies ("Requested brightness_pct=50 but light is at 100% -- the parameter may not have been applied"). This catches cases where valid-looking parameters are accepted but silently ignored.
- **Audit trail**: Log every `do()` call with full request + response + state-before + state-after for post-incident review.

### 7.3 Conversation Loop Token Budget

The system prompt is rebuilt every turn and includes: persona, time context, 10 conversation turns, semantic facts (up to 20), presence summary, device summary, calendar, proactive hints, action trace, and (in the redesign) service schemas. This is a lot of context competing for a finite token window.

**Current estimated per-turn context:**

| Section | Est. Tokens |
|---------|-------------|
| Persona + rules | ~800 |
| Time + presence + calendar | ~300 |
| 10 conversation turns | ~1,500-3,000 |
| Semantic facts (20 max) | ~600 |
| Device summary | ~500-2,000 |
| Service schemas (new) | ~2,000-4,000 |
| Tool definitions (~9 tools) | ~600 |
| **Total** | **~6,200-11,700** |

With a 2,000-token `max_tokens` for the response, this fits within most model context windows but leaves limited room for long tool-calling loops (max 15 iterations, each adding tool call + result tokens). Monitor total token usage per turn and set alerts for when it approaches 80% of the model's context limit.

**Recommended schema injection strategy: on-demand by default.**

The 2,000-4,000 token estimate for service schemas assumes a moderate HA install. Real-world installs with 30+ integrations can push this to 8,000+ tokens, erasing the token savings that motivate the redesign. The recommended approach:

1. **Inject only top-5 domain schemas** into every prompt (light, climate, cover, fan, switch -- the domains used in >80% of commands). This costs ~800-1,200 tokens.
2. **On-demand for everything else.** The LLM calls `discover(what="services", filter="vacuum")` before calling `do()` for unfamiliar domains. One extra tool call per novel domain is a good trade for ~3,000 tokens saved per turn.
3. **Measure on first boot.** Log the full schema token count at startup. If it exceeds `MAX_SCHEMA_TOKENS` (default: 1500), automatically fall back to on-demand mode for long-tail domains.
4. **Cache aggressively.** Schemas change only on HA restart or config reload. Cache in memory and refresh on a 1-hour interval or `homeassistant.restart` event.

### 7.4 SQLite Under Concurrent Load

Both the conversation store and knowledge store use SQLite with `aiosqlite`. SQLite handles concurrent reads well but serializes writes. With webhooks, background fact extraction, and user conversations all writing simultaneously, write contention could cause latency spikes or `database is locked` errors under load.

**Status: RESOLVED.** WAL mode and busy_timeout are now enabled on both stores:

```python
# Both conversation_store.py and knowledge_store.py initialize():
await self._db.execute("PRAGMA journal_mode=WAL")
await self._db.execute("PRAGMA busy_timeout=5000")
```

WAL allows concurrent reads during writes -- exactly the pattern Apex uses (context builder reads facts while fact extractor writes them). The 5-second busy_timeout lets SQLite retry internally before raising `database is locked` errors.

**Further mitigations (if contention becomes measurable):**
- Add a write queue or connection pool for serializing writes from multiple async tasks.
- Monitor for `database is locked` errors in logs with a retry mechanism (exponential backoff, max 3 retries).

### 7.5 Event Handler Storm Resistance

The webhook cooldown (60s per entity:event_type) prevents basic reaction storms, but edge cases remain:

- **Area-wide events**: A "goodnight" automation that changes 20 entities fires 20 webhooks in rapid succession, each for a different entity_id. The per-entity cooldown doesn't help because each entity is unique. This could trigger 20 simultaneous AI conversations.
- **Cascading automations**: An AI-triggered action causes a state change, which fires a webhook, which triggers another AI response, creating a feedback loop.

**Mitigations (all three recommended for Phase 1):**

1. **Batch window (highest priority).** Buffer incoming webhooks for 2 seconds before processing. If multiple events arrive within the window, group them into a single AI prompt: "Multiple changes detected: kitchen light off, living room light off, bedroom light off." This converts 20 simultaneous AI calls into 1. Implementation: an `asyncio` debounce queue keyed on a global "batch slot" that flushes every 2 seconds.

2. **Self-action filter.** Track every `do()` call with a timestamp and entity_id in a short-lived set (TTL: 10 seconds). When a webhook arrives, check if the entity was recently acted on by Apex itself. If so, suppress the webhook. This breaks the cascading automation feedback loop.

3. **Global rate limit.** Cap webhook-triggered AI conversations at 5 per minute, regardless of entity. Events that exceed the limit are queued and batched into the next available slot. This is the safety net that catches anything the batch window and self-action filter miss.

### 7.6 Phase Dependency Chain

The ROADMAP phases are not independent -- each phase depends on the one before it being solid:

```
Phase 0 (Stabilize)
  └──► Phase 1 (Generic Tools)     -- rewrites code that Phase 0 tests protect
        └──► Phase 2 (Proactive)   -- needs generic do()/query() to act autonomously
              └──► Phase 3 (Voice) -- proactive behavior drives most voice interactions
                    └──► Phase 4 (Multi-User) -- voice ID feeds into per-user routing
```

**Risk:** The temptation to start Phase 1 before Phase 0 is complete, or to pull "easy" items from Phase 2/3 while Phase 1 is in progress. This creates technical debt that compounds: a half-finished Generic Tools layer makes Proactive Intelligence harder, not easier.

**Mitigation:** Treat phase boundaries as hard gates. A phase is not complete until:
1. All checklist items are checked in `ROADMAP.md`
2. All tests pass (`pytest` green)
3. Live HA validation confirms no regressions
4. The architecture doc is updated to reflect what was actually built (not just what was planned)

The one exception: **Phase 0 quick-wins that don't touch core modules** (e.g., enabling WAL mode, fixing the `notify.py` hardcoded target) can be done at any time since they carry no regression risk.

**Status update:** Phase 0 is nearly complete. WAL mode is enabled, `notify.py` target is configurable, test coverage targets are exceeded, and the `test_settings_defaults` flake is fixed. The remaining Phase 0 item is the vacuum tool entity name dynamic resolution.

### 7.7 Operational Risk: System-Level Access via manage() and configure()

Giving the LLM system-level access to the HA instance (beyond device control) introduces a new class of risk: **operational disruption from hallucinated or misinterpreted system commands.**

**Risk scenarios:**

| Risk | Trigger | Impact |
|------|---------|--------|
| **Unintended HA update** | Hallucinated `manage("update", "core")` | Triggers a core update + restart at a bad time. HA goes offline, automations stop, voice control lost. If the update introduces breaking changes, recovery requires manual intervention. |
| **Backup restore wipes state** | Hallucinated `manage("backup", "restore", config={"backup_id": "..."})` | Restores an old snapshot, destroying current state: entity customizations, recent automations, input helper values, and anything changed since the backup was taken. |
| **Critical entity disabled** | Hallucinated `configure("disable", "binary_sensor.smoke_detector_kitchen")` | Disables a safety sensor. HA automations that depend on it (fire alerts, alarms) stop working silently. The user may not notice until an actual event occurs. |
| **Device removal** | Hallucinated `configure("remove", device_id)` | Permanently removes a device and all its entities. Re-adding requires reconfiguration and may break automations that referenced those entities. |
| **Add-on misconfiguration** | `manage("install", "addon:some_slug", config={...})` with wrong config | Installs or reconfigures an add-on with incorrect settings. Could expose ports, change network settings, or break other add-ons. |

**Mitigations (all required for Phase 1):**

1. **Tiered confirmation system.** Operations are classified into three tiers:

   ```
   Tier 0 (Safe -- no confirmation):
     - backup/create, backup/list, health, logs
     - rename, assign_area, enable, create_area, list_stale

   Tier 1 (Disruptive -- confirmation required):
     - update/core, update/os, update/addon, restart/core, restart/addon
     - install/addon, disable, delete_area

   Tier 2 (Destructive -- confirmation + summary of impact):
     - backup/restore, backup/delete, remove (device)
   ```

   For Tier 1, `manage()`/`configure()` returns a confirmation prompt: "About to restart HA Core. This will cause ~30 seconds of downtime. Confirm?" The LLM relays this to the user and only executes on explicit "yes."

   For Tier 2, the tool first performs a dry-run that shows the full impact: "Restoring backup 'daily_2026-02-17' will revert the system to Feb 17 state. Changes since then: 3 new automations, 12 entity customizations, 47 state changes. Proceed?" Only explicit user approval triggers execution.

2. **Audit logging.** Every `manage()` and `configure()` call is logged to a dedicated audit table in SQLite:

   ```
   ┌───────────────────────────────────────────────────┐
   │  system_audit_log table                            │
   ├───────────────────────────────────────────────────┤
   │  id          INTEGER PRIMARY KEY                   │
   │  timestamp   TEXT (ISO 8601)                       │
   │  tool        TEXT ("manage" | "configure")         │
   │  action      TEXT                                  │
   │  target      TEXT                                  │
   │  config_json TEXT (serialized config/data)         │
   │  result      TEXT ("confirmed" | "executed" |      │
   │              "denied" | "error")                   │
   │  session_id  TEXT (voice | chat | webhook)         │
   │  user_approved BOOLEAN                             │
   └───────────────────────────────────────────────────┘
   ```

   This provides a full audit trail for post-incident review ("what did Apex change on the system in the last 24 hours?").

3. **Dry-run mode for configure().** All `configure()` operations support a `dry_run` flag (via `data={"dry_run": true}`) that returns what *would* change without applying it. The LLM should always call dry-run first for Tier 1+ operations and present the preview to the user.

4. **Session-based escalation.** Webhook-triggered sessions (`session_id="apex_events"`) are restricted to Tier 0 operations only. The rationale: a state-change event should never autonomously trigger a system update or entity disable. Only direct user conversations (voice or chat) can escalate to Tier 1 and Tier 2.

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
