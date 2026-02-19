# Apex Brain -- Development Workflow

## Purpose

This document defines how ALL work gets done on the Apex Brain project. Every AI session, every feature, every bug fix follows the same 3-phase iterative process. This consistency is critical because multiple AI sessions work on this project concurrently and must operate in a predictable, coordinated way.

Read this document before writing any code.

---

## The Three Phases

Every piece of work follows this cycle without exception:

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  PHASE 1    │     │  PHASE 2    │     │  PHASE 3    │
│  EVALUATE   │ ──► │  IMPLEMENT  │ ──► │  VALIDATE   │
│             │     │             │     │             │
│ Where are   │     │ Build it    │     │ Break it    │
│ we? What's  │     │ with multi- │     │ Test it     │
│ next?       │     │ ple agents  │     │ Verify it   │
└─────────────┘     └─────────────┘     └─────────────┘
       ▲                                       │
       └───────────────────────────────────────┘
                    ITERATE
```

Work is never "done" after Phase 2. Implementation without validation is incomplete. If Phase 3 reveals problems, cycle back to Phase 2 and fix them. Only after Phase 3 passes cleanly do you move to the next item from the ROADMAP.

---

## Phase 1: EVALUATE

**Goal:** Understand the current state of the project and decide what to build next.

Before ANY implementation work, complete every step below:

1. **Run the full test suite.**
   ```bash
   pytest apex_brain/tests/ -v
   ```
   Record the results. If tests are already failing, that is the first thing to fix -- not new feature work.

2. **Check test results and coverage.**
   Note how many tests pass, how many fail, and which modules have gaps. This informs where to focus testing effort.

3. **Review the ROADMAP.**
   Read `docs/ROADMAP.md` to see the prioritized backlog. The ROADMAP is the single source of truth for what to build next. Do not invent work that is not on the ROADMAP unless the user explicitly requests it.

4. **Read the relevant source files.**
   Understand the current state of the code you are about to change. Read the module, its tests, and any files it depends on. Do not guess at how things work -- read and verify.

5. **Identify the specific items to implement this session.**
   Pick the next unchecked item(s) from the ROADMAP. Scope the work to what can be completed and validated in a single session.

6. **Document the plan before coding.**
   Write down: what will be implemented, which files will change, and what the expected test coverage looks like.

**Phase 1 Output:** A clear list of what will be implemented and which files will change. This list guides Phase 2.

---

## Phase 2: IMPLEMENT

**Goal:** Build the feature, fix the bug, or make the change -- using parallel agents.

### Agent Decomposition

Every task is broken into parallel sub-agents. Minimum 3 agents per task. For larger tasks, use 4-6 agents.

| Agent Role | Responsibility |
|---|---|
| **Explore Agent** | Research the codebase, find patterns, understand dependencies, locate relevant files |
| **Implement Agent(s)** | Write the actual code changes, split by module or file when multiple areas change |
| **Test Agent** | Write tests alongside the implementation -- not after, alongside |

### Execution Rules

- **Parallel by default.** Independent agents launch simultaneously. Only serialize when one agent genuinely needs another's output.
- **Coordinate via files.** Agents read and write to actual source files. The orchestrating agent merges and resolves conflicts. No coordination through conversation.
- **Follow existing patterns.** Before writing new code, the Explore Agent identifies how similar things are done elsewhere in the codebase. New code matches those patterns.
- **Every new function needs a test.** No exceptions. If you add a function, you add a test for it.
- **Every bug fix needs a regression test.** The test must fail without the fix and pass with it. This prevents the bug from returning.
- **No partial implementations.** Complete the feature end-to-end. Half-built features break the project for the next session.

### Example: Adding a New Tool

```
Agent 1 (Explore):  Find existing tool patterns in tools/, read base.py,
                    understand how tools register and get called
Agent 2 (Implement): Write the new tool in tools/new_tool.py following
                    the patterns Agent 1 found
Agent 3 (Implement): Update any integration points (tool registration,
                    imports, system prompt if needed)
Agent 4 (Test):     Write tests in tests/test_new_tool.py covering
                    normal operation, edge cases, and error handling
```

Agents 1-4 launch simultaneously. Agents 2-4 use Agent 1's findings if needed (Explore agents are fast and return first).

---

## Phase 3: VALIDATE

**Goal:** Prove the implementation works. Break it, test it, verify it against reality.

### Validation Agents

| Agent Role | Responsibility |
|---|---|
| **Test Runner Agent** | Runs the full test suite, reports pass/fail counts and any errors |
| **Breaker Agent** | Tries edge cases, unexpected inputs, error scenarios, boundary conditions |
| **Live Validation Agent** | Tests against the real Home Assistant instance with actual API calls |

### Validation Steps

1. **Run the full test suite.**
   ```bash
   pytest apex_brain/tests/ -v
   ```
   Every test must pass. Not most tests -- every test.

2. **Try to break it.**
   The Breaker Agent feeds edge cases into the new code: empty inputs, missing entities, network errors, malformed data, None values, concurrent calls. If it breaks, go back to Phase 2.

3. **Validate against live Home Assistant.**
   Make real API calls to the running HA instance. Verify:
   - For API/service changes: the response is correct and the state changes as expected.
   - For automation/entity changes: the automation or entity exists and behaves correctly.
   - For tool/capability changes: invoke the tool and verify the output matches expectations.

4. **Document the results.**
   Report to the user: how many tests pass, what was validated live, and what the coverage delta is. The user should see proof that the change works.

### Validation Rules

- **ALL tests must pass** before marking work complete. No exceptions, no "known failures."
- **If tests fail, return to Phase 2.** Fix the code or the test, then run Phase 3 again. This cycle repeats until everything passes.
- **Live validation is not optional.** Unit tests prove the logic is correct in isolation. Live validation proves it works in the real environment.
- **Never skip Phase 3.** A feature that is not validated is not done. Do not report completion without validation results.

---

## Starting a New Session

> **Project status (as of 2026-02-18):** ROADMAP Phase 0 and Phase 1 are complete. The test suite contains 423 tests. See `docs/ROADMAP.md` for current priorities.

When a new AI session begins working on this project, follow this exact sequence:

1. **Read `docs/VISION.md`** -- understand what we are building and why. The Jarvis standard defines the quality bar.
2. **Read `docs/ROADMAP.md`** -- see the prioritized backlog and find what is next.
3. **Read `docs/ARCHITECTURE.md`** -- understand the system structure, data flow, and design decisions.
4. **Run `pytest apex_brain/tests/ -v`** -- verify the current state of the codebase (expect 423+ tests). If tests fail, fixing them is the first priority.
5. **Pick the next unchecked item from ROADMAP.md** -- this is your task for the session.
6. **Follow the 3-phase cycle** -- Evaluate, Implement, Validate. No shortcuts.

Do not skip steps 1-3 even if you think you already know the project. The docs may have changed since your last session. Another session may have made changes you are not aware of.

---

## Code Conventions

These conventions are non-negotiable. All code in this project follows them.

### Tool Development
- All tools use the `@tool` decorator from `tools/base.py`.
- All Home Assistant API calls go through `ha_helpers.py`. Never use httpx directly for HA calls.
- Config comes from environment variables only, loaded through `brain/config.py`.

### Security
- No hardcoded secrets anywhere in source code.
- No hardcoded entity IDs. Entity IDs are looked up dynamically or passed as parameters.
- Never create, rotate, or modify tokens. See `CLAUDE.md` for the full token policy.

### Code Style
- Async functions for all Home Assistant interactions.
- Type hints on all function signatures.
- Docstrings on all public functions.
- Tests in `apex_brain/tests/test_<module>.py`, mirroring the source structure.

### Naming
- Snake case for functions and variables: `get_device_state`, `entity_id`.
- Pascal case for classes: `ConversationStore`, `EventHandler`.
- Constants in upper snake case: `DEFAULT_MODEL`, `HA_BASE_URL`.

---

## Commit Conventions

Every commit message starts with a type prefix. Use the correct one:

| Prefix | When to Use |
|---|---|
| `feat:` | New feature or capability |
| `fix:` | Bug fix |
| `refactor:` | Code restructuring with no behavior change |
| `test:` | Adding or updating tests only |
| `docs:` | Documentation changes only |
| `chore:` | Build configuration, dependencies, tooling |

Examples:
```
feat: add weather tool with forecast and current conditions
fix: handle missing entity_id in smart_home get_state
refactor: extract HA auth logic into shared helper
test: add edge case coverage for vacuum tool commands
docs: add voice pipeline research notes
chore: bump anthropic SDK to 0.35.0
```

Keep the first line under 72 characters. Add a blank line and a body paragraph for complex changes.

---

## File Organization

```
apex_brain/
├── brain/
│   ├── config.py              # Environment config (single source of truth)
│   ├── event_handler.py       # Webhook and event processing
│   └── system_prompt.py       # LLM system prompt construction
├── memory/
│   └── conversation_store.py  # Conversation history management
├── tools/
│   ├── base.py                # @tool decorator and tool registry
│   ├── ha_helpers.py          # All HA API calls go through here
│   ├── smart_home.py          # Device control and state queries
│   ├── vacuum.py              # Vacuum-specific commands
│   ├── calendar_tool.py       # Calendar integration
│   ├── datetime_tool.py       # Date and time utilities
│   ├── notify.py              # Notification services
│   └── script.py              # HA script execution
├── tests/
│   ├── test_config.py
│   ├── test_smart_home.py
│   ├── test_vacuum.py
│   ├── test_webhook.py
│   ├── test_ha_helpers.py
│   └── ...                    # One test file per module
docs/
├── VISION.md                  # Product vision and Jarvis standards
├── ARCHITECTURE.md            # System architecture and design decisions
├── ROADMAP.md                 # Prioritized backlog (SINGLE SOURCE OF TRUTH)
├── WORKFLOW.md                # This file -- how we work
└── VOICE_PIPELINE.md          # Voice pipeline research and design
```

---

## Quick Reference

For any session, the workflow reduces to this:

```
1. Read the docs (VISION, ROADMAP, ARCHITECTURE)
2. Run tests to verify current state
3. Pick the next ROADMAP item
4. EVALUATE  --> understand what needs to change
5. IMPLEMENT --> build it with parallel agents
6. VALIDATE  --> prove it works (tests + live HA)
7. If validation fails, go to step 5
8. If validation passes, commit and move to the next item
```

This cycle repeats until the session ends or the ROADMAP section is complete. Every session leaves the project in a better state than it found it, with all tests passing.
