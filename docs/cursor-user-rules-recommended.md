# User-level rules (not under APEX)

The **canonical** user-level rules live at **user level**, not in this repo:

- **Path**: `%USERPROFILE%\.cursor\cursor-user-rules-recommended.md` (Windows) or `~/.cursor/cursor-user-rules-recommended.md` (Mac/Linux)
- That file is your single source of truth for Cursor User Rules. Copy its contents into **Cursor Settings → Rules (User Rules)** so they apply to every workspace.

This repo only references that location. APEX-specific rules stay in this project (`.cursor/rules/`, `AGENTS.md`).

If the user-level file is missing, you can recreate it from the template in the Cursor docs or from the create-rule skill. The template covers: orchestration (parallel, hands-off), auto-rule creation (no repeat), and minimal friction.
