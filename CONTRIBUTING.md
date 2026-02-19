# Contributing to Apex Brain

This document applies to **all contributors** — human and AI agents alike.

## Non-Negotiable Rules

### 1. Never Touch Credentials
- **Do not** create, rotate, regenerate, or revoke any token (`HA_TOKEN`, `SUPERVISOR_TOKEN`, API keys).
- **Do not** modify `.env` to change credentials unless the project owner explicitly requests it.
- All secrets are loaded from the environment via `apex_brain/config.py`. Do not add inline `os.getenv()` calls elsewhere.

### 2. Every Change Gets Tests
- No PR is accepted without accompanying tests.
- New features require new test cases.
- Bug fixes require a regression test that would have caught the bug.
- Run the full suite before submitting: `PYTHONPATH=apex_brain python -m pytest apex_brain/tests -v --tb=short`
- All tests must pass. Zero exceptions.

### 3. Lint and Format
- Run `ruff check apex_brain scripts` — fix all errors.
- Run `ruff format apex_brain scripts` — apply standard formatting.
- Pre-commit hooks enforce this locally. CI enforces it on push.

### 4. Follow the Roadmap
- Check `docs/ROADMAP.md` before starting work.
- Do not implement features outside the current phase unless discussed with the project owner.

### 5. Follow the Workflow
- Read `docs/WORKFLOW.md` for the 3-phase process: Evaluate → Implement → Validate.
- No phase can be skipped.

## Code Conventions
- Python 3.12+, target syntax via `pyupgrade`.
- Line length: 75 characters (soft limit — E501 is ignored by ruff).
- Double quotes for strings.
- Import order enforced by `isort` (via ruff `I` rules).
- Tools are registered with the `@tool` decorator in `apex_brain/tools/`.

## Commit Messages
- Use conventional format: `type: short description`
- Types: `feat`, `fix`, `chore`, `docs`, `test`, `refactor`
- Examples:
  - `feat: add area-based device control tool`
  - `fix: handle empty calendar response gracefully`
  - `test: add regression test for vacuum dock sensor`
