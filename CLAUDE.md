# Apex Brain – Claude Code Instructions

## Project Overview
- You are working on the **Apex Brain** Home Assistant add-on. See `README.md` for architecture, deployment, and conventions.
- Source code lives in `apex_brain/`; helper scripts in `scripts/`; docs in `docs/`.
- Complete implementations end-to-end without asking for confirmation unless critical.

## Token & Credential Rules (CRITICAL)

**Multiple Claude sessions may be running concurrently against this project.** All sessions share the same `.env` file and the same `HA_TOKEN`. Follow these rules strictly:

1. **NEVER create, rotate, regenerate, or revoke** the Home Assistant long-lived access token (`HA_TOKEN`). The existing token in `.env` is shared across all concurrent sessions and must remain stable.
2. **NEVER modify `.env`** to change `HA_TOKEN`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or any other credential unless the user explicitly asks you to.
3. **NEVER call the Home Assistant API to create or delete long-lived access tokens** (e.g., `POST /auth/long_lived_access_token` or token revocation endpoints).
4. **Use the existing token as-is.** The token is loaded automatically by `brain/config.py` from the environment. Do not add token refresh, rotation, or renewal logic to the codebase.
5. If a token appears invalid or expired, **tell the user** rather than attempting to fix it yourself. The user will rotate it manually in HA (Profile > Security) and update `.env`.
6. The same rules apply to `SUPERVISOR_TOKEN` in the add-on runtime — it is managed by the HA Supervisor and must not be modified.

## Automatic Execution for Home Assistant Tasks (MANDATORY)

When the user says **"go do it"**, **"do it"**, **"make it happen"**, or any similar short directive for Home Assistant-related work, **act autonomously and completely** without asking which tools or methods to use. This means:

1. **Automatically use the HA API** (REST calls via the existing `HA_TOKEN`) to read state, call services, create automations, configure entities, or perform any needed operations.
2. **Automatically use browser/web capabilities** when needed to fetch documentation, look up integration details, or verify configurations.
3. **Do not ask** "should I use the API?" or "should I use the browser?" — just pick the right approach and execute.
4. **Complete the task end-to-end.** Do not stop halfway and ask for confirmation unless there is a genuinely destructive or irreversible action (e.g., deleting an automation the user didn't mention).
5. **Assume intent from context.** If the user has been discussing a specific HA entity, automation, or integration, a bare "do it" means execute the most recently discussed action against HA.

## Mandatory Testing on Every Change (CRITICAL)

**No change is considered complete without testing.** This applies to every code change, feature, bug fix, and refactor — no exceptions.

### Two-Layer Testing Requirement
Every change MUST pass both layers before it is marked done:

1. **Unit Tests (Layer 1)**
   - Write or update unit tests for every code change.
   - Tests live alongside the code they test (e.g., `tests/` directory mirroring `apex_brain/`).
   - Run the full test suite after every change: `pytest tests/` (or the project's test command).
   - All tests must pass. If any test fails, fix the code or the test before moving on.
   - New features require new test cases. Bug fixes require a regression test that would have caught the bug.

2. **Live Home Assistant Validation (Layer 2)**
   - After unit tests pass, validate the change against the running Home Assistant instance.
   - For API/service changes: make real API calls to HA and verify the response.
   - For automation/entity changes: confirm the entity/automation exists and behaves correctly in HA.
   - For tool/capability changes: invoke the tool against HA and verify the output.
   - Log or report the validation result so the user can see proof it works.

### Agent Test Restriction (CRITICAL)
When running tests after a code change, run only the free suite:
- Use: `pytest` or `pytest apex_brain/tests/unit apex_brain/tests/model` (no extra args)
- NEVER run: `pytest apex_brain/tests/paid` or any path including `paid/`
- NEVER set `RUN_PAID_TESTS=1` or any env var to run paid tests
- Paid tests consume API credits; only the user runs those manually before release.

### Testing Rules
- **Tests run automatically** — do not ask the user "should I run tests?" Just run them.
- **If tests fail, fix and re-run.** Do not report a task as complete with failing tests.
- **Test results must be visible.** Always show the user test output (pass/fail counts, any errors).

## Required Reading (MANDATORY — First Action of Every Session)

Before writing any code, you MUST read and internalize these documents:

1. **This file** (`CLAUDE.md`) — You're reading it now. Contains all behavioral rules.
2. **`CONTRIBUTING.md`** — Universal contributor rules (applies to all agents and humans).
3. **`docs/WORKFLOW.md`** — The 3-phase process: Evaluate → Implement → Validate. No phase may be skipped.
4. **`docs/ROADMAP.md`** — Single source of truth for priorities. Do not work outside the current phase.
5. **`docs/ARCHITECTURE.md`** — System design. Understand the structure before modifying it.

### Available Commands
Run these with `/project:command-name` at any time:
- `/project:preflight` — Run the full preflight checklist before starting work.
- `/project:validate` — Run lint, format, tests, and secret scanning.
- `/project:review-rules` — Audit the codebase for rule violations.

## Coding Conventions
- No hardcoded secrets or tokens anywhere in source code — only read from environment via `config.py`.
- See `.env.example` for the full list of configuration variables.
