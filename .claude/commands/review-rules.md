Review the current codebase for rule violations. Check:

1. **No hardcoded secrets** — Grep for patterns like API keys, tokens, passwords in source files (not `.env` or `.env.example`).
2. **All functions have tests** — Cross-reference `apex_brain/` modules with `apex_brain/tests/` to find untested functions.
3. **No direct credential manipulation** — Ensure no code creates, rotates, or revokes HA tokens.
4. **Config reads from environment only** — Verify all config values flow through `apex_brain/config.py`, not inline `os.getenv()` calls scattered through the code.
5. **Import hygiene** — Check for unused imports or circular dependencies.

Report findings as a checklist with pass/fail for each item.
