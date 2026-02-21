# Apex Brain -- Architecture Document

> **Version:** 0.7.0
> **Last updated:** 2026-02-21
> **Scope:** Current architecture with Phase 1 Generic Tools COMPLETE (do, query, discover, history, manage, configure) + MCP Bridge integration

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Key Components](#2-key-components) (incl. 2.7 MCP Bridge)
3. [Generic Tools Architecture (Phase 1 -- COMPLETE)](#3-generic-tools-architecture-phase-1----complete)
4. [Voice Pipeline Architecture](#4-voice-pipeline-architecture)
5. [Data Flow Diagrams](#5-data-flow-diagrams)
6. [Technology Stack](#6-technology-stack)
7. [Architectural Risks & Open Questions](#7-architectural-risks--open-questions)
8. [Appendix: Tool Inventory](#appendix-tool-inventory)

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
    │   ├── context_builder.py      # Assembles system prompt context
    │   └── audit_store.py          # System audit log (manage/configure calls)
    │
    ├── tools/                      # Auto-discovered tool modules
    │   ├── __init__.py             # discover_tools() via pkgutil
    │   ├── base.py                 # @tool decorator + TOOL_REGISTRY
    │   ├── generic.py              # PRIMARY: do(), query(), discover(), history() (862 lines)
    │   ├── manage.py               # PRIMARY: manage() — Supervisor API ops + tiered confirmation
    │   ├── configure.py            # PRIMARY: configure() — registry ops via WebSocket + tiered confirmation
    │   ├── ws_helpers.py           # WebSocket helper (transient connections, no @tool)
    │   ├── mcp_bridge.py           # MCP server integration (SSE/HTTP, tool discovery + execution)
    │   ├── smart_home.py           # [DEPRECATED] thin wrapper delegating to generic tools
    │   ├── ha_helpers.py           # Shared HA API client + helpers (no @tool)
    │   ├── automation.py           # Automation CRUD, scenes
    │   ├── vacuum.py               # Vacuum control + room cleaning
    │   ├── notify.py               # Notifications + Alexa announcements
    │   ├── knowledge.py            # remember / recall / forget
    │   ├── routines.py             # Named multi-step routines
    │   ├── calendar_tool.py        # Google Calendar (service account)
    │   ├── datetime_tool.py        # Current time
    │   ├── weather.py              # Weather forecasts
    │   ├── presence.py             # [DEPRECATED] thin wrapper delegating to generic tools
    │   ├── lock.py                 # [DEPRECATED] thin wrapper delegating to generic tools
    │   ├── switch.py               # [DEPRECATED] thin wrapper delegating to generic tools
    │   ├── security.py             # [DEPRECATED] thin wrapper delegating to generic tools
    │   ├── energy.py               # [DEPRECATED] thin wrapper delegating to generic tools
    │   ├── history.py              # [DEPRECATED] thin wrapper delegating to generic tools
    │   ├── template.py             # [DEPRECATED] thin wrapper delegating to generic tools
    │   ├── system_info.py          # [DEPRECATED] thin wrapper delegating to generic tools
    │   ├── input_helpers.py        # [DEPRECATED] thin wrapper delegating to generic tools
    │   ├── todo.py                 # Shopping/todo list management
    │   ├── script.py               # [DEPRECATED] thin wrapper delegating to generic tools
    │   ├── config_reload.py        # [DEPRECATED] thin wrapper delegating to generic tools
    │   ├── webhook.py              # Fire webhooks + custom events
    │   └── wait_tool.py            # Timed delays between tool calls
    │
    └── tests/                      # 25+ test files, 423 tests
        ├── test_config.py
        ├── test_conversation.py      # 39 tests — orchestrator coverage
        ├── test_context_builder.py   # 17 tests — context assembly coverage
        ├── test_fact_extractor.py    # 25 tests — background extraction coverage
        ├── test_generic.py           # 75 tests — do(), query(), discover(), history()
        ├── test_smart_home.py
        ├── test_vacuum.py
        ├── test_webhook.py
        ├── test_ha_helpers.py
        ├── test_manage.py            # 53 tests — manage() + tiered confirmation
        ├── test_configure.py         # 49 tests — configure() + dry-run + WS mocks
        ├── test_audit_store.py       # 9 tests — audit logging
        ├── test_mcp_bridge.py       # 17 tests — MCP bridge integration
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
                    │  │  MCP bridge ──► Remote MCP servers (optional)   │     │
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

> **Note on API surfaces:** Apex communicates with three distinct HA APIs, plus optional MCP servers.
> The **Core REST API** handles entity state reads and service calls (the primary interface for `do()` and `query()`).
> The **Supervisor API** (`http://supervisor/<endpoint>`) handles system operations via `manage()` -- backups,
> add-on management, OS/core updates, and hardware/network info. The **WebSocket API**
> (`ws://supervisor/core/websocket`) is used by `configure()` via `ws_helpers.py` for config/registry operations
> (entity rename, area management, device registry, config entries) that are not exposed via REST.
> The **MCP Bridge** (optional) connects to remote MCP servers via SSE or Streamable HTTP, enabling
> dynamic tool discovery and execution from external sources (e.g., `ha-mcp` for richer HA integrations,
> or third-party MCP servers for Spotify, custom APIs, etc.).

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
1.  Configure logging
2.  Set API keys in environment
3.  Initialize ConversationStore (SQLite)
4.  Initialize KnowledgeStore (SQLite + embeddings)
5.  Initialize FactExtractor (background AI)
6.  Initialize ContextBuilder
7.  discover_tools() -- auto-import all tool modules
8.  Inject KnowledgeStore into tools that need it
9.  Connect MCP Bridge (if MCP_SERVER_URL configured)
    a. MCPBridge.connect() -- open SSE or Streamable HTTP transport
    b. MCPBridge.discover_tools() -- fetch remote tools, skip native collisions
10. Create Conversation orchestrator (with MCP bridge reference)
11. Create EventHandler (if webhooks enabled)
12. Server ready
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
│                      │  - Service schemas (top-5 domains)
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
│  Route each tool call  Return text response        │
│  ┌─ TOOL_REGISTRY? ─┐ (with confabulation check)  │
│  │ YES → native      │                             │
│  │ NO  → MCP bridge? │                             │
│  │   YES → remote    │                             │
│  │   NO  → error     │                             │
│  └───────────────────┘                             │
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

#### Layer 3: Audit Store (`memory/audit_store.py`)

Added in Phase 1. SQLite WAL-mode logging of all `manage()` and `configure()` calls. Provides a full audit trail for post-incident review ("what did Apex change on the system in the last 24 hours?"). See [Section 7.7](#77-operational-risk-system-level-access-via-manage-and-configure) for schema details. 9 tests in `test_audit_store.py`.

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
│  8. Service schemas (top-5 domains)  │──► cached from GET /api/services
│                                      │
│  All sections injected into:         │
│  SYSTEM_PROMPT_TEMPLATE              │
│  + proactive hints                   │
│  + device block                      │
│  + service schemas                   │
└──────────────────────────────────────┘
```

### 2.4 System Prompt (`brain/system_prompt.py`)

The system prompt is dynamically rebuilt for every turn. It contains:

1. **Persona**: Apex's personality (J.A.R.V.I.S.-inspired, dry wit, anticipatory, reliable)
2. **Context block**: Time, presence, calendar, known facts, recent conversation
3. **Smart home instructions**: Generic tool usage guide (`do()`, `query()`, `discover()`, `history()`)
4. **Service schemas**: Top-5 domain schemas (light, climate, cover, fan, switch) for `do()` parameter construction
5. **Device block**: Current entity IDs and states (injected from HA)
6. **Routines section**: How to define and execute routines
7. **Rules**: Conciseness, natural knowledge reference, no fabrication
8. **Proactive behavior guidelines**: Time-aware, context-aware suggestions
9. **Explainability**: How to trace and explain decisions
10. **Proactive hints**: Dynamic hints based on time of day, presence, calendar

### 2.5 Tool System

#### Architecture: Generic Tools (Primary) + Legacy Wrappers (Deprecated)

As of Phase 1, the tool system uses a **two-tier architecture**:

- **Primary tools (6):** `do()`, `query()`, `discover()`, `history()` in `tools/generic.py`; `manage()` in `tools/manage.py`; `configure()` in `tools/configure.py`. These are the tools the LLM is instructed to use via the system prompt.
- **Legacy tools (~56, deprecated):** Domain-specific tools in `smart_home.py`, `lock.py`, `switch.py`, `energy.py`, `history.py`, `template.py`, `system_info.py`, `input_helpers.py`, `script.py`, `config_reload.py`, `security.py`, `presence.py`. These are now thin wrappers that delegate to the generic tools and emit deprecation warnings. They remain registered in `TOOL_REGISTRY` for backward compatibility but are not promoted in the system prompt. Full removal is deferred to Phase 2.
- **Standalone tools (unchanged):** `knowledge.py`, `routines.py`, `calendar_tool.py`, `datetime_tool.py`, `weather.py`, `vacuum.py`, `notify.py`, `automation.py`, `todo.py`, `webhook.py`, `wait_tool.py`. These either have no generic equivalent yet or are already clean.

**Total registered tools: ~68 across 22 modules** (6 primary + ~56 deprecated wrappers + ~6 standalone).

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
Tool function (do(), query(), or legacy wrapper)
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

The generic `do()` tool follows this pattern:
1. Construct service call payload from `domain`, `service`, `targets`, and `data`
2. Call `call_ha_service()` via the REST API
3. Wait 500ms for state to settle
4. Read back entity state via `verify_generic()` in `tools/generic.py`
5. Return human-readable confirmation with domain-aware attribute formatting

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

### 2.7 MCP Bridge (`tools/mcp_bridge.py`)

The MCP (Model Context Protocol) Bridge connects Apex to external MCP servers, enabling tool discovery and execution from remote sources. This allows Apex to extend its capabilities beyond native tools — for example, connecting to an HA MCP server for richer integrations or third-party services (Spotify, custom APIs, community tools).

#### Architecture

```
                  ┌──────────────────────────────────────┐
                  │          Conversation Loop            │
                  │                                      │
                  │  LLM generates tool_call             │
                  │         │                            │
                  │    ┌────┴──────────────┐             │
                  │    │                   │             │
                  │    ▼                   ▼             │
                  │  TOOL_REGISTRY?    MCP bridge?       │
                  │  (native tools)    (remote tools)    │
                  │    │                   │             │
                  │    ▼                   ▼             │
                  │  execute_tool()   mcp_bridge.        │
                  │  (local)          execute_tool()     │
                  │                   (remote via SSE)   │
                  └──────────────────────────────────────┘
                                       │
                                       ▼
                  ┌──────────────────────────────────────┐
                  │         Remote MCP Server             │
                  │  (e.g. ha-mcp, Spotify MCP, etc.)    │
                  │                                      │
                  │  SSE or Streamable HTTP transport     │
                  │  Tool discovery (list_tools)          │
                  │  Tool execution (call_tool)           │
                  └──────────────────────────────────────┘
```

#### Connection Lifecycle

1. **Startup**: If `MCP_SERVER_URL` is configured, `MCPBridge` initializes with the URL and transport type
2. **Connect**: Opens an SSE or Streamable HTTP transport, creates a `ClientSession`, calls `session.initialize()`
3. **Discover**: Requests `list_tools()` from the server, filters out tools that collide with `TOOL_REGISTRY` names (native tools always take priority)
4. **Schema conversion**: Converts MCP tool input schemas to OpenAI function-calling format, with Gemini compatibility enforcement (every property must have an explicit `type` field)
5. **Runtime**: Tool calls route through `conversation.py` — native first (`TOOL_REGISTRY`), then MCP (`mcp_bridge.has_tool()`)
6. **Shutdown**: Clean disconnect of session and transport on server shutdown

#### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Native tools take priority** | If a tool name exists in both `TOOL_REGISTRY` and MCP, the native version is used. Prevents MCP servers from silently overriding tested, audited tools. |
| **Persistent session** | MCPBridge maintains a single session for the server lifetime (connect once at startup, disconnect at shutdown). Avoids per-call connection overhead. |
| **Graceful degradation** | If MCP connection fails, Apex continues with native tools only. No hard dependency on MCP availability. |
| **Gemini property type enforcement** | `_ensure_property_types()` adds `"type": "string"` to any schema property missing a type field. Gemini (via LiteLLM) rejects schemas without explicit types. |

#### Implementation

```python
# tools/mcp_bridge.py — MCPBridge class (254 lines)

class MCPBridge:
    async def connect()           # Open transport + session
    async def disconnect()        # Clean up on shutdown
    async def discover_tools()    # List tools, skip collisions
    def get_openai_tool_definitions()  # Convert to OpenAI format
    def has_tool(name)            # Check if name is an MCP tool
    async def execute_tool(name, args)  # Forward call to MCP server
```

**Integration points:**
- `brain/server.py` (startup/shutdown): Creates MCPBridge, connects, discovers tools, passes to Conversation
- `brain/conversation.py` (tool routing): Merges MCP tool definitions with native; routes execution by checking `TOOL_REGISTRY` first, then `mcp_bridge.has_tool()`
- `brain/config.py`: `mcp_server_url` and `mcp_transport` settings

**Tests:** 17 test classes in `tests/test_mcp_bridge.py` covering initialization, connection, discovery, schema conversion, tool execution, error handling, and graceful degradation. All mocked (no live MCP server required).

### 2.8 Configuration (`brain/config.py`)

Uses Pydantic Settings for type-safe configuration from environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `LITELLM_MODEL` | `gemini/gemini-2.5-pro` | AI model for conversation |
| `OPENAI_API_KEY` | (empty) | OpenAI API key |
| `ANTHROPIC_API_KEY` | (empty) | Anthropic API key |
| `GEMINI_API_KEY` | (empty) | Gemini API key |
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
| `MCP_SERVER_URL` | (empty) | MCP server endpoint (e.g., `http://ha-ip:8080/sse`) |
| `MCP_TRANSPORT` | `sse` | Transport type: `sse` or `streamable_http` |
| `PORT` | 8080 | Server port |

Auth token resolution order:
1. `SUPERVISOR_TOKEN` env var (injected by HA Supervisor inside add-on)
2. `HA_TOKEN` from settings / `.env`
3. S6 container environment file (fallback for edge cases)

**Supervisor API auth note:** The `SUPERVISOR_TOKEN` already grants full access to the Supervisor API (`http://supervisor/*`) -- no additional credentials are needed. When running as an HA add-on, Apex can call Supervisor endpoints (backups, add-ons, core/OS updates, hardware info) using the same token that authenticates Core REST API requests. The token is passed as `Authorization: Bearer <SUPERVISOR_TOKEN>` to both APIs. In local dev mode, the Supervisor API is not available (it only exists inside HAOS), so `manage()` operations will return an appropriate error message.

---

## 3. Generic Tools Architecture (Phase 1 -- COMPLETE)

> **Status: IMPLEMENTED.** All Phase 1 generic tools are built, tested, and operational. Legacy tools have been converted to thin wrappers that delegate to the generic layer. Test coverage: 423 tests total; 75 generic, 53 manage, 49 configure, 9 audit store.

### 3.1 The Problem (Solved)

The pre-Phase 1 system had **60+ individual tools** -- each HA domain got its own tool with hardcoded parameters, enum values, and verification logic. Examples:

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

**Problems this caused:**

1. **Finite capability**: The AI could only do what we pre-built tools for. New HA integrations, services, or entity types required new tool code.
2. **Token bloat**: 60+ tool definitions consumed a significant portion of the context window. Every turn sent all tool schemas to the LLM.
3. **Parameter rigidity**: Each tool's parameters were frozen at development time. HA services often accept additional data fields that the tool didn't expose.
4. **Maintenance burden**: Every HA update that added services or changed schemas required updating tool code, tests, and system prompt instructions.
5. **Confabulation surface**: With so many similar tools, the LLM sometimes picked the wrong one or invented parameters that didn't exist.

### 3.2 The Solution: 6 Generic Power Tools (Implemented)

The domain-specific tools were replaced with a small set of generic tools that give the AI direct, unrestricted access to the HA API and system management. The AI uses HA service schemas (injected into the system prompt) to construct the right calls, and has system administration capabilities via the Supervisor and WebSocket APIs.

```
┌────────────────────────────────────────────────────────────────────┐
│                     LEGACY (60+ tools, now deprecated wrappers)     │
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

                              │ delegate to
                              ▼

┌────────────────────────────────────────────────────────────────────┐
│              GENERIC TOOLS (6 primary, all implemented)             │
│                                                                    │
│  do()         query()      discover()      history()               │
│  manage()     configure()                                          │
│                                                                    │
│  Files: tools/generic.py (862 lines), tools/manage.py,            │
│         tools/configure.py, tools/ws_helpers.py                    │
│  Tests: 75 + 53 + 49 + 9 = 186 dedicated tests                   │
└────────────────────────────────────────────────────────────────────┘
```

### 3.3 Tool Specifications

#### `do(domain, service, targets, data)` -- Universal Service Caller

> **File:** `tools/generic.py` | **Tests:** `tests/test_generic.py` (75 tests total for all generic tools)

**Replaced:** `control_light`, `control_climate`, `control_fan`, `control_cover`, `control_lock`, `control_switch`, `control_alarm`, `control_vacuum`, `control_media`, `control_area`, `call_service`, `set_input_helper`, `activate_scene`, `trigger_automation`, `toggle_automation`, `execute_script`, `reload_config`

```python
@tool(description="Call ANY Home Assistant service. Use service schemas from context to build the correct call.")
async def do(
    domain: str,           # e.g. "light", "climate", "vacuum"
    service: str,          # e.g. "turn_on", "set_temperature"
    targets: dict = None,  # {"entity_id": "..."} or {"area_id": "..."} or {"device_id": "..."}
    data: dict = None,     # Service-specific data, e.g. {"brightness_pct": 50, "color_temp_kelvin": 3000}
) -> str:
    """
    1. Validate data keys against cached service schema (flags unknown parameters)
    2. Call POST /api/services/{domain}/{service} with targets + data
    3. Wait 500ms for state to settle
    4. Read back entity state for verification via verify_generic()
    5. Return: "Done. {entity_friendly_name}: {new_state} ({relevant_attributes})"
    """
```

**Key behavior:**
- Automatic post-action verification: after calling the service, reads the entity state back and reports it via `verify_generic()` with domain-aware attribute formatting
- Accepts `area_id` or `device_id` targeting (not just `entity_id`)
- Schema validation: diffs requested `data` keys against cached service schema, warns about unknown parameters before execution
- Error messages include the HA response body for debugging

**Security considerations (IMPORTANT):**

Giving the LLM unrestricted access to call any HA service is powerful but dangerous. A single hallucinated or misinterpreted service call could disarm the alarm, unlock the front door, or disable security cameras. Mitigations:

1. **Sensitive domain gate**: Maintain a configurable list of security-critical domains that require extra safeguards:
   - `lock` (door locks)
   - `alarm_control_panel` (arm/disarm)
   - `camera` (disable/snapshot)
   - `cover` (garage doors)
   - `automation` (delete/disable safety automations)
2. **Confirmation step**: For actions on gated domains, `do()` returns a confirmation prompt ("About to unlock front_door. Confirm?") instead of executing immediately. The LLM relays this to the user and only executes on explicit approval.
3. **Allowlist/denylist config**: Add `PROTECTED_DOMAINS` and `BLOCKED_SERVICES` to `config.py` so the user can customize which actions require confirmation or are outright forbidden (e.g., `lock.unlock` from voice commands while away).
4. **Audit log**: Every `do()` call is logged with timestamp, domain, service, targets, and the originating session (voice vs. chat vs. webhook) via `memory/audit_store.py`.

#### `query(target)` -- Universal State Reader

> **File:** `tools/generic.py` | Auto-detects entity_id vs Jinja2; domain-aware attribute formatting; smart 404 fallback

**Replaced:** `get_entity_state`, `query_sensors`, `get_weather`, `get_presence`, `get_energy_summary`, `get_entity_power`, `evaluate_template`

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

> **File:** `tools/generic.py` | Supports: entities, services (with full schemas), areas, devices, integrations, info

**Replaced:** `list_entities`, `list_services`, `get_areas`, `list_devices`, `list_integrations`, `get_ha_info`, `list_input_helpers`, `list_automations`, `list_scenes`, `list_scripts`

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

**Critical for the redesign**: When `what="services"`, the response includes full service schemas (field names, types, required/optional). This is how the AI learns what parameters `do()` accepts for any given service -- either from the injected top-5 schemas or via on-demand discovery for unfamiliar domains.

#### `history(entity_id, hours, mode)` -- State History + Logbook

> **File:** `tools/generic.py` | Two modes: "changes" (state transitions) and "logbook" (human-readable events); deduplication; caps at 50 entries

**Replaced:** `get_history`, `get_logbook`

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

#### `automate(action, config)` -- Automation/Scene/Script CRUD (Phase 2)

**Will replace:** `create_automation`, `update_automation`, `delete_automation`, `list_automations`, `trigger_automation`, `toggle_automation`, `list_scenes`, `activate_scene`, `list_scripts`, `execute_script`

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

#### `notify(target, message, data)` -- Notifications + Announcements (Phase 2)

**Will replace:** `send_notification`, `announce`

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

> **File:** `tools/manage.py` | **Tests:** `tests/test_manage.py` (53 tests)

New capability added in Phase 1 -- extends Apex from device control to full system administration.

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

**Tiered confirmation (implemented):**

| Operation | Risk Level | Tier | Confirmation Required? |
|-----------|-----------|------|----------------------|
| `backup/create` | **Safe** | 0 | No -- creating a backup is non-destructive |
| `backup/list` | **Safe** | 0 | No -- read-only |
| `health` | **Safe** | 0 | No -- read-only diagnostics |
| `logs` | **Safe** | 0 | No -- read-only |
| `backup/restore` | **DESTRUCTIVE** | 2 | **Yes** -- dry-run + impact summary first |
| `backup/delete` | **Destructive** | 2 | **Yes** -- dry-run + impact summary first |
| `update/core` | **Disruptive** | 1 | **Yes** -- confirmation prompt |
| `update/os` | **Disruptive** | 1 | **Yes** -- confirmation prompt |
| `update/addon` | **Disruptive** | 1 | **Yes** -- confirmation prompt |
| `restart/core` | **Disruptive** | 1 | **Yes** -- confirmation prompt |
| `restart/addon` | **Disruptive** | 1 | **Yes** -- confirmation prompt |
| `install/addon` | **Moderate** | 1 | **Yes** -- confirmation prompt |

#### `configure(action, target, data)` -- Entity/Device/Area Registry Management via WebSocket API

> **File:** `tools/configure.py` | **Tests:** `tests/test_configure.py` (49 tests) | **WebSocket:** `tools/ws_helpers.py`

New capability added in Phase 1 -- enables Apex to organize and maintain the HA instance.

```python
@tool(description="Organize HA: rename entities, manage areas, configure integrations, clean up stale devices.")
async def configure(
    action: str,     # "rename", "assign_area", "disable", "enable", "create_area",
                     # "delete_area", "remove", "list_stale"
    target: str = "",  # entity_id, device_id, or area name
    data: dict = None,  # e.g., {"name": "Kitchen Light", "area_id": "kitchen"}
) -> str:
    """
    Uses HA WebSocket API via ws_helpers.py for registry operations not available via REST:

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

    Opens a transient WebSocket connection per operation via ws_helpers.py.
    Returns human-readable confirmation of what changed.
    """
```

**Tiered confirmation (implemented):**

| Operation | Risk Level | Tier | Confirmation Required? |
|-----------|-----------|------|----------------------|
| `rename` | **Safe** | 0 | No -- cosmetic change, easily reversible |
| `assign_area` | **Safe** | 0 | No -- organizational, easily reversible |
| `enable` | **Safe** | 0 | No -- restores functionality |
| `create_area` | **Safe** | 0 | No -- additive, no side effects |
| `list_stale` | **Safe** | 0 | No -- read-only |
| `disable` | **Moderate** | 1 | **Yes** -- confirmation prompt |
| `delete_area` | **Moderate** | 1 | **Yes** -- confirmation prompt |
| `remove` | **Destructive** | 2 | **Yes** -- dry-run + impact summary first |

For Tier 1+ operations, `configure()` performs a **dry-run** that shows what would change (e.g., "This will disable binary_sensor.front_door_contact and remove it from automations X and Y. Confirm?") before applying.

#### Memory Tools (unchanged)

`remember(key, value)`, `recall(query)`, `forget(key)` -- These are already clean and generic. Keep them unchanged, along with the routine tools (`define_routine`, `list_routines`, `run_routine`, `delete_routine`).

### 3.4 Service Schema Injection (Implemented)

The key enabler for generic tools is injecting HA service schemas into the system prompt. Without this, the AI would not know what parameters `light.turn_on` accepts.

**Implementation (live in `brain/system_prompt.py` and `memory/context_builder.py`):**

The top-5 most common domains (light, climate, cover, fan, switch) are injected into every system prompt. Schemas are fetched from `GET /api/services`, compressed to field names + types + enums, and cached in memory with an hourly refresh interval. Token count logging is active -- the injected schemas consume ~800-1,200 tokens per turn.

```python
# Injected into system prompt each turn:
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

This replaced the previous approach of hardcoding service knowledge into each tool's parameter schema. The AI reads the schema and constructs the correct `data` dict for `do()`.

**Token budget**: The top-5 domain schemas cost ~800-1,200 tokens per turn. This is significantly less than the previous 60+ tool definitions (~8,000-12,000 tokens).

**Filtering strategy (implemented):**

1. **Top-5 domain injection**: Only the five most common domains are injected every turn. This provides coverage for >80% of commands at minimal token cost.
2. **On-demand discovery**: For unfamiliar domains, the AI calls `discover(what="services", filter="vacuum")` before calling `do()`. One extra tool call per novel domain is a good trade for ~3,000 tokens saved per turn.
3. **Schema compression**: Verbose field descriptions are stripped; only field names + types + enums are injected. Full descriptions are available via `discover()`.
4. **Hourly cache**: Schema data is cached in memory and refreshed on a 1-hour interval. Changes are rare (only on HA restart or config reload).

### 3.5 WebSocket API (Implemented)

Some HA registry operations required by `configure()` are **only available via the WebSocket API**, not REST. These include:

- `config/entity_registry/update` -- rename entities, disable/enable, assign areas
- `config/device_registry/update` -- assign devices to areas, remove devices
- `config/area_registry/create` / `delete` / `list` -- area CRUD
- `config/config_entries/get` -- integration configuration entries

**Implementation: Transient connections per operation** via `tools/ws_helpers.py`.

Config/registry operations are infrequent (a few per day at most, typically during setup or maintenance sessions). The ~200ms overhead per operation (connect + auth + send + close) is negligible for this use case. The implementation:

```python
# tools/ws_helpers.py
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

### 3.6 Automatic Post-Action Verification (Implemented)

Previously, each domain tool had its own verification function (`_verify_light`, `_verify_climate`, `_verify_media`). The generic `do()` tool now uses `verify_generic()` in `tools/generic.py`:

```python
async def verify_generic(domain: str, entity_id: str) -> str:
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
Phase 1: COMPLETE
         ├── do(), query(), discover(), history() implemented in tools/generic.py
         ├── manage() implemented in tools/manage.py
         ├── configure() implemented in tools/configure.py
         ├── ws_helpers.py provides WebSocket transport
         ├── audit_store.py logs all manage/configure calls
         ├── Legacy tools converted to thin wrappers delegating to generic tools
         ├── Legacy wrappers emit deprecation warnings
         ├── System prompt updated to prefer generic tools
         ├── Service schema injection operational (top-5 domains, hourly cache)
         └── 423 tests passing (186 for Phase 1 tools specifically)

Phase 2: Remove legacy wrappers + add automate() and notify()
         ├── Delete deprecated wrapper code from legacy tool files
         ├── Implement automate() for automation/scene/script CRUD
         ├── Implement notify() for notifications + announcements
         ├── System prompt simplified (no legacy tool instructions)
         └── Service schemas become the single source of truth
```

### 3.9 Comparison Summary

| Aspect | Legacy (60+ tools) | Generic (6 primary tools) |
|--------|-------------------|-------------------|
| **Tool count** | 60+ | 6 primary + memory/routine tools |
| **Token usage** (tool defs) | ~8,000-12,000 | ~2,000-3,200 (incl. top-5 schemas) |
| **New HA service support** | Required new code | Automatic (schema injection) |
| **Parameter accuracy** | Hardcoded, may drift | Live from HA API |
| **Verification** | Per-domain functions | `verify_generic()` with domain hints |
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

### 5.3 MCP Tool Execution Flow

```
LLM generates tool_call(name="mcp_tool_x", args={...})
        │
        ▼
┌───────────────────────┐
│  conversation.py      │
│  Tool routing          │
│                        │
│  1. Check TOOL_REGISTRY│──► Found? Execute native tool
│                        │
│  2. Check MCP bridge   │──► Found? Forward to MCP server
│     mcp_bridge.has_tool│
│                        │
│  3. Neither?           │──► Return "Unknown tool: ..."
└───────────┬────────────┘
            │ (MCP path)
            ▼
┌───────────────────────┐
│  mcp_bridge.           │
│  execute_tool()        │
│                        │
│  session.call_tool(    │
│    name, arguments)    │
│                        │
│  Over existing SSE     │
│  session (persistent)  │
└───────────┬────────────┘
            │
            ▼
┌───────────────────────┐
│  Remote MCP Server     │
│  Processes tool call   │
│  Returns CallToolResult│
│  (TextContent, Image,  │
│   EmbeddedResource)    │
└───────────┬────────────┘
            │
            ▼
┌───────────────────────┐
│  _extract_text()       │
│  Parse result content  │
│  into string for LLM   │
└───────────────────────┘
```

### 5.4 Memory Cycle (Conversation --> Fact Extraction --> Future Context)

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
| **WebSocket client** | aiohttp | latest | Transient WS connections for registry ops (`ws_helpers.py`) |
| **Database** | SQLite | (stdlib) | Conversations + knowledge + embeddings + audit log |
| **SQLite driver** | aiosqlite | latest | Async SQLite access |
| **Embeddings** | numpy | latest | Cosine similarity computation |
| **Config** | Pydantic Settings | latest | Type-safe env var config |
| **Validation** | Pydantic | v2 | Request/response models |
| **MCP client** | mcp | >=1.25,<2 | Model Context Protocol client (SSE + Streamable HTTP) |

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
| **Google** | gemini-2.5-pro, gemini-2.0-flash | Primary conversation |
| **Anthropic** | claude-sonnet-4, claude-opus-4 | Alternative |
| **OpenAI** | gpt-4o, gpt-4o-mini | Conversation + fact extraction |
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
| **pytest** | Test framework (423 tests) |
| **pre-commit** | Secret scanning on commits |
| **GitHub Actions** | CI: test + lint + secret check |

---

## 7. Architectural Risks & Open Questions

Known risks, technical debt, and unresolved design decisions.

### 7.1 Test Coverage

Overall coverage: **423 tests, 0 failing.** Phase 0 and Phase 1 modules have strong coverage:

| Module | Risk Level | Tests | Status |
|--------|-----------|-------|--------|
| `conversation.py` | **Critical** | 39 | **DONE** -- tool loop, confabulation guard, explainability, background tasks |
| `context_builder.py` | **High** | 17 | **DONE** -- semantic search, fallback, core facts, presence/device/calendar integration |
| `fact_extractor.py` | **High** | 25 | **DONE** -- JSON parsing, corrections, expiry, input validation, error handling |
| `event_handler.py` | **Medium** | ~20 | **DONE** -- webhook processing, cooldowns, filtering, redundancy checks |
| `tools/generic.py` | **Critical** | 75 | **DONE** -- do(), query(), discover(), history() with verification |
| `tools/manage.py` | **High** | 53 | **DONE** -- manage() + all tiered confirmation paths |
| `tools/configure.py` | **High** | 49 | **DONE** -- configure() + dry-run + WS mocks |
| `memory/audit_store.py` | **Medium** | 9 | **DONE** -- audit logging |
| `tools/mcp_bridge.py` | **Medium** | 17 | **DONE** -- connection, discovery, schema conversion, execution, graceful degradation |

**Phase 0 gate: PASSED.** Phase 1 gate: PASSED. All critical modules have regression tests protecting them.

### 7.2 Confabulation Surface in Generic Tools (Mitigated)

The confabulation guard detects when the LLM claims it performed a device action without making tool calls. With generic tools, a confabulation vector exists: the LLM constructs a plausible-looking `do()` call with **invented parameters** that the HA API silently ignores.

Example: `do("light", "turn_on", {"entity_id": "light.kitchen"}, {"mood": "romantic"})` -- HA ignores the unknown `mood` field, turns on the light at default settings, and the AI reports success. The user thinks "romantic mode" was applied.

**Mitigations (implemented):**
- **Schema validation in `do()`**: Before executing, `do()` diffs the requested `data` keys against the cached service schema for `{domain}.{service}`. Unknown keys are flagged in the response: "Warning: field 'mood' is not a known parameter for light.turn_on -- it will be ignored by HA."
- **Post-action state verification**: `verify_generic()` in `tools/generic.py` reads back entity state after execution and includes domain-aware attribute formatting, making discrepancies visible.
- **Audit trail**: Every `do()` call is logged via `memory/audit_store.py` with full request + response for post-incident review.

### 7.3 Conversation Loop Token Budget

The system prompt is rebuilt every turn and includes: persona, time context, 10 conversation turns, semantic facts (up to 20), presence summary, device summary, calendar, proactive hints, action trace, and service schemas. This is a lot of context competing for a finite token window.

**Current estimated per-turn context:**

| Section | Est. Tokens |
|---------|-------------|
| Persona + rules | ~800 |
| Time + presence + calendar | ~300 |
| 10 conversation turns | ~1,500-3,000 |
| Semantic facts (20 max) | ~600 |
| Device summary | ~500-2,000 |
| Service schemas (top-5 domains) | ~800-1,200 |
| Tool definitions (6 primary) | ~400 |
| **Total** | **~4,900-8,300** |

With a 2,000-token `max_tokens` for the response, this fits within most model context windows but leaves limited room for long tool-calling loops (max 15 iterations, each adding tool call + result tokens). Monitor total token usage per turn and set alerts for when it approaches 80% of the model's context limit.

**Schema injection strategy (implemented):**

1. **Top-5 domain schemas injected every turn** (light, climate, cover, fan, switch -- the domains used in >80% of commands). Costs ~800-1,200 tokens.
2. **On-demand for everything else.** The LLM calls `discover(what="services", filter="vacuum")` before calling `do()` for unfamiliar domains. One extra tool call per novel domain is a good trade for ~3,000 tokens saved per turn.
3. **Token count logged at startup.** If the full schema exceeds `MAX_SCHEMA_TOKENS` (default: 1500), on-demand mode is used for long-tail domains.
4. **Hourly cache.** Schemas are cached in memory and refreshed on a 1-hour interval.

### 7.4 SQLite Under Concurrent Load

Both the conversation store and knowledge store use SQLite with `aiosqlite`. SQLite handles concurrent reads well but serializes writes. With webhooks, background fact extraction, and user conversations all writing simultaneously, write contention could cause latency spikes or `database is locked` errors under load.

**Status: RESOLVED.** WAL mode and busy_timeout are now enabled on all stores (including `audit_store.py`):

```python
# conversation_store.py, knowledge_store.py, and audit_store.py initialize():
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

**Mitigations (recommended for Phase 2):**

1. **Batch window (highest priority).** Buffer incoming webhooks for 2 seconds before processing. If multiple events arrive within the window, group them into a single AI prompt: "Multiple changes detected: kitchen light off, living room light off, bedroom light off." This converts 20 simultaneous AI calls into 1. Implementation: an `asyncio` debounce queue keyed on a global "batch slot" that flushes every 2 seconds.

2. **Self-action filter.** Track every `do()` call with a timestamp and entity_id in a short-lived set (TTL: 10 seconds). When a webhook arrives, check if the entity was recently acted on by Apex itself. If so, suppress the webhook. This breaks the cascading automation feedback loop.

3. **Global rate limit.** Cap webhook-triggered AI conversations at 5 per minute, regardless of entity. Events that exceed the limit are queued and batched into the next available slot. This is the safety net that catches anything the batch window and self-action filter miss.

### 7.6 Phase Dependency Chain

The ROADMAP phases are not independent -- each phase depends on the one before it being solid:

```
Phase 0 (Stabilize)     -- COMPLETE
  └──► Phase 1 (Generic Tools + MCP Bridge) -- COMPLETE
        └──► Phase 1.5 (Live Deployment)    -- validate everything against real HA + MCP server
              └──► Phase 2 (System Intelligence) -- needs generic do()/query() to act autonomously
                    │                               + MCP multi-server + legacy wrapper removal
                    └──► Phase 3 (Proactive)     -- persistent MCP subscriptions for real-time events
                          └──► Phase 4 (Voice)   -- proactive behavior drives most voice interactions
                                └──► Phase 5 (Multi-User) -- voice ID feeds into per-user routing
```

**Mitigation:** Treat phase boundaries as hard gates. A phase is not complete until:
1. All checklist items are checked in `ROADMAP.md`
2. All tests pass (`pytest` green)
3. Live HA validation confirms no regressions
4. The architecture doc is updated to reflect what was actually built (not just what was planned)

**Status:** Phase 0 is complete. Phase 1 is complete -- generic tools (`do`, `query`, `discover`, `history`), system management (`manage`, `configure`), WebSocket helpers (`ws_helpers`), audit logging (`audit_store`), and MCP Bridge (`mcp_bridge`) are all implemented with 423 tests passing. Phase 1.5 (Live Deployment) is next.

### 7.7 Operational Risk: System-Level Access via manage() and configure()

Giving the LLM system-level access to the HA instance (beyond device control) introduces a class of risk: **operational disruption from hallucinated or misinterpreted system commands.**

**Risk scenarios:**

| Risk | Trigger | Impact |
|------|---------|--------|
| **Unintended HA update** | Hallucinated `manage("update", "core")` | Triggers a core update + restart at a bad time. HA goes offline, automations stop, voice control lost. If the update introduces breaking changes, recovery requires manual intervention. |
| **Backup restore wipes state** | Hallucinated `manage("backup", "restore", config={"backup_id": "..."})` | Restores an old snapshot, destroying current state: entity customizations, recent automations, input helper values, and anything changed since the backup was taken. |
| **Critical entity disabled** | Hallucinated `configure("disable", "binary_sensor.smoke_detector_kitchen")` | Disables a safety sensor. HA automations that depend on it (fire alerts, alarms) stop working silently. The user may not notice until an actual event occurs. |
| **Device removal** | Hallucinated `configure("remove", device_id)` | Permanently removes a device and all its entities. Re-adding requires reconfiguration and may break automations that referenced those entities. |
| **Add-on misconfiguration** | `manage("install", "addon:some_slug", config={...})` with wrong config | Installs or reconfigures an add-on with incorrect settings. Could expose ports, change network settings, or break other add-ons. |

**Mitigations (all implemented in Phase 1):**

1. **Tiered confirmation system.** Operations are classified into three tiers in `tools/manage.py` and `tools/configure.py`:

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

2. **Audit logging** in `memory/audit_store.py`. Every `manage()` and `configure()` call is logged to a dedicated audit table in SQLite (WAL mode):

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

   9 tests in `tests/test_audit_store.py` cover audit logging.

3. **Dry-run mode for configure().** All `configure()` operations support a `dry_run` flag (via `data={"dry_run": true}`) that returns what *would* change without applying it. The LLM calls dry-run first for Tier 1+ operations and presents the preview to the user.

4. **Session-based escalation.** Webhook-triggered sessions (`session_id="apex_events"`) are restricted to Tier 0 operations only. The rationale: a state-change event should never autonomously trigger a system update or entity disable. Only direct user conversations (voice or chat) can escalate to Tier 1 and Tier 2.

**Test coverage:** 53 tests in `tests/test_manage.py` + 49 tests in `tests/test_configure.py` cover all tiered confirmation paths, dry-run mode, session-based escalation, and error handling.

---

## Appendix: Tool Inventory

Complete list of all registered `@tool` functions as of v0.7.0, organized by status and module.

### PHASE 1 GENERIC TOOLS (Primary)

These are the tools the LLM is instructed to use. They provide full coverage of HA device control, state reading, discovery, history, system management, and registry operations.

#### generic.py (4 tools -- 862 lines, 75 tests)
| Tool | Description |
|------|-------------|
| `do` | Universal service caller: any HA domain/service with automatic verification via `verify_generic()`. Schema validation flags unknown parameters. |
| `query` | Universal state reader: entity_id auto-detection or Jinja2 template evaluation. Domain-aware attribute formatting. Smart 404 fallback. |
| `discover` | Universal discovery: entities, services (with full schemas), areas, devices, integrations, HA info. Supports domain/keyword filtering. |
| `history` | State change history or logbook entries. Two modes: "changes" and "logbook". Deduplication, capped at 50 entries. |

#### manage.py (1 tool -- 53 tests)
| Tool | Description |
|------|-------------|
| `manage` | System management via Supervisor API: backups (create/list/restore/delete), updates (core/OS/addon), restarts, health, logs. Tiered confirmation: Tier 0 (safe, immediate), Tier 1 (disruptive, requires confirmation), Tier 2 (destructive, dry-run + summary). Session-based escalation blocks webhook sessions from Tier 1/2. |

#### configure.py (1 tool -- 49 tests)
| Tool | Description |
|------|-------------|
| `configure` | Registry operations via WebSocket API (`ws_helpers.py`): rename entities, assign areas, disable/enable entities, create/delete areas, remove devices, list stale entities. Tiered confirmation with dry-run mode for Tier 1+ operations. |

#### Support modules (no @tool)
| Module | Description |
|--------|-------------|
| `ws_helpers.py` | Transient WebSocket connections for HA registry operations (auth, send command, receive result, close). Used by `configure.py`. |
| `mcp_bridge.py` | MCP server integration (254 lines, 17 tests). Connects via SSE or Streamable HTTP, discovers remote tools, converts schemas to OpenAI format, routes execution from conversation loop. Graceful degradation if server unreachable. |
| `memory/audit_store.py` | SQLite WAL-mode audit log for all manage/configure calls (timestamp, tool, action, target, result, session). 9 tests. |

### LEGACY TOOLS [DEPRECATED]

These tools are thin wrappers that delegate to the generic tools above and emit deprecation warnings. They remain registered in `TOOL_REGISTRY` for backward compatibility. Full removal is deferred to Phase 2.

#### smart_home.py (14 tools) [DEPRECATED]
| Tool | Description | Delegates to |
|------|-------------|-------------|
| `list_entities` | List entities by domain | `discover(what="entities")` |
| `get_entity_state` | Get entity state + attributes | `query()` |
| `get_areas` | List all rooms/areas | `discover(what="areas")` |
| `query_sensors` | Query sensors by type/area | `query()` / `discover()` |
| `control_light` | Light control | `do("light", ...)` |
| `cycle_light_timed` | Blink a light N times | `do("light", ...)` loop |
| `control_climate` | Thermostat control | `do("climate", ...)` |
| `control_media` | Media player control | `do("media_player", ...)` |
| `control_cover` | Blinds/shades/garage | `do("cover", ...)` |
| `control_fan` | Fan control | `do("fan", ...)` |
| `control_area` | Area-wide control | `do()` with area_id target |
| `call_service` | Generic service call | `do()` |

#### automation.py (8 tools)
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

#### Other legacy modules [DEPRECATED]
| Module | Tool(s) | Delegates to |
|--------|---------|-------------|
| `lock.py` | `control_lock` | `do("lock", ...)` |
| `switch.py` | `control_switch` | `do("switch", ...)` / `do("input_boolean", ...)` |
| `security.py` | `control_alarm`, `get_camera_snapshot` | `do("alarm_control_panel", ...)` / `query()` |
| `energy.py` | `get_energy_entities`, `get_entity_power`, `get_energy_summary` | `discover()` / `query()` |
| `history.py` | `get_history`, `get_logbook` | `history()` |
| `template.py` | `evaluate_template` | `query()` with Jinja2 |
| `system_info.py` | `get_ha_info`, `list_devices`, `list_integrations`, `list_services` | `discover()` |
| `input_helpers.py` | `set_input_helper`, `list_input_helpers` | `do()` / `discover()` |
| `script.py` | `list_scripts`, `execute_script` | `discover()` / `do("script", ...)` |
| `config_reload.py` | `reload_config` | `do("homeassistant", "reload_all")` |
| `presence.py` | `get_presence` | `query()` / `discover()` |

### STANDALONE TOOLS (Unchanged)

These tools have no generic equivalent yet or are already clean single-purpose tools.

#### vacuum.py (2 tools)
| Tool | Description |
|------|-------------|
| `control_vacuum` | Vacuum actions: start, pause, stop, return_to_base, locate |
| `clean_rooms` | Send vacuum to clean specific rooms by name |

#### notify.py (2 tools)
| Tool | Description |
|------|-------------|
| `send_notification` | Send notification to a specific notify service target |
| `announce` | Voice announcement via Alexa or phone notification |

#### knowledge.py (3 tools)
| Tool | Description |
|------|-------------|
| `remember` | Store a fact the user explicitly asks to remember |
| `recall` | Search knowledge base by query |
| `forget` | Delete a remembered fact by key |

#### routines.py (4 tools)
| Tool | Description |
|------|-------------|
| `define_routine` | Create a named multi-step routine |
| `list_routines` | View all defined routines |
| `run_routine` | Execute a routine by name |
| `delete_routine` | Remove a routine |

#### calendar_tool.py (4 tools)
| Tool | Description |
|------|-------------|
| `get_today_schedule` | Today's calendar events |
| `get_upcoming_events` | Events in next N days |
| `create_event` | Create a calendar event |
| `delete_event` | Delete a calendar event |

#### Other standalone modules
| Module | Tool | Description |
|--------|------|-------------|
| `weather.py` | `get_weather` | Weather forecast (daily/hourly) |
| `datetime_tool.py` | `get_current_datetime` | Current date/time in configured timezone |
| `todo.py` | `manage_todo` | Shopping/todo list CRUD |
| `webhook.py` | `fire_webhook` + `fire_event` + `fire_custom_event` | Trigger webhooks and custom events |
| `wait_tool.py` | `wait_seconds` | Timed delay between tool calls |

**Total: ~68 registered native tools across 22 modules (6 primary + ~56 deprecated wrappers + ~6 standalone) + dynamic MCP tools from remote servers**
