Before starting any work, complete this preflight checklist:

1. Read `CLAUDE.md` fully — confirm you understand the token rules, parallel execution mandate, and testing requirements.
2. Read `docs/WORKFLOW.md` — confirm you understand the 3-phase process (Evaluate → Implement → Validate).
3. Read `docs/ROADMAP.md` — identify the current phase and priorities.
4. Run `PYTHONPATH=apex_brain python -m pytest apex_brain/tests -v --tb=short` to establish a baseline of passing tests.
5. Report: (a) current test pass/fail count, (b) which roadmap items are next, (c) any blockers you see.

Do NOT begin any code changes until this checklist is complete.
