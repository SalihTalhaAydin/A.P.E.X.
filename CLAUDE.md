# Apex Brain – Claude Code Instructions

## Project Overview
- You are working on the **Apex Brain** Home Assistant add-on. See `README.md` for architecture, deployment, and conventions.
- Source code lives in `apex_brain/`; helper scripts in `scripts/`; docs in `docs/`.
- Run tasks in parallel when possible; complete implementations end-to-end without asking for confirmation unless critical.

## Token & Credential Rules (CRITICAL)

**Multiple Claude sessions may be running concurrently against this project.** All sessions share the same `.env` file and the same `HA_TOKEN`. Follow these rules strictly:

1. **NEVER create, rotate, regenerate, or revoke** the Home Assistant long-lived access token (`HA_TOKEN`). The existing token in `.env` is shared across all concurrent sessions and must remain stable.
2. **NEVER modify `.env`** to change `HA_TOKEN`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or any other credential unless the user explicitly asks you to.
3. **NEVER call the Home Assistant API to create or delete long-lived access tokens** (e.g., `POST /auth/long_lived_access_token` or token revocation endpoints).
4. **Use the existing token as-is.** The token is loaded automatically by `brain/config.py` from the environment. Do not add token refresh, rotation, or renewal logic to the codebase.
5. If a token appears invalid or expired, **tell the user** rather than attempting to fix it yourself. The user will rotate it manually in HA (Profile > Security) and update `.env`.
6. The same rules apply to `SUPERVISOR_TOKEN` in the add-on runtime — it is managed by the HA Supervisor and must not be modified.

## Parallel-First Execution (MANDATORY)

**Every task MUST be parallelized by default.** This is not optional — it is the standard operating mode for this project.

### Rules
1. **Always decompose work into parallel sub-agents.** Before writing any code, break the task into independent units and spawn them simultaneously using the Task tool. Even seemingly "small" tasks should be evaluated for parallelization.
2. **Minimum parallel agents: 3.** For any non-trivial task, spawn at least 3 sub-agents. For larger tasks (features, refactors, multi-file changes), use 4–6 agents.
3. **Agent roles to consider for every task:**
   - **Explore agent** — research the codebase, find relevant files, understand patterns
   - **Implement agent(s)** — write the actual code changes (split by module/file)
   - **Test agent** — write or run tests for the changes
   - **Validate agent** — lint, type-check, or verify the changes work
4. **Run independent work in parallel, dependent work sequentially.** If agents don't depend on each other's output, they run at the same time. Only serialize when one agent needs another's result.
5. **Background agents for long-running tasks.** Use `run_in_background: true` for tasks like test suites or builds, and continue other work while they run.
6. **Coordinate via files, not conversation.** Agents working on the same feature should read/write to the actual source files. The orchestrating agent (you) merges and resolves conflicts.
7. **Never do sequentially what can be done in parallel.** If you catch yourself doing steps one-by-one that could be concurrent, stop and restructure.

### Example Decomposition
For a task like "add a new API endpoint":
- Agent 1 (Explore): Find existing endpoint patterns, router setup, middleware
- Agent 2 (Implement): Write the endpoint handler and route registration
- Agent 3 (Implement): Write the data model / service layer changes
- Agent 4 (Test): Write tests for the new endpoint
- Agent 5 (Validate): Run linting and existing tests to check for regressions

All 5 launch simultaneously. Agents 2–4 use Agent 1's findings if needed (Agent 1 runs as Explore type which is fast).

## Coding Conventions
- No hardcoded secrets or tokens anywhere in source code — only read from environment via `config.py`.
- See `.env.example` for the full list of configuration variables.
