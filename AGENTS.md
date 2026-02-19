# Apex Brain – Agent Instructions

- You are working on the Apex Brain add-on. See `README.md` for architecture, deployment, and conventions.
- For full rules (parallel execution, testing, "do it" mandate), see `CLAUDE.md`.
- Run tasks in parallel when possible; complete implementations end-to-end without asking for confirmation unless critical.
- Source code lives in `apex_brain/`; helper scripts in `scripts/`; docs in `docs/`.

## Token & Credential Rules (CRITICAL)

**Multiple AI sessions may be running concurrently against this project.** All sessions share the same `.env` file and the same `HA_TOKEN`. Follow these rules strictly:

1. **NEVER create, rotate, regenerate, or revoke** the Home Assistant long-lived access token (`HA_TOKEN`). The existing token in `.env` is shared across all concurrent sessions and must remain stable.
2. **NEVER modify `.env`** to change `HA_TOKEN`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or any other credential unless the user explicitly asks you to.
3. **NEVER call the Home Assistant API to create or delete long-lived access tokens** (e.g., `POST /auth/long_lived_access_token` or token revocation endpoints).
4. **Use the existing token as-is.** The token is loaded automatically by `brain/config.py` from the environment. Do not add token refresh, rotation, or renewal logic to the codebase.
5. If a token appears invalid or expired, **tell the user** rather than attempting to fix it yourself. The user will rotate it manually in HA (Profile > Security) and update `.env`.
6. The same rules apply to `SUPERVISOR_TOKEN` in the add-on runtime — it is managed by the HA Supervisor and must not be modified.
