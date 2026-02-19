# Phase 1 Agent Prompts

> Ready-to-use prompts for Claude Code / Cursor sessions.
> Run Prompt 1 first (small), then Prompts 2 and 3 in parallel, then Prompt 4 to integrate.

---

## Prompt 1: Finish Phase 0 (run first — small task)

```
You are working on the Apex Brain project. Read these docs before doing anything:
1. CLAUDE.md
2. docs/WORKFLOW.md
3. docs/ROADMAP.md
4. docs/ARCHITECTURE.md

Phase 0 has one remaining item: the vacuum tool needs to read entity names
from HA dynamically instead of having hardcoded entity names. Currently
apex_brain/tools/vacuum.py has hardcoded vacuum entity references that break
when vacuums are renamed or re-paired.

Fix it:
- Read tools/vacuum.py and tools/ha_helpers.py to understand the current pattern
- Make the vacuum tool discover vacuum entities dynamically (via list_entities
  or HA API call for vacuum domain) instead of assuming specific entity_id names
- Add/update tests in tests/test_vacuum.py with a regression test
- Run the full test suite: PYTHONPATH=apex_brain python -m pytest apex_brain/tests -v
- All tests must pass before you're done
- Mark the Phase 0 item as complete in docs/ROADMAP.md when done
```

---

## Prompt 2: Core Generic Tools — `do()`, `query()`, `discover()`, `history()`

> This is the big one. Can run in parallel with Prompt 3.

```
You are working on the Apex Brain project — Phase 1: Generic Tools Redesign.

MANDATORY FIRST STEP: Read these docs completely before writing any code:
1. CLAUDE.md (behavioral rules, parallel execution, testing requirements)
2. CONTRIBUTING.md (code conventions, commit format)
3. docs/WORKFLOW.md (3-phase process — you must follow it)
4. docs/ARCHITECTURE.md (CRITICAL — Section 3 has the full spec for every tool)
5. docs/ROADMAP.md (Phase 1 checklist — this is your task list)

SECOND STEP: Run the test suite to verify current state:
  PYTHONPATH=apex_brain python -m pytest apex_brain/tests -v
If any tests fail, fix them first.

THIRD STEP: Read the existing tool code to understand patterns:
- apex_brain/tools/base.py (@tool decorator, TOOL_REGISTRY, execute_tool)
- apex_brain/tools/ha_helpers.py (ha_request, call_ha_service, shared httpx client)
- apex_brain/tools/smart_home.py (existing tools you're replacing)
- apex_brain/brain/conversation.py (tool execution loop — understand how tools get called)

YOUR TASK: Implement the four core generic tools as specified in ARCHITECTURE.md
Section 3.3. Build them in this order because each builds on the previous:

1. **discover()** — Build first. It's read-only, low risk, and the other tools
   benefit from it. Create apex_brain/tools/generic.py (new file). The tool
   should handle: entities, services (with full schemas), areas, devices,
   integrations, info. Filter parameter narrows results. Use ha_helpers.py
   for all HA API calls. See ARCHITECTURE.md Section 3.3 for the full spec.

2. **query()** — Universal state reader + template evaluator. Detects whether
   the target is an entity_id (contains dot, no braces) or a Jinja2 template
   (contains {{ or {%). For entities: GET /api/states/{target}, return
   formatted state + key attributes. For templates: POST /api/template.
   Smart fallback if entity returns 404. See ARCHITECTURE.md Section 3.3.

3. **do()** — The universal service caller. This is the most important tool.
   POST /api/services/{domain}/{service} with targets + data. Wait 500ms,
   then read back entity state for verification using a generic _verify_action().
   IMPORTANT: Implement the security gate from ARCHITECTURE.md — sensitive
   domains (lock, alarm_control_panel, camera, cover) return a confirmation
   prompt instead of executing immediately. See ARCHITECTURE.md Section 3.3.

4. **history()** — State history + logbook. Two modes: "changes"
   (GET /api/history/period) and "logbook" (GET /api/logbook). Both accept
   entity_id filter and hours parameter. See ARCHITECTURE.md Section 3.3.

TESTING REQUIREMENTS (non-negotiable):
- Create apex_brain/tests/test_generic.py
- Every tool function needs tests: normal operation, edge cases, error handling
- Mock HA API calls (do NOT make real API calls in unit tests)
- Follow the mocking patterns from existing tests (test_smart_home.py, test_conversation.py)
- Run the full test suite after implementation — ALL tests must pass (old and new)

IMPORTANT RULES:
- All HA API calls go through ha_helpers.py. Never use httpx directly.
- Do NOT modify or delete any existing tool files yet. The old tools stay
  as-is during migration. generic.py is additive.
- Do NOT modify conversation.py or base.py unless absolutely necessary.
  The existing tool dispatch should work with new tools automatically via
  the @tool decorator and auto-discovery.
- Config from environment only, via brain/config.py.
- Async functions for all HA interactions. Type hints on all signatures.

When done, show me: test results (pass/fail counts), which files were
created/modified, and a summary of what each tool can do.
```

---

## Prompt 3: Ops Tools — `manage()`, `configure()`, WebSocket helper

> Can run in parallel with Prompt 2 (different files).

```
You are working on the Apex Brain project — Phase 1: System Management Tools.

MANDATORY FIRST STEP: Read these docs completely before writing any code:
1. CLAUDE.md (behavioral rules, parallel execution, testing requirements)
2. CONTRIBUTING.md (code conventions)
3. docs/WORKFLOW.md (3-phase process)
4. docs/ARCHITECTURE.md (Section 3.3 for manage() and configure() specs,
   Section 3.5 for WebSocket API requirements, Section 7.7 for security risks)
5. docs/ROADMAP.md (Phase 1 checklist)

SECOND STEP: Run the test suite to confirm clean baseline:
  PYTHONPATH=apex_brain python -m pytest apex_brain/tests -v

THIRD STEP: Read existing code:
- apex_brain/tools/base.py (tool registration)
- apex_brain/tools/ha_helpers.py (HA API patterns — you'll extend this)
- apex_brain/brain/config.py (settings, SUPERVISOR_TOKEN resolution)

YOUR TASK: Build the system management layer — three pieces:

1. **WebSocket API helper** — Add to ha_helpers.py (or a new ws_helpers.py
   if it's cleaner). Implement a transient WebSocket connection pattern:
   open connection, authenticate with SUPERVISOR_TOKEN, send command, receive
   result, close. See ARCHITECTURE.md Section 3.5 for the exact pattern.
   Use aiohttp for WebSocket (it's already available or add to requirements.txt).
   Handle: auth failure, timeout, connection refused.
   In local dev mode (no SUPERVISOR_TOKEN), return a clear error message.

2. **manage()** — Create apex_brain/tools/manage.py. Supervisor API operations:
   backup (create/list/restore/delete), update (core/os/addon), restart
   (core/addon/supervisor), install (addon), health (system stats), logs.
   All calls go to http://supervisor/<endpoint> with SUPERVISOR_TOKEN.
   CRITICAL: Implement the tiered confirmation system from ARCHITECTURE.md
   Section 7.7. Safe operations (backup/create, backup/list, health, logs)
   execute immediately. Destructive operations (backup/restore, update/*,
   restart/*) return a confirmation string instead of executing.
   See ARCHITECTURE.md Section 3.3 for the full routing table.

3. **configure()** — Create apex_brain/tools/configure.py. Registry operations
   via WebSocket API: rename, assign_area, disable, enable, create_area,
   delete_area, remove, list_stale. Uses the ws_command() helper from step 1.
   Implement dry-run mode for destructive operations.
   See ARCHITECTURE.md Section 3.3 for the full spec.

4. **Audit logging** — Create a system_audit_log table in the SQLite database.
   Log every manage() and configure() call with: timestamp, tool, action,
   target, config_json, result, session_id, user_approved. Add this to
   the existing database initialization in memory/conversation_store.py or
   create a new audit_store.py module. See ARCHITECTURE.md Section 7.7.

TESTING REQUIREMENTS:
- Create apex_brain/tests/test_manage.py and apex_brain/tests/test_configure.py
- Mock all Supervisor API and WebSocket calls
- Test the tiered confirmation system: verify safe ops execute, destructive ops
  return confirmation prompts
- Test audit logging: verify every call gets logged
- Test error handling: Supervisor unavailable, WS auth failure, timeout
- Run full suite — all tests must pass

IMPORTANT:
- NEVER make real Supervisor API calls during development/testing
- NEVER actually create backups, trigger updates, or restart anything
- The confirmation system is a HARD REQUIREMENT — not optional
- Session-based escalation: webhook sessions (session_id="apex_events")
  are restricted to Tier 0 (safe) operations only
```

---

## Prompt 4: Integration — schema injection, migration, system prompt

> Run AFTER Prompts 2 and 3 are both complete.

```
You are working on the Apex Brain project — Phase 1 integration and migration.

MANDATORY FIRST STEP: Read these docs:
1. CLAUDE.md
2. docs/ARCHITECTURE.md (Section 3.4 schema injection, 3.8 migration path)
3. docs/ROADMAP.md

SECOND STEP: Run tests to verify current state:
  PYTHONPATH=apex_brain python -m pytest apex_brain/tests -v

THIRD STEP: Read the files that were created in earlier sessions:
- apex_brain/tools/generic.py (do, query, discover, history)
- apex_brain/tools/manage.py (manage)
- apex_brain/tools/configure.py (configure)
- apex_brain/brain/system_prompt.py (current system prompt)
- apex_brain/brain/conversation.py (orchestrator)

YOUR TASK: Wire everything together. Four pieces:

1. **Service schema injection into system prompt.** Modify system_prompt.py
   to fetch and inject HA service schemas. Strategy from ARCHITECTURE.md
   Section 3.4: inject top-5 domain schemas (light, climate, cover, fan,
   switch) into every prompt (~800-1200 tokens). For all other domains,
   the LLM uses discover(what="services", filter="domain") on demand.
   Cache schemas in memory, refresh every hour. Measure token count at
   startup and log it.

2. **Old tools as deprecated aliases.** DO NOT delete any existing tool files.
   Instead, make the old tools thin wrappers that call the new generic tools.
   For example, control_light() should internally call do("light", ...).
   This ensures backward compatibility during migration. Add a deprecation
   log warning when old tools are called.

3. **Update the system prompt instructions.** The system prompt currently has
   per-tool usage guides for 60+ tools. Add a new section that teaches the
   LLM to prefer the generic tools (do, query, discover, history, manage,
   configure, notify) and explains the patterns:
   - Use discover() to find entities/services before acting
   - Use do() for any device control
   - Use query() for any state read
   - Use manage() for system operations (with confirmation awareness)
   - Use configure() for registry organization
   Keep the old tool instructions but mark them as legacy.

4. **End-to-end integration test.** Create apex_brain/tests/test_integration.py
   that tests the full flow: a user message comes in, the orchestrator builds
   context (including schemas), calls the LLM (mocked), the LLM returns a
   tool call for do(), the tool executes against HA (mocked), and the result
   comes back. This proves the whole pipeline works with the new tools.

5. **Update ROADMAP.md** — check off completed Phase 1 items.

Run the full test suite. All tests must pass. Show me the results.
```

---

## Execution Order

```
Prompt 1 (Phase 0 cleanup)     ──► small, run first, ~15 min
        │
        ▼
Prompt 2 (Core tools)          ──┐
                                  ├──► run in PARALLEL, ~45-60 min each
Prompt 3 (Ops tools)           ──┘
        │
        ▼
Prompt 4 (Integration)         ──► run after 2+3 complete, ~30 min
```

*Created: 2026-02-18*
